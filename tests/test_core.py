"""Collaudo del nucleo di tk-ftp (senza interfaccia): elenchi, FileZilla, credenziali e, contro i server di prova
locali, connessione / carica / scarica / riprendi / rinomina / permessi / elimina per FTP, FTPS esplicito,
FTPS implicito e SFTP (password e chiave), più la coda con trasferimenti in parallelo.
Uso: python tests/test_core.py   (variabile TKFTP_PORTA per cambiare la porta base, predefinita 2621)"""
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
WORK = tempfile.mkdtemp(prefix="tkftp-test-")
os.environ["TKFTP_DATI"] = os.path.join(WORK, "dati")
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo"
os.makedirs(os.environ["TKFTP_DATI"], exist_ok=True)

from tkftp import filezilla, listing, remote, session, transfers, vault  # noqa: E402
from tkftp.sites import Site, SiteStore  # noqa: E402
import servers  # noqa: E402

BASE = int(os.environ.get("TKFTP_PORTA", "2621"))
SRV_ROOT = os.path.join(WORK, "server")
INFO = None


def setUpModule():
    global INFO
    INFO = servers.start_all(SRV_ROOT, BASE, os.path.join(WORK, "chiavi"))
    time.sleep(0.3)


def tearDownModule():
    try:
        INFO["sock"].close()
    except Exception:
        pass
    vault.purge_service()  # niente credenziali di prova lasciate nel portachiavi


def rnd(path, size):
    with open(path, "wb") as fh:
        fh.write(os.urandom(size))
    return path


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def connect(site, password=servers.PASSWORD, passphrase=""):
    """Connette accettando (come farebbe l'utente) certificato autofirmato e chiave SSH sconosciuta."""
    log = []
    for _ in range(3):
        c = remote.make_client(site, password, lambda k, t: log.append((k, t)), passphrase)
        try:
            c.connect()
            return c, log
        except (remote.CertQuestion, remote.HostKeyQuestion) as q:
            q.accept()
    raise AssertionError("connessione non riuscita")


class TestListing(unittest.TestCase):
    def test_unix(self):
        e = listing.parse_list_line("-rw-r--r--    1 pietro   www-data    12345 Mar 14 09:30 index.php")
        self.assertEqual((e.name, e.size, e.perms, e.owner, e.is_dir), ("index.php", 12345, "rw-r--r--", "pietro", False))
        self.assertEqual(e.octal, "644")
        d = listing.parse_list_line("drwxr-xr-x 2 u g 4096 Jan  1  2024 nome con spazi")
        self.assertTrue(d.is_dir)
        self.assertEqual(d.name, "nome con spazi")
        ln = listing.parse_list_line("lrwxrwxrwx 1 u g 11 Feb 2 10:00 www -> public_html")
        self.assertEqual((ln.name, ln.link_target, ln.is_link), ("www", "public_html", True))
        self.assertIsNone(listing.parse_list_line("total 12"))
        no_group = listing.parse_list_line("-rw-r--r-- 1 owner 77 Dec 31 2023 a.txt")
        self.assertEqual((no_group.name, no_group.size), ("a.txt", 77))

    def test_dos(self):
        e = listing.parse_list_line("03-14-24  09:30PM       <DIR>          wwwroot")
        self.assertTrue(e.is_dir)
        f = listing.parse_list_line("03-14-24  09:30AM                 1024 web.config")
        self.assertEqual((f.name, f.size), ("web.config", 1024))

    def test_mlsd(self):
        e = listing.parse_mlsd("a.txt", {"type": "file", "size": "10", "modify": "20240314093000", "unix.mode": "0644"})
        self.assertEqual((e.size, e.perms), (10, "rw-r--r--"))
        self.assertIsNone(listing.parse_mlsd(".", {"type": "cdir"}))

    def test_paths(self):
        self.assertEqual(listing.join("/", "a"), "/a")
        self.assertEqual(listing.join("/a/", "b"), "/a/b")
        self.assertEqual(listing.parent("/a/b"), "/a")
        self.assertEqual(listing.parent("/a"), "/")
        self.assertEqual(listing.octal_to_perms("755"), "rwxr-xr-x")


SAMPLE = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<FileZilla3 version="3.70.6" platform="windows">
    <Servers>
        <Server><Host>radice.it</Host><Port>21</Port><Protocol>0</Protocol><Type>0</Type><User>u</User>
            <Pass encoding="base64">cGFzc3fDqA==</Pass><Logontype>1</Logontype><Name>Sito radice</Name>
            <RemoteDir>1 0 3 www 6 public</RemoteDir></Server>
        <Folder expanded="1">1.Clienti
            <Server><Host>ssh.esempio.it</Host><Port>65100</Port><Protocol>1</Protocol><User>root</User>
                <Keyfile>C:\\chiavi\\id</Keyfile><Logontype>5</Logontype><Name>Cliente SSH</Name></Server>
            <Folder expanded="1">Sotto
                <Server><Host>ftp.esempio.it</Host><Port>21</Port><Protocol>6</Protocol><User>a</User>
                    <Logontype>2</Logontype><PasvMode>MODE_ACTIVE</PasvMode><Name>In chiaro</Name></Server>
            </Folder>
        </Folder>
        <Server><Host>web.esempio.it</Host><Protocol>5</Protocol><Name>HTTPS, non supportato</Name></Server>
    </Servers>
