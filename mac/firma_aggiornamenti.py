"""Firma dei manifest di aggiornamento dei software TK (Ed25519, RFC 8032, solo libreria standard).

Ogni file del manifest (windows, windows-zip, mac-arm64…) riceve il campo «firma» su
  tk-aggiornamento-v1|<slug>|<versione>|<piattaforma>|<url>|<sha256>|<dimensione>
I programmi lo verificano con CHIAVE_AGGIORNAMENTI di tk_aggiornamento.py: chi entra nel sito
può cambiare il manifest ma non firmarlo, perché la chiave segreta sta solo sul PC di Pietro.

Uso:
  python -I firma_aggiornamenti.py genera                       crea la chiave (una volta sola)
  python -I firma_aggiornamenti.py firma --slug tk-pdf FILE.json firma il manifest sul posto
  python -I firma_aggiornamenti.py verifica --slug tk-pdf FILE.json

La chiave segreta sta in %USERPROFILE%\\.tk-firma\\aggiornamenti.chiave (fuori da Dropbox e dal
server). Se si perde non si possono più pubblicare aggiornamenti: tenerne una copia su chiavetta.
"""
import base64
import hashlib
import json
import os
import sys

CARTELLA = os.path.join(os.path.expanduser("~"), ".tk-firma")
FILE_CHIAVE = os.path.join(CARTELLA, "aggiornamenti.chiave")
ORIGINE = "https://pietrodefilippis.it/updates/"

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _somma(a, b):
    x = (a[1] - a[0]) * (b[1] - b[0]) % _P
    y = (a[1] + a[0]) * (b[1] + b[0]) % _P
    c = 2 * a[3] * b[3] * _D % _P
    d = 2 * a[2] * b[2] % _P
    e, f, g, h = y - x, d - c, d + c, y + x
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _per(n, a):
    r = (0, 1, 1, 0)
    while n > 0:
        if n & 1:
            r = _somma(r, a)
        a = _somma(a, a)
        n >>= 1
    return r


def _x(y, segno):
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x & 1) != segno:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


def _codifica(p):
    zi = pow(p[2], _P - 2, _P)
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _segreto(seme):
    h = hashlib.sha512(seme).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def pubblica(seme: bytes) -> bytes:
    return _codifica(_per(_segreto(seme)[0], _G))


def firma(seme: bytes, messaggio: bytes) -> bytes:
    a, prefisso = _segreto(seme)
    pub = _codifica(_per(a, _G))
    r = int.from_bytes(hashlib.sha512(prefisso + messaggio).digest(), "little") % _Q
    rr = _codifica(_per(r, _G))
    k = int.from_bytes(hashlib.sha512(rr + pub + messaggio).digest(), "little") % _Q
    return rr + ((r + k * a) % _Q).to_bytes(32, "little")


def messaggio(slug, versione, piattaforma, asset) -> bytes:
    """Stesso testo di tk_aggiornamento.messaggio(): se cambia uno, cambia anche l'altro."""
    return "|".join([
        "tk-aggiornamento-v1", slug, str(versione), piattaforma, str(asset["url"]),
        str(asset["sha256"]).lower(), str(int(asset["size"])),
    ]).encode("utf-8")


def _leggi_seme():
    # test della build (mac/build_mac.sh): chiave usa e getta dall'ambiente, mai quella vera
    if os.environ.get("TK_FIRMA_SEME_PROVA"):
        return base64.b64decode(os.environ["TK_FIRMA_SEME_PROVA"])
    if not os.path.exists(FILE_CHIAVE):
        sys.exit(f"Manca la chiave di firma {FILE_CHIAVE}: senza non si pubblicano aggiornamenti "
                 "(rimettila dalla copia su chiavetta).")
    with open(FILE_CHIAVE, encoding="ascii") as fh:
        seme = base64.b64decode(fh.read().strip())
    if len(seme) != 32:
        sys.exit("Chiave di firma non valida.")
    return seme


def _piattaforme(manifest):
    return [(k, v) for k, v in manifest.items() if isinstance(v, dict) and "url" in v]


def _controlla(slug, manifest):
    if not manifest.get("version"):
        sys.exit("Manifest senza versione.")
    origine = "file://" if os.environ.get("TK_FIRMA_SEME_PROVA") else ORIGINE
    for k, a in _piattaforme(manifest):
        if not str(a["url"]).startswith(origine):
            sys.exit(f"{k}: l'indirizzo deve iniziare con {ORIGINE}")
        if len(str(a.get("sha256", ""))) != 64 or not a.get("size"):
            sys.exit(f"{k}: mancano impronta SHA-256 o dimensione")


def cmd_genera():
    if os.path.exists(FILE_CHIAVE):
        sys.exit(f"La chiave esiste già ({FILE_CHIAVE}): non la sovrascrivo.")
    os.makedirs(CARTELLA, exist_ok=True)
    seme = os.urandom(32)
    with open(FILE_CHIAVE, "x", encoding="ascii") as fh:
        fh.write(base64.b64encode(seme).decode())
    print("Chiave creata:", FILE_CHIAVE)
    print("CHIAVE_AGGIORNAMENTI =", base64.b64encode(pubblica(seme)).decode())


def cmd_firma(slug, path):
    seme = _leggi_seme()
    with open(path, encoding="utf-8-sig") as fh:
        manifest = json.load(fh)
    _controlla(slug, manifest)
    for k, a in _piattaforme(manifest):
        a["firma"] = base64.b64encode(firma(seme, messaggio(slug, manifest["version"], k, a))).decode()
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"   manifest firmato ({len(_piattaforme(manifest))} file)")


def cmd_verifica(slug, path):
    from hmac import compare_digest
    pub = pubblica(_leggi_seme())
    with open(path, encoding="utf-8-sig") as fh:
        manifest = json.load(fh)
    ok = True
    for k, a in _piattaforme(manifest):
        attesa = firma(_leggi_seme(), messaggio(slug, manifest["version"], k, a))
        buona = compare_digest(base64.b64decode(a.get("firma", "")), attesa)
        print(f"   {k}: {'firma valida' if buona else 'FIRMA NON VALIDA'}")
        ok &= buona
    print("   chiave pubblica:", base64.b64encode(pub).decode())
    return 0 if ok else 1


def cmd_prova():
    """Chiave usa e getta per il test della build: stampa «seme chiave_pubblica» (base64)."""
    seme = os.urandom(32)
    print(base64.b64encode(seme).decode(), base64.b64encode(pubblica(seme)).decode())


def main(argv):
    if argv[:1] == ["genera"]:
        return cmd_genera()
    if argv[:1] == ["prova"]:
        return cmd_prova()
    if len(argv) == 4 and argv[0] in ("firma", "verifica") and argv[1] == "--slug":
        return (cmd_firma if argv[0] == "firma" else cmd_verifica)(argv[2], argv[3]) or 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
