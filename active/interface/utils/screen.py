import os
import time
import cv2
import numpy as np


def normalize_ocr(img, modo='auto', debug=False):

    if modo == "desativado":
        return img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    mean = np.mean(gray)
    contraste = np.std(gray)

    # --- Heuristica mais inteligente --- #
    if modo == 'auto':
        if mean > 160 and contraste < 35:
            modo = 'texto'      # fundo muito claro, texto escuro
        elif mean < 100 and contraste > 30:
            modo = 'botao'      # fundo escuro ou cinza
        else:
            modo = 'neutro'     # casos intermediarios

    if modo == 'texto':
        norm = cv2.bilateralFilter(gray, 9, 75, 75)
        norm = cv2.equalizeHist(norm)
    elif modo == 'botao':
        norm = cv2.GaussianBlur(gray, (3, 3), 0)
        _, norm = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif modo == 'neutro':
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        norm = clahe.apply(gray)
    else:
        norm = gray

    if debug:
        os.makedirs("debug_ocr", exist_ok=True)
        cv2.imwrite(f"debug_ocr/{int(time.time())}_{modo}.png", norm)

    return norm
