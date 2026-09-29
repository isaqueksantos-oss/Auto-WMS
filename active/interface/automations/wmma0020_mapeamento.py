import os
import time
import pyautogui
import pyperclip
import keyboard as kb
import pygetwindow as gw
from PIL import Image
import imagehash
import numpy as np

from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import (
    aceitar_alt_o,
    acao_limpar,
    aguardar_textos,
    alt_f4,
    ativar_edicao,
    colar_ctrl_v,
    copiar_ctrl_c,
    copiar_para_clipboard,
    digitar_transacao,
    executar_campo,
    inicio_do_campo,
    inserir_registro,
    limpar_campo,
    proximo_campo,
    proximo_bloco,
    remover_registro,
    salvar_alt_s,
    salvar_registro,
    selecionar_texto_esq_dir,
)


# =================== VARIÁVEIS GLOBAIS =================== #

TRANSACAO_MAPEAMENTO = "wmma0020"

# Máximo de tentativas de reabrir o WMS para a MESMA linha antes de
# marcar como falha e seguir para a próxima.
MAX_RECUPERACOES_POR_LINHA = 3


# =================== AJUSTE FINO DE TEMPOS =================== #
# Centraliza os tempos para facilitar a calibração.

# --- Digitação (mais lenta = mais confiável) --- #
# Intervalo entre as teclas dentro de um mesmo campo.
INTERVALO_DIGITACAO = 0.04

# Pausa após terminar de digitar um campo, antes do TAB.
# Dá tempo do WMS processar o valor digitado.
PAUSA_APOS_DIGITAR = 0.15

# Pausa após o TAB, antes de começar a digitar o próximo campo.
PAUSA_APOS_TAB = 0.10

# --- Verificação de duplicidade (mais rápida) --- #
# Tempo máximo de busca pelo popup de duplicidade.
TIMEOUT_DUPLICIDADE = 0.05

# Pausa entre detectar o popup e pressionar Enter.
DELAY_CONFIRMACAO_DUPLICIDADE = 0.20

# Pausa entre o Enter e o remover_registro().
DELAY_ENTRE_ACOES_DUPLICIDADE = 0.20

# Pausa após remover o registro duplicado.
PAUSA_APOS_REMOVER = 0.05

# --- Transição para o próximo item (mais rápida) --- #
PAUSA_ANTES_PROXIMO_BLOCO = 0.07


# Títulos aceitos como "janela do WMS" (sempre em minúsculas).
TITULOS_WMS = (
    "wms americanas",
)

# Títulos que NUNCA devem receber digitação da automação.
# A interface do robô se chama "Auto WMS V7" e contém a substring "wms",
# por isso esta lista é avaliada ANTES da lista de aceitos.
TITULOS_PROIBIDOS = (
    "auto wms",
    "visual studio code",
    "excel",
    "outlook",
    "chrome",
    "edge",
    "bloco de notas",
    "notepad",
)

logger = print
status_callback = None
stop_requested = False


# =================== EXCEÇÕES DE CONTROLE =================== #

class WMSCaiuError(Exception):
    """Sinaliza que o WMS caiu (FRM-92103) e precisa ser reiniciado."""
    pass


class FocoPerdidoError(Exception):
    """A janela do WMS não pôde ser focada; digitar seria inseguro."""
    pass


class AbortarMapeamento(Exception):
    """
    Interrompe todo o mapeamento (ex.: tela não encontrada ou parada).

    Pode carregar um resultado parcial para ser registrado antes de sair.
    """
    def __init__(self, motivo, resultado_parcial=None):
        super().__init__(motivo)
        self.motivo = motivo
        self.resultado_parcial = resultado_parcial


# =================== UTILITÁRIOS =================== #

def request_stop():
    global stop_requested
    stop_requested = True


def clear_stop():
    global stop_requested
    stop_requested = False


def log(message):
    try:
        logger(message)
    except Exception:
        print(message)


def verificar_tamanho_lista(dados, planta=None, *, tamanho_esperado):
    if dados:
        return len(dados[0]) >= tamanho_esperado

    if planta:
        return len(planta) >= tamanho_esperado

    return False


