"""Memoria del programma e donazione libera.

tk-ftp è software libero (AGPL-3.0) con tutte le funzioni per tutti: qui restano solo la «licenza» (che ora è
la piccola memoria del programma: benvenuto visto, consenso alle statistiche, invito al caffè), il pulsante
«Offrimi un caffè» e l'invito discreto all'avvio. Il nome del file resta per non rompere gli import.
"""
import os
import sys

from PySide6.QtWidgets import QApplication


def crea_licenza(versione):
    """La memoria sta nella cartella dell'utente, non accanto al programma: tk-ftp gira anche da pennetta."""
    try:
        from tkftp.tk_licenza import Licenza
        if os.environ.get("TKFTP_DATI"):
            base = os.environ["TKFTP_DATI"]
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Licenza("tk-ftp", versione, os.path.join(base, "tk-ftp"))
    except Exception:
        return None


def licenza():
    return getattr(QApplication.instance(), "licenza", None)


def pulsante_caffe(nome_oggetto=""):
    from tkftp.tk_licenza_qt import pulsante_caffe as crea
    return crea(licenza(), nome_oggetto=nome_oggetto)


def invito(parent=None, puo_mostrare=None):
    """Invito al caffè all'avvio: la prima volta e poi al massimo una volta al mese (vedi tk_licenza_qt)."""
    try:
        from tkftp.style import logo_tile
        from tkftp.tk_licenza_qt import invito_caffe
        invito_caffe(licenza(), "tk-ftp", parent, logo_tile(104), puo_mostrare)
    except Exception:
        pass
