"""Linux per i software TK, parte che usa Qt: i link aperti con QDesktopServices.

Copia IDENTICA in ogni software TK accanto a tk_linux.py (originale in Dropbox\\CLAUDE\\tk-software\\librerie).
Qt apre i link con un xdg-open che eredita l'ambiente del pacchetto (librerie Qt e Python incluse): il browser o
il programma di posta potrebbero non partire. Con instrada_link() tutti i QDesktopServices.openUrl del programma,
anche quelli delle librerie comuni (Informazioni, caffè, licenze), passano da tk_linux.apri con l'ambiente pulito.
"""
from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices

from . import tk_linux

SCHEMI = ("http", "https", "mailto", "file")


class _ApriConIlSistema(QObject):
    @Slot(QUrl)
    def apri(self, url):
        tk_linux.apri(url.toLocalFile() if url.isLocalFile() else url.toString())


def instrada_link(app):
    """Da chiamare una volta dopo aver creato QApplication (solo su Linux non fa niente altrove). Ritorna
    l'oggetto che riceve i link: resta in vita come figlio di app."""
    if not tk_linux.IS_LINUX:
        return None
    gestore = _ApriConIlSistema(app)
    for schema in SCHEMI:
        QDesktopServices.setUrlHandler(schema, gestore, "apri")
    return gestore
