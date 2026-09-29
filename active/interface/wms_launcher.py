import os
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

import keyring
import pyautogui
import pygetwindow as gw

from interface.automations.base_automation import aguardar_textos
from interface.utils.config_manager import carregar_config

APP_NAME = "AutoWMS"


class EstadoWMS(Enum):
    INIT = 1
    AGUARDANDO = 2
    UPDATE = 3
    SEGURANCA = 4
    LOGIN = 5
    LOGADO = 6
    ERRO = 7


def abrir_jnlp(caminho_jnlp: str) -> None:
    if not os.path.exists(caminho_jnlp):
        raise FileNotFoundError(f"Arquivo JNLP nao encontrado: {caminho_jnlp}")

    try:
        os.startfile(caminho_jnlp)
    except AttributeError:
        subprocess.Popen([caminho_jnlp], shell=True)
    except Exception as exc:
        raise RuntimeError(f"Falha ao abrir JNLP: {exc}") from exc


def detectar_janelas_de_alerta_wms():
    titulos = gw.getAllTitles()
    lower = [titulo.lower() for titulo in titulos]

    return {
        "update": any("java update necessario" in titulo or "java update necess" in titulo for titulo in lower),
        "seguranca": any("advertencia de seguranca" in titulo or ("advert" in titulo and "seguran" in titulo) for titulo in lower),
        "login": any("wms americanas - login" in titulo for titulo in lower),
        "logado": any("wms americanas (usu" in titulo for titulo in lower),
    }


def listar_titulos_wms():
    """
    Retorna os titulos de janela que contem 'wms' ou 'java'.

    Util para diagnostico: mostra exatamente o que o launcher esta
    enxergando quando decide se o WMS ja esta aberto.
    """
    encontrados = []
    for titulo in gw.getAllTitles():
        limpo = (titulo or "").strip()
        if not limpo:
            continue
        baixo = limpo.lower()
        if "wms" in baixo or "java" in baixo or "forms" in baixo:
            encontrados.append(limpo)
    return encontrados


def fechar_wms_existente(log_fn=print) -> bool:
    """
    Fecha qualquer janela do WMS ainda aberta (inclusive a que caiu com
    FRM-92103 e mantem o titulo 'WMS AMERICANAS (Usuario...)').

    Sem isso, detectar_janelas_de_alerta_wms() continua retornando
    logado=True e o launcher nunca reabre a aplicacao.
    """
    fechou = False

    # Confirma popups de erro que estejam em foco (ex.: FRM-92103).
    try:
        pyautogui.press("enter")
        time.sleep(0.5)
    except Exception:
        pass

    for titulo in list(gw.getAllTitles()):
        baixo = (titulo or "").lower()
        if "wms americanas" not in baixo:
            continue

        try:
            for janela in gw.getWindowsWithTitle(titulo):
                try:
                    janela.activate()
                    time.sleep(0.2)
                except Exception:
                    pass

                try:
                    janela.close()
                except Exception:
                    pyautogui.hotkey("alt", "f4")

                fechou = True
                time.sleep(0.6)
        except Exception as exc:
            log_fn(f"[WARN] Falha ao fechar janela '{titulo}': {exc}")

    if fechou:
        # Confirma eventual dialogo de "deseja sair?".
        try:
            pyautogui.press("enter")
            time.sleep(0.4)
        except Exception:
            pass

    log_fn(
        f"[INFO] Janelas WMS anteriores: "
        f"{'fechadas' if fechou else 'nenhuma encontrada'}."
    )
    return fechou


def handle_advertencia(log_fn=print):
    log_fn("[INFO] Confirmando ADVERTENCIA DE SEGURANCA...")
    time.sleep(0.5)

    opcoes_textos = {"advert": ["risco", "aceito", "eu aceito"]}
    resultado = aguardar_textos(
        "WMMS",
        opcoes_textos,
        timeout=20,
        log_fn=log_fn,
        ordem_blocos=[18, 17, 13],
        deslocamento_x=0,
        n_clicks=1,
        clicar=True,
        modo="auto",
    )

    if not resultado:
        raise RuntimeError("Tela de seguranca nao confirmada")

    pyautogui.press("enter")


def handle_update(log_fn=print):
    log_fn("[INFO] Confirmando JAVA UPDATE NECESSARIO...")
    time.sleep(0.5)

    for _ in range(3):
        pyautogui.press("tab")
        time.sleep(0.2)

    pyautogui.press("space")


