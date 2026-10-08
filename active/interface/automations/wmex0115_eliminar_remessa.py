import os
import time
import re
import ctypes
import pyautogui
import pyperclip
import keyboard as kb
from PIL import Image
import imagehash
import numpy as np
from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import (
    CURSORINFO,
    executar_campo,
    proximo_campo,
    proximo_bloco,
    limpar_campo,
    colar_ctrl_v,
    copiar_para_clipboard,
    digitar_transacao,
    aguardar_textos,
    alt_f4,
    inicio_do_campo,
    selecionar_texto_esq_dir,
    copiar_ctrl_c,
    acao_limpar,
    remover_registro,
    campo_limpar,
    limpar_shift_f5,
    campo_anterior,
    ativar_edicao,
    salvar_alt_s,
    aceitar_alt_o,
    limpar_shift_f7,
    maximize_manager,
)

# =================== VARIÃVEIS GLOBAIS =================== #

TRANSACAO_CAPTURAR = "wmex1090"
TRANSACAO_VERIFICAR = "wmco0510"
TRANSACAO_ELIMINAR = "wmex0115"

# para o load do cursor:
ABORTAR_AUTOMACAO_POR_LEITURAS_VAZIAS = "__ABORTAR_AUTOMACAO_POR_LEITURAS_VAZIAS__"
IDC_APPSTARTING = 32650  # seta + loading
IDC_WAIT = 32514         # loading/ampulheta

logger = print  # funÃ§Ã£o de log externa (pode ser substituÃ­da)
status_callback = None  # funÃ§Ã£o de callback opcional: fn(row_index:int, status:str, value:Optional[str]=None)
stop_requested = False
stop_hotkey_handle = None


# =================== UTILITÃRIOS =================== #

def request_stop():
    global stop_requested
    if stop_requested:
        return
    stop_requested = True
    print(f"{time.strftime('[%H:%M:%S]')} [STOP] CapsLock pressionado. Encerrando automação...")

def clear_stop():
    global stop_requested
    stop_requested = False


def register_stop_hotkey(log_fn=print):
    global stop_hotkey_handle
    unregister_stop_hotkey()
    stop_hotkey_handle = kb.add_hotkey("caps lock", request_stop, suppress=False)
    try:
        log_fn("[INFO] Tecla CapsLock vinculada para interromper a automação.")
    except Exception:
        print("[INFO] Tecla CapsLock vinculada para interromper a automação.")


def unregister_stop_hotkey(log_fn=None):
    global stop_hotkey_handle
    if stop_hotkey_handle is None:
        return
    try:
        kb.remove_hotkey(stop_hotkey_handle)
        if log_fn:
            try:
                log_fn("[INFO] Tecla CapsLock desvinculada.")
            except Exception:
                print("[INFO] Tecla CapsLock desvinculada.")
    except Exception:
        pass
    finally:
        stop_hotkey_handle = None

def log(message):
    try:
        logger(message)
    except Exception:
        print(message)

def quebrar_itens_multilinha(valor):
    """Quebra texto com separadores mistos em uma lista limpa de itens."""
    if valor is None:
        return []
    return [item.strip() for item in re.split(r"[\r\n\t]+", str(valor)) if item and item.strip()]

def extrair_valores_remessa(remessa):
    """Normaliza diferentes formatos de linha para (planta_digitada, planta_copiada, remessa)."""
    planta_digitada = ""
    planta_copiada = ""
    valor_remessa = ""

    if isinstance(remessa, (list, tuple)) and remessa:
        if len(remessa) >= 3:
            planta_digitada = str(remessa[0]).strip()
            planta_copiada = str(remessa[1]).strip()
            valor_remessa = str(remessa[2]).strip()
        elif len(remessa) >= 2:
            planta_digitada = str(remessa[0]).strip()
            valor_remessa = str(remessa[1]).strip()
        else:
            valor_remessa = str(remessa[0]).strip()
    else:
        valor_remessa = str(remessa).strip()

    return planta_digitada, planta_copiada, valor_remessa

def remover_repeticoes_finais(registros):
    """Remove repetiÃ§Ãµes consecutivas do fim da lista, mantendo sÃ³ a primeira ocorrÃªncia."""
    if not registros:
        return registros

    ultimo = registros[-1]
    idx = len(registros) - 2
    while idx >= 0 and registros[idx] == ultimo:
        idx -= 1

    repetidos = len(registros) - 1 - idx
    if repetidos <= 1:
        return registros

    return registros[:idx + 2]

def remover_lojas_poupar(registros, lojas_poupar, log_fn=log):
    """Remove linhas cuja loja copiada esteja na lista de lojas/CDs a poupar."""
    if not registros or not lojas_poupar:
        return registros

    lojas_bloqueadas = {
        str(loja).strip().upper()
        for loja in quebrar_itens_multilinha(lojas_poupar)
    }
    if not lojas_bloqueadas:
        return registros

    registros_filtrados = []
    removidos = 0
    for registro in registros:
        _, loja_copiada, valor_remessa = extrair_valores_remessa(registro)
        if loja_copiada.strip().upper() in lojas_bloqueadas:
            removidos += 1
            log_fn(f"[INFO] Linha removida por loja a poupar: loja='{loja_copiada}' remessa='{valor_remessa}'.")
            continue
        registros_filtrados.append(registro)

    if removidos:
        log_fn(f"[INFO] {removidos} linha(s) removida(s) por 'Lojas/CDs a poupar'.")

    return registros_filtrados