</FileZilla3>"""


class TestFileZilla(unittest.TestCase):
    def test_import(self):
        r = filezilla.parse(SAMPLE)
        self.assertEqual(len(r.sites), 3)
        self.assertEqual(r.skipped, 1)
        a, b, c = r.sites
        self.assertEqual((a.password, a.remote_dir, a.protocol, a.group), ("passwè", "/www/public", "ftp", ""))
        self.assertEqual((b.protocol, b.logon, b.keyfile, b.port, b.group), ("sftp", "key", "C:\\chiavi\\id", 65100, "1.Clienti"))
        self.assertEqual((c.protocol, c.logon, c.passive, c.group), ("ftp-plain", "ask", False, "1.Clienti/Sotto"))

    def test_old_phone_export_base64_without_encoding(self):
        """Le app telefono ≤ 2.0.2 scrivevano <Pass> in base64 senza encoding="base64": va decodificata.
        Una password in chiaro di un FileZilla vecchio (senza encoding) invece resta com'è."""
        import base64 as b64
        def pw(text):
            return b64.b64encode(text.encode()).decode()
        phone = ('<?xml version="1.0" encoding="UTF-8"?><FileZilla3 version="3.66.4" platform="linux"><Servers>'
                 f'<Server><Host>a.it</Host><Protocol>0</Protocol><User>u</User><Pass>{pw("pässwörd1")}</Pass>'
                 '<Logontype>1</Logontype><Name>A</Name></Server>'
                 f'<Server><Host>b.it</Host><Protocol>1</Protocol><User>u</User><Pass>{pw("Segreta!2026")}</Pass>'
                 '<Logontype>1</Logontype><Name>B</Name></Server></Servers></FileZilla3>')
        r = filezilla.parse(phone)
        self.assertTrue(r.phone_export)
        self.assertEqual([s.password for s in r.sites], ["pässwörd1", "Segreta!2026"])
        self.assertEqual(r.old_phone, 2, "export vecchio: si avvisa di rifarlo")
        old_fz = ('<FileZilla3 version="3.20.1" platform="windows"><Servers>'
                  '<Server><Host>c.it</Host><User>u</User><Pass>Ciao1234</Pass><Logontype>1</Logontype></Server>'
                  '<Server><Host>d.it</Host><User>u</User><Pass>segreta</Pass><Logontype>1</Logontype></Server>'
                  f'<Server><Host>e.it</Host><User>u</User><Pass>{pw("ok")}</Pass><Logontype>1</Logontype></Server>'
                  '</Servers></FileZilla3>')
        r = filezilla.parse(old_fz)
        self.assertFalse(r.phone_export)
        self.assertEqual([s.password for s in r.sites], ["Ciao1234", "segreta", "ok"])  # «b2s=» finisce con =

    def test_remote_dir(self):
        self.assertEqual(filezilla.decode_remote_dir("1 0 3 www 6 public"), "/www/public")
        self.assertEqual(filezilla.decode_remote_dir("1 0 9 con spazi"), "/con spazi")
        self.assertEqual(filezilla.decode_remote_dir("1 2 3 www 6 public"), "/www/public")  # vecchia app telefono
        self.assertEqual(filezilla.encode_remote_dir("/www/public"), "1 0 3 www 6 public")
        self.assertEqual(filezilla.decode_remote_dir(filezilla.encode_remote_dir("/a b/c")), "/a b/c")

    def test_roundtrip_plain_and_encrypted(self):
        sites = filezilla.parse(SAMPLE).sites
        pw = {s.id: s.password for s in sites}
        plain = filezilla.parse(filezilla.build(sites, pw, include_passwords=True)).sites
        self.assertEqual([(s.host, s.group, s.password, s.remote_dir) for s in plain],
                         [(s.host, s.group, s.password, s.remote_dir) for s in sites])
        nopw = filezilla.parse(filezilla.build(sites, pw, include_passwords=False)).sites
        self.assertEqual(nopw[0].password, "")
        enc = filezilla.build(sites, pw, phrase="frase segreta lunga")
        self.assertNotIn(b"cGFzc3fDqA", enc)
        self.assertNotIn(b"<Pass", enc)
        ok = filezilla.parse(enc, "frase segreta lunga")
        self.assertTrue(ok.encrypted)
        self.assertEqual(ok.sites[0].password, "passwè")
        bad = filezilla.parse(enc, "sbagliata")
        self.assertTrue(bad.wrong_phrase)
        self.assertEqual(bad.sites[0].password, "")
        none = filezilla.parse(enc)
        self.assertEqual((none.encrypted, none.sites[0].password), (True, ""))