def handle_login(usuario: str, senha: str, log_fn=print):
    log_fn("[OK] Tela de login detectada: preenchendo credenciais...")

    janelas = gw.getWindowsWithTitle("wms americanas - login")
    if not janelas:
        raise RuntimeError("Janela de login do WMS nao encontrada")

    janela = janelas[0]
    janela.activate()
    janela.maximize()
    time.sleep(0.5)

    pyautogui.write(usuario)
    time.sleep(0.5)
    pyautogui.press("tab")
    time.sleep(0.5)
    pyautogui.write(senha)
    time.sleep(0.5)
    pyautogui.press("enter")
    time.sleep(1)


def fluxo_wms(usuario: str, senha: str, timeout: int = 300, log_fn=print) -> bool:
    estado = EstadoWMS.INIT
    estado_anterior = None
    inicio = time.time()
    login_realizado = False

    while time.time() - inicio < timeout:
        janelas = detectar_janelas_de_alerta_wms()

        if janelas["logado"]:
            estado = EstadoWMS.LOGADO
        elif janelas["update"]:
            estado = EstadoWMS.UPDATE
        elif janelas["seguranca"]:
            estado = EstadoWMS.SEGURANCA
        elif janelas["login"]:
            estado = EstadoWMS.LOGIN
        else:
            estado = EstadoWMS.AGUARDANDO

        # Loga apenas quando o estado muda, para nao poluir o log.
        if estado != estado_anterior:
            decorrido = int(time.time() - inicio)
            log_fn(f"[ESTADO] {estado.name} (t={decorrido}s)")
            estado_anterior = estado

        try:
            if estado == EstadoWMS.LOGADO:
                log_fn("[OK] WMS logado detectado.")
                return True

            if estado == EstadoWMS.UPDATE:
                handle_update(log_fn=log_fn)
                time.sleep(1)
                continue

            if estado == EstadoWMS.SEGURANCA:
                handle_advertencia(log_fn=log_fn)
                time.sleep(1)
                continue

            if estado == EstadoWMS.LOGIN:
                if not login_realizado:
                    handle_login(usuario, senha, log_fn=log_fn)
                    login_realizado = True
                time.sleep(2)
                continue

            time.sleep(1)
        except Exception as exc:
            log_fn(f"[ERRO] Falha no estado {estado.name}: {exc}")
            estado = EstadoWMS.ERRO
            break

    if estado == EstadoWMS.ERRO:
        return False

    log_fn("[ERRO] Timeout aguardando inicializacao do WMS.")
    return False


def iniciar_wms(caminho_wms: str, usuario: str, senha: str, timeout: int = 300, log_fn=print) -> bool:
    if not os.path.exists(caminho_wms):
        raise FileNotFoundError(f"Caminho invalido: {caminho_wms}")

    log_fn(f"[INFO] Iniciando WMS a partir de: {caminho_wms}")
    abrir_jnlp(caminho_wms)
    log_fn("[INFO] JNLP disparado. Aguardando janelas do WMS...")
    time.sleep(2)
    return fluxo_wms(usuario, senha, timeout=timeout, log_fn=log_fn)


def abrir_janela_wms(
    caminho_wms: str,
    usuario: str,
    senha: str,
    log_fn=print,
    timeout: int = 300,
    forcar: bool = False,
) -> bool:
    """
    Abre o WMS.

    Parametros:
        forcar: quando True, ignora a deteccao de "ja esta aberto" e
                fecha as janelas existentes antes de reabrir. Use nos
                casos de queda (FRM-92103), em que a janela morta
                mantem o titulo e enganaria a deteccao.
    """
    try:
        log_fn("Buscando janela do WMS...")

        titulos = listar_titulos_wms()
        log_fn(f"[DIAG] Janelas relacionadas encontradas: {titulos or 'nenhuma'}")

        if forcar:
            log_fn("[INFO] Modo forcar ativo: fechando WMS anterior...")
            fechar_wms_existente(log_fn=log_fn)
            time.sleep(1.5)
        else:
            janelas = detectar_janelas_de_alerta_wms()
            if janelas["logado"]:
                log_fn(
                    "Janela WMS ja esta aberta. "
                    "(Se o WMS caiu, use forcar=True para reabrir.)"
                )
                return True

        return iniciar_wms(
            caminho_wms,
            usuario,
            senha,
            timeout=timeout,
            log_fn=log_fn,
        )
    except Exception as exc:
        log_fn(f"[ERRO] Falha ao iniciar o WMS: {exc}")
        return False