def remover_duplicatas_loja_remessa(registros, log_fn=log):
    """Remove duplicatas globais preservando a primeira ocorrência por loja/remessa."""
    if not registros:
        return registros

    unicos = []
    vistos = set()
    removidos = 0

    for registro in registros:
        _, loja_copiada, valor_remessa = extrair_valores_remessa(registro)
        chave = (str(loja_copiada).strip().upper(), str(valor_remessa).strip())

        if chave in vistos:
            removidos += 1
            continue

        vistos.add(chave)
        unicos.append(registro)

    if removidos:
        log_fn(f"[INFO] {removidos} linha(s) duplicada(s) removida(s) por loja/remessa.")

    return unicos


def filtrar_registros_fora_do_padrao(registros, log_fn=log):
    """Mantem apenas registros com loja valida e remessa final de 10 caracteres."""
    if not registros:
        return registros

    registros_filtrados = []
    removidos = 0

    for registro in registros:
        planta_digitada, loja_copiada, valor_remessa = extrair_valores_remessa(registro)
        loja_norm = str(loja_copiada).strip()
        remessa_norm = str(valor_remessa).strip()

        if not loja_norm or len(loja_norm) > 4:
            removidos += 1
            continue

        if len(remessa_norm) == 9:
            remessa_norm = "0" + remessa_norm
        elif len(remessa_norm) != 10:
            removidos += 1
            continue

        registros_filtrados.append([planta_digitada, loja_norm, remessa_norm])

    if removidos:
        log_fn(f"[INFO] {removidos} linha(s) removida(s) por fugir do padrão esperado.")

    return registros_filtrados

