#!/bin/bash
# Crea dist/tk-ftp-<versione>-mac-<arch>.dmg. Da eseguire su un Mac (o sul runner macOS di GitHub).
# Uso: bash mac/build_mac.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARCH="$(uname -m)"
PY="${PYTHON:-python3}"
VERSION="$($PY -c "import re;print(re.search(r'VERSION = \"(.+)\"', open('tkftp/__init__.py').read()).group(1))")"
echo "== tk-ftp $VERSION per macOS ($ARCH)"

$PY -m venv .venv-mac
# shellcheck disable=SC1091
source .venv-mac/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet "pyside6-essentials==6.11.*" paramiko certifi pyinstaller pyftpdlib pyopenssl
# Mac Intel: dalla 49 cryptography non ha più il pacchetto pronto (si compila contro l'OpenSSL di Homebrew e nel .app
# finisce la libssl di Python, più vecchia: «Symbol not found: _SSL_get0_group_name»). La 48 universal2 ha OpenSSL dentro.
if [ "$(uname -m)" = "x86_64" ]; then
  python -m pip install --quiet --only-binary=cryptography "cryptography<49" "pyopenssl<26.3"
fi

echo "== collaudo del nucleo (FTP, FTPS, SFTP contro server locali, Portachiavi)"
mkdir -p dist
QT_QPA_PLATFORM=offscreen python tests/test_core.py > "dist/test-core-$ARCH.txt" 2>&1 || {
    tail -n 60 "dist/test-core-$ARCH.txt"; echo "COLLAUDO DEL NUCLEO FALLITO"; exit 1; }
tail -n 4 "dist/test-core-$ARCH.txt"

echo "== icona"
QT_QPA_PLATFORM=offscreen python tools_make_icon.py
QT_QPA_PLATFORM=offscreen python tools_make_icon.py --iconset
iconutil -c icns assets/tk-ftp.iconset -o assets/tk-ftp.icns

echo "== app"
rm -rf build dist/*.app dist/tk-ftp
pyinstaller --noconfirm --clean mac/tk-ftp-mac.spec
APP="dist/tk-ftp.app"
for lang in Base en it; do
    mkdir -p "$APP/Contents/Resources/$lang.lproj"
    printf 'CFBundleName = "tk-ftp";\nCFBundleDisplayName = "tk-ftp";\n' >"$APP/Contents/Resources/$lang.lproj/InfoPlist.strings"
done
codesign --force --deep --sign - "$APP"

echo "== selftest"
SHOT="$ROOT/dist/selftest-$ARCH.png"
TXT="$ROOT/dist/selftest-$ARCH.txt"
run_selftest() {
    "$APP/Contents/MacOS/tk-ftp" --selftest "$SHOT" &
    local pid=$!
    for _ in $(seq 1 90); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill "$pid" 2>/dev/null || true
}
run_selftest
if [ ! -f "$SHOT" ]; then
    echo "   finestra non disponibile, riprovo in modalità offscreen"
    export QT_QPA_PLATFORM=offscreen
    run_selftest
    unset QT_QPA_PLATFORM
fi
[ -f "$SHOT" ] || { echo "SELFTEST FALLITO: l'app non si avvia"; exit 1; }
cat "$TXT"; echo
grep -q "^OK" "$TXT" || { echo "SELFTEST FALLITO: librerie mancanti nel pacchetto"; exit 1; }
echo "   selftest OK"

echo "== Portachiavi dal pacchetto"
"$APP/Contents/MacOS/tk-ftp" --vault-test "$ROOT/dist/vault-$ARCH.txt" || true
cat "$ROOT/dist/vault-$ARCH.txt" 2>/dev/null || true; echo

echo "== dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applicazioni"
cp mac/LEGGIMI.txt "$STAGE/Leggimi - primo avvio.txt"
DMG="dist/tk-ftp-$VERSION-mac-$ARCH.dmg"
for tentativo in 1 2 3 4; do
    if hdiutil create -volname "tk-ftp $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"; then
        break
    fi
    echo "   hdiutil occupato, riprovo ($tentativo)"
    sleep 6
    [ "$tentativo" = "4" ] && { echo "CREAZIONE DMG FALLITA"; exit 1; }
done
rm -rf "$STAGE"
echo "== Creato $DMG ($(du -h "$DMG" | cut -f1))"

if [ "${SKIP_UPDATE_TEST:-0}" != "1" ]; then
    echo "== test aggiornamento automatico"
    TESTAPP="$HOME/Applications/tk-ftp.app"
    mkdir -p "$HOME/Applications"
    rm -rf "$TESTAPP"
    cp -R "$APP" "$TESTAPP"
    BEFORE="$(stat -f %i "$TESTAPP/Contents/Info.plist")"
    COPY="$(mktemp -d)/tk-ftp-test.dmg"
    cp "$DMG" "$COPY"   # lo script di aggiornamento cancella il dmg usato
    SHA="$(shasum -a 256 "$COPY" | cut -d' ' -f1)"
    SIZE="$(stat -f %z "$COPY")"
    MANIFEST="$(mktemp -d)/tk-ftp.json"
    printf '{"version":"99.0.0","notes":["test"],"mac-%s":{"url":"file://%s","sha256":"%s","size":%s}}' "$ARCH" "$COPY" "$SHA" "$SIZE" > "$MANIFEST"
    # aggiornamenti firmati: chiave usa e getta solo per questo test (la vera resta sul PC di Pietro)
    read -r SEME PUB <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_FIRMA_SEME_PROVA="$SEME" python mac/firma_aggiornamenti.py firma --slug tk-ftp "$MANIFEST"
    TK_AGGIORNAMENTI_PROVA="$PUB" "$TESTAPP/Contents/MacOS/tk-ftp" --update-test "file://$MANIFEST" --no-relaunch
    AFTER="$BEFORE"
    for _ in $(seq 1 120); do
        if [ -f "$TESTAPP/Contents/Info.plist" ]; then
            AFTER="$(stat -f %i "$TESTAPP/Contents/Info.plist" 2>/dev/null || echo "$BEFORE")"
            [ "$AFTER" != "$BEFORE" ] && break
        fi
        sleep 1
    done
    cat "$HOME/Library/Application Support/tk-ftp/aggiornamento.log" 2>/dev/null || true
    if [ "$AFTER" = "$BEFORE" ] || [ ! -x "$TESTAPP/Contents/MacOS/tk-ftp" ]; then
        echo "TEST AGGIORNAMENTO FALLITO"
        exit 1
    fi
    rm -rf "$TESTAPP"
    echo "   aggiornamento OK (bundle sostituito)"
fi