def executar_wms_com_config_salva(
    log_fn=print,
    timeout: int = 300,
    forcar: bool = False,
) -> bool:
    """
    Le as credenciais/caminho salvos e abre o WMS.

    Diferente da versao anterior, NAO levanta excecao quando falta
    configuracao: registra o problema no log e retorna False. Assim o
    botao da interface nunca fica "mudo" por causa de uma excecao
    engolida por uma thread.
    """
    try:
        usuario, senha, caminho_wms, *_ = carregar_config()
    except Exception as exc:
        log_fn(f"[ERRO] Falha ao carregar configuracoes: {exc}")
        return False

    if not usuario:
        usuario = keyring.get_password(APP_NAME, "usuario")
    if not senha:
        senha = keyring.get_password(APP_NAME, "senha")

    # Diagnostico explicito do que esta faltando.
    faltando = []
    if not usuario:
        faltando.append("usuario")
    if not senha:
        faltando.append("senha")
    if not caminho_wms:
        faltando.append("caminho do JNLP")

    if faltando:
        log_fn(
            "[ERRO] Configuracao incompleta. "
            f"Faltando: {', '.join(faltando)}. "
            "Preencha e salve os dados na aba de configuracao."
        )
        return False

    log_fn(f"[INFO] Usuario configurado: {usuario}")
    log_fn(f"[INFO] Caminho JNLP: {caminho_wms}")

    if not os.path.exists(caminho_wms):
        log_fn(
            f"[ERRO] O arquivo JNLP nao existe no caminho informado: "
            f"{caminho_wms}"
        )
        return False

    return abrir_janela_wms(
        caminho_wms,
        usuario,
        senha,
        log_fn=log_fn,
        timeout=timeout,
        forcar=forcar,
    )


def reabrir_wms_apos_queda(log_fn=print, timeout: int = 300) -> bool:
    """
    Atalho para recuperacao apos queda do WMS (FRM-92103).

    Equivale a executar_wms_com_config_salva(forcar=True): fecha a
    janela morta e reabre a aplicacao.
    """
    return executar_wms_com_config_salva(
        log_fn=log_fn,
        timeout=timeout,
        forcar=True,
    )


def gerar_script_autologin(destino: str, project_root: Path | None = None) -> Path:
    caminho_destino = Path(destino)
    caminho_destino.parent.mkdir(parents=True, exist_ok=True)

    raiz_projeto = (project_root or Path(__file__).resolve().parents[1]).resolve()
    executavel_atual = Path(sys.executable).resolve()

    if getattr(sys, "frozen", False):
        comando = f'"{executavel_atual}" --run-wms-login'
    else:
        pythonw = executavel_atual.with_name("pythonw.exe")
        interpretador = pythonw if pythonw.exists() else executavel_atual
        comando = f'cd /d "{raiz_projeto}"\r\n"{interpretador}" -m interface.wms_launcher'

    script = f"@echo off\r\n{comando}\r\n"
    caminho_destino.write_text(script, encoding="utf-8")
    return caminho_destino


def diagnostico(log_fn=print) -> None:
    """
    Executa um diagnostico rapido e imprime tudo que o launcher enxerga.

    Rode no terminal para descobrir por que o botao "nao faz nada":
        python -m interface.wms_launcher --diagnostico
    """
    log_fn("=" * 60)
    log_fn("DIAGNOSTICO AUTO WMS")
    log_fn("=" * 60)

    try:
        usuario, senha, caminho_wms, *_ = carregar_config()
        log_fn(f"usuario (config)      : {usuario or '(vazio)'}")
        log_fn(f"senha (config)        : {'***' if senha else '(vazio)'}")
        log_fn(f"caminho_wms (config)  : {caminho_wms or '(vazio)'}")
    except Exception as exc:
        log_fn(f"[ERRO] carregar_config() falhou: {exc}")
        usuario = senha = caminho_wms = None

    if not usuario:
        kr_user = keyring.get_password(APP_NAME, "usuario")
        log_fn(f"usuario (keyring)     : {kr_user or '(vazio)'}")
    if not senha:
        kr_pass = keyring.get_password(APP_NAME, "senha")
        log_fn(f"senha (keyring)       : {'***' if kr_pass else '(vazio)'}")

    if caminho_wms:
        existe = os.path.exists(caminho_wms)
        log_fn(f"JNLP existe no disco  : {existe}")

    log_fn("-" * 60)
    log_fn(f"Janelas WMS/Java       : {listar_titulos_wms() or 'nenhuma'}")
    log_fn(f"Deteccao de estado     : {detectar_janelas_de_alerta_wms()}")
    log_fn("=" * 60)


def main() -> int:
    if "--diagnostico" in sys.argv:
        diagnostico()
        return 0

    forcar = "--forcar" in sys.argv
    sucesso = executar_wms_com_config_salva(forcar=forcar)
    return 0 if sucesso else 1


if __name__ == "__main__":
    raise SystemExit(main())
