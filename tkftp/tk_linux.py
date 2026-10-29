"""Linux per i software TK: pacchetto AppImage, voce nel menu, portachiavi, aggiornamento e programmi del sistema.

Copia IDENTICA in ogni software TK accanto a tk_aggiornamento.py (originale in Dropbox\\CLAUDE\\tk-software\\librerie).
Si importa anche su Windows e Mac (non fa niente): le funzioni vanno chiamate solo se IS_LINUX.
Nel pacchetto servono secretstorage + jeepney (portachiavi) e i file .desktop si scrivono in ~/.local/share.
Modello: tk-ftp-desktop (linux/build_linux.sh, linux/<nome>-linux.spec).
"""
import os
import subprocess
import sys
import threading

IS_LINUX = sys.platform.startswith("linux")


# --------------------------------------------------------------------------- pacchetto e cartelle
def appimage_path():
    """Percorso del file .AppImage se il programma gira dal pacchetto (lo imposta il runtime AppImage)."""
    path = os.environ.get("APPIMAGE", "")
    return path if getattr(sys, "frozen", False) and path and os.path.isfile(path) else None


def xdg_data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def cartella_dati(nome):
    """~/.local/share/<nome>: dati del programma (gli aggiornamenti non la toccano)."""
    return os.path.join(xdg_data_home(), nome)


# --------------------------------------------------------------------------- programmi del sistema
def system_env():
    """Ambiente per i programmi del sistema avviati dal pacchetto. PyInstaller cambia LD_LIBRARY_PATH (salva
    l'originale in *_ORIG) e il pacchetto imposta variabili di Qt/Python: passate così, l'editor o il file manager
    caricherebbero le nostre librerie e potrebbero non partire. Fuori dal pacchetto o fuori da Linux: None."""
    if not IS_LINUX or not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            env[var] = orig
        else:
            env.pop(var, None)
    for var in list(env):
        if var.startswith(("QT_", "PYTHON", "_PYI", "APPDIR", "APPIMAGE", "ARGV0", "OWD")):
            env.pop(var)
    return env


def avvia(cmd):
    """Avvia un programma del sistema staccato da questo (non si chiude con noi)."""
    return subprocess.Popen(cmd, env=system_env(), start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apri(path):
    """Apre un file o una cartella col programma predefinito."""
    avvia(["xdg-open", path])


def mostra_nel_file_manager(path):
    """Apre la cartella con il file già selezionato (Nautilus, Dolphin…: interfaccia FileManager1)."""
    from urllib.parse import quote
    uri = "file://" + quote(os.path.abspath(path))
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                            "--object-path", "/org/freedesktop/FileManager1",
                            "--method", "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", ""],
                           capture_output=True, timeout=10, env=system_env())
        if r.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        pass
    apri(os.path.dirname(path))


def editor_di_testo():
    """File .desktop dell'editor di testo predefinito (quello di text/plain), oppure ""."""
    try:
        r = subprocess.run(["xdg-mime", "query", "default", "text/plain"], capture_output=True, text=True,
                           timeout=5, env=system_env())
        name = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    if not name.endswith(".desktop"):
        return ""
    dirs = [xdg_data_home()] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return next((p for p in (os.path.join(d, "applications", name) for d in dirs if d) if os.path.isfile(p)), "")


def apri_come_testo(path):
    """Apre il file nell'editor di testo (un .html o uno script non finiscono nel browser né vengono eseguiti)."""
    desktop = editor_di_testo()
    avvia(["gio", "launch", desktop, path] if desktop else ["xdg-open", path])


# --------------------------------------------------------------------------- voce nel menu
def installa_menu(desktop_id, nome, commento, categorie, icona_png, nome_generico="", parole="", mime=""):
    """Voce nel menu delle applicazioni con l'icona, che punta al file AppImage dove si trova ora: se l'utente lo
    sposta si corregge al prossimo avvio, se lo cancella la voce sparisce (TryExec). Ritorna il .desktop o ""."""
    appimage = appimage_path()
    if not IS_LINUX or not appimage:
        return ""
    base = xdg_data_home()
    icon_dir = os.path.join(base, "icons", "hicolor", "512x512", "apps")
    os.makedirs(icon_dir, exist_ok=True)
    if os.path.isfile(icona_png):
        import shutil
        shutil.copyfile(icona_png, os.path.join(icon_dir, desktop_id + ".png"))
    apps = os.path.join(base, "applications")
    os.makedirs(apps, exist_ok=True)
    exe = appimage.replace("\\", "\\\\").replace('"', '\\"')
    righe = ["[Desktop Entry]", "Type=Application", f"Name={nome}"]
    if nome_generico:
        righe.append(f"GenericName={nome_generico}")
    righe += [f"Comment={commento}", f'Exec="{exe}" %U', f"TryExec={appimage}", f"Icon={desktop_id}",
              "Terminal=false", f"Categories={categorie}"]
    if parole:
        righe.append(f"Keywords={parole}")
    if mime:
        righe.append(f"MimeType={mime}")
    righe += [f"StartupWMClass={desktop_id}", "X-TecnikGeek=1"]
    text = "\n".join(righe) + "\n"
    path = os.path.join(apps, desktop_id + ".desktop")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() == text:
                return path
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)
    for cmd in (["update-desktop-database", "-q", apps],
                ["gtk-update-icon-cache", "-q", "-t", "-f", os.path.join(base, "icons", "hicolor")]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=20, env=system_env())
        except (OSError, subprocess.SubprocessError):
            pass
    return path


