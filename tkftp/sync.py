"""Cartella condivisa col telefono: tk-ftp tiene i siti nel file «tk-ftp-siti.xml» (formato FileZilla) in una
cartella scelta dall'utente (es. Dropbox). Se le password sono incluse, sono cifrate con la frase segreta
(schema in filezilla.py). Se il file cambia da fuori (un altro computer, il telefono), i siti nuovi o cambiati
entrano nel gestore; le cancellazioni fatte altrove non si propagano."""
import os

from tkftp import filezilla, vault
from tkftp.sites import get_password

SHARED_NAME = "tk-ftp-siti.xml"
PHRASE_ACCOUNT = "frase-cartella-condivisa"


def get_phrase():
    try:
        return vault.get_secret(PHRASE_ACCOUNT) or ""
    except Exception:
        return ""


def set_phrase(phrase):
    if phrase:
        vault.set_secret(PHRASE_ACCOUNT, phrase)
    else:
        try:
            vault.delete_secret(PHRASE_ACCOUNT)
        except Exception:
            pass


class SharedSync:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    @property
    def folder(self):
        return self.settings.value("shared_dir", "") or ""

    def path(self):
        return os.path.join(self.folder, SHARED_NAME) if self.folder else ""

    def enabled(self):
        return bool(self.folder) and os.path.isdir(self.folder)

    def write(self):
        if not self.enabled():
            return False
        phrase = get_phrase() if self.settings.value("shared_pw", False) else ""
        passwords = {s.id: get_password(s) for s in self.store.sites} if phrase else {}
        filezilla.write_file(self.path(), self.store.sites, passwords, include_passwords=False, phrase=phrase or None)
        self.settings.setValue("shared_mtime", os.path.getmtime(self.path()))
        return True

    def check(self):
        """Se il file è stato cambiato da fuori lo legge e unisce i siti. Ritorna (aggiunti, aggiornati, avviso)."""
        if not self.enabled():
            return None
        p = self.path()
        if not os.path.isfile(p):
            self.write()
            return None
        mtime = os.path.getmtime(p)
        if mtime <= float(self.settings.value("shared_mtime", 0) or 0) + 0.5:
            return None
        res = filezilla.read_file(p, get_phrase() or None)
        self.settings.setValue("shared_mtime", mtime)
        added, updated = self.store.merge(res.sites)
        warn = ""
        if res.encrypted and res.wrong_phrase:
            warn = "Le password della cartella condivisa sono cifrate con un'altra frase segreta: non le ho lette."
        elif res.encrypted and not get_phrase():
            warn = "La cartella condivisa contiene password cifrate: scrivi la frase segreta nelle Impostazioni."
        elif res.old_phone:
            warn = ("La cartella condivisa contiene password solo codificate (app tk-ftp per telefono vecchia): "
                    "aggiorna l'app e rifai l'esportazione con la frase segreta.")
        return added, updated, warn
