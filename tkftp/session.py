"""Sessione di navigazione: una connessione in un thread suo, con una coda di lavori (elenco, nuova cartella,
rinomina, elimina, permessi). Se la connessione cade, si ricollega da sola e riprova una volta.
Le risposte arrivano con ok(risultato) / err(eccezione) DAL THREAD della sessione: l'interfaccia le riporta
sul suo thread (vedi ui.Bridge)."""
import queue
import threading

from tkftp import listing
from tkftp.remote import RemoteError, make_client
from tkftp.transfers import _retryable


class RemoteSession:
    def __init__(self, site, password="", passphrase="", log=None):
        self.site = site
        self.password = password
        self.passphrase = passphrase
        self.logfn = log
        self.client = None
        self.home = "/"
        self.closed = False
        self._q = queue.Queue()
        self._t = threading.Thread(target=self._loop, daemon=True, name="sessione")
        self._t.start()

    def _log(self, kind, text):
        if self.logfn:
            try:
                self.logfn(kind, text)
            except Exception:
                pass

    # ------------------------------------------------------------------ API
    def submit(self, fn, ok=None, err=None):
        """fn(client) gira nel thread della sessione (connessa)."""
        self._q.put((fn, ok, err))

    def connect(self, ok=None, err=None):
        self._q.put(("connect", ok, err))

    def close(self):
        self.closed = True
        self._q.put(None)

    @property
    def connected(self):
        return self.client is not None

    # ------------------------------------------------------------------ thread
    def _do_connect(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        c = make_client(self.site, self.password, self._log, self.passphrase)
        c.connect()
        self.client = c
        self.home = c.home
        return c.home

    def _loop(self):
        while True:
            try:
                job = self._q.get(timeout=40)
            except queue.Empty:
                self._keepalive()
                continue
            if job is None:
                break
            fn, ok, err = job
            try:
                if fn == "connect":
                    res = self._do_connect()
                else:
                    res = self._run(fn)
            except Exception as exc:  # noqa: BLE001
                if err:
                    err(exc)
                continue
            if ok:
                ok(res)
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self._log("status", "Disconnesso.")

    def _run(self, fn):
        if self.client is None:
            self._log("status", "Mi ricollego al server…")
            self._do_connect()
            return fn(self.client)
        try:
            return fn(self.client)
        except RemoteError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not _retryable(exc):
                raise
            self._log("error", "Connessione persa: mi ricollego…")
            self._do_connect()
            return fn(self.client)

    def _keepalive(self):
        if self.client is None or self.closed:
            return
        try:
            self.client.noop()
        except Exception:  # noqa: BLE001
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None  # al prossimo lavoro si ricollega


def _same_path(a, b):
    return (a or "/").rstrip("/") == (b or "/").rstrip("/")


def scan_tree(client, path, is_dir, log=None):
    """Elenco di cosa c'è da toccare sotto «path», nell'ordine giusto per eliminare (prima il contenuto, poi la
    cartella): [(percorso, tipo)] con tipo «file», «dir» o «link». Prima di scendere in una cartella si controlla
    sul server il suo percorso vero (FTP: CWD + PWD; SFTP: realpath): se non è quello atteso la «cartella» è un
    collegamento nascosto (alcuni server lo elencano come cartella) e non si scende dentro: si tocca solo il
    collegamento, mai i file a cui punta."""
    if not is_dir:
        return [(path, "file")]
    out = []
    real_of = getattr(client, "real_path", None)
    parent_real = None
    if real_of is not None:
        try:
            parent_real = real_of(listing.parent(path))
        except Exception:  # noqa: BLE001 - cartella superiore non leggibile: si controlla solo dentro
            parent_real = None

    def walk(p, expected_real):
        if real_of is not None:
            real = real_of(p)
            if expected_real is not None and not _same_path(real, expected_real):
                if log:
                    log("status", f"{p} porta a {real}: è un collegamento, non entro")
                out.append((p, "link"))
                return
        else:
            real = None
        for e in sorted(client.listdir(p), key=lambda x: x.name.lower()):
            child = listing.join(p, e.name)
            if e.is_link:
                out.append((child, "link"))
            elif e.is_dir:
                walk(child, listing.join(real, e.name) if real is not None else None)
            else:
                out.append((child, "file"))
        out.append((p, "dir"))

    walk(path, listing.join(parent_real, listing.basename(path)) if parent_real is not None else None)
    return out


def count_plan(plan):
    """(file, cartelle) di un elenco di scan_tree (i collegamenti contano come file)."""
    dirs = sum(1 for _p, k in plan if k == "dir")
    return len(plan) - dirs, dirs


def delete_plan(client, plan):
    """Elimina esattamente gli elementi elencati (e mostrati all'utente) da scan_tree."""
    for p, kind in plan:
        if kind == "dir":
            client.rmdir(p)
        else:
            client.delete(p)  # un collegamento si elimina come un file: il suo contenuto resta dov'è
    return len(plan)


def delete_tree(client, path, is_dir, log=None):
    """Elimina file o cartella (con tutto il contenuto, senza mai seguire i collegamenti)."""
    return delete_plan(client, scan_tree(client, path, is_dir, log))
