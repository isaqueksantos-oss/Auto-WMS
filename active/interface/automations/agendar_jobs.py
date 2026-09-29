import os
import time
import subprocess
import psutil
from pathlib import Path
import imagehash
import pyperclip
from PIL import Image
from interface.automations.base_automation import aguardar_textos
from interface.automations.limpeza_file import limpar_arquivo_sap
import numpy as np
import shutil
from datetime import datetime

try:
    from win32com.client import GetObject, Dispatch
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False

# =================== VARIÁVEIS GLOBAIS =================== #

logger = print  # função de log externa (pode ser substituída)
status_callback = None  # função de callback opcional: fn(row_index:int, status:str, value:Optional[str]=None)
stop_requested = False
TRANSACAO = "AGENDAR_JOBS"

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


def _obter_caminho_log_execucao() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    pasta_logs = base_dir / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)
    return pasta_logs / "agendar_jobs_execucao.txt"


def _registrar_log_execucao(evento: str, nome_job: str = "", usuario_job: str = "", status: str = "", detalhe: str = "") -> None:
    try:
        caminho_log = _obter_caminho_log_execucao()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linha = (
            f"[{timestamp}] evento={evento} status={status or '-'} "
            f"job={nome_job or '-'} usuario_job={usuario_job or '-'}"
        )
        if detalhe:
            linha += f" detalhe={detalhe}"
        with open(caminho_log, "a", encoding="utf-8") as arquivo_log:
            arquivo_log.write(linha + "\n")
            arquivo_log.flush()
            os.fsync(arquivo_log.fileno())
    except Exception:
        pass


def _registrar_marcador_tentativa(tentativa_atual: int, nome_job: str = "", usuario_job: str = "") -> None:
    """Registra um separador visual para reinicio de tentativa no log externo."""
    _registrar_log_execucao(
        evento="retry_inicio",
        nome_job=nome_job,
        usuario_job=usuario_job,
        status=f"tentativa_{tentativa_atual}",
        detalhe=f"reiniciando tentativa {tentativa_atual}/2",
    )

def colar_do_clipboard(texto: str, intervalo_ms: int = 50) -> None:
    """
    Copia um texto para o clipboard e o cola usando Ctrl+V.
    
    Este método é mais seguro que digitação direta para:
    - Credenciais e dados sensíveis
    - Textos com caracteres especiais
    - Evitar problemas de velocidade de digitação
    
    Parâmetros:
        texto: O texto a ser colado
        intervalo_ms: Intervalo em ms entre copiar e colar (padrão: 50ms)
    """
    try:
        
        # Copiar para clipboard
        pyperclip.copy(texto)
        time.sleep(intervalo_ms / 1000.0)  # Converter ms para segundos
        
        # Colar usando Ctrl+V
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(intervalo_ms / 1000.0)
        
    except ImportError:
        # Se pyperclip não estiver instalado, usar método alternativo com win32com
        try:
            import ctypes
            # Usar método Windows nativo via ctypes (alternativa)
            # Copiar para clipboard usando o método do Windows
            cmd = f'powershell -Command "Set-Clipboard -Value \'{texto}\'"'
            subprocess.run(cmd, shell=True, capture_output=True)
            time.sleep(intervalo_ms / 1000.0)
            
            # Colar
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(intervalo_ms / 1000.0)
        except Exception as e:
            log(f"[AVISO] Erro ao usar clipboard: {e}. Usando digitação como fallback.")
            pyautogui.write(texto)

def verificar_tamanho_lista(dados, planta=None, *, tamanho_esperado):
    if dados:
        return len(dados[0]) >= tamanho_esperado
    if planta:
        return len(planta) >= tamanho_esperado
    return False

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


