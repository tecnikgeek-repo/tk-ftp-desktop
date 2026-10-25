"""Collaudo dell'interfaccia vera di tk-ftp contro i server di prova locali, con screenshot di ogni passo.
Uso: python tests/test_ui.py <cartella screenshot>
Passi: benvenuto con siti recenti → gestore siti → connessione SFTP (chiave sconosciuta: conferma) → elenco →
carica cartella (coda con avanzamento, server FTP rallentato) → file già esistente → completati → modifica al volo
(il file cambia → domanda → ricaricato sul server, contenuto verificato) → permessi, impostazioni, Informazioni,
registro. Esce con codice 0 se tutto è andato bene."""
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
SHOTS = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "schermate"))
os.makedirs(SHOTS, exist_ok=True)
WORK = tempfile.mkdtemp(prefix="tkftp-ui-")
os.environ["TKFTP_DATI"] = os.path.join(WORK, "dati")
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-ui"
os.makedirs(os.environ["TKFTP_DATI"])

import servers  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PORT = int(os.environ.get("TKFTP_PORTA_UI", "2721"))
SRV = os.path.join(WORK, "server")
LOCAL = os.path.join(WORK, "computer", "Sito cliente")


def make_tree():
    web = os.path.join(SRV, "public_html")
    for d in ("wp-content/themes/tk-tema", "wp-content/uploads/2026", "assets/css", "assets/img"):
        os.makedirs(os.path.join(web, d), exist_ok=True)
    files = {"index.php": "<?php\n// Pagina iniziale\nrequire 'wp-blog-header.php';\n",
             ".htaccess": "RewriteEngine On\n", "robots.txt": "User-agent: *\nAllow: /\n",
             "assets/css/stile.css": "body { color: #0f172a; }\n", "wp-config.php": "<?php define('DB_NAME','sito');\n",
             "LEGGIMI.md": "# Sito di prova\n"}
    for rel, txt in files.items():
        with open(os.path.join(web, rel), "w", encoding="utf-8") as fh:
            fh.write(txt)
    for rel, n in (("assets/img/logo.png", 48_000), ("wp-content/uploads/2026/foto-negozio.jpg", 820_000),
                   ("backup-sito.zip", 3_400_000), ("documento.pdf", 210_000)):
        with open(os.path.join(web, rel), "wb") as fh:
            fh.write(os.urandom(n))
    os.makedirs(os.path.join(LOCAL, "immagini"), exist_ok=True)
    for i, n in enumerate((14_000_000, 9_000_000, 6_000_000, 11_000_000)):
        with open(os.path.join(LOCAL, "immagini", f"galleria-{i + 1}.jpg"), "wb") as fh:
            fh.write(os.urandom(n))
    for name, txt in (("index.html", "<h1>Benvenuti</h1>\n"), ("contatti.html", "<p>Contatti</p>\n"),
                      ("stile.css", "h1 { color: #e39a2e; }\n")):
        with open(os.path.join(LOCAL, name), "w", encoding="utf-8") as fh:
            fh.write(txt)


def throttle_ftp():
    """Server FTP «lento» (2 MB/s) per vedere la coda in movimento."""
    from pyftpdlib.handlers import ThrottledDTPHandler
    ThrottledDTPHandler.read_limit = 2_500_000
    ThrottledDTPHandler.write_limit = 2_500_000
    return ThrottledDTPHandler


