import os
import site
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# Sviluppo su Windows: avviato con il Python base (Smart App Control blocca quello del venv), aggiunge le librerie del venv.
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if sys.prefix == sys.base_prefix and not os.path.isdir(os.path.join(ROOT, "python")) and os.path.isdir(DEV_SITE):
    site.addsitedir(DEV_SITE)
sys.path.insert(0, ROOT)

from tkftp.app import main  # noqa: E402

if __name__ == "__main__":
    main()