def wait_window(matches, timeout=None, interval=0.2):
    """
    Procura por janelas usando texto no título (case-insensitive).
    Quando encontra, ativa a janela, maximiza e chama o handler.
    
    Args:
        matches: dict {"texto a localizar": handler_function}
        timeout: tempo máximo de espera em segundos
        interval: intervalo de verificação em segundos
    
    Returns:
        str: chave da primeira janela encontrada, None se timeout
    
    Exemplo:
        def handle_login(janela):
            pyautogui.write("usuario")
            time.sleep(0.5)
            pyautogui.press("tab")
        
        resultado = wait_window(
            {"sap logon": handle_login},
            timeout=30
        )
    """
    if not PYGETWINDOW_AVAILABLE:
        log("[ERRO] pygetwindow não está instalado. Instale com: pip install pygetwindow")
        return None
    
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            janelas = gw.getAllTitles()
            lower = [t.lower() for t in janelas]

            for texto, handler in matches.items():
                texto_lower = texto.lower()
                for titulo in lower:
                    if texto_lower in titulo:
                        log(f"[HIT] Janela detectada: '{texto}' em '{titulo}'")
                        janela_encontrada = gw.getWindowsWithTitle(titulo)[0]
                        
                        try:
                            # Ativar e maximizar a janela
                            janela_encontrada.activate()
                            time.sleep(0.2)
                            janela_encontrada.maximize()
                            time.sleep(0.3)
                        except Exception as e:
                            log(f"[AVISO] Erro ao ativar/maximizar janela: {e}")
                        
                        try:
                            # Executar o handler
                            handler(janela_encontrada)
                        except Exception as e:
                            log(f"[ERRO] Erro ao executar handler: {e}")
                        
                        return texto
            
            time.sleep(interval)
        except Exception as e:
            log(f"[AVISO] Erro ao procurar janelas: {e}")
            time.sleep(interval)

    log(f"[AVISO] Timeout ao procurar janelas: {list(matches.keys())}")
    return None


# =================== GERENCIAMENTO DE ARQUIVOS TEMPORÁRIOS =================== #

def criar_pasta_temporaria(nome_base: str) -> Path:
    """
    Cria uma pasta temporária única para processar arquivos.
    
    Localização: %LOCALAPPDATA%/AutoWMS/temp/{timestamp}_{nome_base_sanitizado}/
    
    Args:
        nome_base: Nome descritivo para a pasta (ex: "job_teste")
                   Acentos serão removidos para compatibilidade
    
    Returns:
        Path à pasta criada
    """
    try:
        import unicodedata
        
        # Remover acentos do nome_base para evitar problemas de encoding no SAP
        nome_base_sanitizado = ''.join(
            c for c in unicodedata.normalize('NFD', nome_base)
            if unicodedata.category(c) != 'Mn'
        )
        # Remover outros caracteres problemáticos
        nome_base_sanitizado = nome_base_sanitizado.replace('/', '_').replace('\\', '_')
        
        # Obter pasta LOCALAPPDATA
        local_appdata = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local')))
        
        # Criar estrutura: AutoWMS/temp/
        pasta_base = local_appdata / "AutoWMS" / "temp"
        pasta_base.mkdir(parents=True, exist_ok=True)
        
        # Criar pasta única com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # YYYYMMDD_HHMMSS_mmm
        pasta_temp = pasta_base / f"{timestamp}_{nome_base_sanitizado}"
        pasta_temp.mkdir(parents=True, exist_ok=True)
        
        log(f"[INFO] Pasta temporária criada: {pasta_temp}")
        return pasta_temp
        
    except Exception as e:
        log(f"[ERRO] Falha ao criar pasta temporária: {e}")
        raise


def limpar_pasta_temporaria(pasta_temp: Path) -> bool:
    """
    Remove a pasta temporária e todo seu conteúdo.
    
    Args:
        pasta_temp: Caminho à pasta temporária
    
    Returns:
        True se sucesso, False caso contrário
    """
    try:
        if pasta_temp.exists():
            shutil.rmtree(pasta_temp)
            log(f"[OK] Pasta temporária removida: {pasta_temp}")
            return True
        else:
            log(f"[AVISO] Pasta temporária não encontrada para limpeza: {pasta_temp}")
            return False
            
    except Exception as e:
        log(f"[ERRO] Falha ao limpar pasta temporária: {e}")
        return False


# =================== UTILITÁRIOS DE SAP =================== #

def encontrar_sapgui() -> Path:
    """
    Localiza o executável do SAP GUI automaticamente.
    Procura em locais padrões de instalação do SAP.
    
    Retorna:
        Path ao saplogon.exe ou sapgui.exe, ou None se não encontrado
    """
    caminhos_possiveis = [
        Path("C:/Program Files/SAP/FrontEnd/SAPgui"),
        Path("C:/Program Files (x86)/SAP/FrontEnd/SAPgui"),
        Path("C:/SAP/FrontEnd/SAPgui"),
    ]
    
    nomes_exec = ["saplogon.exe", "sapgui.exe"]
    
    for caminho_base in caminhos_possiveis:
        if caminho_base.exists():
            for exec_name in nomes_exec:
                full_path = caminho_base / exec_name
                if full_path.exists():
                    return full_path
    
    # Tentar localizar em PATH do sistema
    try:
        result = subprocess.run(["where", "saplogon.exe"], capture_output=True, text=True)
        if result.returncode == 0:
            return Path(result.stdout.strip().split('\n')[0])
    except Exception:
        pass
    
    return None


