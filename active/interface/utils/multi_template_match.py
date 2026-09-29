import os
import time
import hashlib
import numpy as np
import re
import unicodedata
from difflib import SequenceMatcher
import cv2
import easyocr
from .screen import normalize_ocr


_reader = easyocr.Reader(
    ['pt', 'en'],
    gpu=False,
    quantize=True,
    detector=True,
    model_storage_directory='.EasyOCR\\model',
    download_enabled=False,
)

# Cache global
_last_frame_hash = None
_last_ocr_cache = {}  # armazena resultados por ROI hash


def ocr_cached_global(img, roi_img):
    """Executa OCR com cache duplo: global (frame) + ROI."""
    global _last_frame_hash, _last_ocr_cache

    frame_hash = hashlib.md5(img.tobytes()).hexdigest()

    if frame_hash != _last_frame_hash:
        _last_frame_hash = frame_hash
        _last_ocr_cache = {}

    roi_hash = hashlib.md5(roi_img.tobytes()).hexdigest()

    if roi_hash in _last_ocr_cache:
        return _last_ocr_cache[roi_hash]

    result = _reader.readtext(roi_img)
    _last_ocr_cache[roi_hash] = result
    return result


def _normalize_text(text):
    normalized = unicodedata.normalize('NFD', str(text).lower().strip())
    without_accents = ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9 ]', '', without_accents)


def _extract_words(text):
    return [word for word in re.split(r'[\s.:;]+', text) if word]


