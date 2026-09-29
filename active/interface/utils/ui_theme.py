"""
Tema (claro/escuro) e dimensionamento responsivo do Auto WMS.

Paleta escura inspirada no Windows 11 (Mica dark) com acento
azul-marinho. A paleta clara mantém o verde institucional original.

Uso no main_window.py:

    from interface.utils.ui_theme import ThemeManager, ajustar_janela

    ajustar_janela(self.root, proporcao=0.9, minimo=(1300, 500))
    self.theme = ThemeManager(self.root)
    ...
    self.theme.aplicar()   # na ULTIMA linha do __init__
"""

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk


ARQUIVO_PREFERENCIA = Path.home() / ".autowms_tema.json"


PALETAS = {
    "claro": {
        # Fundos
        "bg": "#ECF4E8",
        "bg_painel": "#ECF4E8",
        "bg_conteudo": "#F4F8F2",
        # Texto
        "fg": "#1f1f1f",
        "fg_suave": "#5a5a5a",
        # Campos
        "campo_bg": "#FFFFFF",
        "campo_fg": "#1f1f1f",
        "texto_bg": "#FFFFFF",
        "texto_fg": "#1a1a1a",
        "log_bg": "#FFFFFF",
        "log_fg": "#1a1a1a",
        # Acento (azul-marinho)
        "acento": "#1F3A63",
        "acento_hover": "#2B4E82",
        "acento_fg": "#FFFFFF",
        # Seleção
        "selecao_bg": "#1F3A63",
        "selecao_fg": "#FFFFFF",
        # Estrutura
        "borda": "#C3D4BB",
        "borda_sutil": "#D8E4D2",
        # Abas
        "aba_bg": "#DCEBD4",
        "aba_ativa_bg": "#ECF4E8",
        "aba_fg": "#1f1f1f",
        "aba_ativa_fg": "#1F3A63",
        # Botões
        "botao_bg": "#E3EFDD",
        "botao_fg": "#1f1f1f",
        "botao_hover": "#D2E5C8",
        # Scrollbar
        "scroll_bg": "#C9D8C1",
        "scroll_trough": "#ECF4E8",
        # Cabeçalho do ExcelInput
        "header_bg": "#D9EDD1",
        "header_fg": "#1f1f1f",
        # Status
        "sucesso": "#2E7D32",
        "sucesso_bg": "#90EE90",
        "erro": "#C62828",
        "erro_bg": "#FFB6C6",
        "aviso": "#EF6C00",
    },
    "escuro": {
        # Fundos - Windows 11 dark (Mica)
        "bg": "#202020",
        "bg_painel": "#272727",
        "bg_conteudo": "#1C1C1C",
        # Texto
        "fg": "#FFFFFF",
        "fg_suave": "#C5C5C5",
        # Campos
        "campo_bg": "#2D2D2D",
        "campo_fg": "#FFFFFF",
        "texto_bg": "#1C1C1C",
        "texto_fg": "#E4E4E4",
        "log_bg": "#181818",
        "log_fg": "#D0D0D0",
        # Acento (azul-marinho)
        "acento": "#2B4E82",
        "acento_hover": "#3A63A0",
        "acento_fg": "#FFFFFF",
        # Seleção
        "selecao_bg": "#2B4E82",
        "selecao_fg": "#FFFFFF",
        # Estrutura
        "borda": "#3D3D3D",
        "borda_sutil": "#323232",
        # Abas
        "aba_bg": "#272727",
        "aba_ativa_bg": "#2B4E82",
        "aba_fg": "#C5C5C5",
        "aba_ativa_fg": "#FFFFFF",
        # Botões
        "botao_bg": "#323232",
        "botao_fg": "#FFFFFF",
        "botao_hover": "#3A63A0",
        # Scrollbar
        "scroll_bg": "#4A4A4A",
        "scroll_trough": "#202020",
        # Cabeçalho do ExcelInput
        "header_bg": "#2B4E82",
        "header_fg": "#FFFFFF",
        # Status
        "sucesso": "#6CCB70",
        "sucesso_bg": "#2E5E32",
        "erro": "#E57373",
        "erro_bg": "#6E2B2B",
        "aviso": "#FFB74D",
    },
}


# =================== DIMENSIONAMENTO RESPONSIVO =================== #

def ativar_dpi_awareness():
    """
    Informa ao Windows que a aplicação entende escalonamento de DPI.

    Deve ser chamada ANTES de criar a janela Tk, senão em monitores
    com escala 125%/150% tudo fica borrado.
    """
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


