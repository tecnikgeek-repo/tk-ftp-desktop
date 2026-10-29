# -*- mode: python -*-
# PyInstaller: crea la cartella «dist/tk-ftp» per Linux, poi build_linux.sh la mette nell'AppImage.
# Uso: pyinstaller --noconfirm --clean linux/tk-ftp-linux.spec
import os
import re
import shutil
import sys
from importlib import metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "tkftp", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'VERSION = "(.+)"', fh.read()).group(1)

# licenze (finiscono in _internal/licenze): AGPL di tk-ftp, elenco dei componenti, testi generici e i file di
# licenza ORIGINALI dei pacchetti inclusi (dai *.dist-info) + la licenza di Python
LIC = os.path.join(ROOT, "build", "licenze")
shutil.rmtree(LIC, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "licenze"), LIC)
for pkg in ("paramiko", "cryptography", "bcrypt", "pynacl", "cffi", "certifi", "secretstorage", "jeepney"):
    try:
        dist = metadata.distribution(pkg)
    except metadata.PackageNotFoundError:
        continue
    for f in dist.files or []:
        name = os.path.basename(str(f))
        if ".dist-info" in str(f) and re.match(r"(LICEN[CS]E|COPYING|NOTICE)", name):
            n = re.sub(r"\.txt$", "", name).replace(".", "-")
            shutil.copy(str(f.locate()), os.path.join(LIC, f"{pkg.lower()}-{n}.txt"))
for cand in (os.path.join(os.path.dirname(os.__file__), "LICENSE.txt"), os.path.join(sys.base_prefix, "LICENSE.txt"),
             f"/usr/share/doc/python{sys.version_info[0]}.{sys.version_info[1]}/copyright"):
    if os.path.isfile(cand):
        shutil.copy(cand, os.path.join(LIC, "Python-LICENSE.txt"))
        break
# libxcb-cursor (MIT/X11), messa nel pacchetto da build_linux.sh per chi usa X11
xcb_lic = os.path.join(ROOT, "build", "xcb-cursor", "copyright")
if os.path.isfile(xcb_lic):
    shutil.copy(xcb_lic, os.path.join(LIC, "libxcb-cursor-LICENSE.txt"))

extra_bin = []
xcb_lib = os.path.join(ROOT, "build", "xcb-cursor", "libxcb-cursor.so.0")
if os.path.isfile(xcb_lib):
    extra_bin.append((xcb_lib, "."))

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=extra_bin,
    datas=[(os.path.join(ROOT, "assets", "tk-ftp-512.png"), "assets"), (LIC, "licenze")],
    hiddenimports=["PySide6.QtSvg", "paramiko", "nacl.signing", "bcrypt", "cryptography.hazmat.primitives.ciphers.aead",
                   "tkftp.pro", "tkftp.tk_licenza", "tkftp.tk_licenza_qt", "secretstorage", "jeepney",
                   "jeepney.io.blocking"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia",
              "PySide6.QtPdf", "PySide6.QtPrintSupport", "invoke"],
)

# componenti Qt non usati da un'app a widget
DROP = ("QtQuick", "QtQml", "QtVirtualKeyboard", "QtPdf", "libqpdf", "QtWebEngine", "Qt3D", "QtMultimedia")
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in DROP)]
a.datas = [d for d in a.datas if not any(k in d[0] for k in DROP)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="tk-ftp", console=False, strip=False)
coll = COLLECT(exe, a.binaries, a.datas, name="tk-ftp")