def sap_esta_rodando() -> bool:
    """
    Verifica se SAP GUI já está em execução.
    
    Retorna:
        True se SAP está rodando, False caso contrário
    """
    for proc in psutil.process_iter(['name']):
        try:
            if 'saplogon' in proc.info['name'].lower() or 'sapgui' in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def iniciar_sap(sapgui_path: str, max_espera: int = 60, intervalo: int = 1) -> bool:
    """
    Inicia o SAP GUI e aguarda sua abertura.
    
    Parâmetros:
        sapgui_path: Caminho do executável do SAP
        max_espera: Tempo máximo de espera em segundos
        intervalo: Intervalo entre verificações em segundos
    
    Retorna:
        True se SAP foi iniciado com sucesso, False caso contrário
    """
    try:
        log("[INFO] Iniciando SAP GUI...")
        subprocess.Popen([str(sapgui_path)])
        
        # Aguardar SAP inicializar
        start = time.time()
        while time.time() - start < max_espera:
            if sap_esta_rodando():
                log("[OK] SAP GUI iniciado com sucesso.")
                time.sleep(2)  # Dar tempo extra para interface inicializar
                return True
            time.sleep(intervalo)
        
        log("[ERRO] Timeout aguardando SAP iniciar.")
        return False
        
    except Exception as e:
        log(f"[ERRO] Falha ao iniciar SAP: {e}")
        return False


# =================== UTILITÁRIOS DE CONEXÃO SAP =================== #


def finalizar_sap_forcado(log_fn=print) -> bool:
    """
    Mata o processo SAP LOGON/SAPGUI forçadamente.
    
    Percorre todos os processos em execução e mata aqueles com nomes:
    - saplogon.exe
    - sapgui.exe
    
    Parâmetros:
        log_fn: Função de logging
    
    Retorna:
        True se sucesso ou SAP não estava rodando, False se erro
    """
    try:
        log_fn("[INFO] Finalizando SAP (fechamento forçado)...")
        
        # Verificar se SAP está rodando
        if not sap_esta_rodando():
            log_fn("[INFO] SAP não estava em execução.")
            return True
        
        # Matar processos SAP
        processos_mortos = 0
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                proc_name = proc.info['name'].lower()
                if 'saplogon' in proc_name or 'sapgui' in proc_name:
                    log_fn(f"[INFO] Matando processo: {proc.info['name']} (PID: {proc.info['pid']})")
                    proc.kill()
                    processos_mortos += 1
                    time.sleep(0.3)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.PermissionError) as e:
                log_fn(f"[AVISO] Erro ao matar processo: {e}")
        
        # Aguardar para confirmar
        time.sleep(1)
        
        if not sap_esta_rodando():
            log_fn(f"[OK] SAP finalizado com sucesso ({processos_mortos} processo(s) morto(s)).")
            return True
        else:
            log_fn("[AVISO] SAP pode ainda estar rodando após tentativa de finalização.")
            return False
            
    except Exception as e:
        log_fn(f"[ERRO] Erro ao finalizar SAP: {e}")
        return False


def aguardar_sap_encerrar(max_espera: int = 30, intervalo: float = 1.0, log_fn=print) -> bool:
    """
    Aguarda os processos do SAP sumirem apos uma tentativa de encerramento.

    Retorna:
        True se o SAP encerrou dentro do tempo esperado, False caso contrario.
    """
    log_fn("[INFO] Aguardando encerramento completo do SAP...")
    for tentativa in range(1, max_espera + 1):
        if not sap_esta_rodando():
            log_fn("[OK] SAP encerrado completamente.")
            return True
        if tentativa == 1 or tentativa % 5 == 0:
            log_fn(f"[INFO] SAP ainda em encerramento... {tentativa}/{max_espera}s")
        time.sleep(intervalo)

    log_fn("[AVISO] Timeout aguardando o encerramento completo do SAP.")
    return False


