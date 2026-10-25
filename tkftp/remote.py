"""Client FTP / FTPS (ftplib) e SFTP (paramiko) con la stessa interfaccia. Da usare solo fuori dal thread
dell'interfaccia: ogni metodo è bloccante. Ogni client registra comandi e risposte con log(tipo, testo);
le password non vengono mai scritte nel registro.

Lezioni (anche dall'app telefono tk-ftp): STOR/RETR/LIST rispondono 125/150 (preliminari) prima del 226; in PASV
si usa l'indirizzo del server di controllo, non quello della risposta 227 (dietro NAT è spesso privato); in FTPS il
canale dati si protegge DOPO aver mandato il comando (il server fa la stretta di mano TLS solo allora) e molti server
(vsftpd, ProFTPD, FileZilla Server) vogliono la stessa sessione TLS del canale di controllo."""
import base64
import ftplib
import hashlib
import os
import socket
import ssl
import stat as _stat

from tkftp.util import conta
from tkftp import listing, trust
from tkftp.listing import Entry

TIMEOUT = 30
BLOCK = 64 * 1024


class RemoteError(Exception):
    pass


class AuthError(RemoteError):
    pass


class Cancelled(Exception):
    pass


class NeedPassword(RemoteError):
    """Serve una password (accesso «chiedi») o la frase della chiave privata (kind = 'password' | 'passphrase')."""

    def __init__(self, kind, text):
        super().__init__(text)
        self.kind = kind


class HostKeyQuestion(RemoteError):
    """Chiave SSH sconosciuta o cambiata: l'interfaccia chiede all'utente e, se accetta, la ricorda e riprova."""

    def __init__(self, host, port, keytype, b64, fingerprint, old=None):
        super().__init__("chiave del server da confermare")
        self.host, self.port, self.keytype, self.b64, self.fingerprint, self.old = host, port, keytype, b64, fingerprint, old

    def accept(self):
        trust.remember_hostkey(self.host, self.port, self.keytype, self.b64, self.fingerprint)


class CertQuestion(RemoteError):
    """Certificato TLS non verificabile (autofirmato, nome diverso, scaduto) o cambiato."""

    def __init__(self, host, port, sha256, info, reason, changed=False):
        super().__init__("certificato del server da confermare")
        self.host, self.port, self.sha256, self.info, self.reason, self.changed = host, port, sha256, info, reason, changed

    def accept(self):
        trust.remember_cert(self.host, self.port, self.sha256, self.info)


class PlainQuestion(RemoteError):
    """«FTP · TLS se disponibile» verso un server senza TLS: prima di mandare la password in chiaro si chiede
    all'utente; se accetta, la scelta vale per questo server."""

    def __init__(self, host, port):
        super().__init__("il server non accetta connessioni protette (TLS)")
        self.host, self.port = host, port

    def accept(self):
        trust.allow_plain(self.host, self.port)


def friendly_error(exc):
    """Messaggio in italiano per l'utente."""
    if isinstance(exc, RemoteError):
        return str(exc)
    if isinstance(exc, socket.gaierror):
        return "Server non trovato: controlla l'indirizzo (host)."
    if isinstance(exc, ConnectionRefusedError):
        return "Connessione rifiutata: il server non risponde su quella porta."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Il server non risponde (tempo scaduto)."
    if isinstance(exc, ConnectionResetError):
        return "Il server ha chiuso la connessione."
    if isinstance(exc, ftplib.error_perm):
        text = str(exc)
        if text.startswith("530"):
            return "Accesso negato: utente o password errati."
        if text.startswith("550"):
            return "Operazione non permessa o file inesistente (" + text + ")."
        return "Il server ha rifiutato: " + text
    if isinstance(exc, ftplib.error_temp):
        return "Errore temporaneo del server: " + str(exc)
    if isinstance(exc, ssl.SSLError):
        return "Errore TLS: " + (exc.reason or str(exc))
    if isinstance(exc, OSError) and exc.errno is None and exc.args:
        return str(exc.args[0])
    if isinstance(exc, OSError):
        return f"Errore di rete o di file: {exc.strerror or exc}"
    try:
        import paramiko
        if isinstance(exc, paramiko.AuthenticationException):
            return "Accesso negato: utente, password o chiave non accettati."
        if isinstance(exc, IOError) and getattr(exc, "errno", None) == 2:
            return "File o cartella inesistente."
        if isinstance(exc, paramiko.SSHException):
            return "Errore SSH: " + str(exc)
    except ImportError:
        pass
    return str(exc) or exc.__class__.__name__


