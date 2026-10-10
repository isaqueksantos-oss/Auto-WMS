import os
import time
import pyautogui
import pyperclip
import keyboard as kb
from PIL import Image
import imagehash
import numpy as np
from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import (
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
)

# =================== VARIÁVEIS GLOBAIS =================== #

TRANSACAO_PROCESSAR = "wmex1120"
TRANSACAO_CAPTURAR = "wmex1090"

logger = print  # função de log externa (pode ser substituída)
status_callback = None  # função de callback opcional: fn(row_index:int, status:str, value:Optional[str]=None)
stop_requested = False


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


# --- Funções auxiliares ---

def copiar_remessa(max_tentativas=3, intervalo=0.3):
    """Tenta copiar o conteúdo atual do campo, retornando texto válido ou None."""
    for _ in range(max_tentativas):
        inicio_do_campo()
        selecionar_texto_esq_dir()
        copiar_ctrl_c()
        texto = pyperclip.paste().strip()
        print(len(texto))
        if texto:
            time.sleep(intervalo)
            return texto
        time.sleep(intervalo)
    return None


def remover_duplicatas_remessas(registros, log_fn=log):
    """Remove remessas duplicadas preservando a primeira ocorrência."""
    if not registros:
        return registros

    unicos = []
    vistos = set()
    removidos = 0

    for registro in registros:
        chave = str(registro).strip()
        if chave in vistos:
            removidos += 1
            continue

        vistos.add(chave)
        unicos.append(registro)

    if removidos:
        log_fn(f"[INFO] {removidos} remessa(s) duplicada(s) removida(s).")

    return unicos


def atualizar_interface_threadsafe(root, callback, lista_remessas):
    """Executa o callback de atualização da interface de forma segura."""
    if callback and root:
        root.after(0, lambda: callback(lista_remessas))

def detectar_mudanca_tela(hash_ref=None, limiar=5, max_espera=3.5, intervalo=0.1, log_fn=print):
        """
        Aguarda até que a tela mude perceptivelmente (comparando perceptual hash).
        Retorna (novo_hash, mudou:bool)
        """
        def capturar_phash():
            screenshot = pyautogui.screenshot()
            gray = np.array(screenshot.convert("L").resize((64, 64), Image.BILINEAR))
            return imagehash.phash(Image.fromarray(gray))

        start = time.time()
        if hash_ref is None:
            hash_ref = capturar_phash()

        while time.time() - start < max_espera:
            hash_atual = capturar_phash()
            dist = abs(hash_ref - hash_atual)
            if dist > limiar:
                log_fn(f"[MUDANCA] Tela alterada (distância pHash={dist})")
                return hash_atual, True
            time.sleep(intervalo)

        log_fn("[MUDANCA] Nenhuma mudança detectada dentro do tempo limite.")
        return hash_ref, False

# =================== ETAPA 1 — CAPTURA DE REMESSAS =================== #

def iniciar_captura_remessas(transacao: str, planta: str, root=None, status_callback=None, log_fn=print):
    """
    Fluxo principal da automação de captura de remessas.
    Realiza pesquisa pela planta e captura as remessas da tela.
    """
    log(f"[INFO] Iniciando captura de remessas para planta {planta}...")
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
                                    n_clicks=0, clicar=False, modo="neutro", ignorar_textos=ignorar_textos)
        if not resultado:
            log("[WARN] Mensagem 'Planta' não encontrada. Tentando novamente...")
            continue
        else:
            break

    while True:
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas

        # Aguardar o botão "Pesquisar"
        opcoes_textos = {"botao_pesquisar": ["pesquisar"]}
        resultado = aguardar_textos(transacao, opcoes_textos, timeout=60, 
                                    log_fn=log,ordem_blocos=[4,5,3,9,10,8], deslocamento_x=0, 
                                    n_clicks=0, clicar=False, modo="auto")
        if not resultado:
            log("[WARN] Botão de pesquisa não encontrado. Tentando novamente...")
            continue

        texto, alvo, (cx, cy) = resultado
        log(f"[OK] '{texto}' localizado. Clicando em ({cx},{cy})")
        #copiar_para_clipboard(planta)
        pyautogui.write(planta, interval=0.01) 
        #colar_ctrl_v()
        pyautogui.click(cx, cy)
        break

    # Etapa 1.2 – aguardar execução da pesquisa

    #hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

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
                                    n_clicks=0, clicar=False, modo="neutro", ignorar_textos=ignorar_textos)
        if not resultado and count > 0:
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
        log("[TIMEOUT] Pesquisa não finalizou em 300 segundos.")
        return


    # Etapa 1.3: iniciar captura de remessas
    log("[OK] Iniciando captura de remessas...")
    proximo_campo()
    proximo_campo()
    time.sleep(0.5)
    start_captura = time.time()
    falhas = 0
    repeticoes = 0
    while not stop_requested and time.time() - start_captura < 120:
        remessa = copiar_remessa()
        if stop_requested:
            log("[ABORT] Parada solicitada antes da pesquisa.")
            return resultado_remessas
        
        if not remessa:
            log("[WARN] Nenhum texto copiado. Tentando novamente...")
            falhas += 1
            if falhas >= 5:
                log("[ERRO] 3 tentativas sem valor. Encerrando captura.")
                break
            continue

        try:
            remessa_int = int(remessa.strip())
            remessa_verif = str(remessa_int)
            if len(remessa_verif) == 9:
                remessa_int = '0' + remessa_verif
                print("remessa_int= ", len(remessa_int))
        except ValueError:
            log(f"[ERRO] Valor não numérico detectado: '{remessa}'.")
            break

        if remessa_int == planta:
            log("[ERRO] Nenhuma remessa encontrada (eco da planta).")
            break

        if resultado_remessas and remessa_int == resultado_remessas[-1]:
            repeticoes += 1
            if repeticoes >= 3:
                log("[INFO] Remessa repetida. Fim da lista.")
                break
        else:
            repeticoes = 0
            resultado_remessas.append(remessa_int)
            log(f"[OK] Remessa capturada: {remessa_int}")
            pyautogui.press('down')


    log(f"[OK] Captura concluída. Total: {len(resultado_remessas)} remessas.")
    resultado_remessas = remover_duplicatas_remessas(resultado_remessas, log_fn=log)
    return resultado_remessas

