"""Gestore siti: siti e gruppi in «Dati/siti.json». Le password stanno nel portachiavi del sistema (vault)."""
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields

from tkftp import vault
from tkftp.util import data_dir

# protocolli come in FileZilla (numero = <Protocol> di sitemanager.xml)
PROTOCOLS = [
    ("ftp", "FTP · TLS esplicito se disponibile", 0),
    ("ftps", "FTPS · TLS esplicito obbligatorio", 4),
    ("ftps-implicit", "FTPS · TLS implicito (porta 990)", 3),
    ("ftp-plain", "FTP · solo in chiaro (non sicuro)", 6),
    ("sftp", "SFTP · SSH", 1),
]
PROTOCOL_LABEL = {k: lab for k, lab, _ in PROTOCOLS}
PROTOCOL_SHORT = {"ftp": "FTP", "ftps": "FTPS", "ftps-implicit": "FTPS", "ftp-plain": "FTP", "sftp": "SFTP"}

# tipi di accesso come in FileZilla (<Logontype>: 0 anonimo, 1 normale, 2 chiedi, 3 interattivo, 5 file chiave)
LOGONS = [
    ("normal", "Normale (utente e password)"),
    ("ask", "Chiedi la password a ogni connessione"),
    ("key", "File chiave (solo SFTP)"),
    ("anonymous", "Anonimo"),
]
LOGON_LABEL = dict(LOGONS)


def default_port(protocol):
    return {"sftp": 22, "ftps-implicit": 990}.get(protocol, 21)


@dataclass
class Site:
    name: str = ""
    host: str = ""
    port: int = 21
    protocol: str = "ftp"
    logon: str = "normal"
    user: str = ""
    keyfile: str = ""
    remote_dir: str = ""
    local_dir: str = ""
    passive: bool = True
    notes: str = ""
    group: str = ""
    website: str = ""   # indirizzo del sito, per il logo (vuoto = dedotto da host/nome)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_used: float = 0.0
    # password solo in memoria (mai scritta in siti.json): si legge/scrive nel vault con get/set_password
    password: str = field(default="", repr=False, compare=False)

    @property
    def title(self):
        return self.name.strip() or self.host

    @property
    def secure(self):
        return self.protocol in ("sftp", "ftps", "ftps-implicit")

    def key(self):
        """Identità del sito per riconoscerlo tra importazioni diverse (FileZilla non ha un id)."""
        return (self.host.strip().lower(), int(self.port or 0), self.user.strip(), PROTOCOL_SHORT.get(self.protocol, ""))

    def to_json(self):
        d = asdict(self)
        d.pop("password", None)
        return d

    @classmethod
    def from_json(cls, d):
        names = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in d.items() if k in names and k != "password"})
        s.port = int(s.port or default_port(s.protocol))
        return s

    def copy(self):
        c = Site.from_json(self.to_json())
        c.password = self.password
        return c


def _account(site_id):
    return f"sito:{site_id}"


class SiteStore:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "siti.json")
        self.sites = []
        self.groups = []
        self.listeners = []
        self._lock = threading.Lock()
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            d = {}
        self.sites = [Site.from_json(x) for x in d.get("siti", [])]
        self.groups = list(d.get("gruppi", []))

    def save(self, notify=True):
        with self._lock:
            groups = sorted(set(self.groups) | {s.group for s in self.sites if s.group}, key=str.lower)
            self.groups = groups
            data = {"versione": 1, "gruppi": groups, "siti": [s.to_json() for s in self.sites]}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        if notify:
            for fn in list(self.listeners):
                try:
                    fn()
                except Exception:
                    pass

    def get(self, site_id):
        return next((s for s in self.sites if s.id == site_id), None)

    def find_match(self, other):
        k = other.key()
        return next((s for s in self.sites if s.key() == k), None)

    def upsert(self, site, password=None):
        """Aggiunge o aggiorna un sito; password: None = non toccarla, "" = cancellarla."""
        cur = self.get(site.id)
        if cur is None:
            self.sites.append(site)
        else:
            self.sites[self.sites.index(cur)] = site
        if password is not None:
            set_password(site, password)
        self.save()
        return site

    def delete(self, site_id):
        s = self.get(site_id)
        if s:
            self.sites.remove(s)
            try:
                vault.delete_secret(_account(site_id))
            except Exception:
                pass
            self.save()

    def rename_group(self, old, new):
        new = new.strip().strip("/")
        for s in self.sites:
            if s.group == old or s.group.startswith(old + "/"):
                s.group = new + s.group[len(old):]
        self.groups = [new + g[len(old):] if (g == old or g.startswith(old + "/")) else g for g in self.groups]
        self.save()

    def delete_group(self, name):
        """Toglie il gruppo: i suoi siti passano al gruppo superiore."""
        parent = name.rsplit("/", 1)[0] if "/" in name else ""
        for s in self.sites:
            if s.group == name:
                s.group = parent
            elif s.group.startswith(name + "/"):
                s.group = parent + ("/" if parent else "") + s.group[len(name) + 1:]
        self.groups = [g for g in self.groups if g != name and not g.startswith(name + "/")]
        self.save()

    def merge(self, imported, overwrite=True):
        """Unisce siti importati (FileZilla, cartella condivisa). Ritorna (aggiunti, aggiornati)."""
        added = updated = 0
        for imp in imported:
            cur = self.find_match(imp)
            if cur is None:
                self.sites.append(imp)
                if imp.password:
                    set_password(imp, imp.password)
                added += 1
            elif overwrite:
                changed = False
                for f in ("name", "group", "logon", "keyfile", "remote_dir", "local_dir", "passive", "notes", "protocol",
                          "website"):
                    v = getattr(imp, f)
                    if v != getattr(cur, f) and (v or f in ("passive",)):
                        setattr(cur, f, v)
                        changed = True
                if imp.password and imp.password != get_password(cur):
                    set_password(cur, imp.password)
                    changed = True
                updated += int(changed)
        self.save()
        return added, updated

    def touch(self, site):
        import time
        s = self.get(site.id)
        if s:
            s.last_used = time.time()
            self.save(notify=False)

    def recent(self, n=6):
        return sorted([s for s in self.sites if s.last_used], key=lambda s: -s.last_used)[:n]


def get_password(site):
    try:
        return vault.get_secret(_account(site.id)) or ""
    except Exception:
        return ""


def set_password(site, password):
    if password:
        vault.set_secret(_account(site.id), password)
    else:
        try:
            vault.delete_secret(_account(site.id))
        except Exception:
            pass
