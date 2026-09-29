import win32gui

def enum_windows_callback(hwnd, windows):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if title:  # ignora janelas sem título
            windows.append((hwnd, title))

def listar_janelas_sap():
    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    sap_windows = []
    for hwnd, title in windows:
        # Ajuste os filtros conforme aparece no seu SAP
        if "java update necessário" in title.lower():
            sap_windows.append((hwnd, title))

    return sap_windows


if __name__ == "__main__":
    janelas = listar_janelas_sap()

    if not janelas:
        print("Nenhuma janela SAP encontrada.")
    else:
        print("Janelas SAP encontradas:\n")
        for i, (hwnd, title) in enumerate(janelas, 1):
            print(f"{i}. HWND: {hwnd} | Título: {title}")