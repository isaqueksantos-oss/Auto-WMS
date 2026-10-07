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
    campo_anterior,
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

MAX_RECUPERACOES_POR_LINHA = 3


# =================== AJUSTE FINO DE TEMPOS =================== #

INTERVALO_DIGITACAO = 0.15
PAUSA_APOS_DIGITAR = 0.15
PAUSA_APOS_TAB = 0.15

# Pausa após F7 (entrar em modo consulta) no bloco de classes.
PAUSA_APOS_ENTER_QUERY = 0.35

# Pausa após F8 (executar a consulta), antes de ler o resultado.
PAUSA_APOS_EXECUTAR_CONSULTA = 0.40

# Tempo máximo de busca pela mensagem na barra de status.
TIMEOUT_BARRA_STATUS = 1.5

PAUSA_APOS_REMOVER = 0.30
PAUSA_APOS_LIMPAR = 0.30
PAUSA_ANTES_PROXIMO_BLOCO = 0.20


TITULOS_WMS = (
    "wms americanas",
)

TITULOS_PROIBIDOS = (
    "auto wms",
    "visual studio code",
    "excel",
    "outlook",
    "chrome",
    "edge",
    "bloco de notas",
    "notepad",
    "teams",
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


class AbortarRemocao(Exception):
    """Interrompe toda a remoção (ex.: tela não encontrada ou parada)."""

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
    """
    Valida se as linhas coladas possuem a quantidade mínima de colunas.

    Para a remoção são esperadas 3 colunas: planta, item e classe.
    """
    if dados:
        return len(dados[0]) >= tamanho_esperado

    if planta:
        return len(planta) >= tamanho_esperado

    return False


def atualizar_interface_threadsafe(root, callback, lista):
    if callback and root:
        root.after(0, lambda: callback(lista))


# =================== SEGURANÇA DE FOCO =================== #

def _titulo_janela_ativa():
    try:
        janela = gw.getActiveWindow()
        if janela and janela.title:
            return janela.title.strip().lower()
    except Exception:
        pass
    return ""


def janela_wms_esta_ativa():
    titulo = _titulo_janela_ativa()

    if not titulo:
        return False

    for proibido in TITULOS_PROIBIDOS:
        if proibido in titulo:
            return False

    return any(aceito in titulo for aceito in TITULOS_WMS)


def garantir_foco_wms(tentativas=3, log_fn=None):
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
        "Operação abortada para não agir na janela errada."
    )


def escrever_wms(texto, interval=None, pausa_final=None):
    if interval is None:
        interval = INTERVALO_DIGITACAO

    if pausa_final is None:
        pausa_final = PAUSA_APOS_DIGITAR

    garantir_foco_wms()

    pyautogui.write(str(texto), interval=interval)
    time.sleep(pausa_final)

    if not janela_wms_esta_ativa():
        titulo_atual = _titulo_janela_ativa() or "(desconhecida)"
        raise FocoPerdidoError(
            f"O foco mudou para '{titulo_atual}' durante a digitação "
            f"de '{texto}'."
        )

    return True


def atalho_wms(func, *args, **kwargs):
    garantir_foco_wms()
    return func(*args, **kwargs)


def proximo_campo_wms():
    atalho_wms(proximo_campo)
    time.sleep(PAUSA_APOS_TAB)


def limpar_shift_f4():
    """
    SHIFT+F4 - limpa os valores digitados no bloco de consulta.

    Não existe no base_automation, por isso é definido aqui.
    """
    garantir_foco_wms()
    pyautogui.hotkey("shift", "f4")
    time.sleep(PAUSA_APOS_LIMPAR)


# =================== DETECÇÃO DE TELA =================== #

def capturar_hash_tela():
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

    log_fn("[MUDANCA] Nenhuma mudança detectada dentro do tempo limite.")
    return hash_ref, False