def make_client(site, password="", log=None, passphrase=""):
    if site.protocol == "sftp":
        return SftpClient(site, password, log, passphrase)
    return FtpClient(site, password, log)


def _dropbox_roots():
    """Cartelle Dropbox di questo computer: quelle scritte da Dropbox in info.json, poi i posti soliti."""
    import glob
    import json
    home = os.path.expanduser("~")
    infos = [os.path.join(home, ".dropbox", "info.json")]
    for var in ("APPDATA", "LOCALAPPDATA"):
        if os.environ.get(var):
            infos.append(os.path.join(os.environ[var], "Dropbox", "info.json"))
    roots = []
    for info in infos:
        try:
            with open(info, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for account in data.values():
            if isinstance(account, dict) and account.get("path"):
                roots.append(account["path"])
    roots.append(os.path.join(home, "Dropbox"))
    roots += sorted(glob.glob(os.path.join(home, "Library", "CloudStorage", "Dropbox*")))
    return [r for i, r in enumerate(roots) if r not in roots[:i] and os.path.isdir(r)]


def resolve_keyfile(path):
    """Percorso del file chiave su QUESTO computer. I siti importati da un altro computer (Windows ↔ Mac) portano
    il percorso di là: se il file non c'è si cerca la parte dopo «Dropbox» nella Dropbox di qui, poi in ~/.ssh.
    Se non si trova niente torna il percorso originale (per il messaggio d'errore)."""
    if not path or os.path.isfile(path):
        return path
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower().startswith("dropbox"):
            tail = parts[i + 1:]
            for root in _dropbox_roots():
                candidate = os.path.join(root, *tail)
                if tail and os.path.isfile(candidate):
                    return candidate
            break
    if parts:
        candidate = os.path.join(os.path.expanduser("~"), ".ssh", parts[-1])
        if os.path.isfile(candidate):
            return candidate
    return path


def _cert_info(der):
    info = {"soggetto": "", "emittente": "", "scadenza": ""}
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        c = x509.load_der_x509_certificate(der)

        def cn(name):
            v = name.get_attributes_for_oid(NameOID.COMMON_NAME)
            return v[0].value if v else name.rfc4514_string()
        info["soggetto"] = cn(c.subject)
        info["emittente"] = cn(c.issuer)
        until = getattr(c, "not_valid_after_utc", None) or c.not_valid_after
        info["scadenza"] = until.strftime("%d/%m/%Y")
    except Exception:
        pass
    return info


# =========================================================================== FTP / FTPS
class _FTP(ftplib.FTP_TLS):
    """FTP_TLS con: registro dei comandi, TLS implicito, riuso della sessione TLS sul canale dati,
    nomi file non UTF-8 che non fanno cadere la connessione (surrogateescape)."""

    def __init__(self, owner, context, implicit):
        super().__init__(context=context, timeout=TIMEOUT, encoding="utf-8")
        self._owner = owner
        self._implicit = implicit

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        self.host, self.port = host, port
        if timeout != -999:
            self.timeout = timeout
        sock = socket.create_connection((host, port), self.timeout)
        self.af = sock.family
        if self._implicit:
            sock = self.context.wrap_socket(sock, server_hostname=host)
        self.sock = sock
        self.file = sock.makefile("r", encoding=self.encoding, errors="surrogateescape")
        self.welcome = self.getresp()
        return self.welcome

    def auth(self):
        resp = super().auth()
        # dopo AUTH TLS ftplib rifà «file» senza surrogateescape
        self.file = self.sock.makefile("r", encoding=self.encoding, errors="surrogateescape")
        return resp

    def putline(self, line):
        if "\r" in line or "\n" in line:
            raise ValueError("comando con a capo non ammesso")
        shown = line
        if line[:5].upper() == "PASS " or line[:5].upper() == "ACCT ":
            shown = line[:5] + "********"
        self._owner._log("cmd", shown)
        self.sock.sendall((line + "\r\n").encode(self.encoding, "surrogateescape"))

    def getmultiline(self):
        line = super().getmultiline()
        self._owner._log("resp", line)
        return line

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            session = getattr(self.sock, "session", None)
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=session)
        return conn, size


