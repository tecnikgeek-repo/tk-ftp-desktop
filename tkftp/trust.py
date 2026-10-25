"""Chiavi dei server SFTP e certificati FTPS accettati dall'utente (Dati/chiavi-server.json)."""
import json
import os
import threading

from tkftp.util import data_dir

_lock = threading.Lock()


def _path():
    return os.path.join(data_dir(), "chiavi-server.json")


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save(d):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())


def _id(host, port):
    return f"{host.lower()}:{int(port)}"


def known_hostkey(host, port):
    with _lock:
        return _load().get("ssh", {}).get(_id(host, port))


def remember_hostkey(host, port, keytype, b64, fingerprint):
    with _lock:
        d = _load()
        d.setdefault("ssh", {})[_id(host, port)] = {"tipo": keytype, "chiave": b64, "impronta": fingerprint}
        _save(d)


def trusted_cert(host, port):
    with _lock:
        return _load().get("tls", {}).get(_id(host, port))


def remember_cert(host, port, sha256, info):
    with _lock:
        d = _load()
        d.setdefault("tls", {})[_id(host, port)] = dict(info, sha256=sha256)
        _save(d)


def remember_tls(host, port):
    """Il server ha accettato TLS: d'ora in poi un «non supporto TLS» è sospetto e non si passa al chiaro."""
    with _lock:
        d = _load()
        if not d.get("tls_visto", {}).get(_id(host, port)):
            d.setdefault("tls_visto", {})[_id(host, port)] = True
            d.get("chiaro", {}).pop(_id(host, port), None)
            _save(d)


def tls_seen(host, port):
    with _lock:
        return bool(_load().get("tls_visto", {}).get(_id(host, port)))


def allow_plain(host, port):
    """L'utente ha accettato di collegarsi in chiaro a questo server (non supporta TLS)."""
    with _lock:
        d = _load()
        d.setdefault("chiaro", {})[_id(host, port)] = True
        _save(d)


def plain_allowed(host, port):
    with _lock:
        return bool(_load().get("chiaro", {}).get(_id(host, port)))


def forget(host, port):
    with _lock:
        d = _load()
        for k in ("ssh", "tls", "tls_visto", "chiaro"):
            d.get(k, {}).pop(_id(host, port), None)
        _save(d)