def verificar_restricoes_poupar(registros_finais, restricoes_poupar=None, log_fn=log, restricoes_callback=None):
    """
    Ponto de orquestração para validar remessas finais contra 'Restrições a poupar'.

    Por enquanto, apenas normaliza a entrada de restrições e devolve a lista sem alterações.
    """

    if stop_requested:
        log("[ABORT] Parada solicitada antes da pesquisa.")
        return registros_finais

    if not registros_finais:
        log_fn("[INFO] Nenhuma remessa para verificar restrições. Pulando abertura da tela de restrições.")
        return []
    
    acao_limpar()
    time.sleep(0.3)
    ignorar_textos = ["programas"]
    opcoes_textos = {"programa": ["programa"]}
    resultado = aguardar_textos(TRANSACAO_VERIFICAR, opcoes_textos, timeout=25, 
                                log_fn=log, ordem_blocos=[1], deslocamento_x=0.8, 
                                n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                stop_checker=lambda: stop_requested)
    if not resultado:
        return log("[ERRO] Tela inicial nÃ£o confirmada.")

    if not digitar_transacao(TRANSACAO_VERIFICAR):
        return log_fn(f"[ERRO] Falha ao digitar transaÃ§Ã£o {TRANSACAO_VERIFICAR}.")

    while True:
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return registros_finais
        # Aguardar a mensagem "Restr." surgir
        ignorar_textos = ["rota"]
        opcoes_textos_status = {"restricao": ["restr", "estr"]}
        resultado = aguardar_textos(TRANSACAO_VERIFICAR, opcoes_textos_status, timeout=0.5, 
                                    log_fn=log, ordem_blocos=[8,7,13,12], deslocamento_x=0, 
                                    n_clicks=0, clicar=False, modo="auto", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if not resultado:
            log("[WARN] Mensagem 'Restr.' não encontrada. Tentando novamente...")
            continue
        else:
            texto, alvo, (cx, cy) = resultado
            local_campo_restr = (cx + 50, cy)
            break

    registros_enriquecidos = []

    for registro in registros_finais:
        if stop_requested:
            log("[ABORT] Parada solicitada durante a captura de restrições.")
            break

        planta, loja, valor_remessa = extrair_valores_remessa(registro)
        log_fn(f"[INFO] Validando remessa '{valor_remessa}' contra restrições a poupar...")
        ativar_edicao()
        time.sleep(0.1)
        proximo_campo()
        pyautogui.write(valor_remessa, interval=0.01)
        time.sleep(0.2)

        hash_ref_antes = capturar_hash_tela()

        executar_campo()

        time.sleep(0.2)
        mudou = False
        timer_restr = 0.0
        while timer_restr < 2:
            if stop_requested:
                log("[ABORT] Parada solicitada durante a espera de mudança visual das restrições.")
                break
            hash_ref_depois = capturar_hash_tela()
            dist = abs(hash_ref_antes - hash_ref_depois)
            log_fn(
                f"[HASH DEBUG] remessa='{valor_remessa}' "
                f"tempo={timer_restr:.1f}s distancia_pHash={dist}"
            )

            if dist >= 2:
                log_fn(f"[OK] Mudança visual detectada para remessa '{valor_remessa}' (distância pHash={dist}). Prosseguindo com captura de restrição.")
                mudou = True
                break
            timer_restr += 0.05
            time.sleep(0.05)

        if stop_requested:
            log("[ABORT] Parada solicitada antes da leitura da restrição.")
            break

        if not mudou:
            log_fn(f"[WARN] Nenhuma mudança visual detectada para remessa '{valor_remessa}' dentro do tempo limite.")

        ignorar_textos = ["record 11", "record", "11"]
        opcoes_textos_status = {"pedido": ["n pedido", "pedido", "npedido"]}
        resultado = aguardar_textos(TRANSACAO_VERIFICAR, opcoes_textos_status, timeout=5, 
                                    log_fn=log, ordem_blocos=[21], deslocamento_x=0.0, 
                                    n_clicks=0, clicar=False, modo="neutro", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if stop_requested:
            log("[ABORT] Parada solicitada durante a busca da restrição.")
            break
        if not resultado:
            log("[WARN] Mensagem 'N Pedido' não encontrada. Tentando novamente...")
            continue
        else:
            log_fn(f"[OK] Remessa '{valor_remessa}' encontrada.")

        if stop_requested:
            log("[ABORT] Parada solicitada antes de copiar a restrição.")
            break
        pyautogui.click(local_campo_restr[0], local_campo_restr[1], clicks=4, interval=0.1)
        copiar_ctrl_c()
        restricao_text = pyperclip.paste().strip()
        registros_enriquecidos.append([planta, loja, valor_remessa, restricao_text])

        if callable(restricoes_callback):
            try:
                restricoes_callback(registros_enriquecidos)
            except Exception as e:
                log_fn(f"[AVISO] Falha ao atualizar ExcelInput com restrições: {e}")
    hash_antes_fechar = capturar_hash_tela()
    alt_f4()
    acao_limpar()
    time.sleep(0.5)
    hash_depois_fechar = capturar_hash_tela()
    dist_fechamento = abs(hash_antes_fechar - hash_depois_fechar)
    log_fn(f"[HASH] Fechamento da janela de restricoes: distancia pHash={dist_fechamento}")
    if dist_fechamento <= 21:
        log_fn(
            "[WARN] Diferenca visual abaixo do esperado apos fechar restricoes. "
            "A confirmacao da tela principal dependera da busca por 'programa'."
        )


    if not registros_enriquecidos:
        return []

    restricoes_normalizadas = quebrar_itens_multilinha(restricoes_poupar)
    if restricoes_normalizadas:
        log_fn(
            f"[INFO] Validação de restrições preparada com "
            f"{len(restricoes_normalizadas)} restrição(ões) a poupar."
        )
        restricoes_bloqueadas = {str(item).strip().upper() for item in restricoes_normalizadas}
        registros_filtrados = []
        removidos = 0

        for registro in registros_enriquecidos:
            restricao_capturada = str(registro[3]).strip().upper() if len(registro) > 3 else ""
            if restricao_capturada in restricoes_bloqueadas:
                removidos += 1
                log_fn(
                    f"[INFO] Linha removida por restrição a poupar: "
                    f"remessa='{registro[2]}' restrição='{registro[3]}'."
                )
                continue
            registros_filtrados.append(registro)

        registros_enriquecidos = registros_filtrados
        if removidos:
            log_fn(f"[INFO] {removidos} linha(s) removida(s) por 'Restrições a poupar'.")
            if callable(restricoes_callback):
                try:
                    restricoes_callback(registros_enriquecidos)
                except Exception as e:
                    log_fn(f"[AVISO] Falha ao atualizar ExcelInput após filtro de restrições: {e}")
    else:
        log_fn("[INFO] Validação de restrições preparada sem restrições informadas.")

    return registros_enriquecidos

def verificar_tamanho_lista(dados, planta=None, *, tamanho_esperado):
    if dados:
        return len(dados[0]) >= tamanho_esperado
    if planta:
        return len(planta) >= tamanho_esperado
    return False


# --- FunÃ§Ãµes auxiliares ---

def copiar_loja_remessa(intervalo=0.05):
    """Tenta copiar a planta/loja e a remessa no registro atual.

    Retorna uma tupla (planta, remessa) ou None se nÃ£o houver valor.
    """
    # copiar planta/loja
    inicio_do_campo()
    selecionar_texto_esq_dir()
    planta_text = copiar_texto_do_campo(max_tentativas=2, espera_ms=60)

    # copiar remessa (avanÃ§ar para o campo de remessa)
    proximo_campo()
    proximo_campo()
    inicio_do_campo()
    selecionar_texto_esq_dir()
    remessa_text = copiar_texto_do_campo(max_tentativas=2, espera_ms=60)

    # mover para o prÃ³ximo registro e voltar para posiÃ§Ã£o inicial
    pyautogui.press('down')
    campo_anterior()
    campo_anterior()

    if planta_text or remessa_text:
        time.sleep(intervalo)
        return (planta_text, remessa_text)

    time.sleep(intervalo)
    return None


def copiar_uma_vez(espera_ms=120):
    marcador = f"__MARKER__{time.time_ns()}__"
    pyperclip.copy(marcador)

    copiar_ctrl_c()

    prazo = time.time() + (espera_ms / 1000)
    while time.time() < prazo:
        if stop_requested:
            return ""
        atual = pyperclip.paste()
        if atual != marcador:
            return str(atual).strip()
        time.sleep(0.01)

    return ""


def copiar_texto_do_campo(max_tentativas=2, espera_ms=60):
    for _ in range(max_tentativas):
        if stop_requested:
            return ""
        texto = copiar_uma_vez(espera_ms=espera_ms)
        if texto:
            return texto
        time.sleep(0.05)

    return ""


def atualizar_interface_threadsafe(root, callback, lista_remessas):
    """Executa o callback de atualizaÃ§Ã£o da interface de forma segura."""
    if callback and root:
        root.after(0, lambda: callback(lista_remessas))

def detectar_mudanca_tela(
    hash_ref=None,
    limiar=5,
    max_espera=3.5,
    intervalo=0.1,
    confirmacoes=1,
    log_fn=print,
):
        """
        Aguarda atÃ© que a tela mude perceptivelmente comparando perceptual hash.
        Quando `confirmacoes` > 1, exige a mudanÃ§a acima do limiar em leituras seguidas.
        Retorna (novo_hash, mudou:bool)
        """
        start = time.time()
        if hash_ref is None:
            hash_ref = capturar_hash_tela()

        consecutivas = 0
        ultimo_hash_valido = hash_ref
        tentativa = 0

        while time.time() - start < max_espera:
            if stop_requested:
                log_fn("[MUDANCA] Parada solicitada durante detecção de mudança visual.")
                return hash_ref, False
            tentativa += 1
            hash_atual = capturar_hash_tela()
            dist = abs(hash_ref - hash_atual)
            log_fn(
                f"[MUDANCA DEBUG] tentativa={tentativa} "
                f"distancia_pHash={dist} limiar={limiar} "
                f"confirmacoes={consecutivas}/{max(1, int(confirmacoes))}"
            )

            if dist >= limiar:
                consecutivas += 1
                ultimo_hash_valido = hash_atual
                if consecutivas >= max(1, int(confirmacoes)):
                    log_fn(
                        f"[MUDANCA] Tela alterada "
                        f"(distÃ¢ncia pHash={dist}, confirmaÃ§Ãµes={consecutivas})"
                    )
                    return ultimo_hash_valido, True
            else:
                consecutivas = 0

            time.sleep(intervalo)

        log_fn("[MUDANCA] Nenhuma mudanÃ§a detectada dentro do tempo limite.")
        return hash_ref, False


def capturar_hash_tela():
        """Captura o pHash da tela atual para comparacao pontual."""
        screenshot = pyautogui.screenshot()
        gray = np.array(screenshot.convert("L").resize((64, 64), Image.BILINEAR))
        return imagehash.phash(Image.fromarray(gray))


def cursor_carregando():
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)

    ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci))

    h_wait = ctypes.windll.user32.LoadCursorW(0, IDC_WAIT)
    h_appstarting = ctypes.windll.user32.LoadCursorW(0, IDC_APPSTARTING)

    return ci.hCursor in (h_wait, h_appstarting)