def atualizar_interface_threadsafe(root, callback, lista_remessas):
    """
    Executa o callback de atualização da interface de forma segura.
    """
    if callback and root:
        root.after(0, lambda: callback(lista_remessas))


# =================== SEGURANÇA DE FOCO =================== #

def _titulo_janela_ativa():
    """Retorna o título da janela ativa em minúsculas (ou string vazia)."""
    try:
        janela = gw.getActiveWindow()
        if janela and janela.title:
            return janela.title.strip().lower()
    except Exception:
        pass
    return ""


def janela_wms_esta_ativa():
    """
    True somente se a janela ativa for o WMS.

    A lista de proibidos é checada primeiro porque a interface do robô
    ("Auto WMS V7") contém a substring "wms" e daria falso positivo.
    """
    titulo = _titulo_janela_ativa()

    if not titulo:
        return False

    for proibido in TITULOS_PROIBIDOS:
        if proibido in titulo:
            return False

    return any(aceito in titulo for aceito in TITULOS_WMS)


def garantir_foco_wms(tentativas=3, log_fn=None):
    """
    Garante que a janela do WMS esteja ativa antes de qualquer digitação.

    Levanta FocoPerdidoError se não conseguir focar o WMS, evitando que
    dados da planilha sejam digitados na interface errada.
    """
    if log_fn is None:
        log_fn = log

    for tentativa in range(1, tentativas + 1):
        if janela_wms_esta_ativa():
            return True

        titulo_atual = _titulo_janela_ativa() or "(desconhecida)"
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[FOCO] Janela ativa incorreta: '{titulo_atual}'. "
            f"Reativando WMS (tentativa {tentativa}/{tentativas})..."
        )

        alvo = None
        for titulo in gw.getAllTitles():
            baixo = (titulo or "").lower()
            if not baixo:
                continue
            if any(p in baixo for p in TITULOS_PROIBIDOS):
                continue
            if any(a in baixo for a in TITULOS_WMS):
                alvo = titulo
                break

        if not alvo:
            log_fn(
                f"{time.strftime('[%H:%M:%S]')} "
                "[FOCO] Nenhuma janela do WMS encontrada."
            )
            time.sleep(0.6)
            continue

        try:
            for janela in gw.getWindowsWithTitle(alvo):
                try:
                    if janela.isMinimized:
                        janela.restore()
                except Exception:
                    pass
                janela.activate()
                time.sleep(0.5)
                break
        except Exception as exc:
            log_fn(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[FOCO] Falha ao ativar '{alvo}': {exc}"
            )

        time.sleep(0.4)

    raise FocoPerdidoError(
        "Não foi possível focar a janela do WMS. "
        "Digitação abortada para não preencher a janela errada."
    )


def escrever_wms(texto, interval=None, pausa_final=None):
    """
    Substituto seguro de pyautogui.write().

    1. Confirma o foco do WMS antes de digitar;
    2. Digita com intervalo controlado entre as teclas;
    3. Aguarda o WMS processar o valor;
    4. Revalida o foco após a escrita.

    Parâmetros:
        interval: intervalo entre teclas (padrão INTERVALO_DIGITACAO).
        pausa_final: pausa após digitar (padrão PAUSA_APOS_DIGITAR).
    """
    if interval is None:
        interval = INTERVALO_DIGITACAO

    if pausa_final is None:
        pausa_final = PAUSA_APOS_DIGITAR

    garantir_foco_wms()

    pyautogui.write(str(texto), interval=interval)

    # Dá tempo do WMS registrar o valor antes do próximo comando.
    time.sleep(pausa_final)

    if not janela_wms_esta_ativa():
        titulo_atual = _titulo_janela_ativa() or "(desconhecida)"
        raise FocoPerdidoError(
            f"O foco mudou para '{titulo_atual}' durante a digitação "
            f"de '{texto}'."
        )

    return True


def atalho_wms(func, *args, **kwargs):
    """
    Executa um atalho do base_automation com o foco garantido.

    Exemplo:
        atalho_wms(salvar_registro)
        atalho_wms(proximo_campo)
    """
    garantir_foco_wms()
    return func(*args, **kwargs)


