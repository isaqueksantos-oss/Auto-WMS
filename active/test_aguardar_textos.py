import argparse
import os
import sys
import time
from difflib import SequenceMatcher

import cv2
import numpy as np

try:
    from PIL import Image
except ImportError:
    Image = None

from interface.utils.multi_template_match import (
    _extract_words,
    _normalize_text,
    ocr_cached_global,
    find_any_text,
)
from interface.utils.screen import normalize_ocr


def parse_blocks(blocks_str):
    if not blocks_str:
        return list(range(1, 26))
    blocks = set()
    for part in blocks_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            blocks.update(range(int(start), int(end) + 1))
        else:
            blocks.add(int(part))
    return sorted(b for b in blocks if 1 <= b <= 25)


def compare_texts(detected_text, target_text, match_parcial=False):
    detected_clean = _normalize_text(detected_text)
    target_clean = _normalize_text(target_text)

    if not target_clean or not detected_clean:
        return False, 0.0, 0

    detected_words = _extract_words(detected_clean)
    target_words = _extract_words(target_clean)
    detected_word_set = set(detected_words)
    matched_words = sum(1 for word in target_words if word in detected_word_set)
    similarity = SequenceMatcher(None, detected_clean, target_clean).ratio()

    if len(target_words) <= 1:
        is_match = (
            (match_parcial and target_clean in detected_clean)
            or similarity >= 0.85
            or detected_clean.startswith(target_clean[:5])
        )
    elif len(target_words) == 2:
        is_match = matched_words >= 2 and (
            (match_parcial and target_clean in detected_clean)
            or similarity >= 0.85
            or detected_clean.startswith(target_clean[:5])
        )
    else:
        is_match = matched_words >= 2

    return is_match, similarity, matched_words


def build_blocks(image_shape, grid_size=5, overlap_ratio=0.35):
    h, w = image_shape[:2]
    bloco_h = h // grid_size
    bloco_w = w // grid_size
    blocks = []
    bloco_id = 1
    for i in range(grid_size):
        for j in range(grid_size):
            y1 = max(0, int(i * bloco_h - bloco_h * overlap_ratio / 2))
            y2 = min(h, int((i + 1) * bloco_h + bloco_h * overlap_ratio / 2))
            x1 = max(0, int(j * bloco_w - bloco_w * overlap_ratio / 2))
            x2 = min(w, int((j + 1) * bloco_w + bloco_w * overlap_ratio / 2))
            blocks.append((bloco_id, x1, y1, x2, y2))
            bloco_id += 1
    return blocks


