"""Gestore siti di FileZilla (sitemanager.xml): importazione, esportazione e file della cartella condivisa.

Formato FileZilla 3: <FileZilla3><Servers> con <Server> e <Folder>nome<Server>…</Folder> annidati.
Il file della cartella condivisa è lo stesso formato; se contiene le password, sono cifrate così
(lo schema è scritto anche nella memoria del progetto, per l'app telefono):
  <TkFtp versione="1" cifratura="pbkdf2-sha256+aes-256-gcm" iterazioni="200000" sale="B64" controllo="B64"/>
  nel <Server>: niente <Pass>, al suo posto <TkPass>B64</TkPass>
  chiave = PBKDF2-HMAC-SHA256(frase segreta UTF-8, sale (16 byte), iterazioni, 32 byte)
  TkPass e controllo = base64( nonce (12 byte) || testo cifrato || tag GCM (16 byte) ), AES-256-GCM senza AAD
  controllo = cifratura della parola «tk-ftp»: se si decifra, la frase segreta è giusta.
"""
import base64
import os
import xml.etree.ElementTree as ET

from tkftp.sites import Site, default_port
from tkftp.util import IS_MAC, IS_WIN

PROTO_FROM_FZ = {"0": "ftp", "1": "sftp", "3": "ftps-implicit", "4": "ftps", "6": "ftp-plain"}
PROTO_TO_FZ = {"ftp": "0", "sftp": "1", "ftps-implicit": "3", "ftps": "4", "ftp-plain": "6"}
LOGON_TO_FZ = {"anonymous": "0", "normal": "1", "ask": "2", "key": "5"}
CHECK_WORD = b"tk-ftp"
ITERATIONS = 200_000


class ImportResult:
    def __init__(self):
        self.sites = []
        self.skipped = 0          # protocolli non supportati (HTTP, S3, …)
        self.locked = 0           # password protette dalla password principale di FileZilla
        self.encrypted = False    # file con password cifrate da tk-ftp (serve la frase segreta)
        self.wrong_phrase = False
        self.phone_export = False
        self.old_phone = 0        # password solo in base64 dalle app telefono vecchie: va rifatta l'esportazione


def installed_sitemanager():
    """Percorso di sitemanager.xml di FileZilla installato su questo computer, se c'è."""
    cands = []
    if IS_WIN:
        cands.append(os.path.join(os.environ.get("APPDATA", ""), "FileZilla", "sitemanager.xml"))
    else:
        home = os.path.expanduser("~")
        cands.append(os.path.join(home, ".config", "filezilla", "sitemanager.xml"))
        if IS_MAC:
            cands.append(os.path.join(home, "Library", "Application Support", "FileZilla", "sitemanager.xml"))
    return next((p for p in cands if p and os.path.isfile(p)), "")