def proximo_campo_wms():
    """
    TAB com foco garantido e pausa para o WMS reposicionar o cursor.

    Evita que o próximo valor comece a ser digitado antes do campo
    seguinte estar realmente pronto para receber a entrada.
    """
    atalho_wms(proximo_campo)
    time.sleep(PAUSA_APOS_TAB)


# =================== DETECÇÃO DE TELA =================== #

def capturar_hash_tela():
    """
    Captura o pHash da tela atual para comparação pontual.
    """
    screenshot = pyautogui.screenshot()

    gray = np.array(
        screenshot.convert("L").resize(
            (64, 64),
            Image.BILINEAR,
        )
    )

    return imagehash.phash(Image.fromarray(gray))


def detectar_mudanca_tela(
    hash_ref=None,
    limiar=5,
    max_espera=3.5,
    intervalo=0.1,
    confirmacoes=1,
    log_fn=print,
):
    """
    Aguarda até que a tela mude perceptivelmente comparando perceptual hash.

    Quando confirmacoes for maior que 1, exige a mudança acima do
    limiar em leituras consecutivas.

    Retorna:
        (novo_hash, mudou)
    """
    start = time.time()

    if hash_ref is None:
        hash_ref = capturar_hash_tela()

    consecutivas = 0
    ultimo_hash_valido = hash_ref

    while time.time() - start < max_espera:
        hash_atual = capturar_hash_tela()
        dist = abs(hash_ref - hash_atual)

        if dist >= limiar:
            consecutivas += 1
            ultimo_hash_valido = hash_atual

            if consecutivas >= max(1, int(confirmacoes)):
                log_fn(
                    f"[MUDANCA] Tela alterada "
                    f"(distância pHash={dist}, "
                    f"confirmações={consecutivas})"
                )

                return ultimo_hash_valido, True

        else:
            consecutivas = 0

        time.sleep(intervalo)

    log_fn(
        "[MUDANCA] Nenhuma mudança detectada "
        "dentro do tempo limite."
    )

    return hash_ref, False


def aguardar_transacao_completada(timeout=4.0):
    """
    Aguarda a confirmação "Transação Completada." na barra de status
    (canto inferior esquerdo = bloco 21 do grid 5x5) após salvar.

    Retorna:
        True  -> confirmação encontrada (registro salvo com sucesso).
        False -> confirmação não encontrada dentro do tempo limite.
    """
    opcoes_sucesso = {
        "transacao_completada": [
            "transação completada",
            "transacao completada",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_sucesso,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[21, 22],  # barra de status: inferior esquerdo
        deslocamento_x=0.0,
        n_clicks=0,
        clicar=False,
        modo="neutro",
        ignorar_textos=[],
        roi_attempts=2,
        roi_delay=0.1,
        roi_retry_between_blocks=True,
        stop_checker=lambda: stop_requested,
    )

    if resultado:
        log(
            f"{time.strftime('[%H:%M:%S]')} "
            "[SUCESSO] Mensagem 'Transação Completada.' confirmada."
        )
        return True

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[WARN] 'Transação Completada.' não confirmada no tempo limite."
    )
    return False