class Runner:
    def __init__(self, app, win):
        self.app, self.win = app, win
        self.steps = []
        self.errors = []
        self.n = 0

    def shot(self, name, widget=None):
        self.n += 1
        w = widget or self.win
        path = os.path.join(SHOTS, f"{self.n:02d}-{name}.png")
        w.grab().save(path)
        print("  schermata", os.path.basename(path), flush=True)

    def screen_shot(self, name, widget, pad=0):
        """Foto dello schermo vero (composizione di Windows): le ombre dei dialoghi trasparenti si vedono davvero."""
        from PySide6.QtGui import QGuiApplication
        widget.raise_()
        widget.activateWindow()
        QApplication.processEvents()
        time.sleep(0.4)
        QApplication.processEvents()
        g = widget.frameGeometry()
        scr = widget.screen() or QGuiApplication.primaryScreen()
        pm = scr.grabWindow(0, g.x() - pad, g.y() - pad, g.width() + 2 * pad, g.height() + 2 * pad)
        self.n += 1
        path = os.path.join(SHOTS, f"{self.n:02d}-{name}-schermo.png")
        pm.save(path)
        print("  schermata", os.path.basename(path), flush=True)

    def shot_on_bg(self, name, widget):
        """Finestra trasparente (dialoghi) disegnata su fondo chiaro: si vede come sfuma l'ombra attorno agli angoli."""
        from PySide6.QtGui import QColor, QPixmap
        pm = QPixmap(widget.size())
        pm.fill(QColor("#e9edf4"))
        widget.render(pm)
        self.n += 1
        path = os.path.join(SHOTS, f"{self.n:02d}-{name}-su-fondo.png")
        pm.save(path)
        print("  schermata", os.path.basename(path), flush=True)

    def modal(self):
        return QApplication.activeModalWidget()

    def wait(self, cond, then, timeout=40, what=""):
        t0 = time.time()

        def tick():
            try:
                ok = cond()
            except Exception:
                ok = False
            if ok:
                QTimer.singleShot(250, lambda: self._safe(then))
            elif time.time() - t0 > timeout:
                self.fail(f"tempo scaduto: {what}")
            else:
                QTimer.singleShot(150, tick)
        QTimer.singleShot(150, tick)

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            self.fail(traceback.format_exc())

    def fail(self, msg):
        print("ERRORE:", msg, flush=True)
        self.errors.append(msg)
        self.shot("errore")
        self.finish()

    def check(self, cond, msg):
        if not cond:
            raise AssertionError(msg)

    def finish(self):
        m = self.modal()
        if m is not None:
            m.reject()
        self.win.closing_for_update = True
        QTimer.singleShot(200, self.app.quit)


