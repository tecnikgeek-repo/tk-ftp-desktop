"""Loghi dei siti contro un server HTTP locale finto: scelta dell'icona più grande (apple-touch PNG, SVG, ICO con più
misure), ripiego /favicon.ico, nessun logo → badge a lettera, cache e rinnovo, logo scelto a mano, dove cercare
(host, sito web, nome del sito, server del provider), niente richieste di rete con l'opzione spenta.
Uso: python tests/test_logos.py"""
import http.server
import io
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
WORK = tempfile.mkdtemp(prefix="tkftp-loghi-")
os.environ["TKFTP_DATI"] = WORK
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []
HITS = []


def check(cond, msg):
    print(("  ok   " if cond else "  NO   ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def png(size, color):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def ico(sizes):
    import struct
    imgs = [(s, png(s, "#00aa00")) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    data = b""
    for s, p in imgs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), off + len(data))
        data += p
    return out + data


SITES = {
    "/a/": (b'<html><head><link rel="icon" href="/a/piccola.png" sizes="16x16">'
            b'<link rel="apple-touch-icon" href="/a/grande.png" sizes="180x180"></head></html>', "text/html"),
    "/a/piccola.png": (None, "image/png"), "/a/grande.png": (None, "image/png"),
    "/b/": (b'<html><head><link rel="shortcut icon" href="logo.svg" type="image/svg+xml">'
            b'<link rel="icon" href="x.png" sizes="32x32"></head></html>', "text/html"),
    "/b/logo.svg": (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" '
                    b'fill="#0000ff"/></svg>', "image/svg+xml"),
    "/c/": (b"<html><head><title>senza icone</title></head></html>", "text/html"),
    "/favicon.ico": (None, "image/x-icon"),
    "/d/": (b"<html><head></head></html>", "text/html"),
    # manutenzione: 503 ma con le icone nell'HTML (caso garageputeoli.it)
    "/m/": (b'<html><head><link rel="icon" href="/m/icona-192.png" sizes="192x192"></head><body>Manutenzione</body></html>',
            "text/html; charset=utf-8"),
    "/m/icona-192.png": (None, "text/plain"),             # PNG con content-type sbagliato
    "/r/": (b"<html><head></head></html>", "text/html"),  # niente <link>: /r/favicon.ico non c'è, va su /favicon.ico
    "/s/": (b'<html><head><link rel="icon" href="/s/logo"></head></html>', "text/html"),
    "/s/logo": (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
                b'<rect width="4" height="4" fill="#00ff00"/></svg>', "application/octet-stream"),
}
REDIRECTS = {"/vai-altrove.ico": None}  # riempito in main: redirect verso l'altro server (altro «dominio»)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        HITS.append(self.path)
        if self.path in REDIRECTS:
            self.send_response(302)
            self.send_header("Location", REDIRECTS[self.path])
            self.end_headers()
            return
        body, ctype = SITES.get(self.path, (b"", ""))
        if self.path == "/a/piccola.png":
            body = png(16, "#ff0000")
        elif self.path == "/a/grande.png":
            body = png(180, "#e39a2e")
        elif self.path == "/favicon.ico":
            body = ico([16, 32, 48])
        elif self.path == "/m/icona-192.png":
            body = png(192, "#3366cc")
        if self.path == "/m/":
            self.send_response(503)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not ctype:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    app = QApplication(sys.argv)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    from tkftp import logos, style
    from tkftp.sites import Site

    # indirizzi locali e privati: mai (anche dopo un redirect); il server finto è su 127.0.0.1
    hits = len(HITS)
    img, _src = logos.fetch([base + "/a/"])
    check(img is None and len(HITS) == hits, "127.0.0.1: nessuna richiesta (indirizzi locali bloccati)")
    for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.1.1", "::1", "fe80::1", "::ffff:127.0.0.1"):
        check(not logos._public(ip), f"{ip}: non pubblico")
    check(logos._public("93.184.216.34"), "93.184.216.34: pubblico")
    try:
        logos._get("file:///C:/Windows/win.ini")
        check(False, "file:// rifiutato")
    except ValueError:
        check(True, "file:// rifiutato")
    logos.ALLOW_LOCAL = True  # da qui in poi il collaudo usa il server finto locale

    img, src = logos.fetch([base + "/a/"])
    check(img is not None and img.width() == 180 and src.endswith("grande.png"), "sceglie l'apple-touch-icon 180 px")
    img, src = logos.fetch([base + "/b/"])
    check(img is not None and img.width() == logos.SIZE and src.endswith(".svg"), "preferisce l'SVG (disegnato a 256 px)")
    img, src = logos.fetch([base + "/c/"])
    check(img is not None and img.width() == 48 and src.endswith("favicon.ico"),
          "senza <link>: ripiego /favicon.ico, misura più grande dell'ICO")
    img, src = logos.fetch([base + "/m/"])
    check(img is not None and img.width() == 192, "home in manutenzione (503): icona letta lo stesso, PNG con content-type sbagliato")
    img, src = logos.fetch([base + "/s/"])
    check(img is not None and img.pixelColor(10, 10).green() > 200, "SVG servito come application/octet-stream: riconosciuto dai byte")
    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    other_base = f"http://127.0.0.1:{other.server_address[1]}"
    REDIRECTS["/vai-altrove.ico"] = other_base + "/favicon.ico"
    SITES["/x/"] = (b'<html><head><link rel="icon" href="/vai-altrove.ico"></head></html>', "text/html")
    img, src = logos.fetch([base + "/x/"])
    check(img is not None and src.startswith(other_base), "icona con redirect verso un altro server: seguito")
    img, src = logos.fetch(["http://127.0.0.1:1/"])
    check(img is None, "sito che non risponde: niente logo")

    s = Site(name="Cliente", host="ftp.cliente.it")
    path = logos.update(s, base_urls=[base + "/a/"])
    check(bool(path) and QImage(path).width() == 180, "logo salvato in cache (Dati/loghi)")
    check(not logos.needs_fetch(s), "in cache: niente nuova ricerca")
    idx = logos._load_index()
    idx[s.id]["quando"] = time.time() - 31 * 86400
    logos._save_index(idx)
    check(logos.needs_fetch(s), "dopo 30 giorni si rinnova")
    f = Site(name="Fallito", host="fallito.example")
    logos.update(f, base_urls=["http://127.0.0.1:1/"])
    check(logos.last_failed(f.id) and not logos.needs_fetch(f), "logo non trovato: segnato, niente nuova ricerca subito")
    idx = logos._load_index()
    idx[f.id]["quando"] = time.time() - 25 * 3600
    logos._save_index(idx)
    check(logos.needs_fetch(f), "logo non trovato: si riprova dopo 1 giorno")
    # indice scritto da una versione precedente (1.0.4: senza «regole»), fallito pochi minuti fa: si riprova subito
    old = Site(name="garageputeoli", host="ftp.garageputeoli.it")
    idx = logos._load_index()
    idx[old.id] = {"quando": time.time() - 600, "file": False, "fonte": "", "manuale": False,
                   "chiave": ["", old.host, old.name]}
    logos._save_index(idx)
    check(logos.needs_fetch(old), "fallito con le regole della 1.0.4: si riprova subito")
    ok_old = Site(name="vecchio ok", host="ok.example")
    logos.update(ok_old, base_urls=[base + "/a/"])
    idx = logos._load_index()
    idx[ok_old.id].pop("regole", None)
    logos._save_index(idx)
    check(not logos.needs_fetch(ok_old), "successo della versione precedente: resta valido")
    ok_old.host = "nuovohost.example"
    check(logos.needs_fetch(ok_old), "cambiato l'host: si ricerca subito")
    ok_old.host, ok_old.name = "ok.example", "nome nuovo"
    check(logos.needs_fetch(ok_old), "cambiato il nome: si ricerca subito")
    s.website = "nuovo.it"
    check(logos.needs_fetch(s), "cambiato il sito web: si ricerca")
    s.website = ""
    logos.update(s, base_urls=[base + "/a/"])

    # badge: logo nitido (disegnato a 3x) oppure lettera
    style.clear_badge_cache()
    b = style.site_badge(s, 22)
    check(b.devicePixelRatio() == 3 and b.width() == 66, "badge del logo disegnato a 3x (nitido ad alta risoluzione)")
    c = b.toImage().pixelColor(33, 33)
    check(c.red() > 200 and 120 < c.green() < 180, f"nel badge c'è il logo (colore al centro {c.name()})")
    corner = b.toImage().pixelColor(1, 1)
    check(corner.alpha() < 60, "angolo arrotondato trasparente")
    nologo = Site(name="Zeta", host="10.0.0.1")
    z = style.site_badge(nologo, 22).toImage().pixelColor(33, 20)
    check(z.blue() > 150 or z.green() > 150, "senza logo resta il badge a lettera colorato")

    # scelto a mano: non si rinnova
    man = os.path.join(WORK, "mio.png")
    with open(man, "wb") as fh:
        fh.write(png(64, "#123456"))
    logos.set_manual(s, man)
    check(not logos.needs_fetch(s), "logo scelto a mano: non viene più cercato")

    # dove cercare
    def cand(**kw):
        return logos.candidates(Site(**kw))
    check(cand(host="cpanel.pietrodefilippis.it", name="Pietro") == ["https://pietrodefilippis.it"], "cpanel. tolto")
    check(cand(host="ftp.www.esempio.it", name="x") == ["https://esempio.it"], "ftp. e www. tolti")
    check(cand(host="hostingssd101.netsons.net", name="almacolorificio") == [],
          "server del provider e nome non dominio: nessun dominio indovinato (niente .it/.com)")
    check(cand(host="hostingssd101.netsons.net", name="almacolorificio.it") == ["https://almacolorificio.it"],
          "server del provider: il nome del sito è un dominio scritto dall'utente")
    check(cand(host="5.6.7.8", name="graziavecchione.it") == ["https://graziavecchione.it"], "IP: il nome è un dominio")
    check(cand(host="5.6.7.8", name="Sito di prova lungo con spazi e parole") == [], "IP e nome non dominio: niente")
    check(cand(host="h.netsons.net", name="x", website="www.miosito.it") == ["https://www.miosito.it"],
          "campo Sito web: vince lui")

    # scheda del sito: suggerimento se non trovato, ricerca subito quando si scrive il sito web
    from tkftp.sitemanager import SiteManager
    from tkftp.sites import SiteStore
    st = SiteStore()
    st.upsert(f, None)
    calls = []
    dlg = SiteManager(None, st, {"logo": lambda site, force: calls.append((site.website, force))}, f.id)
    dlg.show()
    QApplication.processEvents()
    check("NON TROVATO" in dlg.l_web.text(), "scheda: «Logo non trovato: scrivi l'indirizzo del sito»")
    dlg.f_web.setText("rcpelletteriaitaliana.it")
    dlg._changed()
    dlg._flush()
    check(calls == [("rcpelletteriaitaliana.it", True)], f"sito web scritto: logo cercato subito ({calls})")
    dlg.close()

    # opzione spenta: nessuna richiesta di rete (tramite la finestra principale)
    from tkftp.app import MainWindow
    from tkftp.util import Settings
    cfg = Settings()
    cfg.setValue("show_logos", False)
    cfg.setValue("fz_asked", True)
    cfg.setValue("last_check", time.time())
    win = MainWindow(cfg)
    win.request_logo(Site(name="Prima", host="x", website=base + "/a/"), force=True)
    check(not win._logo_pending, "prima della risposta al benvenuto: nessuna ricerca di loghi")
    win.rete = True  # come dopo il benvenuto (avvio)
    before = len(HITS)
    t = Site(name="Spento", host="spento.example", website=base + "/d/")
    win.store.upsert(t, None)
    win.request_logo(t, force=True)
    win._request_all_logos()
    t0 = time.time()
    while time.time() - t0 < 2.5:
        QApplication.processEvents()
        time.sleep(0.05)
    check(len(HITS) == before and not logos.logo_file(t.id), "opzione spenta: nessuna richiesta di rete")
    style.LOGOS["enabled"] = True
    win.request_logo(Site(name="Acceso", host="x", website=base + "/a/"), force=True)
    t0 = time.time()
    while time.time() - t0 < 5 and len(HITS) == before:
        QApplication.processEvents()
        time.sleep(0.05)
    check(len(HITS) > before, "opzione accesa: la ricerca parte in background")
    win.closing_for_update = True
    win.close()
    win.tm.shutdown()
    srv.shutdown()
    shutil.rmtree(WORK, ignore_errors=True)
    _ = (io, Qt, app)
    print("LOGHI OK" if not FAILS else f"LOGHI FALLITO: {FAILS}", flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