def aguardar_arquivo_download_concluir(
    arquivo: Path,
    timeout: int = 1200,
    intervalo: float = 2.0,
    leituras_estaveis_necessarias: int = 4,
    confirmar_finalizacao_fn=None,
    log_fn=print,
) -> bool:
    """
    Aguarda o arquivo existir e estabilizar. Quando estabiliza, executa uma
    confirmacao visual opcional para validar que o SAP realmente concluiu o
    download antes de sair do loop.
    """
    log_fn(f"[INFO] Aguardando conclusao real do download: {arquivo}")

    inicio = time.time()
    tamanho_anterior = None
    mtime_anterior = None
    leituras_estaveis = 0
    ultimo_tamanho_logado = None

    while time.time() - inicio < timeout:
        if not arquivo.exists():
            time.sleep(intervalo)
            continue

        try:
            stat = arquivo.stat()
        except OSError as exc:
            log_fn(f"[AVISO] Falha ao consultar arquivo em download: {exc}")
            time.sleep(intervalo)
            continue

        tamanho_atual = stat.st_size
        mtime_atual = stat.st_mtime

        if tamanho_anterior is None:
            log_fn(f"[INFO] Arquivo criado. Tamanho inicial: {tamanho_atual} bytes")
            leituras_estaveis = 0
        elif tamanho_atual == tamanho_anterior and mtime_atual == mtime_anterior:
            leituras_estaveis += 1
            if leituras_estaveis == 1 or leituras_estaveis == leituras_estaveis_necessarias:
                log_fn(
                    f"[INFO] Arquivo sem mudanca ha {leituras_estaveis} leitura(s): "
                    f"{tamanho_atual} bytes"
                )
        else:
            leituras_estaveis = 0
            if ultimo_tamanho_logado != tamanho_atual:
                log_fn(f"[INFO] Download em andamento. Tamanho atual: {tamanho_atual} bytes")
                ultimo_tamanho_logado = tamanho_atual

        tamanho_anterior = tamanho_atual
        mtime_anterior = mtime_atual

        if leituras_estaveis >= leituras_estaveis_necessarias:
            log_fn(f"[INFO] Arquivo estabilizado em {tamanho_atual} bytes. Validando confirmacao visual...")

            if confirmar_finalizacao_fn is None:
                log_fn("[OK] Download finalizado. Confirmacao visual nao configurada.")
                return True

            try:
                if confirmar_finalizacao_fn():
                    log_fn(f"[OK] Download finalizado. Arquivo estabilizado em {tamanho_atual} bytes.")
                    return True
                log_fn("[INFO] Confirmacao visual ainda nao apareceu. Voltando a monitorar o arquivo.")
            except Exception as exc:
                log_fn(f"[AVISO] Erro na confirmacao visual do download: {exc}")

            leituras_estaveis = 0

        time.sleep(intervalo)

    log_fn("[ERRO] Timeout aguardando o arquivo terminar de ser gravado pelo SAP.")
    return False


