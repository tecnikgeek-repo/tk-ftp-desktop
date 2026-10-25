"""Verifica degli aggiornamenti dei software TK.

Copia IDENTICA in ogni software TK accanto a tk_licenza.py (originale in Dropbox\\CLAUDE\\tk-software\\librerie).
Un aggiornamento si installa solo se il suo file nel manifest è firmato con la chiave degli aggiornamenti
(Ed25519): la chiave segreta sta solo sul PC di Pietro, quindi anche chi entrasse nel sito non potrebbe
far installare un file suo. In più l'impronta SHA-256 è obbligatoria e il file deve stare sotto ORIGINE.
La firma la mette release\\publish.ps1 con librerie\\firma_aggiornamenti.py.
"""
import base64
import os

from .tk_licenza import verifica_firma

CHIAVE_AGGIORNAMENTI = "X3D/BTq64qNAkYfSmG1BqJGSqxhbvbtZrUQniBjWZHo="
ORIGINE = "https://pietrodefilippis.it/updates/"
# Solo per il test automatico della build (mac/build_mac.sh): chiave usa e getta passata dall'ambiente,
# accettata insieme a file:// . Chi può impostare l'ambiente del programma ha già il controllo del computer.
PROVA = "TK_AGGIORNAMENTI_PROVA"


def messaggio(slug, versione, piattaforma, asset) -> bytes:
    """Stesso testo di firma_aggiornamenti.messaggio(): se cambia uno, cambia anche l'altro."""
    return "|".join([
        "tk-aggiornamento-v1", slug, str(versione), piattaforma, str(asset["url"]),
        str(asset["sha256"]).lower(), str(int(asset["size"])),
    ]).encode("utf-8")


def asset_valido(slug, manifest, piattaforma, asset) -> bool:
    """True solo se il file è sotto ORIGINE, ha impronta e dimensione ed è firmato."""
    try:
        chiave, origini = CHIAVE_AGGIORNAMENTI, (ORIGINE,)
        if os.environ.get(PROVA):
            chiave, origini = os.environ[PROVA], ("file://",)
        if not str(asset.get("url", "")).startswith(origini):
            return False
        if len(str(asset.get("sha256", ""))) != 64 or int(asset.get("size") or 0) <= 0:
            return False
        return verifica_firma(base64.b64decode(chiave),
                              messaggio(slug, manifest["version"], piattaforma, asset),
                              base64.b64decode(str(asset.get("firma", ""))))
    except Exception:
        return False
