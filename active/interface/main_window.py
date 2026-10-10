import os
import time
import threading
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json
from interface.automations.base_automation import aguardar_textos, copiar_para_clipboard, focus_manager, maximize_manager
import keyring
import pyautogui
import pygetwindow as gw
import tkinter as tk
import pyperclip
from tkinter import ttk, scrolledtext, font as tkfont
from .automations import agendar_jobs, relex_download, wmex0115_eliminar_remessa, wmex1120_processar_remessa, wmma0020_mapeamento, wmma0020_remover_mapeamento, wmma0020_alterar_prioridade, wmma0020_alterar_restricao, wmma0031_cativar, wmma0031_descativar, wmma0031_alterar_ponto_minimo
from .tabs.excel_input import ExcelInput
from interface.utils.config_manager import carregar_config
from interface.utils.scheduler_manager import GerenciadorAgendamentos, Agendamento
from enum import Enum
from interface.utils.ui_theme import ThemeManager, ajustar_janela, ativar_dpi_awareness, escala_janela, largura_campo
from interface.utils.execution_tracker import ExecutionTracker

pyautogui.FAILSAFE = False

try:
    import keyboard as kb
except Exception:
    kb = None


APP_NAME = "AutoWMS"

# ========== CONFIGURAÇÕES ==========
BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "interface" / "utils" / "config_global.json"
CONFIG_ELIM_DEM_PATH = BASE_DIR / "interface" / "utils" / "config_eliminar_dem.json"

WINDOWS_CONFIG = {
    "width": 1800,
    "height": 900,
    "title": "Auto WMS V7",
    "resizable": True,
    "min_width": 1100,
    "min_height": 600,
}
AGENDAMENTOS_PANEL_WIDTH = 640

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

TABS_CONFIG = [
    #{"nome": "Agendar JOB's", "modulo": agendar_jobs, "tamanho_esperado": 1},
    #{"nome": "RELEX", "modulo": relex_download, "tamanho_esperado": 0},
    {"nome": "Eliminar remessa", "modulo": wmex0115_eliminar_remessa, "tamanho_esperado": 1},
    {"nome": "Processar remessa", "modulo": wmex1120_processar_remessa, "tamanho_esperado": 1},
    {"nome": "Mapeamento", "modulo": wmma0020_mapeamento, "tamanho_esperado": 7, "grupo": "WMMA0020"},
    {"nome": "Remover mapeamento", "modulo": wmma0020_remover_mapeamento, "tamanho_esperado": 3, "grupo": "WMMA0020"},
    {"nome": "Alterar prioridade", "modulo": wmma0020_alterar_prioridade, "tamanho_esperado": 4, "grupo": "WMMA0020"},
    {"nome": "Alterar restricao", "modulo": wmma0020_alterar_restricao, "tamanho_esperado": 4, "grupo": "WMMA0020"},
    {"nome": "Cativar local", "modulo": wmma0031_cativar, "tamanho_esperado": 3, "grupo": "WMMA0031"},
    {"nome": "Descativar local", "modulo": wmma0031_descativar, "tamanho_esperado": 2, "grupo": "WMMA0031"},
    {"nome": "Alterar ponto minimo", "modulo": wmma0031_alterar_ponto_minimo, "tamanho_esperado": 3, "grupo": "WMMA0031"},

]