class FtpClient:
    def __init__(self, site, password="", log=None):
        self.site = site
        self.password = password
        self.logfn = log
        self.ftp = None
        self.home = "/"
        self.feats = set()
        self.mlsd = True
        self.tls = False
        self.tls12 = False

    def _log(self, kind, text):
        if self.logfn:
            try:
                self.logfn(kind, text)
            except Exception:
                pass

    # ------------------------------------------------------------------ connessione
    def _contexts(self):
        verify = ssl.create_default_context()
        try:
            import certifi
            verify.load_verify_locations(certifi.where())
        except Exception:
            pass
        loose = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        loose.check_hostname = False
        loose.verify_mode = ssl.CERT_NONE
        for c in (verify, loose):
            c.minimum_version = ssl.TLSVersion.TLSv1_2
            if self.tls12:
                c.maximum_version = ssl.TLSVersion.TLSv1_2
        return verify, loose

    def connect(self):
        s = self.site
        verify, loose = self._contexts()
        uses_tls = s.protocol in ("ftp", "ftps", "ftps-implicit")
        pinned = trust.trusted_cert(s.host, s.port) if uses_tls else None
        self._log("status", f"Connessione a {s.host}:{s.port}…")
        try:
            self._open(loose if pinned else verify)
        except ssl.SSLCertVerificationError as exc:
            self._close_quiet()
            der = self._grab_cert(loose)
            raise CertQuestion(s.host, s.port, hashlib.sha256(der).hexdigest(), _cert_info(der),
                               _cert_reason(exc)) from None
        if pinned and self.tls:
            der = self.ftp.sock.getpeercert(True)
            fp = hashlib.sha256(der).hexdigest()
            if fp != pinned.get("sha256"):
                # certificato rinnovato: se ora è valido va bene da solo, altrimenti si chiede di nuovo
                self._close_quiet()
                try:
                    self._open(verify)
                    trust.remember_cert(s.host, s.port, fp, _cert_info(der))
                except ssl.SSLCertVerificationError as exc:
                    self._close_quiet()
                    raise CertQuestion(s.host, s.port, fp, _cert_info(der), _cert_reason(exc), changed=True) from None
        self._login()

    def _grab_cert(self, loose):
        ftp = _FTP(self, loose, self.site.protocol == "ftps-implicit")
        try:
            ftp.connect(self.site.host, self.site.port, TIMEOUT)
            if not ftp._implicit:
                ftp.auth()
            return ftp.sock.getpeercert(True)
        finally:
            try:
                ftp.close()
            except Exception:
                pass

    def _open(self, ctx):
        s = self.site
        self.ftp = _FTP(self, ctx, s.protocol == "ftps-implicit")
        self.ftp.connect(s.host, s.port, TIMEOUT)
        self.tls = s.protocol == "ftps-implicit"
        if s.protocol in ("ftp", "ftps"):
            try:
                self.ftp.auth()
                self.tls = True
                if s.protocol == "ftp":
                    trust.remember_tls(s.host, s.port)  # da qui in poi il chiaro su questo server non si accetta più
            except ftplib.error_perm as exc:
                if s.protocol == "ftps":
                    raise RemoteError(f"Il server non accetta FTPS (AUTH TLS rifiutato: {exc}). "
                                      "Prova con «FTP · TLS esplicito se disponibile».") from None
                if trust.trusted_cert(s.host, s.port) or trust.tls_seen(s.host, s.port):
                    self._close_quiet()
                    raise RemoteError("Il server ora rifiuta la connessione protetta (TLS), ma prima la accettava: "
                                      "qualcuno potrebbe essersi messo in mezzo. Per sicurezza non mando la password "
                                      "in chiaro. Se sai che il server è cambiato, nel Gestore siti scegli "
                                      "«FTP in chiaro».") from None
                if s.logon != "anonymous" and not trust.plain_allowed(s.host, s.port):
                    self._close_quiet()
                    raise PlainQuestion(s.host, s.port) from None
                self._log("status", "Il server non supporta TLS: la connessione prosegue in chiaro.")
        if self.tls:
            v = self.ftp.sock.version() if hasattr(self.ftp.sock, "version") else ""
            self._log("status", f"Connessione protetta ({v}).")

    def _login(self):
        s = self.site
        user, pw = s.user, self.password
        if s.logon == "anonymous":
            user, pw = "anonymous", "anonymous@"
        elif s.logon == "ask" and not pw:
            raise NeedPassword("password", f"Password per {user}@{s.host}")
        try:
            self.ftp.login(user, pw, secure=False)
        except ftplib.error_perm as exc:
            if str(exc).startswith("530"):
                raise AuthError("Accesso negato: utente o password errati.") from None
            raise
        if self.tls:
            self.ftp.prot_p()
        try:
            resp = self.ftp.sendcmd("FEAT")
            self.feats = {ln.strip().split(" ")[0].upper() for ln in resp.splitlines()[1:-1] if ln.strip()}
        except ftplib.all_errors:
            self.feats = set()
        if "UTF8" in self.feats:
            try:
                self.ftp.sendcmd("OPTS UTF8 ON")
            except ftplib.all_errors:
                pass
        self.mlsd = "MLSD" in self.feats
        self.ftp.set_pasv(bool(s.passive))
        try:
            self.home = self.ftp.pwd() or "/"
        except ftplib.all_errors:
            self.home = "/"
        self._log("status", f"Connesso. Cartella iniziale {self.home}")

    def _close_quiet(self):
        if self.ftp is not None:
            try:
                self.ftp.close()
            except Exception:
                pass
        self.ftp = None

    def close(self):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                pass
        self._close_quiet()

    def noop(self):
        self.ftp.voidcmd("NOOP")

    def alive(self):
        """La connessione risponde ancora? (per distinguere un comando rifiutato da una rete caduta)"""
        try:
            self.ftp.voidcmd("NOOP")
            return True
        except ftplib.error_perm:
            return True
        except Exception:  # noqa: BLE001
            return False

    def real_path(self, path):
        """Percorso vero della cartella sul server (CWD + PWD): se è diverso da quello atteso c'è un collegamento."""
        self.ftp.cwd(path)
        return self.ftp.pwd()

    def perms(self, path):
        """Permessi di un file («rw-r--r--») letti da LIST, per i server senza MLST (es. vsftpd). "" se ignoti."""
        for ln in self._retr_lines("LIST " + path):
            e = listing.parse_list_line(ln)
            if e is not None and not e.is_dir:
                return e.perms
        return ""

    # ------------------------------------------------------------------ elenchi
    def _retr_lines(self, cmd):
        self.ftp.voidcmd("TYPE A")
        conn, _ = self.ftp.ntransfercmd(cmd)
        chunks = []
        try:
            while True:
                data = conn.recv(BLOCK)
                if not data:
                    break
                chunks.append(data)
            _unwrap(conn)
        finally:
            conn.close()
        self.ftp.voidresp()
        text = b"".join(chunks).decode("utf-8", "surrogateescape")
        return [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]

    def listdir(self, path):
        self.ftp.cwd(path)
        if self.mlsd:
            try:
                out = []
                for ln in self._retr_lines("MLSD"):
                    facts_s, _, name = ln.partition(" ")
                    facts = {}
                    for f in facts_s.split(";"):
                        k, _, v = f.partition("=")
                        if k:
                            facts[k.lower()] = v
                    e = listing.parse_mlsd(name, facts)
                    if e is not None:
                        out.append(e)
                return out
            except ftplib.error_perm:
                self.mlsd = False
        try:
            lines = self._retr_lines("LIST -a")
        except ftplib.error_perm:
            lines = self._retr_lines("LIST")
        out = []
        for ln in lines:
            e = listing.parse_list_line(ln)
            if e is not None and e.name not in (".", ".."):
                out.append(e)
        return out

    def stat(self, path):
        """Entry del file/cartella remota oppure None se non esiste."""
        if "MLST" in self.feats:
            try:
                resp = self.ftp.sendcmd("MLST " + path)
                for ln in resp.splitlines()[1:]:
                    if ln.startswith(" "):
                        facts_s, _, _ = ln.strip().partition(" ")
                        facts = {k.lower(): v for k, _, v in (f.partition("=") for f in facts_s.split(";")) if k}
                        t = facts.get("type", "file").lower()
                        if t in ("cdir", "pdir"):  # pure-ftpd risponde «pdir» per la radice
                            t = "dir"
                        return listing.parse_mlsd(listing.basename(path) or "/", dict(facts, type=t))
            except ftplib.error_perm:
                return None
        try:
            self.ftp.voidcmd("TYPE I")
            size = self.ftp.size(path)
            mtime = 0
            if "MDTM" in self.feats:
                try:
                    mt = self.ftp.sendcmd("MDTM " + path).split(" ", 1)[1].strip()
                    e = listing.parse_mlsd("x", {"type": "file", "modify": mt})
                    mtime = e.mtime if e else 0
                except ftplib.all_errors:
                    pass
            return Entry(listing.basename(path), False, int(size or 0), mtime)
        except ftplib.error_perm:
            pass
        try:
            cur = self.ftp.pwd()
            self.ftp.cwd(path)
            self.ftp.cwd(cur)
            return Entry(listing.basename(path), True)
        except ftplib.error_perm:
            return None

    # ------------------------------------------------------------------ operazioni
    def mkdir(self, path):
        self.ftp.mkd(path)

    def rmdir(self, path):
        self.ftp.rmd(path)

    def delete(self, path):
        self.ftp.delete(path)

    def rename(self, src, dst):
        self.ftp.rename(src, dst)

    def chmod(self, path, octal):
        self.ftp.voidcmd(f"SITE CHMOD {octal} {path}")

    def _abort(self):
        """Annullato a metà: ABOR sul canale di controllo, così il server chiude subito il file
        (ftplib.abort usa MSG_OOB, che con TLS non si può mandare)."""
        try:
            self.ftp.sock.settimeout(5)
            self.ftp.putline("ABOR")
            for _ in range(2):
                if self.ftp.getmultiline()[:3] in ("225", "226"):
                    break
        except Exception:
            pass

    def download(self, remote, fh, offset=0, progress=None, cancel=None):
        self.ftp.voidcmd("TYPE I")
        conn, _ = self.ftp.ntransfercmd("RETR " + remote, rest=offset or None)
        try:
            while True:
                if cancel and cancel():
                    self._abort()  # prima ABOR (il server chiude il file), poi si chiude il canale dati
                    conn.close()
                    raise Cancelled()
                data = conn.recv(BLOCK)
                if not data:
                    break
                fh.write(data)
                if progress:
                    progress(len(data))
            _unwrap(conn)
        finally:
            conn.close()
        self.ftp.voidresp()

    def upload(self, fh, remote, offset=0, progress=None, cancel=None):
        self.ftp.voidcmd("TYPE I")
        if offset:
            fh.seek(offset)
        conn, _ = self.ftp.ntransfercmd(("APPE " if offset else "STOR ") + remote)
        try:
            while True:
                if cancel and cancel():
                    self._abort()  # prima ABOR (il server chiude il file), poi si chiude il canale dati
                    conn.close()
                    raise Cancelled()
                data = fh.read(BLOCK)
                if not data:
                    break
                conn.sendall(data)
                if progress:
                    progress(len(data))
            _unwrap(conn)
        finally:
            conn.close()
        self.ftp.voidresp()