# --------------------------------------------------------------------------- portachiavi (Secret Service)
NOME_PORTACHIAVI = "portachiavi del sistema («Password e chiavi»)"
_CONN = None
_LOCK = threading.RLock()  # la stessa connessione D-Bus non va usata da due thread insieme


def _raccolta():
    """Raccolta predefinita del portachiavi, sbloccata (se è chiusa il sistema chiede la password)."""
    global _CONN
    try:
        import secretstorage
        if _CONN is None:
            _CONN = secretstorage.dbus_init()
        coll = secretstorage.get_default_collection(_CONN)
        if coll.is_locked() and coll.unlock():
            raise OSError("portachiavi chiuso: sblocco annullato")
        return coll
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 (D-Bus assente, servizio non avviato…)
        raise OSError(f"portachiavi del sistema non disponibile ({exc.__class__.__name__}: {exc})") from exc


def _attributi(servizio, account=None):
    a = {"service": servizio}
    if account is not None:
        a["account"] = account
    return a


def scrivi_segreto(servizio, account, segreto: bytes, etichetta=""):
    with _LOCK:
        _raccolta().create_item(etichetta or f"{servizio}: {account}", _attributi(servizio, account), segreto,
                                replace=True)


def leggi_segreto(servizio, account):
    """bytes del segreto, oppure None."""
    try:
        with _LOCK:
            item = next(_raccolta().search_items(_attributi(servizio, account)), None)
            return item.get_secret() if item is not None else None
    except Exception:  # noqa: BLE001
        return None


def cancella_segreto(servizio, account):
    try:
        with _LOCK:
            for it in list(_raccolta().search_items(_attributi(servizio, account))):
                it.delete()
    except OSError:
        pass


def cancella_servizio(servizio):
    """Cancella tutte le voci del servizio (solo per i collaudi). Ritorna quante."""
    with _LOCK:
        items = list(_raccolta().search_items(_attributi(servizio)))
        for it in items:
            it.delete()
    return len(items)


# --------------------------------------------------------------------------- aggiornamento
# Il nuovo AppImage (già verificato: firma + SHA-256) viene copiato accanto a quello vecchio (stesso disco: rinomina
# atomica) e lo sostituisce dopo la chiusura; se qualcosa va storto resta quello di prima. I dati stanno altrove.
SCRIPT_AGGIORNAMENTO = r'''#!/bin/bash
PID="$1"; NEW="$2"; TARGET="$3"; RELAUNCH="$4"; LOG="$5"
exec >>"$LOG" 2>&1
echo "[$(date)] aggiornamento: $NEW -> $TARGET"
for _ in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
STAGE="$(dirname "$TARGET")/.$(basename "$TARGET").nuovo"
rm -f "$STAGE"
if cp "$NEW" "$STAGE" && chmod 755 "$STAGE" && [ -s "$STAGE" ]; then
  if mv -f "$STAGE" "$TARGET"; then
    echo "AppImage sostituito: $TARGET"
  else
    echo "sostituzione fallita: versione precedente mantenuta"; rm -f "$STAGE"
  fi
else
  echo "copia fallita: versione precedente mantenuta"; rm -f "$STAGE"
fi
rm -f "$NEW"
if [ "$RELAUNCH" = "1" ]; then setsid "$TARGET" >/dev/null 2>&1 < /dev/null & fi
echo "fine"
'''


def chiave_piattaforma():
    """Chiave del manifest aggiornamenti per questo Linux."""
    import platform
    return "linux-aarch64" if platform.machine() in ("aarch64", "arm64") else "linux-x86_64"


def applica_aggiornamento(nuovo, cartella_script, log, rilancia=True):
    """Sostituisce il file AppImage con «nuovo» dopo la chiusura del programma (il chiamante poi deve uscire)."""
    target = appimage_path()
    parent = os.path.dirname(target or "")
    if not target or not (os.access(parent, os.W_OK) and os.access(target, os.W_OK)):
        raise PermissionError("non hai i permessi per sostituire «" + str(target) + "»")
    script = os.path.join(cartella_script, "applica-aggiornamento.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT_AGGIORNAMENTO)
    subprocess.Popen(["/bin/bash", script, str(os.getpid()), nuovo, target, "1" if rilancia else "0", log],
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=system_env())
