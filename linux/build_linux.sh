#!/bin/bash
# Crea dist/tk-ftp-<versione>-linux-<arch>.AppImage. Da eseguire su Linux (Ubuntu di casa o runner di GitHub).
# Uso: bash linux/build_linux.sh
# Usa al massimo METÀ dei processori (JOBS per cambiarlo): con tutti, sul PC di casa la memoria si riempie.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export JOBS="${JOBS:-$(( $(nproc) / 2 > 0 ? $(nproc) / 2 : 1 ))}"  # esportato: dopo taskset nproc vede già la metà
if [ -z "${TK_BUILD_LIMITATA:-}" ] && command -v taskset >/dev/null; then
    export TK_BUILD_LIMITATA=1
    exec nice -n 10 taskset -c "0-$(( JOBS - 1 ))" bash "$0" "$@"
fi
ARCH="$(uname -m)"
PY="${PYTHON:-python3}"
VERSION="$($PY -c "import re;print(re.search(r'VERSION = \"(.+)\"', open('tkftp/__init__.py').read()).group(1))")"
APPIMAGETOOL_VER="1.9.0"
echo "== tk-ftp $VERSION per Linux ($ARCH), $JOBS processori"

$PY -m venv .venv-linux
# shellcheck disable=SC1091
source .venv-linux/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet "pyside6-essentials==6.11.*" paramiko certifi secretstorage pyinstaller pyftpdlib pyopenssl

mkdir -p dist build
if [ "${SKIP_CORE_TEST:-0}" != "1" ]; then
    echo "== collaudo del nucleo (FTP, FTPS, SFTP contro server locali, portachiavi)"
    QT_QPA_PLATFORM=offscreen python tests/test_core.py > "dist/test-core-linux-$ARCH.txt" 2>&1 || {
        tail -n 60 "dist/test-core-linux-$ARCH.txt"; echo "COLLAUDO DEL NUCLEO FALLITO"; exit 1; }
    tail -n 4 "dist/test-core-linux-$ARCH.txt"
fi

