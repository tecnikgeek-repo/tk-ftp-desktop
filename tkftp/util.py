"""Percorsi, impostazioni e piccole utilità di sistema (Windows, Mac e Linux)."""
import json
import os
import subprocess
import sys
import threading

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

from tkftp import tk_linux  # noqa: E402  (libreria comune dei software TK)
from tkftp.tk_linux import appimage_path, system_env  # noqa: E402,F401

# dove stanno le password, per i testi dell'interfaccia
VAULT_NAME = ("Gestione credenziali di Windows" if IS_WIN else "Portachiavi del Mac" if IS_MAC
              else tk_linux.NOME_PORTACHIAVI)


def mac_bundle_path():
    """Percorso di «tk-ftp.app» se il programma gira dal bundle macOS."""
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/MacOS/"
    i = exe.find(marker)
    return exe[:i + 4] if i >= 0 else None


def is_installed():
    """True se gira dal pacchetto (Windows: cartella «app» col Python incluso; Mac: bundle .app; Linux: AppImage)."""
    if IS_MAC:
        return bool(getattr(sys, "frozen", False) and mac_bundle_path())
    if IS_LINUX:
        return bool(appimage_path())
    bundled = os.path.join(APP_ROOT, "python")
    return (os.path.isfile(os.path.join(bundled, "pythonw.exe"))
            and os.path.normcase(os.path.abspath(sys.base_prefix)) == os.path.normcase(bundled))


def _writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".prova")
        open(probe, "w").close()
        os.remove(probe)
        return True
    except OSError:
        return False


_DATA = None


def data_dir():
    """Dati del programma (siti, impostazioni, chiavi dei server). Windows: «Dati» accanto ad «app»;
    Mac: Libreria/Application Support/tk-ftp; Linux: ~/.local/share/tk-ftp. Gli aggiornamenti non la toccano.
    Le password NON stanno qui: vanno in Gestione credenziali di Windows / Portachiavi del Mac / portachiavi di Linux."""
    global _DATA
    if _DATA:
        return _DATA
    override = os.environ.get("TKFTP_DATI")
    if override:
        path = override
    elif IS_MAC:
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "tk-ftp")
    elif IS_LINUX:
        path = tk_linux.cartella_dati("tk-ftp")
    else:
        base = os.path.dirname(APP_ROOT) if is_installed() else APP_ROOT
        path = os.path.join(base, "Dati")
    if not _writable_dir(path):
        path = os.path.join(os.path.expanduser("~"), "Documents", "tk-ftp")
        os.makedirs(path, exist_ok=True)
    _DATA = path
    return path


def log_dir():
    return data_dir()


def licenses_dir():
    """Cartella «licenze» del pacchetto (AGPL di tk-ftp + licenze dei componenti inclusi). Windows: accanto a
    run.py; Mac: Contents/Resources/licenze (PyInstaller la vede anche da Frameworks); sviluppo: quella del repo."""
    cands = [os.path.join(APP_ROOT, "licenze")]
    if getattr(sys, "_MEIPASS", ""):
        cands.append(os.path.join(sys._MEIPASS, "licenze"))
    bundle = mac_bundle_path()
    if bundle:
        cands.append(os.path.join(bundle, "Contents", "Resources", "licenze"))
    return next((c for c in cands if os.path.isdir(c)), cands[0])


def temp_edit_dir():
    """Cartella dei file aperti con «Modifica al volo»."""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "tk-ftp-modifica")
    os.makedirs(path, exist_ok=True)
    return path


EDIT_KEEP_DAYS = 3


def clean_edit_dir(days=EDIT_KEEP_DAYS, root=None):
    """All'avvio: toglie le copie della modifica al volo non più seguite (non toccate da qualche giorno: quelle
    recenti possono essere di un altro tk-ftp aperto o modifiche rimaste dopo una chiusura improvvisa)."""
    import time
    import tempfile
    root = root or os.path.join(tempfile.gettempdir(), "tk-ftp-modifica")
    if not os.path.isdir(root):
        return 0
    limit = time.time() - days * 86400
    n = 0
    for d, dirs, files in os.walk(root, topdown=False):
        for f in files:
            p = os.path.join(d, f)
            try:
                if os.path.getmtime(p) < limit:
                    os.remove(p)
                    n += 1
            except OSError:
                pass
        if d != root:
            try:
                os.rmdir(d)  # solo se vuota
            except OSError:
                pass
    return n


# programmi e script: mai aperti col programma predefinito del sistema (li eseguirebbe)
DANGEROUS_EXT = {
    "exe", "msi", "msp", "bat", "cmd", "com", "scr", "pif", "cpl", "ps1", "psm1", "vbs", "vbe", "js", "jse", "wsf",
    "wsh", "hta", "lnk", "url", "reg", "msc", "jar", "command", "app", "sh", "bash", "zsh", "csh", "py", "pyw", "pl",
    "rb", "applescript", "scpt", "workflow", "terminal", "appref-ms", "application", "gadget", "inf", "scf",
}


def _ext(name):
    n = os.path.basename(name).lower()
    if n.startswith(".") and n.count(".") == 1:
        return n[1:]
    return n.rsplit(".", 1)[1] if "." in n else ""


def is_dangerous(name):
    """Vero per i file che il computer può eseguire (programmi, script, collegamenti)."""
    return _ext(name) in DANGEROUS_EXT