# =================== ETAPA 2 — PROCESSAMENTO DE REMESSAS =================== #

def iniciar_processamento_remessas(transacao, remessas):
    log(f"[INFO] Iniciando processamento com {len(remessas)} linhas.")
    resultados = []
    time.sleep(1)
    pyautogui.press('f7')

    opcoes_textos_status = {"liberacao_manual": ["liberaracao manual"],}
    resultado_status = aguardar_textos(TRANSACAO_CAPTURAR, opcoes_textos_status, timeout=90,
                                        log_fn=log, ordem_blocos=[7,8], deslocamento_x=0.0,
                                        n_clicks=0, clicar=False, modo="neutro")

    if not resultado_status:
        log(f"[ERRO] Nenhuma resposta para a remessa {valor_remessa}.")
        resultados.append([valor_remessa, "Sem retorno"])
        return

    texto_status, alvo, (cx, cy) = resultado_status
    clique_processar = (cx, cy)
    log(f"[OK] Posição do botão de processamento localizada em ({cx},{cy})")
        
    for i, remessa in enumerate(remessas, 1):
        valor_remessa = str(remessa[0]).strip() if isinstance(remessa, list) and remessa else str(remessa).strip()
        log(f"[PROCESSAMENTO] Linha {i}: remessa {valor_remessa}")

        if stop_requested:
            log(f"[ABORT] Parada solicitada antes de processar a linha {i}.")
            break

        limpar_campo()
        time.sleep(0.05)
        pyautogui.write(valor_remessa, interval=0.01)
        time.sleep(0.05)
        executar_campo()
        time.sleep(0.2)
        pyautogui.click(clique_processar[0], clique_processar[1])
        time.sleep(0.1)
        print(f'{time.strftime("[%H:%M:%S]")} - Executando remessa {valor_remessa}...')


        # --- Espera de mudança leve na tela (pós execução do campo) ---
        #hash_ref, _ = detectar_mudanca_tela(max_espera=0.5, log_fn=lambda *_: None)


        ignorar_textos = ["record 11", "record", "11", "enterquery"]
        opcoes_textos_status = {"encontrou": ["enter a query", "query press f8", "press f8 to execute", "a pesquisa nao", "pesquisa nao retornou", "nao retornou registro"],}

        resultado_status = aguardar_textos( TRANSACAO_CAPTURAR, opcoes_textos_status, timeout=30,
                                            log_fn=log, ordem_blocos=[21], deslocamento_x=0.0,
                                            n_clicks=0, clicar=False, modo="neutro", ignorar_textos=ignorar_textos)
        texto_status, alvo, (cx, cy) = resultado_status if resultado_status else (None, None)    

        if alvo in ("a pesquisa nao", "pesquisa nao retornou", "nao retornou registro"):
            log(f"[INFO] Remessa {valor_remessa} não encontrada. Limpando campo...")
            # resultados.append([valor_remessa, "Não encontrada"])
            if callable(status_callback):
                status_callback(i, "Não_encontrada", valor_remessa)
            limpar_campo()
            continue  # Recomeça o loop

        elif alvo in ("enter a query", "query press f8", "press f8 to execute"):
            log(f"[INFO] Remessa {valor_remessa} encontrada. Limpando campo...")
            # resultados.append([valor_remessa, "Não encontrada"])
            if callable(status_callback):
                status_callback(i, "Liberada", valor_remessa)
            limpar_campo()
            continue  # Recomeça o loop

        else:
            log(f"[WARN] Estado inesperado após processamento da remessa {valor_remessa}.")
            # resultados.append([valor_remessa, "Indeterminado"])
            if callable(status_callback):
                status_callback(i, "Indeterminado", valor_remessa)
            limpar_campo()
            continue

    alt_f4()
    alt_f4()
    log("[INFO] Processamento concluído.")
    return resultados