# =================== ETAPA 1 â€” CAPTURA DE REMESSAS =================== #

def iniciar_captura_remessas(transacao: str, plantas: str, root=None, status_callback=None, log_fn=print, lojas_poupar=None):
    """
    Fluxo principal da automaÃ§Ã£o de captura de remessas.
    Realiza pesquisa pela planta e captura as remessas da tela.
    """

    log(f"[INFO] Iniciando captura de remessas para planta {plantas}...")
    resultado_remessas = []

    # Etapa 1.1: localizar tela de pesquisa
    now = time.strftime("[%H:%M:%S]")
    print(f'{time.strftime("[%H:%M:%S]")}')

    while True:
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas
        
        # Aguardar a mensagem "Planta" surgir
        ignorar_textos = ["record 11", "record", "11"]
        opcoes_textos_status = {"mensagem_planta": ["planta", "list of values", "list", "values"]}
        resultado = aguardar_textos(transacao, opcoes_textos_status, timeout=0.1, 
                                    log_fn=log, ordem_blocos=[21], deslocamento_x=0.0, 
                                    n_clicks=0, clicar=False, modo="neutro", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if not resultado:
            log("[WARN] Mensagem 'Planta' nÃ£o encontrada. Tentando novamente...")
            continue
        else:
            break

    while True:
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas

        # Aguardar o botÃ£o "Pesquisar"
        opcoes_textos = {"botao_pesquisar": ["pesquisar"]}
        resultado = aguardar_textos(transacao, opcoes_textos, timeout=60, 
                                    log_fn=log,ordem_blocos=[4,5,3,9,10,8], deslocamento_x=0, 
                                    n_clicks=0, clicar=False, modo="auto",
                                    stop_checker=lambda: stop_requested)
        if not resultado:
            log("[WARN] BotÃ£o de pesquisa nÃ£o encontrado. Tentando novamente...")
            continue

        texto, alvo, (cx, cy) = resultado
        log(f"[OK] '{texto}' localizado. Clicando em ({cx},{cy})")
        limpar_campo()
        time.sleep(0.1)
        pyautogui.write(str(plantas).strip(), interval=0.01)
        #colar_ctrl_v()
        pyautogui.click(cx, cy)
        break

    # Etapa 1.2 - aguardar execução da pesquisa

    time.sleep(2)
    while cursor_carregando():
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas
        print("Aguardando...")
        time.sleep(0.5)

    start = time.time()
    count = 0
    while time.time() - start < 300:  # limite global de 5 min
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas

        ignorar_textos = ["record 11", "record", "11"]
        opcoes_textos_status = {"mensagem_planta": ["planta", "list of values", "list", "values"]}
        resultado = aguardar_textos(transacao, opcoes_textos_status, timeout=0.1, 
                                    log_fn=log, ordem_blocos=[21], deslocamento_x=0.0, 
                                    n_clicks=0, clicar=False, modo="auto", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if not resultado and count > 1:
            log("[INFO] Pesquisa finalizada.")
            break
        elif not resultado:
            count += 1
            continue    

        texto, alvo, (cx, cy) = resultado
        print(f'{time.strftime("[%H:%M:%S]")} - texto encontrado: {texto}, alvo: {alvo}')   
        if texto in ("Planta"):
            log("[INFO] Pesquisa executando.")
            continue
        else:
            log("[INFO] Pesquisa finalizada.")
            break
    else:
        log("[TIMEOUT] Pesquisa nÃ£o finalizou em 300 segundos.")
        return

    # Etapa 1.3: iniciar captura de remessas
    log("[OK] Iniciando captura de remessas...")
    proximo_bloco()
    proximo_bloco()
    time.sleep(0.1)
    start_captura = time.time()
    falhas = 0
    leituras_vazias_consecutivas = 0
    repeticoes = 0
    ultimo_registro = None
    while not stop_requested and time.time() - start_captura < 1200:
        par_capturado = copiar_loja_remessa()
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas

        if not par_capturado:
            log("[WARN] Nenhum texto copiado. Tentando novamente...")
            falhas += 1
            leituras_vazias_consecutivas += 1
            if leituras_vazias_consecutivas >= 3:
                log("[INFO] 3 leituras vazias consecutivas. Nenhuma remessa encontrada para esta planta.")
                break
            if falhas >= 5:
                log("[ERRO] 5 tentativas sem valor. Encerrando captura.")
                break
            continue

        leituras_vazias_consecutivas = 0
        loja_copiada, remessa = par_capturado
        pair = (str(plantas).strip(), str(loja_copiada).strip(), str(remessa).strip())
        planta_digitada, planta_copied, remessa = extrair_valores_remessa(pair)

        planta_digitada_norm = str(planta_digitada).strip().upper()
        planta_copied_norm = str(planta_copied).strip().upper()
        remessa_norm = str(remessa).strip()

        # Quando a pesquisa volta sem linhas válidas, a automação pode acabar
        # recopiando a planta digitada ou campos vazios. Nesses casos, tratamos
        # como "sem remessas" para encerrar a captura dessa planta.
        if not remessa_norm:
            if not planta_copied_norm or planta_copied_norm == planta_digitada_norm:
                log("[INFO] Nenhuma remessa encontrada para a planta pesquisada.")
                break

            log("[WARN] Remessa vazia detectada. Tentando novamente...")
            falhas += 1
            leituras_vazias_consecutivas += 1
            if leituras_vazias_consecutivas >= 3:
                log("[INFO] 3 leituras vazias consecutivas. Nenhuma remessa encontrada para esta planta.")
                break
            if falhas >= 5:
                log("[ERRO] 5 tentativas com remessa vazia. Encerrando captura.")
                break
            continue

        leituras_vazias_consecutivas = 0
        if remessa_norm.upper() == planta_digitada_norm or (
            planta_copied_norm and remessa_norm.upper() == planta_copied_norm
        ):
            log("[INFO] Nenhuma remessa encontrada (eco da planta pesquisada).")
            break

        # Registrar exatamente o que foi copiado para que o gatilho de repetição
        # funcione mesmo com remessas fora do padrão esperado.
        registro_atual = [planta_digitada, planta_copied, remessa_norm]
        resultado_remessas.append(registro_atual)
        falhas = 0
        leituras_vazias_consecutivas = 0
        log(f"[OK] Remessa capturada: planta_digitada='{planta_digitada}' planta_tela='{planta_copied}' remessa={remessa_norm}")

        if ultimo_registro == registro_atual:
            repeticoes += 1
            if repeticoes >= 3:
                log("[INFO] Registro repetido 3 vezes consecutivas. Fim da lista.")
                resultado_remessas = remover_repeticoes_finais(resultado_remessas)
                break
        else:
            repeticoes = 0
            ultimo_registro = registro_atual


    log(f"[OK] Captura concluÃ­da. Total: {len(resultado_remessas)} remessas.")
    resultado_remessas = filtrar_registros_fora_do_padrao(resultado_remessas, log_fn=log)
    resultado_remessas = remover_duplicatas_loja_remessa(resultado_remessas, log_fn=log)
    resultado_remessas = remover_lojas_poupar(resultado_remessas, lojas_poupar, log_fn=log)
    return resultado_remessas

# =================== ETAPA 2 - ELIMINAÇÃO DE REMESSAS =================== #


def iniciar_eliminacao_remessas(transacao, remessas, status_cb=None):
    log(f"[INFO] Iniciando limpeza com {len(remessas)} linhas.")
    resultados = []
    if status_cb is None:
        status_cb = status_callback
    time.sleep(0.2)
    limpar_shift_f5()

    opcoes_textos_status = {"botao_pesquisar": ["pesquisar"]}
    resultado_status = aguardar_textos(TRANSACAO_ELIMINAR, opcoes_textos_status, timeout=90,
                                        log_fn=log, ordem_blocos=[3,4,8], deslocamento_x=0.0,
                                        n_clicks=0, clicar=False, modo="auto",
                                        stop_checker=lambda: stop_requested)
    if not resultado_status:
        log(f"[ERRO] Botão 'pesquisar' não encontrado.")
        resultados.append([valor_remessa, "botao_pesquisar_nao_encontrado"])
        return
    texto_status, alvo, (cx, cy) = resultado_status
    clique_processar = (cx, cy)



    opcoes_textos_status = {"botao_solicitar": ["solicitar"]}
    resultado_status = aguardar_textos(TRANSACAO_ELIMINAR, opcoes_textos_status, timeout=90,
                                        log_fn=log, ordem_blocos=[13,18,19,14,12,17,22,23,24], deslocamento_x=0.0,
                                        n_clicks=0, clicar=False, modo="auto",
                                        stop_checker=lambda: stop_requested)
    if not resultado_status:
        log(f"[ERRO] Botão 'Solicitar' não encontrado.")
        resultados.append([valor_remessa, "botao_solicitar_nao_encontrado"])
        return

    texto_status, alvo, (cx, cy) = resultado_status
    clique_solicitar = (cx, cy)

    log(f"[OK] Posicao do botao de processamento localizada em ({cx},{cy})")

    for i, linha_da_lista in enumerate(remessas, 1):
        planta_digitada, _, valor_remessa = extrair_valores_remessa(linha_da_lista)

        log(f"[PROCESSAMENTO] Linha {i}: planta_digitada='{planta_digitada}' remessa={valor_remessa}")

        if stop_requested:
            log(f"[ABORT] Parada solicitada antes de processar a linha {i}.")
            break

        limpar_shift_f5()

        hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

        pyautogui.write(planta_digitada, interval=0.01)
        time.sleep(0.1)
        proximo_campo()
        proximo_campo()

        hash_ref, mudou = detectar_mudanca_tela(
            hash_ref,
            limiar=6,
            max_espera=0.5,
            intervalo=0.15,
            confirmacoes=2,
            log_fn=log,
        )
        if mudou:
            if callable(status_cb):
                status_cb(i, "Planta_inválida", valor_remessa)
            log("[WARN] Popup detectado. Mudança visual detectada apos digitar a planta. Limpando e reiniciando...")
            aceitar_alt_o()
            remover_registro()
            time.sleep(0.5)
            continue

        pyautogui.write(str(valor_remessa), interval=0.01)
        time.sleep(0.1)
        pyautogui.click(clique_processar[0], clique_processar[1])
        time.sleep(0.1)
        print(f'{time.strftime("[%H:%M:%S]")} - Executando remessa {valor_remessa}...')
        campo_anterior()
        pyautogui.press('space')
        time.sleep(0.1)
        hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)
        pyautogui.click(clique_solicitar[0], clique_solicitar[1])

        # Aguarda a mudanca visual antes de iniciar o OCR do popup.
        hash_ref, mudou = detectar_mudanca_tela(
            hash_ref,
            limiar=6,
            max_espera=20,
            intervalo=0.15,
            confirmacoes=2,
            log_fn=log,
        )
        if not mudou:
            log("[WARN] Nenhuma mudanca visual detectada apos clicar em 'Solicitar'. Iniciando OCR mesmo assim.")


        ignorar_textos = ["total entregas 1", "total lojas 1", "total", "entregas", "lojas"]
        opcoes_textos_status = {
            "encontrou": [
                "sim",
                "certeza",
                "dos pedidos"],
            "remessa_invalida": [
                "encontrado",
                "erro ora20764",
                "ora20764",
                "ora06512",
                "wlasa pc pedv",
                "pc pedv valida",
                "erro na solicitacao",
                "pedido nao encontrado"],
            "planta_invalida": [
                "erro 20002",
                "20002",
                "planta invalida",
                "invalida",
            ]
        }
        resultado_status = aguardar_textos( TRANSACAO_ELIMINAR, opcoes_textos_status, timeout=30,
                                            log_fn=log, ordem_blocos=[13, 12], deslocamento_x=0.0,
                                            n_clicks=0, clicar=False, modo="auto", ignorar_textos=ignorar_textos,
                                            roi_attempts=3, roi_delay=0.2, roi_retry_between_blocks=True,
                                            stop_checker=lambda: stop_requested)
        texto_status, alvo, (cx, cy) = resultado_status if resultado_status else (None, None, (None, None))

        if alvo in ("sim", "não", "certeza", "dos pedidos"):
            log(f"[INFO] Remessa {valor_remessa} encontrada. Limpando campo...")
            # resultados.append([valor_remessa, "Não_encontrada"])
            if callable(status_cb):
                status_cb(i, "Solicitada", valor_remessa)

            hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

            salvar_alt_s()
            time.sleep(0.5)
            aceitar_alt_o()

            hash_ref, mudou = detectar_mudanca_tela(
                hash_ref,
                limiar=6,
                max_espera=10,
                intervalo=0.15,
                confirmacoes=2,
                log_fn=log,
            )
            if mudou:
                log("[WARN] Solicitação enviada. Seguindo para a próxima remessa...")
                continue
            

            continue  # Recomeça o loop

        elif alvo in ("erro ora20764", "ora06512", "wlasa pc pedv", "pc pedv valida", "erro na solicitacao", "pedido nao encontrado"):
            log(f"[INFO] Remessa {valor_remessa} não encontrada. Limpando campo...")
            # resultados.append([valor_remessa, "Não_encontrada"])
            if callable(status_cb):
                status_cb(i, "Não_encontrada", valor_remessa)

            hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

            aceitar_alt_o()
            time.sleep(0.2)

            hash_ref, mudou = detectar_mudanca_tela(
                hash_ref,
                limiar=6,
                max_espera=10,
                intervalo=0.15,
                confirmacoes=2,
                log_fn=log,
            )
            if mudou:
                limpar_shift_f7()
                log("[WARN] Popup de erro liberado. Seguindo para a próxima remessa...")
                continue

            limpar_shift_f7()
            continue  # Recomeça o loop

        elif alvo in ("erro 20002", "planta invalida"):
            log(f"[INFO] Planta {planta_digitada} inválida. Próxima...")
            # resultados.append([valor_remessa, "Não_encontrada"])
            if callable(status_cb):
                status_cb(i, "Planta_inválida", valor_remessa)
            hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)
            aceitar_alt_o()
            # Aguarda a mudanca visual antes de iniciar o OCR do popup.
            hash_ref, mudou = detectar_mudanca_tela(
                hash_ref,
                limiar=5,
                max_espera=12,
                intervalo=0.15,
                confirmacoes=2,
                log_fn=log,
            )
            if not mudou:
                log("[WARN] Nenhuma mudanca visual detectada apos clicar em 'Solicitar'. Iniciando OCR mesmo assim.")
            
            remover_registro()
            time.sleep(1)
            continue  # Recomeça o loop

        else:
            log(f"[WARN] Estado inesperado após processamento da remessa {valor_remessa}.")
            # resultados.append([valor_remessa, "Indeterminado"])
            if callable(status_cb):
                status_cb(i, "Indeterminado", valor_remessa)
            aceitar_alt_o()
            time.sleep(0.3)
            limpar_shift_f7()
            time.sleep(0.3)
            continue

    alt_f4()
    log("[INFO] Processamento concluÃ­do.")
    return resultados



