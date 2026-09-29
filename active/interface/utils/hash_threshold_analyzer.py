from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import imagehash
from PIL import Image


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class ImageEntry:
    path: Path
    hash_value: imagehash.ImageHash


@dataclass(frozen=True)
class PairDistance:
    left: ImageEntry
    right: ImageEntry
    distance: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analisa perceptual hash (pHash) entre imagens de uma pasta para "
            "ajudar a definir um limiar de mudanca visual."
        )
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default="hash_samples",
        help="Pasta com as imagens a analisar. Padrao: hash_samples",
    )
    parser.add_argument(
        "--hash-size",
        type=int,
        default=8,
        help="Tamanho do pHash. Padrao: 8",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Quantidade de pares para exibir nos rankings. Padrao: 10",
    )
    return parser.parse_args()


def iter_image_paths(folder: Path) -> Iterable[Path]:
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS:
            yield path


def load_image_hash(path: Path, hash_size: int) -> imagehash.ImageHash:
    with Image.open(path) as img:
        gray = img.convert("L")
        return imagehash.phash(gray, hash_size=hash_size)


def load_entries(folder: Path, hash_size: int) -> list[ImageEntry]:
    entries: list[ImageEntry] = []
    for path in iter_image_paths(folder):
        entries.append(ImageEntry(path=path, hash_value=load_image_hash(path, hash_size)))
    return entries


def build_pair_distances(entries: list[ImageEntry]) -> list[PairDistance]:
    distances: list[PairDistance] = []
    for idx, left in enumerate(entries):
        for right in entries[idx + 1 :]:
            distances.append(
                PairDistance(
                    left=left,
                    right=right,
                    distance=abs(left.hash_value - right.hash_value),
                )
            )
    return sorted(distances, key=lambda item: item.distance)


def suggest_threshold(pairs: list[PairDistance]) -> int | None:
    if not pairs:
        return None

    if len(pairs) == 1:
        return pairs[0].distance

    gaps: list[tuple[int, int]] = []
    for idx in range(len(pairs) - 1):
        current = pairs[idx].distance
        nxt = pairs[idx + 1].distance
        gaps.append((nxt - current, idx))

    biggest_gap, gap_idx = max(gaps, key=lambda item: item[0])
    if biggest_gap <= 0:
        return pairs[len(pairs) // 2].distance

    low = pairs[gap_idx].distance
    high = pairs[gap_idx + 1].distance
    return (low + high) // 2


def print_entries(entries: list[ImageEntry]) -> None:
    print("\nHashes das imagens")
    print("-" * 80)
    for entry in entries:
        print(f"{entry.path.name:<35} hash={entry.hash_value}")


def print_pairs(title: str, pairs: list[PairDistance], limit: int) -> None:
    print(f"\n{title}")
    print("-" * 80)
    if not pairs:
        print("Nenhum par disponivel.")
        return

    for pair in pairs[:limit]:
        print(
            f"dist={pair.distance:>3} | "
            f"{pair.left.path.name:<30} <-> {pair.right.path.name}"
        )


def print_summary(pairs: list[PairDistance]) -> None:
    print("\nResumo")
    print("-" * 80)
    if not pairs:
        print("Sem pares suficientes para resumir.")
        return

    values = [pair.distance for pair in pairs]
    avg = sum(values) / len(values)
    median = values[len(values) // 2]
    print(f"Menor distancia : {values[0]}")
    print(f"Maior distancia : {values[-1]}")
    print(f"Media           : {avg:.2f}")
    print(f"Mediana         : {median}")

    suggested = suggest_threshold(pairs)
    if suggested is not None:
        print(f"Limiar sugerido : {suggested}")
        print(
            "Leitura pratica : pares abaixo desse valor tendem a ser mudancas menores; "
            "pares acima tendem a ser mudancas mais fortes."
        )


def main() -> int:
    args = parse_args()
    folder = Path(args.folder).expanduser().resolve()

    if not folder.exists():
        print(f"Pasta nao encontrada: {folder}")
        return 1

    if not folder.is_dir():
        print(f"O caminho informado nao e uma pasta: {folder}")
        return 1

    entries = load_entries(folder, args.hash_size)
    if len(entries) < 2:
        print("Adicione pelo menos 2 imagens na pasta para comparar os hashes.")
        return 1

    pairs = build_pair_distances(entries)

    print(f"Pasta analisada : {folder}")
    print(f"Imagens lidas   : {len(entries)}")
    print(f"Pares gerados   : {len(pairs)}")
    print(f"Hash size       : {args.hash_size}")

    print_entries(entries)
    print_pairs("Pares mais parecidos", pairs, args.top)
    print_pairs("Pares mais diferentes", list(reversed(pairs)), args.top)
    print_summary(pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