def draw_grid(image, blocks):
    annotated = image.copy()
    for bloco_id, x1, y1, x2, y2 in blocks:
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 255, 0), 1)
        label = str(bloco_id)
        cv2.putText(
            annotated,
            label,
            (x1 + 4, y1 + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )
    return annotated


def get_adjacent_blocks(selected_blocks, grid_size=5):
    expanded = set(selected_blocks)
    for bloco_id in selected_blocks:
        row = (bloco_id - 1) // grid_size
        col = (bloco_id - 1) % grid_size
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr = row + dr
                nc = col + dc
                if 0 <= nr < grid_size and 0 <= nc < grid_size:
                    expanded.add(nr * grid_size + nc + 1)
    return sorted(expanded)


def process_image(image_path, terms, selected_blocks, match_parcial=False, display=True, save_output=True):
    image = cv2.imread(image_path)
    if image is None:
        print(f"[ERROR] Não foi possível abrir a imagem: {image_path}")
        return

    h, w = image.shape[:2]
    print(f"\n[IMAGE] {os.path.basename(image_path)} | size={w}x{h}")
    print(f"[TERMS] {terms}")
    print(f"[BLOCKS] selecionados={selected_blocks}")

    blocks = build_blocks(image.shape, grid_size=5)
    annotated = draw_grid(image, blocks)

    any_match = False
    for bloco_id, x1, y1, x2, y2 in blocks:
        if bloco_id not in selected_blocks:
            continue

        roi = image[y1:y2, x1:x2]
        roi_norm = normalize_ocr(roi, modo='auto', debug=True)
        ocr_result = ocr_cached_global(image, roi_norm)

        roi_path = os.path.join(os.path.dirname(image_path), f"{os.path.splitext(os.path.basename(image_path))[0]}_block{bloco_id}_roi.png")
        cv2.imwrite(roi_path, roi)
        print(f"[DEBUG] ROI salvo em: {roi_path}")

        print(f"\n[BLOCK] {bloco_id} area=({x1},{y1},{x2},{y2}) textos_detectados={len(ocr_result)}")

        if not ocr_result:
            continue

        for idx, (bbox, text, conf) in enumerate(ocr_result, 1):
            text_clean = text.replace('\n', ' ').strip()
            xs = [int(pt[0]) for pt in bbox]
            ys = [int(pt[1]) for pt in bbox]
            bx1 = min(xs) + x1
            by1 = min(ys) + y1
            bx2 = max(xs) + x1
            by2 = max(ys) + y1

            print(
                f"   [{idx:02d}] '{text_clean}' conf={conf:.2f} bbox=({bx1},{by1},{bx2},{by2})"
            )
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 0, 255), 1)
            cv2.putText(
                annotated,
                f"{idx}: {text_clean}",
                (bx1, max(by1 - 4, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )

            for term in terms:
                is_match, similarity, matched_words = compare_texts(
                    text_clean, term, match_parcial=match_parcial
                )
                status = "MATCH" if is_match else "NO MATCH"
                print(
                    f"       >> Procurado: '{term}' | sim={similarity:.2f} | "
                    f"palavras={matched_words}/{len(_extract_words(_normalize_text(term)))} | {status}"
                )

                if is_match:
                    any_match = True
                    cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                    cv2.putText(
                        annotated,
                        f"MATCH: {term}",
                        (bx1, min(by1 - 20, by1)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (0, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )

    output_name = os.path.splitext(os.path.basename(image_path))[0] + "_ocr_debug.png"
    output_path = os.path.join(os.path.dirname(image_path), output_name)
    if save_output:
        cv2.imwrite(output_path, annotated)
        print(f"[OUTPUT] Imagem anotada salva em: {output_path}")

    if not any_match and selected_blocks:
        print("[DEBUG] Nenhum texto compatível encontrado nos blocos selecionados. Tentando verificação direta com find_any_text...")
        resultado = find_any_text(
            image,
            {"termos": terms},
            grid_divisions=5,
            ordem_blocos=selected_blocks,
            conf_min=0.7,
            match_parcial=match_parcial,
            debug=True,
            modo='auto',
        )
        if not resultado:
            expanded_blocks = get_adjacent_blocks(selected_blocks)
            if expanded_blocks != selected_blocks:
                print(f"[DEBUG] Expandindo busca para blocos adjacentes: {expanded_blocks}")
                resultado = find_any_text(
                    image,
                    {"termos": terms},
                    grid_divisions=5,
                    ordem_blocos=expanded_blocks,
                    conf_min=0.7,
                    match_parcial=match_parcial,
                    debug=True,
                    modo='auto',
                )
        if resultado:
            text_detected, target, bloco_id, bbox, center = resultado
            print(f"[DEBUG MATCH] detectado='{text_detected}' alvo='{target}' bloco={bloco_id} bbox={bbox}")
            bx1, by1, bx2, by2 = bbox
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                f"MATCH_DIRECT: {target}",
                (bx1, max(by1 - 18, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
            any_match = True
            if save_output:
                cv2.imwrite(output_path, annotated)

    if display:
        window_name = f"OCR Test - {os.path.basename(image_path)}"
        try:
            cv2.imshow(window_name, annotated)
            print("Pressione qualquer tecla na janela para continuar...")
            cv2.waitKey(0)
            cv2.destroyWindow(window_name)
        except cv2.error as exc:
            print(f"[WARN] cv2.imshow indisponível: {exc}")
            if Image is not None:
                pil_image = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
                pil_image.show()
                print("[INFO] Abrindo imagem com PIL Image.show() como fallback.")
            else:
                print("[WARN] PIL não está instalado. Apenas a imagem anotada foi salva.")

    if not any_match:
        print("[RESULT] Nenhum match encontrado para os termos fornecidos.")
    else:
        print("[RESULT] Pelo menos um match encontrado.")


def main():
    parser = argparse.ArgumentParser(
        description="Teste de OCR e validação de termos em imagem, usando a lógica de aguardar_textos."
    )
    parser.add_argument("--images", required=True, help="Pasta com as imagens a testar.")
    parser.add_argument(
        "--terms",
        nargs='+',
        required=True,
        help="Termos ou frases a procurar. Use aspas para frases compostas.",
    )
    parser.add_argument(
        "--blocks",
        default=None,
        help="Blocos 1-25 separados por vírgula ou intervalos (ex: 1,2,5-10)."
    )
    parser.add_argument(
        "--no-display",
        action='store_true',
        help="Não exibir a imagem anotada na tela.",
    )
    parser.add_argument(
        "--partial",
        action='store_true',
        help="Permite correspondência parcial dos termos.",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.images):
        print(f"[ERROR] A pasta de imagens não existe: {args.images}")
        sys.exit(1)

    selected_blocks = parse_blocks(args.blocks)
    image_files = [
        os.path.join(args.images, name)
        for name in sorted(os.listdir(args.images))
        if name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'))
    ]

    if not image_files:
        print(f"[ERROR] Nenhuma imagem encontrada em: {args.images}")
        sys.exit(1)

    for image_path in image_files:
        process_image(
            image_path,
            args.terms,
            selected_blocks,
            match_parcial=args.partial,
            display=not args.no_display,
            save_output=True,
        )

    print("\n[FIM] Teste concluído.")


if __name__ == '__main__':
    main()
