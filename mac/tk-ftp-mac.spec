# -*- mode: python -*-
# PyInstaller: crea "tk-ftp.app" per macOS. Uso: pyinstaller --noconfirm --clean mac/tk-ftp-mac.spec
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "tkftp", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'VERSION = "(.+)"', fh.read()).group(1)

# licenze (finiscono in tk-ftp.app/Contents/Resources/licenze): AGPL di tk-ftp, elenco dei componenti, testi
# generici e i file di licenza ORIGINALI dei pacchetti inclusi (dai *.dist-info) + la licenza di Python
import shutil  # noqa: E402
import sys  # noqa: E402
from importlib import metadata  # noqa: E402

LIC = os.path.join(ROOT, "build", "licenze")
shutil.rmtree(LIC, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "licenze"), LIC)
for pkg in ("paramiko", "cryptography", "bcrypt", "pynacl", "cffi", "certifi"):  # Qt/PySide6: LGPL-3.0.txt
    try:
        dist = metadata.distribution(pkg)
    except metadata.PackageNotFoundError:
        continue
    for f in dist.files or []:
        name = os.path.basename(str(f))
        if ".dist-info" in str(f) and re.match(r"(LICEN[CS]E|COPYING|NOTICE)", name):
            n = re.sub(r"\.txt$", "", name).replace(".", "-")
            shutil.copy(str(f.locate()), os.path.join(LIC, f"{pkg.lower()}-{n}.txt"))
for cand in (os.path.join(os.path.dirname(os.__file__), "LICENSE.txt"), os.path.join(sys.base_prefix, "LICENSE.txt")):
    if os.path.isfile(cand):
        shutil.copy(cand, os.path.join(LIC, "Python-LICENSE.txt"))
        break

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "assets", "tk-ftp-512.png"), "assets"), (LIC, "licenze")],
    hiddenimports=["PySide6.QtSvg", "paramiko", "nacl.signing", "bcrypt", "cryptography.hazmat.primitives.ciphers.aead",
                   "tkftp.pro", "tkftp.tk_licenza", "tkftp.tk_licenza_qt"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia",
              "PySide6.QtPdf", "PySide6.QtPrintSupport", "invoke"],
)

# componenti Qt non usati da un'app a widget
DROP = ("QtQuick", "QtQml", "QtVirtualKeyboard", "QtPdf", "libqpdf", "QtWebEngine", "Qt3D", "QtMultimedia")
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in DROP)]
a.datas = [d for d in a.datas if not any(k in d[0] for k in DROP)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="tk-ftp", console=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="tk-ftp")
app = BUNDLE(
    coll,
    name="tk-ftp.app",
    icon=os.path.join(ROOT, "assets", "tk-ftp.icns"),
    bundle_identifier="com.tecnikgeek.tkftp",
    version=VERSION,
    info_plist={
        "CFBundleName": "tk-ftp",
        "CFBundleDisplayName": "tk-ftp",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": True,
        "NSHumanReadableCopyright": "TecnikGeek - pietrodefilippis.it",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
)
