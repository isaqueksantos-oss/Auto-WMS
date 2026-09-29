"""
Base compartilhada das automações da transação WMMA0031
(Mapeamento Local Cativo).

Contém tudo que é comum às três macros:
    - segurança de foco;
    - digitação, colagem e atalhos protegidos;
    - navegação específica da tela wmma0031;
    - detecção de mensagens da barra de status e de popups;
    - detecção e recuperação de queda do WMS;
    - pesquisa do item no bloco de cima;
    - loop principal com retomada no item que parou.

Os módulos wmma0031_cativar, wmma0031_descativar e
wmma0031_alterar_ponto_minimo importam daqui.
"""

import time

import pyautogui
import pyperclip
import pygetwindow as gw
from PIL import Image
import imagehash
import numpy as np

from interface.automations.base_automation import (
    aceitar_alt_o,
    acao_limpar,
    aguardar_textos,
    ativar_edicao,
    campo_anterior,
    cancelar_consulta,
    colar_ctrl_v,
    copiar_para_clipboard,
    digitar_transacao,
    executar_campo,
    inserir_registro,
    limpar_campo,
    proximo_campo,
    proximo_bloco,
    remover_registro,
    salvar_registro,
)


# =================== IDENTIFICAÇÃO DA TRANSAÇÃO =================== #

TRANSACAO = "wmma0031"

MAX_RECUPERACOES_POR_LINHA = 3


# =================== NAVEGAÇÃO DA TELA WMMA0031 =================== #
# Bloco "Locais": Planta | (descrição) | Local | Endereço | Classe |
#                 Qt. Mínima | Ressup. Bloqueado
#
# O TAB após o item leva ao campo PLANTA, que não é usado nesta tela.
# Mais um TAB chega ao campo LOCAL.
TABS_PLANTA_ATE_LOCAL = 1

# A partir do campo LOCAL, 3 Shift+TAB chegam ao campo QT. MÍNIMA.
# Usado na cativação, após o TAB que confirma o local.
SHIFT_TABS_LOCAL_ATE_QT_MINIMA = 3

# A partir do campo PLANTA, 2 Shift+TAB chegam ao campo QT. MÍNIMA.
# Usado após o F8 da consulta, quando o cursor volta ao início do
# registro localizado.
SHIFT_TABS_PLANTA_ATE_QT_MINIMA = 2
# =================== AJUSTE FINO DE TEMPOS =================== #

INTERVALO_DIGITACAO = 0.04
PAUSA_APOS_DIGITAR = 0.15
PAUSA_APOS_TAB = 0.10

PAUSA_APOS_ENTER_QUERY = 0.30
PAUSA_APOS_CANCELAR_CONSULTA = 0.30
PAUSA_APOS_EXECUTAR_CONSULTA = 0.50
PAUSA_APOS_INSERIR_REGISTRO = 0.25

# Pausa após o TAB que confirma o item e leva o cursor ao bloco de
# Locais (campo Planta).
PAUSA_APOS_CONFIRMAR_ITEM = 0.50

# Pausa após o TAB que confirma o local e dispara o preenchimento
# automático de endereço e classe.
PAUSA_APOS_CONFIRMAR_LOCAL = 0.40

TIMEOUT_BARRA_STATUS = 1.5

# Tratamento de popups (erro de duplicidade e diálogo de salvamento).
PAUSA_CONFIRMAR_POPUP = 0.25
PAUSA_ENTRE_POPUPS = 0.50

PAUSA_APOS_LIMPAR_CAMPO = 0.15
PAUSA_APOS_LIMPAR = 0.30
PAUSA_APOS_REMOVER = 0.30
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
)


# =================== ESTADO GLOBAL =================== #

logger = print
stop_requested = False


def request_stop():
    global stop_requested
    stop_requested = True


def clear_stop():
    global stop_requested
    stop_requested = False


def set_logger(log_fn):
    global logger
    logger = log_fn


def log(message):
    try:
        logger(message)
    except Exception:
        print(message)


def verificar_tamanho_lista(dados, planta=None, *, tamanho_esperado):
    """Valida a quantidade mínima de colunas das linhas coladas."""
    if dados:
        return len(dados[0]) >= tamanho_esperado

    if planta:
        return len(planta) >= tamanho_esperado

    return False


# =================== EXCEÇÕES DE CONTROLE =================== #

class WMSCaiuError(Exception):
    """Sinaliza que o WMS caiu (FRM-92103) e precisa ser reiniciado."""
    pass


class FocoPerdidoError(Exception):
    """A janela do WMS não pôde ser focada; digitar seria inseguro."""
    pass


