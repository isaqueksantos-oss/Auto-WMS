import tkinter as tk
import pandas as pd
from io import StringIO


class ExcelInput(tk.Text):
    """
    Campo que aceita colar grids do Excel.
    - Permite múltiplas colagens (acrescenta ao final se não houver seleção)
    - Substitui corretamente o conteúdo selecionado (Ctrl+V)
    - Atualiza status de cada linha individualmente
    """

    def __init__(self, parent):
        super().__init__(parent, wrap="none", height=20, undo=True)
        self.configure(font="TkFixedFont")
        # Bind de colagem (Excel/Windows/Linux)
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Control-V>", self._on_paste)
        self.bind("<<Paste>>", self._on_paste)

    # ----------------------------------------------------------------------
    # -------------------------- COLAGEM -----------------------------------
    # ----------------------------------------------------------------------
    def _on_paste(self, event=None):
        """Cola conteúdo do clipboard (como no Excel)."""
        try:
            raw = self.clipboard_get().strip()
        except tk.TclError:
            return "break"

        if not raw:
            return "break"

        # Normaliza separadores (\r\n, etc)
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")

        # Se houver texto selecionado → substituir
        if self.tag_ranges("sel"):
            self.delete("sel.first", "sel.last")
            insert_pos = "insert"
        else:
            # Se não houver seleção, inserir na posição do cursor
            insert_pos = self.index(tk.INSERT)

        self.insert(insert_pos, raw + "\n")
        self.see(tk.END)
        return "break"

    # ----------------------------------------------------------------------
    # -------------------------- LEITURA -----------------------------------
    # ----------------------------------------------------------------------
    def get_data(self):
        """Retorna os dados colados como lista de listas."""
        text = self.get("1.0", tk.END).strip()
        if not text:
            return []

        # tenta ler como CSV, fallback para ';'
        try:
            df = pd.read_csv(StringIO(text), sep="\t", header=None, dtype=str)
        except Exception:
            df = pd.read_csv(StringIO(text), sep=";", header=None, dtype=str)

        # mantém strings exatas (não converte números em dígitos separados)
        return df.values.tolist()

    # ----------------------------------------------------------------------
    # ------------------------ STATUS DE LINHA ------------------------------
    # ----------------------------------------------------------------------
    def set_row_status(self, row_index, status):
        """
        Atualiza ou adiciona uma coluna de status na linha indicada.
        row_index é 1-based.
        """
        lines = self.get("1.0", tk.END).splitlines()
        abs_index = row_index - 1
        if abs_index < 0 or abs_index >= len(lines):
            return False

        parts = lines[abs_index].rstrip().split('\t')
        possible_statuses = {
            "Sucesso", "Duplicado", "Não encontrado",
            "Timeout", "Parcialmente Sucesso", "Em progresso"
        }

        if parts and parts[-1] in possible_statuses:
            parts[-1] = status
        else:
            parts.append(status)

        lines[abs_index] = '\t'.join(parts)
        new_text = '\n'.join(lines) + '\n'

        self.delete("1.0", tk.END)
        self.insert("1.0", new_text)
        self.see(f"{abs_index + 1}.0")
        return True

    # ----------------------------------------------------------------------
    # ---------------------------- REPLACE ---------------------------------
    # ----------------------------------------------------------------------
    def replace(self, new_text):
        """Substitui todo o conteúdo do campo por um novo texto."""
        self.delete("1.0", tk.END)
        self.insert("1.0", new_text.strip() + "\n")
        self.see(tk.END)
