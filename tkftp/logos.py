"""Logo dei siti (favicon / apple-touch-icon) al posto del badge a lettera.

Dove cercarlo: campo «Sito web» del sito; se è vuoto il dominio si deduce dall'host (via ftp., sftp., www., cpanel.…);
se l'host è un IP o un server del provider (hostingssd101.netsons.net…) si usa il NOME del sito solo se è già un
dominio («graziavecchione.it»): nessun dominio indovinato (niente «<nome>.it / .com»). Mai indirizzi locali o privati
(rete di casa, 127.0.0.1…), nemmeno dopo un redirect. Dalla home si leggono i <link rel="icon"> e
apple-touch-icon e si sceglie l'immagine più grande (PNG/SVG/ICO); ripiego /favicon.ico.
Cache in Dati/loghi (PNG 256 px + indice.json), rinnovata ogni 30 giorni; un logo scelto a mano non si rinnova.
Tutto bloccante: va chiamato fuori dal thread dell'interfaccia (LogoService in app.py)."""
import html.parser
import http.client
import ipaddress
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from tkftp.util import data_dir

REFRESH = 30 * 86400        # logo trovato: si rinnova dopo 30 giorni
RETRY_FAILED = 1 * 86400    # logo non trovato: si riprova dopo 1 giorno
# versione delle regole di ricerca: quando cambiano (nuova versione che trova più loghi) i fallimenti registrati
# con regole vecchie si ritentano SUBITO (1: tk-ftp 1.0.4; 2: 1.0.5 con 503/redirect/byte), i successi restano
RULES = 2
TIMEOUT = 6
MAX_BYTES = 2_000_000
SIZE = 256
PREFIXES = ("ftp.", "sftp.", "ftps.", "www.", "cpanel.", "ssh.", "webmail.", "mail.", "admin.", "panel.", "plesk.",
            "server.", "host.", "web.")
PROVIDERS = ("netsons.net", "aruba.it", "arubabusiness.it", "register.it", "siteground", "hostinger", "ovh.net",
             "keliweb", "serverplan", "amazonaws.com", "googleusercontent.com", "hetzner", "contabo", "vultr",
             "linode", "digitalocean", "cloudways", "your-server.de", "webhosting", "hostingssd", "dominiok",
             "altervista.org", "tophost.it", "netsonsdns", "seeweb.it", "ionos", "1and1", "godaddy", "bluehost",
             "secureserver.net", "fastweb", "infomaniak", "plesk.page")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tk-ftp (logo del sito)"
_lock = threading.Lock()


# --------------------------------------------------------------------------- dove cercare
def _is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _looks_provider(host):
    h = host.lower()
    if any(p in h for p in PROVIDERS):
        return True
    first = h.split(".")[0]
    return bool(re.search(r"\d", first)) and len(h.split(".")) >= 3  # srv123.…, hostingssd101.…, vps12345.…


def _strip(host):
    h = host.lower().strip().strip(".")
    changed = True
    while changed:
        changed = False
        for p in PREFIXES:
            if h.startswith(p) and h.count(".") >= 2:
                h = h[len(p):]
                changed = True
    return h


def _domain_like(text):
    t = text.strip().lower()
    t = re.sub(r"^https?://", "", t).split("/")[0]
    return t if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}", t or "") else ""


def candidates(site):
    """Indirizzi da provare, nell'ordine. Lista vuota = niente da cercare."""
    web = (getattr(site, "website", "") or "").strip()
    if web:
        return [web if re.match(r"^https?://", web, re.I) else "https://" + web.strip("/")]
    out = []
    host = (site.host or "").strip()
    if host and not _is_ip(host) and not _looks_provider(host) and "." in host:
        out.append("https://" + _strip(host))
    name = (site.name or "").strip()
    dom = _domain_like(name)
    if dom:  # il nome del sito è già un dominio scritto dall'utente (es. «graziavecchione.it»): niente da indovinare
        out.append("https://" + _strip(dom))
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- rete
ALLOW_LOCAL = False  # solo i collaudi (server finto su 127.0.0.1) lo accendono