class AbortarExecucao(Exception):
    """Interrompe toda a execução (tela não encontrada ou parada)."""

    def __init__(self, motivo, resultado_parcial=None):
        super().__init__(motivo)
        self.motivo = motivo
        self.resultado_parcial = resultado_parcial


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
def detectar_clipboard_negado(timeout=1.0):
    """
    Detecta o popup do Forms:
        "FRM-92220: access to system clipboard denied"

    O Java bloqueia o acesso ao clipboard e o Ctrl+V não chega a colar
    o valor, então além de fechar o aviso é preciso refazer a entrada
    por digitação.
    """
    opcoes = {
        "clipboard_negado": [
            "frm-92220",
            "access to system clipboard denied",
            "system clipboard denied",
            "clipboard denied",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO,
        opcoes,
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


def fechar_popup_clipboard():
    """
    Fecha o aviso FRM-92220 confirmando o botão OK.

    O popup costuma abrir sem foco de teclado, por isso a rotina
    clica no centro da janela antes de pressionar Enter.
    """
    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[WARN] FRM-92220: acesso ao clipboard negado."
    )

    garantir_foco_wms()

    # Dá foco ao popup clicando no centro da tela e confirma com Enter.
    largura, altura = pyautogui.size()
    pyautogui.click(largura // 2, altura // 2)
    time.sleep(PAUSA_CONFIRMAR_POPUP)

    pyautogui.press("enter")
    time.sleep(PAUSA_ENTRE_POPUPS)

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[INFO] Aviso de clipboard fechado."
    )

def colar_wms(texto):
    """
    Cola um valor via clipboard (Ctrl+V), com o foco garantido.

    Se o Java bloquear o acesso (FRM-92220), fecha o aviso e refaz a
    entrada por digitação — o Ctrl+V negado não chega a preencher o
    campo.
    """
    garantir_foco_wms()

    if not copiar_para_clipboard(str(texto)):
        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[WARN] Clipboard indisponível para '{texto}'. Digitando..."
        )
        return escrever_wms(str(texto))

    atalho_wms(colar_ctrl_v)
    time.sleep(PAUSA_APOS_DIGITAR)

    # O Java pode recusar o acesso ao clipboard.
    if detectar_clipboard_negado():
        fechar_popup_clipboard()

        # Garante o campo vazio antes de redigitar.
        limpar_campo_wms()
        return escrever_wms(str(texto))

    if not janela_wms_esta_ativa():
        titulo_atual = _titulo_janela_ativa() or "(desconhecida)"
        raise FocoPerdidoError(
            f"O foco mudou para '{titulo_atual}' durante a colagem "
            f"de '{texto}'."
        )

    return True

def atalho_wms(func, *args, **kwargs):
    garantir_foco_wms()
    return func(*args, **kwargs)


def proximo_campo_wms():
    atalho_wms(proximo_campo)
    time.sleep(PAUSA_APOS_TAB)


def campo_anterior_wms():
    atalho_wms(campo_anterior)
    time.sleep(PAUSA_APOS_TAB)


def limpar_campo_wms():
    """Ctrl+U - limpa o conteúdo do campo sob o cursor."""
    atalho_wms(limpar_campo)
    time.sleep(PAUSA_APOS_LIMPAR_CAMPO)


def limpar_shift_f4():
    """SHIFT+F4 - limpa os valores digitados no bloco de consulta."""
    garantir_foco_wms()
    pyautogui.hotkey("shift", "f4")
    time.sleep(PAUSA_APOS_LIMPAR)


def resetar_formulario():
    """
    F7 + Ctrl+Q - devolve o formulário ao estado inicial.

    Usado entre um item e outro na cativação: sem esse reset o bloco
    de Locais não aceita a inclusão quando o item ainda não possui
    nenhum local cativo.
    """
    atalho_wms(ativar_edicao)
    time.sleep(PAUSA_APOS_ENTER_QUERY)

    atalho_wms(cancelar_consulta)
    time.sleep(PAUSA_APOS_CANCELAR_CONSULTA)


# =================== NAVEGAÇÃO ESPECÍFICA DA WMMA0031 =================== #

def colar_item_e_descer(item):
    """
    Cola o item e confirma com TAB.

    O cursor precisa estar no campo Item (tela recém-aberta ou logo
    após F7 + Ctrl+Q). O TAB confirma o item e leva o cursor direto ao
    campo PLANTA do bloco de Locais — não há F8 nem Ctrl+PgDn neste
    fluxo.
    """
    colar_wms(str(item))

    proximo_campo_wms()
    time.sleep(PAUSA_APOS_CONFIRMAR_ITEM)


