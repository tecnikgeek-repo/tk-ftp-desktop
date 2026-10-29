"""Linux per i software TK: pacchetto AppImage, voce nel menu, portachiavi, aggiornamento e programmi del sistema.

Copia IDENTICA in ogni software TK accanto a tk_aggiornamento.py (originale in Dropbox\\CLAUDE\\tk-software\\librerie).
Si importa anche su Windows e Mac (non fa niente): le funzioni vanno chiamate solo se IS_LINUX.
Nel pacchetto servono secretstorage + jeepney (portachiavi, salvaschermo) e i file .desktop si scrivono in
~/.local/share. Per i link aperti da Qt c'è tk_linux_qt.py. Modello: tk-ftp-desktop (linux/build_linux.sh,
linux/<nome>-linux.spec). Versione 2 (29/10/2026): cartelle dell'utente, tipi di file, avvio automatico,
salvaschermo, XWayland.
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


def xdg_config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def cartella_dati(nome):
    """~/.local/share/<nome>: dati del programma (gli aggiornamenti non la toccano)."""
    return os.path.join(xdg_data_home(), nome)


def cartella_utente(chiave):
    """Cartella dell'utente col nome della sua lingua, da ~/.config/user-dirs.dirs (in italiano «Documenti»,
    «Scrivania», «Scaricati»…). chiave = DOCUMENTS, DESKTOP, DOWNLOAD, PICTURES, VIDEOS, MUSIC. "" se manca."""
    casa = os.path.expanduser("~")
    try:
        with open(os.path.join(xdg_config_home(), "user-dirs.dirs"), "r", encoding="utf-8") as fh:
            for riga in fh:
                riga = riga.strip()
                if riga.startswith(f"XDG_{chiave}_DIR="):
                    valore = riga.split("=", 1)[1].strip().strip('"').replace("$HOME", casa)
                    if os.path.isdir(valore) and os.path.abspath(valore) != os.path.abspath(casa):
                        return valore
    except OSError:
        pass
    return ""


def scegli_xwayland():
    """Da chiamare prima di creare QApplication, solo per i programmi che agganciano altro a una finestra X11
    (es. il video di VLC) o posizionano finestre sopra altre: su Wayland puro non si può. Su GNOME/KDE con
    Wayland c'è sempre XWayland (DISPLAY impostato). Non decide se l'utente ha già scelto con QT_QPA_PLATFORM."""
    if IS_LINUX and not os.environ.get("QT_QPA_PLATFORM") and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


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
def exec_desktop(path):
    """Percorso tra virgolette per la riga Exec di un file .desktop (specifica freedesktop)."""
    for c in ("\\", '"', "`", "$"):
        path = path.replace(c, "\\" + c)
    return f'"{path}"'


def _misura_png(path):
    """Lato dell'icona PNG (dall'intestazione), per metterla nella cartella hicolor giusta; 512 se non si legge."""
    try:
        with open(path, "rb") as fh:
            testa = fh.read(24)
        if testa[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(testa[16:20], "big") or 512
    except OSError:
        pass
    return 512


def _copia_icona(icona_png, tipo, nome):
    """Icona in ~/.local/share/icons/hicolor/<lato>x<lato>/<tipo>/<nome>.png (tipo = apps o mimetypes)."""
    if not os.path.isfile(icona_png):
        return
    import shutil
    lato = _misura_png(icona_png)
    cartella = os.path.join(xdg_data_home(), "icons", "hicolor", f"{lato}x{lato}", tipo)
    os.makedirs(cartella, exist_ok=True)
    shutil.copyfile(icona_png, os.path.join(cartella, nome + ".png"))


def _scrivi_se_cambia(path, testo, eseguibile=False):
    """Scrittura atomica solo se il contenuto è diverso. True se ha scritto."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() == testo:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(testo)
    if eseguibile:
        os.chmod(path + ".tmp", 0o755)
    os.replace(path + ".tmp", path)
    return True


