import os
import socket
import keyring
import json
import pyautogui
from time import strftime
from pathlib import Path
from typing import Tuple, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = BASE_DIR / "interface" / "utils" / "config_global.json"
CONFIG_ELIM_DEM_PATH = BASE_DIR / "interface" / "utils" / "config_eliminar_dem.json"
SERVICE_NAME = "AutoWMS"

def salvar_config(usuario, senha, caminho_wms, link_relex=None, caminho_salvar_relex=None):
    """Salva o caminho do WMS e RELEX em JSON e as credenciais no cofre do Windows."""
    # salva caminho no JSON
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "caminho_wms": caminho_wms,
                "link_relex": link_relex or "",
                "caminho_salvar_relex": caminho_salvar_relex or "",
            },
            f,
            indent=4,
        )

    # salva credenciais no cofre seguro do Windows
    keyring.set_password(SERVICE_NAME, "usuario", usuario)
    keyring.set_password(SERVICE_NAME, "senha", senha)


def carregar_config():
    """Carrega caminho do JSON e credenciais do cofre."""
    usuario = keyring.get_password(SERVICE_NAME, "usuario")
    senha = keyring.get_password(SERVICE_NAME, "senha")

    caminho_wms = None
    link_relex = None
    caminho_salvar_relex = None
    plantas_eliminar = None
    restricoes_poupar = None
    lojas_poupar = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                caminho_wms = data.get("caminho_wms")
                link_relex = data.get("link_relex")
                caminho_salvar_relex = data.get("caminho_salvar_relex")
        except Exception:
            pass
    if os.path.exists(CONFIG_ELIM_DEM_PATH):
        try:
            with open(CONFIG_ELIM_DEM_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # file may contain specific keys for elimination config
                caminho_wms = caminho_wms or data.get("caminho_wms")
                plantas_eliminar = data.get("plantas_eliminar")
                restricoes_poupar = data.get("restricoes_poupar")
                lojas_poupar = data.get("lojas_poupar")
        except Exception:
            pass

    return (
        usuario,
        senha,
        caminho_wms,
        link_relex,
        caminho_salvar_relex,
        plantas_eliminar,
        restricoes_poupar,
        lojas_poupar,
    )


def limpar_config():
    """Remove tudo (para reset ou debug)."""
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)

    try:
        keyring.delete_password(SERVICE_NAME, "usuario")
        keyring.delete_password(SERVICE_NAME, "senha")
    except keyring.errors.PasswordDeleteError:
        pass


'-=-=-=-=-=-=-=-=-=-=-=-=-=-=- SALVAR CONFIGURAÇÕES DA TELA -=-=-=-=-=-=-=-=-=-=-=-=-=-=-'



HISTORICO_FILE = BASE_DIR / "interface" / "utils" / "coords_config.json"

class ElementRegistry:
    def __init__(self, path: Optional[str] = None):
        self.hostname = socket.gethostname()
        self.path = Path(path) if path else Path(HISTORICO_FILE)
        self._data = self._load()
        self._ensure_host_structure()

    # -------------------- CORE -------------------- #

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("[WARN] Arquivo JSON corrompido, recriando estrutura.")
        return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def _ensure_host_structure(self):
        if self.hostname not in self._data:
            w, h = pyautogui.size()
            self._data[self.hostname] = {
                "screen_size": {"w": w, "h": h},
                "transacoes": {}
            }
            self._save()

    # -------------------- API PÚBLICA -------------------- #

    def obter_roi_elemento(self, transacao: str, elemento: str) -> Optional[Tuple[int, int, int, int]]:
        """
        Retorna o bounding box (x1, y1, x2, y2) salvo, se existir.
        """
        host_data = self._data.get(self.hostname, {})
        trans = host_data.get("transacoes", {}).get(transacao, {})
        elem = trans.get("elements", {}).get(elemento)
        if elem:
            return elem["x1"], elem["y1"], elem["x2"], elem["y2"]
        return None

    def atualizar_elemento(self, transacao: str, elemento: str, bbox: Tuple[int, int, int, int]):
        x1, y1, x2, y2 = map(int, bbox)

        # --- Expansão proporcional do ROI ---
        largura = x2 - x1
        altura = y2 - y1
        expand_x = int(largura * 0.3)
        expand_y = int(altura * 0.05)

        # Limites da tela (caso já tenha dimensão global salva)
        screen_w, screen_h = pyautogui.size()
        x1 = max(0, x1 - expand_x)
        y1 = max(0, y1 - expand_y)
        x2 = min(screen_w, x2 + expand_x)
        y2 = min(screen_h, y2 + expand_y)

        host = self._data.setdefault(self.hostname, {})
        trans = host.setdefault("transacoes", {}).setdefault(transacao, {})
        elems = trans.setdefault("elements", {})
        elems[elemento] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

        self._save()
        print(f"{strftime('[%H:%M:%S]')} [REGISTRY] ROI expandido salvo para {transacao}.{elemento}: ({x1},{y1},{x2},{y2})")


    def remover_elemento(self, transacao: str, elemento: str):
        """
        Remove o elemento específico de uma transação.
        """
        try:
            del self._data[self.hostname]["transacoes"][transacao]["elements"][elemento]
            self._save()
            print(f"{strftime('[%H:%M:%S]')} [REGISTRY] Elemento removido: {transacao}.{elemento}")
        except KeyError:
            pass

    def limpar_transacao(self, transacao: str):
        """
        Remove todos os elementos de uma transação.
        """
        try:
            del self._data[self.hostname]["transacoes"][transacao]
            self._save()
            print(f"{strftime('[%H:%M:%S]')} [REGISTRY] Transação '{transacao}' limpa.")
        except KeyError:
            pass

    def resetar_hostname(self):
        """
        Remove completamente os dados do host atual.
        """
        try:
            del self._data[self.hostname]
            self._save()
            print(f"{strftime('[%H:%M:%S]')} [REGISTRY] Host '{self.hostname}' removido do registro.")
        except KeyError:
            pass

    def dump(self):
        """
        Retorna o dicionário atual (para debug/log).
        """
        return json.dumps(self._data.get(self.hostname, {}), indent=2, ensure_ascii=False)
