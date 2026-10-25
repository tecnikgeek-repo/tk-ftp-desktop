"""Aggiornamenti automatici (come tk-listino): manifest sul server, download verificato (SHA-256) e sostituzione
della cartella «app» (Windows) o del bundle (Mac)."""
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import urllib.request

from tkftp import VERSION
from tkftp.tk_aggiornamento import asset_valido
from tkftp.util import APP_ROOT, IS_MAC, log_dir, mac_bundle_path

def _codice_conteggio():
    """«; <codice>» per il manifest: conta l'installazione una volta sola anche se cambia rete (Privacy 4-ter)."""
    try:
        from tkftp import tk_licenza
        return f"; {tk_licenza.CODICE_CONTEGGIO}" if tk_licenza.CODICE_CONTEGGIO else ""
    except Exception:
        return ""


MANIFEST_URL = "https://pietrodefilippis.it/updates/tk-ftp.json"
CHECK_INTERVAL = 12 * 3600
# nome del manifest (tk-pdf, tk-tv-player-mac…): entra nel testo firmato
SLUG = MANIFEST_URL.rsplit("/", 1)[-1][:-len(".json")]

# Solo cmd, tar e reg (nessun eseguibile nuovo: Smart App Control non deve valutare nulla).
# Sostituisce la cartella «app»; la cartella «Dati» sta fuori e non viene toccata.
WIN_SCRIPT = r'''@echo off
setlocal
set "ZIP=%~1"
set "DIR=%~2"
set "RELAUNCH=%~3"
set "LOG=%~4"
set "NEWVER=%~5"
>>"%LOG%" echo [%date% %time%] aggiornamento a %NEWVER%: %ZIP%
ping 127.0.0.1 -n 3 >nul
set "NEW=%DIR%.nuova"
set "OLD=%DIR%.vecchia"
if exist "%NEW%" rmdir /s /q "%NEW%"
if exist "%OLD%" rmdir /s /q "%OLD%"
mkdir "%NEW%"
tar -xf "%ZIP%" -C "%NEW%"
if errorlevel 1 goto fail
if not exist "%NEW%\python\pythonw.exe" goto fail
if not exist "%NEW%\run.py" goto fail
set /a TRIES=0
:moveold
move "%DIR%" "%OLD%" >nul 2>&1
if not errorlevel 1 goto movenew
set /a TRIES+=1
if %TRIES% GEQ 60 goto fail
ping 127.0.0.1 -n 2 >nul
goto moveold
:movenew
move "%NEW%" "%DIR%" >nul 2>&1
if errorlevel 1 (
  move "%OLD%" "%DIR%" >nul 2>&1
  goto fail
)
rmdir /s /q "%OLD%"
>>"%LOG%" echo cartella sostituita
del /q "%ZIP%" >nul 2>&1
if "%RELAUNCH%"=="1" start "" "%DIR%\python\pythonw.exe" "%DIR%\run.py"
>>"%LOG%" echo fine
exit /b 0
:fail
>>"%LOG%" echo AGGIORNAMENTO NON RIUSCITO: versione precedente mantenuta
if exist "%NEW%" rmdir /s /q "%NEW%"
if "%RELAUNCH%"=="1" if exist "%DIR%\run.py" start "" "%DIR%\python\pythonw.exe" "%DIR%\run.py"
exit /b 1
'''

