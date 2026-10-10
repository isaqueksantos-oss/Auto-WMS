"""
WMMA0031 - DESCATIVAR local

Entrada (2 colunas): item | id_local

Fluxo por linha:
    pesquisa o item (bloco de cima)
        -> Ctrl+PgDn  (cai em Planta)
        -> TAB        (vai para Local)
        -> F7         (modo consulta)
        -> TAB        (vai para Local no modo consulta)
        -> digita o id_local
        -> F8         (executa a consulta)
            encontrou -> Shift+F6 (remove) -> F10 (salva)
            não achou -> Shift+F4 (limpa)  -> F8 (volta ao normal)
"""

import time

from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import (
    ativar_edicao,
    executar_campo,
    proximo_bloco,
    remover_registro,
    salvar_registro,
)
from interface.automations import wmma0031_base as base

# Reexporta para a interface (main_window chama estas funções).
from interface.automations.wmma0031_base import (  # noqa: F401
    request_stop,
    clear_stop,
    verificar_tamanho_lista,
)


CAMPOS = ("item", "id_local")

status_callback = None


def _processar_linha(i, valores, status_cb):
    item, id_local = valores

    base.log(f"[DESCATIVAR] Linha {i}: item {item} | local {id_local}")

    if base.stop_requested:
        raise base.AbortarExecucao("parada_solicitada")

    try:
        if callable(status_cb):
            status_cb(i, "Em progresso", item)
    except Exception as erro:
        base.log(f"[WARN] Falha ao atualizar status da linha {i}: {erro}")

    if base.detectar_erro_wms_caido(timeout=0.5):
        raise base.WMSCaiuError()

    base.garantir_foco_wms()

    if not base.aguardar_tela_transacao(timeout=60):
        if base.detectar_erro_wms_caido(timeout=1.0):
            raise base.WMSCaiuError()

        base.log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Tela {base.TRANSACAO} não encontrada. Abortando..."
        )

        if callable(status_cb):
            try:
                status_cb(i, "Transacao_nao_encontrada", item)
            except Exception:
                pass

        raise base.AbortarExecucao(
            "Transacao_nao_encontrada",
            {
                "linha": i,
                "item": item,
                "id_local": id_local,
                "status": "Transacao_nao_encontrada",
            },
        )

    # --- Pesquisa o item --- #
    if not base.pesquisar_item(item):
        if callable(status_cb):
            try:
                status_cb(i, "Item_nao_encontrado", item)
            except Exception:
                pass

        return {
            "linha": i,
            "item": item,
            "id_local": id_local,
            "status": "Item_nao_encontrado",
        }

    # --- Bloco de locais: consulta pelo local --- #
    base.descer_para_bloco_locais()

    # F7 -> modo consulta.
    base.atalho_wms(ativar_edicao)
    time.sleep(base.PAUSA_APOS_ENTER_QUERY)

    # O F7 devolve o cursor ao campo Planta; avança até Local.
    for _ in range(base.TABS_PLANTA_ATE_LOCAL):
        base.proximo_campo_wms()

    base.limpar_campo_wms()
    base.escrever_wms(str(id_local))

    # F8 -> executa a consulta.
    base.atalho_wms(executar_campo)
    time.sleep(base.PAUSA_APOS_EXECUTAR_CONSULTA)

    if base.detectar_erro_wms_caido(timeout=0.5):
        raise base.WMSCaiuError()

    # --- Caso 1: local não cativado para este item --- #
    if base.detectar_pesquisa_sem_registro():
        base.log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Local {id_local} não está cativado para o item "
            f"{item}. Nada a descativar."
        )

        base.limpar_shift_f4()

        base.atalho_wms(executar_campo)
        time.sleep(base.PAUSA_APOS_EXECUTAR_CONSULTA)

        if callable(status_cb):
            try:
                status_cb(i, "Local_inexistente", item)
            except Exception:
                pass

        time.sleep(base.PAUSA_ANTES_PROXIMO_BLOCO)
        base.atalho_wms(proximo_bloco)

        return {
            "linha": i,
            "item": item,
            "id_local": id_local,
            "status": "Local_inexistente",
        }

    # --- Caso 2: registro encontrado -> remover --- #
    base.atalho_wms(remover_registro)
    time.sleep(base.PAUSA_APOS_REMOVER)

    base.atalho_wms(salvar_registro)

    if base.aguardar_transacao_completada(timeout=4.0):
        if callable(status_cb):
            try:
                status_cb(i, "Concluído", item)
            except Exception:
                pass

        base.log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[SUCESSO] Local {id_local} descativado do item {item}."
        )

        # O F10 já devolveu o cursor ao bloco de itens.
        base.voltar_para_bloco_itens()

        return {
            "linha": i,
            "item": item,
            "id_local": id_local,
            "status": "Descativado",
        }

    if base.detectar_erro_wms_caido(timeout=0.8):
        raise base.WMSCaiuError()

    if callable(status_cb):
        try:
            status_cb(i, "Nao_confirmado", item)
        except Exception:
            pass

    base.log(
        f"{time.strftime('[%H:%M:%S]')} "
        f"[WARN] Item {item}: descativação não confirmada. "
        "Verifique manualmente."
    )

    time.sleep(base.PAUSA_ANTES_PROXIMO_BLOCO)
    base.atalho_wms(proximo_bloco)

    return {
        "linha": i,
        "item": item,
        "id_local": id_local,
        "status": "Nao_confirmado",
    }


def iniciar_automacao(
    data=None,
    planta=None,
    log_fn=print,
    status_callback_fn=None,
):
    global status_callback

    base.set_logger(log_fn)

    if status_callback_fn is not None:
        status_callback = status_callback_fn

    base.clear_stop()

    inicio_execucao = registrar_evento_execucao(
        "wmma0031_descativar",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
    )

    log_fn("[INFO] Iniciando automação de descativação de locais...")

    if not base.abrir_transacao(log_fn=log_fn):
        registrar_evento_execucao(
            "wmma0031_descativar",
            "fim",
            inicio=inicio_execucao,
            status="erro",
            detalhe="Não foi possível abrir a transação",
        )
        return []

    if not data or len(data) == 0:
        log_fn("[INFO] Nenhum dado fornecido. Encerrando...")
        return []

    log_fn(f"[INFO] Dados fornecidos ({len(data)} linhas).")

    resultados = base.executar_linhas(
        data,
        _processar_linha,
        status_callback,
        CAMPOS,
    )

    totais = base.resumir(resultados, "Descativado", log_fn=log_fn)

    registrar_evento_execucao(
        "wmma0031_descativar",
        "fim",
        inicio=inicio_execucao,
        status="sucesso",
        **totais,
    )

    return resultados


if __name__ == "__main__":
    iniciar_automacao()