class EstadoWMS(Enum):
    INIT = 1
    AGUARDANDO = 2
    UPDATE = 3
    SEGURANCA = 4
    LOGIN = 5
    LOGADO = 6
    ERRO = 7


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        # Inicializa a janela principal da aplicação
        self.root = root
        self.root.title(WINDOWS_CONFIG["title"])
        self.root.resizable(*([WINDOWS_CONFIG["resizable"]] * 2))
        # Dimensiona conforme a resolucao do monitor atual
        ajustar_janela(
            self.root,
            proporcao=0.9,
            minimo=(
                int(WINDOWS_CONFIG["min_width"] * 0.8),
                int(WINDOWS_CONFIG["min_height"] * 0.8),
            ),
        )
        self._escala_interface = 1.0
        self._espacamentos_base: Dict[tk.Misc, Tuple[str, Dict[str, Any]]] = {}
        self._fontes_nomeadas_base: Dict[str, Tuple[tkfont.Font, int]] = {}
        self._fontes_personalizadas: Dict[str, Tuple[tkfont.Font, int]] = {}
        self._fontes_estilos: Dict[str, Tuple[Any, List[Tuple[Any, Any]]]] = {}
        self._metricas_estilos: Dict[str, Dict[str, Any]] = {}
        self.theme = ThemeManager(self.root)
        self.root.option_add("*Label.Background", "#ECF4E8")
        self.root.option_add("*Label.Foreground", "#1f1f1f")
        self.root.option_add("*Checkbutton.Background", "#ECF4E8")
        self.root.option_add("*Checkbutton.Foreground", "#1f1f1f")
        self.root.option_add("*Checkbutton.ActiveBackground", "#ECF4E8")
        self.root.option_add("*Scrollbar.Background", "#d9d9d9")
        self.root.option_add("*Scrollbar.ActiveBackground", "#cfcfcf")
        self.root.option_add("*Scrollbar.TroughColor", "#ECF4E8")
        self.root.option_add("*Scrollbar.HighlightBackground", "#ECF4E8")
        self.root.option_add("*Scrollbar.HighlightColor", "#ECF4E8")
        self.root.option_add("*Scrollbar.BorderWidth", 0)
        self._keep_alive_thread: Optional[threading.Thread] = None
        self._parar_keep_alive = False
        self._keep_alive_watchdog_job = None
        self._execucoes_ativas = 0
        self._thread_monitor_agendamentos = None
        self._parar_monitor = False
        self._eliminar_remessa_campos_persistentes = {
            "plantas_eliminar": "",
            "restricoes_poupar": "",
            "lojas_poupar": "",
        }
        self.theme.aplicar()


        # Criar frames principais
        self._criar_frame_login(root)
        self._criar_frame_agendamentos(root)
        self._criar_notebook_abas(root)

        # Carregar configurações persistentes
        self._carregar_e_preencher_config()
        self._desabilitar_todos_campos()

        # Configurar hotkeys e protocolo de fechamento
        self._registrar_hotkey_global()
        self.root.bind_all("<Control-s>", self._on_ctrl_s_salvar)
        self.root.bind_all("<Control-S>", self._on_ctrl_s_salvar)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.iniciar_keep_alive()

        # Inicializar gerenciador de agendamentos
        self.gerenciador_agendamentos = GerenciadorAgendamentos()
        self._monitor_thread = None
        self.fila_popup = None
        self._configurar_callbacks_agendamentos()
        self._thread_monitor_agendamentos = self.gerenciador_agendamentos.iniciar_monitor_agendamentos()
        self._atualizar_botao_monitoramento()

        # Estado de edição do formulário
        self._modo_form = "visualizacao"  # visualizacao | novo | editar
        self._agendamento_selecionado_id = None
        self._tree_update_job = None
        self._resize_release_job = None
        self._window_resize_in_progress = False
        self._pending_agendamentos_refresh = False
        self._last_root_size: Optional[Tuple[int, int]] = None
        self._mudanca_aba_por_selecao_tree = False  # Flag para rastrear mudança de aba por seleção na treeview
        self._capturar_espacamentos_widgets(self.root)
        self.root.bind("<Configure>", self._on_root_configure)
        
        # Atualizar exibição com agendamentos carregados do JSON
        self._atualizar_exibicao_agendamentos()

        # Aplica o tema depois que todos os widgets ja existem
        self.theme.aplicar()
        self._capturar_fontes_widgets(self.root)

    def _criar_frame_login(self, root: tk.Tk) -> None:
        # Cria o frame de login com campos de usuário, senha, WMS e SAP
        frame = ttk.LabelFrame(root, text="Configuração de Login e Aplicação", padding=(1, 1))
        frame.pack(fill="x", padx=1, pady=1, side="top")

        # Campos WMS
        frame_wms = ttk.Frame(frame, padding=(5, 5))
        frame_wms.pack(fill="x", padx=10, pady=10, side="top")
        tk.Button(frame_wms, text="Login WMS", command=self._on_login_wms, width=16).pack(side="left", padx=(10, 10))
        self.usuario_var = self._criar_campo_entrada(frame_wms, "Usuário:", width=20)
        self.senha_var = self._criar_campo_entrada(frame_wms, "Senha:", width=20, is_password=True)
        self.wms_var = self._criar_campo_entrada(frame_wms, "Caminho (.jnlp):", width=55)
        
        # Separador visual
        ttk.Separator(frame, orient="horizontal").pack(side="top", fill="x", padx=10)

        # Campos SAP
        frame_sap = ttk.Frame(frame, padding=(1, 1))
        frame_sap.pack(fill="x", padx=10, pady=10, side="top")
        tk.Button(frame_sap, text="Login SAP", command=self._on_login_sap, width=16).pack(side="left", padx=(10, 10))
        self.usuario_sap_var = self._criar_campo_entrada(frame_sap, "Usuário:", width=20)
        self.senha_sap_var = self._criar_campo_entrada(frame_sap, "Senha:", width=20, is_password=True)
        self.conexao_sap_var = self._criar_campo_entrada(frame_sap, "Conexão:", width=20)

        # Alternancia entre tema claro e escuro
        self._btn_tema = tk.Button(
            frame_wms,
            text=self.theme.rotulo_botao(),
            width=10,
            command=self._alternar_tema,
        )
        self._btn_tema.pack(side="right", padx=5)


    def _criar_frame_agendamentos(self, root: tk.Tk) -> None:
        # Cria o frame de visualização de agendamentos
        frame = ttk.LabelFrame(root, text="Agendamentos", padding=(10, 5))
        self.frame_agendamentos = frame
        frame.configure(width=AGENDAMENTOS_PANEL_WIDTH)
        frame.pack(fill="y", padx=10, pady=10, side="right")
        frame.pack_propagate(False)
        frame2 = ttk.LabelFrame(frame, padding=(10, 5))
        frame2.pack(fill="x", expand=True, padx=10, pady=5, side="top")
        frame_botoes = ttk.Frame(frame2)
        frame_botoes.pack(fill="x", padx=5, pady=5)
        
        # Treeview de agendamentos
        self.frame_agendamentos_vazio = ttk.Frame(frame, width=AGENDAMENTOS_PANEL_WIDTH - 40, height=200)
        self.frame_agendamentos_vazio.pack(side="top", padx=10, pady=5, fill="both", expand=True)
        self.frame_agendamentos_vazio.pack_propagate(False)

        columns = ("id", "automacao", "nome_job", "proxima", "status")
        self.tree_agendamentos = ttk.Treeview(
            self.frame_agendamentos_vazio,
            columns=columns,
            show="headings",
            height=12,
        )
        self.tree_agendamentos.heading("id", text="ID")
        self.tree_agendamentos.heading("automacao", text="Automação")
        self.tree_agendamentos.heading("nome_job", text="Nome JOB")
        self.tree_agendamentos.heading("proxima", text="Próxima Exec.")
        self.tree_agendamentos.heading("status", text="Status")

        self.tree_agendamentos.column("id", width=50, anchor="center")
        self.tree_agendamentos.column("automacao", width=140, anchor="w")
        self.tree_agendamentos.column("nome_job", width=190, anchor="w")
        self.tree_agendamentos.column("proxima", width=110, anchor="center")
        self.tree_agendamentos.column("status", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(self.frame_agendamentos_vazio, orient="vertical", command=self.tree_agendamentos.yview)
        self.tree_agendamentos.configure(yscrollcommand=scrollbar.set)
        self.tree_agendamentos.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree_agendamentos.bind("<<TreeviewSelect>>", self._on_tree_agendamento_select)
        self.tree_agendamentos.bind('<Control-e>', lambda e: self._on_editar())
        
        frame3 = ttk.LabelFrame(frame, padding=(10, 5))
        frame3.pack(fill="x", expand=True, padx=10, pady=20, side="bottom")
        
        # Botões de fluxo
        self.btn_novo = tk.Button(frame_botoes, text="Novo", command=self._on_novo)
        self.btn_novo.pack(side="left", padx=5)
        self.btn_editar = tk.Button(frame_botoes, text="Editar", command=self._on_editar, state="disabled")
        self.btn_editar.pack(side="left", padx=5)
        self.btn_salvar = tk.Button(frame_botoes, text="Salvar", command=self._on_salvar, state="disabled")
        self.btn_salvar.pack(side="left", padx=5)
        self.btn_cancelar = tk.Button(frame_botoes, text="Cancelar", command=self._on_cancelar, state="disabled")
        self.btn_cancelar.pack(side="left", padx=5)
        self.btn_excluir = tk.Button(frame_botoes, text="Excluir", command=self._on_excluir, state="disabled")
        self.btn_excluir.pack(side="left", padx=5)

        # Botão para exibir fila em popup
        btn_exibir = tk.Button(frame2, text="Exibir fila", command=self._abrir_popup_exibir_agendamentos)
        btn_exibir.pack(side="top", padx=10, pady=5, fill="x")
        
        # Botão para excluir agendamento (popup removido; agora usa treeview)
        
        # Estado do monitoramento de agendamentos (Parado = False, Em execução = True)
        self._monitoramento_ativo = True
        
        # Botão para pausar/retomar monitoramento
        self.btn_monitoramento = tk.Button(frame3, text="Parado", font=("bold"), command=self._alternar_monitoramento_agendamentos)
        self.btn_monitoramento.pack(side="top", padx=10, pady=20, fill="x")
        self._atualizar_botao_monitoramento()
        self.theme.marcar_cor_fixa(self.btn_monitoramento)

    def _criar_notebook_abas(self, root: tk.Tk) -> None:
        # Cria o notebook com as abas de automações
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("AutoWMS.TNotebook", background="#ECF4E8", borderwidth=0)
        style.configure(
            "AutoWMS.TNotebook.Tab",
            background="#CBF3BB",
            foreground="#1f1f1f",
            padding=(12, 6),
        )

        style.map(
            "AutoWMS.TNotebook.Tab",
            background=[("selected", "#CBF3BB"), ("active", "#BCF7A0")],
            foreground=[("selected", "#1f1f1f"), ("active", "#1f1f1f")],
            font=[("selected", ("Arial", 10, "bold")), ("active", ("Arial", 10, "bold")), ("!active", ("Arial", 10))],

        )
        style.configure("TFrame", background="#ECF4E8")
        style.configure("TLabelframe", background="#ECF4E8")
        style.configure("TLabelframe.Label", background="#ECF4E8", foreground="#1f1f1f")
        style.configure(
            "Vertical.TScrollbar",
            background="#d9d9d9",
            troughcolor="#ECF4E8",
            arrowcolor="#1f1f1f",
            bordercolor="#ECF4E8",
            lightcolor="#ECF4E8",
            darkcolor="#ECF4E8",
            relief="flat",
            borderwidth=0,
            gripcount=0,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#cfcfcf"), ("pressed", "#bfbfbf")],
            arrowcolor=[("active", "#1f1f1f"), ("pressed", "#1f1f1f")],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background="#d9d9d9",
            troughcolor="#ECF4E8",
            arrowcolor="#1f1f1f",
            bordercolor="#ECF4E8",
            lightcolor="#ECF4E8",
            darkcolor="#ECF4E8",
            relief="flat",
            borderwidth=0,
            gripcount=0,
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", "#cfcfcf"), ("pressed", "#bfbfbf")],
            arrowcolor=[("active", "#1f1f1f"), ("pressed", "#1f1f1f")],
        )
        style.configure("AutoWMS.TabBody.TFrame", background="#ECF4E8")

        self.notebook = ttk.Notebook(root, style="AutoWMS.TNotebook")
        self.notebook.configure(takefocus=False)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
        # Notebooks internos, um por transacao agrupada
        self._grupos = {}

        self.automacoes = TABS_CONFIG.copy()
        for auto in self.automacoes:
            self._criar_aba_automacao(auto)

    def _criar_campo_entrada(self, parent: tk.Widget, label_text: str, width: int = 25, is_password: bool = False) -> tk.StringVar:
        # Helper para criar label + entry combinados
        tk.Label(parent, text=label_text).pack(side="left", padx=(0, 5))
        var = tk.StringVar()
        tk.Entry(parent, textvariable=var, width=width, show="*" if is_password else "").pack(side="left", padx=(0, 20))
        return var

    def _criar_excel_input_com_scroll(self, parent: tk.Widget) -> ExcelInput:
        # Cria um ExcelInput com barras de rolagem vertical e horizontal
        container = ttk.Frame(parent)
        container.pack(side="top", padx=10, pady=0, fill="both", expand=True)

        excel_input = ExcelInput(container)
        scrollbar_y = ttk.Scrollbar(container, orient="vertical", command=excel_input.yview)
        scrollbar_x = ttk.Scrollbar(container, orient="horizontal", command=excel_input.xview)

        excel_input.configure(
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
        )

        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        excel_input.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        return excel_input

    def _criar_texto_com_scroll_vertical(self, parent: tk.Widget, **text_kwargs) -> Tuple[ttk.Frame, tk.Text]:
        # Cria um Text com scrollbar vertical usando ttk.Scrollbar estilizado
        container = ttk.Frame(parent)
        text_widget = tk.Text(container, **text_kwargs)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        text_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return container, text_widget

    def _criar_guia_colunas_excel_input(self, parent: tk.Widget, *colunas) -> None:
        # Exibe um cabeçalho estático com as colunas esperadas para o ExcelInput
        if not colunas:
            return

        colunas_normalizadas = []
        for coluna in colunas:
            if isinstance(coluna, (tuple, list)) and coluna:
                titulo = str(coluna[0]).strip().upper()
                largura = int(coluna[1]) if len(coluna) > 1 and str(coluna[1]).strip() else len(titulo)
            else:
                titulo = str(coluna).strip().upper()
                largura = len(titulo)

            if titulo:
                colunas_normalizadas.append((titulo, max(1, largura)))

        if not colunas_normalizadas:
            return

        fonte_excel = tkfont.nametofont("TkFixedFont")
        frame_guia = tk.Frame(parent, bg=self.theme.cor("bg"))
        frame_guia.pack(anchor="w", padx=10, pady=(0, 0))

        for titulo, largura in colunas_normalizadas:
            tk.Label(
                frame_guia,
                text=titulo,
                bg=self.theme.cor("header_bg"),
                fg=self.theme.cor("header_fg"),
                font=fonte_excel,
                anchor="center",
                justify="center",
                relief="groove",
                bd=1,
                padx=2,
                pady=2,
                width=largura,
            ).pack(side="left")


    def _carregar_e_preencher_config(self) -> None:
        # Carrega configurações e preenche os campos correspondentes
        try:
            usuario, senha, wms, link_relex, caminho_salvar_relex, plantas, restricoes, lojas = carregar_config()
            if usuario:
                self.usuario_var.set(usuario)
            if senha:
                self.senha_var.set(senha)
            if wms:
                self.wms_var.set(wms)
            #if link_relex:
                #self.link_relex_var.set(link_relex)
            if caminho_salvar_relex:
                self.caminho_salvar_relex_var.set(caminho_salvar_relex)

            # Carregar credenciais SAP do keyring
            try:
                usuario_sap = keyring.get_password(APP_NAME, "usuario_sap")
                senha_sap = keyring.get_password(APP_NAME, "senha_sap")
                conexao_sap = keyring.get_password(APP_NAME, "conexao_sap")
                if usuario_sap:
                    self.usuario_sap_var.set(usuario_sap)
                if senha_sap:
                    self.senha_sap_var.set(senha_sap)
                if conexao_sap:
                    self.conexao_sap_var.set(conexao_sap)
                #usuario_relex = keyring.get_password(APP_NAME, "usuario_relex")
                #senha_relex = keyring.get_password(APP_NAME, "senha_relex")
                #if usuario_relex:
                #    self.usuario_relex_var.set(usuario_relex)
                #if senha_relex:
                #    self.senha_relex_var.set(senha_relex)
            except Exception:
                pass  # Se keyring falhar, apenas continua sem SAP

            if plantas and hasattr(self, "plantas_eliminar"):
                self._inserir_texto_widget(self.plantas_eliminar, plantas)
            if restricoes and hasattr(self, "restricoes_poupar"):
                self._inserir_texto_widget(self.restricoes_poupar, restricoes)
            if lojas and hasattr(self, "lojas_poupar"):
                self._inserir_texto_widget(self.lojas_poupar, lojas)
            self._atualizar_cache_campos_eliminar_remessa({
                "plantas_eliminar": plantas or "",
                "restricoes_poupar": restricoes or "",
                "lojas_poupar": lojas or "",
            })
        except Exception as e:
            self.log_app(f"Falha ao carregar config: {e}", "AVISO")

    @staticmethod
    def _inserir_texto_widget(widget: tk.Text, texto: str) -> None:
        # Helper para inserir texto em widget Text
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, texto)

    @staticmethod
    def log_app(mensagem: str, nivel: str = "INFO") -> None:
        # Logger centralizado com timestamp
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{nivel}] {mensagem}")

    #----------------------------------------------------------------------
    #---------------- GERENCIAMENTO DE AGENDAMENTOS-------------------
    #----------------------------------------------------------------------
    def _atualizar_widget_agendamentos(self, widget: scrolledtext.ScrolledText) -> None:
        # Legado desativado; mantido apenas para compatibilidade transitória
        self._atualizar_widget_fila(widget)
        return

        agendamentos = self.gerenciador_agendamentos.obter_agendamentos()

        if not agendamentos:
            widget.insert(tk.END, "Nenhum agendamento\npendente")
            widget.config(state="disabled")
            self._indice_para_id = {}  # Limpar mapeamento
            return

        # Criar mapeamento de índice visual para ID real
        self._indice_para_id = {i + 1: ag.id for i, ag in enumerate(agendamentos)}

        for idx, ag in enumerate(agendamentos, 1):  # Começa em 1
            ag_id = ag.id
            diario = "Sim" if ag.diario else "Não"
            nome_auto = ag.nome_automacao
            horas_str = ", ".join(ag.horas) if ag.horas else "N/A"

            status_info = self.gerenciador_agendamentos.obter_status_agendamento(ag_id)
            proxima_exec = status_info.get("proxima_execucao")
            status = status_info.get("status")
            posicao = status_info.get("posicao")

            status_str = ""
            if status == "aguardando_execucao" and posicao:
                status_str = f" [Fila: #{posicao}]"
            elif status == "executando":
                status_str = " [EXECUTANDO]"
            elif status == "pendente":
                status_str = " [PENDENTE]"
            elif status == "sem_fila":
                status_str = " [SEM FILA]"

            data_hora = proxima_exec.strftime("%d/%m %H:%M") if proxima_exec else "N/A"

            # Cabeçalho do agendamento - usa índice visual (idx)
            widget.insert(tk.END, f"#{idx} • Próxima: {data_hora}{status_str}\n")
            widget.insert(tk.END, f"  Automação: {nome_auto}\n")
            widget.insert(tk.END, f"  Diário: {diario}\n")
            widget.insert(tk.END, f"  Agenda: {horas_str}\n")

            # Informações específicas conforme tipo de automação
            self._exibir_info_agendamento(ag, widget)

            widget.insert(tk.END, "─" * 23 + "\n")

        widget.config(state="disabled")
        widget.see(tk.END)

    def _atualizar_exibicao_agendamentos(self) -> None:
        # Atualiza a exibição da seção de agendamentos (se janela popup estiver aberta)
        # Se a janela popup estiver aberta, atualiza o widget lá
        if (hasattr(self, "fila_popup") and self.fila_popup
            and self.fila_popup.winfo_exists()
            and hasattr(self.fila_popup, "fila_widget")):
            self._atualizar_widget_fila(self.fila_popup.fila_widget)

        # Atualizar treeview principal
        if self._window_resize_in_progress:
            self._pending_agendamentos_refresh = True
            return

        if hasattr(self, "tree_agendamentos"):
            self._agendar_atualizacao_treeview()

    def _atualizar_widget_fila(self, widget) -> None:
        # Atualiza um widget Text com a fila de execução ordenada por data/hora
        widget.config(state="normal")
        widget.delete("1.0", tk.END)

        fila_execucao = self.gerenciador_agendamentos.obter_fila_execucao()
        if not fila_execucao:
            widget.insert(tk.END, "Nenhum item na fila")
            widget.config(state="disabled")
            return

        agendamentos_por_id = {
            ag.id: ag for ag in self.gerenciador_agendamentos.obter_agendamentos()
        }

        for fe in fila_execucao:
            ag = agendamentos_por_id.get(fe.agendamento_id)
            if not ag:
                continue

            data_hora = fe.hora_agendada.strftime("%d/%m %H:%M")
            partes = [data_hora, ag.nome_automacao]

            identificador = self._obter_rotulo_fila_agendamento(ag)
            if identificador:
                partes.append(identificador)

            detalhes = self._obter_detalhes_fila_agendamento(ag)
            if detalhes:
                partes.append(detalhes)

            linha = " - ".join(partes)

            status = str(getattr(fe, "status", "") or "").strip().lower()
            if status == "executando":
                linha = f"{linha} [EXECUTANDO]"
            elif status == "aguardando_execucao":
                linha = f"{linha} [NA FILA]"

            widget.insert(tk.END, f"{linha}\n")

        widget.config(state="disabled")
        widget.see("1.0")

    def _obter_rotulo_fila_agendamento(self, ag: Agendamento) -> str:
        # Retorna o nome do job/arquivo exibido na fila quando aplicável
        payload = ag.payload or {}
        nome_job = str(payload.get("nome_job", "") or "").strip()
        output_name = str(payload.get("output_name", "") or "").strip()

        if nome_job:
            return nome_job
        if output_name:
            return output_name
        return ""

    def _obter_detalhes_fila_agendamento(self, ag: Agendamento) -> str:
        # Retorna o trecho de plantas exibido na fila quando houver
        payload = ag.payload or {}
        nome_auto = ag.nome_automacao.lower()

        if "eliminar remessa" in nome_auto:
            plantas = self._normalizar_texto_multilinha(payload.get("plantas", ""))
            if plantas:
                return ", ".join(plantas.splitlines()[:3])

        return ""

    def _agendar_atualizacao_treeview(self) -> None:
        # Debounce da atualização da treeview para evitar piscadas
        if self._window_resize_in_progress:
            self._pending_agendamentos_refresh = True
            return

        if self._tree_update_job:
            try:
                self.root.after_cancel(self._tree_update_job)
            except Exception:
                pass
        self._tree_update_job = self.root.after(120, self._atualizar_tree_agendamentos)

    def _on_root_configure(self, event=None) -> None:
        # Suspende atualizações pesadas enquanto a janela está sendo redimensionada
        if event is None or event.widget is not self.root:
            return

        novo_tamanho = (event.width, event.height)
        if self._last_root_size == novo_tamanho:
            return

        self._last_root_size = novo_tamanho
        self._aplicar_escala_interface(event.width)
        self._window_resize_in_progress = True
        self._pending_agendamentos_refresh = True

        if self._tree_update_job:
            try:
                self.root.after_cancel(self._tree_update_job)
            except Exception:
                pass
            finally:
                self._tree_update_job = None

        if self._resize_release_job:
            try:
                self.root.after_cancel(self._resize_release_job)
            except Exception:
                pass

        self._resize_release_job = self.root.after(180, self._finalizar_redimensionamento)

    def _capturar_espacamentos_widgets(self, parent: tk.Misc) -> None:
        metricas = ("padx", "pady", "ipadx", "ipady")
        for widget in parent.winfo_children():
            if widget.winfo_toplevel() is self.root:
                gerenciador = widget.winfo_manager()
                if gerenciador in ("pack", "grid", "place") and widget not in self._espacamentos_base:
                    obter_info = getattr(widget, f"{gerenciador}_info")
                    info = obter_info()
                    espacamentos = {
                        chave: info[chave]
                        for chave in metricas
                        if chave in info
                    }
                    self._espacamentos_base[widget] = (gerenciador, espacamentos)
                self._capturar_espacamentos_widgets(widget)

    def _escalar_espacamento(self, valor, escala: float):
        if isinstance(valor, (tuple, list)):
            return tuple(self._escalar_espacamento(item, escala) for item in valor)

        if isinstance(valor, str):
            partes = self.root.tk.splitlist(valor)
            if len(partes) > 1:
                return tuple(self._escalar_espacamento(item, escala) for item in partes)
            if partes:
                valor = partes[0]

        try:
            return int(round(float(valor) * escala))
        except (TypeError, ValueError):
            return valor

    def _obter_fonte_escalavel(self, especificacao):
        nomes_fontes = set(tkfont.names(self.root))
        if isinstance(especificacao, str) and especificacao in nomes_fontes:
            return especificacao

        chave = str(especificacao)
        if chave not in self._fontes_personalizadas:
            fonte = tkfont.Font(root=self.root, font=especificacao)
            self._fontes_personalizadas[chave] = (
                fonte,
                int(fonte.cget("size")),
            )
        return self._fontes_personalizadas[chave][0]

    def _capturar_fonte_estilo(self, nome: str, estilo: ttk.Style) -> None:
        if nome in self._fontes_estilos:
            return

        fonte_base = estilo.lookup(nome, "font")
        fonte_estilo = self._obter_fonte_escalavel(fonte_base) if fonte_base else ""
        mapa_fontes = []
        for estados, especificacao in estilo.map(nome, "font"):
            fonte = self._obter_fonte_escalavel(especificacao)
            mapa_fontes.append((estados, fonte))

        if fonte_estilo and not isinstance(fonte_estilo, str):
            estilo.configure(nome, font=fonte_estilo)
        if mapa_fontes:
            estilo.map(nome, font=mapa_fontes)
        self._fontes_estilos[nome] = (fonte_estilo, mapa_fontes)

        configuracoes = estilo.configure(nome) or {}
        metricas = {
            chave: configuracoes[chave]
            for chave in ("padding", "tabmargins", "rowheight")
            if chave in configuracoes
        }
        if metricas:
            self._metricas_estilos[nome] = metricas

    def _capturar_fontes_widgets(self, parent: tk.Misc) -> None:
        if not self._fontes_nomeadas_base:
            for nome in tkfont.names(self.root):
                fonte = tkfont.nametofont(nome, root=self.root)
                self._fontes_nomeadas_base[nome] = (
                    fonte,
                    int(fonte.cget("size")),
                )

        estilo = ttk.Style(self.root)
        for widget in parent.winfo_children():
            if widget.winfo_toplevel() is self.root:
                try:
                    especificacao = widget.cget("font")
                except tk.TclError:
                    especificacao = ""
                if especificacao and isinstance(widget, tk.Widget):
                    fonte = self._obter_fonte_escalavel(especificacao)
                    if not isinstance(fonte, str):
                        widget.configure({"font": fonte})

                if isinstance(widget, ttk.Widget):
                    nome_estilo = widget.cget("style") or widget.winfo_class()
                    self._capturar_fonte_estilo(nome_estilo, estilo)
                    if "Notebook" in nome_estilo:
                        self._capturar_fonte_estilo(f"{nome_estilo}.Tab", estilo)
                    if isinstance(widget, ttk.Treeview):
                        self._capturar_fonte_estilo("Treeview.Heading", estilo)
                    if isinstance(widget, ttk.LabelFrame):
                        self._capturar_fonte_estilo("TLabelframe.Label", estilo)

                self._capturar_fontes_widgets(widget)

    @staticmethod
    def _tamanho_fonte_escalado(tamanho: int, escala: float) -> int:
        escalado = int(round(tamanho * escala))
        if tamanho > 0:
            return max(1, escalado)
        if tamanho < 0:
            return min(-1, escalado)
        return 0

    def _aplicar_escala_interface(self, largura: int, forcar: bool = False) -> None:
        escala = round(
            escala_janela(largura, referencia=WINDOWS_CONFIG["width"]),
            2,
        )
        if escala == self._escala_interface and not forcar:
            return

        self._escala_interface = escala
        for fonte, tamanho in self._fontes_nomeadas_base.values():
            fonte.configure(size=self._tamanho_fonte_escalado(tamanho, escala))
        for fonte, tamanho in self._fontes_personalizadas.values():
            fonte.configure(size=self._tamanho_fonte_escalado(tamanho, escala))

        estilo = ttk.Style(self.root)
        for nome, (fonte, mapa_fontes) in self._fontes_estilos.items():
            if fonte:
                estilo.configure(nome, font=fonte)
            if mapa_fontes:
                estilo.map(nome, font=mapa_fontes)
        for nome, metricas in self._metricas_estilos.items():
            estilo.configure(
                nome,
                **{
                    chave: self._escalar_espacamento(valor, escala)
                    for chave, valor in metricas.items()
                },
            )

        self.frame_agendamentos.configure(width=round(AGENDAMENTOS_PANEL_WIDTH * escala))
        self.frame_agendamentos_vazio.configure(
            width=round((AGENDAMENTOS_PANEL_WIDTH - 40) * escala),
            height=round(200 * escala),
        )

        for widget, (gerenciador, espacamentos) in self._espacamentos_base.items():
            if not espacamentos or not widget.winfo_exists():
                continue
            configure = getattr(widget, f"{gerenciador}_configure")
            configure(**{
                chave: self._escalar_espacamento(valor, escala)
                for chave, valor in espacamentos.items()
            })

        self._configurar_colunas_tree_agendamentos()

    def _finalizar_redimensionamento(self) -> None:
        # Retoma as atualizaÃ§Ãµes quando o usuÃ¡rio termina o resize
        self._resize_release_job = None
        self._window_resize_in_progress = False

        if self._pending_agendamentos_refresh:
            self._pending_agendamentos_refresh = False
            self._atualizar_exibicao_agendamentos()

    def _configurar_colunas_tree_agendamentos(self) -> None:
        # Configura as colunas fixas da treeview de agendamentos
        self.tree_agendamentos["displaycolumns"] = ("id", "automacao", "nome_job", "proxima", "status")

        escala = self._escala_interface
        largura_total = round(600 * escala)
        largura_id = round(50 * escala)
        largura_proxima = round(120 * escala)
        largura_status = round(110 * escala)
        largura_nome_job = round(180 * escala)
        largura_automacao = largura_total - (largura_id + largura_proxima + largura_status + largura_nome_job)

        self.tree_agendamentos.column("id", width=largura_id, anchor="center")
        self.tree_agendamentos.column("automacao", width=largura_automacao, anchor="w")
        self.tree_agendamentos.column("nome_job", width=180, stretch=True, anchor="w")
        self.tree_agendamentos.column("proxima", width=largura_proxima, anchor="center")
        self.tree_agendamentos.column("status", width=largura_status, anchor="center")

    def _atualizar_tree_agendamentos(self) -> None:
        # Atualiza a Treeview principal com os agendamentos
        try:
            self.tree_agendamentos.configure(takefocus=False)
            self.tree_agendamentos.configure(selectmode="browse")
            self._configurar_colunas_tree_agendamentos()

            for item in self.tree_agendamentos.get_children():
                self.tree_agendamentos.delete(item)

            agendamentos = self.gerenciador_agendamentos.obter_agendamentos()
            agendamentos = sorted(
                agendamentos,
                key=lambda ag: (
                    str((ag.payload or {}).get("nome_job", "")).strip().lower(),
                    ag.id,
                ),
                reverse=True,
            )
            if not agendamentos:
                return

            for ag in agendamentos:
                status_info = self.gerenciador_agendamentos.obter_status_agendamento(ag.id)
                proxima_exec = status_info.get("proxima_execucao")
                status = status_info.get("status", "")
                posicao = status_info.get("posicao")

                status_str = status.upper() if status else ""
                if status == "aguardando_execucao" and posicao:
                    status_str = f"FILA #{posicao}"

                proxima_str = proxima_exec.strftime("%d/%m %H:%M") if proxima_exec else "N/A"
                nome_job = ag.payload.get("nome_job", "") if ag.payload else ""
                nome_job = nome_job.strip() if isinstance(nome_job, str) else str(nome_job).strip()
                nome_job = nome_job or "-"

                self.tree_agendamentos.insert(
                    "",
                    "end",
                    values=(
                        ag.id,
                        ag.nome_automacao,
                        nome_job,
                        proxima_str,
                        status_str,
                    ),
                )
        except Exception:
            pass
        finally:
            try:
                self._tree_update_job = None
            except Exception:
                pass

    def _obter_auto_ativo(self) -> Optional[Dict[str, Any]]:
        # Retorna o dicionário da automação da aba atualmente selecionada
        try:
            tab_id = self.notebook.select()
            if not tab_id:
                return None
            frame = self.notebook.nametowidget(tab_id)

            # Se a aba selecionada for um grupo, desce para a aba interna
            for interno in getattr(self, "_grupos", {}).values():
                if interno.winfo_parent() == str(frame):
                    sub_id = interno.select()
                    if sub_id:
                        frame = interno.nametowidget(sub_id)
                    break

            for auto in self.automacoes:
                if auto.get("frame") == frame:
                    return auto
        except Exception:
            return None
        return None

    def _nome_automacao_chave(self, nome: str) -> str:
        # Normaliza o nome da automacao para comparacoes internas
        return (nome or "").strip().lower().replace("'", "")

    def _registrar_widgets_editaveis(self, auto: Dict[str, Any], *widgets: tk.Widget) -> None:
        # Registra widgets que devem ser habilitados/desabilitados
        lista = auto.setdefault("widgets_editaveis", [])
        for w in widgets:
            if w and w not in lista:
                lista.append(w)

    def _set_campos_state(self, auto: Dict[str, Any], enabled: bool) -> None:
        # Habilita/desabilita campos editáveis
        estado = "normal" if enabled else "disabled"
        for w in auto.get("widgets_editaveis", []):
            try:
                w.config(state=estado)
            except Exception:
                pass

    def _desabilitar_todos_campos(self) -> None:
        # Desabilita todos os campos de todas as abas
        for auto in self.automacoes:
            self._set_campos_state(auto, False)

    def _atualizar_botoes_fluxo(self, modo: str = "inicial") -> None:
        # Centraliza o estado dos botões do fluxo principal
        estados = {
            "inicial": {
                "novo": "normal",
                "editar": "disabled",
                "salvar": "disabled",
                "cancelar": "disabled",
                "excluir": "disabled",
            },
            "edicao": {
                "novo": "disabled",
                "editar": "disabled",
                "salvar": "normal",
                "cancelar": "normal",
                "excluir": "disabled",
            },
            "selecao": {
                "novo": "normal",
                "editar": "normal",
                "salvar": "disabled",
                "cancelar": "disabled",
                "excluir": "normal",
            },
        }
        estado = estados.get(modo, estados["inicial"])
        self.btn_novo.config(state=estado["novo"])
        self.btn_editar.config(state=estado["editar"])
        self.btn_salvar.config(state=estado["salvar"])
        self.btn_cancelar.config(state=estado["cancelar"])
        self.btn_excluir.config(state=estado["excluir"])

    def _cancelar_formulario_ativo(self, limpar_campos: bool = True) -> None:
        # Cancela criação/edição ativa e restaura a interface ao estado inicial
        if limpar_campos:
            for auto in self.automacoes:
                try:
                    self._limpar_campos_auto(auto)
                except Exception:
                    pass

        self._desabilitar_todos_campos()
        self._atualizar_botoes_fluxo("inicial")
        self._modo_form = "visualizacao"
        self._agendamento_selecionado_id = None

        try:
            self.tree_agendamentos.selection_remove(self.tree_agendamentos.selection())
        except Exception:
            pass

        self._atualizar_botoes_fluxo("inicial")

    def _atualizar_cache_campos_eliminar_remessa(self, valores: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        # Atualiza o cache dos campos persistentes da aba 'Eliminar remessa'
        if valores is None:
            valores = {
                "plantas_eliminar": self._ler_campo(getattr(self, "plantas_eliminar", None)) or "",
                "restricoes_poupar": self._ler_campo(getattr(self, "restricoes_poupar", None)) or "",
                "lojas_poupar": self._ler_campo(getattr(self, "lojas_poupar", None)) or "",
            }
        valores = {
            "plantas_eliminar": self._normalizar_texto_multilinha(valores.get("plantas_eliminar", "")),
            "restricoes_poupar": self._normalizar_texto_multilinha(valores.get("restricoes_poupar", "")),
            "lojas_poupar": self._normalizar_texto_multilinha(valores.get("lojas_poupar", "")),
        }
        self._eliminar_remessa_campos_persistentes.update(valores)
        return dict(self._eliminar_remessa_campos_persistentes)

    @staticmethod
    def _normalizar_texto_multilinha(valor: Any) -> str:
        # Normaliza separadores de lista para uma linha por item
        if valor is None:
            return ""
        texto = str(valor).replace("\r\n", "\n").replace("\r", "\n").replace("\t", "\n")
        linhas = [linha.strip() for linha in texto.split("\n") if linha and linha.strip()]
        return "\n".join(linhas)

    def _restaurar_campos_persistentes_eliminar_remessa(self, auto: Dict[str, Any]) -> None:
        # Restaura os campos persistentes da aba 'Eliminar remessa'
        for chave, valor in self._eliminar_remessa_campos_persistentes.items():
            widget = auto.get(chave)
            if widget:
                try:
                    widget.config(state="normal")
                    widget.delete("1.0", tk.END)
                    if valor:
                        widget.insert(tk.END, valor)
                except Exception:
                    pass

    def _limpar_campos_auto(self, auto: Dict[str, Any]) -> None:
        # Limpa os campos da automação
        # Horas
        horas_vars = auto.get("hora_var")
        if isinstance(horas_vars, list):
            for campo in horas_vars:
                try:
                    campo.config(state="normal")
                    campo.delete(0, tk.END)
                except Exception:
                    pass
        elif horas_vars is not None:
            try:
                if hasattr(horas_vars, "set"):
                    horas_vars.set("")
                else:
                    horas_vars.config(state="normal")
                    horas_vars.delete(0, tk.END)
            except Exception:
                pass

        # Checkbox diário
        if auto.get("checkbox_var") is not None:
            try:
                auto["checkbox_var"].set(False)
            except Exception:
                pass

        # Campos específicos
        campos_texto = [
            auto.get("nome_job_entry"),
            auto.get("usuario_job_entry"),
            auto.get("caminho_salvar_job_entry"),
            auto.get("sql_file_entry"),
            auto.get("output_dir_entry"),
            auto.get("output_name_entry"),
            auto.get("planta_entry"),
            auto.get("link_relex_entry"),
            auto.get("usuario_relex_entry"),
            auto.get("senha_relex_entry"),
            auto.get("caminho_salvar_relex_entry"),
        ]
        for w in campos_texto:
            if w:
                try:
                    w.config(state="normal")
                    w.delete(0, tk.END)
                except Exception:
                    pass

        campos_textarea = [
            auto.get("plantas_eliminar"),
            auto.get("restricoes_poupar"),
            auto.get("lojas_poupar"),
            auto.get("remessas_poupar"),
        ]
        for w in campos_textarea:
            if w:
                try:
                    w.config(state="normal")
                    w.delete("1.0", tk.END)
                except Exception:
                    pass

        excel_input = auto.get("excel_input")
        if excel_input:
            try:
                excel_input.config(state="normal")
                excel_input.delete("1.0", tk.END)
            except Exception:
                pass

    def _preencher_campos_agendamento(self, auto: Dict[str, Any], agendamento: Agendamento) -> None:
        # Preenche os campos da automação a partir de um agendamento
        self._limpar_campos_auto(auto)

        # Horas
        horas_vars = auto.get("hora_var")
        if isinstance(horas_vars, list):
            payload = agendamento.payload or {}
            valores_lista = agendamento.horas
            if self._nome_automacao_chave(agendamento.nome_automacao.lower()) == "agendar sistema de apoio":
                valores_lista = payload.get("minutos_cada_hora", []) or []
            for i, campo in enumerate(horas_vars):
                try:
                    campo.config(state="normal")
                    valor = valores_lista[i] if i < len(valores_lista) else ""
                    campo.delete(0, tk.END)
                    campo.insert(0, valor)
                except Exception:
                    pass
        elif horas_vars is not None:
            try:
                if hasattr(horas_vars, "set"):
                    horas_vars.set(agendamento.horas[0] if agendamento.horas else "")
                else:
                    horas_vars.config(state="normal")
                    horas_vars.delete(0, tk.END)
                    if agendamento.horas:
                        horas_vars.insert(0, agendamento.horas[0])
            except Exception:
                pass

        # Checkbox diário
        if auto.get("checkbox_var") is not None:
            try:
                auto["checkbox_var"].set(bool(agendamento.diario))
            except Exception:
                pass

        payload = agendamento.payload or {}
        nome_auto = agendamento.nome_automacao.lower()

        if self._nome_automacao_chave(nome_auto) == "agendar jobs":
            if auto.get("nome_job_entry"):
                auto["nome_job_entry"].config(state="normal")
                auto["nome_job_entry"].delete(0, tk.END)
                auto["nome_job_entry"].insert(0, payload.get("nome_job", ""))
            if auto.get("usuario_job_entry"):
                auto["usuario_job_entry"].config(state="normal")
                auto["usuario_job_entry"].delete(0, tk.END)
                auto["usuario_job_entry"].insert(0, payload.get("usuario_job", ""))
            if auto.get("caminho_salvar_job_entry"):
                auto["caminho_salvar_job_entry"].config(state="normal")
                auto["caminho_salvar_job_entry"].delete(0, tk.END)
                auto["caminho_salvar_job_entry"].insert(0, payload.get("caminho_salvar_job", ""))

        elif "agendar sistema de apoio" in nome_auto:
            if auto.get("sql_file_entry"):
                auto["sql_file_entry"].config(state="normal")
                auto["sql_file_entry"].delete(0, tk.END)
                auto["sql_file_entry"].insert(0, payload.get("sql_file", ""))
            if auto.get("output_dir_entry"):
                auto["output_dir_entry"].config(state="normal")
                auto["output_dir_entry"].delete(0, tk.END)
                auto["output_dir_entry"].insert(0, payload.get("output_dir", ""))
            if auto.get("output_name_entry"):
                auto["output_name_entry"].config(state="normal")
                auto["output_name_entry"].delete(0, tk.END)
                auto["output_name_entry"].insert(0, payload.get("output_name", ""))

        elif "eliminar remessa" in nome_auto:
            plantas = self._normalizar_texto_multilinha(payload.get("plantas", ""))
            restricoes = self._normalizar_texto_multilinha(payload.get("restricoes", ""))
            lojas = self._normalizar_texto_multilinha(payload.get("lojas", ""))
            remessas = payload.get("remessas", "")
            self._atualizar_cache_campos_eliminar_remessa({
                "plantas_eliminar": plantas,
                "restricoes_poupar": restricoes,
                "lojas_poupar": lojas,
            })

            if isinstance(remessas, list):
                remessas = "\n".join(remessas)

            for campo, valor in [
                (auto.get("plantas_eliminar"), plantas),
                (auto.get("restricoes_poupar"), restricoes),
                (auto.get("lojas_poupar"), lojas),
                (auto.get("remessas_poupar"), remessas),
            ]:
                if campo:
                    try:
                        campo.config(state="normal")
                        campo.delete("1.0", tk.END)
                        campo.insert(tk.END, valor)
                    except Exception:
                        pass

        elif "processar remessa" in nome_auto:
            if auto.get("planta_entry"):
                auto["planta_entry"].config(state="normal")
                auto["planta_entry"].delete(0, tk.END)
                auto["planta_entry"].insert(0, payload.get("planta", ""))

        elif "relex" in nome_auto:
            if auto.get("link_relex_entry"):
                auto["link_relex_entry"].config(state="normal")
                auto["link_relex_entry"].delete(0, tk.END)
                auto["link_relex_entry"].insert(0, payload.get("link", ""))
            if auto.get("usuario_relex_entry"):
                auto["usuario_relex_entry"].config(state="normal")
                auto["usuario_relex_entry"].delete(0, tk.END)
                auto["usuario_relex_entry"].insert(0, payload.get("usuario", ""))
            if auto.get("senha_relex_entry"):
                auto["senha_relex_entry"].config(state="normal")
                auto["senha_relex_entry"].delete(0, tk.END)
                auto["senha_relex_entry"].insert(0, payload.get("senha", ""))
            if auto.get("caminho_salvar_relex_entry"):
                auto["caminho_salvar_relex_entry"].config(state="normal")
                auto["caminho_salvar_relex_entry"].delete(0, tk.END)
                auto["caminho_salvar_relex_entry"].insert(0, payload.get("caminho_salvar", ""))

    def _on_tree_agendamento_select(self, event=None) -> None:
        # Ao selecionar agendamento na treeview, carrega dados nos campos
        try:
            selecionados = self.tree_agendamentos.selection()
            if not selecionados:
                return
            valores = self.tree_agendamentos.item(selecionados[0], "values")
            if not valores:
                return
            ag_id = int(valores[0])
            ag = self.gerenciador_agendamentos.obter_agendamento_por_id(ag_id)
            if not ag:
                return

            # Trocar para a aba correspondente
            for auto in self.automacoes:
                if self._nome_automacao_chave(auto["nome"]) == self._nome_automacao_chave(ag.nome_automacao):
                    if auto.get("frame"):
                        # Sinalizar que a mudança de aba foi por seleção na treeview
                        self._mudanca_aba_por_selecao_tree = True

                        grupo_auto = auto.get("grupo")
                        if grupo_auto and grupo_auto in getattr(self, "_grupos", {}):
                            interno = self._grupos[grupo_auto]
                            self.notebook.select(interno.winfo_parent())
                            interno.select(auto["frame"])
                        else:
                            self.notebook.select(auto["frame"])
                    self._preencher_campos_agendamento(auto, ag)
                    self._set_campos_state(auto, False)
                    break

            self._configurar_colunas_tree_agendamentos()

            self._agendamento_selecionado_id = ag_id
            self._modo_form = "visualizacao"
            self._atualizar_botoes_fluxo("selecao")
        except Exception:
            pass

    def _on_notebook_tab_changed(self, event=None) -> None:
        # Atualiza o layout da treeview ao trocar de aba
        try:
            if hasattr(self, "tree_agendamentos"):
                self._configurar_colunas_tree_agendamentos()
            # Só cancelar o formulário se a mudança de aba NÃO foi por seleção na treeview
            if self._mudanca_aba_por_selecao_tree:
                self._mudanca_aba_por_selecao_tree = False
                return
            self._cancelar_formulario_ativo(limpar_campos=self._modo_form in ("novo", "editar"))
        except Exception as e:
            print(f"Erro em _on_notebook_tab_changed: {e}")

    def _on_novo(self) -> None:
        # Habilita campos para novo agendamento
        auto = self._obter_auto_ativo()
        if not auto:
            return
        if auto["nome"].lower() == "eliminar remessa":
            self._atualizar_cache_campos_eliminar_remessa()
        self._limpar_campos_auto(auto)
        if auto["nome"].lower() == "eliminar remessa":
            self._restaurar_campos_persistentes_eliminar_remessa(auto)
        self._set_campos_state(auto, True)
        self._modo_form = "novo"
        self._agendamento_selecionado_id = None
        self._atualizar_botoes_fluxo("edicao")

    def _on_editar(self) -> None:
        # Habilita edição do agendamento selecionado
        if not self._agendamento_selecionado_id:
            return
        auto = self._obter_auto_ativo()
        if not auto:
            return
        ag = self.gerenciador_agendamentos.obter_agendamento_por_id(self._agendamento_selecionado_id)
        if not ag or self._nome_automacao_chave(auto["nome"]) != self._nome_automacao_chave(ag.nome_automacao):
            return
        self._set_campos_state(auto, True)
        self._modo_form = "editar"
        self._atualizar_botoes_fluxo("edicao")

    def _on_cancelar(self) -> None:
        # Cancela a criação ou edição ativa
        if self._modo_form == "editar":
            auto = self._obter_auto_ativo()
            if auto:
                self._set_campos_state(auto, False)
            self._modo_form = "visualizacao"
            self._atualizar_botoes_fluxo("selecao")
        else:
            self._cancelar_formulario_ativo()

    def _on_salvar(self) -> None:
        # Salva ou executa conforme regras (com validações)
        auto = self._obter_auto_ativo()
        if not auto:
            return

        ok = self._executar_automacao(
            auto,
            auto.get("excel_input"),
            auto.get("log_area"),
        )
        if ok:
            modo_anterior = self._modo_form
            self._set_campos_state(auto, False)
            self._modo_form = "visualizacao"
            if modo_anterior == "editar":
                self._atualizar_botoes_fluxo("selecao")
                self.tree_agendamentos.selection_set(str(self._agendamento_selecionado_id))
            else:
                self._cancelar_formulario_ativo(limpar_campos=False)

    def _on_ctrl_s_salvar(self, event=None) -> str:
        # Atalho Ctrl+S para acionar o mesmo fluxo do botão Salvar
        try:
            if hasattr(self, "btn_salvar") and str(self.btn_salvar.cget("state")) == "normal":
                self._on_salvar()
        except Exception:
            pass
        return "break"

    def _on_excluir(self) -> None:
        # Exclui o agendamento selecionado na treeview
        try:
            if not self._agendamento_selecionado_id:
                return
            sucesso = self.gerenciador_agendamentos.remover_agendamento(self._agendamento_selecionado_id)
            if sucesso:
                self._cancelar_formulario_ativo()
                self._atualizar_exibicao_agendamentos()
        except Exception:
            pass

    def _exibir_info_agendamento(self, ag: Agendamento, widget) -> None:
        # Exibe informações específicas do agendamento conforme seu tipo em um widget
        nome_auto = ag.nome_automacao.lower()

        if self._nome_automacao_chave(nome_auto) == "agendar jobs":
            nome_job = ag.payload.get("nome_job", "")
            usuario_job = ag.payload.get("usuario_job", "")
            if nome_job:
                widget.insert(tk.END, f"  Job: {nome_job[:32]}...\n" if len(nome_job) > 32 else f"  Job: {nome_job}\n")
            if usuario_job:
                widget.insert(tk.END, f"  Usuário: {usuario_job}\n")
        
        elif "agendar sistema de apoio" in nome_auto:
            data_ini = ag.payload.get("data_ini", "")
            data_fim = ag.payload.get("data_fim", "")
            output_name = ag.payload.get("output_name", "")
            if data_ini:
                widget.insert(tk.END, f"  Período: {data_ini} até {data_fim}\n")
            if output_name:
                widget.insert(tk.END, f"  Arquivo: {output_name}\n")

        elif "eliminar remessa" in nome_auto:
            plantas = ag.payload.get("plantas", "")
            if plantas:
                plantas_str = ", ".join(plantas.split("\n")[:7])  # Primeiras 7
                widget.insert(tk.END, f"  Plantas: {plantas_str}\n")
            restr = ag.payload.get("restricoes", "")
            if restr:
                restr_str = ", ".join(restr.split("\n")[:7])  # Primeiras 7
                widget.insert(tk.END, f"  Restrições: {restr_str}\n")

        elif "processar remessa" in nome_auto:
            planta = ag.payload.get("planta", "")
            if planta:
                widget.insert(tk.END, f"  Planta: {planta}\n")

        elif "mapeamento" in nome_auto:
            widget.insert(tk.END, "  Tipo: Mapeamento\n")
        elif "relex" in nome_auto:
            link = ag.payload.get("link", "")
            caminho = ag.payload.get("caminho_salvar", "")
            if link:
                widget.insert(tk.END, f"  Link: {link}\n")
            if caminho:
                widget.insert(tk.END, f"  Path: {caminho}\n")

    def _criar_agendamento_proximo_dia(self, agendamento: Agendamento) -> Agendamento:
        # Cria um novo agendamento idêntico para o próximo dia (usado para agendamentos diários)
        self.gerenciador_agendamentos.adicionar_agendamento_diario(agendamento)
        agendamentos = self.gerenciador_agendamentos.obter_agendamentos()
        novo_ag = agendamentos[-1]  # Pega o último adicionado
        self._atualizar_exibicao_agendamentos()
        return novo_ag

    def _processar_agendamento_executado(self, agendamento_id: int, agendamento: Agendamento) -> None:
        """Processa o agendamento após a execução.
        
        ⭐ NOVA ARQUITETURA: A lógica de recriação de diários agora é feita pelo scheduler_manager
        quando detecta o agendamento. Este método é mantido apenas para compatibilidade.
        
        Responsabilidades atuais:
        - Apenas atualizar exibição
        - Logar informações
        """
        # Atualizar exibição
        self._atualizar_exibicao_agendamentos()

    def _formatar_horarios_agendamento(self, agendamento: Agendamento) -> str:
        # Retorna uma representação amigável dos horários de um agendamento
        payload = agendamento.payload or {}
        if self._nome_automacao_chave(agendamento.nome_automacao.lower()) == "agendar sistema de apoio":
            minutos = payload.get("minutos_cada_hora") or []
            if minutos:
                return "Minutos: " + ", ".join(minutos)
        return ", ".join(agendamento.horas) if agendamento.horas else "N/A"

    def _expandir_minutos_para_horarios(self, minutos_texto: list[str]) -> tuple[Optional[list[str]], Optional[str]]:
        # Converte minutos de cada hora em uma lista completa de horários do dia
        minutos_validos = []

        for minuto_texto in minutos_texto:
            valor = (minuto_texto or "").strip()
            if not valor:
                continue

            if not valor.isdigit():
                return None, f"Minuto inválido: {valor} (use apenas números de 0 a 59)."

            minuto = int(valor)
            if minuto < 0 or minuto > 59:
                return None, f"Minuto inválido: {valor} (o minuto deve ser entre 0 e 59)."

            minutos_validos.append(f"{minuto:02d}")

        minutos_ordenados = sorted(set(minutos_validos), key=int)
        horarios = [f"{hora:02d}:{minuto}" for hora in range(24) for minuto in minutos_ordenados]
        return horarios, None

    def _criar_agendamento(self, auto: Dict[str, Any], nome_automacao: str, agendamento_id: Optional[int] = None, **kwargs) -> tuple:
        """Cria um agendamento único com múltiplos horários.
        
        Retorna: (agendamento, erro_msg, eh_novo)
        - Se sucesso: (agendamento, None, True/False)
        - Se erro: (None, mensagem_erro, False)
        - Se nenhuma hora preenchida: (None, None, False)
        """
        horas_vars = auto.get("hora_var")
        checkbox_diario = self._ler_campo(auto.get("checkbox_var"))

        horas_texto = []
        if isinstance(horas_vars, list):
            for campo in horas_vars:
                texto = self._ler_campo(campo)
                if texto:
                    horas_texto.append(texto)
        else:
            texto = self._ler_campo(horas_vars)
            if texto:
                horas_texto.append(texto)

        if not horas_texto:
            return None, None, False

        if self._nome_automacao_chave(nome_automacao) == "agendar sistema de apoio":
            horas_final, erro = self._expandir_minutos_para_horarios(horas_texto)
            if erro:
                return None, erro, False

            kwargs = dict(kwargs) if kwargs else {}
            kwargs["minutos_cada_hora"] = sorted({f"{int(h):02d}" for h in horas_texto if str(h).strip().isdigit()}, key=int)

            agendamento, erro, eh_novo = self.gerenciador_agendamentos.criar_ou_atualizar_agendamento(
                nome_automacao=nome_automacao,
                horas=horas_final or [],
                diario=bool(checkbox_diario),
                payload=kwargs if kwargs else {},
                agendamento_id=agendamento_id,
            )

            self._atualizar_exibicao_agendamentos()
            return agendamento, erro, eh_novo

        # Validar todas as horas PRIMEIRO
        horas_validas = []
        try:
            for hora_exec in horas_texto:
                try:
                    hora, minuto = map(int, hora_exec.split(":"))
                    if 0 <= hora <= 23 and 0 <= minuto <= 59:
                        horas_validas.append(f"{hora:02d}:{minuto:02d}")
                    else:
                        erro = f"Hora inválida: {hora_exec} (hora deve ser 0-23, minuto 0-59). Nenhum agendamento foi criado."
                        return None, erro, False
                except ValueError:
                    erro = f"Formato de hora inválido: {hora_exec} (use HH:MM). Nenhum agendamento foi criado."
                    return None, erro, False
        except Exception as e:
            erro = f"Erro ao parsear horas: {e}. Nenhum agendamento foi criado."
            return None, erro, False

        # Normalizar (remover duplicadas e ordenar)
        horas_final = sorted(set(horas_validas))

        agendamento, erro, eh_novo = self.gerenciador_agendamentos.criar_ou_atualizar_agendamento(
            nome_automacao=nome_automacao,
            horas=horas_final,
            diario=bool(checkbox_diario),
            payload=kwargs if kwargs else {},
            agendamento_id=agendamento_id,
        )

        self._atualizar_exibicao_agendamentos()
        return agendamento, erro, eh_novo

    def _abrir_popup_exibir_agendamentos(self) -> None:
        # Abre um popup para exibir a fila de execução
        # Fechar popup anterior se existir
        if hasattr(self, "fila_popup") and self.fila_popup and self.fila_popup.winfo_exists():
            self.fila_popup.destroy()

        # Criar janela popup
        popup = tk.Toplevel(self.root)
        popup.title("Fila de execução")
        popup.geometry("950x600")
        popup.resizable(True, True)
        
        # Centralizar na tela
        popup.transient(self.root)
        
        # Criar widget ScrolledText dentro do popup
        widget_container, widget_agendamentos = self._criar_texto_com_scroll_vertical(
            popup, width=70, height=20, state="normal", wrap="word"
        )
        widget_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Armazenar referência ao popup e ao widget
        self.fila_popup = popup
        popup.fila_widget = widget_agendamentos
        
        # Atualizar widget com agendamentos atuais
        self._atualizar_widget_fila(widget_agendamentos)
        
        # Limpar referência e destruir popup ao fechar
        def limpar_popup():
            if hasattr(self, "fila_popup"):
                self.fila_popup = None
            popup.destroy()
        
        popup.protocol("WM_DELETE_WINDOW", limpar_popup)

    def _alternar_monitoramento_agendamentos(self) -> None:
        # Alterna o estado de monitoramento (parado/em execução)
        self._monitoramento_ativo = not self._monitoramento_ativo
        self._atualizar_botao_monitoramento()
        
        if self._monitoramento_ativo:
            self.log_app("Monitoramento de agendamentos ativado", "SUCESSO")
            if (not self._thread_monitor_agendamentos 
                or not self._thread_monitor_agendamentos.is_alive()):
                self._thread_monitor_agendamentos = self.gerenciador_agendamentos.iniciar_monitor_agendamentos()
        else:
            self.log_app("Monitoramento de agendamentos pausado", "AVISO")
            self.gerenciador_agendamentos.parar_monitor_agendamentos()
            

    def _atualizar_botao_monitoramento(self) -> None:
        # Atualiza a aparência do botão de monitoramento conforme o estado
        if self._monitoramento_ativo:
            # Verde claro com texto "Em execução"
            self.btn_monitoramento.config(
                text="Em execução",
                bg="#90EE90",  # Verde claro
                fg="#000000",   # Preto para contraste
                activebackground="#7BC97B"  # Verde um pouco mais escuro ao clicar
            )


        else:
            # Vermelho claro com texto "Parado"
            self.btn_monitoramento.config(
                text="Parado",
                bg="#FFB6C6",  # Vermelho claro/rosa claro
                fg="#000000",   # Preto para contraste
                activebackground="#FF9DB5"  # Vermelho um pouco mais escuro ao clicar
            )

    def iniciar_keep_alive(self) -> None:
        # Inicia uma thread dedicada para pressionar Scroll Lock periodicamente

        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            return
        self._parar_keep_alive = False

        def _sinalizar_atividade_windows() -> bool:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
                return True
            except Exception:
                return False
        
        def keep_alive_loop():
            while not self._parar_keep_alive:
                try:
                    if self._parar_keep_alive:
                        break

                    try:
                        if not _sinalizar_atividade_windows():
                            pyautogui.press('scrolllock')
                    except Exception:
                        pass

                    time.sleep(5)

                except Exception:
                    pass
        
        self._keep_alive_thread = threading.Thread(target=keep_alive_loop, daemon=True)
        self._keep_alive_thread.start()

    def parar_keep_alive(self) -> None:
        # Para a thread de keep-alive
        self._parar_keep_alive = True
        if self._keep_alive_thread:
            self._keep_alive_thread.join(timeout=2)
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass

    def _agendar_keep_alive_watchdog(self) -> None:
        # Garante que o keep-alive permaneça ativo enquanto 'Em execução'
        return None

    def _cancelar_keep_alive_watchdog(self) -> None:
        # Cancela o watchdog do keep-alive
        return None

    def _registrar_inicio_execucao(self) -> None:
        # Mantido por compatibilidade; Scroll Lock não depende mais da execução
        return None

    def _registrar_fim_execucao(self) -> None:
        # Mantido por compatibilidade; Scroll Lock não depende mais da execução
        return None
    #----------------------------------------------------------------------
    #------------------- PERSISTÊNCIA E SALVAMENTO--------------------
    #----------------------------------------------------------------------
    def _salvar_config(self) -> bool:
        # Salva configurações globais e específicas de automações
        sucesso_global = self._salvar_config_global()
        sucesso_local = self._salvar_config_eliminar_dem()
        return sucesso_global and sucesso_local

    def _salvar_config_global(self) -> bool:
        # Salva configurações globais (caminho WMS, credenciais WMS e SAP)
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"caminho_wms": self.wms_var.get().strip()}
            if data["caminho_wms"].startswith('"'):
                data["caminho_wms"] = data["caminho_wms"][1:]
            if data["caminho_wms"].endswith('"'):
                data["caminho_wms"] = data["caminho_wms"][:-1]
            data = {
                "caminho_wms": self.wms_var.get().strip(),
                #"link_relex": self.link_relex_var.get().strip(),
                #"caminho_salvar_relex": self.caminho_salvar_relex_var.get().strip(),
            }
            if data["caminho_wms"].startswith('"'):
                data["caminho_wms"] = data["caminho_wms"][1:]
            if data["caminho_wms"].endswith('"'):
                data["caminho_wms"] = data["caminho_wms"][:-1]
            #if data["link_relex"].startswith('"'):
            #    data["link_relex"] = data["link_relex"][1:]
            #if data["link_relex"].endswith('"'):
            #    data["link_relex"] = data["link_relex"][:-1]

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Salvar credenciais WMS
            keyring.set_password(APP_NAME, "usuario", self.usuario_var.get().strip())
            keyring.set_password(APP_NAME, "senha", self.senha_var.get().strip())
            
            # Salvar credenciais SAP
            keyring.set_password(APP_NAME, "usuario_sap", self.usuario_sap_var.get().strip())
            keyring.set_password(APP_NAME, "senha_sap", self.senha_sap_var.get().strip())
            keyring.set_password(APP_NAME, "conexao_sap", self.conexao_sap_var.get().strip())
            
            # Salvar credenciais RELEX
            #keyring.set_password(APP_NAME, "usuario_relex", self.usuario_relex_var.get().strip())
            #keyring.set_password(APP_NAME, "senha_relex", self.senha_relex_var.get().strip())
            
            return True
        except FileNotFoundError as e:
            self.log_app(f"Arquivo de config não encontrado: {e}", "ERRO")
            return False
        except Exception as e:
            self.log_app(f"Falha ao salvar config global: {e}", "ERRO")
            return False

    def _on_login_wms(self) -> None:
        # Executa apenas o fluxo de login do WMS sem iniciar automacoes
        usuario = self.usuario_var.get().strip()
        senha = self.senha_var.get().strip()
        caminho_wms = self.wms_var.get().strip()
        if caminho_wms.startswith('"'):
            caminho_wms = caminho_wms[1:]
        if caminho_wms.endswith('"'):
            caminho_wms = caminho_wms[:-1]

        if not all([usuario, senha, caminho_wms]):
            self.log_app("Usuario, senha ou caminho WMS ausentes. Preencha antes de fazer login.", "ERRO")
            return

        if not self._salvar_config_global():
            self.log_app("Falha ao salvar configuracoes antes do login WMS.", "ERRO")
            return

        self.log_app("[INFO] Iniciando fluxo de login do WMS...")

        def _worker():
            sucesso = self._abrir_janela_wms(self.log_app, caminho_wms, usuario, senha)
            if sucesso:
                self.log_app("[OK] Login WMS concluido.")
            else:
                self.log_app("[ERRO] Nao foi possivel concluir o login WMS.", "ERRO")

        threading.Thread(target=_worker, daemon=True).start()

    def _aguardar_janela_sap(
        self,
        titulo_esperado: str,
        timeout: float,
        titulos_ignorados: Tuple[str, ...] = (),
    ) -> Optional[Any]:
        prazo = time.monotonic() + timeout
        while time.monotonic() < prazo:
            for titulo in gw.getAllTitles():
                titulo_normalizado = titulo.casefold()
                if titulo_esperado.casefold() not in titulo_normalizado:
                    continue
                if any(ignorado.casefold() in titulo_normalizado for ignorado in titulos_ignorados):
                    continue

                janelas = gw.getWindowsWithTitle(titulo)
                if janelas:
                    janela = janelas[0]
                    janela.activate()
                    time.sleep(0.2)
                    janela.maximize()
                    time.sleep(0.3)
                    return janela
            time.sleep(0.2)
        return None

    def _on_login_sap(self) -> None:
        usuario = self.usuario_sap_var.get().strip()
        senha = self.senha_sap_var.get().strip()
        conexao = self.conexao_sap_var.get().strip()
        if not all([usuario, senha, conexao]):
            self.log_app("Usuario, senha ou conexao SAP ausentes. Preencha antes de fazer login.", "ERRO")
            return

        if not self._salvar_config_global():
            self.log_app("Falha ao salvar configuracoes antes do login SAP.", "ERRO")
            return

        self.log_app("[INFO] Iniciando fluxo de login do SAP...")

        def _worker() -> None:
            try:
                if not agendar_jobs.sap_esta_rodando():
                    sapgui_path = agendar_jobs.encontrar_sapgui()
                    if not sapgui_path:
                        self.log_app("[ERRO] Nao foi possivel localizar o SAP GUI.")
                        return
                    self.log_app(f"[INFO] Iniciando SAP GUI em: {sapgui_path}")
                    if not agendar_jobs.iniciar_sap(str(sapgui_path)):
                        self.log_app("[ERRO] Nao foi possivel iniciar o SAP GUI.", "ERRO")
                        return

                janela_logon = self._aguardar_janela_sap("logon", timeout=30)
                if janela_logon is None:
                    self.log_app("[ERRO] Janela de conexao do SAP nao encontrada.", "ERRO")
                    return

                pyperclip.copy(conexao)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")

                janela_login = self._aguardar_janela_sap(
                    "sap",
                    timeout=60,
                    titulos_ignorados=("logon",),
                )
                if janela_login is None:
                    self.log_app("[ERRO] Janela de login do SAP nao encontrada.", "ERRO")
                    return

                pyperclip.copy(usuario)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("tab")
                time.sleep(0.2)
                pyperclip.copy(senha)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")
                self.log_app("[OK] Credenciais enviadas ao SAP.")
            except Exception as e:
                self.log_app(f"[ERRO] Falha ao iniciar ou autenticar no SAP: {e}", "ERRO")

        threading.Thread(target=_worker, daemon=True).start()

    def _salvar_config_eliminar_dem(self) -> bool:
        # Salva configurações específicas da aba 'Eliminar remessa'
        try:
            CONFIG_ELIM_DEM_PATH.parent.mkdir(parents=True, exist_ok=True)
            plantas = self._ler_campo(self.plantas_eliminar) if hasattr(self, "plantas_eliminar") else ""
            restricoes = self._ler_campo(self.restricoes_poupar) if hasattr(self, "restricoes_poupar") else ""
            lojas = self._ler_campo(self.lojas_poupar) if hasattr(self, "lojas_poupar") else ""
            plantas = self._normalizar_texto_multilinha(plantas)
            restricoes = self._normalizar_texto_multilinha(restricoes)
            lojas = self._normalizar_texto_multilinha(lojas)

            data = {"plantas_eliminar": plantas, "restricoes_poupar": restricoes, "lojas_poupar": lojas}
            with open(CONFIG_ELIM_DEM_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except FileNotFoundError as e:
            self.log_app(f"Arquivo de config eliminar não encontrado: {e}", "ERRO")
            return False
        except Exception as e:
            self.log_app(f"Falha ao salvar config eliminar: {e}", "ERRO")
            return False

    def _on_close(self) -> None:
        # Encerra a aplicação salvando configurações
        self._salvar_config()
        self.parar_keep_alive()
        if kb and getattr(self, "_kb_hotkey", None):
            try:
                kb.remove_hotkey(self._kb_hotkey)
            except Exception:
                pass
        self.root.destroy()



    #----------------------------------------------------------------------
    #------------------- LEITURA E VALIDAÇÃO DE CAMPOS----------------
    #----------------------------------------------------------------------
    def _ler_campo(self, campo: Any) -> Optional[str]:
        # Lê valor de qualquer tipo de widget (StringVar, Text, etc)
        if campo is None:
            return None

        if hasattr(campo, "get") and not isinstance(campo, tk.Text):
            value = campo.get()
            return value.strip() if isinstance(value, str) else value

        if isinstance(campo, tk.Text):
            return campo.get("1.0", tk.END).strip()

        return None

    def _validar_campos_obrigatorios(self, campos: Dict[str, Optional[str]]) -> Tuple[bool, str]:
        # Valida múltiplos campos obrigatórios
        for nome, valor in campos.items():
            if not valor or not str(valor).strip():
                return False, f"Campo '{nome}' obrigatório não preenchido."
        return True, ""

    def _processar_remessas_poupar(self, remessas_texto: str) -> list:
        """Processa remessas com padding de 10 caracteres.
        
        - Split por quebra de linha
        - Remove espaços em branco
        - Preenche com zeros à esquerda até 10 caracteres
        - Retorna lista de remessas formatadas
        """
        if not remessas_texto or not remessas_texto.strip():
            return []
        
        remessas_processadas = []
        linhas = remessas_texto.strip().split('\n')
        
        for linha in linhas:
            remessa = linha.strip()
            if remessa:
                # Preencher com zeros à esquerda até completar 10 caracteres
                remessa_padded = remessa.zfill(10)
                remessas_processadas.append(remessa_padded)
        
        return remessas_processadas

    #----------------------------------------------------------------------
    #------------------------ CRIAÇÃO DE ABA---------------------------
    #----------------------------------------------------------------------
    def _criar_aba_automacao(self, auto: Dict[str, Any]) -> None:
        # Dispatcher para criar abas específicas baseado no nome
        nome = auto["nome"].lower()
        grupo = auto.get("grupo")

        if grupo:
            # Agrupa as automacoes da mesma transacao em um notebook interno
            if grupo not in self._grupos:
                container = ttk.Frame(self.notebook, style="AutoWMS.TabBody.TFrame")
                self.notebook.add(container, text=grupo)

                interno = ttk.Notebook(container, style="AutoWMS.TNotebook")
                interno.configure(takefocus=False)
                interno.pack(fill="both", expand=True, padx=2, pady=2)
                interno.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
                self._grupos[grupo] = interno

            destino = self._grupos[grupo]
        else:
            destino = self.notebook

        frame_dados = ttk.Frame(destino, style="AutoWMS.TabBody.TFrame")
        destino.add(frame_dados, text=auto["nome"])
        auto["frame"] = frame_dados

        if self._nome_automacao_chave(nome) == "agendar jobs":
            self._criar_aba_agendar_jobs(frame_dados, auto)
        elif nome == "eliminar remessa":
            self._criar_aba_eliminar_remessa(frame_dados, auto)
        elif nome == "processar remessa":
            self._criar_aba_processar_remessa(frame_dados, auto)
        elif nome == "mapeamento":
            self._criar_aba_mapeamento(frame_dados, auto)
        elif nome == "remover mapeamento":
            self._criar_aba_remover_mapeamento(frame_dados, auto)
        elif nome == "alterar prioridade":
            self._criar_aba_alterar_prioridade(frame_dados, auto)
        elif nome == "alterar restricao":
            self._criar_aba_alterar_restricao(frame_dados, auto)
        elif nome == "cativar local":
            self._criar_aba_cativar_local(frame_dados, auto)
        elif nome == "descativar local":
            self._criar_aba_descativar_local(frame_dados, auto)
        elif nome == "alterar ponto minimo":
            self._criar_aba_alterar_ponto_minimo(frame_dados, auto)
        elif nome == "relex":
            self._criar_aba_relex(frame_dados, auto)

                # Adicionar seção de logs e botão de execução em todas as abas
        self._adicionar_logs_e_botao(frame_dados, auto)

    def _criar_aba_relex(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba RELEX com campos de link, usuário, senha, caminho salvar e agendamento
        frame_relex = ttk.Frame(frame_dados)
        frame_relex.pack(anchor="n", padx=10, pady=10, fill="x")

        # Linha com horas (6 campos) e checkbox ao lado
        frame_horas = ttk.Frame(frame_relex)
        frame_horas.pack(anchor="w", padx=10, pady=(0, 10), fill="x")
        tk.Label(frame_horas, text="Horas (HH:MM):").pack(side="left", padx=(0, 5))

        horas_vars = []
        for _ in range(6):
            hora_entry = tk.Entry(frame_horas, width=6)
            hora_entry.pack(side="left", padx=2)
            horas_vars.append(hora_entry)

        checkbox_var = tk.BooleanVar(value=False)
        checkbox_widget = tk.Checkbutton(frame_horas, text="Executar diariamente", variable=checkbox_var)
        checkbox_widget.pack(side="left", padx=(10, 0))

        # Campos empilhados verticalmente: Link, Usuário, Senha, Caminho salvar
        def _linha_campo(parent, label_text, var=None, show=None, entry_width=80):
            row = ttk.Frame(parent)
            row.pack(anchor="w", fill="x", padx=10, pady=4)
            tk.Label(row, text=label_text).pack(side="left", padx=(0, 8))
            if var is None:
                var = tk.StringVar()
            entry = tk.Entry(row, textvariable=var, width=entry_width, show=show if show else "")
            entry.pack(side="left", fill="x", expand=True)
            return var, entry

        link_relex_var, link_relex_entry = _linha_campo(frame_relex, "Link:")
        usuario_relex_var, usuario_relex_entry = _linha_campo(frame_relex, "Usuário:")
        senha_relex_var, senha_relex_entry = _linha_campo(frame_relex, "Senha:", show="*")
        caminho_salvar_relex_var, caminho_salvar_relex_entry = _linha_campo(frame_relex, "Caminho salvar:")

        # Registrar no dicionário 'auto' para reaproveitamento pelo restante da lógica
        auto["hora_var"] = horas_vars
        auto["checkbox_var"] = checkbox_var
        auto["link_relex_var"] = link_relex_var
        auto["usuario_relex_var"] = usuario_relex_var
        auto["senha_relex_var"] = senha_relex_var
        auto["caminho_salvar_relex_var"] = caminho_salvar_relex_var

        auto["link_relex_entry"] = link_relex_entry
        auto["usuario_relex_entry"] = usuario_relex_entry
        auto["senha_relex_entry"] = senha_relex_entry
        auto["caminho_salvar_relex_entry"] = caminho_salvar_relex_entry

        # Mantém referências no objeto para persistência global
        self.link_relex_var = link_relex_var
        self.usuario_relex_var = usuario_relex_var
        self.senha_relex_var = senha_relex_var
        self.caminho_salvar_relex_var = caminho_salvar_relex_var

        # Registrar widgets editáveis
        self._registrar_widgets_editaveis(
            auto,
            *horas_vars,
            checkbox_widget,
            link_relex_entry,
            usuario_relex_entry,
            senha_relex_entry,
            caminho_salvar_relex_entry,
        )

    def _criar_aba_agendar_jobs(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de agendamento de JOBs
        frame_hora_job = ttk.Frame(frame_dados)
        frame_hora_job.pack(anchor="n", padx=10, pady=5, fill="x")

        tk.Label(frame_hora_job, text="Horas (HH:MM):").pack(side="left", padx=(0, 5))
        
        # Criar 12 campos pequenos para horas
        horas_vars = []
        for i in range(12):
            hora_entry = tk.Entry(frame_hora_job, width=6)
            hora_entry.pack(side="left", padx=2)
            horas_vars.append(hora_entry)

        checkbox_var = tk.BooleanVar(value=False)
        checkbox_widget = tk.Checkbutton(frame_hora_job, text="Executar diariamente", variable=checkbox_var)
        checkbox_widget.pack(side="left", padx=(0, 5))

        frame_dados_job = ttk.Frame(frame_dados)
        frame_dados_job.pack(anchor="n", padx=10, pady=10, fill="x")

        # Nome job
        frame_nome_job = ttk.Frame(frame_dados_job)
        frame_nome_job.pack(anchor="n", padx=10, pady=10, fill="x")
        tk.Label(frame_nome_job, text="Nome JOB:").pack(side="left", padx=(0, 5))
        nome_job_var = tk.StringVar()
        nome_job_entry = tk.Entry(frame_nome_job, textvariable=nome_job_var, width=300)
        nome_job_entry.pack(side="left", padx=(0, 20))

        # Usuário job
        frame_usuario_job = ttk.Frame(frame_dados_job)
        frame_usuario_job.pack(anchor="n", padx=10, pady=10, fill="x")
        tk.Label(frame_usuario_job, text="Usuário JOB:").pack(side="left", padx=(0, 5))
        usuario_job_var = tk.StringVar()
        usuario_job_entry = tk.Entry(frame_usuario_job, textvariable=usuario_job_var, width=300)
        usuario_job_entry.pack(side="left", padx=(0, 20))

        # Caminho salvar job
        frame_caminho_job = ttk.Frame(frame_dados_job)
        frame_caminho_job.pack(anchor="n", padx=10, pady=10, fill="x")
        tk.Label(frame_caminho_job, text="Caminho salvar JOB:").pack(side="left", padx=(0, 5))
        caminho_salvar_job_var = tk.StringVar()
        caminho_salvar_job_entry = tk.Entry(frame_caminho_job, textvariable=caminho_salvar_job_var, width=300)
        caminho_salvar_job_entry.pack(side="left", padx=(0, 20))

        auto["hora_var"] = horas_vars
        auto["checkbox_var"] = checkbox_var
        auto["nome_job_var"] = nome_job_var
        auto["usuario_job_var"] = usuario_job_var
        auto["caminho_salvar_job_var"] = caminho_salvar_job_var
        auto["nome_job_entry"] = nome_job_entry
        auto["usuario_job_entry"] = usuario_job_entry
        auto["caminho_salvar_job_entry"] = caminho_salvar_job_entry
        auto["excel_input"] = None  # Agendar JOBs não usa ExcelInput

        self._registrar_widgets_editaveis(
            auto,
            *horas_vars,
            checkbox_widget,
            nome_job_entry,
            usuario_job_entry,
            caminho_salvar_job_entry,
        )

    def _criar_aba_eliminar_remessa(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de eliminação de remessa
        frame_principal_1 = ttk.Frame(frame_dados, border=1, relief="groove")
        frame_principal_1.pack(side="left", anchor="n", padx=4, pady=5, fill="y")

        frame_principal_2 = ttk.Frame(frame_dados, border=1)
        frame_principal_2.pack(side="left", anchor="n", padx=4, pady=5, fill="y")
        auto["frame_principal_2"] = frame_principal_2

        #----------------------------- Seção de horário e checkbox diário--------------------------
        frame_hora_checkbox_plant = ttk.Frame(frame_principal_1, border=1)
        frame_hora_checkbox_plant.pack(side="top", anchor="n", padx=7, pady=5, fill="y")

        frame_princ_hora_checkbox = ttk.Frame(frame_hora_checkbox_plant, border=1)
        frame_princ_hora_checkbox.pack(side="left", anchor="n", padx=7, pady=5, fill="y")

        frame_princ_plant = ttk.Frame(frame_hora_checkbox_plant, border=1)
        frame_princ_plant.pack(side="left", anchor="n", padx=7, pady=5, fill="y")

        tk.Label(frame_princ_hora_checkbox, text="Hora:").pack(side="top", padx=(2, 5))
        hora_var = tk.StringVar()
        hora_entry = tk.Entry(frame_princ_hora_checkbox, textvariable=hora_var, width=10)
        hora_entry.pack(side="top", padx=(2, 10), pady=(2, 2))

        checkbox_var = tk.BooleanVar(value=False)
        checkbox_widget = tk.Checkbutton(frame_princ_hora_checkbox, text="Executar diariamente", variable=checkbox_var)
        checkbox_widget.pack(side="top", padx=(2, 2), pady=(2, 20))

        tk.Label(frame_princ_plant, text="Plantas a eliminar:").pack(side="top", padx=(2, 10))
        plantas_eliminar_container, plantas_eliminar_widget = self._criar_texto_com_scroll_vertical(
            frame_princ_plant, height=5, width=6, wrap="word", relief="groove", borderwidth=2
        )
        plantas_eliminar_container.pack(side="top", padx=(2, 10), pady=(2, 20))
        self.plantas_eliminar = plantas_eliminar_widget

        #-------------------------- Seção de plantas, restrições e lojas--------------------------

        frame_restr_loj = ttk.Frame(frame_principal_1, border=1)
        frame_restr_loj.pack(side="top", anchor="n", padx=7, pady=5, fill="y")

        frame_restr = ttk.Frame(frame_restr_loj, border=1)
        frame_restr.pack(side="left", anchor="n", padx=7, pady=5, fill="y")

        frame_loj = ttk.Frame(frame_restr_loj, border=1)
        frame_loj.pack(side="left", anchor="n", padx=7, pady=5, fill="y")

        tk.Label(frame_restr, text="Restrições a poupar:").pack(side="top", padx=(2, 10))
        restricoes_container, restricoes_poupar_widget = self._criar_texto_com_scroll_vertical(
            frame_restr, height=5, width=6, wrap="word", relief="groove", borderwidth=2
        )
        restricoes_container.pack(side="top", padx=(2, 10), pady=(2, 20))
        self.restricoes_poupar = restricoes_poupar_widget

        tk.Label(frame_loj, text="Lojas/CDs a poupar:").pack(side="top", padx=(2, 10))
        lojas_container, lojas_poupar_widget = self._criar_texto_com_scroll_vertical(
            frame_loj, height=5, width=6, wrap="word", relief="groove", borderwidth=2
        )
        lojas_container.pack(side="top", padx=(2, 10), pady=(2, 20))
        self.lojas_poupar = lojas_poupar_widget

        frame_rem = ttk.Frame(frame_principal_1, border=1)
        frame_rem.pack(side="top", anchor="n", padx=7, pady=5, fill="y")

        tk.Label(frame_rem, text="Remessas a poupar:").pack(side="top", padx=(5, 10))
        remessas_container, remessas_poupar_widget = self._criar_texto_com_scroll_vertical(
            frame_rem, height=40, width=12, wrap="word", relief="groove", borderwidth=2
        )
        remessas_container.pack(side="top", fill="y", padx=(5, 10), pady=(2, 20))
        self.remessas_poupar = remessas_poupar_widget

        auto["hora_var"] = hora_var
        auto["checkbox_var"] = checkbox_var
        auto["planta_var"] = plantas_eliminar_widget
        auto["plantas_eliminar"] = plantas_eliminar_widget
        auto["restricoes_poupar"] = restricoes_poupar_widget
        auto["lojas_poupar"] = lojas_poupar_widget
        auto["remessas_poupar"] = remessas_poupar_widget

        # Adicionar ExcelInput
        tk.Label(frame_principal_2, text="Cole os dados aqui:").pack(anchor="n", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_principal_2,
            ("Planta", 7),
            ("Remessa", 11),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_principal_2)
        auto["excel_input"] = excel_input

        self._registrar_widgets_editaveis(auto, excel_input)

        self._registrar_widgets_editaveis(
            auto,
            hora_entry,
            checkbox_widget,
            plantas_eliminar_widget,
            restricoes_poupar_widget,
            lojas_poupar_widget,
            remessas_poupar_widget,
            excel_input,
        )

    def _criar_aba_processar_remessa(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de processamento de remessa
        frame_linha = ttk.Frame(frame_dados)
        frame_linha.pack(anchor="n", padx=10, pady=5, fill="x")

        tk.Label(frame_linha, text="Planta:").pack(side="left", padx=(0, 5))
        planta_var = tk.StringVar()
        planta_entry = tk.Entry(frame_linha, textvariable=planta_var, width=13)
        planta_entry.pack(side="left", padx=(0, 20))

        tk.Label(frame_linha, text="Hora:").pack(side="left", padx=(0, 5))
        hora_var = tk.StringVar()
        hora_entry = tk.Entry(frame_linha, textvariable=hora_var, width=10)
        hora_entry.pack(side="left", padx=(0, 20))

        checkbox_var = tk.BooleanVar(value=False)
        checkbox_widget = tk.Checkbutton(frame_linha, text="Executar diariamente", variable=checkbox_var)
        checkbox_widget.pack(side="left", padx=(0, 5))

        auto["planta_var"] = planta_var
        auto["hora_var"] = hora_var
        auto["checkbox_var"] = checkbox_var
        auto["planta_entry"] = planta_entry

        # Adicionar ExcelInput
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Remessa", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        self.excel_input_remessa = excel_input
        auto["excel_input"] = excel_input

        self._registrar_widgets_editaveis(
            auto,
            planta_entry,
            hora_entry,
            checkbox_widget,
            excel_input,
        )

    def _criar_aba_mapeamento(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de mapeamento
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Planta", 7),
            ("Item", 8),
            ("Classe", 6),
            ("Prio.", 6),
            ("Restr.", 7),
            ("Caixas", 7),
            ("Camadas", 7),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_remover_mapeamento(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de remoção de mapeamento (planta + item + classe)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Planta", 7),
            ("Item", 8),
            ("Classe", 6),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_alterar_prioridade(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de alteração de prioridade (planta + item + classe + prioridade)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Planta", 7),
            ("Item", 8),
            ("Classe", 6),
            ("Prior.", 6),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_alterar_restricao(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de alteração de restrição (planta + item + classe + restrição)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Planta", 7),
            ("Item", 8),
            ("Classe", 6),
            ("Restr.", 6),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_cativar_local(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de cativação de local (item + id local + qt mínima)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Item", 8),
            ("ID Local", 10),
            ("Qt. Min", 7),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_descativar_local(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de descativação de local (item + id local)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Item", 8),
            ("ID Local", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _criar_aba_alterar_ponto_minimo(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Cria a aba de alteração de ponto mínimo (item + id local + novo ponto)
        tk.Label(frame_dados, text="Cole os dados aqui:").pack(anchor="w", padx=10, pady=5)
        self._criar_guia_colunas_excel_input(
            frame_dados,
            ("Item", 8),
            ("ID Local", 10),
            ("Pt. Min", 7),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
            ("-", 10),
        )
        excel_input = self._criar_excel_input_com_scroll(frame_dados)
        auto["excel_input"] = excel_input
        self._registrar_widgets_editaveis(auto, excel_input)

    def _adicionar_logs_e_botao(self, frame_dados: tk.Widget, auto: Dict[str, Any]) -> None:
        # Adiciona a seção de logs em qualquer aba
        container = frame_dados
        logs_anchor = "w"
        logs_width = 150

        if auto["nome"].lower() == "eliminar remessa" and auto.get("frame_principal_2"):
            container = auto["frame_principal_2"]
            logs_anchor = "n"

        tk.Label(container, text="Logs:").pack(anchor=logs_anchor, padx=10, pady=5)
        log_container, log_area = self._criar_texto_com_scroll_vertical(
            container, width=logs_width, height=10, state="disabled"
        )
        log_container.pack(side="top", padx=10, pady=5)
        auto["log_area"] = log_area



    #----------------------------------------------------------------------
    #------------------------ EXECUÇÃO---------------------------------
    #----------------------------------------------------------------------
    def _executar_automacao(self, auto: Dict[str, Any], excel_input: Any, log_area: scrolledtext.ScrolledText) -> bool:
        # Executa a automação selecionada com validações
        nome = auto["nome"]
        modulo = auto["modulo"]
        tamanho_esperado = auto["tamanho_esperado"]
        planta = self._ler_campo(auto.get("planta_var"))
        agendamento_id = self._agendamento_selecionado_id if self._modo_form == "editar" else None
        
        # Verificar se hora_var é uma lista (múltiplos campos) ou um campo único
        hora_var_raw = auto.get("hora_var")
        if isinstance(hora_var_raw, list):
            # Lista de 12 campos - verificar se algum está preenchido
            hora_exec = None
            for campo in hora_var_raw:
                texto = self._ler_campo(campo)
                if texto:
                    hora_exec = True  # Marca como "tem algo preenchido"
                    break
        else:
            # Campo único (compatibilidade com código antigo)
            hora_exec = self._ler_campo(hora_var_raw)
        
        # Campos específicos de "Eliminar remessa"
        plantas_eliminar = self._ler_campo(auto.get("plantas_eliminar"))
        restricoes_poupar = self._ler_campo(auto.get("restricoes_poupar"))
        lojas_poupar = self._ler_campo(auto.get("lojas_poupar"))
        remessas_poupar_raw = self._ler_campo(auto.get("remessas_poupar"))
        if nome.lower() == "eliminar remessa":
            planta = plantas_eliminar
        
        # Processar remessas a poupar com padding
        remessas_poupar_processadas = self._processar_remessas_poupar(remessas_poupar_raw) if remessas_poupar_raw else None

        wms_usuario = self.usuario_var.get().strip()
        wms_senha = self.senha_var.get().strip()
        wms_caminho = self.wms_var.get().strip()
        if wms_caminho.startswith('"'):
            wms_caminho = wms_caminho[1:]
        if wms_caminho.endswith('"'):
            wms_caminho = wms_caminho[:-1]

        def log(msg):
            now = time.strftime("[%H:%M:%S]")
            log_area.config(state="normal")
            log_area.insert(tk.END, f"{now} {msg}\n")
            log_area.see(tk.END)
            log_area.config(state="disabled")

        self._limpar_log(log_area)

        # Validação de login
        # Agendar JOBs, Sistema de Apoio e RELEX não precisam de login WMS
        if self._nome_automacao_chave(nome) not in ("agendar jobs", "agendar sistema de apoio", "relex"):
            if not all([wms_usuario, wms_senha, wms_caminho]):
                log("[ERRO] Usuário, senha ou caminho WMS ausentes. Preencha antes de executar.")
                return False

        self._salvar_config()
        if nome.lower() == "eliminar remessa":
            self._atualizar_cache_campos_eliminar_remessa({
                "plantas_eliminar": plantas_eliminar or "",
                "restricoes_poupar": restricoes_poupar or "",
                "lojas_poupar": lojas_poupar or "",
            })

        # Função que executa a automação de fato
        def executar_agora():
            # Agendar JOBs, Sistema de Apoio e RELEX usam SAP/direto ou browser, não WMS
            if self._nome_automacao_chave(nome) not in ("agendar jobs", "agendar sistema de apoio", "relex"):
                if not self._abrir_janela_wms(log, wms_caminho, wms_usuario, wms_senha):
                    log("Automação abortada: janela WMS não encontrada.")
                    return

            log(f"Iniciando automação de {nome}...")
            self._registrar_inicio_execucao()

            modulo.logger = log
            # status_callback may be called as (idx, status) or (idx, status, value)
            def _status_cb(idx, status, value=None):
                if excel_input:
                    # Nesta automação, o valor é o item e a primeira coluna é a planta.
                    valor_busca = (
                        None
                        if self._nome_automacao_chave(nome) == "remover mapeamento"
                        else value
                    )
                    self.root.after(0, self._excel_status_update, excel_input, idx, status, valor_busca)

            modulo.status_callback = _status_cb
            def _captura_cb(remessas_capturadas):
                if nome == "Eliminar remessa" and excel_input:
                    self.root.after(0, self._adicionar_linhas_excel_input, excel_input, remessas_capturadas)
            def _restricoes_cb(remessas_atualizadas):
                if nome == "Eliminar remessa" and excel_input:
                    self.root.after(0, self._substituir_linhas_excel_input, excel_input, remessas_atualizadas)

            def _worker():
                tracker = None
                try:
                    # Agendar JOBs não usa dados Excel
                    if self._nome_automacao_chave(nome) == "agendar jobs":
                        nome_job = self._ler_campo(auto.get("nome_job_var"))
                        usuario_job = self._ler_campo(auto.get("usuario_job_var"))
                        caminho_salvar_job = self._ler_campo(auto.get("caminho_salvar_job_var"))
                        usuario_sap = self.usuario_sap_var.get().strip()
                        senha_sap = self.senha_sap_var.get().strip()
                        conexao_sap = self.conexao_sap_var.get().strip()
                        result = modulo.iniciar_automacao(nome_job, usuario_job, caminho_salvar_job, usuario_sap, senha_sap, conexao_sap, log)

                    else:
                        if nome.lower() == "relex":
                            result = modulo.iniciar_automacao(
                                self._ler_campo(auto.get("link_relex_var")),
                                self._ler_campo(auto.get("usuario_relex_var")),
                                self._ler_campo(auto.get("senha_relex_var")),
                                self._ler_campo(auto.get("caminho_salvar_relex_var")),
                                log_fn=log,
                            )
                        else:
                            if not excel_input:
                                raise RuntimeError("Excel input não encontrado para automação de dados.")
                            dados = excel_input.get_data()
                            log(f"Dados do Excel lidos: {len(dados)} linhas")

                            # Rastreador: registra o item em que parou e tira prints.
                            # So para automacoes que informam o status de cada linha.
                            automacoes_rastreadas = (
                                "eliminar remessa",
                                "mapeamento",
                                "remover mapeamento",
                                "alterar prioridade",
                                "alterar restricao",
                                "cativar local",
                                "descativar local",
                                "alterar ponto minimo",
                            )

                            if nome.lower() in automacoes_rastreadas:
                                tracker = ExecutionTracker(nome, len(dados), log_fn=log)
                                status_cb = tracker.envolver(_status_cb)
                            else:
                                status_cb = _status_cb

                            if nome == "Eliminar remessa":
                                # Eliminar remessa passa todos os parâmetros preenchidos
                                result = modulo.iniciar_automacao(
                                    data=dados,
                                    planta=planta,
                                    log_fn=log,
                                    plantas=plantas_eliminar,
                                    restricoes=restricoes_poupar,
                                    lojas=lojas_poupar,
                                    remessas=remessas_poupar_processadas,
                                    captura_callback=_captura_cb,
                                    restricoes_callback=_restricoes_cb,
                                    status_callback_fn=status_cb,
                                )
                                self._atualizar_remessa(result)
                            elif nome == "Processar Remessa":
                                result = modulo.iniciar_automacao(dados, planta)
                                self._atualizar_remessa(result)
                            elif nome.lower() in (
                                "mapeamento",
                                "remover mapeamento",
                                "alterar prioridade",
                                "alterar restricao",
                                "cativar local",
                                "descativar local",
                                "alterar ponto minimo",
                            ):
                                result = modulo.iniciar_automacao(dados, status_callback_fn=status_cb)
                            else:
                                result = modulo.iniciar_automacao(dados)

                            # Execução terminou sem exceção: print final e resumo
                            if tracker:
                                tracker.finalizar()

                except Exception as exc:
                    # Registra onde parou e tira o print antes de seguir
                    if tracker:
                        try:
                            tracker.finalizar(erro=exc)
                        except Exception:
                            pass
                    self.root.after(0, lambda e=exc: log(f"Erro na automação: {e}"))
                    result = False

                def _on_done():
                    log("Automação concluída com sucesso." if result else "Falha na automação.")
                    self._registrar_fim_execucao()

                self.root.after(0, _on_done)

            threading.Thread(target=_worker, daemon=True).start()

        # Função para validar dados antes de executar
        def validar_dados():
            # Valida dados conforme tipo de automação. Retorna True se válido
            # Agendar JOBs não precisa validar dados Excel
            if self._nome_automacao_chave(nome) == "agendar jobs":
                nome_job = self._ler_campo(auto.get("nome_job_var"))
                usuario_job = self._ler_campo(auto.get("usuario_job_var"))
                caminho_salvar_job = self._ler_campo(auto.get("caminho_salvar_job_var"))
                
                if not nome_job or not usuario_job or not caminho_salvar_job:
                    log("[ERRO] Nome JOB, Usuário JOB e Caminho salvar JOB são obrigatórios.")
                    return False
                
                try:
                    modulo.clear_stop()
                except Exception:
                    pass
                
                return True
            
            # Sistema de Apoio também não precisa validar dados Excel
            elif nome.lower() == "agendar sistema de apoio":
                sql_file = self._ler_campo(auto.get("sql_file_var"))
                output_dir = self._ler_campo(auto.get("output_dir_var"))
                output_name = self._ler_campo(auto.get("output_name_var"))
                
                if not all([sql_file, output_dir, output_name]):
                    log("[ERRO] Todos os campos são obrigatórios.")
                    return False
                
                return True
            elif nome.lower() == "relex":
                link_relex = self._ler_campo(auto.get("link_relex_var"))
                usuario_relex = self._ler_campo(auto.get("usuario_relex_var"))
                senha_relex = self._ler_campo(auto.get("senha_relex_var"))
                caminho_salvar_relex = self._ler_campo(auto.get("caminho_salvar_relex_var"))
                if not all([link_relex, usuario_relex, senha_relex, caminho_salvar_relex]):
                    log("[ERRO] Link, Usuário, Senha e Caminho salvar são obrigatórios para RELEX.")
                    return False
                return True
            
            # Para outras automações, validar dados Excel
            try:
                dados = excel_input.get_data()
                log(f"Dados do Excel lidos: {len(dados)} linhas")
            except Exception as e:
                log(f"[ERRO] Falha ao ler dados do Excel: {e}")
                return False

            # ============ Lógica de validação unificada ============

            if nome.lower() in ("eliminar remessa"):
                # Padrão: Dados Excel INPUT ou PLANTA são obrigatórios
                if dados:
                    # Se dados foram preenchidos, validar tamanho e ignorar planta/hora
                    if not modulo.verificar_tamanho_lista(dados, tamanho_esperado=tamanho_esperado):
                        log("[ERRO] Quantidade de colunas incorreta nos dados.")
                        return False
                else:
                    # Se dados não foram preenchidos, planta é obrigatória
                    if not planta:
                        log("[ERRO] Dados Excel ou Planta são obrigatórios.")
                        return False

            elif nome.lower() in ("processar remessa"):
                if not dados:
                    if not planta:
                        log("[ERRO] Nenhum dado nem planta fornecidos. Automação interrompida.")
                        return False

                if dados:
                    if not modulo.verificar_tamanho_lista(dados, tamanho_esperado=tamanho_esperado):
                        log("[ERRO] Quantidade de colunas incorreta nos dados.")
                        return False
                else:
                    if not modulo.verificar_tamanho_lista([], planta, tamanho_esperado=tamanho_esperado):
                        log("[ERRO] Planta inválida ou fora do tamanho esperado.")
                        return False

            elif nome.lower() in ("mapeamento", "remover mapeamento", "alterar prioridade", "alterar restricao", "cativar local", "descativar local", "alterar ponto minimo"):
                if not dados:
                    log("[ERRO] Nenhum dado encontrado para processar.")
                    return False
                if not modulo.verificar_tamanho_lista(dados, tamanho_esperado=tamanho_esperado):
                    log("[ERRO] Quantidade de colunas incorreta nos dados.")
                    return False

            try:
                modulo.clear_stop()
            except Exception:
                pass
            
            return True
        
        # Callback após animação: valida e executa
        def depois_animacao():
            # Executado após animação. Valida dados e executa automação
            if not validar_dados():
                return
            executar_agora()
        
        # FLUXO PRINCIPAL PARA "AGENDAR JOBS"
        if self._nome_automacao_chave(nome) == "agendar jobs":
            # Validar campos obrigatórios
            if not validar_dados():
                return False
            
            # Campos de dados são sempre obrigatórios
            nome_job = self._ler_campo(auto.get("nome_job_var"))
            usuario_job = self._ler_campo(auto.get("usuario_job_var"))
            caminho_salvar_job = self._ler_campo(auto.get("caminho_salvar_job_var"))
            
            if not all([nome_job, usuario_job, caminho_salvar_job]):
                log("[ERRO] Nome JOB, Usuário JOB e Caminho salvar JOB são obrigatórios.")
                return False
            
            # Verificar se é diário e se horário é obrigatório
            checkbox_diario = self._ler_campo(auto.get("checkbox_var"))
            
            if checkbox_diario and not hora_exec:
                log("[ERRO] Informe ao menos um minuto quando marcado 'Executar diariamente'.")
                return False
            
            # Se tem minuto → agendar; Se não tem minuto e não é diário → executar imediatamente
            if hora_exec:
                # AGENDAR para os minutos especificados
                try:
                    info_extra = {
                        "nome_job": nome_job,
                        "usuario_job": usuario_job,
                        "caminho_salvar_job": caminho_salvar_job,
                    }

                    # Criar agendamento (retorna tupla: agendamento, erro, eh_novo)
                    agendamento, erro, eh_novo = self._criar_agendamento(
                        auto,
                        nome,
                        agendamento_id=agendamento_id,
                        **info_extra
                    )
                    
                    if erro:
                        log(f"[ERRO] {erro}")
                        return False
                    
                    if not agendamento:
                        log("Agendamento não foi realizado - duplicata detectada")
                        return False

                    ag_id = agendamento.id
                    horas_str = self._formatar_horarios_agendamento(agendamento)

                    # Log de criação com sucesso
                    log(f"[Agendamento #{ag_id}] Agenda configurada: {horas_str}")

                    # Iniciar monitor de agendamentos se não estiver rodando
                    if not self._monitor_thread:
                        self._monitor_thread = self.gerenciador_agendamentos.iniciar_monitor_agendamentos(timeout=10)

                    return True

                except Exception as e:
                    log(f"[ERRO] Falha ao agendar JOB: {e}")
                    return False
            else:
                # SEM MINUTOS e NÃO é diário → EXECUTAR IMEDIATAMENTE
                log("Nenhum minuto especificado. Executando imediatamente...")
                self._animar_execucao_log(log_area, callback=depois_animacao)
                return True
        
        # FLUXO PRINCIPAL PARA "AGENDAR SISTEMA DE APOIO"
        if nome.lower() == "agendar sistema de apoio":
            # Validar campos obrigatórios
            if not validar_dados():
                return False
            
            # Campos de dados são sempre obrigatórios
            sql_file = self._ler_campo(auto.get("sql_file_var"))
            output_dir = self._ler_campo(auto.get("output_dir_var"))
            output_name = self._ler_campo(auto.get("output_name_var"))
            
            if not all([sql_file, output_dir, output_name]):
                log("[ERRO] Todos os campos são obrigatórios (SQL, Diretório de Saída, Nome do Arquivo).")
                return False
            
            # Verificar se é diário e se horário é obrigatório
            checkbox_diario = self._ler_campo(auto.get("checkbox_var"))
            
            if checkbox_diario and not hora_exec:
                log("[ERRO] Horário é obrigatório quando marcado 'Executar diariamente'.")
                return False
            
            # Se tem horário → agendar; Se não tem horário e não é diário → executar imediatamente
            if hora_exec:
                # AGENDAR para o horário especificado
                try:
                    info_extra = {
                        "sql_file": sql_file,
                        "output_dir": output_dir,
                        "output_name": output_name,
                    }

                    # Criar agendamento (retorna tupla: agendamento, erro, eh_novo)
                    agendamento, erro, eh_novo = self._criar_agendamento(
                        auto,
                        nome,
                        agendamento_id=agendamento_id,
                        **info_extra
                    )
                    
                    if erro:
                        log(f"[ERRO] {erro}")
                        return False
                    
                    if not agendamento:
                        log("Agendamento não foi realizado - duplicata detectada")
                        return False

                    ag_id = agendamento.id
                    horas_str = self._formatar_horarios_agendamento(agendamento)

                    # Log de criação com sucesso
                    log(f"[Agendamento #{ag_id}] Horas agendadas: {horas_str}")

                    # Iniciar monitor de agendamentos se não estiver rodando
                    if not self._monitor_thread:
                        self._monitor_thread = self.gerenciador_agendamentos.iniciar_monitor_agendamentos(timeout=10)

                    return True

                except Exception as e:
                    log(f"[ERRO] Falha ao agendar Sistema de Apoio: {e}")
                    return False
            else:
                # SEM HORÁRIO e NÃO é diário → EXECUTAR IMEDIATAMENTE
                log("Nenhum horário especificado. Executando imediatamente...")
                self._animar_execucao_log(log_area, callback=depois_animacao)
                return True
            
        # FLUXO PRINCIPAL PARA "ELIMINAR REMESSA"
        if nome.lower() in ("eliminar remessa"):
            try:
                dados = excel_input.get_data()
            except Exception as e:
                self.log_app(f"[ERRO] Falha ao ler dados do Excel: {e}", "ERRO")
                return False

            # Se dados Excel foram preenchidos, ignorar hora e planta, executar imediatamente
            if dados:
                self._animar_execucao_log(log_area, callback=depois_animacao)
                return True
            
            # Se dados não foram preenchidos, planta é obrigatória para prosseguir
            if not plantas_eliminar:
                log("[ERRO] Dados Excel ou 'Plantas a eliminar' são obrigatórios.")
                return False
            
            # Planta foi preenchida - agora verificar hora
            if hora_exec:
                # Hora preenchida → agendar
                try:
                    remessas_raw = self._ler_campo(auto.get("remessas_poupar"))
                    remessas_processadas = self._processar_remessas_poupar(remessas_raw)
                    info_extra = {
                        "plantas": self._normalizar_texto_multilinha(self._ler_campo(auto.get("plantas_eliminar"))),
                        "restricoes": self._normalizar_texto_multilinha(self._ler_campo(auto.get("restricoes_poupar"))),
                        "lojas": self._normalizar_texto_multilinha(self._ler_campo(auto.get("lojas_poupar"))),
                        "remessas": remessas_processadas,
                    }

                    # Validar dados ANTES de agendar
                    if not validar_dados():
                        return False

                    # Criar agendamento (retorna tupla: agendamento, erro, eh_novo)
                    agendamento, erro, eh_novo = self._criar_agendamento(
                        auto,
                        nome,
                        agendamento_id=agendamento_id,
                        **info_extra
                    )
                    
                    if erro:
                        log(f"[ERRO] {erro}")
                        return False
                    
                    if not agendamento:
                        log("Agendamento não foi realizado - duplicata detectada")
                        return False

                    ag_id = agendamento.id
                    horas_str = self._formatar_horarios_agendamento(agendamento)

                    # Log de criação com sucesso
                    log(f"[Agendamento #{ag_id}] Horas agendadas: {horas_str}")

                    # Iniciar monitor de agendamentos se não estiver rodando
                    if not self._monitor_thread:
                        self._monitor_thread = self.gerenciador_agendamentos.iniciar_monitor_agendamentos(timeout=10)

                    return True

                except Exception as e:
                    log(f"[ERRO] Horário inválido: {e}")
                    return False
            else:
                # Hora não preenchida → executar imediatamente
                self._animar_execucao_log(log_area, callback=depois_animacao)
                return True
            
        # FLUXO PRINCIPAL: Com horário → agendar; Sem horário → executar imediatamente (para outras automações)
        if hora_exec:
            try:
                # Preparar informações específicas conforme tipo de automação
                info_extra = {}
                nome_auto = nome.lower()

                if self._nome_automacao_chave(nome_auto) == "agendar jobs":
                    info_extra = {
                        "nome_job": self._ler_campo(auto.get("nome_job_var")),
                        "usuario_job": self._ler_campo(auto.get("usuario_job_var")),
                        "caminho_salvar_job": self._ler_campo(auto.get("caminho_salvar_job_var")),
                    }
                elif "processar remessa" in nome_auto:
                    dados = []
                    if excel_input:
                        dados = excel_input.get_data()
                    info_extra = {"planta": planta, "dados": dados}
                elif nome_auto == "relex":
                    info_extra = {
                        "link": self._ler_campo(auto.get("link_relex_var")),
                        "usuario": self._ler_campo(auto.get("usuario_relex_var")),
                        "senha": self._ler_campo(auto.get("senha_relex_var")),
                        "caminho_salvar": self._ler_campo(auto.get("caminho_salvar_relex_var")),
                    }
                elif "mapeamento" in nome_auto:
                    dados = []
                    if excel_input:
                        dados = excel_input.get_data()
                    info_extra = {"tipo": "mapeamento", "dados": dados}

                # Validar dados ANTES de agendar
                if not validar_dados():
                    return False

                # Criar agendamento (retorna tupla: agendamento, erro, eh_novo)
                agendamento, erro, eh_novo = self._criar_agendamento(
                    auto,
                    nome,
                    agendamento_id=agendamento_id,
                    **info_extra
                )
                
                if erro:
                    log(f"[ERRO] {erro}")
                    return False
                
                if not agendamento:
                    log("Agendamento não foi realizado - duplicata detectada")
                    return False

                ag_id = agendamento.id
                horas_str = self._formatar_horarios_agendamento(agendamento)

                # Log de criação com sucesso
                log(f"[Agendamento #{ag_id}] Horas agendadas: {horas_str}")

                # Iniciar monitor de agendamentos se não estiver rodando
                if not self._monitor_thread:
                    self._monitor_thread = self.gerenciador_agendamentos.iniciar_monitor_agendamentos(timeout=10)

                return True

            except Exception as e:
                log(f"[ERRO] Horário inválido: {e}")
                return False
        
        # Sem horário especificado → executar imediatamente com validação
        self._animar_execucao_log(log_area, callback=depois_animacao)
        return True

    #----------------------------------------------------------------------
    #------------------------ UTILITÁRIOS------------------------------
    #----------------------------------------------------------------------
    def _adicionar_linhas_excel_input(self, excel_input: Optional[ExcelInput], linhas: list) -> None:
        # Consolida linhas em um ExcelInput, evitando duplicatas
        try:
            if not excel_input:
                print("[ERRO] ExcelInput não encontrado.")
                return
            if not linhas:
                print("[INFO] Nenhuma nova remessa capturada.")
                return

            estado_original = str(excel_input.cget("state"))
            if estado_original != "normal":
                excel_input.config(state="normal")

            linhas_novas = []
            for linha in linhas:
                if isinstance(linha, (list, tuple)):
                    texto = "\t".join(map(str, linha)).strip()
                else:
                    texto = str(linha).strip()

                if texto:
                    linhas_novas.append(texto)

            texto_atual = excel_input.get("1.0", tk.END).strip().splitlines()
            linhas_existentes = {linha.strip() for linha in texto_atual if linha.strip()}
            novas_unicas = [linha for linha in linhas_novas if linha not in linhas_existentes]

            if not novas_unicas:
                print("[INFO] Nenhuma linha nova para adicionar.")
                return

            for linha in novas_unicas:
                excel_input.insert(tk.END, linha + "\n")

            excel_input.see(tk.END)
            if estado_original != "normal":
                excel_input.config(state=estado_original)
            print(f"[INFO] {len(novas_unicas)} novas remessas adicionadas com sucesso.")
        except Exception as e:
            print(f"[ERRO] Falha ao atualizar remessa: {e}")

    def _substituir_linhas_excel_input(self, excel_input: Optional[ExcelInput], linhas: list) -> None:
        # Substitui todo o conteúdo do ExcelInput pela lista informada
        try:
            if not excel_input:
                print("[ERRO] ExcelInput nÃ£o encontrado.")
                return

            estado_original = str(excel_input.cget("state"))
            if estado_original != "normal":
                excel_input.config(state="normal")

            texto_linhas = []
            for linha in linhas or []:
                if isinstance(linha, (list, tuple)):
                    texto = "\t".join(map(str, linha)).strip()
                else:
                    texto = str(linha).strip()
                if texto:
                    texto_linhas.append(texto)

            novo_texto = "\n".join(texto_linhas)
            excel_input.replace(novo_texto)
            if estado_original != "normal":
                excel_input.config(state=estado_original)
        except Exception as e:
            print(f"[ERRO] Falha ao substituir remessa: {e}")

    def _atualizar_remessa(self, nova_remessa: list) -> None:
        """
        Atualiza o campo 'Processar Remessa' com as novas linhas capturadas.
        - Remove duplicatas
        - Adiciona apenas linhas inéditas
        - Mantém a formatação correta (sem tabular números)
        """
        try:
            if not hasattr(self, "excel_input_remessa"):
                for tab in self.notebook.tabs():
                    if "Remessa" in self.notebook.tab(tab, "text"):
                        frame = self.notebook.nametowidget(tab)
                        for child in frame.winfo_children():
                            if isinstance(child, ExcelInput):
                                self.excel_input_remessa = child
                                break
                        break

            self._adicionar_linhas_excel_input(getattr(self, "excel_input_remessa", None), nova_remessa)
        except Exception as e:
            print(f"[ERRO] Falha ao atualizar remessa: {e}")

#------------------------------------ Iniciar WMS------------------------------------
    
    def _iniciar_wms(self, wms_caminho: str, usuario: str, senha: str, timeout: int = 300) -> bool:
        if not os.path.exists(wms_caminho):
            raise FileNotFoundError(f"Caminho inválido: {wms_caminho}")

        print(f"[INFO] Iniciando WMS a partir de: {wms_caminho}")
        self.abrir_jnlp(wms_caminho)
        time.sleep(2)

        # focar na janela

        return self._fluxo_wms(usuario, senha, timeout)

    def abrir_jnlp(self, caminho_jnlp: str) -> None:
        if not os.path.exists(caminho_jnlp):
            raise FileNotFoundError(f"Arquivo JNLP não encontrado: {caminho_jnlp}")

        try:
            os.startfile(caminho_jnlp)
        except AttributeError:
            subprocess.Popen([caminho_jnlp], shell=True)
        except Exception as e:
            raise RuntimeError(f"Falha ao abrir JNLP: {e}") from e


    def _detectar_janelas_do_wms(self):
        titulos = gw.getAllTitles()
        lower = [t.lower() for t in titulos]

        return {
            "update": any("java update necessário" in t for t in lower),
            "seguranca": any("advertência de segurança" in t for t in lower),
            "login": any("wms americanas - login" in t for t in lower),
            "logado": any("wms americanas (usu" in t for t in lower),
        }


    def _handle_advertencia(self):
        print("[INFO] Confirmando ADVERTÊNCIA DE SEGURANÇA...")
        time.sleep(0.5)

        opcoes_textos = {"advert": ["risco", "aceito", "eu aceito","nao mostrar novamente"]}

        resultado = aguardar_textos(
            "WMMS",
            opcoes_textos,
            timeout=20,
            log_fn=print,
            ordem_blocos=[18,17,13],
            deslocamento_x=0,
            n_clicks=1,
            clicar=True,
            modo="auto"
        )

        if not resultado:
            raise RuntimeError("Tela de segurança não confirmada")

        pyautogui.press("enter")


    def _handle_update(self):
        print("[INFO] Confirmando JAVA UPDATE NECESSÁRIO...")
        time.sleep(0.5)

        for _ in range(3):
            pyautogui.press("tab")
            time.sleep(0.2)

        pyautogui.press("space")

        pyautogui.press("enter")

    def _handle_login(self, usuario, senha):
        print("[OK] Tela de login: preenchendo credenciais...")

        janela = focus_manager(["wms americanas - login"])

        if not janela:
            raise RuntimeError("Janela de login não encontrada")
        time.sleep(0.3)

        copiar_para_clipboard(usuario)
        focus_manager(["wms americanas - login"])
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        pyautogui.press("tab")
        time.sleep(0.3)

        copiar_para_clipboard(senha)
        focus_manager(["wms americanas - login"])
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        pyautogui.press("enter")
        time.sleep(0.3)

        pyautogui.press("enter")
        time.sleep(2)

    def _fluxo_wms(self, usuario: str, senha: str, timeout: int = 300) -> bool:
        estado = EstadoWMS.INIT
        inicio = time.time()
        login_realizado = False

        while time.time() - inicio < timeout:
            janelas = self._detectar_janelas_do_wms()

            if janelas["logado"]:
                estado = EstadoWMS.LOGADO
                maximize_manager(["wms americanas (usu"])
            elif janelas["update"]:
                estado = EstadoWMS.UPDATE
            elif janelas["seguranca"]:
                estado = EstadoWMS.SEGURANCA
            elif janelas["login"]:
                maximize_manager(["wms americanas - login"])
                estado = EstadoWMS.LOGIN
            else:
                estado = EstadoWMS.AGUARDANDO

            try:
                if estado == EstadoWMS.LOGADO:
                    print("[OK] WMS logado detectado.")
                    return True

                if estado == EstadoWMS.UPDATE:
                    self._handle_update()
                    time.sleep(1)
                    continue

                if estado == EstadoWMS.SEGURANCA:
                    self._handle_advertencia()
                    time.sleep(1)
                    continue

                if estado == EstadoWMS.LOGIN:
                    if not login_realizado:
                        self._handle_login(usuario, senha)
                        login_realizado = True
                    time.sleep(2)
                    continue

                time.sleep(1)
            except Exception as e:
                print(f"[ERRO] Falha no estado {estado.name}: {e}")
                estado = EstadoWMS.ERRO
                break

        if estado == EstadoWMS.ERRO:
            return False

        print("[ERRO] Timeout aguardando inicialização do WMS.")
        return False

    def _abrir_janela_wms(self, log: callable, caminho_wms: str, usuario: str, senha: str) -> bool:
        try:
            log("Buscando janela do WMS...")

            janelas = self._detectar_janelas_do_wms()
            if janelas["logado"]:
                focus_manager(["wms americanas (usu"])
                maximize_manager(["wms americanas (usu"])
                log("Janela WMS já está aberta.")
                return True

            return self._iniciar_wms(caminho_wms, usuario, senha)
        except Exception as e:
            log(f"[ERRO] Falha ao iniciar o WMS: {e}")
            return False
















#----------------------------------------------------------------------

    def _alternar_tema(self) -> None:
        # Alterna entre claro e escuro e atualiza o rotulo do botao
        self.theme.alternar()
        self._aplicar_escala_interface(self.root.winfo_width(), forcar=True)
        try:
            self._btn_tema.config(text=self.theme.rotulo_botao())
        except Exception:
            pass

    def _limpar_log(self, log_area: scrolledtext.ScrolledText) -> None:
        # Limpa o conteúdo de um widget ScrolledText
        log_area.config(state="normal")
        log_area.delete(1.0, tk.END)
        log_area.config(state="disabled")

    def _excel_status_update(self, excel_input: Any, row_index: int, status: str, value: Optional[Any] = None) -> bool:
        """Robusta atualização de status:
        - Se `value` for fornecido, procura a linha que contenha esse valor na primeira coluna e atualiza o status nessa linha.
        - Caso contrário, usa `row_index` como fallback e garante que o valor não seja perdido (insere antes do status, se necessário).
        """
        try:
            lines = excel_input.get("1.0", tk.END).splitlines()
            # busca por valor (primeira coluna)
            if value:
                for i, line in enumerate(lines):
                    first = line.split('\t')[0].strip() if line else ""
                    if first == str(value).strip():
                        excel_input.set_row_status(i + 1, status)
                        return True

            # fallback: atualiza pela posição
            updated = excel_input.set_row_status(row_index, status)

            # se um `value` foi fornecido e a linha ficou sem o valor, insere-o
            if value and updated:
                # re-obter a linha
                lines = excel_input.get("1.0", tk.END).splitlines()
                idx = row_index - 1
                if 0 <= idx < len(lines):
                    parts = lines[idx].split('\t')
                    first = parts[0].strip() if parts else ""
                    possible_statuses = {"Sucesso", "Duplicado", "Não encontrado", "Timeout", "Parcialmente Sucesso", "Em progresso"}
                    if not first or first in possible_statuses:
                        # substitui a primeira coluna pelo valor
                        parts[0:1] = [str(value).strip()]
                        lines[idx] = '\t'.join(parts)
                        new_text = '\n'.join(lines) + '\n'
                        excel_input.delete("1.0", tk.END)
                        excel_input.insert("1.0", new_text)
                        excel_input.see(f"{idx+1}.0")
            return updated
        except Exception:
            return False

    def _animar_execucao_log(self, log_area: scrolledtext.ScrolledText, mensagem: str = "Executando automação", ciclos: int = 6, delay: int = 200, callback: Optional[callable] = None) -> None:
        def animar(i=0):
            if i == 0:
                log_area.config(state="normal")
                log_area.insert(tk.END, f"{mensagem}\n")
                log_area.config(state="disabled")

            pontos = "." * ((i % 3) + 1)
            log_area.config(state="normal")
            log_area.delete("end-2l", "end-1l")
            log_area.insert(tk.END, f"{mensagem}{pontos}\n")
            log_area.see(tk.END)
            log_area.config(state="disabled")

            if i < ciclos - 1:
                self.root.after(delay, animar, i + 1)
            else:
                # Animação finalizada -> só aqui chama o callback
                if callback:
                    self.root.after(0, callback)

        animar()

    #----------------------------------------------------------------------
    #------------------- HOTKEY E PARADA DE EXECUÇÃO-----------------
    #----------------------------------------------------------------------
    def _registrar_hotkey_global(self) -> None:
        # Registra o hotkey global CapsLock para parar automações
        if kb:
            try:
                self._kb_hotkey = kb.add_hotkey('caps lock', lambda: self.root.after(0, self._request_stop))
            except Exception as exc:
                self._kb_hotkey = None
                self.root.bind_all('<Caps_Lock>', lambda e: self._request_stop())
                self.root.bind_all('<KeyPress-Caps_Lock>', lambda e: self._request_stop())
                self.log_app(f"[WARN] Falha ao registrar hotkey global CapsLock. Usando fallback de janela. Erro: {exc}")
        else:
            self.root.bind_all('<Caps_Lock>', lambda e: self._request_stop())
            self.root.bind_all('<KeyPress-Caps_Lock>', lambda e: self._request_stop())

    def _request_stop(self) -> None:
        # Solicita parada de todas as automações em execução
        for auto in self.automacoes:
            try:
                auto["modulo"].request_stop()
            except Exception:
                pass
        self.log_app("Parada solicitada (CapsLock)")

    #----------------------------------------------------------------------
    #------------ CONFIGURAÇÃO DE CALLBACKS DE AGENDAMENTOS------------
    #----------------------------------------------------------------------
    def _executar_agendamento(self, agendamento: Agendamento) -> bool:
        """
            Executa um agendamento com toda a lógica necessária.
            Retorna True se executou com sucesso, False caso contrário.
        """
        try:
            # Encontrar a automação e módulo correspondente
            auto = None
            for a in self.automacoes:
                if self._nome_automacao_chave(a["nome"]) == self._nome_automacao_chave(agendamento.nome_automacao):
                    auto = a
                    break
            
            if not auto:
                self.log_app(f"[Agendamento #{agendamento.id}] Automação '{agendamento.nome_automacao}' não encontrada", "ERRO")
                return False
            
            modulo = auto["modulo"]
            nome = auto["nome"]
            tamanho_esperado = auto["tamanho_esperado"]
            excel_input = auto.get("excel_input")
            nome_auto = nome.lower()
            payload = agendamento.payload
            
            usuario = self.usuario_var.get().strip()
            senha = self.senha_var.get().strip()
            wms_caminho = self.wms_var.get().strip()
            if wms_caminho.startswith('"'):
                wms_caminho = wms_caminho[1:]
            if wms_caminho.endswith('"'):
                wms_caminho = wms_caminho[:-1]
            
            # Agendar JOBs, Sistema de Apoio e RELEX não precisam de login WMS
            if self._nome_automacao_chave(nome_auto) not in ("agendar jobs", "agendar sistema de apoio", "relex"):
                # Validar login WMS
                if not all([usuario, senha, wms_caminho]):
                    self.log_app(f"[Agendamento #{agendamento.id}] Credenciais WMS ausentes", "ERRO")
                    return False
                
                # Abrir janela WMS
                if not self._abrir_janela_wms(self.log_app, wms_caminho, usuario, senha):
                    self.log_app(f"[Agendamento #{agendamento.id}] Janela WMS não encontrada", "ERRO")
                    return False
            
            self.log_app(f"[Agendamento #{agendamento.id}] Iniciando execução de {nome}...")
            
            # Preparar módulo
            modulo.logger = self.log_app
            modulo.status_callback = lambda idx, status, value=None: None  # Callback dummy para agendamentos
            
            # Executar de acordo com o tipo
            try:
                if self._nome_automacao_chave(nome_auto) == "agendar jobs":
                    # Agendar JOBs não usa dados Excel
                    nome_job = payload.get("nome_job", "")
                    usuario_job = payload.get("usuario_job", "")
                    caminho_salvar_job = payload.get("caminho_salvar_job", "")
                    usuario_sap = self.usuario_sap_var.get().strip()
                    senha_sap = self.senha_sap_var.get().strip()
                    conexao_sap = self.conexao_sap_var.get().strip()
                    result = modulo.iniciar_automacao(nome_job, usuario_job, caminho_salvar_job, usuario_sap, senha_sap, conexao_sap, self.log_app)
                
                else:
                    # Outras automações requerem ExcelInput
                    if not excel_input:
                        self.log_app(f"[Agendamento #{agendamento.id}] Excel input não encontrado", "ERRO")
                        return False
                    
                    dados = payload.get("dados")
                    if dados is None:
                        dados = []
                    
                    if "eliminar remessa" in nome_auto:
                        # Eliminar remessa passa todos os parâmetros preenchidos
                        def _captura_cb(remessas_capturadas):
                            self.root.after(0, self._adicionar_linhas_excel_input, excel_input, remessas_capturadas)

                        def _restricoes_cb(remessas_atualizadas):
                            self.root.after(0, self._substituir_linhas_excel_input, excel_input, remessas_atualizadas)

                        result = modulo.iniciar_automacao(
                            data=dados,
                            log_fn=self.log_app,
                            planta=payload.get("planta"),
                            plantas=payload.get("plantas"),
                            restricoes=payload.get("restricoes"),
                            lojas=payload.get("lojas"),
                            remessas=payload.get("remessas"),
                            captura_callback=_captura_cb,
                            restricoes_callback=_restricoes_cb,
                            status_callback_fn=modulo.status_callback,
                        )
                        self._atualizar_remessa(result)
                    elif "processar remessa" in nome_auto:
                        planta = payload.get("planta", "")
                        result = modulo.iniciar_automacao(dados, planta)
                        self._atualizar_remessa(result)
                    elif "mapeamento" in nome_auto:
                        result = modulo.iniciar_automacao(dados, status_callback_fn=modulo.status_callback)
                    elif "relex" in nome_auto:
                        result = modulo.iniciar_automacao(
                            payload.get("link", ""),
                            payload.get("usuario", ""),
                            payload.get("senha", ""),
                            payload.get("caminho_salvar", ""),
                            log_fn=self.log_app,
                        )
                    else:
                        result = modulo.iniciar_automacao(dados)
            except Exception as e:
                self.log_app(f"[Agendamento #{agendamento.id}] Erro durante execução: {e}", "ERRO")
                return False
            
            return bool(result)
        except Exception as e:
            self.log_app(f"[Agendamento #{agendamento.id}] Erro ao processar agendamento: {e}", "ERRO")
            return False
        finally:
            agendamento._evento_execucao_concluida.set()

    def _configurar_callbacks_agendamentos(self) -> None:
        # Configura os callbacks para execução de agendamentos
        def callback_antes_execucao(agendamento: Agendamento) -> None:
            # Chamado antes de executar um agendamento
            # Resetar evento para permitir sincronização da próxima execução
            agendamento._evento_execucao_concluida.clear()
            
            self.log_app(f"[Agendamento #{agendamento.id}] Executando automação: {agendamento.nome_automacao}")
            self._atualizar_exibicao_agendamentos()
            # Executar o agendamento em uma thread separada
            threading.Thread(target=lambda: self._executar_agendamento(agendamento), daemon=True).start()

        def callback_depois_execucao(agendamento: Agendamento, sucesso: bool) -> None:
            # Chamado após executar um agendamento
            if sucesso:
                self.log_app(f"[Agendamento #{agendamento.id}] Concluído com sucesso")
            else:
                self.log_app(f"[Agendamento #{agendamento.id}] Falhou", "AVISO")
            
            # Processa pós-execução (recorrência ou remoção)
            self._processar_agendamento_executado(agendamento.id, agendamento)

        def callback_verificar_monitoramento() -> bool:
            # Verifica se o monitoramento de agendamentos está ativo
            return self._monitoramento_ativo

        self.gerenciador_agendamentos.registrar_callbacks(
            antes_execucao=callback_antes_execucao,
            depois_execucao=callback_depois_execucao,
            verificar_monitoramento=callback_verificar_monitoramento,
            atualizar_visualizacao=lambda: self.root.after(0, self._atualizar_exibicao_agendamentos)
        )


def main():
    # Informa o DPI ao Windows antes de criar a janela
    ativar_dpi_awareness()

    def fit_window_to_work_area(root: tk.Tk) -> None:
        # Ajusta a janela para ocupar a area util da tela
        try:
            spi_get_work_area = 0x0030
            rect = wintypes.RECT()
            ok = ctypes.windll.user32.SystemParametersInfoW(
                spi_get_work_area,
                0,
                ctypes.byref(rect),
                0,
            )
            if ok:
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                root.geometry(f"{width}x{height}+{rect.left}+{rect.top}")
                return
        except Exception:
            pass

        root.update_idletasks()
        width, height = root.maxsize()
        root.geometry(f"{width}x{height}+0+0")

    root = tk.Tk()
    try:
        root.state("zoomed")
    except Exception:
        fit_window_to_work_area(root)

    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