echo "== libxcb-cursor (serve a Qt sotto X11; su Wayland no): presa dal pacchetto Ubuntu, non installata"
rm -rf build/xcb-cursor && mkdir -p build/xcb-cursor
(cd build/xcb-cursor && apt-get download libxcb-cursor0 >/dev/null && dpkg-deb -x libxcb-cursor0_*.deb x \
    && cp x/usr/lib/*/libxcb-cursor.so.0.* libxcb-cursor.so.0 && cp x/usr/share/doc/libxcb-cursor0/copyright .) \
    || echo "   libxcb-cursor non disponibile: il pacchetto funzionerà solo su Wayland o con la libreria di sistema"

echo "== programma"
rm -rf build/tk-ftp-linux dist/tk-ftp
pyinstaller --noconfirm --clean --workpath build/tk-ftp-linux linux/tk-ftp-linux.spec

echo "== AppImage"
APPDIR="build/AppDir"
rm -rf "$APPDIR" && mkdir -p "$APPDIR/usr/lib"
cp -a dist/tk-ftp "$APPDIR/usr/lib/tk-ftp"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/tk-ftp/tk-ftp" "$@"
EOF
chmod 755 "$APPDIR/AppRun"
cat > "$APPDIR/tk-ftp.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=tk-ftp
GenericName=Client FTP
Comment=Client FTP, FTPS e SFTP con due pannelli (TecnikGeek)
Exec=tk-ftp %U
Icon=tk-ftp
Terminal=false
Categories=Network;FileTransfer;
StartupWMClass=tk-ftp
EOF
cp assets/tk-ftp-512.png "$APPDIR/tk-ftp.png"
ln -sf tk-ftp.png "$APPDIR/.DirIcon"

TOOLS="${TK_STRUMENTI_BUILD:-$HOME/.cache/tk-build}"
TOOL="$TOOLS/appimagetool-$APPIMAGETOOL_VER-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$TOOLS"
    curl -fsSL -o "$TOOL.part" \
        "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VER/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL.part" && mv "$TOOL.part" "$TOOL"
fi
OUT="dist/tk-ftp-$VERSION-linux-$ARCH.AppImage"
rm -f "$OUT"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" --no-appstream \
    --mksquashfs-opt -processors --mksquashfs-opt "$JOBS" "$APPDIR" "$OUT" > build/appimagetool.log 2>&1 || {
    tail -n 30 build/appimagetool.log; echo "CREAZIONE APPIMAGE FALLITA"; exit 1; }
chmod 755 "$OUT"
echo "== Creato $OUT ($(du -h "$OUT" | cut -f1))"

echo "== selftest (dal file AppImage)"
SHOT="$ROOT/dist/selftest-linux-$ARCH.png"
TXT="$ROOT/dist/selftest-linux-$ARCH.txt"
rm -f "$SHOT" "$TXT"
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" timeout 90 "$OUT" --selftest "$SHOT" || true
[ -f "$SHOT" ] || { echo "SELFTEST FALLITO: il programma non si avvia"; exit 1; }
cat "$TXT"; echo
grep -q "^OK" "$TXT" || { echo "SELFTEST FALLITO: librerie mancanti nel pacchetto"; exit 1; }

echo "== portachiavi dal pacchetto"
timeout 60 "$OUT" --vault-test "$ROOT/dist/vault-linux-$ARCH.txt" || true
cat "$ROOT/dist/vault-linux-$ARCH.txt" 2>/dev/null || true; echo

if [ "${SKIP_UPDATE_TEST:-0}" != "1" ]; then
    echo "== test aggiornamento automatico"
    WORK="$(mktemp -d)"
    TESTAPP="$WORK/Programmi/tk-ftp.AppImage"     # copia «installata» che deve essere sostituita
    mkdir -p "$(dirname "$TESTAPP")"
    cp "$OUT" "$TESTAPP"
    BEFORE="$(stat -c %i "$TESTAPP")"
    COPY="$WORK/tk-ftp-nuova.AppImage"
    cp "$OUT" "$COPY"   # lo script di aggiornamento cancella il file usato
    SHA="$(sha256sum "$COPY" | cut -d' ' -f1)"
    SIZE="$(stat -c %s "$COPY")"
    MANIFEST="$WORK/tk-ftp.json"
    printf '{"version":"99.0.0","notes":["test"],"linux-%s":{"url":"file://%s","sha256":"%s","size":%s}}' \
        "$ARCH" "$COPY" "$SHA" "$SIZE" > "$MANIFEST"
    # aggiornamenti firmati: chiave usa e getta solo per questo test (la vera resta sul PC di Pietro)
    read -r SEME PUB <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_FIRMA_SEME_PROVA="$SEME" python mac/firma_aggiornamenti.py firma --slug tk-ftp "$MANIFEST"
    export TKFTP_DATI="$WORK/dati"
    # prima la prova contraria: manifest firmato con un'altra chiave = rifiutato
    read -r _ ALTRA <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_AGGIORNAMENTI_PROVA="$ALTRA" "$TESTAPP" --update-test "file://$MANIFEST" --no-relaunch || true
    grep -q "rifiutato" "$TKFTP_DATI/update-test.log" || { cat "$TKFTP_DATI/update-test.log"; echo "TEST FIRMA FALLITO: accettato con la chiave sbagliata"; exit 1; }
    TK_AGGIORNAMENTI_PROVA="$PUB" "$TESTAPP" --update-test "file://$MANIFEST" --no-relaunch
    AFTER="$BEFORE"
    for _ in $(seq 1 120); do
        AFTER="$(stat -c %i "$TESTAPP" 2>/dev/null || echo "$BEFORE")"
        [ "$AFTER" != "$BEFORE" ] && break
        sleep 1
    done
    cat "$TKFTP_DATI/update-test.log" "$TKFTP_DATI/aggiornamento.log" 2>/dev/null || true
    unset TKFTP_DATI
    if [ "$AFTER" = "$BEFORE" ] || [ ! -x "$TESTAPP" ] || ! cmp -s "$TESTAPP" "$OUT"; then
        echo "TEST AGGIORNAMENTO FALLITO"
        exit 1
    fi
    rm -rf "$WORK"
    echo "   aggiornamento OK (file AppImage sostituito, firma sbagliata rifiutata)"
fi