# =================== ETAPA 3 â€” ORQUESTRAÃ‡ÃƒO =================== #
def iniciar_automacao(
    data=None,
    planta=None,
    log_fn=print,
    plantas=None,
    restricoes=None,
    lojas=None,
    remessas=None,
    captura_callback=None,
    restricoes_callback=None,
    status_callback_fn=None,
):
    """
    Inicia a automaÃ§Ã£o de eliminaÃ§Ã£o de remessas.
    
    ParÃ¢metros:
        data: Dados do Excel (linhas)
        planta: Planta especÃ­fica fornecida via campo
        log_fn: FunÃ§Ã£o de logging
        plantas: Plantas a eliminar (multilinhas, pode ser None)
        restricoes: RestriÃ§Ãµes a poupar (multilinhas, pode ser None)
        lojas: Lojas/CDs a poupar (multilinhas, pode ser None)
        remessas: Remessas a poupar (multilinhas, pode ser None)
    """

    global logger, status_callback

    logger = log_fn
    if status_callback_fn is not None:
        status_callback = status_callback_fn
    clear_stop()
    register_stop_hotkey(log_fn=log_fn)
    registrar_evento_execucao(
        "wmex0115_eliminar_remessa",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
        plantas=plantas,
    )
    resultados = []

    transacao_capturar = globals().get("TRANSACAO_CAPTURAR", "wmex1090")
    transacao_verificar = globals().get("TRANSACAO_VERIFICAR", "wmco0510")
    transacao_eliminar = globals().get("TRANSACAO_ELIMINAR", "wmex0115")

    try:
        # --- INÃCIO DA AUTOMAÃ‡ÃƒO --- #
        log_fn("[INFO] Iniciando automaÃ§Ã£o...")
        time.sleep(0.3)
        
        acao_limpar()
        time.sleep(0.3)

        # Captura hash inicial
        hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

        ignorar_textos = ["programas"]
        opcoes_textos = {"programa": ["programa"]}
        resultado = aguardar_textos(transacao_capturar, opcoes_textos, timeout=25, 
                                    log_fn=log, ordem_blocos=[1], deslocamento_x=0.8, 
                                    n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if not resultado:
            registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe="Tela inicial não confirmada")
            return log("[ERRO] Tela inicial nÃ£o confirmada.")

        # --- Determina fluxo --- #
        if data and len(data) > 0:
            log_fn(f"[INFO] Remessas fornecidas manualmente ({len(data)}).")

            # --- Primeira condiÃ§Ã£o: remover remessas_poupar de data --- #
            if remessas and len(remessas) > 0:
                log_fn(f"[INFO] Removendo remessas a poupar da lista de dados...")
                # Converter remessas a poupar para um conjunto para busca rÃ¡pida
                remessas_poupar_set = set(str(r).strip() for r in remessas if r)
                
                # Filtrar dados: manter apenas as linhas que NÃƒO estÃ£o em remessas_poupar
                dados_filtrados = []
                for linha in data:
                    if linha and len(linha) > 0:
                        _, _, valor_remessa = extrair_valores_remessa(linha)
                        if valor_remessa not in remessas_poupar_set:
                            dados_filtrados.append(linha)
                        else:
                            log_fn(f"[INFO] Remessa {valor_remessa} removida da lista (poupar).")
                
                data = dados_filtrados
                log_fn(f"[INFO] Dados apÃ³s filtragem: {len(data)} remessas restantes.")

            if lojas:
                data = remover_lojas_poupar(data, lojas, log_fn=log_fn)

            # --- Pular etapas 1 e 2, iniciar da etapa 3 --- #
            if not digitar_transacao(transacao_eliminar):
                registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe=f"Falha ao digitar transação {transacao_eliminar}")
                return log_fn(f"[ERRO] Falha ao digitar transaÃ§Ã£o {transacao_eliminar}.")
            time.sleep(0.5)

            # --- aguarda mudanÃ§a perceptÃ­vel da tela --- #
            hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

            if not mudou:
                log_fn("[WARN] Nenhuma mudanÃ§a visual detectada apÃ³s digitaÃ§Ã£o.")

            resultados = iniciar_eliminacao_remessas(
                transacao_eliminar,
                data,
                status_cb=status_callback,
            )