class TestRealFileZilla(unittest.TestCase):
    def test_installed_sitemanager_reads(self):
        """Il sitemanager.xml di FileZilla di questo computer (se c'è) si legge tutto (sola lettura)."""
        path = filezilla.installed_sitemanager()
        if not path:
            self.skipTest("FileZilla non installato")
        r = filezilla.read_file(path)
        self.assertGreater(len(r.sites), 0)
        for s in r.sites:
            self.assertTrue(s.host)
            self.assertIn(s.protocol, ("ftp", "ftps", "ftps-implicit", "ftp-plain", "sftp"))
            if s.logon == "key":
                self.assertTrue(s.keyfile)
        again = filezilla.parse(filezilla.build(r.sites, {}, False)).sites
        self.assertEqual(sorted((s.host, s.port, s.group, s.logon, s.keyfile, s.user) for s in again),
                         sorted((s.host, s.port, s.group, s.logon, s.keyfile, s.user) for s in r.sites))
        print(f"\n   FileZilla installato: {len(r.sites)} siti letti, {len({s.group for s in r.sites})} gruppi")


class TestSharedFolder(unittest.TestCase):
    def test_write_and_merge_from_outside(self):
        from tkftp import sync
        from tkftp.util import Settings
        folder = os.path.join(WORK, "Dropbox")
        os.makedirs(folder, exist_ok=True)
        st = SiteStore(os.path.join(WORK, "siti-condivisi.json"))
        cfg = Settings(os.path.join(WORK, "impostazioni-condivise.json"))
        cfg.setValue("shared_dir", folder)
        cfg.setValue("shared_pw", True)
        sync.set_phrase("frase del telefono")
        a = Site(name="Uno", host="uno.it", user="u")
        st.upsert(a, "pw-uno")
        sh = sync.SharedSync(st, cfg)
        self.assertTrue(sh.write())
        with open(sh.path(), "rb") as fh:
            data = fh.read()
        self.assertNotIn(b"pw-uno", data)
        self.assertIn(b"<TkPass>", data)
        # un altro computer (o il telefono) aggiunge un sito
        other = filezilla.parse(data, "frase del telefono").sites + [Site(name="Due", host="due.it", user="d",
                                                                          password="pw-due", group="Telefono")]
        time.sleep(1.1)
        filezilla.write_file(sh.path(), other, {s.id: s.password for s in other}, phrase="frase del telefono")
        added, updated, warn = sh.check()
        self.assertEqual((added, warn), (1, ""))
        due = next(s for s in st.sites if s.host == "due.it")
        from tkftp.sites import get_password
        self.assertEqual((due.group, get_password(due)), ("Telefono", "pw-due"))
        self.assertIsNone(sh.check())  # già letto
        sync.set_phrase("")
        for x in list(st.sites):
            st.delete(x.id)


class TestVaultAndStore(unittest.TestCase):
    def test_vault(self):
        vault.set_secret("prova-collaudo", "pàssword segreta")
        self.assertEqual(vault.get_secret("prova-collaudo"), "pàssword segreta")
        vault.delete_secret("prova-collaudo")
        self.assertIsNone(vault.get_secret("prova-collaudo"))

    def test_store_no_password_on_disk(self):
        st = SiteStore(os.path.join(WORK, "siti-prova.json"))
        s = Site(name="Prova", host="h.it", user="u", group="G/H")
        st.upsert(s, "nonvaipiùsudisco")
        with open(st.path, encoding="utf-8") as fh:
            self.assertNotIn("nonvaipiùsudisco", fh.read())
        from tkftp.sites import get_password
        self.assertEqual(get_password(s), "nonvaipiùsudisco")
        added, updated = st.merge(filezilla.parse(SAMPLE).sites)
        self.assertEqual((added, updated), (3, 0))
        added, updated = st.merge(filezilla.parse(SAMPLE).sites)
        self.assertEqual(added, 0)
        st.delete(s.id)
        self.assertEqual(get_password(s), "")
        for x in list(st.sites):
            st.delete(x.id)


