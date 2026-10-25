"""Schermata del Gestore siti con i loghi VERI di alcuni siti (rete vera, solo lettura delle home).
Uso: python tests/shot_logos.py <cartella>"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
os.makedirs(OUT, exist_ok=True)
WORK = tempfile.mkdtemp(prefix="tkftp-loghi-veri-")
os.environ["TKFTP_DATI"] = WORK
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-loghi"

from PySide6.QtGui import QColor, QFont, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    from tkftp import logos, style
    from tkftp.sitemanager import SiteManager
    from tkftp.sites import Site, SiteStore
    from tkftp.util import Settings
    app.setStyleSheet(style.stylesheet(style.check_png(os.path.join(WORK, "spunta.png"))))
    st = SiteStore()
    sites = [Site(name="pietrodefilippis", host="cpanel.pietrodefilippis.it", port=65100, protocol="sftp",
                  group="1.SitiPersonali", last_used=time.time()),
             Site(name="almacolorificio", host="hostingssd101.netsons.net", group="2.Generici"),
             Site(name="graziavecchione", host="ftp.graziavecchione.it", group="2.Generici"),
             Site(name="paydea", host="cpanel.paydea.it", port=65100, protocol="sftp", group="1.SitiPersonali"),
             Site(name="ricciotravel", host="ricciotravel.it", group="2.Generici"),
             Site(name="Server di prova", host="10.0.0.5", group="2.Generici")]
    for s in sites:
        st.upsert(s, None)
        t0 = time.time()
        p = logos.update(s)
        print(f"  {s.name:18} {'logo ' + os.path.basename(logos._load_index()[s.id]['fonte']) if p else 'nessun logo (lettera)'}"
              f"  ({time.time() - t0:.1f} s)", flush=True)
    cfg = Settings()
    cfg.setValue("gruppi_aperti", ["1.SitiPersonali", "2.Generici"])
    dlg = SiteManager(None, st, {}, sites[0].id, settings=cfg)
    dlg.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.03)
    pm = QPixmap(dlg.size())
    pm.fill(QColor("#e9edf4"))
    dlg.render(pm)
    pm.save(os.path.join(OUT, "gestore-siti-loghi.png"))
    # ingrandimento 4x dell'elenco (nitidezza): il dialogo disegnato a 2x come su uno schermo ad alta risoluzione
    hi = QPixmap(dlg.size() * 2)
    hi.setDevicePixelRatio(2)
    hi.fill(QColor("#e9edf4"))
    dlg.render(hi)
    hi.save(os.path.join(OUT, "gestore-siti-loghi-2x.png"))
    tree = dlg.tree.viewport()
    g = tree.mapTo(dlg, tree.rect().topLeft())
    crop = hi.toImage().copy(g.x() * 2, g.y() * 2, 300 * 2, 230 * 2)
    crop.scaled(crop.width() * 2, crop.height() * 2).save(os.path.join(OUT, "gestore-siti-loghi-ingrandito.png"))
    from PySide6.QtWidgets import QScrollArea
    sc = dlg.findChild(QScrollArea)
    sc.verticalScrollBar().setValue(sc.verticalScrollBar().maximum())
    for _ in range(10):
        app.processEvents()
        time.sleep(0.03)
    pm2 = QPixmap(dlg.size())
    pm2.fill(QColor("#e9edf4"))
    dlg.render(pm2)
    pm2.save(os.path.join(OUT, "gestore-siti-sito-web.png"))
    dlg.close()
    shutil.rmtree(WORK, ignore_errors=True)
    print("fatto", OUT)


if __name__ == "__main__":
    main()