def iniciar_automacao(nome_job, usuario_job, caminho_salvar_job, usuario_sap, senha_sap, conexao_sap, log_fn=print, tentativa_atual: int = 1):
    """
    Inicia a automação de agendamento de JOBs no SAP.
    
    Parâmetros:
        nome_job: Nome do JOB a ser agendado
        usuario_job: Usuário para executar o JOB
        caminho_salvar_job: Caminho onde o JOB será salvo
        usuario_sap: Usuário SAP para login
        senha_sap: Senha SAP para login
        conexao_sap: Nome da conexão SAP (ex: "SYS", "PRD", "DEV")
        log_fn: Função de logging
    
    Retorna:
        True se executado com sucesso, False caso contrário
    """
    def handle_conexao(janela):
        try:            
            janela.activate()
            time.sleep(0.2)
            janela.maximize()
            time.sleep(0.3)

            pyautogui.typewrite(conexao_sap, interval=0.05)
            time.sleep(0.5)
            pyautogui.press('enter')
            time.sleep(1)
        except Exception as e:
            log_fn(f"[ERRO] Não foi possível trazer a janela para foco: {e}")

    
    def handle_login(janela):
        colar_do_clipboard(usuario_sap)
        time.sleep(0.3)
        pyautogui.press("tab")
        time.sleep(0.3)
        colar_do_clipboard(senha_sap)
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(1)

    def handle_derrubar(janela):
        time.sleep(0.5)
        pyautogui.press('enter')
        time.sleep(1)

    def handle_sm37(janela):
        time.sleep(0.5)
        opcoes_textos = {"s_e_a": ["easy", "access", "menu"]}
        resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=15, 
                                    log_fn=log, ordem_blocos=[1], deslocamento_x=0, 
                                    n_clicks=0, clicar=True, modo="neutro")
        if not resultado:
            log_fn("[ERRO] Tela inicial não confirmada.")
            raise RuntimeError("Tela inicial não confirmada.")
        pyautogui.press("esc")
        time.sleep(0.3)
        pyautogui.press("esc")
        time.sleep(0.5)
        pyautogui.write("SM37")
        time.sleep(0.2)
        pyautogui.press("enter")

    def handle_selecao_job(janela):
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.press("delete")
        pyautogui.press("backspace")
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.press("delete")
        pyautogui.press("backspace")
        time.sleep(0.3)
        colar_do_clipboard(nome_job)
        time.sleep(0.3)
        pyautogui.press("tab")
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.press("delete")
        pyautogui.press("backspace")
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.press("delete")
        pyautogui.press("backspace")
        time.sleep(0.3)
        colar_do_clipboard(usuario_job)

        # Desmarcar opções: tab tab esp tab esp tab esp tab tab esp
        time.sleep(0.3)
        pyautogui.press("tab", presses=2, interval=0.2)
        time.sleep(0.3)
        pyautogui.press("space")
        time.sleep(0.2)
        pyautogui.press("tab")
        time.sleep(0.3)
        pyautogui.press("space")
        time.sleep(0.2)
        pyautogui.press("tab")
        time.sleep(0.3)
        pyautogui.press("space")
        time.sleep(0.2)
        pyautogui.press("tab", presses=2, interval=0.2)
        time.sleep(0.1)
        pyautogui.press("space")

        time.sleep(0.5)
        pyautogui.press("f8", presses=2, interval=0.3)

    def handle_sintese_jobs(janela):
        pyautogui.hotkey('ctrl', 'shift', 'f8')
        time.sleep(0.5)

    def handle_controle_saida_spool(janela):
        pyautogui.press('tab')
        time.sleep(0.5)
        pyautogui.press('f6')
        time.sleep(1)

    def handle_exibicao_graf_ordem_spool(janela):
        pyautogui.hotkey('ctrl', 'shift', 'f12')
        time.sleep(3)

    def handle_gravar_lista(janela):
        pass