# -------- NENHUMA REMESSA FORNECIDA: INICIAR CAPTURA AUTOMATICA -------- #

        else:
            log_fn("[INFO] Nenhuma remessa fornecida. Iniciando captura automatica...")

            # Suporta mÃºltiplas plantas: iterar captura por planta e agregar resultados
            remessas_agg = []
            plantas_list = quebrar_itens_multilinha(plantas) if plantas else [""]
            for p in plantas_list:
                if not digitar_transacao(transacao_capturar):
                    registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe=f"Falha ao digitar transação {transacao_capturar}")
                    return log_fn(f"[ERRO] Falha ao digitar transaÃ§Ã£o {transacao_capturar}.")

                # Aguarda mudanca apos digitacao da transacao
                hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

                if not mudou:
                    log_fn("[WARN] Nenhuma mudanÃ§a visual detectada apÃ³s digitaÃ§Ã£o (captura automÃ¡tica).")
                log_fn(f"[INFO] Iniciando captura automÃ¡tica para planta: '{p}'")
                remessas_encontradas = iniciar_captura_remessas(transacao_capturar, p, log_fn=log_fn, lojas_poupar=lojas)
                if remessas_encontradas:
                    remessas_agg.extend(remessas_encontradas)
                    if callable(captura_callback):
                        try:
                            captura_callback(remessas_encontradas)
                        except Exception as e:
                            log_fn(f"[AVISO] Falha ao atualizar ExcelInput com captura da planta '{p}': {e}")
                    alt_f4()
                    time.sleep(0.5)
                else:
                    alt_f4()
                    time.sleep(0.5)
                

            remessas = remessas_agg
            if restricoes:
                remessas = verificar_restricoes_poupar(
                    remessas,
                    restricoes_poupar=restricoes,
                    log_fn=log_fn,
                    restricoes_callback=restricoes_callback,
                )
            if remessas and callable(captura_callback):
                try:
                    captura_callback(remessas)
                except Exception as e:
                    log_fn(f"[AVISO] Falha ao atualizar ExcelInput com captura automÃ¡tica: {e}")

            if remessas:
                acao_limpar()
                time.sleep(0.3)
                ignorar_textos = ["programas"]
                opcoes_textos = {"programa": ["programa"]}
                resultado = aguardar_textos(transacao_capturar, opcoes_textos, timeout=60,
                                            log_fn=log_fn, ordem_blocos=[1], deslocamento_x=0.8,
                                            n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                            stop_checker=lambda: stop_requested)
                if not resultado:
                    registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe="Tela inicial não confirmada após captura")
                    return log_fn("[ERRO] Tela inicial nÃ£o confirmada.")


