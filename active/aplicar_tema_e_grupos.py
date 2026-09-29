"""
Aplica no main_window.py:
  1. Correcao do __init__ (ordem do ajustar_janela / ThemeManager)
  2. Mover theme.aplicar() para o fim do __init__
  3. Correcao da funcao main() (remove o '...' e o tk.Tk() duplicado)
  4. Botao de alternancia claro/escuro + metodo _alternar_tema
  5. Agrupamento das abas por transacao (WMMA0020 / WMMA0031)

Uso (a partir da pasta 'active'):
    ..\\python.exe aplicar_tema_e_grupos.py

O script cria backup, valida a sintaxe e restaura tudo se algo falhar.
"""

import ast
import shutil
import sys
from pathlib import Path


ALVO = Path("interface/main_window.py")
BACKUP = Path("interface/main_window.py.bak2")


# ---------------------------------------------------------------- #
# 1. __init__ : ordem correta
# ---------------------------------------------------------------- #

INIT_ANTIGO = '''        # Inicializa a janela principal da aplicação
        ajustar_janela(self.root, proporcao=0.85, minimo=(1100, 700))
        self.theme = ThemeManager(self.root)
        self.root = root
        self.root.title(WINDOWS_CONFIG["title"])
        self.root.resizable(*([WINDOWS_CONFIG["resizable"]] * 2))
        self.root.minsize(WINDOWS_CONFIG["min_width"], WINDOWS_CONFIG["min_height"])'''

INIT_NOVO = '''        # Inicializa a janela principal da aplicação
        self.root = root
        self.root.title(WINDOWS_CONFIG["title"])
        self.root.resizable(*([WINDOWS_CONFIG["resizable"]] * 2))
        # Dimensiona conforme a resolucao do monitor atual
        ajustar_janela(
            self.root,
            proporcao=0.9,
            minimo=(WINDOWS_CONFIG["min_width"], WINDOWS_CONFIG["min_height"]),
        )
        self.theme = ThemeManager(self.root)'''


# ---------------------------------------------------------------- #
# 2. theme.aplicar() : remover do meio, colocar no fim
# ---------------------------------------------------------------- #

APLICAR_MEIO_ANTIGO = '''        self.theme.aplicar()
        # Criar frames principais'''

APLICAR_MEIO_NOVO = '''        # Criar frames principais'''

APLICAR_FIM_ANTIGO = '''        # Atualizar exibição com agendamentos carregados do JSON
        self._atualizar_exibicao_agendamentos()'''

APLICAR_FIM_NOVO = '''        # Atualizar exibição com agendamentos carregados do JSON
        self._atualizar_exibicao_agendamentos()

        # Aplica o tema depois que todos os widgets ja existem
        self.theme.aplicar()'''


# ---------------------------------------------------------------- #
# 3. Botao de tema no frame de login
# ---------------------------------------------------------------- #

BOTAO_ANTIGO = '''        self.conexao_sap_var = self._criar_campo_entrada(frame, "Conexão:", width=20)'''

BOTAO_NOVO = '''        self.conexao_sap_var = self._criar_campo_entrada(frame, "Conexão:", width=20)

        # Alternancia entre tema claro e escuro
        self._btn_tema = tk.Button(
            frame,
            text=self.theme.rotulo_botao(),
            width=10,
            command=self._alternar_tema,
        )
        self._btn_tema.pack(side="right", padx=5)'''


# ---------------------------------------------------------------- #
# 4. Metodo _alternar_tema (inserido antes de _limpar_log)
# ---------------------------------------------------------------- #

METODO_TEMA = '''    def _alternar_tema(self) -> None:
        # Alterna entre claro e escuro e atualiza o rotulo do botao
        self.theme.alternar()
        try:
            self._btn_tema.config(text=self.theme.rotulo_botao())
        except Exception:
            pass

'''

MARCADOR_TEMA = "    def _limpar_log(self, log_area: scrolledtext.ScrolledText) -> None:"


# ---------------------------------------------------------------- #
# 5. Agrupamento das abas
# ---------------------------------------------------------------- #