def detectar_aviso_registro_duplicado(timeout=None):
    """
    Detecta APENAS o popup de "Tentativa de duplicação de registro".

    Usa frases completas e match exato para evitar falso positivo que
    acabaria removendo um registro salvo corretamente. O modal de erro
    fica no CENTRO da tela (blocos 12/13 do grid 5x5).

    A busca é rápida de propósito: quando o popup existe, ele já está
    na tela no momento da chamada, então não há motivo para esperar.
    """
    if timeout is None:
        timeout = TIMEOUT_DUPLICIDADE

    opcoes_duplicidade = {
        "registro_duplicado": [
            "tentativa de duplicação de registro",
            "tentativa de duplicacao de registro",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_duplicidade,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[12, 13],  # modal de erro no centro da tela
        deslocamento_x=0.0,
        n_clicks=0,
        clicar=False,
        match_parcial=False,  # exige a frase completa
        modo="neutro",
        ignorar_textos=[],
        roi_attempts=1,
        roi_delay=0.05,
        roi_retry_between_blocks=False,
        stop_checker=lambda: stop_requested,
    )

    return bool(resultado)


def tratar_aviso_registro_duplicado(
    delay_confirmacao=None,
    delay_entre_acoes=None,
):
    """
    Fecha o popup de duplicidade e remove o registro atual.

    Deve ser chamada SOMENTE após detectar_aviso_registro_duplicado()
    retornar True.
    """
    if delay_confirmacao is None:
        delay_confirmacao = DELAY_CONFIRMACAO_DUPLICIDADE

    if delay_entre_acoes is None:
        delay_entre_acoes = DELAY_ENTRE_ACOES_DUPLICIDADE

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[WARN] Tentativa de duplicação de registro detectada."
    )

    time.sleep(delay_confirmacao)

    garantir_foco_wms()
    pyautogui.press("enter")

    time.sleep(delay_entre_acoes)

    atalho_wms(remover_registro)
    time.sleep(PAUSA_APOS_REMOVER)

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[INFO] Enter e remover_registro() executados. "
        "Prosseguindo para o próximo item."
    )


# =================== DETECÇÃO / RECUPERAÇÃO DE QUEDA DO WMS =================== #

def detectar_erro_wms_caido(timeout=0.8):
    """
    Detecta o popup de falha do WMS (queda de rede/servidor):
        "FRM-92103: A network error or server failure has occurred.
         You will need to restart your application."

    O modal fica no CENTRO da tela (título 'Forms').
    """
    opcoes_erro = {
        "wms_caiu": [
            "frm-92103",
            "network error or server failure",
            "restart your application",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_erro,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[12, 13, 8, 17],  # modal centralizado
        deslocamento_x=0.0,
        n_clicks=0,
        clicar=False,
        modo="neutro",
        ignorar_textos=[],
        roi_attempts=1,
        roi_delay=0.05,
        roi_retry_between_blocks=False,
        stop_checker=lambda: stop_requested,
    )

    return bool(resultado)


def _renavegar_ate_mapeamento(log_fn=None):
    """
    Após reabrir o WMS, repete a navegação inicial até a tela wmma0020,
    deixando-a pronta para inserir o próximo item.
    """
    if log_fn is None:
        log_fn = log

    time.sleep(1.5)

    # Garante o foco antes de qualquer atalho pós-recuperação.
    try:
        garantir_foco_wms(log_fn=log_fn)
    except FocoPerdidoError as exc:
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[RECUPERACAO] {exc}"
        )
        return False

    acao_limpar()
    time.sleep(0.3)

    detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

    ignorar_textos = ["programas"]
    opcoes_textos = {"programa": ["Programa:"]}

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_textos,
        timeout=25,
        log_fn=log_fn,
        ordem_blocos=[1],
        deslocamento_x=0.8,
        n_clicks=5,
        clicar=True,
        modo="auto",
        ignorar_textos=ignorar_textos,
        stop_checker=lambda: stop_requested,
    )

    if not resultado:
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            "[RECUPERACAO] Tela inicial não confirmada após reabrir o WMS."
        )
        return False

    if not digitar_transacao(TRANSACAO_MAPEAMENTO):
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            "[RECUPERACAO] Falha ao digitar transação após reabrir o WMS."
        )
        return False

    time.sleep(0.5)
    detectar_mudanca_tela(limiar=6, max_espera=3.5, log_fn=log_fn)

    log_fn(
        f"{time.strftime('[%H:%M:%S]')} "
        "[RECUPERACAO] Tela de mapeamento pronta para retomar."
    )
    return True