# -------- CAPTURA FINALIZADA - INICIAR ELIMINACAO -------- #

                acao_limpar()
                time.sleep(0.3)
                ignorar_textos = ["programas"]
                opcoes_textos = {"programa": ["programa"]}
                resultado = aguardar_textos(transacao_capturar, opcoes_textos, timeout=25, 
                                            log_fn=log, ordem_blocos=[1], deslocamento_x=0.8, 
                                            n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                            stop_checker=lambda: stop_requested)
                if not resultado:
                    registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe="Tela inicial não confirmada antes da eliminação")
                    return log("[ERRO] Tela inicial nÃ£o confirmada.")

                if not digitar_transacao(transacao_eliminar):
                    registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="erro", detalhe=f"Falha ao digitar transação {transacao_eliminar}")
                    return log_fn(f"[ERRO] Falha ao digitar transaÃ§Ã£o {transacao_eliminar}.")

                hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

                if not mudou:
                    log_fn("[WARN] Nenhuma mudanÃ§a visual detectada apÃ³s digitaÃ§Ã£o (processamento).")

                resultados = iniciar_eliminacao_remessas(
                    transacao_eliminar,
                    remessas,
                    status_cb=status_callback,
                )
            else:
                registrar_evento_execucao("wmex0115_eliminar_remessa", "fim", status="sem_dados", detalhe="Nenhuma remessa encontrada")
                return log_fn("[INFO] Nenhuma remessa encontrada.")

        registrar_evento_execucao(
            "wmex0115_eliminar_remessa",
            "fim",
            status="sucesso",
            linhas_processadas=len(resultados) if resultados else 0,
        )
        log_fn("[INFO] AutomaÃ§Ã£o finalizada.")
        return resultados
    finally:
        unregister_stop_hotkey(log_fn=log_fn)

if __name__ == "__main__":
    iniciar_automacao()