def _public(ip):
    """Vero per un indirizzo di internet; falso per rete locale, loopback, link-local, riservati."""
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def _guarded_connection(address, *args, **kwargs):
    """socket.create_connection che si rifiuta di parlare con indirizzi locali o privati: vale per la home, per le
    icone e per ogni redirect (si controlla l'indirizzo vero a cui ci si collega, anche se il DNS cambia)."""
    import socket
    sock = socket.create_connection(address, *args, **kwargs)
    if not ALLOW_LOCAL:
        try:
            peer = sock.getpeername()[0]
        except OSError:
            peer = ""
        if not _public(peer):
            sock.close()
            raise ConnectionRefusedError(f"indirizzo locale o privato non ammesso per i loghi ({peer or address[0]})")
    return sock


class _HTTP(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _guarded_connection


class _HTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _guarded_connection


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTP, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPS, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Redirect solo verso http/https (niente file:, ftp:…), al massimo 5."""
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(newurl, code, "redirect non ammesso", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _opener():
    # niente proxy di sistema: il controllo dell'indirizzo vale sulla connessione vera
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(context=_ctx()),
                                       _Redirects())


def _get(url, limit=MAX_BYTES, accept_error_html=False):
    """GET con redirect seguiti (anche verso altri domini, mai verso indirizzi locali). Con accept_error_html anche
    le pagine con errore (503 manutenzione, 401/403/404) restituiscono il loro HTML: spesso hanno i <link rel=icon>."""
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError("indirizzo non ammesso")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        r = _opener().open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        ctype = err.headers.get("Content-Type", "") if err.headers else ""
        if not (accept_error_html and "html" in ctype.lower()):
            raise
        r = err
    with r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError("file troppo grande")
        return r.geturl(), r.headers.get("Content-Type", ""), data


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []
        self.base = ""

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and a.get("href"):
            self.base = a["href"]
        if tag != "link":
            return
        rel = a.get("rel", "").lower().split()
        if not a.get("href") or "mask-icon" in rel:
            return
        if "icon" in rel or "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
            self.icons.append((rel, a.get("sizes", ""), a.get("type", ""), a["href"]))


def _score(rel, sizes, typ, href):
    svg = "svg" in typ or href.lower().split("?")[0].endswith(".svg")
    if svg:
        return 1000
    best = 0
    for m in re.finditer(r"(\d+)\s*[xX]\s*(\d+)", sizes):
        best = max(best, min(int(m.group(1)), int(m.group(2))))
    if not best:
        best = 180 if any(r.startswith("apple-touch-icon") for r in rel) else 32
    return best


def icon_urls(page_url, html_text):
    p = _Links()
    try:
        p.feed(html_text)
    except Exception:
        pass
    base = urllib.parse.urljoin(page_url, p.base) if p.base else page_url
    ranked = sorted(p.icons, key=lambda x: -_score(*x))
    urls = [urllib.parse.urljoin(base, href) for _r, _s, _t, href in ranked]
    urls.append(urllib.parse.urljoin(base, "/favicon.ico"))
    return list(dict.fromkeys(urls))


def _decode(data, content_type, url):
    """bytes → QImage (la più grande se è un .ico con più misure, SVG disegnato a 256 px)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage, QImageReader, QPainter
    is_svg = "svg" in content_type or url.lower().split("?")[0].endswith(".svg") or data[:200].lstrip().startswith(b"<svg") \
        or b"<svg" in data[:2000]  # anche con un content-type sbagliato
    if is_svg:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtSvg import QSvgRenderer
            r = QSvgRenderer(QByteArray(data))
            if not r.isValid():
                return None
            img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            r.render(p)
            p.end()
            return img
        except ImportError:
            return None
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    best = None
    for i in range(max(1, reader.imageCount())):
        if i:
            reader.jumpToImage(i)
        img = reader.read()
        if not img.isNull() and (best is None or img.width() * img.height() > best.width() * best.height()):
            best = img
    return best if best is not None and best.width() >= 8 else None


def fetch(base_urls):
    """Cerca il logo partendo dagli indirizzi (home dei siti). Ritorna (QImage, url) oppure (None, "")."""
    for base in base_urls:
        try:
            page_url, ctype, data = _get(base, accept_error_html=True)
        except Exception:
            page_url, ctype, data = base, "", b""  # home irraggiungibile: si prova almeno /favicon.ico
        text = data.decode("utf-8", "replace") if ("html" in ctype or b"<html" in data[:2000].lower()) else ""
        for u in icon_urls(page_url, text):
            try:
                final, ct, img_data = _get(u)
            except Exception:
                continue
            img = _decode(img_data, ct, final)
            if img is not None:
                return img, final
    return None, ""


# --------------------------------------------------------------------------- cache su disco
def _dir():
    d = os.path.join(data_dir(), "loghi")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path():
    return os.path.join(_dir(), "indice.json")


def _load_index():
    try:
        with open(_index_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_index(d):
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)
    os.replace(tmp, _index_path())


def last_failed(site_id):
    """True se l'ultima ricerca automatica non ha trovato il logo (per il suggerimento nella scheda del sito)."""
    with _lock:
        e = _load_index().get(site_id)
    return bool(e) and not e.get("file") and not e.get("manuale")


def logo_file(site_id):
    p = os.path.join(_dir(), f"{site_id}.png")
    return p if os.path.isfile(p) else ""


def needs_fetch(site, now=None):
    now = now or time.time()
    with _lock:
        e = _load_index().get(site.id)
    if not e:
        return True
    if e.get("manuale"):
        return False
    key = (getattr(site, "website", "") or "", site.host, site.name)
    if e.get("chiave") != list(key):
        return True  # cambiato sito web / host / nome: si ricerca
    if not e.get("file") and int(e.get("regole", 1)) < RULES:
        return True  # fallito con regole di ricerca più vecchie: si riprova subito
    if e.get("file") and logo_file(site.id):
        return now - e.get("quando", 0) > REFRESH
    return now - e.get("quando", 0) > RETRY_FAILED


def _store(site, img, source, manual=False):
    from PySide6.QtCore import Qt
    if img is not None:
        if max(img.width(), img.height()) > SIZE:
            img = img.scaled(SIZE, SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img.save(os.path.join(_dir(), f"{site.id}.png"), "PNG")
    with _lock:
        d = _load_index()
        d[site.id] = {"quando": time.time(), "file": bool(img is not None), "fonte": source, "manuale": manual,
                      "regole": RULES,
                      "chiave": [getattr(site, "website", "") or "", site.host, site.name]}
        _save_index(d)


def update(site, force=False, base_urls=None):
    """Cerca e salva il logo del sito (bloccante). Ritorna il percorso del PNG o ""."""
    if not force and not needs_fetch(site):
        return logo_file(site.id)
    img, src = fetch(base_urls if base_urls is not None else candidates(site))
    if img is None and force is False and logo_file(site.id):
        _store(site, None, "")  # non trovato ora: si tiene quello vecchio
        return logo_file(site.id)
    if img is None:
        try:
            os.remove(os.path.join(_dir(), f"{site.id}.png"))
        except OSError:
            pass
    _store(site, img, src)
    return logo_file(site.id)


def set_manual(site, path):
    """Immagine scelta dall'utente: non viene più cercata né rinnovata."""
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        raise ValueError("immagine non leggibile")
    _store(site, img, "manuale", manual=True)
    return logo_file(site.id)


def forget(site_id):
    with _lock:
        d = _load_index()
        d.pop(site_id, None)
        _save_index(d)
    try:
        os.remove(os.path.join(_dir(), f"{site_id}.png"))
    except OSError:
        pass