class NetBase:
    protocol = "ftp"
    port_key = "ftp"
    logon = "normal"

    def site(self):
        s = Site(name=self.protocol, host="127.0.0.1" if self.protocol == "sftp" else "localhost",
                 port=INFO[self.port_key], protocol=self.protocol, user=servers.USER, logon=self.logon)
        if self.logon == "key":
            s.keyfile = INFO["client_key"]
        return s

    def setUp(self):
        self.dir = "/" + self.protocol.replace("-", "_") + "_" + self.logon
        self.loc = tempfile.mkdtemp(dir=WORK)
        c, _ = connect(self.site())
        try:
            session.delete_tree(c, self.dir, True)
        except Exception:
            pass
        c.close()

    def test_full_cycle(self):
        c, log = connect(self.site())
        self.assertTrue(any(k == "cmd" for k, _ in log) or self.protocol == "sftp")
        self.assertFalse(any(servers.PASSWORD in t for _, t in log), "la password non deve finire nel registro")
        c.mkdir(self.dir)
        src = rnd(os.path.join(self.loc, "grande è.bin"), 1_500_000)
        rpath = listing.join(self.dir, "grande è.bin")
        with open(src, "rb") as fh:
            c.upload(fh, rpath)
        names = {e.name: e for e in c.listdir(self.dir)}
        self.assertIn("grande è.bin", names)
        self.assertEqual(names["grande è.bin"].size, 1_500_000)
        st = c.stat(rpath)
        self.assertEqual((st.size, st.is_dir), (1_500_000, False))
        self.assertIsNone(c.stat(listing.join(self.dir, "non-esiste.txt")))
        self.assertTrue(c.stat(self.dir).is_dir)
        dst = os.path.join(self.loc, "scaricato.bin")
        with open(dst, "wb") as fh:
            c.download(rpath, fh)
        self.assertEqual(sha(dst), sha(src))
        # ripresa download: metà file già presente
        with open(src, "rb") as fh:
            half = fh.read(700_000)
        part = os.path.join(self.loc, "parziale.bin")
        with open(part, "wb") as fh:
            fh.write(half)
        with open(part, "ab") as fh:
            c.download(rpath, fh, offset=700_000)
        self.assertEqual(sha(part), sha(src))
        # ripresa upload
        rpart = listing.join(self.dir, "parziale.bin")
        with open(part, "wb") as fh:
            fh.write(half)
        with open(part, "rb") as fh:
            c.upload(fh, rpart)
        with open(src, "rb") as fh:
            c.upload(fh, rpart, offset=700_000)
        back = os.path.join(self.loc, "ritorno.bin")
        with open(back, "wb") as fh:
            c.download(rpart, fh)
        self.assertEqual(sha(back), sha(src))
        # rinomina, permessi, annulla, elimina
        c.rename(rpart, listing.join(self.dir, "rinominato.bin"))
        self.assertIn("rinominato.bin", {e.name for e in c.listdir(self.dir)})
        try:
            c.chmod(rpath, "640")
        except Exception as exc:  # pyftpdlib su Windows non fa chmod: basta che il server risponda
            self.assertIn("SITE CHMOD", " ".join(t for _, t in log) + str(exc))
        with self.assertRaises(remote.Cancelled):
            with open(os.path.join(self.loc, "annullato.bin"), "wb") as fh:
                c.download(rpath, fh, cancel=lambda: True)
        c.close()
        c, _ = connect(self.site())
        c.mkdir(listing.join(self.dir, "sotto"))
        with open(src, "rb") as fh:
            c.upload(fh, listing.join(listing.join(self.dir, "sotto"), "x.bin"))
        n = session.delete_tree(c, self.dir, True)
        self.assertGreaterEqual(n, 5)
        self.assertIsNone(c.stat(self.dir))
        c.close()

    def test_queue_parallel_and_folders(self):
        c, _ = connect(self.site())
        c.mkdir(self.dir)
        c.close()
        src_dir = os.path.join(self.loc, "cartella")
        os.makedirs(os.path.join(src_dir, "dentro"))
        files = [rnd(os.path.join(src_dir, f"f{i}.bin"), 200_000 + i) for i in range(4)]
        files.append(rnd(os.path.join(src_dir, "dentro", "g.bin"), 300_000))
        asked = []

        def ask(item, src, dst):
            asked.append(item.name)
            return "overwrite", True

        tm = transfers.TransferManager(parallel=3, ask_overwrite=ask)
        site = self.site()
        tm.add([transfers.Item("up", src_dir, listing.join(self.dir, "cartella"), site, servers.PASSWORD, is_dir=True)])
        self._wait(tm)
        self.assertEqual([i.status for i in tm.items if i.status != transfers.DONE], [])
        self.assertEqual(len(tm.items), 6)
        # di nuovo: i file esistono, chiede una volta («per tutti») e sovrascrive
        tm.clear({transfers.DONE})
        tm.add([transfers.Item("up", src_dir, listing.join(self.dir, "cartella"), site, servers.PASSWORD, is_dir=True)])
        self._wait(tm)
        self.assertEqual(len(asked), 1)
        tm.clear({transfers.DONE})
        out = os.path.join(self.loc, "giu")
        tm.add([transfers.Item("down", out, listing.join(self.dir, "cartella"), site, servers.PASSWORD, is_dir=True)])
        self._wait(tm)
        for f in files:
            rel = os.path.relpath(f, src_dir)
            self.assertEqual(sha(os.path.join(out, rel)), sha(f), rel)
        tm.shutdown()

    def _wait(self, tm, limit=60):
        t0 = time.time()
        while tm.pending_count() and time.time() - t0 < limit:
            time.sleep(0.1)
        bad = [(i.name, i.status, i.error) for i in tm.items if i.status not in (transfers.DONE,)]
        self.assertEqual(bad, [])