def recuperar_wms(timeout_wms=300, log_fn=None):
    """
    Reabre o WMS após uma queda (FRM-92103) e re-navega até a tela de
    mapeamento, deixando tudo pronto para reprocessar a MESMA linha.
    """
    if log_fn is None:
        log_fn = log

    # Import tardio para evitar qualquer risco de import circular.
    from interface.wms_launcher import reabrir_wms_apos_queda

    log_fn(
        f"{time.strftime('[%H:%M:%S]')} "
        "[RECUPERACAO] WMS caiu (FRM-92103). Reiniciando aplicação..."
    )

    # reabrir_wms_apos_queda() fecha a janela morta antes de reabrir.
    try:
        sucesso = reabrir_wms_apos_queda(
            log_fn=log_fn,
            timeout=timeout_wms,
        )
    except Exception as exc:
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[RECUPERACAO] Erro ao reabrir o WMS: {exc}"
        )
        return False

    if not sucesso:
        log_fn(
            f"{time.strftime('[%H:%M:%S]')} "
            "[RECUPERACAO] Não foi possível reabrir o WMS."
        )
        return False

    return _renavegar_ate_mapeamento(log_fn=log_fn)


# =================== PROCESSAMENTO DE UMA LINHA =================== #

def _processar_linha(
    i,
    planta,
    item,
    classe,
    priori,
    restricao,
    lastro,
    camada,
    status_cb,
):
    """
    Processa UMA linha do mapeamento.

    Retorna:
        dict com a chave 'status'.

    Lança:
        WMSCaiuError      -> WMS caiu; a linha deve ser reprocessada.
        FocoPerdidoError  -> foco saiu do WMS; digitação abortada.
        AbortarMapeamento -> interrompe todo o mapeamento.
    """
    log(f"[MAPEAMENTO] Linha {i}: item {item}")

    if stop_requested:
        raise AbortarMapeamento("parada_solicitada")

    try:
        if callable(status_cb):
            status_cb(i, "Em progresso", item)
    except Exception as erro:
        log(
            f"[WARN] Não foi possível atualizar o status "
            f"da linha {i}: {erro}"
        )

    # Checkpoint inicial: o WMS já pode ter caído antes de começar.
    if detectar_erro_wms_caido(timeout=0.5):
        raise WMSCaiuError()

    # Garante o foco antes de iniciar a linha.
    garantir_foco_wms()

    # --- Aguarda a tela de item (herdar mapeamento / sobrescrever) --- #
    opcoes_textos_status = {
        "encontrou": [
            "herdar mapeamento",
            "sobrescrever",
        ]
    }

    resultado_status = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_textos_status,
        timeout=60,
        log_fn=log,
        ordem_blocos=[7, 12, 8, 13],
        deslocamento_x=0.0,
        n_clicks=1,
        clicar=True,
        modo="auto",
        ignorar_textos=[],
        roi_attempts=2,
        roi_delay=0.2,
        roi_retry_between_blocks=True,
        stop_checker=lambda: stop_requested,
    )

    texto_status, alvo, (cx, cy) = (
        resultado_status
        if resultado_status
        else (None, None, (None, None))
    )

    if alvo not in ("herdar mapeamento", "sobrescrever"):
        # Antes de abortar, confirma se a causa foi a queda do WMS.
        if detectar_erro_wms_caido(timeout=1.0):
            raise WMSCaiuError()

        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Tela {TRANSACAO_MAPEAMENTO} "
            "não encontrada. Abortando mapeamento..."
        )

        if callable(status_cb):
            try:
                status_cb(i, "Transacao_nao_encontrada", item)
            except Exception:
                pass

        raise AbortarMapeamento(
            "Transacao_nao_encontrada",
            {
                "linha": i,
                "planta": planta,
                "item": item,
                "status": "Transacao_nao_encontrada",
            },
        )

    # --- Pesquisa o item --- #
    atalho_wms(ativar_edicao)
    escrever_wms(str(item))

    hash_ref, _ = detectar_mudanca_tela(
        max_espera=0.1,
        log_fn=lambda *_: None,
    )

    atalho_wms(executar_campo)

    contador = 0
    inicio_pesquisa = time.time()
    item_encontrado = True

    while True:
        if stop_requested:
            raise AbortarMapeamento("parada_solicitada")

        ignorar_textos = ["record 11", "record", "11"]
        opcoes_query = {
            "mensagem_enter_query": [
                "enterquery",
                "enter-query",
                "enter",
                "query",
            ]
        }

        resultado = aguardar_textos(
            TRANSACAO_MAPEAMENTO,
            opcoes_query,
            timeout=0.1,
            log_fn=log,
            ordem_blocos=[21],
            deslocamento_x=0.0,
            n_clicks=0,
            clicar=False,
            modo="neutro",
            ignorar_textos=ignorar_textos,
            stop_checker=lambda: stop_requested,
        )

        hash_ref, mudou = detectar_mudanca_tela(
            hash_ref,
            limiar=7,
            max_espera=0.35,
            intervalo=0.15,
            confirmacoes=2,
            log_fn=log,
        )

        tempo_pesquisa = time.time() - inicio_pesquisa

        if resultado:
            log(
                f"{time.strftime('[%H:%M:%S]')} "
                "[INFO] Mensagem 'Enter-Query' encontrada. "
                "Tentando novamente..."
            )
            contador = 0
            time.sleep(0.3)
            continue

        if mudou:
            atalho_wms(aceitar_alt_o)
            time.sleep(0.3)
            log(
                f"{time.strftime('[%H:%M:%S]')} "
                "[WARN] Mudança de tela detectada. "
                "Executando Alt+O e tentando novamente..."
            )
            contador += 1
            continue

        if not resultado and contador > 1:
            log(
                f"{time.strftime('[%H:%M:%S]')} "
                "[INFO] Mensagem 'Enter-Query' não encontrada. "
                "Item localizado, continuando..."
            )
            break

        if tempo_pesquisa > 10:
            # Antes de declarar "não encontrado", confirma se o WMS caiu.
            if detectar_erro_wms_caido(timeout=0.5):
                raise WMSCaiuError()

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                "[WARN] Item não encontrado após múltiplas "
                "tentativas. Pulando para o próximo..."
            )

            if callable(status_cb):
                try:
                    status_cb(i, "Item_nao_encontrado", item)
                except Exception:
                    pass

            item_encontrado = False
            break

        contador += 1

    if not item_encontrado:
        return {
            "linha": i,
            "planta": planta,
            "item": item,
            "status": "Item_nao_encontrado",
        }

    # --- Preenche os campos e salva --- #
    # Cada escrever_wms() já aguarda PAUSA_APOS_DIGITAR e cada
    # proximo_campo_wms() aguarda PAUSA_APOS_TAB.
    atalho_wms(proximo_bloco)
    atalho_wms(inserir_registro)
    time.sleep(PAUSA_APOS_TAB)

    escrever_wms(str(planta))
    proximo_campo_wms()

    escrever_wms(str(classe))
    proximo_campo_wms()
    time.sleep(0.2)
    proximo_campo_wms()

    escrever_wms(str(priori))
    proximo_campo_wms()

    escrever_wms(str(restricao))
    proximo_campo_wms()

    escrever_wms(str(lastro))
    proximo_campo_wms()

    escrever_wms(str(camada))
    proximo_campo_wms()

    atalho_wms(salvar_registro)

    # ================================================================
    # ORDEM DE VERIFICAÇÃO APÓS SALVAR:
    #   1º) "Transação Completada." -> salvou -> próximo item
    #   2º) queda do WMS (FRM-92103) -> reprocessa a mesma linha
    #   3º) popup de duplicidade -> remover registro -> próximo item
    #   4º) nenhum -> salvamento não confirmado (conferência manual)
    # ================================================================

    if aguardar_transacao_completada(timeout=4.0):
        if callable(status_cb):
            try:
                status_cb(i, "Concluído", item)
            except Exception:
                pass

        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[SUCESSO] Item {item}, planta {planta}, "
            "mapeado e confirmado com sucesso."
        )

        time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
        atalho_wms(proximo_bloco)

        return {
            "linha": i,
            "planta": planta,
            "item": item,
            "status": "Mapeado",
        }

    # Não confirmou o sucesso: o WMS caiu?
    if detectar_erro_wms_caido(timeout=0.8):
        raise WMSCaiuError()

    # Não caiu: foi duplicidade?
    if detectar_aviso_registro_duplicado():
        tratar_aviso_registro_duplicado()

        if callable(status_cb):
            try:
                status_cb(i, "Registro_duplicado", item)
            except Exception:
                pass

        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Item {item}, planta {planta}, "
            "já possui o registro informado. "
            "Seguindo para o próximo item."
        )

        time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
        atalho_wms(proximo_bloco)

        return {
            "linha": i,
            "planta": planta,
            "item": item,
            "status": "Registro_duplicado",
        }

    # Caso incerto: sem sucesso, sem queda e sem duplicidade.
    if callable(status_cb):
        try:
            status_cb(i, "Nao_confirmado", item)
        except Exception:
            pass

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        f"[WARN] Item {item}, planta {planta}: "
        "salvamento não confirmado. Verifique manualmente."
    )

    time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
    atalho_wms(proximo_bloco)

    return {
        "linha": i,
        "planta": planta,
        "item": item,
        "status": "Salvamento_nao_confirmado",
    }