# =================== ETAPA 3 — ORQUESTRAÇÃO =================== #
def iniciar_automacao(data=None, planta=None, log_fn=print):
    inicio_execucao = registrar_evento_execucao(
        "wmex1120_processar_remessa",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
    )
    resultados = []

    # --- INÍCIO DA AUTOMAÇÃO --- #
    log_fn("[INFO] Iniciando automação...")
    time.sleep(0.3)
    acao_limpar()
    time.sleep(0.3)

    # Captura hash inicial
    hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

    ignorar_textos = ["programas"]
    opcoes_textos = {"programa": ["programa"]}
    resultado = aguardar_textos(TRANSACAO_CAPTURAR, opcoes_textos, timeout=25, 
                                log_fn=log, ordem_blocos=[1], deslocamento_x=0.8, 
                                n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                stop_checker=lambda: stop_requested)
    if not resultado:
        registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="erro", detalhe="Tela inicial não confirmada")
        return log("[ERRO] Tela inicial não confirmada.")

    # --- Determina fluxo --- #
    if data and len(data) > 0:
        log(f"[INFO] Remessas fornecidas manualmente ({len(data)}).")

        if not digitar_transacao(TRANSACAO_PROCESSAR):
            registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="erro", detalhe=f"Falha ao digitar transação {TRANSACAO_PROCESSAR}")
            return log(f"[ERRO] Falha ao digitar transação {TRANSACAO_PROCESSAR}.")
        time.sleep(0.5)

        # --- aguarda mudança perceptível da tela --- #
        hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

        if not mudou:
            log_fn("[WARN] Nenhuma mudança visual detectada após digitação.")

        resultados = iniciar_processamento_remessas(TRANSACAO_PROCESSAR, data)



    else:
        log_fn("[INFO] Nenhuma remessa fornecida. Iniciando captura automática...")

        if not digitar_transacao(TRANSACAO_CAPTURAR):
            registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="erro", detalhe=f"Falha ao digitar transação {TRANSACAO_CAPTURAR}")
            return log_fn(f"[ERRO] Falha ao digitar transação {TRANSACAO_CAPTURAR}.")

        # Aguarda mudança após digitação da transação
        hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

        if not mudou:
            log_fn("[WARN] Nenhuma mudança visual detectada após digitação (captura automática).")

        remessas = iniciar_captura_remessas(TRANSACAO_CAPTURAR, planta)

        if not remessas:
            registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="sem_dados", detalhe="Nenhuma remessa encontrada")
            log_fn("[INFO] Nenhuma remessa encontrada.")
            return []

        # Captura hash inicial
        hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

        alt_f4()
        time.sleep(1)

        # --- aguarda mudança perceptível da tela --- #
        hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)
        time.sleep(0.2)

        ignorar_textos = ["programas"]
        opcoes_textos = {"programa": ["programa"]}
        resultado = aguardar_textos(TRANSACAO_CAPTURAR, opcoes_textos, timeout=60,
                                    log_fn=log_fn, ordem_blocos=[1], deslocamento_x=0.8,
                                    n_clicks=5, clicar=True, modo="auto", ignorar_textos=ignorar_textos,
                                    stop_checker=lambda: stop_requested)
        if not resultado:
            registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="erro", detalhe="Tela inicial não confirmada após captura")
            return log_fn("[ERRO] Tela inicial não confirmada.")

        if not digitar_transacao(TRANSACAO_PROCESSAR):
            registrar_evento_execucao("wmex1120_processar_remessa", "fim", inicio=inicio_execucao, status="erro", detalhe=f"Falha ao digitar transação {TRANSACAO_PROCESSAR}")
            return log_fn(f"[ERRO] Falha ao digitar transação {TRANSACAO_CAPTURAR}.")

        hash_ref, mudou = detectar_mudanca_tela(hash_ref, limiar=6, max_espera=3.5, log_fn=log_fn)

        if not mudou:
            log_fn("[WARN] Nenhuma mudança visual detectada após digitação (processamento).")

        resultados = iniciar_processamento_remessas(TRANSACAO_PROCESSAR, remessas)

    registrar_evento_execucao(
        "wmex1120_processar_remessa",
        "fim",
        inicio=inicio_execucao,
        status="sucesso",
        linhas_processadas=len(resultados) if resultados else 0,
    )
    log_fn("[INFO] Automação finalizada.")
    return resultados

if __name__ == "__main__":
    iniciar_automacao()
