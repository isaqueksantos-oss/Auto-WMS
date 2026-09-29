import sys

from interface import main_window
from interface.wms_launcher import executar_wms_com_config_salva

if __name__ == "__main__":
    if "--run-wms-login" in sys.argv:
        sucesso = executar_wms_com_config_salva()
        raise SystemExit(0 if sucesso else 1)

    main_window.main()
