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
    inicio: datetime | None = None,
    **campos,
) -> datetime | None:
    agora = datetime.now()
    inicio_execucao = inicio

    if evento == "inicio" and inicio_execucao is None:
        inicio_execucao = agora

    try:
        caminho_log = obter_caminho_log_execucao(nome_automacao)
        timestamp = agora.strftime("%Y-%m-%d %H:%M:%S")
        partes = [
            f"[{timestamp}]",
            f"evento={evento}",
            f"status={status or '-'}",
        ]

        if evento == "inicio":
            partes.append(f"inicio={inicio_execucao:%Y-%m-%d %H:%M:%S}")
        elif evento == "fim" and inicio_execucao is not None:
            duracao = agora - inicio_execucao
            total_segundos = int(duracao.total_seconds())
            horas, segundos_restantes = divmod(total_segundos, 3600)
            minutos, segundos = divmod(segundos_restantes, 60)
            partes.extend(
                (
                    f"inicio={inicio_execucao:%Y-%m-%d %H:%M:%S}",
                    f"fim={agora:%Y-%m-%d %H:%M:%S}",
                    f"duracao=[{horas:02d}:{minutos:02d}:{segundos:02d}]",
                )
            )
            linhas_processadas = campos.get("linhas_processadas")
            if isinstance(linhas_processadas, (int, float)) and linhas_processadas > 0:
                media_segundos = duracao.total_seconds() / linhas_processadas
                tempo_medio = f"{media_segundos:.2f}s"
            else:
                tempo_medio = "-"
            partes.append(f"tempo_medio_por_registro={tempo_medio}")

        for chave, valor in campos.items():
            partes.append(f"{chave}={valor if valor not in (None, '') else '-'}")

        if detalhe:
            partes.append(f"detalhe={detalhe}")

        with open(caminho_log, "a", encoding="utf-8") as arquivo_log:
            arquivo_log.write(" ".join(partes) + "\n\n")
            arquivo_log.flush()
            os.fsync(arquivo_log.fileno())
    except Exception:
        pass
    return inicio_execucao
