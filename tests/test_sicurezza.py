"""Protezioni dei dati sui server, nella finestra vera di tk-ftp (offscreen) contro i server di prova locali:
«Nuovo file» non azzera un file che c'è, la rinomina non sovrascrive senza chiedere, il doppio clic non apre
programmi e script, la modifica al volo non perde modifiche non caricate e non sovrascrive un file cambiato sul
server, l'eliminazione di cartelle mostra quanti elementi tocca, «TLS se disponibile» chiede prima del chiaro.
Più: finestre Benvenuto, Licenze, Informazioni e Impostazioni costruite senza errori.
Uso: python tests/test_sicurezza.py"""
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
WORK = tempfile.mkdtemp(prefix="tkftp-sicurezza-")
os.environ["TKFTP_DATI"] = os.path.join(WORK, "dati")
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-sicurezza"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.makedirs(os.environ["TKFTP_DATI"])

import servers  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  NO   ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def wait(cond, sec=15):
    t0 = time.time()
    while time.time() - t0 < sec:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    return False


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def main():
    srv = os.path.join(WORK, "server")
    os.makedirs(os.path.join(srv, "cartella", "sotto"))
    files = {"index.php": b"<?php echo 'pagina vera';", "a.txt": b"contenuto di a", "b.txt": b"contenuto di b",
             "setup.exe": b"MZ finto", "pagina.php": b"<?php // originale",
             "cartella/uno.txt": b"1", "cartella/due.txt": b"2", "cartella/sotto/tre.txt": b"3"}
    for name, data in files.items():
        with open(os.path.join(srv, *name.split("/")), "wb") as fh:
            fh.write(data)
    loc = os.path.join(WORK, "computer")
    os.makedirs(loc)
    info = servers.start_all(srv, int(os.environ.get("TKFTP_PORTA_SIC", "3221")), os.path.join(WORK, "chiavi"))
    from tkftp import pro, remote, style, transfers, trust
    import tkftp.app as appmod
    from tkftp.app import MainWindow
    from tkftp.listing import Entry
    from tkftp.sites import Site
    from tkftp.util import Settings, data_dir
    s = Site(name="Sicurezza", host="127.0.0.1", port=info["sftp"], protocol="sftp", user=servers.USER)
    try:
        remote.make_client(s, servers.PASSWORD).connect()
    except remote.HostKeyQuestion as q:
        q.accept()
    app = QApplication(sys.argv)
    app.licenza = pro.crea_licenza("prova")
    app.setStyleSheet(style.stylesheet(style.check_png(os.path.join(data_dir(), "spunta.png"))))
    cfg = Settings()
    cfg.setValue("fz_asked", True)
    cfg.setValue("last_check", time.time())
    cfg.setValue("last_local", loc)
    cfg.setValue("dbl_remote", "edit")
    win = MainWindow(cfg)
    win.store.upsert(s, servers.PASSWORD)
    win.show()

    # finestre a scelta: le risposte le dà il collaudo
    answers, asked, warned, opened, inputs = [], [], [], [], []
    appmod.tk_choice = lambda parent, title, text, buttons, kind="ask", sub="": (
        asked.append((title, text)), answers.pop(0) if answers else 0)[1]
    appmod.tk_warn = lambda parent, title, text: warned.append(text)
    appmod.tk_input = lambda *a, **kw: inputs.pop(0) if inputs else None
    appmod.open_in_editor = lambda path, editor="": opened.append(path)

    win.connect_site(win.store.get(s.id))
    check(wait(lambda: win.connected and win.remote_pane.model.entries), "connesso (SFTP)")

    # --- «Nuovo file» su un nome che c'è già: rifiutato, il file resta com'era
    inputs.append("index.php")
    win.remote_new_file()
    check(wait(lambda: warned), "Nuovo file con un nome esistente: avviso")
    check(read(os.path.join(srv, "index.php")) == files["index.php"], "Nuovo file: index.php NON azzerato")
    check(any("c'è già" in w for w in warned), f"messaggio chiaro ({warned[-1:]})")
    warned.clear()
    # nome nuovo: creato vuoto e aperto al volo
    inputs.append("nuovo.txt")
    win.remote_new_file()
    check(wait(lambda: opened), "Nuovo file con un nome nuovo: creato e aperto nell'editor")
    check(read(os.path.join(srv, "nuovo.txt")) == b"", "nuovo.txt creato vuoto sul server")

    # --- rinomina sopra un file che esiste: si chiede; «Annulla» non tocca niente, «Sostituisci» sì
    a = next(e for e in win.remote_pane.model.entries if e.name == "a.txt")
    win.remote_pane.selected_paths = lambda: [("/a.txt", a)]
    asked.clear()
    inputs.append("b.txt")
    answers.append(0)
    win.remote_rename()
    check(wait(lambda: asked), "rinomina su un nome usato: domanda")
    time.sleep(0.5)
    check(read(os.path.join(srv, "b.txt")) == files["b.txt"] and os.path.exists(os.path.join(srv, "a.txt")),
          "rinomina annullata: b.txt e a.txt intatti")
    asked.clear()
    inputs.append("b.txt")
    answers.append(1)
    win.remote_rename()
    check(wait(lambda: not os.path.exists(os.path.join(srv, "a.txt"))), "rinomina confermata: a.txt diventa b.txt")
    check(read(os.path.join(srv, "b.txt")) == files["a.txt"], "b.txt ora ha il contenuto di a.txt")
    # rinomina verso un nome libero: nessuna domanda
    b = Entry("b.txt", False, len(files["a.txt"]))
    win.remote_pane.selected_paths = lambda: [("/b.txt", b)]
    asked.clear()
    inputs.append("c.txt")
    win.remote_rename()
    check(wait(lambda: os.path.exists(os.path.join(srv, "c.txt"))) and not asked, "rinomina su nome libero: diretta")

    # --- doppio clic su un programma: si scarica e basta, niente modifica al volo
    edits, downloads = [], []
    real_edit, real_download = win.edit_remote, win.download_entries
    win.edit_remote = lambda p, e, ask_script=True: edits.append(p)
    win.download_entries = lambda ents, d=None: downloads.extend(p for p, _ in ents)
    win._remote_activated(Entry("setup.exe", False, 8))
    win._remote_activated(Entry("installa.sh", False, 8))
    win._remote_activated(Entry("index.php", False, 8))
    check(downloads == ["/setup.exe", "/installa.sh"] and edits == ["/index.php"],
          f"doppio clic: programmi/script scaricati, testo aperto al volo ({downloads} / {edits})")
    win.edit_remote, win.download_entries = real_edit, real_download
    # «Modifica al volo» esplicita su uno script: chiede prima (Annulla = niente)
    asked.clear()
    n_items = len(win.tm.items)
    answers.append(0)
    win.edit_remote("/setup.exe", Entry("setup.exe", False, 8))
    check(asked and len(win.tm.items) == n_items, "Modifica al volo su un programma: chiede, Annulla non scarica")

    # --- modifica al volo: modifiche non caricate non si perdono riscaricando
    opened.clear()
    page = Entry("pagina.php", False, len(files["pagina.php"]), os.path.getmtime(os.path.join(srv, "pagina.php")))
    win.edit_remote("/pagina.php", page)
    check(wait(lambda: opened), "pagina.php aperta al volo")
    w = next(x for x in win.edits.files.values() if x.remote == "/pagina.php")
    check(getattr(w, "remote_sig", None) == (len(files["pagina.php"]), int(page.mtime)) or
          getattr(w, "remote_sig", (0,))[0] == len(files["pagina.php"]), f"ricordato com'era sul server ({w.remote_sig})")
    w.dirty = True
    asked.clear()
    n_items = len(win.tm.items)
    answers.append(0)
    win.edit_remote("/pagina.php", page)
    check(asked and "non sono ancora sul server" in asked[-1][1] and len(win.tm.items) == n_items,
          "file con modifiche non caricate: chiede prima di riscaricare, Annulla non riscarica")
    # il file cambia sul server (un collega) e io carico la mia copia: si chiede, «Non caricare» lo lascia stare
    time.sleep(1.1)
    with open(os.path.join(srv, "pagina.php"), "wb") as fh:
        fh.write(b"<?php // cambiato da un collega, piu' lungo")
    with open(w.local, "wb") as fh:
        fh.write(b"<?php // la mia modifica")
    asked.clear()
    answers.append(0)
    win._upload_edit(w)
    check(wait(lambda: not w.busy, 20), "caricamento della modifica: finito")
    check(any("cambiato" in t.lower() for t, _x in asked), f"file cambiato sul server: domanda ({asked})")
    check(read(os.path.join(srv, "pagina.php")) == b"<?php // cambiato da un collega, piu' lungo",
          "«Non caricare»: le modifiche del collega restano")
    check(w.dirty and "cambiato" in w.state, f"la mia copia resta da caricare ({w.state})")
    answers.append(1)
    asked.clear()
    win._upload_edit(w)
    check(wait(lambda: not w.busy and read(os.path.join(srv, "pagina.php")) == b"<?php // la mia modifica", 20),
          "«Sovrascrivi lo stesso»: caricata la mia copia")
    # dopo il mio caricamento, il prossimo non chiede più (la «firma» del server è aggiornata)
    with open(w.local, "wb") as fh:
        fh.write(b"<?php // seconda modifica mia")
    asked.clear()
    win._upload_edit(w)
    check(wait(lambda: not w.busy and read(os.path.join(srv, "pagina.php")) == b"<?php // seconda modifica mia", 20)
          and not asked, "caricamento successivo: nessuna domanda")
    check(not any(n.endswith(transfers.TMP_UP) for n in os.listdir(srv)), "nessun .tkpart rimasto sul server")

    # --- eliminazione di una cartella: prima il conteggio, poi la conferma con i numeri
    cart = Entry("cartella", True)
    win.remote_pane.selected_paths = lambda: [("/cartella", cart)]
    asked.clear()
    answers.append(0)
    win.remote_delete()
    check(wait(lambda: asked), "eliminazione cartella: domanda")
    check("3 file e 2 cartelle" in asked[-1][1], f"la domanda dice quanti elementi ({asked[-1][1]})")
    time.sleep(0.4)
    check(os.path.isdir(os.path.join(srv, "cartella")), "Annulla: la cartella resta")
    asked.clear()
    answers.append(1)
    win.remote_delete()
    check(wait(lambda: not os.path.exists(os.path.join(srv, "cartella"))), "confermata: cartella eliminata")

    # --- «FTP · TLS se disponibile» verso un server senza TLS: si chiede prima di mandare la password
    f = Site(name="Senza TLS", host="localhost", port=info["ftp"], protocol="ftp", user=servers.USER)
    trust.forget(f.host, f.port)
    asked.clear()
    answers.append(0)
    win.connect_site(f, servers.PASSWORD)
    check(wait(lambda: asked) and "non protetta" in asked[-1][0].lower(), "server senza TLS: domanda prima del chiaro")
    check(wait(lambda: not win.connected), "rifiutato: non connesso")
    asked.clear()
    answers.append(1)
    win.connect_site(f, servers.PASSWORD)
    check(wait(lambda: win.connected), "accettato: connesso in chiaro")
    asked.clear()
    win.connect_site(f, servers.PASSWORD)
    check(wait(lambda: win.connected) and not asked, "la scelta vale per il server: nessuna nuova domanda")
    trust.forget(f.host, f.port)

    # --- finestre del software libero
    from tkftp import URL_SORGENTE, VERSION
    from tkftp.dialogs import AboutDialog, SettingsDialog
    from tkftp.tk_licenza_qt import BenvenutoDialog, LicenzeDialog
    from tkftp.util import licenses_dir
    ben = BenvenutoDialog(app.licenza, "tk-ftp", URL_SORGENTE, win, style.logo_tile(96), appmod.RIGHE_BENVENUTO)
    check(not ben.casella.isChecked(), "benvenuto: statistiche spente di default")
    ben.reject()
    check(app.licenza.consenso_statistiche() is False and app.licenza.ricordo("benvenuto_agpl"),
          "benvenuto chiuso: niente statistiche, non si mostra più")
    lic = LicenzeDialog("tk-ftp", VERSION, URL_SORGENTE, licenses_dir(), win)
    voci = [lic.elenco.item(i).text() for i in range(lic.elenco.count())]
    check(voci and voci[0].startswith("COPYING"), f"licenze: prima l'AGPL ({voci[:3]})")
    check("COMPONENTI" in voci, "licenze: c'è COMPONENTI")
    about = AboutDialog(win)
    from PySide6.QtWidgets import QLabel, QPushButton
    labels = " ".join(x.text() for x in about.findChildren(QLabel))
    buttons = [x.text() for x in about.findChildren(QPushButton)]
    check("AGPL-3.0" in labels and "Pro" not in labels, "Informazioni: «Software libero · AGPL-3.0», niente Pro")
    check(any("Licenze e codice sorgente" in t for t in buttons), "Informazioni: pulsante Licenze e codice sorgente")
    check(not any("Pro" in t or "Sblocca" in t for t in buttons), f"Informazioni: nessun pulsante Pro ({buttons})")
    sd = SettingsDialog(win, cfg, "")
    check(sd.stats.text().startswith("Invia statistiche") and not sd.stats.isChecked(),
          "Impostazioni: casella statistiche (spenta)")
    sd.shared.setText(WORK)
    sd.shared_pw.setChecked(True)
    sd.phrase.setText("corta1234")
    sd.choice = True
    warned.clear()
    import tkftp.dialogs as dlgmod
    dlgmod.tk_warn = lambda parent, title, text: warned.append(text)
    sd._validate()
    check(warned and "12" in warned[-1], "frase segreta nuova di 9 caratteri: rifiutata (minimo 12)")

    win.closing_for_update = True
    win.close()
    win.tm.shutdown()
    shutil.rmtree(WORK, ignore_errors=True)
    print("SICUREZZA OK" if not FAILS else f"SICUREZZA FALLITO: {FAILS}", flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
