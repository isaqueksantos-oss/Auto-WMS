"""
Rastreador de execução das automações do Auto WMS.

Registra em qual item a macro parou e guarda um print da tela quando
ela termina, trava ou dá erro.

Funciona para TODAS as automações sem alterar cada macro: ele envolve o
status_callback que o main_window já passa para iniciar_automacao().

Arquivos gerados (pasta active/logs/execucoes/, já ignorada pelo Git):

    logs/execucoes/2026-09-29/143512_Cativar local/
        checkpoint.json    -> atualizado a cada linha (sobrevive a travas)
        resumo.json        -> resumo final da execução
        resumo.txt         -> mesmo resumo, legível no Bloco de Notas
        final.png          -> print da tela ao terminar
        travamento_*.png   -> print quando a macro fica parada demais
        erro_linha_*.png   -> print em status críticos (falha, foco...)

Uso no main_window.py (dentro do _worker):

    tracker = ExecutionTracker(auto["nome"], len(dados), log_fn=log)
    status_cb = tracker.envolver(_status_cb)
    try:
        result = modulo.iniciar_automacao(dados, status_callback_fn=status_cb)
    except Exception as exc:
        tracker.finalizar(erro=exc)
        raise
    else:
        tracker.finalizar()
"""

import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path


# Pasta base: active/logs/execucoes
# (este arquivo fica em active/interface/utils/)
PASTA_BASE = Path(__file__).resolve().parents[2] / "logs" / "execucoes"

# Sem nenhuma atualização de status por este tempo, considera travamento.
TIMEOUT_TRAVAMENTO_SEGUNDOS = 120

# Status que disparam um print imediato da tela.
STATUS_CRITICOS = {
    "Falha_wms",
    "Foco_perdido",
    "Transacao_nao_encontrada",
    "Nao_confirmado",
    "Salvamento_nao_confirmado",
    "Remocao_nao_confirmada",
    "Alteracao_nao_confirmada",
}

# Status que indicam que a linha ainda não terminou.
STATUS_EM_ANDAMENTO = {"Em progresso"}

# Limite de prints de status crítico por execução (evita encher o disco).
MAX_PRINTS_CRITICOS = 20


def _nome_seguro(texto):
    """Remove caracteres inválidos para nome de pasta no Windows."""
    return re.sub(r'[<>:"/\\|?*]', "_", str(texto)).strip() or "automacao"


def capturar_tela(destino):
    """
    Salva um print de TODOS os monitores.

    Usa o ImageGrab do Pillow (captura todas as telas); se falhar,
    recorre ao pyautogui (somente o monitor principal).
    """
    destino = Path(destino)

    try:
        from PIL import ImageGrab

        imagem = ImageGrab.grab(all_screens=True)
        imagem.save(destino)
        return destino
    except Exception:
        pass

    try:
        import pyautogui

        pyautogui.screenshot().save(destino)
        return destino
    except Exception:
        return None


