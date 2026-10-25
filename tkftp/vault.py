"""Password dei siti e frase segreta della cartella condivisa: mai in chiaro su disco.
Windows: Gestione credenziali (credenziali generiche «tk-ftp:…», legate all'utente di Windows).
Mac: Portachiavi (servizio «tk-ftp»), scritto con «security -i» così la password non compare tra gli argomenti."""
import base64
import os
import subprocess

from tkftp.util import IS_MAC, IS_WIN

SERVICE = os.environ.get("TKFTP_VAULT_SERVICE", "tk-ftp")  # i test usano un nome loro, mai quello vero


if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]
    _GENERIC, _PERSIST_LOCAL = 1, 2

    def _target(account):
        return f"{SERVICE}:{account}"


def set_secret(account, secret):
    raw = secret.encode("utf-8")
    if IS_WIN:
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw) if raw else None
        cred = _CREDENTIAL()
        cred.Type = _GENERIC
        cred.TargetName = _target(account)
        cred.Comment = "tk-ftp"
        cred.CredentialBlobSize = len(raw)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)) if raw else None
        cred.Persist = _PERSIST_LOCAL
        cred.UserName = account
        if not _adv.CredWriteW(ctypes.byref(cred), 0):
            raise OSError(f"Gestione credenziali di Windows: scrittura non riuscita ({ctypes.get_last_error()})")
        return
    if IS_MAC:
        # in base64: «security … -w» restituisce in esadecimale le password con lettere accentate
        value = "b64:" + base64.b64encode(raw).decode()
        cmd = f'add-generic-password -U -s "{SERVICE}" -a "{account}" -l "tk-ftp" -w "{value}"\n'
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise OSError("Portachiavi: scrittura non riuscita " + (r.stderr or "").strip()[:200])
        return
    raise OSError("portachiavi non disponibile su questo sistema")


def get_secret(account):
    """Il segreto salvato, oppure None."""
    if IS_WIN:
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _adv.CredReadW(_target(account), _GENERIC, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            data = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
            return data.decode("utf-8", "replace")
        finally:
            _adv.CredFree(p)
    if IS_MAC:
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        out = r.stdout.rstrip("\n")
        if out.startswith("b64:"):
            try:
                return base64.b64decode(out[4:]).decode("utf-8")
            except Exception:
                return None
        return out
    return None


def purge_service():
    """Cancella TUTTE le voci del servizio corrente (solo per i collaudi, che usano un servizio loro)."""
    if SERVICE == "tk-ftp":
        raise RuntimeError("purge_service non si usa sul servizio vero")
    if IS_WIN:
        count = wintypes.DWORD()
        arr = ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))()
        _adv.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)))]
        if not _adv.CredEnumerateW(f"{SERVICE}:*", 0, ctypes.byref(count), ctypes.byref(arr)):
            return 0
        names = [arr[i].contents.TargetName for i in range(count.value)]
        _adv.CredFree(arr)
        for n in names:
            _adv.CredDeleteW(n, _GENERIC, 0)
        return len(names)
    if IS_MAC:
        n = 0
        while subprocess.run(["security", "delete-generic-password", "-s", SERVICE], capture_output=True,
                             timeout=20).returncode == 0 and n < 500:
            n += 1
        return n
    return 0


def delete_secret(account):
    if IS_WIN:
        _adv.CredDeleteW(_target(account), _GENERIC, 0)
        return
    if IS_MAC:
        subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", account],
                       capture_output=True, timeout=20)