def detectar_pesquisa_sem_registro(timeout=None):
    """
    Detecta a mensagem da barra de status (canto inferior esquerdo):
        "A pesquisa não retornou registro algum."

    Indica que a combinação planta + classe não existe para o item.
    """
    if timeout is None:
        timeout = TIMEOUT_BARRA_STATUS

    opcoes = {
        "sem_registro": [
            "a pesquisa não retornou registro algum",
            "a pesquisa nao retornou registro algum",
            "não retornou registro algum",
            "nao retornou registro algum",
            "não retornou registro",
            "nao retornou registro",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        opcoes,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[21, 22],  # barra de status inferior esquerda
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

    return bool(resultado)


def aguardar_transacao_completada(timeout=4.0):
    """
    Confirma "Transação Completada." na barra de status após salvar
    a remoção.
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
        ordem_blocos=[21, 22],
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


def detectar_erro_wms_caido(timeout=0.8):
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
        ordem_blocos=[12, 13, 8, 17],
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
    if log_fn is None:
        log_fn = log

    time.sleep(1.5)

    try:
        garantir_foco_wms(log_fn=log_fn)
    except FocoPerdidoError as exc:
        log_fn(f"{time.strftime('[%H:%M:%S]')} [RECUPERACAO] {exc}")
        return False

    acao_limpar()
    time.sleep(0.3)

    detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        {"programa": ["Programa:"]},
        timeout=25,
        log_fn=log_fn,
        ordem_blocos=[1],
        deslocamento_x=0.8,
        n_clicks=5,
        clicar=True,
        modo="auto",
        ignorar_textos=["programas"],
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
        "[RECUPERACAO] Tela pronta para retomar."
    )
    return True


def recuperar_wms(timeout_wms=300, log_fn=None):
    if log_fn is None:
        log_fn = log

    from interface.wms_launcher import reabrir_wms_apos_queda

    log_fn(
        f"{time.strftime('[%H:%M:%S]')} "
        "[RECUPERACAO] WMS caiu (FRM-92103). Reiniciando aplicação..."
    )

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

def _processar_linha(i, planta, item, classe, status_cb):
    """
    Remove UM mapeamento (item + planta + classe).

    Fluxo no bloco de classes:
        Ctrl+PgDn -> F7 -> planta -> TAB -> classe -> F8
            encontrou  -> Shift+F6 -> F10 -> próximo item
            não achou  -> Shift+F4 -> F8  -> próximo item

    Retorna:
        dict com a chave 'status'.
    """
    log(f"[REMOCAO] Linha {i}: item {item} | planta {planta} | {classe}")

    if stop_requested:
        raise AbortarRemocao("parada_solicitada")

    try:
        if callable(status_cb):
            status_cb(i, "Em progresso", item)
    except Exception as erro:
        log(f"[WARN] Falha ao atualizar status da linha {i}: {erro}")

    if detectar_erro_wms_caido(timeout=0.5):
        raise WMSCaiuError()

    garantir_foco_wms()

    # --- Aguarda a tela de item --- #
    resultado_status = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        {"encontrou": ["herdar mapeamento", "sobrescrever"]},
        timeout=60,
        log_fn=log,
        ordem_blocos=[7, 12, 8, 13],
        deslocamento_x=0.0,
        n_clicks=1,
        clicar=False,
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
        if detectar_erro_wms_caido(timeout=1.0):
            raise WMSCaiuError()

        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Tela {TRANSACAO_MAPEAMENTO} não encontrada. "
            "Abortando remoção..."
        )

        if callable(status_cb):
            try:
                status_cb(i, "Transacao_nao_encontrada", item)
            except Exception:
                pass

        raise AbortarRemocao(
            "Transacao_nao_encontrada",
            {
                "linha": i,
                "planta": planta,
                "item": item,
                "classe": classe,
                "status": "Transacao_nao_encontrada",
            },
        )

    # --- Pesquisa o item no bloco de cima --- #
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
            raise AbortarRemocao("parada_solicitada")

        resultado = aguardar_textos(
            TRANSACAO_MAPEAMENTO,
            {
                "mensagem_enter_query": [
                    "enterquery",
                    "enter-query",
                    "enter",
                    "query",
                ]
            },
            timeout=0.1,
            log_fn=log,
            ordem_blocos=[21],
            deslocamento_x=0.0,
            n_clicks=0,
            clicar=False,
            modo="neutro",
            ignorar_textos=["record 11", "record", "11"],
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
            contador = 0
            time.sleep(0.3)
            continue

        if mudou:
            atalho_wms(aceitar_alt_o)
            time.sleep(0.3)
            contador += 1
            continue

        if not resultado and contador > 1:
            break

        if tempo_pesquisa > 10:
            if detectar_erro_wms_caido(timeout=0.5):
                raise WMSCaiuError()

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                "[WARN] Item não encontrado. Pulando..."
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
            "classe": classe,
            "status": "Item_nao_encontrado",
        }

    # ================================================================
    # BLOCO DE CLASSES: consulta pela combinação exata planta + classe
    # ================================================================

    # Ctrl+PgDn -> desce para "Classes de Locais associadas".
    atalho_wms(proximo_bloco)
    time.sleep(PAUSA_APOS_TAB)

    # F7 -> entra em modo consulta (Enter-Query).
    atalho_wms(ativar_edicao)
    time.sleep(PAUSA_APOS_ENTER_QUERY)

    # Preenche os critérios da consulta.
    escrever_wms(str(planta))
    proximo_campo_wms()
    escrever_wms(str(classe))

    # F8 -> executa a consulta.
    atalho_wms(executar_campo)
    time.sleep(PAUSA_APOS_EXECUTAR_CONSULTA)

    # O WMS pode ter caído durante a consulta.
    if detectar_erro_wms_caido(timeout=0.5):
        raise WMSCaiuError()

    # --- Caso 1: combinação não existe --- #
    if detectar_pesquisa_sem_registro():
        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Mapeamento {planta}/{classe} não existe "
            f"para o item {item}. Nada a remover."
        )

        # Shift+F4 -> limpa os valores digitados na consulta.
        limpar_shift_f4()

        # F8 -> devolve a tela ao estado normal.
        atalho_wms(executar_campo)
        time.sleep(PAUSA_APOS_EXECUTAR_CONSULTA)

        if callable(status_cb):
            try:
                status_cb(i, "Mapeamento_inexistente", item)
            except Exception:
                pass

        # Ctrl+PgDn -> volta ao bloco de itens para o próximo item.
        time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
        atalho_wms(proximo_bloco)

        return {
            "linha": i,
            "planta": planta,
            "item": item,
            "classe": classe,
            "status": "Mapeamento_inexistente",
        }

    # --- Caso 2: registro encontrado -> remover --- #
    # Shift+F6 -> apaga o registro localizado.
    atalho_wms(remover_registro)
    time.sleep(PAUSA_APOS_REMOVER)

    # F10 -> salva a remoção.
    atalho_wms(salvar_registro)

    if aguardar_transacao_completada(timeout=4.0):
        if callable(status_cb):
            try:
                status_cb(i, "Concluído", item)
            except Exception:
                pass

        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[SUCESSO] Mapeamento {planta}/{classe} removido "
            f"do item {item}."
        )

        time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
        atalho_wms(proximo_bloco)

        return {
            "linha": i,
            "planta": planta,
            "item": item,
            "classe": classe,
            "status": "Removido",
        }

    if detectar_erro_wms_caido(timeout=0.8):
        raise WMSCaiuError()

    if callable(status_cb):
        try:
            status_cb(i, "Nao_confirmado", item)
        except Exception:
            pass

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        f"[WARN] Item {item}: remoção não confirmada. "
        "Verifique manualmente."
    )

    time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)
    atalho_wms(proximo_bloco)

    return {
        "linha": i,
        "planta": planta,
        "item": item,
        "classe": classe,
        "status": "Remocao_nao_confirmada",
    }


# =================== LOOP PRINCIPAL =================== #

def iniciar_remocao_itens(data, status_cb=None):
    log(f"[INFO] Iniciando remoção com {len(data)} linhas.")

    if status_cb is None:
        status_cb = status_callback

    resultados = []

    idx = 0
    recuperacoes_por_linha = {}

    while idx < len(data):
        if stop_requested:
            log(f"[ABORT] Parada solicitada antes da linha {idx + 1}.")
            break

        i = idx + 1
        planta, item, classe = data[idx][:3]

        try:
            resultado = _processar_linha(i, planta, item, classe, status_cb)
            resultados.append(resultado)
            idx += 1

        except WMSCaiuError:
            tentativas = recuperacoes_por_linha.get(idx, 0) + 1
            recuperacoes_por_linha[idx] = tentativas

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[RECUPERACAO] Linha {i} (item {item}): "
                f"tentativa {tentativas}/{MAX_RECUPERACOES_POR_LINHA}."
            )

            if tentativas > MAX_RECUPERACOES_POR_LINHA:
                log(
                    f"{time.strftime('[%H:%M:%S]')} "
                    f"[ERRO] Linha {i} falhou após "
                    f"{MAX_RECUPERACOES_POR_LINHA} recuperações."
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
                    "classe": classe,
                    "status": "Falha_wms",
                })

                idx += 1
                continue

            if not recuperar_wms(log_fn=log):
                log(
                    f"{time.strftime('[%H:%M:%S]')} "
                    "[ERRO] Não foi possível recuperar o WMS."
                )
                return resultados

            continue

        except FocoPerdidoError as exc:
            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[ERRO] Foco perdido na linha {i}: {exc}"
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
                "classe": classe,
                "status": "Foco_perdido",
            })

            idx += 1
            continue

        except AbortarRemocao as ab:
            if ab.resultado_parcial:
                resultados.append(ab.resultado_parcial)

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[ABORT] Remoção interrompida: {ab.motivo}."
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
        "wmma0020_remover_mapeamento",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
    )

    resultados = []

    log_fn("[INFO] Iniciando automação de remoção...")

    try:
        garantir_foco_wms(log_fn=log_fn)
    except FocoPerdidoError as exc:
        registrar_evento_execucao(
            "wmma0020_remover_mapeamento",
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

    resultado = aguardar_textos(
        TRANSACAO_MAPEAMENTO,
        {"programa": ["Programa:"]},
        timeout=25,
        log_fn=log,
        ordem_blocos=[1],
        deslocamento_x=0.8,
        n_clicks=5,
        clicar=True,
        modo="auto",
        ignorar_textos=["programas"],
        stop_checker=lambda: stop_requested,
    )

    if not resultado:
        registrar_evento_execucao(
            "wmma0020_remover_mapeamento",
            "fim",
            status="erro",
            detalhe="Tela inicial não confirmada",
        )
        log("[ERRO] Tela inicial não confirmada.")
        return []

    if data and len(data) > 0:
        log(f"[INFO] Dados fornecidos ({len(data)} linhas).")

        if not digitar_transacao(TRANSACAO_MAPEAMENTO):
            registrar_evento_execucao(
                "wmma0020_remover_mapeamento",
                "fim",
                status="erro",
                detalhe=f"Falha ao digitar transação {TRANSACAO_MAPEAMENTO}",
            )
            log(f"[ERRO] Falha ao digitar transação {TRANSACAO_MAPEAMENTO}.")
            return []

        time.sleep(0.5)

        hash_ref, mudou = detectar_mudanca_tela(
            hash_ref,
            limiar=6,
            max_espera=3.5,
            log_fn=log_fn,
        )

        if not mudou:
            log_fn("[WARN] Nenhuma mudança visual detectada após digitação.")

        resultados = iniciar_remocao_itens(data, status_cb=status_callback)

    else:
        log_fn("[INFO] Nenhum dado fornecido. Encerrando...")

    total_removidos = sum(
        1 for r in resultados if r.get("status") == "Removido"
    )
    total_inexistentes = sum(
        1 for r in resultados if r.get("status") == "Mapeamento_inexistente"
    )
    total_nao_encontrados = sum(
        1 for r in resultados if r.get("status") == "Item_nao_encontrado"
    )
    total_nao_confirmados = sum(
        1 for r in resultados if r.get("status") == "Remocao_nao_confirmada"
    )
    total_falha_wms = sum(
        1 for r in resultados if r.get("status") == "Falha_wms"
    )
    total_foco_perdido = sum(
        1 for r in resultados if r.get("status") == "Foco_perdido"
    )

    registrar_evento_execucao(
        "wmma0020_remover_mapeamento",
        "fim",
        status="sucesso",
        linhas_processadas=len(resultados),
        removidos=total_removidos,
        mapeamentos_inexistentes=total_inexistentes,
        itens_nao_encontrados=total_nao_encontrados,
        remocoes_nao_confirmadas=total_nao_confirmados,
        falhas_wms=total_falha_wms,
        focos_perdidos=total_foco_perdido,
    )

    log_fn(
        "[INFO] Automação de remoção finalizada. "
        f"Removidos: {total_removidos}. "
        f"Inexistentes: {total_inexistentes}. "
        f"Não encontrados: {total_nao_encontrados}. "
        f"Não confirmados: {total_nao_confirmados}. "
        f"Falhas WMS: {total_falha_wms}. "
        f"Foco perdido: {total_foco_perdido}."
    )

    return resultados


if __name__ == "__main__":
    iniciar_automacao()