def ir_da_planta_para_local():
    """
    TAB(s) do campo PLANTA até o campo LOCAL.

    Usado quando o cursor já está no bloco de Locais.
    """
    for _ in range(TABS_PLANTA_ATE_LOCAL):
        proximo_campo_wms()


def descer_para_bloco_locais():
    """
    Ctrl+PgDn e, em seguida, TAB para sair do campo Planta e chegar ao
    campo LOCAL.

    Usado pelas macros de descativação e alteração de ponto mínimo,
    que pesquisam o item com F7/F8 e depois trocam de bloco.
    """
    atalho_wms(proximo_bloco)
    time.sleep(PAUSA_APOS_TAB)

    ir_da_planta_para_local()


def confirmar_local_digitado():
    """
    TAB que confirma o local e dispara o preenchimento automático de
    endereço e classe pelo WMS.
    """
    proximo_campo_wms()
    time.sleep(PAUSA_APOS_CONFIRMAR_LOCAL)


def ir_do_local_para_qt_minima():
    """
    A partir do campo LOCAL, 3 Shift+TAB chegam ao campo QT. MÍNIMA.
    """
    for _ in range(SHIFT_TABS_LOCAL_ATE_QT_MINIMA):
        campo_anterior_wms()

def ir_da_planta_para_qt_minima():
    """
    A partir do campo PLANTA, 2 Shift+TAB chegam ao campo QT. MÍNIMA.

    Usado após o F8 da consulta, quando o cursor retorna ao início do
    registro localizado.
    """
    for _ in range(SHIFT_TABS_PLANTA_ATE_QT_MINIMA):
        campo_anterior_wms()


def voltar_para_bloco_itens():
    """
    Garante que o cursor esteja no bloco de itens antes do próximo item.

    Na wmma0031 o F10 (salvar) já devolve o foco ao bloco de itens,
    como se executasse F10 + PgUp. Por isso, após um salvamento
    bem-sucedido NÃO se deve chamar proximo_bloco() — isso desceria
    novamente para o bloco de locais.
    """
    time.sleep(PAUSA_ANTES_PROXIMO_BLOCO)


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
    Detecta "A pesquisa não retornou registro algum." na barra de status.
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
        TRANSACAO,
        opcoes,
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

    return bool(resultado)


