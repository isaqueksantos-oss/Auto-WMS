import time
import cv2
import ctypes
from ctypes import wintypes
import numpy as np
import pyautogui
import pyperclip
import pygetwindow as gw
from interface.utils.multi_template_match import find_any_text
from interface.utils.config_manager import ElementRegistry

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

registry = ElementRegistry()

CONFIANCA_PADRAO = 0.7
EXIBIR_VISUALMENTE = False


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", wintypes.POINT),
    ]


def focus_manager(palavras_chave=None):
    """
    Decide automaticamente qual janela focar
    """

    janelas = gw.getAllWindows()

    # 1. Tenta pegar janela ativa
    ativa = gw.getActiveWindow()
    if ativa:
        titulo = ativa.title.lower()

        if palavras_chave:
            if any(p in titulo for p in palavras_chave):
                ativa.activate()
                return ativa
        else:
            ativa.activate()
            return ativa

    # 2. Busca por palavras no título
    if palavras_chave:
        for w in reversed(janelas):  # mais recentes primeiro
            titulo = w.title.lower()
            if any(p in titulo for p in palavras_chave):
                w.activate()
                return w

    # 3. Fallback: última janela visível
    for w in reversed(janelas):
        if w.title.strip():
            w.activate()
            return w

    return None


def maximize_manager(palavras_chave=None):
    """
    Localiza uma janela pelo titulo e a maximiza.
    """
    janelas = gw.getAllWindows()

    if palavras_chave:
        if isinstance(palavras_chave, str):
            palavras_chave = [palavras_chave]

        palavras_chave = [p.lower() for p in palavras_chave if p]

        for w in reversed(janelas):
            titulo = (w.title or "").lower()
            if any(p in titulo for p in palavras_chave):
                try:
                    w.activate()
                except Exception:
                    pass
                w.maximize()
                return w

        return None

    ativa = gw.getActiveWindow()
    if ativa:
        try:
            ativa.activate()
        except Exception:
            pass
        ativa.maximize()
        return ativa

    for w in reversed(janelas):
        if w.title.strip():
            try:
                w.activate()
            except Exception:
                pass
            w.maximize()
            return w

    return None

def clicar_coord(x, y, n, intervalo=0.01):
    """Executa multiplos cliques rapidos."""
    for _ in range(n):
        pyautogui.click(x, y)
        time.sleep(intervalo)

def ativar_edicao():
    pyautogui.press('f7')
    time.sleep(0.05)

def acao_limpar():
    pyautogui.hotkey('alt', 'a', 'l')
    time.sleep(0.05)
def campo_limpar():
    pyautogui.hotkey('alt', 'c', 'l')
    time.sleep(0.05)

def limpar_shift_f7():
    pyautogui.hotkey('shift', 'f7')
    time.sleep(0.05)

def salvar_alt_s():
    pyautogui.hotkey('alt', 's')
    time.sleep(0.1)


def aceitar_alt_o():
    pyautogui.hotkey('alt', 'o')
    time.sleep(0.05)

def executar_campo():
    pyautogui.press('f8')
    time.sleep(0.05)


def proximo_campo():
    pyautogui.press('tab')
    time.sleep(0.05)


def limpar_campo():
    pyautogui.hotkey('ctrl', 'u')
    time.sleep(0.05)

def limpar_shift_f5():
    pyautogui.hotkey('shift', 'f5')
    time.sleep(0.05)

def cancelar_consulta():
    pyautogui.hotkey('ctrl', 'q')
    time.sleep(0.05)

def inserir_registro():
    pyautogui.press('f6')
    time.sleep(0.05)

def remover_registro():
    pyautogui.hotkey('shift', 'f6')
    time.sleep(0.05)

def campo_anterior():
    pyautogui.hotkey('shift', 'tab')
    time.sleep(0.05)


def salvar_registro():
    pyautogui.press('f10')
    time.sleep(0.05)

def proximo_bloco():
    pyautogui.hotkey('ctrl', 'pgdn')
    time.sleep(0.05)


def copiar_para_clipboard(texto):
    for _ in range(3):
        pyperclip.copy(texto)
        if pyperclip.paste() == texto:
            return True
    return False


def colar_ctrl_v():
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.05)


def copiar_ctrl_c():
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(0.05)


def alt_f4():
    pyautogui.hotkey('alt', 'f4')
    time.sleep(0.1)


def inicio_do_campo():
    pyautogui.hotkey('ctrl', 'left')
    time.sleep(0.05)


def selecionar_texto_esq_dir():
    pyautogui.hotkey('ctrl', 'shiftright', 'shiftleft', 'right')
    time.sleep(0.05)


