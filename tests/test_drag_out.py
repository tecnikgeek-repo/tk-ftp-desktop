"""Prova VERA (solo Windows) del trascinamento dal pannello del server verso Esplora file.
Apre una finestra di Esplora file su una cartella vuota, trascina col mouse simulato (SendInput) due file e una
cartella dal pannello del server di tk-ftp, poi controlla che arrivino integri (SHA-256 uguale al server).
Uso: python tests/test_drag_out.py <cartella screenshot>   (muove il mouse: non toccarlo per ~30 secondi)"""
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
SHOTS = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "schermate"))
os.makedirs(SHOTS, exist_ok=True)
WORK = tempfile.mkdtemp(prefix="tkftp-drag-")
os.environ["TKFTP_DATI"] = os.path.join(WORK, "dati")
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-drag"
os.makedirs(os.environ["TKFTP_DATI"])

import servers  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
SRV = os.path.join(WORK, "server")
DEST = os.path.join(WORK, "Destinazione trascinamento")


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def mouse(x, y, flags=0):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)), 0, 0x8000 | 0x0001 | flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def drag(x0, y0, x1, y1):
    mouse(x0, y0)
    time.sleep(0.4)
    mouse(x0, y0, 0x0002)  # sinistro giù
    time.sleep(0.3)
    for i in range(1, 41):
        mouse(x0 + (x1 - x0) * i / 40, y0 + (y1 - y0) * i / 40)
        time.sleep(0.03)
    time.sleep(0.8)
    mouse(x1, y1)
    time.sleep(0.4)
    mouse(x1, y1, 0x0004)  # sinistro su


