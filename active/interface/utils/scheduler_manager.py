r"""
Gerenciador de Agendamentos com suporte a:
1. Múltiplas horas por agendamento (lista de strings "HH:MM")
2. Detecção de duplicatas (evita agendamentos idênticos)
3. Execução sequencial (uma execução por vez)
4. Persistência em dois JSONs:
   - agendamentos.json: Dados dos agendamentos
   - fila_execucao.json: Fila de execução com datas/horas completas
5. Gerenciamento centralizado de pastas
"""

import time
import threading
import json
import os
import tempfile
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field


@dataclass
class Agendamento:
    """Representa um agendamento com lista de horários."""
    id: int
    nome_automacao: str
    horas: List[str] = field(default_factory=list)  # ["09:00", "14:30", "18:45"]
    diario: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "ativo"  # ativo, inativo, pendente
    _evento_execucao_concluida: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )

    def eh_identico(self, outro: "Agendamento") -> bool:
        """Verifica se este agendamento é idêntico a outro."""
        return (
            self.horas == outro.horas
            and self.nome_automacao == outro.nome_automacao
            and self.diario == outro.diario
            and self._payload_identico(outro.payload)
        )

    def _payload_identico(self, outro_payload: Dict[str, Any]) -> bool:
        """Verifica se dois payloads são idênticos."""
        if set(self.payload.keys()) != set(outro_payload.keys()):
            return False
        for chave in self.payload:
            if self.payload[chave] != outro_payload[chave]:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário para persistência em JSON."""
        return {
            "id": self.id,
            "nome_automacao": self.nome_automacao,
            "horas": self.horas,
            "diario": self.diario,
            "status": self.status,
            **self.payload
        }


@dataclass
class FilaExecucao:
    """Representa uma entrada na fila de execução."""
    agendamento_id: int
    hora_agendada: datetime  # Data/hora completa desta execução
    status: str = "pendente"  # pendente, executando, concluido
    ordem_execucao: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agendamento_id": self.agendamento_id,
            "hora_agendada": self.hora_agendada.isoformat(),
            "status": self.status,
            "ordem_execucao": self.ordem_execucao,
        }


class GerenciadorAgendamentos:
    """Gerencia agendamentos com suporte a múltiplas horas por agendamento."""

    def __init__(self):
        self._callback_atualizar_visualizacao: Optional[Callable[[], None]] = None
        self.agendamentos: List[Agendamento] = []
        self.fila_execucao: List[FilaExecucao] = []
        self.proximo_id = 1
        self._lock = threading.RLock()
        self._callback_antes_execucao: Optional[Callable[[Agendamento], None]] = None
        self._callback_depois_execucao: Optional[Callable[[Agendamento, bool], None]] = None
        self._callback_verificar_monitoramento: Optional[Callable[[], bool]] = None
        self._semaforo_execucao = threading.Semaphore(1)
        self._parar_monitor = False
        self._thread_monitor = None
        self._processando_fila = False
        
        # ⭐ CAMINHOS CENTRALIZADOS
        appdata_local = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'AutoWMS')
        self._pasta_temp = os.path.join(appdata_local, 'temp')
        self._pasta_agendamentos = os.path.join(appdata_local, 'agend_data')
        self._arquivo_agendamentos = os.path.join(self._pasta_agendamentos, 'agendamentos.json')
        self._arquivo_fila = os.path.join(self._pasta_agendamentos, 'fila_execucao.json')
        
        self._criar_pastas_necessarias()
        self._carregar_agendamentos()
        self._carregar_fila_execucao()
        self._garantir_fila_execucao_inicial()
        self._descartar_agendamentos_passados()

    def _permite_execucao_paralela(self, agendamento: Optional[Agendamento]) -> bool:
        """Define se um agendamento pode executar em paralelo aos demais."""
        if not agendamento:
            return False
        if "agendar sistema de apoio" in (agendamento.nome_automacao or "").lower():
            return False
        return bool((agendamento.payload or {}).get("__allow_parallel__", False))

    def _prioridade_agendamento(self, agendamento: Optional[Agendamento]) -> int:
        """Menor valor = maior prioridade."""
        if not agendamento:
            return 99
        nome = (agendamento.nome_automacao or "").lower()
        if "agendar sistema de apoio" in nome:
            return 10
        return 0

    def _peso_status_fila(self, status: str) -> int:
        status_norm = (status or "").strip().lower()
        if status_norm == "executando":
            return 0
        if status_norm == "aguardando_execucao":
            return 1
        return 2

    def _chave_ordenacao_fila(self, fe: FilaExecucao, agendamento: Optional[Agendamento]) -> tuple:
        """Ordena a fila por status, prioridade da automação e depois horário."""
        return (
            self._peso_status_fila(fe.status),
            self._prioridade_agendamento(agendamento),
            fe.hora_agendada,
            fe.agendamento_id,
        )

    def _garantir_fila_execucao_inicial(self) -> None:
        """Reconstrói a fila quando os agendamentos existem, mas a fila está vazia ou incompleta."""
        with self._lock:
            if not self.agendamentos:
                return

            chaves_fila = {
                (fe.agendamento_id, fe.hora_agendada.strftime("%H:%M"))
                for fe in self.fila_execucao
            }
            chaves_esperadas = {
                (ag.id, hora_str)
                for ag in self.agendamentos
                if ag.status in ["ativo", "pendente"]
                for hora_str in ag.horas
            }

        if not chaves_esperadas:
            return

        if chaves_esperadas.issubset(chaves_fila):
            return

        self._reconstruir_fila_execucao()

    def _descartar_agendamentos_passados(self) -> None:
        """Remove execuções passadas da fila e reprograma apenas diários."""
        agora = datetime.now()
        mudou = False

        with self._lock:
            ag_por_id = {ag.id: ag for ag in self.agendamentos}
            filas_futuras = [fe for fe in self.fila_execucao if fe.hora_agendada > agora]
            chaves_futuras = {
                (fe.agendamento_id, fe.hora_agendada.time())
                for fe in filas_futuras
            }

            novas_filas = list(filas_futuras)

            for fe in self.fila_execucao:
                if fe.hora_agendada > agora:
                    continue

                mudou = True
                ag = ag_por_id.get(fe.agendamento_id)
                if not ag or not ag.diario:
                    continue

                # Reprograma para o próximo dia no mesmo horário
                proxima_exec = fe.hora_agendada
                while proxima_exec <= agora:
                    proxima_exec += timedelta(days=1)

                chave = (fe.agendamento_id, proxima_exec.time())
                if chave in chaves_futuras:
                    continue

                novas_filas.append(
                    FilaExecucao(
                        agendamento_id=fe.agendamento_id,
                        hora_agendada=proxima_exec,
                        status="pendente",
                        ordem_execucao=0,
                    )
                )
                chaves_futuras.add(chave)

            self.fila_execucao = novas_filas
            self._reordenar_fila_execucao()

        if mudou:
            self._salvar_fila_execucao()

    def _criar_pastas_necessarias(self) -> None:
        """Cria as pastas necessárias."""
        for pasta in [self._pasta_temp, self._pasta_agendamentos]:
            os.makedirs(pasta, exist_ok=True)

    def _escrever_json_atomico(self, caminho_arquivo: str, dados: Dict[str, Any]) -> None:
        """Escreve JSON de forma atômica usando arquivo temporário e replace."""
        pasta_destino = os.path.dirname(caminho_arquivo)
        os.makedirs(pasta_destino, exist_ok=True)

        fd_temp, caminho_temp = tempfile.mkstemp(
            prefix=".tmp_",
            suffix=".json",
            dir=pasta_destino,
            text=True,
        )
        try:
            with os.fdopen(fd_temp, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(caminho_temp, caminho_arquivo)
        except Exception:
            try:
                os.remove(caminho_temp)
            except Exception:
                pass
            raise

    def _carregar_agendamentos(self) -> None:
        """Carrega agendamentos do arquivo JSON."""
        try:
            if os.path.exists(self._arquivo_agendamentos):
                with open(self._arquivo_agendamentos, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    self.proximo_id = dados.get("proximo_id", 1)
                    self.agendamentos = []
                    for ag_dict in dados.get("agendamentos", []):
                        ag = Agendamento(
                            id=ag_dict["id"],
                            nome_automacao=ag_dict["nome_automacao"],
                            horas=ag_dict.get("horas", []),
                            diario=ag_dict.get("diario", False),
                            status=ag_dict.get("status", "ativo"),
                            payload={k: v for k, v in ag_dict.items() 
                                    if k not in ["id", "nome_automacao", "horas", "diario", "status"]}
                        )
                        self.agendamentos.append(ag)
        except Exception as e:
            print(f"[ERRO] Carregando agendamentos: {e}")

    def _salvar_agendamentos(self) -> None:
        """Salva agendamentos em JSON."""
        try:
            dados = {
                "proximo_id": self.proximo_id,
                "agendamentos": [ag.to_dict() for ag in self.agendamentos]
            }
            self._escrever_json_atomico(self._arquivo_agendamentos, dados)
        except Exception as e:
            print(f"[ERRO] Salvando agendamentos: {e}")

    def _carregar_fila_execucao(self) -> None:
        """Carrega a fila de execução do JSON."""
        try:
            if os.path.exists(self._arquivo_fila):
                with open(self._arquivo_fila, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    self.fila_execucao = []
                    for fe_dict in dados.get("fila", []):
                        fe = FilaExecucao(
                            agendamento_id=fe_dict["agendamento_id"],
                            hora_agendada=datetime.fromisoformat(fe_dict["hora_agendada"]),
                            status=fe_dict.get("status", "pendente"),
                            ordem_execucao=fe_dict.get("ordem_execucao", 0)
                        )
                        self.fila_execucao.append(fe)
        except Exception as e:
            print(f"[ERRO] Carregando fila de execução: {e}")

    def _salvar_fila_execucao(self) -> None:
        """Salva a fila de execução em JSON."""
        try:
            dados = {
                "fila": [fe.to_dict() for fe in self.fila_execucao]
            }
            self._escrever_json_atomico(self._arquivo_fila, dados)
        except Exception as e:
            print(f"[ERRO] Salvando fila de execução: {e}")

    def _reconstruir_fila_execucao(self) -> None:
        """Reconstrói a fila de execução baseada nos agendamentos atuais."""
        with self._lock:
            self.fila_execucao = []
            ag_por_id = {}
            for ag in self.agendamentos:
                ag_por_id[ag.id] = ag
                if ag.status in ["ativo", "pendente"]:
                    for hora_str in ag.horas:
                        try:
                            hora_obj = datetime.strptime(hora_str, "%H:%M").time()
                            agora = datetime.now()
                            data_exec = agora.date()
                            hora_agendada = datetime.combine(data_exec, hora_obj)
                            
                            if hora_agendada < agora:
                                hora_agendada += timedelta(days=1)
                            
                            fe = FilaExecucao(
                                agendamento_id=ag.id,
                                hora_agendada=hora_agendada,
                                status="pendente",
                                ordem_execucao=len(self.fila_execucao)
                            )
                            self.fila_execucao.append(fe)
                        except Exception as e:
                            print(f"[ERRO] Processando hora {hora_str} do agendamento #{ag.id}: {e}")
            
            self.fila_execucao.sort(key=lambda x: self._chave_ordenacao_fila(x, ag_por_id.get(x.agendamento_id)))
            for idx, fe in enumerate(self.fila_execucao):
                fe.ordem_execucao = idx
        self._salvar_fila_execucao()

    def _reordenar_fila_execucao(self) -> None:
        """Reordena a fila por horário e atualiza a ordem de execução."""
        ag_por_id = {ag.id: ag for ag in self.agendamentos}
        self.fila_execucao.sort(key=lambda x: self._chave_ordenacao_fila(x, ag_por_id.get(x.agendamento_id)))
        for idx, fe in enumerate(self.fila_execucao):
            fe.ordem_execucao = idx

    def _notificar_atualizacao_visualizacao(self) -> None:
        """Notifica callback de atualização de visualização."""
        if self._callback_atualizar_visualizacao:
            try:
                self._callback_atualizar_visualizacao()
            except Exception as e:
                print(f"[ERRO] Callback de visualização: {e}")

    def registrar_callback_atualizar_visualizacao(self, callback: Callable[[], None]) -> None:
        """Registra callback para atualizar visualização."""
        self._callback_atualizar_visualizacao = callback

    def registrar_callbacks(
        self,
        antes_execucao: Optional[Callable[[Agendamento], None]] = None,
        depois_execucao: Optional[Callable[[Agendamento, bool], None]] = None,
        verificar_monitoramento: Optional[Callable[[], bool]] = None,
        atualizar_visualizacao: Optional[Callable[[], None]] = None
    ) -> None:
        """Registra callbacks de antes/depois execução e monitoramento."""
        if antes_execucao:
            self._callback_antes_execucao = antes_execucao
        if depois_execucao:
            self._callback_depois_execucao = depois_execucao
        if atualizar_visualizacao:
            self._callback_atualizar_visualizacao = atualizar_visualizacao

    def criar_ou_atualizar_agendamento(
        self,
        nome_automacao: str,
        horas: List[str],
        diario: bool = False,
        payload: Optional[Dict[str, Any]] = None,
        agendamento_id: Optional[int] = None
    ) -> Tuple[Optional[Agendamento], Optional[str], bool]:
        """
        Cria ou atualiza um agendamento.
        Retorna: (agendamento, erro, eh_novo)
        """
        if payload is None:
            payload = {}

        novo_ag = Agendamento(
            id=agendamento_id or self.proximo_id,
            nome_automacao=nome_automacao,
            horas=horas,
            diario=diario,
            payload=payload,
            status="ativo"
        )

        with self._lock:
            if agendamento_id:
                # Atualizar existente
                for i, ag in enumerate(self.agendamentos):
                    if ag.id == agendamento_id:
                        self.agendamentos[i] = novo_ag
                        self._salvar_agendamentos()
                        self._reconstruir_fila_execucao()
                        self._notificar_atualizacao_visualizacao()
                        return novo_ag, None, False
                return None, "Agendamento não encontrado", False
            else:
                # Criar novo
                if self._existe_identico(novo_ag):
                    return None, "Duplicata: agendamento idêntico já existe", False

                self.proximo_id += 1
                self.agendamentos.append(novo_ag)
                self._salvar_agendamentos()
                self._reconstruir_fila_execucao()
                self._notificar_atualizacao_visualizacao()
                return novo_ag, None, True

    def _existe_identico(self, agendamento: Agendamento) -> bool:
        """Verifica se já existe um agendamento idêntico."""
        for ag in self.agendamentos:
            if ag.eh_identico(agendamento):
                return True
        return False

    def atualizar_agendamento(
        self,
        agendamento_id: int,
        horas: List[str],
        payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Agendamento], Optional[str]]:
        """Atualiza um agendamento existente."""
        if payload is None:
            payload = {}

        with self._lock:
            for ag in self.agendamentos:
                if ag.id == agendamento_id:
                    ag.horas = horas
                    ag.payload.update(payload)
                    self._salvar_agendamentos()
                    self._reconstruir_fila_execucao()
                    self._notificar_atualizacao_visualizacao()
                    return ag, None

        return None, "Agendamento não encontrado"

    def obter_agendamentos(self) -> List[Agendamento]:
        """Retorna lista de agendamentos."""
        with self._lock:
            return list(self.agendamentos)

    def obter_agendamento_por_id(self, agendamento_id: int) -> Optional[Agendamento]:
        """Obtém um agendamento específico por ID."""
        with self._lock:
            for ag in self.agendamentos:
                if ag.id == agendamento_id:
                    return ag
        return None

    def obter_fila_execucao(self) -> List[FilaExecucao]:
        """Retorna uma cópia da fila de execução."""
        with self._lock:
            ag_por_id = {ag.id: ag for ag in self.agendamentos}
            return sorted(
                list(self.fila_execucao),
                key=lambda fe: self._chave_ordenacao_fila(fe, ag_por_id.get(fe.agendamento_id))
            )

    def obter_status_agendamento(self, agendamento_id: int) -> Dict[str, Any]:
        """Retorna status resumido (próxima execução e posição na fila) para um agendamento."""
        with self._lock:
            fila_ag = [fe for fe in self.fila_execucao if fe.agendamento_id == agendamento_id]
            if not fila_ag:
                return {"status": "sem_fila", "proxima_execucao": None, "posicao": None}

            agendamento = self.obter_agendamento_por_id(agendamento_id)
            fila_ag.sort(key=lambda x: self._chave_ordenacao_fila(x, agendamento))
            proxima = fila_ag[0]

            ag_por_id = {ag.id: ag for ag in self.agendamentos}
            fila_ordenada = sorted(
                self.fila_execucao,
                key=lambda x: self._chave_ordenacao_fila(x, ag_por_id.get(x.agendamento_id))
            )
            posicao = None
            for idx, fe in enumerate(fila_ordenada, 1):
                if fe is proxima:
                    posicao = idx
                    break

            return {
                "status": proxima.status,
                "proxima_execucao": proxima.hora_agendada,
                "posicao": posicao,
            }

    def remover_agendamento(self, agendamento_id: int) -> bool:
        """Remove um agendamento por ID."""
        sucesso = False
        with self._lock:
            for i, ag in enumerate(self.agendamentos):
                if ag.id == agendamento_id:
                    self.agendamentos.pop(i)
                    sucesso = True
                    break

        if sucesso:
            self._salvar_agendamentos()
            self._reconstruir_fila_execucao()
            self._notificar_atualizacao_visualizacao()
            return True
        return False

    def contar_agendamentos(self) -> int:
        """Retorna o número total de agendamentos."""
        with self._lock:
            return len(self.agendamentos)

    def iniciar_monitor_agendamentos(self, timeout: int = 2) -> threading.Thread:
        """Inicia thread que monitora e executa agendamentos."""
        def monitor():
            try:
                while not self._parar_monitor:
                    try:
                        self._verificar_e_executar_agendamentos()
                        time.sleep(timeout)
                    except Exception as e:
                        print(f"[ERRO] Monitor: {e}")
                        time.sleep(timeout)
            except Exception as e:
                print(f"[ERRO] Thread monitor finalizada: {e}")

        if self._thread_monitor and self._thread_monitor.is_alive():
            return self._thread_monitor

        self._parar_monitor = False
        self._thread_monitor = threading.Thread(target=monitor, daemon=True)
        self._thread_monitor.start()
        return self._thread_monitor

    def parar_monitor_agendamentos(self) -> None:
        """Para o monitor de agendamentos."""
        self._parar_monitor = True
        if self._thread_monitor:
            self._thread_monitor.join(timeout=2)

    def _verificar_e_executar_agendamentos(self) -> None:
        """Verifica agendamentos vencidos e os adiciona ? fila."""
        agora = datetime.now()

        with self._lock:
            ag_ids = {ag.id for ag in self.agendamentos}
            self.fila_execucao = [fe for fe in self.fila_execucao if fe.agendamento_id in ag_ids]

            for fe in self.fila_execucao:
                if fe.hora_agendada <= agora and fe.status == "pendente":
                    fe.status = "aguardando_execucao"
            self._reordenar_fila_execucao()
            self._salvar_fila_execucao()

        self._processar_fila_execucao_paralela()
        self._processar_fila_execucao()

    def _finalizar_execucao_agendamento(self, fe_atual: FilaExecucao, ag: Agendamento, sucesso: bool) -> None:
        """Finaliza a execu??o, remove da fila e reprograma recorr?ncia quando necess?rio."""
        if self._callback_depois_execucao:
            self._callback_depois_execucao(ag, sucesso)

        with self._lock:
            if fe_atual in self.fila_execucao:
                self.fila_execucao.remove(fe_atual)

            if sucesso and ag.diario:
                proxima_exec = fe_atual.hora_agendada + timedelta(days=1)
                agora = datetime.now()
                while proxima_exec <= agora:
                    proxima_exec += timedelta(days=1)
                self.fila_execucao.append(
                    FilaExecucao(
                        agendamento_id=ag.id,
                        hora_agendada=proxima_exec,
                        status="pendente",
                        ordem_execucao=0,
                    )
                )
            elif sucesso:
                self.agendamentos = [a for a in self.agendamentos if a.id != ag.id]
                self.fila_execucao = [fe for fe in self.fila_execucao if fe.agendamento_id != ag.id]
                self._salvar_agendamentos()

            self._reordenar_fila_execucao()

        self._salvar_fila_execucao()
        self._notificar_atualizacao_visualizacao()

    def _acompanhar_execucao_assincrona(self, fe_atual: FilaExecucao, ag: Agendamento) -> None:
        """Acompanha uma execu??o iniciada fora da fila serial."""
        sucesso = True
        try:
            ag._evento_execucao_concluida.wait()
        except Exception:
            sucesso = False
        finally:
            try:
                self._finalizar_execucao_agendamento(fe_atual, ag, sucesso)
            except Exception as e:
                print(f"[ERRO] Finalizando execu??o ass?ncrona: {e}")

    def _processar_fila_execucao_paralela(self) -> None:
        """Dispara execu??es paralelas eleg?veis sem passar pelo sem?foro global."""
        itens_para_iniciar: List[Tuple[FilaExecucao, Agendamento]] = []

        with self._lock:
            ag_por_id = {ag.id: ag for ag in self.agendamentos}
            for fe in sorted(self.fila_execucao, key=lambda x: self._chave_ordenacao_fila(x, ag_por_id.get(x.agendamento_id))):
                if fe.status != "aguardando_execucao":
                    continue
                ag = ag_por_id.get(fe.agendamento_id)
                if not ag or not self._permite_execucao_paralela(ag):
                    continue
                fe.status = "executando"
                itens_para_iniciar.append((fe, ag))

        if not itens_para_iniciar:
            return

        self._salvar_fila_execucao()
        self._notificar_atualizacao_visualizacao()

        for fe_atual, ag in itens_para_iniciar:
            try:
                if self._callback_antes_execucao:
                    self._callback_antes_execucao(ag)

                threading.Thread(
                    target=self._acompanhar_execucao_assincrona,
                    args=(fe_atual, ag),
                    daemon=True,
                ).start()
            except Exception as e:
                print(f"[ERRO] Iniciando execu??o paralela: {e}")
                try:
                    self._finalizar_execucao_agendamento(fe_atual, ag, False)
                except Exception:
                    pass

    def _processar_fila_execucao(self) -> None:
        """Processa a fila sequencialmente para automa??es n?o paraleliz?veis."""
        with self._lock:
            if self._processando_fila:
                return
            self._processando_fila = True

        def processar():
            try:
                while True:
                    fe_atual = None
                    with self._lock:
                        ag_por_id = {ag.id: ag for ag in self.agendamentos}
                        pendentes = [
                            fe for fe in self.fila_execucao
                            if fe.status == "aguardando_execucao"
                            and not self._permite_execucao_paralela(ag_por_id.get(fe.agendamento_id))
                        ]
                        if pendentes:
                            fe_atual = min(
                                pendentes,
                                key=lambda x: self._chave_ordenacao_fila(x, ag_por_id.get(x.agendamento_id))
                            )
                        if not fe_atual:
                            break

                    try:
                        acquired = self._semaforo_execucao.acquire(blocking=True, timeout=None)
                        if not acquired:
                            continue

                        try:
                            ag = self.obter_agendamento_por_id(fe_atual.agendamento_id)
                            if not ag:
                                with self._lock:
                                    if fe_atual in self.fila_execucao:
                                        self.fila_execucao.remove(fe_atual)
                                        self._reordenar_fila_execucao()
                                        self._salvar_fila_execucao()
                                continue

                            if self._callback_antes_execucao:
                                self._callback_antes_execucao(ag)

                            with self._lock:
                                fe_atual.status = "executando"
                            self._notificar_atualizacao_visualizacao()
                            self._salvar_fila_execucao()

                            try:
                                ag._evento_execucao_concluida.wait()
                            except Exception:
                                pass
                            self._finalizar_execucao_agendamento(fe_atual, ag, True)

                        finally:
                            self._semaforo_execucao.release()

                    except Exception as e:
                        print(f"[ERRO] Processando fila: {e}")
                        if self._callback_depois_execucao:
                            ag = self.obter_agendamento_por_id(fe_atual.agendamento_id)
                            if ag:
                                self._callback_depois_execucao(ag, False)
            finally:
                with self._lock:
                    self._processando_fila = False

        thread = threading.Thread(target=processar, daemon=True)
        thread.start()
