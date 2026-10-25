"""Server di prova locali per il collaudo: FTP, FTPS esplicito, FTPS implicito (pyftpdlib, stesso ciclo e stesso
thread) e SFTP (paramiko). Utente «prova», password «segreta», chiave SSH di prova in <dati>/chiave_prova.
Uso a mano: python tests/servers.py <cartella radice> [porta base 2121]"""
import datetime
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USER, PASSWORD = "prova", "segreta"


def make_cert(folder):
    """Certificato autofirmato per «localhost» (come quelli dei server degli hosting)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tk-ftp prova")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
            .sign(key, hashes.SHA256()))
    path = os.path.join(folder, "prova.pem")
    with open(path, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption()))
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    return path


def start_ftp(root, base_port, certfile):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler, TLS_FTPHandler
    from pyftpdlib.ioloop import IOLoop
    from pyftpdlib.servers import FTPServer

    auth = DummyAuthorizer()
    auth.add_user(USER, PASSWORD, root, perm="elradfmwMT")
    loop = IOLoop()

    class Plain(FTPHandler):
        authorizer = auth
        passive_ports = range(base_port + 100, base_port + 150)

    class Explicit(TLS_FTPHandler):
        authorizer = auth
        certfile = None
        tls_control_required = True
        tls_data_required = True
        passive_ports = range(base_port + 150, base_port + 200)

    Explicit.certfile = certfile

    class Implicit(Explicit):
        passive_ports = range(base_port + 200, base_port + 250)

        def handle(self):  # TLS subito, prima del benvenuto
            self.secure_connection(self.ssl_context)

        def handle_ssl_established(self):
            TLS_FTPHandler.handle(self)

    for h in (Plain, Explicit, Implicit):
        h.banner = "tk-ftp server di prova pronto"
    servers = [FTPServer(("127.0.0.1", base_port), Plain, ioloop=loop),
               FTPServer(("127.0.0.1", base_port + 1), Explicit, ioloop=loop),
               FTPServer(("127.0.0.1", base_port + 2), Implicit, ioloop=loop)]
    for s in servers:
        s.max_cons = 64
    t = threading.Thread(target=loop.loop, kwargs={"timeout": 0.2, "blocking": True}, daemon=True)
    t.start()
    return {"ftp": base_port, "ftps": base_port + 1, "ftps-implicit": base_port + 2, "loop": loop}


# --------------------------------------------------------------------------- SFTP (paramiko)
def start_sftp(root, port, keydir):
    import paramiko
    from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface, SFTP_OK, ServerInterface

    hostkey_path = os.path.join(keydir, "server_host_key")
    if not os.path.exists(hostkey_path):
        paramiko.RSAKey.generate(2048).write_private_key_file(hostkey_path)
    host_key = paramiko.RSAKey.from_private_key_file(hostkey_path)
    client_key_path = os.path.join(keydir, "chiave_prova")
    if not os.path.exists(client_key_path):
        k = paramiko.RSAKey.generate(2048)
        k.write_private_key_file(client_key_path)
    client_key = paramiko.RSAKey.from_private_key_file(client_key_path)

    def err(e):
        return SFTPServer.convert_errno(e.errno)

    class Handle(SFTPHandle):
        def stat(self):
            try:
                return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
            except OSError as e:
                return err(e)

        def chattr(self, attr):
            return SFTP_OK

    class Iface(SFTPServerInterface):
        def _p(self, path):
            return os.path.join(root, path.lstrip("/").replace("/", os.sep)) if path not in ("", "/", ".") else root

        def canonicalize(self, path):
            p = "/" + path.strip("/") if path not in (".", "") else "/"
            return os.path.normpath(p).replace("\\", "/")

        def list_folder(self, path):
            try:
                out = []
                for n in os.listdir(self._p(path)):
                    a = SFTPAttributes.from_stat(os.stat(os.path.join(self._p(path), n)))
                    a.filename = n
                    out.append(a)
                return out
            except OSError as e:
                return err(e)

        def stat(self, path):
            try:
                return SFTPAttributes.from_stat(os.stat(self._p(path)))
            except OSError as e:
                return err(e)

        lstat = stat

        def open(self, path, flags, attr):
            p = self._p(path)
            try:
                fd = os.open(p, flags | getattr(os, "O_BINARY", 0), 0o666)
            except OSError as e:
                return err(e)
            if flags & os.O_WRONLY:
                mode = "ab" if flags & os.O_APPEND else "wb"
            elif flags & os.O_RDWR:
                mode = "a+b" if flags & os.O_APPEND else "r+b"
            else:
                mode = "rb"
            try:
                f = os.fdopen(fd, mode)
            except OSError as e:
                return err(e)
            h = Handle(flags)
            h.filename = p
            h.readfile = f
            h.writefile = f
            return h

        def remove(self, path):
            try:
                os.remove(self._p(path))
            except OSError as e:
                return err(e)
            return SFTP_OK

        def rename(self, old, new):
            try:
                os.rename(self._p(old), self._p(new))
            except OSError as e:
                return err(e)
            return SFTP_OK

        def posix_rename(self, old, new):
            try:
                os.replace(self._p(old), self._p(new))
            except OSError as e:
                return err(e)
            return SFTP_OK

        def mkdir(self, path, attr):
            try:
                os.mkdir(self._p(path))
            except OSError as e:
                return err(e)
            return SFTP_OK

        def rmdir(self, path):
            try:
                os.rmdir(self._p(path))
            except OSError as e:
                return err(e)
            return SFTP_OK

        def chattr(self, path, attr):
            if attr.st_mode is not None:
                CHMODS.append((path, attr.st_mode & 0o777))
            return SFTP_OK

    class Server(ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if (username, password) == (USER, PASSWORD) else paramiko.AUTH_FAILED

        def check_auth_publickey(self, username, key):
            return paramiko.AUTH_SUCCESSFUL if username == USER and key == client_key else paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password,publickey"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(("127.0.0.1", port))
    lsock.listen(32)

    def serve(conn):
        t = paramiko.Transport(conn)
        t.add_server_key(host_key)
        t.set_subsystem_handler("sftp", SFTPServer, Iface)
        try:
            t.start_server(server=Server())
            while t.is_active():
                time.sleep(0.2)
        except Exception:
            pass

    def accept():
        while True:
            try:
                c, _ = lsock.accept()
            except OSError:
                return
            threading.Thread(target=serve, args=(c,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    return {"sftp": port, "client_key": client_key_path, "host_key": host_key, "sock": lsock}


CHMODS = []  # permessi ricevuti dal server SFTP di prova (chattr), per i test


def start_all(root, base_port=2121, keydir=None):
    keydir = keydir or os.path.join(os.path.dirname(root), "chiavi-prova")
    os.makedirs(keydir, exist_ok=True)
    os.makedirs(root, exist_ok=True)
    cert = make_cert(keydir)
    info = start_ftp(root, base_port, cert)
    info.update(start_sftp(root, base_port + 3, keydir))
    return info


if __name__ == "__main__":
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "radice"))
    base = int(sys.argv[2]) if len(sys.argv) > 2 else 2121
    info = start_all(root, base)
    print(f"Server di prova in {root}: FTP {info['ftp']} · FTPS esplicito {info['ftps']} · "
          f"FTPS implicito {info['ftps-implicit']} · SFTP {info['sftp']} · utente {USER} / {PASSWORD} · "
          f"chiave {info['client_key']}", flush=True)
    while True:
        time.sleep(3600)