def explorer_window(title):
    found = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        if cls.value == "CabinetWClass" and title in buf.value and user32.IsWindowVisible(h):
            found.append(h)
        return True
    user32.EnumWindows(PROC(cb), 0)
    return found[0] if found else None


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    web = os.path.join(SRV, "public_html")
    os.makedirs(os.path.join(web, "assets", "img"), exist_ok=True)
    for rel, n in (("backup-sito.zip", 5_300_000), ("documento.pdf", 410_000), ("assets/img/logo.png", 64_000),
                   ("assets/stile.css", 2_000)):
        with open(os.path.join(web, rel), "wb") as fh:
            fh.write(os.urandom(n))
    os.makedirs(DEST)
    info = servers.start_all(SRV, int(os.environ.get("TKFTP_PORTA_DRAG", "2921")), os.path.join(WORK, "chiavi"))
    from tkftp import remote, style
    from tkftp.app import MainWindow
    from tkftp.sites import Site
    from tkftp.util import Settings, data_dir
    s = Site(name="Prova trascinamento", host="127.0.0.1", port=info["sftp"], protocol="sftp", user=servers.USER,
             remote_dir="/public_html")
    try:
        remote.make_client(s, servers.PASSWORD).connect()
    except remote.HostKeyQuestion as q:
        q.accept()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(style.stylesheet(style.check_png(os.path.join(data_dir(), "spunta.png"))))
    cfg = Settings()
    cfg.setValue("fz_asked", True)
    cfg.setValue("last_check", time.time())
    win = MainWindow(cfg)
    win.store.upsert(s, servers.PASSWORD)
    win.setGeometry(20, 40, 1100, 820)
    win.show()
    subprocess.Popen(["explorer.exe", DEST])
    result = {"ok": False, "msg": ""}

    def step1():
        win.connect_site(win.store.get(s.id))
        wait(lambda: win.connected and win.remote_pane.path == "/public_html" and win.remote_pane.model.entries, step2)

    def wait(cond, then, timeout=30):
        t0 = time.time()

        def tick():
            if cond():
                QTimer.singleShot(300, then)
            elif time.time() - t0 > timeout:
                result["msg"] = "tempo scaduto"
                QGuiApplication.primaryScreen().grabWindow(0).save(os.path.join(SHOTS, "trascina-scaduto.png"))
                print("  in coda:", [(i.name, i.status, i.error) for i in win.tm.items], os.listdir(DEST), flush=True)
                app.quit()
            else:
                QTimer.singleShot(200, tick)
        tick()

    def step2():
        h = explorer_window(os.path.basename(DEST))
        if not h:
            result["msg"] = "finestra di Esplora file non trovata"
            app.quit()
            return
        result["hwnd"] = h
        user32.SetWindowPos(h, 0, 1140, 60, 760, 760, 0x0040)
        user32.SetForegroundWindow(h)
        win.raise_()
        win.activateWindow()
        v = win.remote_pane.view
        m = win.remote_pane.model
        sm = v.selectionModel()
        sm.clear()
        rows = [i for i in range(m.rowCount()) if m.entry(i).name in ("backup-sito.zip", "documento.pdf", "assets")]
        for r in rows:
            sm.select(m.index(r, 0), sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
        rect = v.visualRect(m.index(rows[0], 0))
        dpr = win.screen().devicePixelRatio()
        p = v.viewport().mapToGlobal(rect.center())
        x0, y0 = p.x() * dpr, p.y() * dpr
        rc = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(rc))
        x1, y1 = (rc.left + rc.right) / 2, rc.top + (rc.bottom - rc.top) * 0.65
        # sicurezza: le due finestre stanno sopra a tutto e sotto i due punti devono esserci proprio loro,
        # altrimenti non si muove il mouse (sul PC possono esserci altre finestre aperte)
        mine = int(win.winId())
        for hw in (mine, h):
            user32.SetWindowPos(hw, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_TOPMOST, senza spostare
        QApplication.processEvents()
        time.sleep(0.5)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.restype = wintypes.HWND
        top = lambda x, y: user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(int(x), int(y))), 2)  # noqa: E731
        if top(x0, y0) != mine or top(x1, y1) != h:
            result["msg"] = "sotto il mouse non ci sono le finestre giuste: prova annullata senza muovere il mouse"
            app.quit()
            return
        result["topmost"] = (mine, h)
        print(f"  trascino da {x0:.0f},{y0:.0f} a {x1:.0f},{y1:.0f} (dpr {dpr})", flush=True)
        threading.Thread(target=drag, args=(x0, y0, x1, y1), daemon=True).start()
        wait(lambda: all(os.path.exists(os.path.join(DEST, n)) for n in ("backup-sito.zip", "documento.pdf",
                                                                        os.path.join("assets", "img", "logo.png")))
             and not win.tm.pending_count(), step3, timeout=60)

    def step3():
        time.sleep(1.5)  # Esplora file finisce di copiare
        checks = []
        for rel in ("backup-sito.zip", "documento.pdf", "assets/img/logo.png", "assets/stile.css"):
            a, b = os.path.join(web, rel), os.path.join(DEST, rel)
            checks.append((rel, os.path.exists(b) and sha(a) == sha(b)))
        print("  file arrivati:", checks, flush=True)
        result["ok"] = all(ok for _, ok in checks)
        QGuiApplication.primaryScreen().grabWindow(0).save(os.path.join(SHOTS, "trascina-in-esplora-file.png"))
        win._refresh_queue()
        win.show_tab("completati")
        win._tm_dirty.set()
        win._refresh_queue()
        win.grab().save(os.path.join(SHOTS, "trascina-coda-completati.png"))
        app.quit()

    QTimer.singleShot(1500, step1)
    QTimer.singleShot(120000, app.quit)
    app.exec()
    for hw in result.get("topmost", ()):
        user32.SetWindowPos(hw, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_NOTOPMOST
    if result.get("hwnd"):
        user32.PostMessageW(result["hwnd"], 0x0010, 0, 0)  # chiude la finestra di Esplora file aperta dalla prova
    win.closing_for_update = True
    win.tm.shutdown()
    from tkftp import vault
    vault.purge_service()
    time.sleep(1)
    shutil.rmtree(WORK, ignore_errors=True)
    print("TRASCINAMENTO OK" if result["ok"] else f"TRASCINAMENTO FALLITO {result['msg']}", flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
