"""Frasi per chi usa il programma: il testo tecnico degli errori non va mai a schermo, solo nel registro.

Passano così come sono solo i messaggi scritti da noi: le classi di errore col campo ``leggibile = True``.
"""
# Copyright (C) 2026 Pietro De Filippis (TecnikGeek) — AGPL-3.0-or-later, vedi COPYING
import errno
import logging
import socket
import ssl
import urllib.error

_registro = logging.getLogger("tk")


def motivo_errore(exc):
    """Perché non è riuscito, in parole semplici. Il dettaglio resta nel registro."""
    _registro.warning("errore: %r", exc)
    if getattr(exc, "leggibile", False):
        return str(exc)
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "Lo spazio sul disco è finito: liberane un po' e riprova."
    if isinstance(exc, (urllib.error.URLError, socket.gaierror, socket.timeout, TimeoutError,
                        ConnectionError, ssl.SSLError)):
        return "Controlla la connessione a Internet e riprova."
    if isinstance(exc, PermissionError):
        return "Non hai il permesso, oppure il file è aperto in un altro programma: chiudilo e riprova."
    if isinstance(exc, FileNotFoundError):
        return "Il file non si trova più: controlla che esista ancora."
    return "Riprova: se succede ancora, chiudi e riapri il programma."


def frase_errore(cosa, exc):
    """La frase da mostrare: ``cosa`` dice cosa non è riuscito."""
    return f"{cosa} {motivo_errore(exc)}"