def find_any_text(screen, texts_lists, grid_divisions=5, ordem_blocos=None, conf_min=0.7, match_parcial=None, debug=True, modo=None, ignore_texts=None, bloco_log=None):

    if isinstance(texts_lists, dict):
        texts_lists = list(texts_lists.values())
    elif not isinstance(texts_lists, (list, tuple)):
        raise TypeError("texts_lists deve ser um dict ou lista de listas de textos")

    normalized_lists = []
    for item in texts_lists:
        textos = item if isinstance(item, (list, tuple)) else [item]
        normalized_lists.append([
            (str(target).strip(), _normalize_text(target))
            for target in textos
        ])

    ignored_texts_clean = []
    if ignore_texts:
        ignored_texts_clean = [_normalize_text(ign) for ign in ignore_texts if str(ign).strip()]

    h, w = screen.shape[:2]
    if grid_divisions <= 1:
        blocos = {1: (0, 0, w, h)}
    else:
        bloco_h = h // grid_divisions
        bloco_w = w // grid_divisions
        overlap_ratio = 0.35
        blocos = {}
        bloco_id = 1
        for i in range(grid_divisions):
            for j in range(grid_divisions):
                y1 = max(0, int(i * bloco_h - bloco_h * overlap_ratio / 2))
                y2 = min(h, int((i + 1) * bloco_h + bloco_h * overlap_ratio / 2))
                x1 = max(0, int(j * bloco_w - bloco_w * overlap_ratio / 2))
                x2 = min(w, int((j + 1) * bloco_w + bloco_w * overlap_ratio / 2))
                blocos[bloco_id] = (x1, y1, x2, y2)
                bloco_id += 1

    if ordem_blocos is None:
        ordem_blocos = list(blocos.keys())

    if debug:
        os.makedirs("debug_ocr", exist_ok=True)

    for bloco_id in ordem_blocos:
        x1, y1, x2, y2 = blocos[bloco_id]
        roi = screen[y1:y2, x1:x2]

        roi_norm = normalize_ocr(roi, modo=modo, debug=debug)
        ocr_result = ocr_cached_global(screen, roi_norm)

        if debug:
            print(f'{time.strftime("[%H:%M:%S]")} [DEBUG OCR] Bloco {bloco_id}: {len(ocr_result)} textos detectados.')
            for i, (_, text, conf) in enumerate(ocr_result, 1):
                clean_text = text.replace("\n", " ").strip()
                print(f"   {i:02d}. '{clean_text}' ({conf:.2f})")

            debug_img = roi_norm.copy()
            if len(debug_img.shape) == 2:
                debug_img = cv2.cvtColor(debug_img, cv2.COLOR_GRAY2BGR)
            for bbox, text, conf in ocr_result:
                pts = np.array(bbox, np.int32).reshape((-1, 1, 2))
                cv2.polylines(debug_img, [pts], True, (0, 255, 0), 1)
                cv2.putText(
                    debug_img,
                    f"{text} ({conf:.2f})",
                    (pts[0][0][0], pts[0][0][1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 255, 255),
                    1,
                )
            cv2.imwrite(f'debug_ocr/{int(time.time())}_bloco{bloco_id}.png', debug_img)

        for bbox, detected_text, conf in ocr_result:
            if conf < conf_min and len(detected_text.strip()) < 3:
                continue

            detected_text_clean = _normalize_text(detected_text)
            if not detected_text_clean:
                continue

            ignored = False
            for ign_clean in ignored_texts_clean:
                if SequenceMatcher(None, detected_text_clean, ign_clean).ratio() > 0.85:
                    ignored = True
                    if debug:
                        print("[IGNORADO]", detected_text_clean)
                    break

            if ignored:
                continue

            for texts in normalized_lists:
                for target, target_clean in texts:
                    if not target_clean:
                        continue

                    if not (match_parcial and target_clean in detected_text_clean):
                        if abs(len(detected_text_clean) - len(target_clean)) > max(10, len(target_clean)):
                            continue

                    detected_words = _extract_words(detected_text_clean)
                    target_words = _extract_words(target_clean)
                    detected_word_set = set(detected_words)
                    matched_words = sum(1 for word in target_words if word in detected_word_set)

                    similarity = SequenceMatcher(None, detected_text_clean, target_clean).ratio()
                    basic_match = (
                        (match_parcial and target_clean in detected_text_clean)
                        or (not match_parcial and similarity >= 0.85)
                        or detected_text_clean.startswith(target_clean[:5])
                    )

                    if len(target_words) <= 1:
                        is_match = basic_match
                    elif len(target_words) == 2:
                        is_match = matched_words >= 2 and basic_match
                    else:
                        is_match = matched_words >= 2

                    if match_parcial and target_clean in detected_text_clean:
                        match_method = "substring"
                    elif similarity >= 0.85:
                        match_method = "fuzzy"
                    elif detected_text_clean.startswith(target_clean[:5]):
                        match_method = "prefix"
                    else:
                        match_method = "none"

                    bloco_compare = bloco_log if bloco_log is not None else bloco_id
                    print(
                        f"{time.strftime('[%H:%M:%S]')} [COMPARE] bloco={bloco_compare} | "
                        f"Encontrado: {detected_text} / {detected_text_clean} | "
                        f"Procurado: {target} / {target_clean} | "
                        f"palavras={matched_words}/{len(target_words)} sim={similarity:.2f} | "
                        f"metodo={match_method} | "
                        f"[{'MATCH' if is_match else 'NO MATCH'}]"
                    )

                    if is_match:
                        xs = [p[0] for p in bbox]
                        ys = [p[1] for p in bbox]
                        x1_orig = int(min(xs) + x1)
                        y1_orig = int(min(ys) + y1)
                        x2_orig = int(max(xs) + x1)
                        y2_orig = int(max(ys) + y1)
                        center_x = (x1_orig + x2_orig) // 2
                        center_y = (y1_orig + y2_orig) // 2
                        if debug:
                            print(f"{time.strftime('[%H:%M:%S]')} [MATCH {match_method}] '{detected_text}' reconhecido como '{target}' (sim={similarity:.2f})")
                        return detected_text, target, bloco_id, (x1_orig, y1_orig, x2_orig, y2_orig), (center_x, center_y)

    if debug:
        print(f'{time.strftime("[%H:%M:%S]")} [DEBUG OCR] Nenhum texto compativel encontrado.')
    return None