# --- INÍCIO DA AUTOMAÇÃO --- #
    if tentativa_atual > 1:
        log_fn("")
        log_fn("[INFO] ==============================")
        log_fn(f"[INFO] Reiniciando tentativa {tentativa_atual}/2")
        log_fn("[INFO] ==============================")
        _registrar_marcador_tentativa(tentativa_atual, nome_job=nome_job, usuario_job=usuario_job)
    log_fn("[INFO] Iniciando automação de Agendar JOBs...")
    log_fn(f"[INFO] Tentativa {tentativa_atual}/2.")
    _registrar_log_execucao(
        evento="inicio",
        nome_job=nome_job,
        usuario_job=usuario_job,
        status=f"tentativa_{tentativa_atual}",
    )
    time.sleep(0.3)
    
    # --- Validação de parâmetros --- #
    if not nome_job or not usuario_job or not caminho_salvar_job:
        log_fn("[ERRO] Parâmetros obrigatórios do JOB não preenchidos.")
        raise RuntimeError("Parâmetros não preenchidos")
    
    if not usuario_sap or not senha_sap:
        log_fn("[ERRO] Credenciais SAP não preenchidas.")
        raise RuntimeError("Credenciais SAP não preenchidas")
    
    log_fn(f"[INFO] Parâmetros recebidos:")
    log_fn(f"  - Nome JOB: {nome_job}")
    log_fn(f"  - Usuário JOB: {usuario_job}")
    log_fn(f"  - Caminho Salvar: {caminho_salvar_job}")
    log_fn(f"  - Usuário SAP: {usuario_sap}")
    
    # --- INICIALIZAR SAP --- #
    try:
        log_fn("[INFO] Verificando status do SAP...")
        
        # Verificar se SAP já está rodando
        if not sap_esta_rodando():
            log_fn("[INFO] SAP não detectado. Localizando executável...")
            
            # Localizar SAP automaticamente
            sapgui_path = encontrar_sapgui()
            if not sapgui_path:
                log_fn("[ERRO] Não foi possível localizar SAP GUI no sistema.")
                log_fn("[INFO] Locais procurados:")
                log_fn("  - C:/Program Files/SAP/FrontEnd/SAPgui")
                log_fn("  - C:/Program Files (x86)/SAP/FrontEnd/SAPgui")
                log_fn("  - C:/SAP/FrontEnd/SAPgui")
                raise RuntimeError("SAP GUI não encontrado")            
            
            log_fn(f"[OK] SAP GUI encontrado em: {sapgui_path}")
            
            # Iniciar SAP
            if not iniciar_sap(str(sapgui_path)):
                log_fn("[ERRO] Falha ao iniciar SAP.")
                raise RuntimeError("Falha ao iniciar SAP")
        else:
            log_fn("[OK] SAP já está em execução.")
        
        # --- CONECTAR AO SAP --- #
        
        log_fn("[INFO] Conectando à sessão SAP...")

        resultado = wait_window(
            {"Logon": handle_conexao},
            timeout=30
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao abrir a conexão SAP.")
            raise RuntimeError("Falha ao abrir a conexão SAP")

        log_fn("[OK] Conectado ao SAP com sucesso!")
         
        # --- AGENDAMENTO DE JOB --- #
        log_fn("[INFO] Iniciando agendamento de JOB no SAP...")
        log_fn(f"[INFO] JOB: {nome_job}, Usuário: {usuario_job}, Caminho: {caminho_salvar_job}")

        hash_ref, _ = detectar_mudanca_tela(max_espera=0.1, log_fn=lambda *_: None)

        opcoes_textos = {"mandante": ["mandante", "nova senha"]}
        resultado = None
        for tentativa in range(4):
            resultado = aguardar_textos(
                TRANSACAO,
                opcoes_textos,
                timeout=10,
                log_fn=log,
                ordem_blocos=[1],
                deslocamento_x=0.0,
                n_clicks=0,
                clicar=False,
                modo="neutro",
            )
            if resultado:
                break

            if tentativa >= 3:
                log_fn("[ERRO] Tela inicial não confirmada.")
                raise RuntimeError("Tela inicial não confirmada.")

            log_fn(f"[AVISO] Tela inicial não confirmada. Reabrindo conexão SAP ({tentativa + 1}/3)...")

            resultado_janela = wait_window(
                {"Logon": handle_conexao},
                timeout=2
            )
            if resultado_janela is None:
                log_fn("[AVISO] Janela SAP Logon não encontrada para reenviar a conexão.")
        
        resultado = wait_window(
            {"sap": handle_login},
            timeout=10
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao realizar login no SAP.")
            raise RuntimeError("Falha ao realizar login no SAP")

        loop_derrubar = 0
        while loop_derrubar < 5:
            # espera texto
            opcoes_textos = {"seguir": ["continuar","e possivel","possivel"]}
            resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=2, 
                                        log_fn=log, ordem_blocos=[11, 16, 6], deslocamento_x=0, 
                                        n_clicks=2, clicar=True, modo="neutro")
            if not resultado:
                log_fn("[ERRO] Tela derrubar login não confirmada.")
            else:
                pyautogui.press('tab')
                time.sleep(1)
                pyautogui.press('up')
                time.sleep(1)
                pyautogui.press('enter')
                time.sleep(1)
                pyautogui.press('enter')
            
            resultado = wait_window(
                {"menu usuario": handle_sm37, "easy access": handle_sm37},
                timeout=2
            )
            if resultado is None:
                log_fn("[ERRO] Falha ao acessar a transação SM37.")

            else:
                break
            loop_derrubar += 1
            if loop_derrubar >=10:
                log_fn("[ERRO] Falha ao acessar a transação SM37.")
                raise RuntimeError("Falha ao acessar a transação SM37.")

        resultado = wait_window(
            {"Seleção de job simples": handle_selecao_job},
            timeout=20
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao encontrar job.")
            raise RuntimeError("Falha ao encontrar job.")

        resultado = wait_window(
            {"Síntese de jobs": handle_sintese_jobs},
            timeout=20
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao exibir job.")
            raise RuntimeError("Falha ao exibir job.")
        
        resultado = wait_window(
            {"Controle de saída": handle_controle_saida_spool},
            timeout=20
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao expandir job.")
            raise RuntimeError("Falha ao expandir job.")
        
        resultado = wait_window(
            {"Exibição gráfica de ordem spool": handle_exibicao_graf_ordem_spool},
            timeout=1200
        )
        if resultado is None:
            log_fn("[ERRO] Falha ao expandir spool.")
            raise RuntimeError("Falha ao expandir spool.")

        # Esperamos a tela "gravar lista 01" aparecer

        opcoes_textos = {"opcoes salvar": ["nao convert","planilha eletronica", "rich text", "eletronica", "planilha", "rich", "text"]}
        resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=20, 
                                    log_fn=log, ordem_blocos=[13,23,18,8], deslocamento_x=0, 
                                    n_clicks=0, clicar=False, modo="auto")
        if resultado:
            pyautogui.press('enter')
            time.sleep(1)

        else:        
            opcoes_textos = {"gravar lista": ["gravar lista em file", "gravar lista", "gravar", "lista em file", "lista"]}
            resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=20, 
                                        log_fn=log, ordem_blocos=[8,13], deslocamento_x=0, 
                                        n_clicks=1, clicar=False, modo="auto")
            
            if resultado:
                pyautogui.press('enter')
                time.sleep(1)
            else:
                log_fn("[ERRO] Tela de gravação de lista não confirmada.")
            raise RuntimeError("Tela de gravação de lista não confirmada.")
            
        # Tela inserir diretório e nome do arquivo
        # Usar pasta temporária para salvamento intermediário
        pasta_temp = criar_pasta_temporaria(nome_job)
        caminho_temp = str(pasta_temp)
        nome_arquivo_temp = nome_job + ".txt"

        opcoes_textos = {"diretorio": ["diretorio"]}
        resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=1200, 
                                    log_fn=log, ordem_blocos=[6, 11], deslocamento_x=4, 
                                    n_clicks=2, clicar=True, modo="auto")
        if resultado:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.3)
            pyautogui.press("delete")
            pyautogui.press("backspace")
            time.sleep(0.5)
            # Salvar em pasta TEMPORÁRIA (não direto no destino final)
            # Usar clipboard para evitar problemas de encoding com acentos
            colar_do_clipboard(caminho_temp)
            time.sleep(0.5)
            pyautogui.press('tab')
            time.sleep(0.5)
            # Inserir nome do arquivo temporário
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.3)
            pyautogui.press("delete")
            pyautogui.press("backspace")
            time.sleep(0.5)
            colar_do_clipboard(nome_arquivo_temp)
            time.sleep(0.5)
            pyautogui.hotkey('ctrl', 's')

        else:
            log_fn("[ERRO] Tela de inserção de diretório não confirmada.")
            limpar_pasta_temporaria(pasta_temp)
            raise RuntimeError("Tela de inserção de diretório não confirmada.") 

        # --- FLUXO DE PÓS-PROCESSAMENTO ---
        # 1. Verificar se arquivo foi salvo
        arquivo_temp = pasta_temp / nome_arquivo_temp
        time.sleep(2)

        # Loop esperando o arquivo ser criado
        log_fn("[INFO] Aguardando arquivo ser salvo...")
        espera_arquivo = 0
        while espera_arquivo < 1200:
            if arquivo_temp.exists():
                log_fn(f"[OK] Arquivo salvo: {arquivo_temp}")
                break
            else:
                opcoes_textos = {"memorizar": ["memorizar"]}
                resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=3, 
                                            log_fn=log, ordem_blocos=[11], deslocamento_x=0, 
                                            n_clicks=0, clicar=False, modo="auto")
                if resultado:
                    pyautogui.hotkey('alt', 'p')
                    time.sleep(1)
                    

            time.sleep(1)
            espera_arquivo += 1
        
        if not arquivo_temp.exists():
            log_fn("[ERRO] Arquivo .txt não foi salvo no tempo esperado.")
            limpar_pasta_temporaria(pasta_temp)
            raise RuntimeError("Arquivo .txt não foi salvo no tempo esperado.")
        
        def confirmar_download_finalizado() -> bool:
            opcoes_textos = {"code_page": ["code page", "bytes transf", "code", "page", "bytes", "transf"]}
            resultado = aguardar_textos(TRANSACAO, opcoes_textos, timeout=5, 
                                        log_fn=log, ordem_blocos=[21], deslocamento_x=0, 
                                        n_clicks=0, clicar=False, modo="auto")
            if resultado:
                pyautogui.hotkey('alt', 'a')
                time.sleep(1)
                return True
            return False

        if not aguardar_arquivo_download_concluir(
            arquivo_temp,
            timeout=1200,
            intervalo=2.0,
            leituras_estaveis_necessarias=4,
            confirmar_finalizacao_fn=confirmar_download_finalizado,
            log_fn=log_fn,
        ):
            log_fn("[ERRO] Nao foi possivel finalizar o download.")
            limpar_pasta_temporaria(pasta_temp)
            raise RuntimeError("Nao foi possivel finalizar o download.")

        # 2. Aplicar limpeza de dados (converte .txt → .xlsx)
        log_fn("[INFO] Iniciando limpeza de dados (txt → xlsx)...")
        try:
            # Importar o logger para o módulo de limpeza
            from interface.automations.limpeza_file import set_logger
            set_logger(log_fn)

            # Chamar função de limpeza
            arquivo_xlsx, arquivo_parquet = limpar_arquivo_sap(str(arquivo_temp), exportar_para_bq=True)
            log_fn(f"[OK] Arquivo limpo gerado: {arquivo_xlsx} e {arquivo_parquet}")
        except Exception as e:
            log_fn(f"[ERRO] Falha ao limpar dados: {e}")
            limpar_pasta_temporaria(pasta_temp)
            raise RuntimeError("Falha ao limpar dados.")
        
        # 3. Mover arquivo .xlsx para destino final
        log_fn("[INFO] Movendo arquivo para destino final...")
        try:
            arquivo_xlsx_path = Path(arquivo_xlsx)
            arquivo_parquet_path = Path(arquivo_parquet)

            if not arquivo_xlsx_path.exists():
                log_fn(f"[AVISO] Arquivo .xlsx não encontrado para mover: {arquivo_xlsx_path}")
            if not arquivo_parquet_path.exists():
                log_fn(f"[ERRO] Arquivo .parquet não encontrado para mover: {arquivo_parquet_path}")
                raise FileNotFoundError(f"Parquet não encontrado: {arquivo_parquet_path}")

            nome_arquivo_xlsx = arquivo_xlsx_path.name
            caminho_final = Path(caminho_salvar_job) / nome_arquivo_xlsx
            nome_arquivo_parquet = arquivo_parquet_path.name
            caminho_final_parquet = Path(caminho_salvar_job) / "parquet" / nome_arquivo_parquet
            
            # Criar pasta destino se não existir
            Path(caminho_salvar_job).mkdir(parents=True, exist_ok=True)
            Path(caminho_final_parquet).parent.mkdir(parents=True, exist_ok=True)
            
            # Mover arquivo
            import shutil
            if arquivo_xlsx_path.exists():
                shutil.move(str(arquivo_xlsx_path), str(caminho_final))
            shutil.move(str(arquivo_parquet_path), str(caminho_final_parquet))
            log_fn(f"[OK] Arquivo movido para: {caminho_final_parquet}")
        except Exception as e:
            log_fn(f"[ERRO] Falha ao mover arquivo: {e}")
            limpar_pasta_temporaria(pasta_temp)
            raise RuntimeError("Falha ao mover arquivo.")
        
        # 4. Limpar pasta temporária
        log_fn("[INFO] Limpando pasta temporária...")
        limpar_pasta_temporaria(pasta_temp)
        
        # 5. Finalizar SAP
        log_fn("[INFO] Encerrando SAP...")
        finalizar_sap_forcado(log_fn)

        log_fn("[INFO] Automação de Agendar JOBs concluída com sucesso.")
        _registrar_log_execucao(
            evento="fim",
            nome_job=nome_job,
            usuario_job=usuario_job,
            status="sucesso",
        )
        return True
        
    except Exception as e:
        log_fn(f"[ERRO] Falha ao executar automação: {e}")
        # Tentar finalizar SAP mesmo em caso de erro
        try:
            log_fn("[INFO] Finalizando SAP por causa de erro...")
            finalizar_sap_forcado(log_fn)
            aguardar_sap_encerrar(log_fn=log_fn)
        except Exception as cleanup_error:
            log_fn(f"[AVISO] Erro ao limpar SAP: {cleanup_error}")
            raise RuntimeError("Erro ao limpar SAP após falha na automação.")

        if tentativa_atual < 2:
            _registrar_log_execucao(
                evento="retry",
                nome_job=nome_job,
                usuario_job=usuario_job,
                status=f"falha_tentativa_{tentativa_atual}",
                detalhe=str(e),
            )
            log_fn("[INFO] Reiniciando a automação desde o início...")
            return iniciar_automacao(
                nome_job,
                usuario_job,
                caminho_salvar_job,
                usuario_sap,
                senha_sap,
                conexao_sap,
                log_fn,
                tentativa_atual=tentativa_atual + 1,
            )

        _registrar_log_execucao(
            evento="fim",
            nome_job=nome_job,
            usuario_job=usuario_job,
            status="erro",
            detalhe=str(e),
        )
        return False
    finally:
        clear_stop()
        finalizar_sap_forcado(log_fn)


if __name__ == "__main__":
    iniciar_automacao("JOB_TESTE", "usuario_teste", "/caminho/teste", "usuario_sap", "senha_sap", "SYS")