GRUPOS_TABS = [
    ('{"nome": "Mapeamento", "modulo": wmma0020_mapeamento, "tamanho_esperado": 7}',
     '{"nome": "Mapeamento", "modulo": wmma0020_mapeamento, "tamanho_esperado": 7, "grupo": "WMMA0020"}'),
    ('{"nome": "Remover mapeamento", "modulo": wmma0020_remover_mapeamento, "tamanho_esperado": 3}',
     '{"nome": "Remover mapeamento", "modulo": wmma0020_remover_mapeamento, "tamanho_esperado": 3, "grupo": "WMMA0020"}'),
    ('{"nome": "Alterar prioridade", "modulo": wmma0020_alterar_prioridade, "tamanho_esperado": 4}',
     '{"nome": "Alterar prioridade", "modulo": wmma0020_alterar_prioridade, "tamanho_esperado": 4, "grupo": "WMMA0020"}'),
    ('{"nome": "Alterar restricao", "modulo": wmma0020_alterar_restricao, "tamanho_esperado": 4}',
     '{"nome": "Alterar restricao", "modulo": wmma0020_alterar_restricao, "tamanho_esperado": 4, "grupo": "WMMA0020"}'),
    ('{"nome": "Cativar local", "modulo": wmma0031_cativar, "tamanho_esperado": 3}',
     '{"nome": "Cativar local", "modulo": wmma0031_cativar, "tamanho_esperado": 3, "grupo": "WMMA0031"}'),
    ('{"nome": "Descativar local", "modulo": wmma0031_descativar, "tamanho_esperado": 2}',
     '{"nome": "Descativar local", "modulo": wmma0031_descativar, "tamanho_esperado": 2, "grupo": "WMMA0031"}'),
    ('{"nome": "Alterar ponto minimo", "modulo": wmma0031_alterar_ponto_minimo, "tamanho_esperado": 3}',
     '{"nome": "Alterar ponto minimo", "modulo": wmma0031_alterar_ponto_minimo, "tamanho_esperado": 3, "grupo": "WMMA0031"}'),
]

CACHE_GRUPOS_ANTIGO = '''        self.automacoes = TABS_CONFIG.copy()
        for auto in self.automacoes:
            self._criar_aba_automacao(auto)'''

CACHE_GRUPOS_NOVO = '''        # Notebooks internos, um por transacao agrupada
        self._grupos = {}

        self.automacoes = TABS_CONFIG.copy()
        for auto in self.automacoes:
            self._criar_aba_automacao(auto)'''

CRIAR_ABA_ANTIGO = '''        nome = auto["nome"].lower()
        frame_dados = ttk.Frame(self.notebook, style="AutoWMS.TabBody.TFrame")
        self.notebook.add(frame_dados, text=auto["nome"])
        auto["frame"] = frame_dados'''

CRIAR_ABA_NOVO = '''        nome = auto["nome"].lower()
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
        auto["frame"] = frame_dados'''

OBTER_AUTO_ANTIGO = '''            frame = self.notebook.nametowidget(tab_id)
            for auto in self.automacoes:
                if auto.get("frame") == frame:
                    return auto'''

OBTER_AUTO_NOVO = '''            frame = self.notebook.nametowidget(tab_id)

            # Se a aba selecionada for um grupo, desce para a aba interna
            for interno in getattr(self, "_grupos", {}).values():
                if interno.winfo_parent() == str(frame):
                    sub_id = interno.select()
                    if sub_id:
                        frame = interno.nametowidget(sub_id)
                    break

            for auto in self.automacoes:
                if auto.get("frame") == frame:
                    return auto'''

SELECT_TREE_ANTIGO = '''                    if auto.get("frame"):
                        # Sinalizar que a mudança de aba foi por seleção na treeview
                        self._mudanca_aba_por_selecao_tree = True
                        self.notebook.select(auto["frame"])'''

SELECT_TREE_NOVO = '''                    if auto.get("frame"):
                        # Sinalizar que a mudança de aba foi por seleção na treeview
                        self._mudanca_aba_por_selecao_tree = True

                        grupo_auto = auto.get("grupo")
                        if grupo_auto and grupo_auto in getattr(self, "_grupos", {}):
                            interno = self._grupos[grupo_auto]
                            self.notebook.select(interno.winfo_parent())
                            interno.select(auto["frame"])
                        else:
                            self.notebook.select(auto["frame"])'''