# =================== INICIAR MAPEAMENTO DOS ITENS =================== #

def iniciar_mapeamento_itens(data, status_cb=None):
    log(f"[INFO] Iniciando mapeamento com {len(data)} linhas.")

    if status_cb is None:
        status_cb = status_callback

    resultados = []

    idx = 0                      # índice da linha atual (0-based)
    recuperacoes_por_linha = {}  # idx -> nº de recuperações já tentadas

    while idx < len(data):
        if stop_requested:
            log(
                f"[ABORT] Parada solicitada "
                f"antes de processar a linha {idx + 1}."
            )
            break

        i = idx + 1  # número da linha (1-based) para logs/status
        planta, item, classe, priori, restricao, lastro, camada = data[idx]

        try:
            resultado = _processar_linha(
                i,
                planta,
                item,
                classe,
                priori,
                restricao,
                lastro,
                camada,
                status_cb,
            )

            resultados.append(resultado)
            idx += 1  # só avança quando a linha foi concluída sem queda

        except WMSCaiuError:
            # Conta as recuperações desta MESMA linha.
            tentativas = recuperacoes_por_linha.get(idx, 0) + 1
            recuperacoes_por_linha[idx] = tentativas

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[RECUPERACAO] Linha {i} (item {item}): "
                f"tentativa {tentativas}/{MAX_RECUPERACOES_POR_LINHA} "
                "de reabrir o WMS."
            )

            if tentativas > MAX_RECUPERACOES_POR_LINHA:
                log(
                    f"{time.strftime('[%H:%M:%S]')} "
                    f"[ERRO] Linha {i} (item {item}) falhou após "
                    f"{MAX_RECUPERACOES_POR_LINHA} recuperações. "
                    "Pulando para a próxima..."
                )

                if callable(status_cb):
                    try:
                        status_cb(i, "Falha_wms", item)
                    except Exception:
                        pass

                resultados.append({
                    "linha": i,
                    "planta": planta,
                    "item": item,
                    "status": "Falha_wms",
                })

                idx += 1  # desiste desta linha e segue
                continue

            # Reabre o WMS e re-navega até a tela de mapeamento.
            if not recuperar_wms(log_fn=log):
                log(
                    f"{time.strftime('[%H:%M:%S]')} "
                    "[ERRO] Não foi possível recuperar o WMS. "
                    "Encerrando mapeamento."
                )
                return resultados

            # NÃO incrementa idx: reprocessa a mesma linha.
            continue

        except FocoPerdidoError as exc:
            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[ERRO] Foco perdido na linha {i} (item {item}): {exc}"
            )

            if callable(status_cb):
                try:
                    status_cb(i, "Foco_perdido", item)
                except Exception:
                    pass

            resultados.append({
                "linha": i,
                "planta": planta,
                "item": item,
                "status": "Foco_perdido",
            })

            idx += 1
            continue

        except AbortarMapeamento as ab:
            if ab.resultado_parcial:
                resultados.append(ab.resultado_parcial)

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[ABORT] Mapeamento interrompido: {ab.motivo}."
            )
            break

    return resultados