# --------------------------------------------------------------------------- cartelle remote (RemoteDir)
def decode_remote_dir(raw):
    """FileZilla salva le cartelle come «tipo lungh_prefisso [prefisso] (lungh segmento)…», es. «1 0 3 www 6 public»
    = /www/public. Accetta anche il formato delle prime app tk-ftp per telefono («1 N l1 s1 …», N = segmenti)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw[0].isdigit():
        return raw  # già un percorso
    parsed = _parse_safe_path(raw)
    if parsed is not None:
        return parsed
    try:  # formato dell'app telefono
        t = raw.split(" ")
        n, i, parts = int(t[1]), 2, []
        for _ in range(n):
            ln = int(t[i])
            parts.append(t[i + 1][:ln])
            i += 2
        return "/" + "/".join(parts)
    except (ValueError, IndexError):
        return ""


def _parse_safe_path(raw):
    pos = 0

    def read_int():
        nonlocal pos
        j = pos
        while j < len(raw) and raw[j].isdigit():
            j += 1
        if j == pos:
            raise ValueError
        v = int(raw[pos:j])
        pos = j
        return v

    def expect_space():
        nonlocal pos
        if pos >= len(raw) or raw[pos] != " ":
            raise ValueError
        pos += 1

    try:
        kind = read_int()
        expect_space()
        plen = read_int()
        prefix = ""
        if plen:
            expect_space()
            prefix = raw[pos:pos + plen]
            pos += plen
        segs = []
        while pos < len(raw):
            expect_space()
            ln = read_int()
            expect_space()
            if pos + ln > len(raw):
                raise ValueError
            segs.append(raw[pos:pos + ln])
            pos += ln
    except ValueError:
        return None
    if kind == 3 or (prefix and prefix.endswith(":")):  # DOS: C:\a\b
        return (prefix + "\\" + "\\".join(segs)) if prefix else "\\".join(segs)
    return "/" + "/".join(segs)


def encode_remote_dir(path):
    path = (path or "").strip()
    if not path or path == "/":
        return "1 0" if path == "/" else ""
    segs = [s for s in path.replace("\\", "/").split("/") if s]
    return "1 0" + "".join(f" {len(s)} {s}" for s in segs)


# --------------------------------------------------------------------------- cifratura delle password condivise
def _derive(phrase, salt, iterations=ITERATIONS):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(
        phrase.encode("utf-8"))


def _seal(key, data):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, data, None)).decode("ascii")


def _open(key, blob):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


# --------------------------------------------------------------------------- importazione
def _text(e, tag):
    x = e.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse(data, phrase=None):
    """Legge sitemanager.xml (bytes o str). phrase = frase segreta per le password cifrate da tk-ftp."""
    res = ImportResult()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"il file non è un XML valido ({exc})")
    servers = root.find("Servers") if root.tag == "FileZilla3" else (root if root.tag == "Servers" else None)
    if servers is None:
        raise ValueError("non è un Gestore siti di FileZilla (manca <Servers>)")
    # firma dell'export delle app tk-ftp per telefono fino alla 2.0.2 (FileZilla3 version 3.66.4, platform linux)
    res.phone_export = root.get("version") == "3.66.4" and root.get("platform") == "linux"
    key = None
    tk = root.find("TkFtp")
    if tk is not None and tk.get("sale"):
        res.encrypted = True
        if phrase:
            try:
                k = _derive(phrase, base64.b64decode(tk.get("sale")), int(tk.get("iterazioni") or ITERATIONS))
                if _open(k, tk.get("controllo", "")) == CHECK_WORD:
                    key = k
                else:
                    res.wrong_phrase = True
            except Exception:
                res.wrong_phrase = True

    def walk(node, group):
        for e in node:
            if e.tag == "Server":
                s = _site(e, group, res, key)
                if s is not None:
                    res.sites.append(s)
            elif e.tag == "Folder":
                name = (e.text or "").strip() or "Gruppo"
                walk(e, f"{group}/{name}" if group else name)

    walk(servers, "")
    return res


def _site(e, group, res, key):
    host = _text(e, "Host")
    if not host:
        return None
    proto = PROTO_FROM_FZ.get(_text(e, "Protocol") or "0")
    if proto is None:
        res.skipped += 1
        return None
    password = ""
    pe = e.find("Pass")
    if pe is not None and pe.text:
        enc = (pe.get("encoding") or "").lower()
        if enc == "base64":
            try:
                password = base64.b64decode(pe.text.strip()).decode("utf-8")
            except Exception:
                password = ""
        elif enc == "crypt":
            res.locked += 1
        elif _looks_base64(pe.text, res.phone_export):
            # le app tk-ftp per telefono fino alla 2.0.2 scrivevano la password in base64 SENZA encoding="base64"
            password = base64.b64decode(pe.text.strip()).decode("utf-8")
            res.old_phone += 1
        else:
            password = pe.text
    tkp = _text(e, "TkPass")
    if tkp and key is not None:
        try:
            password = _open(key, tkp).decode("utf-8")
        except Exception:
            pass
    lt = _text(e, "Logontype") or "1"
    logon = {"0": "anonymous", "1": "normal", "2": "ask", "3": "ask", "5": "key"}.get(lt, "normal")
    if lt == "4":  # «account» in FileZilla; le prime app tk-ftp per telefono lo usavano per «chiedi»
        logon = "normal" if password else "ask"
    keyfile = _text(e, "Keyfile")
    if keyfile and proto == "sftp" and logon not in ("anonymous",):
        logon = "key" if lt in ("5",) or not password else logon
    try:
        port = int(_text(e, "Port") or 0) or default_port(proto)
    except ValueError:
        port = default_port(proto)
    return Site(
        name=_text(e, "Name") or host, host=host, port=port, protocol=proto, logon=logon,
        user=_text(e, "User"), keyfile=keyfile, remote_dir=decode_remote_dir(_text(e, "RemoteDir")),
        local_dir=_text(e, "LocalDir"), passive=_text(e, "PasvMode") != "MODE_ACTIVE",
        notes=_text(e, "Comments"), group=group, password=password, website=_text(e, "TkWebsite"),
    )


def _looks_base64(text, phone_export):
    """Password senza attributo encoding: è base64 se il file viene dall'app telefono (firma del suo export) oppure
    se il testo è base64 valido con il riempimento «=» e diventa testo UTF-8 stampabile (una password vera in chiaro
    che finisce con «=» ed è base64 valida è praticamente impossibile)."""
    import binascii
    import re
    t = (text or "").strip()
    if not t or len(t) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", t):
        return False
    if not phone_export and not t.endswith("="):
        return False
    try:
        s = base64.b64decode(t, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return bool(s) and s.isprintable()


def read_file(path, phrase=None):
    with open(path, "rb") as fh:
        return parse(fh.read(), phrase)


# --------------------------------------------------------------------------- esportazione
def build(sites, passwords=None, include_passwords=False, phrase=None):
    """Crea il documento. passwords: dict id → password. Con phrase le password si cifrano (TkPass),
    altrimenti, se include_passwords, vanno in base64 come fa FileZilla."""
    passwords = passwords or {}
    root = ET.Element("FileZilla3", {"version": "3.70.6", "platform": "windows" if IS_WIN else "mac" if IS_MAC else "linux"})
    key = None
    if phrase:
        salt = os.urandom(16)
        key = _derive(phrase, salt)
        ET.SubElement(root, "TkFtp", {"versione": "1", "cifratura": "pbkdf2-sha256+aes-256-gcm",
                                      "iterazioni": str(ITERATIONS),
                                      "sale": base64.b64encode(salt).decode("ascii"),
                                      "controllo": _seal(key, CHECK_WORD)})
    servers = ET.SubElement(root, "Servers")
    folders = {"": servers}

    def folder(path):
        if path in folders:
            return folders[path]
        parent, _, name = path.rpartition("/")
        f = ET.SubElement(folder(parent), "Folder", {"expanded": "1"})
        f.text = name
        folders[path] = f
        return f

    def sub(parent, tag, text, attrs=None):
        x = ET.SubElement(parent, tag, attrs or {})
        x.text = text
        return x

    ordered = sorted(sites, key=lambda s: (s.group.lower(), s.title.lower()))
    for s in [x for x in ordered if not x.group] + [x for x in ordered if x.group]:
        srv = ET.SubElement(folder(s.group), "Server")
        sub(srv, "Host", s.host)
        sub(srv, "Port", str(s.port))
        sub(srv, "Protocol", PROTO_TO_FZ.get(s.protocol, "0"))
        sub(srv, "Type", "0")
        sub(srv, "User", s.user)
        pw = passwords.get(s.id, "")
        if pw and s.logon == "normal":
            if key is not None:
                sub(srv, "TkPass", _seal(key, pw.encode("utf-8")))
            elif include_passwords:
                sub(srv, "Pass", base64.b64encode(pw.encode("utf-8")).decode("ascii"), {"encoding": "base64"})
        if s.keyfile:
            sub(srv, "Keyfile", s.keyfile)
        sub(srv, "Logontype", LOGON_TO_FZ.get(s.logon, "1"))
        sub(srv, "PasvMode", "MODE_PASSIVE" if s.passive else "MODE_ACTIVE")
        sub(srv, "EncodingType", "Auto")
        sub(srv, "BypassProxy", "0")
        sub(srv, "Name", s.title)
        if s.notes:
            sub(srv, "Comments", s.notes)
        if s.local_dir:
            sub(srv, "LocalDir", s.local_dir)
        if s.remote_dir:
            sub(srv, "RemoteDir", encode_remote_dir(s.remote_dir))
        if getattr(s, "website", ""):
            sub(srv, "TkWebsite", s.website)  # campo di tk-ftp (FileZilla e il telefono lo ignorano)
        sub(srv, "SyncBrowsing", "0")
        sub(srv, "DirectoryComparison", "0")
    ET.indent(root, "    ")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + ET.tostring(root, encoding="utf-8")


def write_file(path, sites, passwords=None, include_passwords=False, phrase=None):
    data = build(sites, passwords, include_passwords, phrase)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
