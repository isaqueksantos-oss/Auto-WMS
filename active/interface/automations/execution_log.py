import os
import re
from datetime import datetime
from pathlib import Path


def _slugify_nome(nome: str) -> str:
    nome_limpo = re.sub(r"[^a-zA-Z0-9]+", "_", str(nome or "").strip().lower())
    return nome_limpo.strip("_") or "automacao"


def obter_caminho_log_execucao(nome_automacao: str) -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    pasta_logs = base_dir / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)
    return pasta_logs / f"{_slugify_nome(nome_automacao)}_execucao.txt"


def registrar_evento_execucao(
    nome_automacao: str,
    evento: str,
    *,
    status: str = "",
    detalhe: str = "",
    **campos,
) -> None:
    try:
        caminho_log = obter_caminho_log_execucao(nome_automacao)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        partes = [
            f"[{timestamp}]",
            f"evento={evento}",
            f"status={status or '-'}",
        ]

        for chave, valor in campos.items():
            partes.append(f"{chave}={valor if valor not in (None, '') else '-'}")

        if detalhe:
            partes.append(f"detalhe={detalhe}")

        with open(caminho_log, "a", encoding="utf-8") as arquivo_log:
            arquivo_log.write(" ".join(partes) + "\n")
            arquivo_log.flush()
            os.fsync(arquivo_log.fileno())
    except Exception:
        pass