# =================== ORQUESTRAÇÃO =================== #

def iniciar_automacao(
    data=None,
    planta=None,
    log_fn=print,
    status_callback_fn=None,
):
    global logger, status_callback

    logger = log_fn

    if status_callback_fn is not None:
        status_callback = status_callback_fn

    clear_stop()

    registrar_evento_execucao(
        "wmma0020_mapeamento",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
    )

    resultados = []

    log_fn("[INFO] Iniciando automação...")

    # Garante o foco no WMS antes de qualquer atalho.
    try:
        garantir_foco_wms(log_fn=log_fn)
    except FocoPerdidoError as exc:
        registrar_evento_execucao(
            "wmma0020_mapeamento",
            "fim",
            status="erro",
            detalhe=str(exc),
        )
        log_fn(f"[ERRO] {exc}")
        return []

    time.sleep(0.3)
    acao_limpar()
    time.sleep(0.3)

    hash_ref, _ = detectar_mudanca_tela(
        max_espera=0.1,
        log_fn=lambda *_: None,
    )

    ignorar_textos = ["programas"]
    opcoes_textos = {"programa": ["Programa:"]}

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes_textos,
        timeout=25,
        log_fn=log,
        ordem_blocos=[1],
        deslocamento_x=0.8,
        n_clicks=5,
        clicar=True,
        modo="auto",
        ignorar_textos=ignorar_textos,
        stop_checker=lambda: stop_requested,
    )

    if not resultado:
        registrar_evento_execucao(
            "wmma0020_mapeamento",
            "fim",
            status="erro",
            detalhe="Tela inicial não confirmada",
        )

        log("[ERRO] Tela inicial não confirmada.")
        return []

    if data and len(data) > 0:
        log(
            f"[INFO] Dados fornecidos manualmente "
            f"({len(data)} linhas)."
        )

        if not digitar_transacao(TRANSACAO_MAPEAMENTO):
            registrar_evento_execucao(
                "wmma0020_mapeamento",
                "fim",
                status="erro",
                detalhe=(
                    f"Falha ao digitar transação "
                    f"{TRANSACAO_MAPEAMENTO}"
                ),
            )

            log(
                f"[ERRO] Falha ao digitar transação "
                f"{TRANSACAO_MAPEAMENTO}."
            )

            return []

        time.sleep(0.5)

        hash_ref, mudou = detectar_mudanca_tela(
            hash_ref,
            limiar=6,
            max_espera=3.5,
            log_fn=log_fn,
        )

        if not mudou:
            log_fn(
                "[WARN] Nenhuma mudança visual detectada "
                "após digitação."
            )

        resultados = iniciar_mapeamento_itens(
            data,
            status_cb=status_callback,
        )

    else:
        log_fn("[INFO] Nenhum dado fornecido. Encerrando...")

    total_sucesso = sum(
        1 for r in resultados if r.get("status") == "Mapeado"
    )
    total_duplicados = sum(
        1 for r in resultados if r.get("status") == "Registro_duplicado"
    )
    total_nao_encontrados = sum(
        1 for r in resultados if r.get("status") == "Item_nao_encontrado"
    )
    total_nao_confirmados = sum(
        1 for r in resultados if r.get("status") == "Salvamento_nao_confirmado"
    )
    total_falha_wms = sum(
        1 for r in resultados if r.get("status") == "Falha_wms"
    )
    total_foco_perdido = sum(
        1 for r in resultados if r.get("status") == "Foco_perdido"
    )

    registrar_evento_execucao(
        "wmma0020_mapeamento",
        "fim",
        status="sucesso",
        linhas_processadas=len(resultados),
        linhas_mapeadas=total_sucesso,
        registros_duplicados=total_duplicados,
        itens_nao_encontrados=total_nao_encontrados,
        salvamentos_nao_confirmados=total_nao_confirmados,
        falhas_wms=total_falha_wms,
        focos_perdidos=total_foco_perdido,
    )

    log_fn(
        "[INFO] Automação finalizada. "
        f"Mapeados: {total_sucesso}. "
        f"Duplicados: {total_duplicados}. "
        f"Não encontrados: {total_nao_encontrados}. "
        f"Não confirmados: {total_nao_confirmados}. "
        f"Falhas WMS: {total_falha_wms}. "
        f"Foco perdido: {total_foco_perdido}."
    )

    return resultados


if __name__ == "__main__":
    iniciar_automacao()