# Mac: sostituisce il bundle dopo la chiusura (prende il primo .app del dmg), con ripristino in caso di errore.
MAC_SCRIPT = r'''#!/bin/bash
PID="$1"; DMG="$2"; TARGET="$3"; RELAUNCH="$4"; LOG="$5"
exec >>"$LOG" 2>&1
echo "[$(date)] aggiornamento: $DMG -> $TARGET"
for _ in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
MNT="$(mktemp -d /tmp/tkftp-mnt.XXXXXX)"
if ! hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "$DMG"; then
  echo "montaggio dmg fallito"; exit 1
fi
SRC="$(ls -d "$MNT"/*.app 2>/dev/null | head -n 1)"
PARENT="$(dirname "$TARGET")"
STAGE="$PARENT/.tkftp-nuova.app"
OLD="$PARENT/.tkftp-vecchia.app"
rm -rf "$STAGE" "$OLD"
if [ -n "$SRC" ] && ditto "$SRC" "$STAGE" && mv "$TARGET" "$OLD" && mv "$STAGE" "$TARGET"; then
  rm -rf "$OLD"
  echo "app sostituita: $TARGET"
else
  echo "sostituzione fallita: ripristino"
  [ -d "$TARGET" ] || mv "$OLD" "$TARGET"
  rm -rf "$STAGE"
fi
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
hdiutil detach "$MNT" -quiet
rmdir "$MNT" 2>/dev/null
rm -f "$DMG"
if [ "$RELAUNCH" = "1" ]; then open "$TARGET"; fi
echo "fine"
'''


def platform_key():
    if IS_MAC:
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x86_64"
    return "windows"


def parse_version(value):
    parts = [int(x) for x in re.findall(r"\d+", str(value))[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def is_newer(remote, local=VERSION):
    return parse_version(remote) > parse_version(local)


def _open(url, timeout):
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": f"tk-ftp/{VERSION} ({platform_key()}{_codice_conteggio()})",
                                               "Cache-Control": "no-cache"})
    ctx = None
    if url.startswith("https:"):
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def fetch_manifest(url=MANIFEST_URL, timeout=12):
    if url.startswith("http"):
        url += ("&" if "?" in url else "?") + f"t={int(time.time())}"  # il server mette in cache i .json
    with _open(url, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8-sig"))
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError("risposta del server non valida")
    return data


def asset_for(manifest):
    for key in (["windows-zip", "windows"] if platform_key() == "windows" else [platform_key()]):
        asset = manifest.get(key)
        if isinstance(asset, dict) and asset.get("url") and asset_valido(SLUG, manifest, key, asset):
            return asset
    return None


def download_dir():
    path = os.path.join(tempfile.gettempdir(), "tk-ftp-update")
    os.makedirs(path, exist_ok=True)
    return path


def download(url, dest, sha256=None, progress=None, cancelled=None):
    digest = hashlib.sha256()
    tmp = dest + ".part"
    with _open(url, 60) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancelled and cancelled():
                fh.close()
                os.remove(tmp)
                raise InterruptedError("download annullato")
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if not sha256 or digest.hexdigest().lower() != str(sha256).lower():
        os.remove(tmp)
        raise ValueError("il file scaricato non è integro (verifica SHA-256 non riuscita). Riprova.")
    os.replace(tmp, dest)
    return dest


def apply_update(path, relaunch=True, new_version=""):
    """Avvia la sostituzione; subito dopo il chiamante deve chiudere il programma."""
    if IS_MAC:
        bundle = mac_bundle_path()
        parent = os.path.dirname(bundle)
        if not (os.access(parent, os.W_OK) and os.access(bundle, os.W_OK)):
            raise PermissionError("non hai i permessi per sostituire «" + bundle + "»")
        script = os.path.join(download_dir(), "applica-aggiornamento.sh")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(MAC_SCRIPT)
        log = os.path.join(log_dir(), "aggiornamento.log")
        subprocess.Popen(["/bin/bash", script, str(os.getpid()), path, bundle, "1" if relaunch else "0", log],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return
    script = os.path.join(download_dir(), "applica-aggiornamento.cmd")
    with open(script, "w", encoding="ascii", errors="replace", newline="\r\n") as fh:
        fh.write(WIN_SCRIPT)
    log = os.path.join(log_dir(), "aggiornamento.log")
    flags = 0x00000200 | 0x08000000  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(["cmd.exe", "/c", script, path, APP_ROOT, "1" if relaunch else "0", log, new_version],
                     cwd=download_dir(), creationflags=flags, close_fds=True)