class TestFTP(NetBase, unittest.TestCase):
    protocol, port_key = "ftp-plain", "ftp"


class TestFTPAuto(NetBase, unittest.TestCase):
    """«FTP · TLS se disponibile» verso un server FTPS: deve passare in TLS da solo."""
    protocol, port_key = "ftp", "ftps"


class TestFTPS(NetBase, unittest.TestCase):
    protocol, port_key = "ftps", "ftps"


class TestFTPSImplicit(NetBase, unittest.TestCase):
    protocol, port_key = "ftps-implicit", "ftps-implicit"


class TestSFTP(NetBase, unittest.TestCase):
    protocol, port_key = "sftp", "sftp"


class TestSFTPKey(NetBase, unittest.TestCase):
    protocol, port_key, logon = "sftp", "sftp", "key"


class TestQuestions(unittest.TestCase):
    def test_cert_and_hostkey_asked_once(self):
        from tkftp import trust
        for proto, key in (("ftps", "ftps"), ("sftp", "sftp")):
            s = Site(host="localhost" if proto != "sftp" else "127.0.0.1", port=INFO[key], protocol=proto,
                     user=servers.USER)
            trust.forget(s.host, s.port)
            c = remote.make_client(s, servers.PASSWORD)
            with self.assertRaises((remote.CertQuestion, remote.HostKeyQuestion)) as cm:
                c.connect()
            q = cm.exception
            self.assertTrue(q.fingerprint if proto == "sftp" else q.sha256)
            q.accept()
            c = remote.make_client(s, servers.PASSWORD)
            c.connect()  # ora è ricordato: nessuna domanda
            c.close()

    def test_wrong_password_and_ask(self):
        s = Site(host="localhost", port=INFO["ftp"], protocol="ftp-plain", user=servers.USER)
        with self.assertRaises(remote.AuthError):
            remote.make_client(s, "sbagliata").connect()
        s.logon = "ask"
        with self.assertRaises(remote.NeedPassword):
            remote.make_client(s, "").connect()
        ss = Site(host="127.0.0.1", port=INFO["sftp"], protocol="sftp", user=servers.USER)
        connect(ss)[0].close()
        with self.assertRaises(remote.AuthError):
            remote.make_client(ss, "sbagliata").connect()

    def test_session_reconnects(self):
        s = Site(host="localhost", port=INFO["ftp"], protocol="ftp-plain", user=servers.USER)
        sess = session.RemoteSession(s, servers.PASSWORD)
        done = threading.Event()
        res = {}
        sess.connect(lambda h: res.setdefault("home", h), lambda e: res.setdefault("err", e))
        sess.submit(lambda c: c.ftp.sock.close(), None, None)  # connessione «caduta»
        sess.submit(lambda c: c.listdir("/"), lambda r: (res.setdefault("list", r), done.set()),
                    lambda e: (res.setdefault("err2", e), done.set()))
        self.assertTrue(done.wait(20))
        self.assertIn("list", res, res)
        sess.close()


class _Flaky:
    """Client vero con guasti a comando: la connessione «cade» a metà file, il server rifiuta rinomina o nome
    temporaneo. STATE è globale perché dopo un errore la coda apre una connessione nuova."""
    STATE = {}

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _cut(self, kind, progress):
        st = _Flaky.STATE
        if st.get(kind, 0) <= 0:
            return progress
        st[kind] -= 1
        sent = {"n": 0}

        def prog(n):
            sent["n"] += n
            if progress:
                progress(n)
            if sent["n"] >= st.get("cut_at", 300_000):
                if st.get("on_fail"):
                    st["on_fail"]()
                raise ConnectionResetError("connessione caduta (prova)")
        return prog

    def download(self, remote_path, fh, offset=0, progress=None, cancel=None):
        return self.inner.download(remote_path, fh, offset, self._cut("down", progress), cancel)

    def upload(self, fh, remote_path, offset=0, progress=None, cancel=None):
        if _Flaky.STATE.get("reject_tmp") and remote_path.endswith(transfers.TMP_UP):
            import ftplib
            raise ftplib.error_perm("553 nome di file non ammesso (prova)")
        return self.inner.upload(fh, remote_path, offset, self._cut("up", progress), cancel)

    def rename(self, src, dst):
        if _Flaky.STATE.get("no_rename"):
            raise OSError("rinomina non permessa (prova)")
        return self.inner.rename(src, dst)


