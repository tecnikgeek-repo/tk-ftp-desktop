"""Doppio clic e Invio nei due pannelli con clic veri dentro l'app (QTest, il mouse dello schermo non si muove):
cartella = entra, «..» = sale, file = azione scelta (modifica al volo / scarica, carica / apri), anche con l'elemento
già selezionato, dopo un trascinamento annullato, dopo clic singolo e menu del tasto destro.
Uso: python tests/test_dblclick.py"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
WORK = tempfile.mkdtemp(prefix="tkftp-dbl-")
os.environ["TKFTP_DATI"] = os.path.join(WORK, "dati")
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-dbl"
os.makedirs(os.environ["TKFTP_DATI"])

import servers  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  NO   ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        QApplication.processEvents()
        time.sleep(0.02)


def wait(cond, sec=15):
    t0 = time.time()
    while time.time() - t0 < sec:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return False


def row_pos(view, name):
    m = view.model()
    r = next(i for i in range(m.rowCount()) if m.entry(i).name == name)
    return view.visualRect(m.index(r, 0)).center(), r


def main():
    srv = os.path.join(WORK, "server")
    home = os.path.join(srv, "public_html", "sottocartella")
    os.makedirs(home)
    with open(os.path.join(srv, "public_html", "index.php"), "w") as fh:
        fh.write("<?php echo 1;")
    loc = os.path.join(WORK, "computer")
    os.makedirs(os.path.join(loc, "dentro"))
    with open(os.path.join(loc, "foto.txt"), "w") as fh:
        fh.write("x")
    info = servers.start_all(srv, int(os.environ.get("TKFTP_PORTA_DBL", "3021")), os.path.join(WORK, "chiavi"))
    from tkftp import remote, style
    from tkftp.app import MainWindow
    from tkftp.sites import Site
    from tkftp.util import Settings, data_dir
    s = Site(name="Doppio clic", host="127.0.0.1", port=info["sftp"], protocol="sftp", user=servers.USER)
    try:
        remote.make_client(s, servers.PASSWORD).connect()
    except remote.HostKeyQuestion as q:
        q.accept()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(style.stylesheet(style.check_png(os.path.join(data_dir(), "spunta.png"))))
    cfg = Settings()
    cfg.setValue("fz_asked", True)
    cfg.setValue("last_check", time.time())
    cfg.setValue("last_local", loc)
    win = MainWindow(cfg)
    win.store.upsert(s, servers.PASSWORD)
    win.resize(1400, 860)
    win.show()
    QTest.qWaitForWindowExposed(win)
    win.activateWindow()
    pump(0.5)
    edits, downloads, uploads, opened = [], [], [], []
    win.edit_remote = lambda p, e: edits.append(p)
    win.download_entries = lambda ents, d=None: downloads.extend(p for p, _ in ents)
    win.upload_paths = lambda paths, d=None: uploads.extend(paths)
    import tkftp.app as appmod
    appmod.open_path = lambda p: opened.append(p)
    win.connect_site(win.store.get(s.id))
    check(wait(lambda: win.connected and win.remote_pane.model.entries), "connesso, elenco della cartella iniziale")
    rv, lv = win.remote_pane.view, win.local_pane.view
    # il primo clic sintetico di QTest su una finestra appena mostrata non conta: si «arma» con un clic a vuoto
    for v in (rv, lv):
        QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         v.visualRect(v.model().index(0, 0)).center())
        QTest.qWait(600)

    def dbl(view, name, sel_first=True):
        # QTest perde un doppio clic sintetico su due se sono consecutivi (succede anche con un QTreeView puro):
        # prima un clic singolo sulla riga, come farebbe una persona; il primo caso è senza.
        QTest.qWait(700)  # lontano dal clic precedente, come farebbe una persona
        p, r = row_pos(view, name)
        if sel_first:
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
            QTest.qWait(700)  # oltre il tempo del doppio clic: è un clic singolo prima
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)

    # --- server
    if os.environ.get("DBG"):
        for sig in ("pressed", "clicked", "doubleClicked"):
            getattr(rv, sig).connect(lambda i, s=sig: print("   [dbg]", s, i.row(), flush=True))
        rv.activated_entry.connect(lambda e: print("   [dbg] activated", e and e.name, flush=True))
        win.remote_pane.navigate.connect(lambda p: print("   [dbg] navigate", p, flush=True))
        print("   [dbg] righe", [rv.model().entry(i).name for i in range(rv.model().rowCount())], win.remote_pane.path, flush=True)
    dbl(rv, "public_html", sel_first=False)
    check(wait(lambda: win.remote_pane.path == "/public_html"), "server: doppio clic su cartella entra")
    dbl(rv, "..", sel_first=True)
    check(wait(lambda: win.remote_pane.path == "/"), "server: doppio clic su «..» (già selezionato) sale")
    dbl(rv, "public_html", sel_first=True)
    check(wait(lambda: win.remote_pane.path == "/public_html"), "server: doppio clic su cartella già selezionata")
    # trascinamento annullato: premi, muovi poco oltre la soglia e rilascia sullo stesso pannello (rifiutato)
    p, _ = row_pos(rv, "sottocartella")
    QTest.mousePress(rv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    QTest.mouseMove(rv.viewport(), p + QPoint(3, 2))
    QTest.mouseRelease(rv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p + QPoint(3, 2))
    pump(0.4)
    dbl(rv, "sottocartella")
    check(wait(lambda: win.remote_pane.path == "/public_html/sottocartella"), "server: doppio clic dopo trascinamento annullato")
    win.remote_list("/public_html")
    wait(lambda: win.remote_pane.path == "/public_html")
    cfg.setValue("dbl_remote", "edit")
    dbl(rv, "index.php")
    check(wait(lambda: edits), "server: doppio clic su file = modifica al volo")
    cfg.setValue("dbl_remote", "download")
    dbl(rv, "index.php")
    check(wait(lambda: downloads), "server: doppio clic su file = scarica (impostazione)")
    # Invio
    p, r = row_pos(rv, "sottocartella")
    rv.setCurrentIndex(rv.model().index(r, 0))
    rv.setFocus()
    QTest.keyClick(rv, Qt.Key.Key_Return)
    check(wait(lambda: win.remote_pane.path == "/public_html/sottocartella"), "server: Invio su cartella entra")
    # clic singolo seleziona, tasto destro apre il menu
    win.remote_list("/public_html")
    wait(lambda: win.remote_pane.path == "/public_html")
    p, r = row_pos(rv, "index.php")
    QTest.mouseClick(rv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    pump(0.2)
    check([e.name for e in rv.selected_entries()] == ["index.php"], "server: clic singolo seleziona")
    shown = []
    from PySide6.QtWidgets import QMenu
    QTimer.singleShot(400, lambda: (shown.append(QApplication.activePopupWidget()),
                                    QApplication.activePopupWidget() and QApplication.activePopupWidget().close()))
    rv.customContextMenuRequested.emit(p)
    pump(0.6)
    check(bool(shown) and isinstance(shown[0], QMenu), "server: tasto destro apre il menu")

    # --- computer
    check(wait(lambda: os.path.normcase(win.local_pane.path) == os.path.normcase(os.path.realpath(loc))),
          "computer: cartella iniziale")
    dbl(lv, "dentro", sel_first=True)
    check(wait(lambda: win.local_pane.path.endswith("dentro")), "computer: doppio clic su cartella entra")
    dbl(lv, "..")
    check(wait(lambda: not win.local_pane.path.endswith("dentro")), "computer: doppio clic su «..» sale")
    dbl(lv, "foto.txt")
    check(wait(lambda: uploads), "computer: doppio clic su file = carica (connesso)")
    cfg.setValue("dbl_local", "open")
    dbl(lv, "foto.txt")
    check(wait(lambda: opened), "computer: doppio clic su file = apri (impostazione)")
    p, r = row_pos(lv, "dentro")
    lv.setCurrentIndex(lv.model().index(r, 0))
    lv.setFocus()
    QTest.keyClick(lv, Qt.Key.Key_Return)
    check(wait(lambda: win.local_pane.path.endswith("dentro")), "computer: Invio su cartella entra")

    win.closing_for_update = True
    win.close()
    win.tm.shutdown()
    from tkftp import vault
    vault.purge_service()
    shutil.rmtree(WORK, ignore_errors=True)
    print("DOPPIO CLIC OK" if not FAILS else f"DOPPIO CLIC FALLITO: {FAILS}", flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
