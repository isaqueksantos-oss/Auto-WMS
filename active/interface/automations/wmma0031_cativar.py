"""
WMMA0031 - CATIVAR local

Entrada (3 colunas): item | id_local | qt_minima

Sequência de teclas por linha:

    1º item (tela recém-aberta, cursor já no campo Item):
        Ctrl+V (item)
        TAB                  -> campo Planta do bloco de Locais
        TAB                  -> campo Local
        Ctrl+V (id_local)
        TAB                  -> confirma o local (WMS preenche
                                endereço e classe)
        Shift+TAB x3         -> campo Qt. Mínima
        Ctrl+V (qt_minima)
        F10                  -> salva (já retorna ao bloco de Itens)

    demais itens:
        F7 + Ctrl+Q          -> reseta o formulário
        (mesma sequência acima)

Não há F8 nem Ctrl+PgDn neste fluxo: o TAB após o item já leva
diretamente ao bloco de Locais. Também não há F6 — a linha em branco
do bloco já está disponível para digitação.

Duplicidade:
    popup "Tentativa de duplicação de registro." -> Enter (OK)
    popup "Do you want to save the changes...?"  -> TAB + Enter (No)
"""

import time

from interface.automations.execution_log import registrar_evento_execucao
from interface.automations.base_automation import salvar_registro
from interface.automations import wmma0031_base as base

# Reexporta para a interface (main_window chama estas funções).
from interface.automations.wmma0031_base import (  # noqa: F401
    request_stop,
    clear_stop,
    verificar_tamanho_lista,
)


CAMPOS = ("item", "id_local", "qt_minima")

status_callback = None


def _resultado(i, item, id_local, qt_minima, status):
    return {
        "linha": i,
        "item": item,
        "id_local": id_local,
        "qt_minima": qt_minima,
        "status": status,
    }


def _processar_linha(i, valores, status_cb):
    item, id_local, qt_minima = valores

    base.log(
        f"[CATIVAR] Linha {i}: item {item} | local {id_local} | "
        f"qt mínima {qt_minima}"
    )

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
            _resultado(
                i, item, id_local, qt_minima, "Transacao_nao_encontrada"
            ),
        )

    # --- A partir do segundo item, reseta o formulário --- #
    # F7 + Ctrl+Q devolve a tela ao estado inicial, permitindo incluir
    # locais em itens que ainda não têm nenhum.
    if i > 1:
        base.resetar_formulario()

    # --- Item: Ctrl+V + TAB (desce direto para o bloco de Locais) --- #
    base.colar_item_e_descer(item)

    if base.detectar_erro_wms_caido(timeout=0.5):
        raise base.WMSCaiuError()

    # --- Local: TAB (Planta -> Local), Ctrl+V, TAB (confirma) --- #
    base.ir_da_planta_para_local()

    base.colar_wms(str(id_local))

    base.confirmar_local_digitado()

    # --- Qt. Mínima: Shift+TAB x3, Ctrl+V --- #
    base.ir_do_local_para_qt_minima()

    base.limpar_campo_wms()
    base.colar_wms(str(qt_minima))

    # --- F10: salva --- #
    base.atalho_wms(salvar_registro)

    if base.aguardar_transacao_completada(timeout=4.0):
        if callable(status_cb):
            try:
                status_cb(i, "Concluído", item)
            except Exception:
                pass

        base.log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[SUCESSO] Local {id_local} cativado para o item {item} "
            f"com qt mínima {qt_minima}."
        )

        # O F10 já devolveu o cursor ao bloco de Itens.
        base.voltar_para_bloco_itens()

        return _resultado(i, item, id_local, qt_minima, "Cativado")

    if base.detectar_erro_wms_caido(timeout=0.8):
        raise base.WMSCaiuError()

    # O local já pode estar cativado para este item.
    if base.detectar_registro_duplicado():
        # Enter no OK e "No" no diálogo de salvamento.
        base.tratar_registro_duplicado()

        if callable(status_cb):
            try:
                status_cb(i, "Ja_existente", item)
            except Exception:
                pass

        base.log(
            f"{time.strftime('[%H:%M:%S]')} "
            f"[INFO] Local {id_local} já está cativado para o item {item}."
        )

        return _resultado(i, item, id_local, qt_minima, "Ja_existente")

    # Salvamento não confirmado: descarta o que estiver pendente para
    # não travar a próxima linha em um diálogo aberto.
    if callable(status_cb):
        try:
            status_cb(i, "Nao_confirmado", item)
        except Exception:
            pass

    base.log(
        f"{time.strftime('[%H:%M:%S]')} "
        f"[WARN] Item {item}: cativação não confirmada. "
        "Verifique manualmente."
    )

    base.descartar_alteracoes_pendentes()

    return _resultado(i, item, id_local, qt_minima, "Nao_confirmado")


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

    registrar_evento_execucao(
        "wmma0031_cativar",
        "inicio",
        status="iniciado",
        linhas=len(data) if data else 0,
        planta=planta,
    )

    log_fn("[INFO] Iniciando automação de cativação de locais...")

    if not base.abrir_transacao(log_fn=log_fn):
        registrar_evento_execucao(
            "wmma0031_cativar",
            "fim",
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

    totais = base.resumir(resultados, "Cativado", log_fn=log_fn)

    registrar_evento_execucao(
        "wmma0031_cativar",
        "fim",
        status="sucesso",
        **totais,
    )

    return resultados


if __name__ == "__main__":
    iniciar_automacao()