class SafeBase:
    """Trasferimenti sicuri: un'interruzione non lascia mai un file troncato al posto di quello buono."""
    protocol, port_key = "ftp-plain", "ftp"

    def site(self):
        return Site(name=self.protocol, host="127.0.0.1" if self.protocol == "sftp" else "localhost",
                    port=INFO[self.port_key], protocol=self.protocol, user=servers.USER)

    def setUp(self):
        # una cartella per prova: su Windows il server di prova può tenere aperto un file della prova prima
        self.rdir = "/sicuri_" + self.protocol.replace("-", "_") + "_" + self._testMethodName[5:]
        self.sdir = os.path.join(SRV_ROOT, self.rdir.strip("/"))
        os.makedirs(self.sdir)
        self.loc = tempfile.mkdtemp(dir=WORK)
        connect(self.site())[0].close()  # certificato / chiave del server già accettati
        _Flaky.STATE.clear()
        self._orig = transfers.make_client
        transfers.make_client = lambda *a, **kw: _Flaky(self._orig(*a, **kw))

    def tearDown(self):
        transfers.make_client = self._orig
        _Flaky.STATE.clear()

    def _run(self, item, policy="overwrite", ask=None):
        tm = transfers.TransferManager(parallel=1, policy=policy, ask_overwrite=ask)
        tm.add([item])
        t0 = time.time()
        while tm.pending_count() and time.time() - t0 < 60:
            time.sleep(0.05)
        tm.shutdown()
        return item

    def test_download_interrupted_keeps_old_file(self):
        server_file = rnd(os.path.join(self.sdir, "dati.bin"), 900_000)
        final = os.path.join(self.loc, "dati.bin")
        with open(final, "wb") as fh:
            fh.write(b"versione buona di prima")
        seen = {}

        def at_fail():
            with open(final, "rb") as fh:
                seen["final"] = fh.read()
            seen["part"] = os.path.exists(final + transfers.PART)
        _Flaky.STATE.update(down=1, on_fail=at_fail)
        it = self._run(transfers.Item("down", final, self.rdir + "/dati.bin", self.site(), servers.PASSWORD, 900_000))
        self.assertEqual(seen, {"final": b"versione buona di prima", "part": True},
                         "durante l'interruzione il file vero resta quello di prima, i byte vanno nel .part")
        self.assertEqual((it.status, it.attempts), (transfers.DONE, 2))
        self.assertGreater(it.offset, 0, "il secondo tentativo riprende dal .part")
        self.assertEqual(sha(final), sha(server_file))
        self.assertFalse(os.path.exists(final + transfers.PART))

    def test_download_leftover_part_resumed(self):
        server_file = rnd(os.path.join(self.sdir, "pezzo.bin"), 800_000)
        final = os.path.join(self.loc, "pezzo.bin")
        with open(server_file, "rb") as src, open(final + transfers.PART, "wb") as fh:
            fh.write(src.read(500_000))  # rimasto da un tk-ftp chiuso a metà
        it = self._run(transfers.Item("down", final, self.rdir + "/pezzo.bin", self.site(), servers.PASSWORD, 800_000),
                       policy="ask", ask=lambda *a: self.fail("non deve chiedere: il file vero non c'è"))
        self.assertEqual((it.status, it.offset), (transfers.DONE, 500_000))
        self.assertEqual(sha(final), sha(server_file))
        self.assertFalse(os.path.exists(final + transfers.PART))

    def test_upload_interrupted_keeps_old_file(self):
        on_server = os.path.join(self.sdir, "pagina.php")
        with open(on_server, "wb") as fh:
            fh.write(b"<?php // versione buona sul server")
        src = rnd(os.path.join(self.loc, "pagina.php"), 900_000)
        seen = {}

        def at_fail():
            with open(on_server, "rb") as fh:
                seen["server"] = fh.read()
            seen["tmp"] = os.path.exists(on_server + transfers.TMP_UP)
        _Flaky.STATE.update(up=1, on_fail=at_fail)
        it = self._run(transfers.Item("up", src, self.rdir + "/pagina.php", self.site(), servers.PASSWORD))
        self.assertEqual(seen, {"server": b"<?php // versione buona sul server", "tmp": True},
                         "durante l'interruzione sul server resta il file di prima, i byte vanno nel .tkpart")
        self.assertEqual((it.status, it.attempts), (transfers.DONE, 2))
        self.assertEqual(sha(on_server), sha(src))
        # FTPS: con il TLS chiuso di colpo il server di prova (Windows) tiene aperto il .tkpart del primo tentativo:
        # non riprende da lì e non lo può cancellare (si ripiega sul caricamento diretto, il file finale è giusto)
        if self.protocol != "ftps":
            self.assertGreater(it.offset, 0, "il secondo tentativo riprende dal .tkpart")
            self.assertFalse(os.path.exists(on_server + transfers.TMP_UP))

    def test_upload_new_file_no_leftovers(self):
        src = rnd(os.path.join(self.loc, "nuovo.bin"), 300_000)
        it = self._run(transfers.Item("up", src, self.rdir + "/nuovo.bin", self.site(), servers.PASSWORD))
        self.assertEqual(it.status, transfers.DONE)
        self.assertEqual(sorted(os.listdir(self.sdir)), ["nuovo.bin"])
        self.assertEqual(sha(os.path.join(self.sdir, "nuovo.bin")), sha(src))

    def test_upload_rename_refused_falls_back(self):
        on_server = os.path.join(self.sdir, "x.txt")
        with open(on_server, "wb") as fh:
            fh.write(b"vecchio")
        src = rnd(os.path.join(self.loc, "x.txt"), 200_000)
        _Flaky.STATE.update(no_rename=True)
        it = self._run(transfers.Item("up", src, self.rdir + "/x.txt", self.site(), servers.PASSWORD))
        self.assertEqual(it.status, transfers.DONE, it.error)
        self.assertEqual(sha(on_server), sha(src))
        self.assertEqual(sorted(os.listdir(self.sdir)), ["x.txt"], "niente .tkpart lasciati sul server")

    def test_upload_tmp_name_refused_falls_back(self):
        src = rnd(os.path.join(self.loc, "y.txt"), 200_000)
        _Flaky.STATE.update(reject_tmp=True)
        it = self._run(transfers.Item("up", src, self.rdir + "/y.txt", self.site(), servers.PASSWORD))
        self.assertEqual(it.status, transfers.DONE, it.error)
        self.assertEqual(sha(os.path.join(self.sdir, "y.txt")), sha(src))

    def test_upload_changed_on_server_asks(self):
        on_server = os.path.join(self.sdir, "modifica.txt")
        with open(on_server, "wb") as fh:
            fh.write(b"cambiato da qualcun altro")
        src = rnd(os.path.join(self.loc, "modifica.txt"), 1000)
        asked = []
        tm = transfers.TransferManager(parallel=1, policy="overwrite",
                                       ask_changed=lambda item, e: asked.append(e.size) or False)
        it = transfers.Item("up", src, self.rdir + "/modifica.txt", self.site(), servers.PASSWORD, force="overwrite")
        it.expect = (10, 0)  # quello scaricato all'apertura era di 10 byte
        tm.add([it])
        t0 = time.time()
        while tm.pending_count() and time.time() - t0 < 30:
            time.sleep(0.05)
        tm.shutdown()
        self.assertEqual((asked, it.status), ([25], transfers.SKIPPED))
        with open(on_server, "rb") as fh:
            self.assertEqual(fh.read(), b"cambiato da qualcun altro", "senza conferma il file sul server non si tocca")