class ExecutionTracker:
    """Acompanha uma execução de automação, linha a linha."""

    def __init__(
        self,
        nome_automacao,
        total_linhas,
        log_fn=print,
        timeout_travamento=TIMEOUT_TRAVAMENTO_SEGUNDOS,
    ):
        self.nome = nome_automacao
        self.total_linhas = int(total_linhas or 0)
        self.log_fn = log_fn
        self.timeout_travamento = timeout_travamento

        self.inicio = datetime.now()

        self.pasta = (
            PASTA_BASE
            / self.inicio.strftime("%Y-%m-%d")
            / f"{self.inicio.strftime('%H%M%S')}_{_nome_seguro(nome_automacao)}"
        )
        self.pasta.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._linhas = {}            # linha -> {"item", "status", "hora"}
        self._historico = []         # todas as mudanças de status
        self._ultima_linha = None
        self._ultimo_item = None
        self._ultimo_status = None
        self._ultima_atividade = time.time()
        self._prints_criticos = 0
        self._finalizado = False

        self._watchdog_ativo = True
        self._travamento_registrado = False
        self._watchdog = threading.Thread(
            target=self._monitorar_travamento,
            daemon=True,
            name=f"Watchdog-{_nome_seguro(nome_automacao)}",
        )
        self._watchdog.start()

        self._log(
            f"[RASTREIO] Execução registrada em: {self.pasta}"
        )

    # ------------------------------------------------------------- #

    def _log(self, mensagem):
        try:
            self.log_fn(f"{time.strftime('[%H:%M:%S]')} {mensagem}")
        except Exception:
            print(mensagem)

    def _salvar_json(self, nome_arquivo, dados):
        try:
            caminho = self.pasta / nome_arquivo
            temporario = caminho.with_suffix(".tmp")
            temporario.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            # Substituição atômica: um travamento no meio da escrita
            # não corrompe o arquivo anterior.
            os.replace(temporario, caminho)
        except Exception as exc:
            print(f"[RASTREIO] Falha ao salvar {nome_arquivo}: {exc}")

    # ------------------------------------------------------------- #

    def envolver(self, status_cb):
        """
        Retorna um status_callback que registra cada atualização e
        repassa a chamada para o callback original da interface.
        """
        def _cb(linha, status, valor=None, *args, **kwargs):
            self.registrar(linha, status, valor)

            if callable(status_cb):
                return status_cb(linha, status, valor, *args, **kwargs)

            return None

        return _cb

    def registrar(self, linha, status, item=None):
        """Registra o status de uma linha e atualiza o checkpoint."""
        agora = datetime.now()

        with self._lock:
            self._ultima_atividade = time.time()
            self._travamento_registrado = False

            self._ultima_linha = linha
            self._ultimo_status = status
            if item is not None:
                self._ultimo_item = item

            self._linhas[linha] = {
                "item": item,
                "status": status,
                "hora": agora.strftime("%H:%M:%S"),
            }

            self._historico.append({
                "hora": agora.strftime("%H:%M:%S"),
                "linha": linha,
                "item": item,
                "status": status,
            })

            checkpoint = self._montar_estado()

        # Gravado a cada linha: se o programa fechar à força, este
        # arquivo ainda mostra onde a execução estava.
        self._salvar_json("checkpoint.json", checkpoint)

        if status in STATUS_CRITICOS and self._prints_criticos < MAX_PRINTS_CRITICOS:
            self._prints_criticos += 1
            capturar_tela(
                self.pasta / f"erro_linha_{linha}_{_nome_seguro(status)}.png"
            )

    # ------------------------------------------------------------- #

    def _linhas_concluidas(self):
        return sum(
            1 for dados in self._linhas.values()
            if dados["status"] not in STATUS_EM_ANDAMENTO
        )

    def _linha_para_retomar(self):
        """
        Primeira linha que ainda não foi concluída.

        Se a última linha ficou "Em progresso", é ela; senão, a seguinte.
        """
        for linha in range(1, self.total_linhas + 1):
            dados = self._linhas.get(linha)
            if not dados or dados["status"] in STATUS_EM_ANDAMENTO:
                return linha

        return None

    def _contagem_por_status(self):
        contagem = {}
        for dados in self._linhas.values():
            contagem[dados["status"]] = contagem.get(dados["status"], 0) + 1
        return contagem

    def _montar_estado(self, situacao="em_execucao", erro=None):
        fim = datetime.now()

        return {
            "automacao": self.nome,
            "situacao": situacao,
            "inicio": self.inicio.strftime("%d/%m/%Y %H:%M:%S"),
            "ultima_atualizacao": fim.strftime("%d/%m/%Y %H:%M:%S"),
            "duracao_segundos": round((fim - self.inicio).total_seconds(), 1),
            "total_linhas": self.total_linhas,
            "linhas_concluidas": self._linhas_concluidas(),
            "ultima_linha": self._ultima_linha,
            "ultimo_item": self._ultimo_item,
            "ultimo_status": self._ultimo_status,
            "retomar_a_partir_da_linha": self._linha_para_retomar(),
            "contagem_por_status": self._contagem_por_status(),
            "erro": erro,
            "linhas": self._linhas,
        }

    # ------------------------------------------------------------- #

    def _monitorar_travamento(self):
        """Tira um print se a macro ficar parada além do limite."""
        while self._watchdog_ativo:
            time.sleep(5)

            with self._lock:
                parado_ha = time.time() - self._ultima_atividade
                ja_registrado = self._travamento_registrado

            if parado_ha < self.timeout_travamento or ja_registrado:
                continue

            with self._lock:
                self._travamento_registrado = True
                linha = self._ultima_linha
                item = self._ultimo_item

            nome_print = f"travamento_linha_{linha}_{time.strftime('%H%M%S')}.png"
            capturar_tela(self.pasta / nome_print)

            self._log(
                f"[RASTREIO] Sem atividade há {int(parado_ha)}s na linha "
                f"{linha} (item {item}). Print salvo: {nome_print}"
            )

    # ------------------------------------------------------------- #

    def finalizar(self, erro=None):
        """
        Encerra o rastreio: tira o print final e grava o resumo.

        Parâmetros:
            erro: exceção que interrompeu a execução, se houver.

        Retorna o caminho da pasta da execução.
        """
        if self._finalizado:
            return self.pasta

        self._finalizado = True
        self._watchdog_ativo = False

        with self._lock:
            concluidas = self._linhas_concluidas()

            if erro is not None:
                situacao = "erro"
                detalhe_erro = "".join(
                    traceback.format_exception(type(erro), erro, erro.__traceback__)
                )
            elif self.total_linhas and concluidas >= self.total_linhas:
                situacao = "concluido"
                detalhe_erro = None
            else:
                situacao = "interrompido"
                detalhe_erro = None

            resumo = self._montar_estado(situacao=situacao, erro=detalhe_erro)

        print_final = capturar_tela(self.pasta / "final.png")

        resumo["print_final"] = str(print_final) if print_final else None

        self._salvar_json("resumo.json", resumo)
        self._salvar_txt(resumo)

        if situacao == "concluido":
            self._log(
                f"[RASTREIO] Execução concluída ({concluidas}/{self.total_linhas}). "
                f"Registro em: {self.pasta}"
            )
        else:
            self._log(
                f"[RASTREIO] Execução {situacao.upper()} na linha "
                f"{resumo['ultima_linha']} (item {resumo['ultimo_item']}). "
                f"Retomar a partir da linha {resumo['retomar_a_partir_da_linha']}. "
                f"Print e resumo em: {self.pasta}"
            )

        return self.pasta

    def _salvar_txt(self, resumo):
        linhas = [
            f"Automação ........: {resumo['automacao']}",
            f"Situação .........: {resumo['situacao'].upper()}",
            f"Início ...........: {resumo['inicio']}",
            f"Fim ..............: {resumo['ultima_atualizacao']}",
            f"Duração ..........: {resumo['duracao_segundos']}s",
            "",
            f"Linhas concluídas : {resumo['linhas_concluidas']} de {resumo['total_linhas']}",
            f"Última linha .....: {resumo['ultima_linha']}",
            f"Último item ......: {resumo['ultimo_item']}",
            f"Último status ....: {resumo['ultimo_status']}",
            f"Retomar da linha .: {resumo['retomar_a_partir_da_linha']}",
            "",
            "Contagem por status:",
        ]

        for status, qtd in sorted(resumo["contagem_por_status"].items()):
            linhas.append(f"  - {status}: {qtd}")

        if resumo.get("erro"):
            linhas += ["", "Erro:", resumo["erro"]]

        linhas += ["", "Linhas não concluídas com sucesso:"]
        for linha, dados in sorted(resumo["linhas"].items()):
            if dados["status"] not in ("Concluído", "Concluido"):
                linhas.append(
                    f"  linha {linha}: item {dados['item']} -> {dados['status']}"
                )

        try:
            (self.pasta / "resumo.txt").write_text(
                "\n".join(linhas),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[RASTREIO] Falha ao salvar resumo.txt: {exc}")

    def abrir_pasta(self):
        """Abre a pasta da execução no Explorer."""
        try:
            os.startfile(self.pasta)
        except Exception:
            pass