def _unwrap(conn):
    if isinstance(conn, ssl.SSLSocket):
        try:
            conn.unwrap()
        except (OSError, ValueError):
            pass


def _cert_reason(exc):
    msg = (getattr(exc, "verify_message", "") or str(exc)).lower()
    if "hostname" in msg or "ip address mismatch" in msg:
        return "il certificato è intestato a un altro nome"
    if "self-signed" in msg or "self signed" in msg:
        return "il certificato è autofirmato"
    if "expired" in msg:
        return "il certificato è scaduto"
    if "unable to get local issuer" in msg:
        return "il certificato non è emesso da un'autorità riconosciuta"
    return getattr(exc, "verify_message", "") or str(exc)


# =========================================================================== SFTP
class SftpClient:
    def __init__(self, site, password="", log=None, passphrase=""):
        self.site = site
        self.password = password
        self.passphrase = passphrase or password
        self.logfn = log
        self.transport = None
        self.sftp = None
        self.home = "/"

    def _log(self, kind, text):
        if self.logfn:
            try:
                self.logfn(kind, text)
            except Exception:
                pass

    def connect(self):
        import paramiko
        s = self.site
        self._log("status", f"Connessione a {s.host}:{s.port}…")
        sock = socket.create_connection((s.host, s.port), TIMEOUT)
        t = paramiko.Transport(sock)
        t.banner_timeout = TIMEOUT
        try:
            t.start_client(timeout=TIMEOUT)
            self._log("resp", f"Server: {t.remote_version}")
            key = t.get_remote_server_key()
            keytype, b64 = key.get_name(), key.get_base64()
            fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            known = trust.known_hostkey(s.host, s.port)
            if not known or known.get("chiave") != b64:
                raise HostKeyQuestion(s.host, s.port, keytype, b64, fp, old=known)
            self._log("status", f"Chiave del server riconosciuta ({keytype} {fp}).")
            self._auth(t)
            self.transport = t
            self.sftp = paramiko.SFTPClient.from_transport(t)
            self.sftp.get_channel().settimeout(TIMEOUT * 2)
            self.home = self.sftp.normalize(".")
            self._log("status", f"Connesso. Cartella iniziale {self.home}")
        except BaseException:
            try:
                t.close()
            except Exception:
                pass
            raise

    def _load_key(self, path):
        import paramiko
        path = resolve_keyfile(path)
        if not os.path.isfile(path):
            raise RemoteError(f"File chiave non trovato: {path}\nSe la chiave è in Dropbox controlla che sia "
                              "sincronizzata su questo computer, oppure scegli il file nel Gestore siti.")
        with open(path, "rb") as fh:
            head = fh.read(64)
        if head.startswith(b"PuTTY-User-Key-File"):
            raise RemoteError("La chiave è in formato PuTTY (.ppk): convertila in formato OpenSSH con PuTTYgen "
                              "(Conversioni → Esporta chiave OpenSSH) e scegli quel file.")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
        with open(path, "rb") as fh:
            data = fh.read()

        def crypto_load(pw):
            try:
                return serialization.load_ssh_private_key(data, pw)
            except ValueError:
                return serialization.load_pem_private_key(data, pw)

        pw = None
        try:
            loaded = crypto_load(None)
        except TypeError:  # chiave protetta da una frase
            if not self.passphrase:
                raise NeedPassword("passphrase",
                                   f"La chiave {os.path.basename(path)} è protetta: inserisci la frase") from None
            pw = self.passphrase
            try:
                loaded = crypto_load(pw.encode("utf-8"))
            except (ValueError, TypeError):
                raise NeedPassword("passphrase", "Frase della chiave errata: riprova") from None
        except (ValueError, paramiko.SSHException) as exc:
            raise RemoteError(f"Chiave non leggibile: {exc}") from None
        if isinstance(loaded, rsa.RSAPrivateKey):
            cls = paramiko.RSAKey
        elif isinstance(loaded, ed25519.Ed25519PrivateKey):
            cls = paramiko.Ed25519Key
        elif isinstance(loaded, ec.EllipticCurvePrivateKey):
            cls = paramiko.ECDSAKey
        else:
            raise RemoteError("Tipo di chiave non supportato (servono RSA, Ed25519 o ECDSA).")
        return cls.from_private_key_file(path, password=pw)

    def _auth(self, t):
        import paramiko
        s = self.site
        user = s.user or ("anonymous" if s.logon == "anonymous" else "")
        if s.logon == "key":
            if not s.keyfile:
                raise RemoteError("Per l'accesso con file chiave scegli il file della chiave nel Gestore siti.")
            pkey = self._load_key(s.keyfile)
            self._log("status", f"Autenticazione con la chiave {os.path.basename(resolve_keyfile(s.keyfile))} "
                                f"({pkey.get_name()})…")
            remaining = t.auth_publickey(user, pkey)
            if not remaining:
                return
            self._log("status", "Il server chiede anche la password.")
        pw = self.password
        if s.logon == "anonymous":
            pw = "anonymous@"
        if s.logon in ("ask",) and not pw:
            raise NeedPassword("password", f"Password per {user}@{s.host}")
        self._log("status", "Autenticazione con password…")
        try:
            t.auth_password(user, pw)
        except paramiko.BadAuthenticationType as exc:
            if "keyboard-interactive" not in exc.allowed_types:
                raise AuthError("Il server non accetta la password (metodi ammessi: "
                                + ", ".join(exc.allowed_types) + ").") from None
            t.auth_interactive(user, lambda title, instr, prompts: [pw for _p, _echo in prompts])
        except paramiko.AuthenticationException:
            raise AuthError("Accesso negato: utente o password errati.") from None

    def close(self):
        for x in (self.sftp, self.transport):
            try:
                if x is not None:
                    x.close()
            except Exception:
                pass
        self.sftp = self.transport = None

    def noop(self):
        self.sftp.stat(".")

    def alive(self):
        return self.transport is not None and self.transport.is_active()

    def real_path(self, path):
        """Percorso vero (realpath sul server): se è diverso da quello atteso c'è un collegamento."""
        return self.sftp.normalize(path)

    def _entry(self, a, folder):
        mode = a.st_mode or 0
        is_link = _stat.S_ISLNK(mode)
        is_dir = _stat.S_ISDIR(mode)
        if is_link:
            try:
                is_dir = _stat.S_ISDIR(self.sftp.stat(listing.join(folder, a.filename)).st_mode or 0)
            except OSError:
                pass
        owner = ""
        parts = (getattr(a, "longname", "") or "").split()
        if len(parts) >= 4:
            owner = parts[2]
        return Entry(a.filename, is_dir, 0 if is_dir else int(a.st_size or 0), float(a.st_mtime or 0),
                     _stat.filemode(mode)[1:] if mode else "", owner or str(a.st_uid or ""), is_link)

    def listdir(self, path):
        self._log("cmd", f"ls {path}")
        attrs = self.sftp.listdir_attr(path)
        self._log("resp", conta(len(attrs), "elemento", "elementi"))
        return [self._entry(a, path) for a in attrs if a.filename not in (".", "..")]

    def stat(self, path):
        try:
            a = self.sftp.stat(path)
        except (IOError, OSError):
            return None
        a.filename = listing.basename(path)
        e = self._entry(a, listing.parent(path))
        try:  # stat segue i collegamenti: lstat dice se il percorso È un collegamento
            e.is_link = _stat.S_ISLNK(self.sftp.lstat(path).st_mode or 0)
        except (IOError, OSError):
            pass
        return e

    def mkdir(self, path):
        self._log("cmd", f"mkdir {path}")
        self.sftp.mkdir(path)

    def rmdir(self, path):
        self._log("cmd", f"rmdir {path}")
        self.sftp.rmdir(path)

    def delete(self, path):
        self._log("cmd", f"rm {path}")
        self.sftp.remove(path)

    def rename(self, src, dst):
        self._log("cmd", f"rename {src} → {dst}")
        try:
            self.sftp.posix_rename(src, dst)
        except (IOError, OSError):
            self.sftp.rename(src, dst)

    def chmod(self, path, octal):
        self._log("cmd", f"chmod {octal} {path}")
        self.sftp.chmod(path, int(octal, 8))

    def download(self, remote, fh, offset=0, progress=None, cancel=None):
        self._log("cmd", f"get {remote}" + (f" (riprende da {offset} byte)" if offset else ""))
        with self.sftp.open(remote, "rb") as rf:
            size = rf.stat().st_size
            if offset:
                rf.seek(offset)
            rf.prefetch(size, max_concurrent_requests=64)
            while True:
                if cancel and cancel():
                    raise Cancelled()
                data = rf.read(BLOCK)
                if not data:
                    break
                fh.write(data)
                if progress:
                    progress(len(data))
        self._log("resp", "trasferimento completato")

    def upload(self, fh, remote, offset=0, progress=None, cancel=None):
        self._log("cmd", f"put {remote}" + (f" (riprende da {offset} byte)" if offset else ""))
        if offset:
            fh.seek(offset)
        with self.sftp.open(remote, "r+b" if offset else "wb") as wf:
            if offset:
                wf.seek(offset)  # scrittura con posizione esplicita: non tutti i server rispettano «append»
            wf.set_pipelined(True)
            while True:
                if cancel and cancel():
                    raise Cancelled()
                data = fh.read(BLOCK)
                if not data:
                    break
                wf.write(data)
                if progress:
                    progress(len(data))
        self._log("resp", "trasferimento completato")