class TestSafeFTP(SafeBase, unittest.TestCase):
    protocol, port_key = "ftp-plain", "ftp"


class TestSafeFTPS(SafeBase, unittest.TestCase):
    protocol, port_key = "ftps", "ftps"


class TestSafeSFTP(SafeBase, unittest.TestCase):
    protocol, port_key = "sftp", "sftp"

    def test_upload_keeps_permissions(self):
        on_server = os.path.join(self.sdir, "script.cgi")
        with open(on_server, "wb") as fh:
            fh.write(b"vecchio")
        mode = os.stat(on_server).st_mode & 0o777
        src = rnd(os.path.join(self.loc, "script.cgi"), 1000)
        del servers.CHMODS[:]
        it = self._run(transfers.Item("up", src, self.rdir + "/script.cgi", self.site(), servers.PASSWORD))
        self.assertEqual(it.status, transfers.DONE, it.error)
        self.assertIn((self.rdir + "/script.cgi" + transfers.TMP_UP, mode), servers.CHMODS,
                      "il file temporaneo prende i permessi di quello che sostituisce")


class TestTreeSafety(unittest.TestCase):
    """Eliminazione e permessi ricorsivi: mai dentro un collegamento nascosto (cartella che porta altrove)."""

    def test_hidden_link_not_followed(self):
        tree = {"/a": [listing.Entry("x.txt"), listing.Entry("www", True)],
                "/a/www": [listing.Entry("importante.txt")], "/": []}
        real = {"/": "/", "/a": "/a", "/a/www": "/home/altro/public_html"}

        class Fake:
            def real_path(self, p):
                return real[p]

            def listdir(self, p):
                return tree[p]
        plan = session.scan_tree(Fake(), "/a", True)
        self.assertEqual(plan, [("/a/www", "link"), ("/a/x.txt", "file"), ("/a", "dir")])
        self.assertEqual(session.count_plan(plan), (2, 1))

    def test_symlinked_parent_is_fine(self):
        # la cartella scelta sta sotto un collegamento (es. /www → /home/u/public_html): non è un falso allarme
        tree = {"/www/sito": [listing.Entry("a.txt"), listing.Entry("sotto", True)], "/www/sito/sotto": []}
        real = {"/www": "/home/u/public_html", "/www/sito": "/home/u/public_html/sito",
                "/www/sito/sotto": "/home/u/public_html/sito/sotto"}

        class Fake:
            def real_path(self, p):
                return real[p]

            def listdir(self, p):
                return tree[p]
        plan = session.scan_tree(Fake(), "/www/sito", True)
        self.assertEqual(plan, [("/www/sito/a.txt", "file"), ("/www/sito/sotto", "dir"), ("/www/sito", "dir")])

    def test_real_servers_delete_tree(self):
        for proto, key in (("ftp-plain", "ftp"), ("sftp", "sftp")):
            s = Site(host="127.0.0.1" if proto == "sftp" else "localhost", port=INFO[key], protocol=proto,
                     user=servers.USER)
            d = os.path.join(SRV_ROOT, "albero_" + proto.replace("-", "_"))
            os.makedirs(os.path.join(d, "uno", "due"), exist_ok=True)
            for f in ("a.txt", "uno/b.txt", "uno/due/c.txt"):
                with open(os.path.join(d, f), "w") as fh:
                    fh.write("x")
            c, _ = connect(s)
            plan = session.scan_tree(c, "/" + os.path.basename(d), True)
            self.assertEqual(session.count_plan(plan), (3, 3), proto)
            session.delete_plan(c, plan)
            self.assertFalse(os.path.exists(d), proto)
            c.close()


