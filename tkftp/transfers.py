"""Coda trasferimenti: più trasferimenti in parallelo (ogni thread ha la sua connessione), ripresa dei file
interrotti, domanda se il file esiste già, cartelle intere. Niente Qt qui: l'interfaccia passa delle funzioni.
I file non si scrivono mai direttamente col nome vero: si scaricano in «<nome>.part» e si caricano su
«<nome>.tkpart», poi si rinominano a trasferimento completo (un'interruzione non lascia file troncati)."""
import ftplib
import itertools
import os
import shutil
import socket
import threading
import time

from tkftp import listing
from tkftp.remote import Cancelled, RemoteError, friendly_error, make_client

PART = ".part"          # scaricamento in corso sul computer
TMP_UP = ".tkpart"      # caricamento in corso sul server
WAITING, RUNNING, DONE, FAILED, CANCELLED, SKIPPED = "attesa", "corso", "fatto", "errore", "annullato", "saltato"
STATUS_LABEL = {WAITING: "In coda", RUNNING: "In corso", DONE: "Completato", FAILED: "Non riuscito",
                CANCELLED: "Annullato", SKIPPED: "Saltato"}
POLICIES = ("ask", "overwrite", "newer", "resume", "skip")
_ids = itertools.count(1)


class Item:
    def __init__(self, direction, local, remote, site, password="", passphrase="", size=0, is_dir=False,
                 force=None, on_done=None, mtime=0.0, tag=None):
        self.id = next(_ids)
        self.direction = direction          # "up" = carica sul server, "down" = scarica
        self.local = local
        self.remote = remote
        self.site = site
        self.password = password
        self.passphrase = passphrase
        self.size = size
        self.mtime = mtime                  # data della sorgente, per «sovrascrivi se più recente»
        self.is_dir = is_dir
        self.force = force                  # azione imposta (es. «overwrite» per la modifica al volo)
        self.on_done = on_done
        self.tag = tag                      # gruppo (es. un trascinamento verso Esplora file): si aspetta tutto il gruppo
        self.expect = None                  # (dimensione, data) del file sul server quando è stato scaricato:
        #                                     se al caricamento è diverso si chiede prima di sovrascrivere
        self.track = False                  # dopo il trasferimento legge com'è il file sul server (remote_after)
        self.remote_after = None
        self.done = 0
        self.offset = 0
        self.status = WAITING
        self.error = ""
        self.speed = 0.0
        self.started = 0.0
        self.finished = 0.0
        self.attempts = 0
        self.cancel_flag = False
        self._samples = []

    @property
    def name(self):
        return os.path.basename(self.local) if self.direction == "up" else listing.basename(self.remote)

    @property
    def fraction(self):
        if self.status == DONE:
            return 1.0
        return min(1.0, self.done / self.size) if self.size else 0.0

    def _sample(self, n):
        now = time.monotonic()
        self.done += n
        self._samples.append((now, self.done))
        # tiene gli ultimi 3 secondi + un campione più vecchio come base (i server lenti mandano a raffiche)
        while len(self._samples) > 2 and now - self._samples[1][0] > 3.0:
            self._samples.pop(0)

    @property
    def speed(self):
        """Byte al secondo negli ultimi secondi, calcolata quando la si legge (anche tra una raffica e l'altra)."""
        if self.status != RUNNING or not self._samples:
            return 0.0
        t0, d0 = self._samples[0]
        dt = time.monotonic() - t0
        return (self.done - d0) / dt if dt > 0.3 else 0.0

    @speed.setter
    def speed(self, _value):
        pass


def _retryable(exc):
    if isinstance(exc, ftplib.error_temp):
        return True
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, EOFError)):
        return True
    try:
        import paramiko
        if isinstance(exc, paramiko.SSHException):
            return True
    except ImportError:
        pass
    return isinstance(exc, OSError) and not isinstance(exc, (FileNotFoundError, PermissionError))


def _connection_lost(client, exc):
    """Vero se l'errore è la connessione caduta (si riprova), falso se il server ha solo rifiutato il comando
    (es. SFTP «Failure» su una rinomina: è un OSError come una rete caduta, lo distingue la connessione viva)."""
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, EOFError, ftplib.error_temp)):
        return True
    if isinstance(exc, (ftplib.error_perm, ftplib.error_reply, RemoteError)):
        return False
    alive = getattr(client, "alive", None)
    if alive is not None:
        try:
            return not alive()
        except Exception:  # noqa: BLE001
            return True
    return _retryable(exc)


