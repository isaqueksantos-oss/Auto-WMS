import json
import os
import time
import shutil
import subprocess
from pathlib import Path
#from playwright.sync_api import sync_playwright
from interface.utils.config_manager import carregar_config
from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import (  # type: ignore
    aguardar_textos,
    copiar_para_clipboard,
    focus_manager,
    maximize_manager,
)

APP_NAME = "AutoWMS"
ESTADO_SESSAO_RELEX = "DLLs\\estado_relex.json"

logger = print
status_callback = None
stop_requested = False


def request_stop():
    global stop_requested
    stop_requested = True


def clear_stop():
    global stop_requested
    stop_requested = False


def log(message: str) -> None:
    try:
        logger(message)
    except Exception:
        print(message)


def _obter_caminho_edge() -> str | None:
    caminhos = [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
    ]
    for caminho in caminhos:
        if caminho and Path(caminho).exists():
            return caminho
    return None


def iniciar_automacao(
        link: str,
        usuario: str,
        senha: str,
        caminho_salvar: str,
        log_fn=None):

    log_fn = log_fn or print

    try:

        with sync_playwright() as pw:

            log_fn("[RELEX] Iniciando Edge...")

            navegador = pw.chromium.launch(
                channel="msedge",
                headless=False
            )

            context = navegador.new_context(storage_state=ESTADO_SESSAO_RELEX)
            pagina = context.new_page()

            def page_closed():
                log_fn("[RELEX] PAGE FECHADA")
                try:
                    log_fn(f"Pages restantes: {len(context.pages)}")
                    for i, p in enumerate(context.pages):
                        try:
                            log_fn(f"Page {i}: {p.url}")
                        except:
                            pass
                except Exception as e:
                    log_fn(e)
                        
            def detectar_estado_tela(pagina,timeout=1,tentativas=4,log_fn=None):
                log_fn = log_fn or print
                for i in range(tentativas):

                    log_fn(f"[RELEX] loop for {i} na função -detactar_estado_tela-")
                    validador_pagina = pagina.get_by_test_id("title-menu-toggle").get_by_text("Extracao order proposals")
                    validador_senha = pagina.get_by_role("heading", name="Insira a senha")
                    #pagina.pause()
                    try:
                        if pagina.locator("input[type='email']").count() > 0:
                            log_fn(f"[RELEX] Email encontrado após {i} tentativas.")
                            return "CAMPO_EMAIL"

                        if pagina.locator("input[type='password']").count() > 0:
                            log_fn(f"[RELEX] Senha encontrada após {i} tentativas.")
                            return "CAMPO_SENHA"

                        if validador_senha.count() > 0:
                            log_fn(f"[RELEX] Senha encontrada após {i} tentativas.")
                            return "CAMPO_SENHA2"

                        if validador_pagina.count() > 0:
                            log_fn(f"[RELEX] RELEX detectado após {i} tentativas.")
                            return "RELEX"

                    except Exception as e:
                        log_fn(f"[RELEX] Erro: {e}")

                    time.sleep(timeout)

                return None
            
            def aguardar_conclusao_job():
                icone_progresso = pagina.get_by_test_id("job-list-running-jobs").locator("circle")
                nome_job_em_progresso = pagina.get_by_test_id("job-list-running-jobs").get_by_text("Extracao order proposals")
                contador = 0
                while True:
                    if icone_progresso.count() > 0 and contador <= 150:
                        time.sleep(2)
                        contador += 1
                        continue
                    elif icone_progresso.count() == 0:
                        time.sleep(2)
                        return True
            
            def iniciar_extracao():
                log_fn("[RELEX] Iniciando extração de dados...")
                pagina.get_by_test_id("toolbar-menu-button").click()
                time.sleep(1)
                pagina.get_by_text("Export").click()
                time.sleep(1)
                pagina.get_by_text("HTML").click()
                time.sleep(5)

                log_fn("[RELEX] Extração em HTML iniciada.")

                time.sleep(2)

                pagina.get_by_test_id("application-header-button-notifications").click()
                
                time.sleep(10)

                aguardar_conclusao_job()
                
                pagina.get_by_text("• HTML").first.click()


            pagina.on("close", page_closed)
            context.on("close",lambda: log_fn("[RELEX] CONTEXT FECHADO"))
            navegador.on("disconnected",lambda: log_fn("[RELEX] BROWSER DESCONECTADO"))
            pagina.on("framenavigated",lambda frame: log_fn(f"[RELEX] NAVEGOU -> {frame.url}"))
            pagina.on("popup",lambda p: log_fn(f"[RELEX] POPUP: {p.url}"))
            context.on("page",lambda p: log_fn(f"[RELEX] NOVA PAGINA: {p.url}"))
            pagina.goto(link,wait_until="domcontentloaded",timeout=60000)

            log_fn("[RELEX] Página carregada.")

            # ----------- Inicio automação -----------

            time.sleep(3)
            email_preenchido = False
            senha_preenchida = False

            for i in range(60):
                log_fn(f"[RELEX] loop for {i} para identificar estado.")

                estado = detectar_estado_tela(pagina,log_fn=log_fn)

                campo_email = pagina.locator("input[type='email']")
                campo_senha = pagina.locator("input[type='password']")
                botao_avancar_email = pagina.get_by_role("button",name="Avançar")
                botao_entrar_senha = pagina.get_by_role("button",name="Entrar")

                #get_by_test_id("title-menu-toggle").get_by_text("Extracao order proposals")
                if estado == "CAMPO_EMAIL" and email_preenchido == False:
                    campo_email.click()
                    time.sleep(1)
                    campo_email.fill(usuario)
                    time.sleep(1)
                    botao_avancar_email.click()
                    time.sleep(5)
                    email_preenchido = True

                elif estado == "CAMPO_SENHA" and senha_preenchida == False:
                    campo_senha.click()
                    time.sleep(1)
                    campo_senha.fill(senha)
                    time.sleep(1)
                    botao_entrar_senha.click()
                    time.sleep(5)
                    senha_preenchida = True

                elif estado == "CAMPO_SENHA2" and senha_preenchida == False:
                    campo_senha.fill(senha)
                    time.sleep(1)
                    botao_entrar_senha.click()
                    time.sleep(5)
                    senha_preenchida = True

                elif estado == "RELEX":
                    time.sleep(2)
                    iniciar_extracao()
                    break
                
                else:
                    time.sleep(1)


            #
            # CONTINUAÇÃO DA AUTOMAÇÃO
            #
            # localizar botões
            # baixar arquivos
            # exportar planilhas
            # etc
            #

            return True

    except Exception as e:

        log_fn(
            f"[RELEX] Erro na automação: {e}"
        )

        return False
            
if __name__ == "__main__":
    usuario, senha, _, link_relex, caminho_salvar_relex, *_ = carregar_config()

    if not all([link_relex, usuario, senha, caminho_salvar_relex]):
        print("[RELEX] Configurações incompletas. Preencha os campos na MainWindow e tente novamente.")
    else:
        iniciar_automacao(
            link=link_relex,
            usuario=usuario,
            senha=senha,
            caminho_salvar=caminho_salvar_relex,
        )