class TestPlainQuestion(unittest.TestCase):
    def test_plain_asked_and_refused_after_tls(self):
        from tkftp import trust
        s = Site(host="localhost", port=INFO["ftp"], protocol="ftp", user=servers.USER)
        trust.forget(s.host, s.port)
        try:
            with self.assertRaises(remote.PlainQuestion):
                remote.make_client(s, servers.PASSWORD).connect()  # prima di mandare la password in chiaro: si chiede
            remote.PlainQuestion(s.host, s.port).accept()
            c = remote.make_client(s, servers.PASSWORD)
            c.connect()  # accettato: vale per questo server
            c.close()
            trust.remember_tls(s.host, s.port)  # il server prima faceva TLS: il passaggio al chiaro è sospetto
            with self.assertRaises(remote.RemoteError) as cm:
                remote.make_client(s, servers.PASSWORD).connect()
            self.assertNotIsInstance(cm.exception, remote.PlainQuestion)
        finally:
            trust.forget(s.host, s.port)


class TestUtil(unittest.TestCase):
    def test_text_and_dangerous(self):
        from tkftp.util import is_dangerous, is_text_file
        for n in ("index.php", "stile.css", ".htaccess", "robots.txt", "Makefile", "wp-config.php"):
            self.assertTrue(is_text_file(n), n)
        for n in ("setup.exe", "avvia.BAT", "x.cmd", "s.ps1", "a.vbs", "app.js", "f.hta", "l.lnk", "p.jar",
                  "x.command", "y.sh", "foto.jpg", "archivio.zip"):
            self.assertFalse(is_text_file(n), n)
        for n in ("setup.exe", "avvia.BAT", "app.js", "y.sh", "pagina.hta", "x.scr", "x.msi", "x.com"):
            self.assertTrue(is_dangerous(n), n)
        self.assertFalse(is_dangerous("index.php"))

    def test_clean_edit_dir(self):
        from tkftp.util import clean_edit_dir
        root = os.path.join(WORK, "modifica")
        os.makedirs(os.path.join(root, "host-abc", "www"))
        old = os.path.join(root, "host-abc", "www", "vecchio.php")
        new = os.path.join(root, "host-abc", "nuovo.php")
        for p in (old, new):
            with open(p, "w") as fh:
                fh.write("x")
        os.utime(old, (time.time() - 5 * 86400, time.time() - 5 * 86400))
        self.assertEqual(clean_edit_dir(3, root), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new), "le copie recenti restano (forse le segue un altro tk-ftp)")
        self.assertFalse(os.path.exists(os.path.join(root, "host-abc", "www")), "cartelle vuote tolte")


class TestKeyfilePath(unittest.TestCase):
    def test_path_from_other_computer(self):
        # siti importati da Windows sul Mac (e viceversa): la chiave si cerca nella Dropbox di questo computer
        root = os.path.join(WORK, "Dropbox")
        os.makedirs(os.path.join(root, "CLAUDE", "keys"), exist_ok=True)
        key = os.path.join(root, "CLAUDE", "keys", "sito")
        with open(key, "w") as fh:
            fh.write("x")
        old = remote._dropbox_roots
        remote._dropbox_roots = lambda: [root]
        try:
            for other in (r"C:\Users\Altro\Dropbox\CLAUDE\keys\sito", "/Users/macbook/Dropbox/CLAUDE/keys/sito",
                          "/Users/macbook/Library/CloudStorage/Dropbox/CLAUDE/keys/sito"):
                self.assertEqual(remote.resolve_keyfile(other), key, other)
            self.assertEqual(remote.resolve_keyfile(key), key)
            missing = r"C:\Users\Altro\Dropbox\CLAUDE\keys\manca"
            self.assertEqual(remote.resolve_keyfile(missing), missing)
        finally:
            remote._dropbox_roots = old


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