def main():
    make_tree()
    ThrottledDTP = throttle_ftp()
    info = servers.start_all(SRV, PORT, os.path.join(WORK, "chiavi"))
    from pyftpdlib.handlers import FTPHandler
    for h in FTPHandler.__subclasses__():
        if h.__name__ == "Plain":  # solo il server in chiaro: quelli TLS hanno il loro canale dati
            h.dtp_handler = ThrottledDTP
    from tkftp import style
    from tkftp.app import MainWindow
    from tkftp import app as appmod
    from tkftp.sites import Site
    from tkftp.util import Settings, data_dir

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(style.stylesheet(style.check_png(os.path.join(data_dir(), "spunta.png"))))
    settings = Settings()
    settings.setValue("fz_asked", True)
    settings.setValue("last_check", time.time())
    settings.setValue("last_local", LOCAL)
    settings.setValue("parallel", 2)
    win = MainWindow(settings)
    st = win.store
    now = time.time()
    sftp = Site(name="Sito cliente (SFTP)", host="127.0.0.1", port=info["sftp"], protocol="sftp", user=servers.USER,
                group="Clienti", remote_dir="/public_html", last_used=now - 10)
    ftp = Site(name="Negozio online (FTP)", host="localhost", port=info["ftp"], protocol="ftp-plain", user=servers.USER,
               group="Clienti", remote_dir="/public_html", last_used=now - 100)
    ftps = Site(name="Server hosting (FTPS)", host="localhost", port=info["ftps"], protocol="ftps", user=servers.USER,
                group="Hosting", last_used=now - 1000)
    key = Site(name="VPS con chiave", host="127.0.0.1", port=info["sftp"], protocol="sftp", user=servers.USER,
               logon="key", keyfile=info["client_key"], group="Hosting/VPS", last_used=now - 5000)
    for s in (sftp, ftp, ftps, key):
        st.upsert(s, servers.PASSWORD if s.logon == "normal" else None)
    win._refresh_recent()
    win.resize(1440, 900)
    win.show()
    r = Runner(app, win)
    edited = {}

    def fake_editor(path, editor=""):
        """Al posto dell'editor: dopo un attimo «salva» il file con una riga in più (come farebbe l'utente)."""
        def save():
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("// modificato con tk-ftp\n")
            edited["path"] = path
        QTimer.singleShot(1500, save)
    appmod.open_in_editor = fake_editor

    def s1():
        r.shot("benvenuto")
        from tkftp.sitemanager import SiteManager
        dlg = SiteManager(win, st, {"import": lambda: None, "export": lambda: None}, sftp.id)
        dlg.show()
        QTimer.singleShot(500, lambda: r._safe(lambda: (r.shot("gestore-siti", dlg), r.shot_on_bg("gestore-siti", dlg),
                                                        dlg.close(), s2())))

    def s2():
        win.connect_site(st.get(sftp.id))
        r.wait(lambda: r.modal() is not None and r.modal().__class__.__name__ == "HostKeyDialog", s3, what="chiave SSH")

    def s3():
        r.shot("chiave-ssh-nuova", r.modal())
        r.shot_on_bg("chiave-ssh-nuova", r.modal())
        r.modal()._pick(True)
        r.wait(lambda: win.connected and win.remote_pane.path == "/public_html" and win.remote_pane.model.entries, s4,
               what="elenco remoto")

    def s4():
        names = {e.name for e in win.remote_pane.model.entries}
        r.check({"index.php", "assets", "wp-content", "backup-sito.zip"} <= names, f"elenco remoto: {names}")
        win.remote_pane.view.setCurrentIndex(win.remote_pane.model.index(4, 0))
        r.shot("connesso-sftp")
        r.screen_shot("connesso-sftp", win, 0)
        print("  larghezza minima della finestra:", win.minimumSizeHint().width(), flush=True)
        win.resize(1280, 760)  # finestra non massimizzata, da portatile
        QApplication.processEvents()
        r.check(win.width() <= 1290, f"la finestra non si stringe a 1280 (resta {win.width()})")
        names_w = win.remote_pane.view.header().sectionSize(0)
        r.check(names_w >= 170, f"colonna Nome troppo stretta: {names_w}")
        r.check(win.remote_pane.view.horizontalScrollBar().maximum() == 0, "barra orizzontale nel pannello del server a 1280: viewport %d, colonne %s" % (win.remote_pane.view.viewport().width(), [win.remote_pane.view.header().sectionSize(c) for c in range(6)]))
        r.shot("finestra-1280")
        win.resize(1440, 900)
        QApplication.processEvents()
        win.connect_site(st.get(ftp.id))
        r.wait(lambda: win.connected and win.site.id == ftp.id and win.remote_pane.model.entries, s5, what="FTP")

    def s5():
        win.upload_paths([os.path.join(LOCAL, "immagini")])
        r.wait(lambda: sum(1 for it in win.tm.items if it.status == "corso") >= 2 and
               any(it.done > 3_000_000 for it in win.tm.items), s6, what="trasferimenti in corso")

    def s6():
        win._refresh_queue()
        r.shot("coda-in-corso")
        r.wait(lambda: win.tm.pending_count() == 0 and any(e.name == "immagini" for e in win.remote_pane.model.entries),
               s7, timeout=90, what="caricamento finito")

    def s7():
        r.check(all(it.status == "fatto" for it in win.tm.items), [(i.name, i.status, i.error) for i in win.tm.items])
        for i in range(4):
            a = os.path.getsize(os.path.join(LOCAL, "immagini", f"galleria-{i + 1}.jpg"))
            b = os.path.getsize(os.path.join(SRV, "public_html", "immagini", f"galleria-{i + 1}.jpg"))
            r.check(a == b, f"dimensioni diverse galleria-{i + 1}")
        win.show_tab("completati")
        win._tm_dirty.set()
        win._refresh_queue()
        r.shot("completati")
        win.upload_paths([os.path.join(LOCAL, "stile.css")])
        with open(os.path.join(SRV, "public_html", "stile.css"), "w") as fh:
            fh.write("vecchio")
        r.wait(lambda: r.modal() is not None and r.modal().__class__.__name__ == "OverwriteDialog", s8,
               what="domanda file esistente")

    def s8():
        r.shot("file-esistente", r.modal())
        r.modal()._pick("overwrite")
        r.wait(lambda: win.tm.pending_count() == 0, s9, what="sovrascrittura")

    def s9():
        with open(os.path.join(SRV, "public_html", "stile.css"), encoding="utf-8") as fh:
            r.check("e39a2e" in fh.read(), "stile.css non sovrascritto")
        # trascina dal pannello del computer a quello del server (stessi dati di un trascinamento vero)
        lm = win.local_pane.model
        row = next(i for i in range(lm.rowCount()) if lm.entry(i).name == "contatti.html")
        data = win.remote_pane.view._mime(lm.mimeData([lm.index(row, 0)]))
        r.check(data and data.get("local"), "trascinamento locale: dati non riconosciuti")
        win.remote_pane.view.dropped.emit(data, None)
        r.wait(lambda: os.path.exists(os.path.join(SRV, "public_html", "contatti.html")) and not win.tm.pending_count(),
               s9b, what="trascina e carica")

    def s9b():
        rm = win.remote_pane.model
        win.remote_pane.refresh()
        row = next(i for i in range(rm.rowCount()) if rm.entry(i).name == "robots.txt")
        data = win.local_pane.view._mime(rm.mimeData([rm.index(row, 0)]))
        r.check(data and data.get("remote"), "trascinamento remoto: dati non riconosciuti")
        win.local_pane.view.dropped.emit(data, None)
        r.wait(lambda: os.path.exists(os.path.join(LOCAL, "robots.txt")) and not win.tm.pending_count(), s9c,
               what="trascina e scarica")

    def s9c():
        with open(os.path.join(LOCAL, "robots.txt"), encoding="utf-8") as fh:
            r.check("User-agent" in fh.read(), "robots.txt scaricato male")
        # modifica al volo di index.php (doppio clic = Modifica al volo)
        win.remote_pane.refresh()
        r.wait(lambda: any(e.name == "index.php" for e in win.remote_pane.model.entries), s10, what="elenco")

    def s10():
        e = next(e for e in win.remote_pane.model.entries if e.name == "index.php")
        win._remote_activated(e)
        r.wait(lambda: r.modal() is not None and r.modal().__class__.__name__ == "EditChangedDialog", s11,
               what="domanda file modificato")

    def s11():
        r.shot("modifica-al-volo", r.modal())
        r.modal()._pick("yes")
        r.wait(lambda: "modificato con tk-ftp" in open(os.path.join(SRV, "public_html", "index.php"), encoding="utf-8").read(),
               s12, what="file ricaricato")

    def s12():
        win.show_tab("modifica")
        win._refresh_edits()
        r.shot("in-modifica")
        from tkftp.dialogs import ChmodDialog
        e = next(e for e in win.remote_pane.model.entries if e.name == "index.php")
        d = ChmodDialog(win, e.name, e.perms or "rw-r--r--", False)
        d.show()
        QTimer.singleShot(300, lambda: r._safe(lambda: (r.shot("permessi", d), d.close(), s13())))

    def s13():
        from tkftp.dialogs import SettingsDialog
        d = SettingsDialog(win, settings, "")
        d.show()

        def nxt():
            r.shot("impostazioni", d)
            d.close()
            a = win._informazioni()   # finestra comune della libreria
            a.show()
            QTimer.singleShot(300, lambda: r._safe(lambda: (r.shot_on_bg("informazioni", a), a.close(), s14())))
        QTimer.singleShot(300, lambda: r._safe(nxt))

    def s14():
        win.show_tab("registro")
        win._flush_log()
        txt = win.log_view.toPlainText()
        r.check("PASS ********" in txt and servers.PASSWORD not in txt, "registro: password visibile o assente")
        r.shot("registro")
        # FTPS esplicito: certificato autofirmato da confermare
        win.connect_site(st.get(ftps.id))
        r.wait(lambda: r.modal() is not None and r.modal().__class__.__name__ == "CertDialog", s15, what="certificato")

    def s15():
        r.shot("certificato", r.modal())
        r.modal()._pick(True)
        r.wait(lambda: win.connected and win.site.id == ftps.id and win.remote_pane.model.entries, s16, what="FTPS")

    def s16():
        win.show_tab("coda")
        r.shot("connesso-ftps")
        win.connect_site(st.get(key.id))
        r.wait(lambda: win.connected and win.site.id == key.id and win.remote_pane.model.entries, s17, what="chiave")

    def answer_input(text):
        from PySide6.QtWidgets import QLineEdit
        m = r.modal()
        m.findChild(QLineEdit).setText(text)
        m._pick("ok")

    def is_modal(name):
        return lambda: r.modal() is not None and r.modal().__class__.__name__ == name

    def s17():
        r.shot("connesso-con-chiave")
        win.remote_list("/public_html")
        r.wait(lambda: win.remote_pane.path == "/public_html", s18, what="cartella")

    def s18():
        QTimer.singleShot(100, win.remote_mkdir)
        r.wait(is_modal("TkDialog"), lambda: (answer_input("cartella di prova"), r.wait(
            lambda: os.path.isdir(os.path.join(SRV, "public_html", "cartella di prova")) and
            any(e.name == "cartella di prova" for e in win.remote_pane.model.entries), s19, what="nuova cartella")),
            what="domanda nuova cartella")

    def select(name):
        m = win.remote_pane.model
        row = next(i for i in range(m.rowCount()) if m.entry(i).name == name)
        win.remote_pane.view.clearSelection()
        win.remote_pane.view.selectionModel().select(
            m.index(row, 0), win.remote_pane.view.selectionModel().SelectionFlag.Select
            | win.remote_pane.view.selectionModel().SelectionFlag.Rows)

    def s19():
        select("cartella di prova")
        QTimer.singleShot(100, win.remote_rename)
        r.wait(is_modal("TkDialog"), lambda: (answer_input("cartella rinominata"), r.wait(
            lambda: os.path.isdir(os.path.join(SRV, "public_html", "cartella rinominata")) and
            any(e.name == "cartella rinominata" for e in win.remote_pane.model.entries), s20, what="rinomina")),
            what="domanda rinomina")

    def s20():
        select("cartella rinominata")
        n0 = len(servers.CHMODS)
        QTimer.singleShot(100, win.remote_chmod)

        def apply():
            m = r.modal()
            m.octal.setText("750")
            m._pick(True)
            r.wait(lambda: len(servers.CHMODS) > n0, s21, what="permessi")
        r.wait(is_modal("ChmodDialog"), apply, what="finestra permessi")

    def s21():
        r.check(servers.CHMODS[-1][1] == 0o750, f"permessi ricevuti dal server: {oct(servers.CHMODS[-1][1])}")
        select("cartella rinominata")
        QTimer.singleShot(100, win.remote_delete)

        def confirm():
            r.shot("elimina-conferma", r.modal())
            r.modal()._pick(1)
            r.wait(lambda: not os.path.exists(os.path.join(SRV, "public_html", "cartella rinominata")) and
                   not any(e.name == "cartella rinominata" for e in win.remote_pane.model.entries), s22, what="elimina")
        r.wait(is_modal("TkDialog"), confirm, what="conferma elimina")

    def s22():
        # connessione rapida (non salvata) e poi «Salva sito»
        win.qc_proto.setCurrentIndex(win.qc_proto.findData("sftp"))
        win.qc_host.setText(f"127.0.0.1:{info['sftp']}")
        win.qc_user.setText(servers.USER)
        win.qc_pass.setText(servers.PASSWORD)
        n = len(st.sites)
        win.quick_connect()
        r.wait(lambda: win.connected and win.quick and win.remote_pane.model.entries,
               lambda: s23(n), what="connessione rapida")

    def s23(n):
        r.check(win.remote_pane.btn_save_site.isVisible(), "manca «Salva sito»")
        r.shot("connessione-rapida")
        win.remote_pane.btn_save_site.click()
        r.check(len(st.sites) == n + 1 and not win.quick, "sito rapido non salvato")
        from tkftp.sites import get_password
        r.check(get_password(st.sites[-1]) == servers.PASSWORD, "password del sito rapido non salvata")
        print("UI OK", flush=True)
        r.finish()

    QTimer.singleShot(800, lambda: r._safe(s1))
    QTimer.singleShot(240000, lambda: r.fail("tempo totale scaduto"))
    app.exec()
    win.tm.shutdown()
    from tkftp import vault
    vault.purge_service()  # niente credenziali di prova lasciate nel portachiavi
    try:
        info["sock"].close()
    except Exception:
        pass
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