def is_text_file(name):
    """File di testo da aprire al volo col doppio clic (lista bianca; i file senza estensione sono quasi sempre
    testo sui server). Gli script sono esclusi: col doppio clic si scaricano e basta."""
    from tkftp.listing import TEXT_EXT
    e = _ext(name)
    return (e in TEXT_EXT or e == "") and e not in DANGEROUS_EXT


def open_path(path):
    """Apre un file o una cartella con il programma predefinito del sistema."""
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        tk_linux.apri(path)


def reveal(path):
    """Mostra il file nell'Esplora file / nel Finder / nel file manager."""
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        tk_linux.mostra_nel_file_manager(path)


def open_in_editor(path, editor=""):
    """Apre il file per modificarlo: con l'editor scelto nelle impostazioni, altrimenti con quello del sistema.
    Su Windows prova il verbo «Modifica» (così un .html non finisce nel browser); «Apri» solo per i file che non sono
    né testo né programmi/script (immagini, documenti), perché su uno script «Apri» vuol dire eseguirlo; se no il
    Blocco note. Sul Mac testo e script vanno nell'editor di testo («open -t»), mai eseguiti. Su Linux testo e
    script vanno nell'editor di testo predefinito (quello di text/plain), il resto col programma predefinito."""
    from tkftp.listing import TEXT_EXT
    as_text = is_dangerous(path) or _ext(path) in TEXT_EXT or _ext(path) == ""
    if editor:
        if IS_MAC and editor.endswith(".app"):
            subprocess.Popen(["open", "-a", editor, path])
        else:
            subprocess.Popen([editor, path], env=system_env(), start_new_session=IS_LINUX)
        return
    if IS_LINUX:
        (tk_linux.apri_come_testo if as_text else tk_linux.apri)(path)
        return
    if IS_WIN:
        for verb in (("edit",) if as_text else ("edit", "open")):
            try:
                os.startfile(path, verb)
                return
            except OSError:
                continue
        notepad = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
        subprocess.Popen([notepad if os.path.isfile(notepad) else "notepad.exe", path])
    elif IS_MAC:
        if as_text:
            subprocess.Popen(["open", "-t", path])  # editor di testo predefinito (un .html non va nel browser)
        else:
            subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024


def conta(n, singolare, plurale):
    """«1 elemento», «2 elementi», «0 elementi»."""
    return f"{n} {singolare if n == 1 else plurale}"


def human_speed(bps):
    return human_size(bps) + "/s" if bps > 0 else ""


class Settings:
    """Impostazioni in un file JSON nella cartella dei dati (scrittura atomica, sicura tra thread)."""

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "impostazioni.json")
        self._lock = threading.Lock()
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.data = json.load(fh)
        except Exception:
            self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        with self._lock:
            self.data[key] = value
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            except OSError:
                pass


def _make_shortcut(folder_expr):
    """Crea «tk-ftp.lnk» nella cartella indicata: avvia il Python incluso (stesso pythonw.exe già accettato da Windows)."""
    exe = os.path.join(APP_ROOT, "python", "pythonw.exe")
    if not os.path.isfile(exe):
        exe = sys.executable
    icon = os.path.join(APP_ROOT, "assets", "tk-ftp.ico")
    ps = (
        f"$d={folder_expr};"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'tk-ftp.lnk'));"
        f"$s.TargetPath='{exe}';"
        f"$s.Arguments='\"{os.path.join(APP_ROOT, 'run.py')}\"';"
        f"$s.WorkingDirectory='{APP_ROOT}';"
        f"$s.IconLocation='{icon},0';"
        "$s.Description='tk-ftp - client FTP, FTPS e SFTP';$s.Save();Write-Output (Join-Path $d 'tk-ftp.lnk')"
    )
    ps_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")
    r = subprocess.run([ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, creationflags=0x08000000, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
    return r.stdout.strip()


def create_desktop_shortcut():
    if not IS_WIN:
        raise RuntimeError("disponibile solo su Windows")
    return _make_shortcut("[Environment]::GetFolderPath('Desktop')")


def ensure_folder_shortcut():
    """Collegamento con icona nella cartella del programma (accanto ad «app» e «Dati»). Solo Windows."""
    if not IS_WIN:
        return ""
    return _make_shortcut("'" + os.path.dirname(APP_ROOT).replace("'", "''") + "'")


LINUX_DESKTOP_ID = "tk-ftp"  # nome del file .desktop = app_id della finestra su Wayland (icona nella barra)


def install_linux_menu():
    """Linux: voce «tk-ftp» nel menu delle applicazioni con l'icona (si corregge da sola se l'AppImage si sposta)."""
    from tkftp import APP_TITLE
    icon = os.path.join(getattr(sys, "_MEIPASS", APP_ROOT), "assets", "tk-ftp-512.png")
    return tk_linux.installa_menu(LINUX_DESKTOP_ID, APP_TITLE, "Client FTP, FTPS e SFTP con due pannelli (TecnikGeek)",
                                  "Network;FileTransfer;", icon, nome_generico="Client FTP",
                                  parole="ftp;sftp;ftps;server;trasferimento;")


def update_uninstall_entry():
    """Versione installata col setup: tiene aggiornata la versione mostrata in «App installate»."""
    if not IS_WIN or not is_installed():
        return
    try:
        import winreg
        from tkftp import APP_TITLE, VERSION
        key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\tk-ftp"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                loc = winreg.QueryValueEx(k, "InstallLocation")[0]
            except OSError:
                return
            if os.path.normcase(os.path.abspath(loc)) != os.path.normcase(os.path.dirname(APP_ROOT)):
                return
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_TITLE)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
    except OSError:
        pass