def aguardar_transacao_completada(timeout=4.0):
    """Confirma "Transação Completada." na barra de status após salvar."""
    opcoes_sucesso = {
        "transacao_completada": [
            "transação completada",
            "transacao completada",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO,
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


def detectar_registro_duplicado(timeout=0.8):
    """Detecta o popup de tentativa de duplicação de registro."""
    opcoes = {
        "registro_duplicado": [
            "tentativa de duplicação de registro",
            "tentativa de duplicacao de registro",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO,
        opcoes,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[12, 13],
        deslocamento_x=0.0,
        n_clicks=0,
        clicar=False,
        match_parcial=False,
        modo="neutro",
        ignorar_textos=[],
        roi_attempts=1,
        roi_delay=0.05,
        roi_retry_between_blocks=False,
        stop_checker=lambda: stop_requested,
    )

    return bool(resultado)


def detectar_dialogo_salvar_alteracoes(timeout=2.0):
    """
    Detecta o diálogo do Forms:
        "Do you want to save the changes you have made?"

    Aparece após confirmar o erro de duplicidade e também ao sair de
    um bloco que tenha alterações pendentes.
    """
    opcoes = {
        "salvar_alteracoes": [
            "do you want to save the changes",
            "save the changes you have made",
            "deseja salvar as alterações",
            "deseja salvar as alteracoes",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO,
        opcoes,
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[12, 13, 8, 17],
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


def responder_nao_ao_salvamento():
    """
    Responde "No" ao diálogo "Do you want to save the changes...".

    O botão Yes vem em foco, então TAB move para No e Enter confirma.
    """
    garantir_foco_wms()

    pyautogui.press("tab")      # Yes -> No
    time.sleep(PAUSA_CONFIRMAR_POPUP)

    pyautogui.press("enter")    # confirma No
    time.sleep(PAUSA_ENTRE_POPUPS)

    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[INFO] Alterações descartadas (No)."
    )


def descartar_alteracoes_pendentes(timeout=1.0):
    """
    Se o Forms perguntar sobre salvar alterações, responde "No".

    Útil antes de trocar de bloco ou de item, evitando que a automação
    fique presa em um diálogo inesperado.

    Retorna True se o diálogo apareceu e foi tratado.
    """
    if detectar_dialogo_salvar_alteracoes(timeout=timeout):
        responder_nao_ao_salvamento()
        return True

    return False


def tratar_registro_duplicado():
    """
    Trata o erro de duplicação na wmma0031.

    Sequência observada na tela:
        1. Popup "Erro": "Tentativa de duplicação de registro."
           -> Enter confirma o botão OK.
        2. Popup "Forms": "Do you want to save the changes you have
           made?" com o botão Yes em foco.
           -> TAB move para No, Enter confirma.

    Descartar as alterações é o correto aqui: o registro já existe,
    então não há nada a gravar.
    """
    log(
        f"{time.strftime('[%H:%M:%S]')} "
        "[WARN] Tentativa de duplicação de registro detectada."
    )

    # 1) Fecha o popup de erro (botão OK).
    time.sleep(PAUSA_CONFIRMAR_POPUP)
    garantir_foco_wms()
    pyautogui.press("enter")
    time.sleep(PAUSA_ENTRE_POPUPS)

    # 2) Responde "No" ao diálogo de salvamento.
    if detectar_dialogo_salvar_alteracoes():
        responder_nao_ao_salvamento()
    else:
        log(
            f"{time.strftime('[%H:%M:%S]')} "
            "[INFO] Diálogo de salvamento não apareceu."
        )


def detectar_erro_wms_caido(timeout=0.8):
    opcoes_erro = {
        "wms_caiu": [
            "frm-92103",
            "network error or server failure",
            "restart your application",
        ]
    }

    resultado = aguardar_textos(
        TRANSACAO,
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


# =================== RECUPERAÇÃO DE QUEDA DO WMS =================== #

def _renavegar_ate_transacao(log_fn=None):
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
        TRANSACAO,
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

    if not digitar_transacao(TRANSACAO):
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

    return _renavegar_ate_transacao(log_fn=log_fn)


# =================== PESQUISA DO ITEM (BLOCO DE CIMA) =================== #

def pesquisar_item(item):
    """
    Pesquisa o item no bloco superior da tela (F7 -> item -> F8).

    Usada pelas macros de descativação e alteração de ponto mínimo.
    A cativação NÃO usa esta função: lá o fluxo é Ctrl+V + TAB
    (ver colar_item_e_descer).

    Retorna:
        True  -> item localizado.
        False -> item não encontrado (tela já limpa com Shift+F4,
                 pronta para o próximo item).

    Lança:
        WMSCaiuError / AbortarExecucao.
    """
    atalho_wms(ativar_edicao)
    time.sleep(PAUSA_APOS_ENTER_QUERY)

    # O F7 em uma tela que já está em Enter-Query restaura o último
    # critério pesquisado. Ctrl+U garante o campo vazio antes de
    # digitar, evitando que os valores se concatenem.
    limpar_campo_wms()

    colar_wms(str(item))

    hash_ref, _ = detectar_mudanca_tela(
        max_espera=0.1,
        log_fn=lambda *_: None,
    )

    atalho_wms(executar_campo)
    time.sleep(PAUSA_APOS_EXECUTAR_CONSULTA)

    # O WMS pode ter caído durante a consulta.
    if detectar_erro_wms_caido(timeout=0.5):
        raise WMSCaiuError()

    # Item inexistente: a barra de status informa imediatamente.
    if detectar_pesquisa_sem_registro():
        log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Item {item} não retornou registro algum."
        )

        # Shift+F4 -> limpa a consulta, deixando a tela pronta para o
        # próximo item.
        limpar_shift_f4()

        return False

    contador = 0
    inicio_pesquisa = time.time()

    while True:
        if stop_requested:
            raise AbortarExecucao("parada_solicitada")

        resultado = aguardar_textos(
            TRANSACAO,
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
            # Ainda em Enter-Query: pode ser item inexistente.
            if detectar_pesquisa_sem_registro(timeout=0.5):
                log(
                    f"{time.strftime('[%H:%M:%S]')} "
                    f"[INFO] Item {item} não retornou registro algum."
                )
                limpar_shift_f4()
                return False

            contador = 0
            time.sleep(0.3)
            continue

        if mudou:
            atalho_wms(aceitar_alt_o)
            time.sleep(0.3)
            contador += 1
            continue

        if not resultado and contador > 1:
            return True

        if tempo_pesquisa > 10:
            if detectar_erro_wms_caido(timeout=0.5):
                raise WMSCaiuError()

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[WARN] Item {item} não encontrado após múltiplas "
                "tentativas."
            )

            limpar_shift_f4()
            return False

        contador += 1


def aguardar_tela_transacao(timeout=60):
    """
    Confirma que a tela da wmma0031 está aberta e pronta.

    Diferente da wmma0020, esta tela não tem os botões
    "Herdar Mapeamento", então a confirmação usa o título do bloco.
    """
    resultado = aguardar_textos(
        TRANSACAO,
        {
            "tela_locais": [
                "mapeamento local cativo",
                "qt. minima",
                "qt. mínima",
                "locais",
            ]
        },
        timeout=timeout,
        log_fn=log,
        ordem_blocos=[1, 2, 6, 7, 11, 12],
        deslocamento_x=0.0,
        n_clicks=0,
        clicar=False,
        modo="neutro",
        ignorar_textos=[],
        roi_attempts=2,
        roi_delay=0.2,
        roi_retry_between_blocks=True,
        stop_checker=lambda: stop_requested,
    )

    return bool(resultado)


# =================== LOOP PRINCIPAL GENÉRICO =================== #

def executar_linhas(data, processar_linha, status_cb, campos):
    """
    Loop principal com retomada no item que parou.

    Parâmetros:
        data            : lista de tuplas com os dados colados.
        processar_linha : função(i, valores, status_cb) -> dict.
        status_cb       : callback de status da interface.
        campos          : nomes das colunas, na ordem, para montar o
                          dicionário de resultado em caso de falha.
    """
    resultados = []

    idx = 0
    recuperacoes_por_linha = {}

    n_campos = len(campos)

    while idx < len(data):
        if stop_requested:
            log(f"[ABORT] Parada solicitada antes da linha {idx + 1}.")
            break

        i = idx + 1
        valores = tuple(data[idx][:n_campos])
        base = dict(zip(campos, valores))
        base["linha"] = i

        item = base.get("item", "")

        try:
            resultado = processar_linha(i, valores, status_cb)
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

                resultados.append({**base, "status": "Falha_wms"})
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

            resultados.append({**base, "status": "Foco_perdido"})
            idx += 1
            continue

        except AbortarExecucao as ab:
            if ab.resultado_parcial:
                resultados.append(ab.resultado_parcial)

            log(
                f"{time.strftime('[%H:%M:%S]')} "
                f"[ABORT] Execução interrompida: {ab.motivo}."
            )
            break

    return resultados


# =================== ORQUESTRAÇÃO GENÉRICA =================== #

def abrir_transacao(log_fn=None):
    """
    Executa a navegação inicial até a transação wmma0031.

    Retorna True se a tela ficou pronta para receber os itens.
    """
    if log_fn is None:
        log_fn = log

    try:
        garantir_foco_wms(log_fn=log_fn)
    except FocoPerdidoError as exc:
        log_fn(f"[ERRO] {exc}")
        return False

    time.sleep(0.3)
    acao_limpar()
    time.sleep(0.3)

    hash_ref, _ = detectar_mudanca_tela(
        max_espera=0.1,
        log_fn=lambda *_: None,
    )

    resultado = aguardar_textos(
        TRANSACAO,
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
        log_fn("[ERRO] Tela inicial não confirmada.")
        return False

    if not digitar_transacao(TRANSACAO):
        log_fn(f"[ERRO] Falha ao digitar transação {TRANSACAO}.")
        return False

    time.sleep(0.5)

    hash_ref, mudou = detectar_mudanca_tela(
        hash_ref,
        limiar=6,
        max_espera=3.5,
        log_fn=log_fn,
    )

    if not mudou:
        log_fn("[WARN] Nenhuma mudança visual detectada após digitação.")

    return True


def resumir(resultados, status_principal, log_fn=None):
    """
    Monta o resumo final contando cada status.

    Retorna o dicionário de totais para o registro de execução.
    """
    if log_fn is None:
        log_fn = log

    def contar(status):
        return sum(1 for r in resultados if r.get("status") == status)

    totais = {
        "linhas_processadas": len(resultados),
        "concluidos": contar(status_principal),
        "locais_inexistentes": contar("Local_inexistente"),
        "ja_existentes": contar("Ja_existente"),
        "itens_nao_encontrados": contar("Item_nao_encontrado"),
        "nao_confirmados": contar("Nao_confirmado"),
        "falhas_wms": contar("Falha_wms"),
        "focos_perdidos": contar("Foco_perdido"),
    }

    log_fn(
        f"[INFO] Automação finalizada. "
        f"{status_principal}: {totais['concluidos']}. "
        f"Local inexistente: {totais['locais_inexistentes']}. "
        f"Já existente: {totais['ja_existentes']}. "
        f"Item não encontrado: {totais['itens_nao_encontrados']}. "
        f"Não confirmados: {totais['nao_confirmados']}. "
        f"Falhas WMS: {totais['falhas_wms']}. "
        f"Foco perdido: {totais['focos_perdidos']}."
    )

    return totais