def ajustar_janela(root, proporcao=0.9, minimo=(1300, 500), centralizar=True):
    """
    Dimensiona a janela conforme a resolução do monitor atual.

    Retorna (largura, altura) aplicadas.
    """
    root.update_idletasks()

    tela_w = root.winfo_screenwidth()
    tela_h = root.winfo_screenheight()

    largura = max(int(tela_w * proporcao), minimo[0])
    altura = max(int(tela_h * proporcao), minimo[1])

    largura = min(largura, tela_w - 40)
    altura = min(altura, tela_h - 80)

    if centralizar:
        x = max((tela_w - largura) // 2, 0)
        y = max((tela_h - altura) // 3, 0)
        root.geometry(f"{largura}x{altura}+{x}+{y}")
    else:
        root.geometry(f"{largura}x{altura}")

    root.minsize(minimo[0], minimo[1])

    return largura, altura


def escala_fonte(root, base=9):
    """Tamanho de fonte proporcional à altura da tela."""
    altura = root.winfo_screenheight()

    if altura >= 2000:
        return base + 3
    if altura >= 1400:
        return base + 2
    if altura >= 1050:
        return base
    return max(base - 1, 7)

def escala_largura(root, base=1920):
    """
    Fator de escala das larguras conforme a resolução horizontal.

    Retorna um multiplicador entre 0.55 e 1.0 para ajustar a largura
    (em caracteres) de Entry e Button em telas menores.
    """
    largura = root.winfo_screenwidth()
    return max(0.55, min(1.0, largura / base))


def largura_campo(root, largura_base, minimo=8):
    """
    Converte uma largura de campo para a escala da tela atual.

    Ex.: em 1366x768 um campo de 40 vira 28.
    """
    escalado = int(largura_base * escala_largura(root))
    return max(escalado, minimo)


# =================== GERENCIADOR DE TEMA =================== #

class ThemeManager:
    """
    Aplica e alterna entre os temas claro e escuro.

    Sobrescreve inclusive os estilos "AutoWMS.*" e os option_add
    definidos no main_window, que de outra forma manteriam o verde
    fixo mesmo no modo escuro.
    """

    def __init__(self, root, tema=None):
        self.root = root
        self.style = ttk.Style(root)

        self._registrados = []
        self._callbacks = []

        self.tema = tema or self._carregar_preferencia()
        self.fonte_base = escala_fonte(root)

    # ------------------------------------------------------------- #

    @property
    def cores(self):
        return PALETAS[self.tema]

    @property
    def escuro(self):
        return self.tema == "escuro"

    # ------------------------------------------------------------- #

    def _carregar_preferencia(self):
        try:
            if ARQUIVO_PREFERENCIA.exists():
                dados = json.loads(
                    ARQUIVO_PREFERENCIA.read_text(encoding="utf-8")
                )
                tema = dados.get("tema")
                if tema in PALETAS:
                    return tema
        except Exception:
            pass

        return "claro"

    def _salvar_preferencia(self):
        try:
            ARQUIVO_PREFERENCIA.write_text(
                json.dumps({"tema": self.tema}),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------- #

    def registrar(self, widget, tipo="padrao"):
        """
        Registra um widget tk clássico para receber as cores do tema.

        tipo: "padrao" | "campo" | "texto" | "log" | "header"
        """
        self._registrados.append((widget, tipo))
        self._pintar_widget(widget, tipo)

    def ao_trocar(self, callback):
        self._callbacks.append(callback)

    # ------------------------------------------------------------- #

    def _aplicar_option_add(self):
        """
        Sobrescreve os defaults de widgets tk clássicos.

        O main_window define option_add com o verde fixo no __init__;
        como esses valores só são lidos na criação de cada widget,
        precisamos redefini-los a cada troca de tema.
        """
        c = self.cores

        self.root.option_add("*Background", c["bg"])
        self.root.option_add("*Foreground", c["fg"])

        self.root.option_add("*Label.Background", c["bg"])
        self.root.option_add("*Label.Foreground", c["fg"])

        self.root.option_add("*Checkbutton.Background", c["bg"])
        self.root.option_add("*Checkbutton.Foreground", c["fg"])
        self.root.option_add("*Checkbutton.ActiveBackground", c["bg"])
        self.root.option_add("*Checkbutton.ActiveForeground", c["fg"])
        self.root.option_add("*Checkbutton.selectColor", c["campo_bg"])

        self.root.option_add("*Entry.Background", c["campo_bg"])
        self.root.option_add("*Entry.Foreground", c["campo_fg"])
        self.root.option_add("*Entry.insertBackground", c["campo_fg"])

        self.root.option_add("*Button.Background", c["botao_bg"])
        self.root.option_add("*Button.Foreground", c["botao_fg"])
        self.root.option_add("*Button.ActiveBackground", c["acento_hover"])
        self.root.option_add("*Button.ActiveForeground", c["acento_fg"])

        self.root.option_add("*Text.Background", c["texto_bg"])
        self.root.option_add("*Text.Foreground", c["texto_fg"])

        self.root.option_add("*Scrollbar.Background", c["scroll_bg"])
        self.root.option_add("*Scrollbar.ActiveBackground", c["acento"])
        self.root.option_add("*Scrollbar.TroughColor", c["scroll_trough"])
        self.root.option_add("*Scrollbar.HighlightBackground", c["bg"])
        self.root.option_add("*Scrollbar.HighlightColor", c["bg"])
        self.root.option_add("*Scrollbar.BorderWidth", 0)

    def _pintar_widget(self, widget, tipo):
        c = self.cores

        try:
            if tipo == "campo":
                widget.configure(
                    bg=c["campo_bg"],
                    fg=c["campo_fg"],
                    insertbackground=c["campo_fg"],
                    highlightbackground=c["borda"],
                    highlightcolor=c["acento"],
                )

            elif tipo == "texto":
                widget.configure(
                    bg=c["texto_bg"],
                    fg=c["texto_fg"],
                    insertbackground=c["texto_fg"],
                    selectbackground=c["selecao_bg"],
                    selectforeground=c["selecao_fg"],
                    highlightbackground=c["borda"],
                )

            elif tipo == "log":
                widget.configure(
                    bg=c["log_bg"],
                    fg=c["log_fg"],
                    insertbackground=c["log_fg"],
                    selectbackground=c["selecao_bg"],
                    highlightbackground=c["borda"],
                )

            elif tipo == "header":
                widget.configure(
                    bg=c["header_bg"],
                    fg=c["header_fg"],
                )

            else:
                widget.configure(bg=c["bg"])
                try:
                    widget.configure(fg=c["fg"])
                except tk.TclError:
                    pass

        except tk.TclError:
            pass

    def _aplicar_ttk(self):
        c = self.cores
        f = self.fonte_base

        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(
            ".",
            background=c["bg"],
            foreground=c["fg"],
            fieldbackground=c["campo_bg"],
            bordercolor=c["borda"],
            darkcolor=c["bg"],
            lightcolor=c["bg"],
            troughcolor=c["scroll_trough"],
            font=("Segoe UI", f),
        )

        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TLabel", background=c["bg"], foreground=c["fg"])

        self.style.configure(
            "TButton",
            background=c["botao_bg"],
            foreground=c["botao_fg"],
            bordercolor=c["borda"],
            focuscolor=c["acento"],
            padding=(10, 5),
            relief="flat",
        )
        self.style.map(
            "TButton",
            background=[("active", c["acento_hover"]), ("pressed", c["acento"])],
            foreground=[("active", c["acento_fg"]), ("pressed", c["acento_fg"])],
        )

        self.style.configure(
            "TEntry",
            fieldbackground=c["campo_bg"],
            foreground=c["campo_fg"],
            insertcolor=c["campo_fg"],
            bordercolor=c["borda"],
            lightcolor=c["borda"],
            darkcolor=c["borda"],
        )
        self.style.map(
            "TEntry",
            bordercolor=[("focus", c["acento"])],
            lightcolor=[("focus", c["acento"])],
        )

        # --- Notebook padrão e o "AutoWMS" usado pelo main_window --- #
        for nome in ("TNotebook", "AutoWMS.TNotebook"):
            self.style.configure(
                nome,
                background=c["bg"],
                bordercolor=c["borda"],
                borderwidth=0,
                tabmargins=(2, 4, 2, 0),
            )

        for nome in ("TNotebook.Tab", "AutoWMS.TNotebook.Tab"):
            self.style.configure(
                nome,
                background=c["aba_bg"],
                foreground=c["aba_fg"],
                bordercolor=c["borda"],
                padding=(14, 7),
                font=("Segoe UI", f),
            )
            self.style.map(
                nome,
                background=[
                    ("selected", c["aba_ativa_bg"]),
                    ("active", c["botao_hover"]),
                ],
                foreground=[
                    ("selected", c["aba_ativa_fg"]),
                    ("active", c["fg"]),
                ],
                expand=[("selected", [1, 1, 1, 0])],
            )

        # Corpo das abas usado pelo main_window.
        self.style.configure(
            "AutoWMS.TabBody.TFrame",
            background=c["bg"],
        )

        # --- Treeview --- #
        self.style.configure(
            "Treeview",
            background=c["campo_bg"],
            fieldbackground=c["campo_bg"],
            foreground=c["fg"],
            bordercolor=c["borda"],
            rowheight=int(f * 2.4),
        )
        self.style.configure(
            "Treeview.Heading",
            background=c["aba_bg"],
            foreground=c["fg"],
            bordercolor=c["borda"],
            relief="flat",
            font=("Segoe UI", f, "bold"),
        )
        self.style.map(
            "Treeview",
            background=[("selected", c["selecao_bg"])],
            foreground=[("selected", c["selecao_fg"])],
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", c["botao_hover"])],
        )

        # --- LabelFrame --- #
        self.style.configure(
            "TLabelframe",
            background=c["bg"],
            foreground=c["fg"],
            bordercolor=c["borda"],
            lightcolor=c["borda"],
            darkcolor=c["borda"],
        )
        self.style.configure(
            "TLabelframe.Label",
            background=c["bg"],
            foreground=c["fg"],
            font=("Segoe UI", f),
        )

        # --- Scrollbars (inclui os nomes usados no main_window) --- #
        for nome in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
            self.style.configure(
                nome,
                background=c["scroll_bg"],
                troughcolor=c["scroll_trough"],
                bordercolor=c["bg"],
                lightcolor=c["bg"],
                darkcolor=c["bg"],
                arrowcolor=c["fg"],
                relief="flat",
                borderwidth=0,
                gripcount=0,
            )
            self.style.map(
                nome,
                background=[("active", c["acento"]), ("pressed", c["acento_hover"])],
                arrowcolor=[("active", c["acento_fg"])],
            )

        self.style.configure("TSeparator", background=c["borda"])
        self.style.configure(
            "TCheckbutton",
            background=c["bg"],
            foreground=c["fg"],
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", c["bg"])],
            foreground=[("active", c["fg"])],
        )

    def _pintar_recursivo(self, widget):
        """Percorre a árvore aplicando cores nos widgets tk clássicos."""
        c = self.cores

        try:
            classe = widget.winfo_class()
        except tk.TclError:
            return

        try:
            if classe in ("Frame", "Labelframe", "Toplevel", "Tk"):
                widget.configure(bg=c["bg"])

            elif classe == "Label":
                # Preserva cabeçalhos do ExcelInput (relief groove).
                try:
                    if str(widget.cget("relief")) == "groove":
                        widget.configure(
                            bg=c["header_bg"],
                            fg=c["header_fg"],
                        )
                    else:
                        widget.configure(bg=c["bg"], fg=c["fg"])
                except tk.TclError:
                    widget.configure(bg=c["bg"], fg=c["fg"])

            elif classe == "Button":
                # Botões com cor própria (monitoramento) são preservados.
                if not getattr(widget, "_cor_fixa", False):
                    widget.configure(
                        bg=c["botao_bg"],
                        fg=c["botao_fg"],
                        activebackground=c["acento_hover"],
                        activeforeground=c["acento_fg"],
                        relief="flat",
                        borderwidth=1,
                        highlightbackground=c["borda"],
                    )

            elif classe == "Checkbutton":
                widget.configure(
                    bg=c["bg"],
                    fg=c["fg"],
                    activebackground=c["bg"],
                    activeforeground=c["fg"],
                    selectcolor=c["campo_bg"],
                )

            elif classe == "Entry":
                self._pintar_widget(widget, "campo")

            elif classe in ("Text", "Listbox"):
                # Logs ficam desabilitados; usa a paleta de log.
                try:
                    estado = str(widget.cget("state"))
                except tk.TclError:
                    estado = "normal"

                self._pintar_widget(
                    widget,
                    "log" if estado == "disabled" else "texto",
                )

            elif classe == "Scrollbar":
                widget.configure(
                    bg=c["scroll_bg"],
                    activebackground=c["acento"],
                    troughcolor=c["scroll_trough"],
                    highlightbackground=c["bg"],
                    borderwidth=0,
                )

        except tk.TclError:
            pass

        for filho in widget.winfo_children():
            self._pintar_recursivo(filho)

    # ------------------------------------------------------------- #

    def aplicar(self):
        """Aplica o tema atual em toda a janela."""
        self._aplicar_option_add()
        self._aplicar_ttk()

        try:
            self.root.configure(bg=self.cores["bg"])
        except tk.TclError:
            pass

        self._pintar_recursivo(self.root)

        for widget, tipo in list(self._registrados):
            try:
                widget.winfo_exists()
            except tk.TclError:
                self._registrados.remove((widget, tipo))
                continue

            self._pintar_widget(widget, tipo)

        for callback in self._callbacks:
            try:
                callback(self.tema)
            except Exception:
                pass

    def alternar(self):
        """Troca entre claro e escuro, salvando a preferência."""
        self.tema = "escuro" if self.tema == "claro" else "claro"

        self.aplicar()
        self._salvar_preferencia()

        return self.tema

    def rotulo_botao(self):
        return "☀ Claro" if self.escuro else "🌙 Escuro"

    # ------------------------------------------------------------- #

    def cor(self, chave):
        """Acesso direto a uma cor da paleta atual."""
        return self.cores.get(chave, self.cores["bg"])

    def marcar_cor_fixa(self, widget):
        """
        Marca um botão para NÃO ser repintado pelo tema.

        Use em botões com cor semântica própria, como o de
        monitoramento (verde "Em execução" / vermelho "Parado").
        """
        try:
            widget._cor_fixa = True
        except Exception:
            pass