def _same_remote(e, expect):
    """Il file sul server è ancora quello scaricato? Stessa dimensione e (se le date sono note) stessa data."""
    size, mtime = expect
    if e.size != size:
        return False
    return not (mtime and e.mtime) or abs(e.mtime - mtime) <= 2


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def free_name(path, exists):
    base, ext = os.path.splitext(path)
    for i in itertools.count(1):
        cand = f"{base} ({i}){ext}"
        if not exists(cand):
            return cand


class TransferManager:
    def __init__(self, parallel=2, ask_overwrite=None, log=None, changed=None, policy="ask", ask_changed=None):
        self.items = []
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.parallel = max(1, int(parallel))
        self.ask_overwrite = ask_overwrite  # fn(item, src_entry, dst_entry) -> (azione, per_tutti)
        self.ask_changed = ask_changed      # fn(item, entry sul server) -> True = sovrascrivi lo stesso
        self.logfn = log
        self.changed = changed              # fn(item) dal thread del trasferimento
        self.policy = policy
        self._apply_all = None
        self._ask_lock = threading.Lock()
        self._threads = []
        self._stop = False
        self._clients = {}                  # thread → (chiave sito, client, ultimo uso)
        self._ensure_threads()

    # ------------------------------------------------------------------ API
    def add(self, items):
        with self.lock:
            self.items.extend(items)
            self._apply_all = None if not self.running_count() else self._apply_all
            self.wake.notify_all()

    def set_parallel(self, n):
        with self.lock:
            self.parallel = max(1, min(10, int(n)))
            self._ensure_threads()
            self.wake.notify_all()

    def cancel(self, item):
        with self.lock:
            if item.status in (WAITING, RUNNING):
                item.cancel_flag = True
                if item.status == WAITING:
                    item.status = CANCELLED
                    self._notify(item)

    def cancel_all(self):
        with self.lock:
            for it in self.items:
                if it.status in (WAITING, RUNNING):
                    it.cancel_flag = True
                    if it.status == WAITING:
                        it.status = CANCELLED

    def retry(self, item):
        with self.lock:
            if item.status in (FAILED, CANCELLED, SKIPPED):
                item.status, item.error, item.cancel_flag, item.attempts = WAITING, "", False, 0
                item.done = 0
                self.wake.notify_all()
                self._notify(item)

    def remove(self, items):
        with self.lock:
            for it in items:
                if it.status not in (RUNNING,) and it in self.items:
                    self.items.remove(it)

    def clear(self, statuses):
        with self.lock:
            self.items = [it for it in self.items if it.status not in statuses]

    def running_count(self):
        return sum(1 for it in self.items if it.status == RUNNING)

    def group_items(self, tag):
        with self.lock:
            return [it for it in self.items if it.tag == tag]

    def group_pending(self, tag):
        return any(it.status in (WAITING, RUNNING) for it in self.group_items(tag))

    def pending_count(self):
        return sum(1 for it in self.items if it.status in (WAITING, RUNNING))

    def shutdown(self):
        with self.lock:
            self._stop = True
            self.cancel_all()
            self.wake.notify_all()
        for t in self._threads:
            t.join(timeout=3)
        for _k, client, _t in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ thread
    def _ensure_threads(self):
        while len(self._threads) < self.parallel:
            t = threading.Thread(target=self._worker, args=(len(self._threads),), daemon=True,
                                 name=f"trasferimento-{len(self._threads) + 1}")
            self._threads.append(t)
            t.start()

    def _log(self, kind, text):
        if self.logfn:
            try:
                self.logfn(kind, text)
            except Exception:
                pass

    def _notify(self, item):
        if self.changed:
            try:
                self.changed(item)
            except Exception:
                pass

    def _next(self, slot):
        with self.lock:
            while True:
                if self._stop:
                    return None
                if slot < self.parallel:
                    for it in self.items:
                        if it.status == WAITING and not it.cancel_flag:
                            it.status = RUNNING
                            it.started = time.time()
                            return it
                self.wake.wait(timeout=20)
                if not self._stop:
                    self._close_idle(slot)

    def _close_idle(self, slot):
        cur = self._clients.get(slot)
        if cur and time.time() - cur[2] > 60:
            try:
                cur[1].close()
            except Exception:
                pass
            self._clients.pop(slot, None)

    def _client(self, slot, item):
        key = (item.site.id, item.site.key(), item.password)
        cur = self._clients.get(slot)
        if cur and cur[0] == key:
            self._clients[slot] = (key, cur[1], time.time())
            return cur[1]
        if cur:
            try:
                cur[1].close()
            except Exception:
                pass
        c = make_client(item.site, item.password, lambda k, t: self._log(k, t), item.passphrase)
        c.connect()
        self._clients[slot] = (key, c, time.time())
        return c

    def _drop_client(self, slot):
        cur = self._clients.pop(slot, None)
        if cur:
            try:
                cur[1].close()
            except Exception:
                pass

    def _worker(self, slot):
        while True:
            item = self._next(slot)
            if item is None:
                return
            self._notify(item)
            while True:
                item.attempts += 1
                try:
                    client = self._client(slot, item)
                    self._run(client, item)
                    if item.status == RUNNING:
                        item.status = DONE
                    break
                except Cancelled:
                    item.status = CANCELLED
                    self._drop_client(slot)
                    break
                except Exception as exc:  # noqa: BLE001
                    self._drop_client(slot)
                    if item.cancel_flag:
                        item.status = CANCELLED
                        break
                    if _retryable(exc) and item.attempts < 3:
                        self._log("error", f"{item.name}: {friendly_error(exc)} · riprovo")
                        time.sleep(1.0)
                        continue
                    item.status = FAILED
                    item.error = friendly_error(exc)
                    self._log("error", f"{item.name}: {item.error}")
                    break
            item.finished = time.time()
            item.speed = 0.0
            if item.status == DONE and item.on_done:
                try:
                    item.on_done(item)
                except Exception:
                    pass
            self._notify(item)

    # ------------------------------------------------------------------ un trasferimento
    def _decide(self, item, src, dst):
        """Il file di destinazione esiste: cosa fare. Ritorna overwrite | resume | skip | rename."""
        action = item.force or self.policy
        if action == "ask":
            with self._ask_lock:  # una domanda alla volta, anche con più trasferimenti in parallelo
                if self._apply_all:
                    action = self._apply_all
                elif self.ask_overwrite:
                    action, for_all = self.ask_overwrite(item, src, dst)
                    if for_all:
                        self._apply_all = action
                else:
                    action = "overwrite"
        if action == "newer":
            action = "overwrite" if (src.mtime or 0) > (dst.mtime or 0) + 1 else "skip"
        if action == "resume":
            if dst.size >= src.size:
                action = "skip" if dst.size == src.size else "overwrite"
        return action

    def _run(self, client, item):
        if item.direction == "down":
            if item.is_dir:
                return self._scan_down(client, item)
            return self._download(client, item)
        if item.is_dir:
            return self._scan_up(client, item)
        return self._upload(client, item)

    @staticmethod
    def _leftover_action(item, policy):
        """C'è un pezzo di un trasferimento interrotto (.part / .tkpart) e il file finale non esiste:
        con «chiedi», «se più recente» e «riprendi» si riprende da lì, altrimenti si ricomincia da capo."""
        return "resume" if (item.force or policy) in ("ask", "newer", "resume") else "overwrite"

    def _download(self, client, item):
        """Scarica in «<nome>.part» e solo a file completo lo rinomina col nome vero: un trasferimento interrotto
        non lascia mai un file troncato al posto di quello buono (la ripresa riparte dal .part)."""
        cancel = lambda: item.cancel_flag  # noqa: E731
        src = listing.Entry(item.name, False, item.size, item.mtime)
        item.offset = 0
        part = item.local + PART
        if item.attempts > 1 and item.done:
            if os.path.exists(part):
                item.offset = os.path.getsize(part)  # nuovo tentativo dopo un errore: riprende da sé
        elif os.path.exists(item.local):
            st = os.stat(item.local)
            act = self._decide(item, src, listing.Entry(item.name, False, st.st_size, st.st_mtime))
            if act == "skip":
                item.status = SKIPPED
                return
            if act == "rename":
                item.local = free_name(item.local, os.path.exists)
                part = item.local + PART
            elif act == "resume":
                # «Riprendi» su un file già presente (es. interrotto da una versione vecchia): si continua su una
                # copia .part, il file com'è resta intatto finché lo scaricamento non è completo
                if not (os.path.exists(part) and os.path.getsize(part) >= st.st_size):
                    shutil.copyfile(item.local, part)
                item.offset = os.path.getsize(part)
        elif os.path.exists(part):
            if self._leftover_action(item, self.policy) == "resume" and 0 < os.path.getsize(part) < (src.size or 1 << 62):
                item.offset = os.path.getsize(part)
                self._log("status", f"{item.name}: riprendo lo scaricamento interrotto ({item.offset} byte già scaricati)")
        os.makedirs(os.path.dirname(item.local) or ".", exist_ok=True)
        item.done = item.offset
        item._samples = []
        mode = "ab" if item.offset else "wb"
        try:
            with open(part, mode) as fh:
                try:
                    client.download(item.remote, fh, item.offset, item._sample, cancel)
                except ftplib.error_perm as exc:
                    if item.offset and str(exc)[:3] in ("500", "501", "502", "504", "550"):
                        fh.seek(0)
                        fh.truncate()
                        item.offset = item.done = 0
                        client.download(item.remote, fh, 0, item._sample, cancel)
                    else:
                        raise
                fh.flush()
                os.fsync(fh.fileno())
        except Cancelled:
            _remove_quiet(part)  # annullato dall'utente: niente pezzi in giro
            raise
        if item.mtime:
            try:
                os.utime(part, (time.time(), item.mtime))
            except OSError:
                pass
        os.replace(part, item.local)
        item.size = max(item.size, item.done)
        if item.track:
            item.remote_after = client.stat(item.remote)

    def _upload(self, client, item):
        """Carica su «<nome>.tkpart» e a file completo lo rinomina col nome vero (stessi permessi del file che
        sostituisce): se la connessione cade, sul server resta il file di prima, non uno troncato.
        Se il server non permette la rinomina (o il file è un collegamento) si carica direttamente col nome vero."""
        cancel = lambda: item.cancel_flag  # noqa: E731
        st = os.stat(item.local)
        item.size = st.st_size
        src = listing.Entry(item.name, False, st.st_size, st.st_mtime)
        item.offset = 0
        dst = client.stat(item.remote)
        if dst is not None and dst.is_dir:
            raise RemoteError(f"Sul server c'è una cartella che si chiama «{item.name}»: non la sostituisco con un file.")
        if dst is not None and item.expect is not None and not item.attempts > 1 and not _same_remote(dst, item.expect):
            # modifica al volo: il file sul server è cambiato dopo che l'abbiamo scaricato
            if not (self.ask_changed and self.ask_changed(item, dst)):
                item.status = SKIPPED
                item.error = "il file sul server è cambiato: non l'ho sovrascritto"
                return
        if dst is not None and not dst.perms and hasattr(client, "perms"):
            try:
                dst.perms = client.perms(item.remote) or ""
            except Exception as exc:  # noqa: BLE001
                if _connection_lost(client, exc):
                    raise
        # caricamento diretto: server che non rinomina, collegamento (la rinomina lo sostituirebbe con un file),
        # file che esiste con permessi sconosciuti (la rinomina li cambierebbe)
        direct = getattr(client, "no_temp_upload", False) or (dst is not None and (dst.is_link or not dst.perms))
        tmp = item.remote + TMP_UP
        if item.attempts > 1 and item.done:
            if direct:
                item.offset = dst.size if dst is not None and dst.size < src.size else 0
            else:
                t = client.stat(tmp)
                item.offset = t.size if t is not None and not t.is_dir and t.size < src.size else 0
        elif dst is not None:
            act = self._decide(item, src, dst)
            if act == "skip":
                item.status = SKIPPED
                return
            if act == "rename":
                folder = listing.parent(item.remote)
                names = {e.name for e in client.listdir(folder)}
                newname = free_name(item.name, lambda n: n in names)
                item.remote = listing.join(folder, newname)
                tmp = item.remote + TMP_UP
                dst = None
            elif act == "resume":
                # «Riprendi» scelto su un file già sul server (interrotto da una versione vecchia): si continua lui
                direct = True
                item.offset = dst.size
        if not direct and not item.offset and not (item.attempts > 1 and item.done):
            t = client.stat(tmp)
            if t is not None and not t.is_dir and 0 < t.size < src.size and \
                    self._leftover_action(item, self.policy) == "resume":
                item.offset = t.size
                self._log("status", f"{item.name}: riprendo il caricamento interrotto ({item.offset} byte già sul server)")
        item.done = item.offset
        item._samples = []
        if direct:
            with open(item.local, "rb") as fh:
                client.upload(fh, item.remote, item.offset, item._sample, cancel)
        else:
            try:
                with open(item.local, "rb") as fh:
                    client.upload(fh, tmp, item.offset, item._sample, cancel)
            except Cancelled:
                try:
                    client.delete(tmp)  # annullato dall'utente: niente pezzi sul server
                except Exception:  # noqa: BLE001
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                if item.offset or _connection_lost(client, exc):
                    raise
                # il server non accetta il nome temporaneo (filtri sui nomi, permessi): carico col nome vero
                self._log("status", f"{item.name}: il server non accetta il file temporaneo ({friendly_error(exc)}): "
                                    "lo carico direttamente")
                client.no_temp_upload = True
                item.offset = item.done = 0
                item._samples = []
                with open(item.local, "rb") as fh:
                    client.upload(fh, item.remote, 0, item._sample, cancel)
            else:
                self._finish_upload(client, item, tmp, dst)
        if item.track:
            item.remote_after = client.stat(item.remote)

    def _finish_upload(self, client, item, tmp, dst):
        """Il file temporaneo è completo: prende i permessi del file che sostituisce e il suo nome."""
        if dst is not None and dst.perms:
            try:
                client.chmod(tmp, listing.perms_to_octal(dst.perms))
            except Exception as exc:  # noqa: BLE001 - non tutti i server fanno chmod
                if _connection_lost(client, exc):
                    raise
        try:
            client.rename(tmp, item.remote)
            return
        except Exception as exc:  # noqa: BLE001
            if _connection_lost(client, exc):
                raise
            first = exc
        # alcuni server (e Windows) non rinominano sopra un file che esiste: si toglie quello vecchio e si riprova
        if dst is not None:
            try:
                client.delete(item.remote)
                client.rename(tmp, item.remote)
                return
            except Exception as exc:  # noqa: BLE001
                if _connection_lost(client, exc):
                    raise
                first = exc
        self._log("status", f"{item.name}: il server non rinomina i file ({friendly_error(first)}): lo carico direttamente")
        client.no_temp_upload = True
        item.offset = item.done = 0
        item._samples = []
        with open(item.local, "rb") as fh:
            client.upload(fh, item.remote, 0, item._sample, lambda: item.cancel_flag)
        try:
            client.delete(tmp)
        except Exception:  # noqa: BLE001
            pass

    def _scan_down(self, client, item):
        """Cartella remota da scaricare: crea le cartelle locali e mette in coda i file."""
        new, stack = [], [(item.remote, item.local)]
        while stack:
            if item.cancel_flag:
                raise Cancelled()
            rdir, ldir = stack.pop()
            os.makedirs(ldir, exist_ok=True)
            for e in sorted(client.listdir(rdir), key=lambda x: x.name.lower()):
                r, loc = listing.join(rdir, e.name), os.path.join(ldir, _safe_local(e.name))
                if e.is_dir:
                    stack.append((r, loc))
                else:
                    new.append(Item("down", loc, r, item.site, item.password, item.passphrase, e.size,
                                    mtime=e.mtime, force=item.force, tag=item.tag))
        self._insert_after(item, new)
        item.size = item.done = sum(x.size for x in new)

    def _scan_up(self, client, item):
        """Cartella locale da caricare: crea le cartelle sul server e mette in coda i file."""
        new = []
        for d, dirs, files in os.walk(item.local):
            if item.cancel_flag:
                raise Cancelled()
            rel = os.path.relpath(d, item.local)
            rdir = item.remote if rel == "." else listing.join(item.remote, rel.replace(os.sep, "/"))
            try:
                client.mkdir(rdir)
            except Exception:  # noqa: BLE001 - esiste già
                pass
            dirs.sort(key=str.lower)
            for f in sorted(files, key=str.lower):
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                new.append(Item("up", p, listing.join(rdir, f), item.site, item.password, item.passphrase,
                                st.st_size, mtime=st.st_mtime, force=item.force, tag=item.tag))
        self._insert_after(item, new)
        item.size = item.done = sum(x.size for x in new)

    def _insert_after(self, item, new):
        with self.lock:
            i = self.items.index(item) + 1 if item in self.items else len(self.items)
            self.items[i:i] = new
            self.wake.notify_all()
        for it in new:
            self._notify(it)


def _safe_local(name):
    """Nome remoto → nome valido per il disco locale (Windows non accetta alcuni caratteri)."""
    if os.name != "nt":
        return name.replace("/", "_")
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad or ord(c) < 32 else c for c in name).rstrip(" .")
    return out or "_"