EDICOES = [
    ("1. __init__ (ordem do ajustar_janela)", INIT_ANTIGO, INIT_NOVO),
    ("2a. remover theme.aplicar() do meio", APLICAR_MEIO_ANTIGO, APLICAR_MEIO_NOVO),
    ("2b. theme.aplicar() no fim do __init__", APLICAR_FIM_ANTIGO, APLICAR_FIM_NOVO),
    ("3. botao de tema", BOTAO_ANTIGO, BOTAO_NOVO),
    ("5a. cache de grupos", CACHE_GRUPOS_ANTIGO, CACHE_GRUPOS_NOVO),
    ("5b. criacao de abas agrupadas", CRIAR_ABA_ANTIGO, CRIAR_ABA_NOVO),
    ("5c. _obter_auto_ativo", OBTER_AUTO_ANTIGO, OBTER_AUTO_NOVO),
    ("5d. selecao pela treeview", SELECT_TREE_ANTIGO, SELECT_TREE_NOVO),
]


def corrigir_main(texto: str) -> tuple:
    """Reescreve a funcao main() a partir do 'def main():'."""
    marcador = "def main():"
    pos = texto.find(marcador)

    if pos == -1:
        return texto, False

    main_nova = '''def main():
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
'''

    return texto[:pos] + main_nova, True


def main() -> int:
    if not ALVO.exists():
        print(f"[ERRO] Arquivo nao encontrado: {ALVO.resolve()}")
        print("       Execute este script a partir da pasta 'active'.")
        return 1

    texto_original = ALVO.read_text(encoding="utf-8")
    texto = texto_original

    shutil.copy2(ALVO, BACKUP)
    print(f"[OK] Backup criado em {BACKUP}")

    falhas = []

    for descricao, antigo, novo in EDICOES:
        if novo in texto:
            print(f"[SKIP] {descricao} (ja aplicada)")
            continue

        ocorrencias = texto.count(antigo)

        if ocorrencias == 0:
            falhas.append(f"{descricao}: trecho nao encontrado")
            print(f"[FALHA] {descricao}: trecho nao encontrado")
            continue

        if ocorrencias > 1:
            falhas.append(f"{descricao}: {ocorrencias} ocorrencias (ambiguo)")
            print(f"[FALHA] {descricao}: {ocorrencias} ocorrencias")
            continue

        texto = texto.replace(antigo, novo, 1)
        print(f"[OK] {descricao}")

    # TABS_CONFIG: adiciona a chave "grupo"
    for antigo, novo in GRUPOS_TABS:
        if novo in texto:
            continue
        if texto.count(antigo) == 1:
            texto = texto.replace(antigo, novo, 1)
        else:
            falhas.append(f"TABS_CONFIG: {antigo[:45]}...")
    print("[OK] 5. TABS_CONFIG com grupos")

    # Metodo _alternar_tema
    if "_alternar_tema" in texto_original:
        print("[SKIP] 4. metodo _alternar_tema (ja existe)")
    elif texto.count(MARCADOR_TEMA) == 1:
        texto = texto.replace(MARCADOR_TEMA, METODO_TEMA + MARCADOR_TEMA, 1)
        print("[OK] 4. metodo _alternar_tema")
    else:
        falhas.append("4. metodo _alternar_tema: marcador nao encontrado")
        print("[FALHA] 4. metodo _alternar_tema")

    # Funcao main()
    texto, ok_main = corrigir_main(texto)
    if ok_main:
        print("[OK] 6. funcao main() corrigida")
    else:
        falhas.append("6. funcao main(): 'def main():' nao encontrado")
        print("[FALHA] 6. funcao main()")

    if falhas:
        shutil.copy2(BACKUP, ALVO)
        print("\n[ABORTADO] Arquivo restaurado a partir do backup.")
        print("Pendencias:")
        for f in falhas:
            print(f"  - {f}")
        return 1

    try:
        ast.parse(texto)
    except SyntaxError as exc:
        print(f"\n[ERRO] Sintaxe invalida apos as edicoes: {exc}")
        print("[ABORTADO] Nenhuma alteracao foi gravada.")
        return 1

    ALVO.write_text(texto, encoding="utf-8")

    print("\n[SUCESSO] main_window.py atualizado e validado.")
    print("Feche e abra o Auto WMS.")
    print(f"Para desfazer: copie {BACKUP} sobre {ALVO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
