"""Modifica al volo: il file remoto scaricato in una cartella temporanea viene controllato; quando cambia
(salvato dall'editor) e resta fermo per un attimo, la finestra principale chiede o ricarica da sola."""
import os
import re
import time

from tkftp.util import temp_edit_dir


def local_copy_path(site, remote):
    parts = [p for p in remote.split("/") if p]
    safe = [re.sub(r'[<>:"\\|?*\x00-\x1f]', "_", p).rstrip(" .") or "_" for p in parts]
    host = re.sub(r"[^A-Za-z0-9._-]", "_", site.host)
    return os.path.join(temp_edit_dir(), f"{host}-{site.id[:6]}", *safe)


class Watched:
    def __init__(self, local, remote, site, password="", passphrase=""):
        self.local = local
        self.remote = remote
        self.site = site
        self.password = password
        self.passphrase = passphrase
        self.base = self._sig()
        self.last = self.base
        self.always = False
        self.busy = False          # caricamento in corso o domanda aperta
        self.state = "Aperto"
        self.when = time.time()
        self.dirty = False         # modifiche salvate ma non caricate

    def _sig(self):
        try:
            st = os.stat(self.local)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    @property
    def name(self):
        return os.path.basename(self.local)


class EditWatcher:
    def __init__(self):
        self.files = {}

    def add(self, w):
        old = self.files.get(w.local)
        if old is not None:
            w.always = old.always
        self.files[w.local] = w
        return w

    def get(self, local):
        return self.files.get(local)

    def remove(self, w):
        self.files.pop(w.local, None)

    def poll(self):
        """File cambiati e fermi da almeno un controllo (l'editor ha finito di scrivere)."""
        out = []
        for w in list(self.files.values()):
            sig = w._sig()
            if sig is None or w.busy:
                w.last = sig
                continue
            if sig != w.base and sig == w.last:
                out.append(w)
            w.last = sig
        return out

    def accept_current(self, w):
        """Lo stato attuale del file diventa quello «già sul server» (dopo il caricamento o un «Non ora»)."""
        w.base = w._sig()
        w.last = w.base