def _esegui_piano(cmd):
    """Comando di sistema breve, con l'ambiente pulito; None se non c'è o non risponde."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=system_env())
    except (OSError, subprocess.SubprocessError):
        return None


def installa_menu(desktop_id, nome, commento, categorie, icona_png, nome_generico="", parole="", mime=""):
    """Voce nel menu delle applicazioni con l'icona, che punta al file AppImage dove si trova ora: se l'utente lo
    sposta si corregge al prossimo avvio, se lo cancella la voce sparisce (TryExec). Ritorna il .desktop o ""."""
    appimage = appimage_path()
    if not IS_LINUX or not appimage:
        return ""
    base = xdg_data_home()
    _copia_icona(icona_png, "apps", desktop_id)
    apps = os.path.join(base, "applications")
    righe = ["[Desktop Entry]", "Type=Application", f"Name={nome}"]
    if nome_generico:
        righe.append(f"GenericName={nome_generico}")
    righe += [f"Comment={commento}", f"Exec={exec_desktop(appimage)} %U", f"TryExec={appimage}",
              f"Icon={desktop_id}", "Terminal=false", f"Categories={categorie}"]
    if parole:
        righe.append(f"Keywords={parole}")
    if mime:
        righe.append(f"MimeType={mime.rstrip(';')};")
    righe += [f"StartupWMClass={desktop_id}", "X-TecnikGeek=1"]
    path = os.path.join(apps, desktop_id + ".desktop")
    if _scrivi_se_cambia(path, "\n".join(righe) + "\n", eseguibile=True):
        _esegui_piano(["update-desktop-database", "-q", apps])
        _esegui_piano(["gtk-update-icon-cache", "-q", "-t", "-f", os.path.join(base, "icons", "hicolor")])
    return path


def togli_menu(desktop_id):
    """Contrario di installa_menu (per «Cancella tutto»): voce, icone e avvio automatico."""
    import glob
    base = xdg_data_home()
    for p in ([os.path.join(base, "applications", desktop_id + ".desktop"),
               os.path.join(xdg_config_home(), "autostart", desktop_id + ".desktop")]
              + glob.glob(os.path.join(base, "icons", "hicolor", "*", "apps", desktop_id + ".png"))):
        try:
            os.remove(p)
        except OSError:
            pass


def registra_tipo_file(nome_xml, testo_xml, mime, icona_png=""):
    """Tipo di file del programma (es. .listino) in ~/.local/share/mime con la sua icona. testo_xml = file
    shared-mime-info completo. Si riscrive solo se cambia."""
    mime_dir = os.path.join(xdg_data_home(), "mime")
    if _scrivi_se_cambia(os.path.join(mime_dir, "packages", nome_xml + ".xml"), testo_xml):
        _esegui_piano(["update-mime-database", mime_dir])
    if icona_png:
        _copia_icona(icona_png, "mimetypes", mime.replace("/", "-"))


def rendi_predefinito(desktop_id, *mimes):
    """Il programma diventa quello che apre questi tipi di file (xdg-mime). True se ora lo è davvero per tutti."""
    voce = desktop_id + ".desktop"
    ok = True
    for mime in mimes:
        r = _esegui_piano(["xdg-mime", "query", "default", mime])
        if r is not None and r.stdout.strip() == voce:
            continue
        _esegui_piano(["xdg-mime", "default", voce, mime])
        r = _esegui_piano(["xdg-mime", "query", "default", mime])
        ok = ok and r is not None and r.stdout.strip() == voce
    return ok


def avvio_automatico(desktop_id, nome, commento, acceso=None, argomenti=""):
    """Avvio all'accesso (~/.config/autostart/<id>.desktop, punta al file AppImage). acceso=None = solo domanda.
    Ritorna lo stato. Se è acceso va richiamata a ogni avvio, così segue l'AppImage se si sposta."""
    path = os.path.join(xdg_config_home(), "autostart", desktop_id + ".desktop")
    if acceso is None:
        return os.path.isfile(path)
    if not acceso:
        if os.path.isfile(path):
            os.remove(path)
        return False
    appimage = appimage_path()
    if not appimage:
        raise RuntimeError("disponibile solo con il file AppImage del programma")
    righe = ["[Desktop Entry]", "Type=Application", f"Name={nome}", f"Comment={commento}",
             f"Exec={exec_desktop(appimage)}" + (f" {argomenti}" if argomenti else ""), f"TryExec={appimage}",
             f"Icon={desktop_id}", "Terminal=false", "X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-Delay=5",
             "X-TecnikGeek=1"]
    _scrivi_se_cambia(path, "\n".join(righe) + "\n")
    return True


# --------------------------------------------------------------------------- salvaschermo e sospensione
def inibisci(nome, motivo):
    """Niente salvaschermo, blocco schermo o sospensione finché non si chiama togli_inibizione(). L'inibizione è
    legata alla connessione D-Bus: se il programma si chiude di colpo il desktop la toglie da solo.
    Ritorna lo stato da passare a togli_inibizione, oppure None (nessun desktop o non permesso)."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        from jeepney.wrappers import unwrap_msg
        conn = open_dbus_connection(bus="SESSION")
    except Exception:  # noqa: BLE001 (niente bus di sessione, es. test senza desktop)
        return None
    voci = (("/org/gnome/SessionManager", "org.gnome.SessionManager", "Inhibit", "susu", (nome, 0, motivo, 4 | 8),
             "Uninhibit"),  # 4 = sospensione, 8 = inattività
            ("/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", "Inhibit", "ss", (nome, motivo),
             "UnInhibit"))
    for percorso, servizio, metodo, firma, argomenti, togli in voci:
        try:
            addr = DBusAddress(percorso, bus_name=servizio, interface=servizio)
            cookie = unwrap_msg(conn.send_and_get_reply(new_method_call(addr, metodo, firma, argomenti), timeout=5))[0]
            return conn, addr, togli, int(cookie)
        except Exception:  # noqa: BLE001
            continue
    conn.close()
    return None


def togli_inibizione(stato):
    if not stato:
        return
    from jeepney import new_method_call
    conn, addr, togli, cookie = stato
    try:
        conn.send_and_get_reply(new_method_call(addr, togli, "u", (cookie,)), timeout=5)
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


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