def digitar_transacao(transacao):
    acao_limpar()
    time.sleep(0.1)
    pyautogui.press('esc', presses=2, interval=0.05)
    time.sleep(0.2)
    limpar_shift_f7()
    time.sleep(0.3)
    
    """Digita a transacao e pressiona Enter."""
    print(f"{time.strftime('[%H:%M:%S]')} [INFO] Digitando transacao '{transacao}'...")
    pyautogui.write(transacao, interval=0.01)
    time.sleep(0.2)
    pyautogui.press('enter')
    print(f"{time.strftime('[%H:%M:%S]')} [OK] Transacao digitada e Enter pressionado.")
    return True


def aguardar_textos(
    transacao,
    opcoes_textos,
    timeout=None,
    log_fn=print,
    ordem_blocos=None,
    deslocamento_x=0.0,
    n_clicks=1,
    clicar=True,
    match_parcial=True,
    debug=EXIBIR_VISUALMENTE,
    grid_size=5,
    tolerancia01=4,
    tolerancia02=10,
    modo=None,
    ignorar_textos=None,
    roi_attempts=1,
    roi_delay=0.0,
    roi_retry_between_blocks=False,
    overlap_pct=0.2,
    stop_checker=None,
):
    start = time.time()
    log_fn(f"[INFO] Iniciando busca por textos da transacao '{transacao}'")

    if ordem_blocos in ("tela_toda", "full_screen", "all") or ordem_blocos == ["tela_toda"]:
        ordem_blocos = list(range(1, grid_size**2 + 1))
    elif not ordem_blocos:
        ordem_blocos = list(range(1, grid_size**2 + 1))

    def gerar_blocos(screen):
        h, w = screen.shape[:2]
        step_x, step_y = w // grid_size, h // grid_size
        overlap_x = int(step_x * overlap_pct) if overlap_pct and grid_size > 1 else 0
        overlap_y = int(step_y * overlap_pct) if overlap_pct and grid_size > 1 else 0

        for bloco_id in ordem_blocos:
            bx = (bloco_id - 1) % grid_size
            by = (bloco_id - 1) // grid_size
            x1 = bx * step_x
            y1 = by * step_y
            x2 = min((bx + 1) * step_x, w)
            y2 = min((by + 1) * step_y, h)

            if overlap_x or overlap_y:
                x1 = max(0, x1 - overlap_x)
                y1 = max(0, y1 - overlap_y)
                x2 = min(w, x2 + overlap_x)
                y2 = min(h, y2 + overlap_y)

            if x1 < w and y1 < h:
                yield bloco_id, x1, y1, x2, y2

    def buscar_em_roi(screen, nome_texto, lista_textos, roi_base, idx_tentativa=1):
        h, w = screen.shape[:2]
        x1_base, y1_base, x2_base, y2_base = roi_base
        expansoes = [
            (tolerancia01, tolerancia02),
            (max(tolerancia01 * 2, 8), max(tolerancia02 * 2, 16)),
        ]

        for idx_expansao, (expand_x, expand_y) in enumerate(expansoes, 1):
            x1 = max(0, x1_base - expand_x)
            y1 = max(0, y1_base - expand_y)
            x2 = min(w, x2_base + expand_x)
            y2 = min(h, y2_base + expand_y)

            recorte = screen[y1:y2, x1:x2]
            if recorte.size == 0:
                continue

            roi_start = time.time()
            resultado = find_any_text(
                recorte,
                lista_textos,
                grid_divisions=1,
                conf_min=0.7,
                match_parcial=match_parcial,
                debug=debug,
                modo=modo,
                ignore_texts=ignorar_textos,
                bloco_log="ROI",
            )
            roi_elapsed = time.time() - roi_start

            if not resultado:
                log_fn(
                    f"[SCAN ROI] transacao='{transacao}' grupo='{nome_texto}' "
                    f"tentativa={idx_tentativa}.{idx_expansao} area=({x1},{y1},{x2},{y2}) "
                    f"tempo={roi_elapsed:.2f}s resultado=miss"
                )
                continue

            detected, alvo, bloco_roi, (rx1, ry1, rx2, ry2), (cx, cy) = resultado
            bbox_global = (x1 + rx1, y1 + ry1, x1 + rx2, y1 + ry2)
            cx_g = x1 + cx
            cy_g = y1 + cy

            # Recalibra a ROI mesmo quando o hit veio do cache existente.
            registry.atualizar_elemento(transacao, nome_texto, bbox_global)
            total_elapsed = time.time() - start
            log_fn(
                f"[SCAN ROI] transacao='{transacao}' grupo='{nome_texto}' alvo='{alvo}' "
                f"tentativa={idx_tentativa}.{idx_expansao} area=({x1},{y1},{x2},{y2}) "
                f"tempo={roi_elapsed:.2f}s resultado=hit total={total_elapsed:.2f}s"
            )
            log_fn(f"[HIT ROI] grupo='{nome_texto}' alvo='{alvo}' texto='{detected}' roi_bloco={bloco_roi}")

            if clicar:
                largura = rx2 - rx1
                px = int(cx_g + deslocamento_x * largura)
                py = cy_g
                for _ in range(n_clicks):
                    pyautogui.click(px, py)

            return detected, alvo, (cx_g, cy_g)

        return None

    while time.time() - start < timeout:
        if callable(stop_checker) and stop_checker():
            log_fn("[ABORT] Busca por textos interrompida por solicitação de parada.")
            return None

        screenshot = pyautogui.screenshot()
        screen = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        # 1) Primeiro: buscar todas as opcoes nas ROIs
        for idx_tentativa in range(1, max(1, roi_attempts) + 1):
            for nome_texto, lista_textos in opcoes_textos.items():
                if callable(stop_checker) and stop_checker():
                    log_fn("[ABORT] Busca por textos interrompida por solicitação de parada.")
                    return None
                roi = registry.obter_roi_elemento(transacao, nome_texto)
                if roi:
                    resultado = buscar_em_roi(screen, nome_texto, lista_textos, roi, idx_tentativa=idx_tentativa)
                    if resultado:
                        return resultado
            if roi_delay > 0 and idx_tentativa < max(1, roi_attempts):
                time.sleep(roi_delay)

        # 2) So depois: buscar todas as opcoes nos blocos
        blocos = list(gerar_blocos(screen))
        for idx_bloco, (bloco_id, x1b, y1b, x2b, y2b) in enumerate(blocos):
            if callable(stop_checker) and stop_checker():
                log_fn("[ABORT] Busca por textos interrompida por solicitação de parada.")
                return None
            recorte = screen[y1b:y2b, x1b:x2b]
            if recorte.size == 0:
                continue

            for nome_texto, lista_textos in opcoes_textos.items():
                if callable(stop_checker) and stop_checker():
                    log_fn("[ABORT] Busca por textos interrompida por solicitação de parada.")
                    return None
                bloco_start = time.time()
                resultado = find_any_text(
                    recorte,
                    lista_textos,
                    grid_divisions=1,
                    match_parcial=match_parcial,
                    debug=debug,
                    modo=modo,
                    ignore_texts=ignorar_textos,
                    bloco_log=bloco_id,
                )
                bloco_elapsed = time.time() - bloco_start
                if resultado:
                    detected_text, target, bloco_roi, (rx1, ry1, rx2, ry2), (cx, cy) = resultado

                    cx_g = x1b + cx
                    cy_g = y1b + cy
                    bbox_global = (x1b + rx1, y1b + ry1, x1b + rx2, y1b + ry2)

                    registry.atualizar_elemento(transacao, nome_texto, bbox_global)
                    total_elapsed = time.time() - start
                    log_fn(
                        f"[SCAN BLOCO] transacao='{transacao}' bloco_tela={bloco_id} "
                        f"grupo='{nome_texto}' alvo='{target}' area=({x1b},{y1b},{x2b},{y2b}) "
                        f"tempo={bloco_elapsed:.2f}s resultado=hit total={total_elapsed:.2f}s"
                    )
                    log_fn(
                        f"[HIT BLOCO TELA {bloco_id}] grupo='{nome_texto}' alvo='{target}' "
                        f"texto='{detected_text}' bloco_roi={bloco_roi}"
                    )

                    if clicar:
                        largura = rx2 - rx1
                        px = int(cx_g + deslocamento_x * largura)
                        py = cy_g
                        for _ in range(n_clicks):
                            pyautogui.click(px, py)

                    return nome_texto, target, (cx_g, cy_g)
                else:
                    log_fn(
                        f"[SCAN BLOCO] transacao='{transacao}' bloco_tela={bloco_id} "
                        f"grupo='{nome_texto}' area=({x1b},{y1b},{x2b},{y2b}) "
                        f"tempo={bloco_elapsed:.2f}s resultado=miss"
                    )

            if roi_retry_between_blocks and idx_bloco < len(blocos) - 1:
                if roi_delay > 0:
                    time.sleep(roi_delay)
                for nome_texto, lista_textos in opcoes_textos.items():
                    roi = registry.obter_roi_elemento(transacao, nome_texto)
                    if not roi:
                        continue
                    resultado = buscar_em_roi(screen, nome_texto, lista_textos, roi, idx_tentativa=1)
                    if resultado:
                        return resultado

        time.sleep(0.1)

    total_elapsed = time.time() - start
    log_fn(f"[SCAN TOTAL] transacao='{transacao}' tempo_total={total_elapsed:.2f}s resultado=timeout")
    log_fn("[TIMEOUT] Nenhum texto encontrado.")
    return None
