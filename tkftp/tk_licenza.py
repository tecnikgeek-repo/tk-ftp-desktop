"""tk_licenza — software libero (AGPL-3.0), donazione facoltativa e statistiche col consenso (Python).

Copia IDENTICA in ogni software TK (come class-tk-license.php nei plugin): l'originale sta in
Dropbox\\CLAUDE\\tk-software\\librerie\\tk_licenza.py. Solo libreria standard: niente DLL nuove
che Smart App Control potrebbe bloccare.

Dal 2026-10-25 i software TK sono software libero (AGPL-3.0) con TUTTE le funzioni per tutti:
niente chiavi, niente Free/Pro. La donazione è libera e non sblocca nulla.

Uso:
    from tkpdf.tk_licenza import Licenza
    lic = Licenza("tk-pdf", VERSION, cartella_dati)
    lic.avvia()                    # in sottofondo: segnale del giorno, SOLO se l'utente ha detto sì
    lic.sbloccato()                # sempre vero (resta per il codice che lo chiede ancora)
    lic.consenso_statistiche()     # None = non ha ancora risposto, True/False = la sua scelta
    lic.imposta_statistiche(True)

Statistiche: una volta al giorno /ping-app con nome, versione, sistema e un codice CASUALE creato
la prima volta (non ricavato dal computer), solo dopo il sì nella finestra di benvenuto.
Il resto (verifica_firma, chiavi Pro delle versioni vecchie) resta per compatibilità.
"""
import base64
import hashlib
import json
import os
import platform
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

SERVER = "https://pietrodefilippis.it/wp-json/tk-license/v1"
# codice anonimo che l'updater aggiunge alla richiesta del manifest: un'installazione conta una volta sola anche
# se cambia rete. Lo imposta Licenza all'avvio ("" finché non c'è: allora il server conta per indirizzo)
CODICE_CONTEGGIO = ""
# Chiave pubblica Ed25519 del server licenze (GET /chiave-pubblica). La segreta resta sul server.
CHIAVE_PUBBLICA = "3SMmzwVHDZTk7TPQeQhwQoT6mi2zroNja3wzan06Br0="
RICONTROLLO = 7 * 86400        # ogni quanto si richiede al server lo stato della chiave
TOLLERANZA = 30 * 86400        # quanto vale l'ultima risposta firmata senza internet
TIMEOUT = 10
DONAZIONE = "https://pietrodefilippis.it/donazione/"


def url_italiano(url: str) -> str:
    """La pagina di donazione di PayPal si apre in inglese se il link non dice la lingua: la aggiunge
    (anche ai link vecchi rimasti nella memoria del programma)."""
    if "paypal.com/donate" in url and "locale.x=" not in url:
        url += ("&" if "?" in url else "?") + "locale.x=it_IT"
    return url


# ------------------------------------------------------------------ Ed25519 (verifica, RFC 8032)
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
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if segno else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != segno:
        x = _P - x
    return x


def _punto(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    segno = y >> 255
    y &= (1 << 255) - 1
    x = _x(y, segno)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


def verifica_firma(pubblica: bytes, messaggio: bytes, firma: bytes) -> bool:
    try:
        if len(pubblica) != 32 or len(firma) != 64:
            return False
        a = _punto(pubblica)
        r = _punto(firma[:32])
        s = int.from_bytes(firma[32:], "little")
        if a is None or r is None or s >= _Q:
            return False
        h = int.from_bytes(hashlib.sha512(firma[:32] + pubblica + messaggio).digest(), "little") % _Q
        sb = _per(s, _G)
        ra = _somma(r, _per(h, a))
        return (sb[0] * ra[2] - ra[0] * sb[2]) % _P == 0 and (sb[1] * ra[2] - ra[1] * sb[2]) % _P == 0
    except Exception:
        return False


# ------------------------------------------------------------------ sistema
def piattaforma():
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def versione_sistema():
    try:
        if sys.platform == "darwin":
            return platform.mac_ver()[0]
        if sys.platform == "win32":
            v = sys.getwindowsversion()
            return ("11" if v.build >= 22000 else platform.release()) + f" ({v.build})"
        return platform.release()
    except Exception:
        return ""


# ------------------------------------------------------------------ licenza
class Licenza:
    def __init__(self, slug: str, versione: str, cartella_dati: str, free_pro_predefinito: bool = False):
        self.slug = slug
        self.versione = versione
        self.free_pro_predefinito = free_pro_predefinito
        self.cartella = cartella_dati
        self.file = os.path.join(cartella_dati, "licenza.json")
        self._blocco = threading.Lock()
        self._stato = self._leggi()
        self.dispositivo = self._dispositivo()

    # -- archivio locale
    def _leggi(self):
        try:
            with open(self.file, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _scrivi(self):
        try:
            os.makedirs(self.cartella, exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._stato, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.file)
        except Exception:
            pass

    def _dispositivo(self):
        # codice casuale creato la prima volta e conservato: non si legge nulla dal computer
        global CODICE_CONTEGGIO
        grezzo = self._stato.get("casuale")
        if not grezzo:
            grezzo = uuid.uuid4().hex
            self._stato["casuale"] = grezzo
            self._scrivi()
        # per contare le installazioni al controllo degli aggiornamenti (Privacy 4-ter): diverso dal codice
        # delle statistiche, così i due non si possono collegare
        CODICE_CONTEGGIO = hashlib.sha256(("tk-conta|" + grezzo).encode()).hexdigest()[:16]
        return hashlib.sha256(("tk-dispositivo|" + grezzo).encode()).hexdigest()[:32]

    @property
    def dominio(self):
        return "dev-" + self.dispositivo

    # -- rete
    def _chiama(self, metodo, percorso, dati=None):
        url = SERVER + percorso
        corpo = None
        if metodo == "GET" and dati:
            url += "?" + urllib.parse.urlencode(dati)
        elif dati is not None:
            corpo = json.dumps(dati).encode()
        req = urllib.request.Request(url, data=corpo, method=metodo, headers={
            "User-Agent": f"{self.slug}/{self.versione} ({piattaforma()})",
            "Content-Type": "application/json", "Cache-Control": "no-cache"})
        ctx = None
        try:
            import ssl
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
        except Exception:
            pass
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"success": False, "message": f"Errore del server ({e.code})."}

    # -- firma
    def _valida(self, chiave, dati):
        """Vero se la risposta è firmata dal server e riguarda questa chiave, questo prodotto, questo dispositivo."""
        if not isinstance(dati, dict) or not dati.get("firma") or not dati.get("emessa"):
            return False
        msg = "|".join([
            "tk-licenza-v1", chiave.upper(), str(dati.get("product_slug") or ""), str(dati.get("domain") or ""),
            str(dati.get("status") or ""), str(dati.get("plan") or ""), str(dati.get("expires_at") or ""),
            str(dati["emessa"]),
        ]).encode()
        try:
            firma = base64.b64decode(dati["firma"])
        except Exception:
            return False
        return (verifica_firma(base64.b64decode(CHIAVE_PUBBLICA), msg, firma)
                and dati.get("product_slug") == self.slug and dati.get("domain") == self.dominio)

    @staticmethod
    def _secondi(iso):
        try:
            return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return 0

    # -- stato
    def is_pro(self) -> bool:
        s = self._stato
        dati = s.get("risposta")
        chiave = s.get("chiave", "")
        if not chiave or not self._valida(chiave, dati):
            return False
        if dati.get("status") != "active" or dati.get("plan") not in ("pro", "agency"):
            return False
        scade = dati.get("expires_at")
        if scade:
            try:
                if datetime.strptime(scade, "%Y-%m-%d %H:%M:%S").timestamp() < time.time():
                    return False
            except Exception:
                return False
        return time.time() - self._secondi(dati["emessa"]) <= TOLLERANZA

    def free_pro(self) -> bool:
        """Sempre falso: software libero, nessuna funzione a pagamento (il programma non mostra il Pro)."""
        return False

    def sbloccato(self) -> bool:
        """Sempre vero: tutte le funzioni sono per tutti."""
        return True

    # -- statistiche (col consenso)
    def consenso_statistiche(self):
        """None = l'utente non ha ancora risposto; True/False = la sua scelta."""
        v = self.ricordo("statistiche")
        return v if isinstance(v, bool) else None

    def imposta_statistiche(self, si: bool):
        self.ricorda("statistiche", bool(si))

    def pro_gratis(self) -> bool:
        """Pietro ha acceso «Pro gratis per tutti» (firma v2 del server) e la data «fino al», se c'è, non è passata."""
        p = self._stato.get("prodotto") or {}
        if not p.get("pro_gratis") or not p.get("firma2") or not self._prodotto_valido_v2(p):
            return False
        fino = str(p.get("pro_gratis_fino") or "")
        return fino == "" or time.strftime("%Y-%m-%d") <= fino

    def pro_gratis_fino(self) -> str:
        """Data «fino al» del Pro gratis in forma gg/mm/aaaa, '' se senza data o non attivo."""
        if not self.pro_gratis():
            return ""
        fino = str((self._stato.get("prodotto") or {}).get("pro_gratis_fino") or "")
        try:
            return datetime.strptime(fino, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return ""

    def _prodotto_valido_v2(self, p):
        msg = "|".join(["tk-prodotto-v2", self.slug, "1" if p.get("free_pro") else "0",
                        "1" if p.get("pro_gratis") else "0", str(p.get("pro_gratis_fino") or ""),
                        str(p.get("emessa", ""))]).encode()
        try:
            return verifica_firma(base64.b64decode(CHIAVE_PUBBLICA), msg, base64.b64decode(p["firma2"]))
        except Exception:
            return False

    # -- piccola memoria del programma (es. quando è comparso l'invito al caffè), nello stesso file
    def ricordo(self, nome, predefinito=None):
        return (self._stato.get("ricordi") or {}).get(nome, predefinito)

    def ricorda(self, nome, valore):
        with self._blocco:
            self._stato.setdefault("ricordi", {})[nome] = valore
            self._scrivi()

    def _prodotto_valido(self, p):
        msg = f"tk-prodotto-v1|{self.slug}|{'1' if p.get('free_pro') else '0'}|{p.get('emessa', '')}".encode()
        try:
            return verifica_firma(base64.b64decode(CHIAVE_PUBBLICA), msg, base64.b64decode(p["firma"]))
        except Exception:
            return False

    def aggiorna_prodotto(self, forza=False):
        """Ogni 6 ore (all'avvio): interruttore Free/Pro, Pro gratis per tutti, pagina del Pro e link della donazione.
        forza=True (all'apertura di Informazioni): subito, così un Free/Pro appena acceso si vede senza aspettare."""
        p = self._stato.get("prodotto") or {}
        if not forza and time.time() - self._secondi(p.get("emessa", "")) < 6 * 3600:
            return
        try:
            r = self._chiama("GET", "/plugin-info/" + urllib.parse.quote(self.slug))
        except Exception:
            return
        if isinstance(r, dict) and r.get("success") and r.get("firma") and self._prodotto_valido(r):
            with self._blocco:
                self._stato["prodotto"] = {k: r.get(k) for k in ("free_pro", "pagina", "donazione", "emessa", "firma",
                                                                 "pro_gratis", "pro_gratis_fino", "firma2")}
                self._scrivi()

    def piano(self) -> str:
        return (self._stato.get("risposta") or {}).get("plan", "free") if self.is_pro() else "free"

    def info(self) -> dict:
        """Per la finestra Informazioni/Licenza."""
        dati = self._stato.get("risposta") or {}
        chiave = self._stato.get("chiave", "")
        prodotto = self._stato.get("prodotto") or {}
        return {
            "pro": self.is_pro(),
            "free_pro": self.free_pro(),
            "sbloccato": self.sbloccato(),
            "pro_gratis": self.pro_gratis(),
            "pro_gratis_fino": self.pro_gratis_fino(),
            "donazione": DONAZIONE,
            "dispositivo": self.dispositivo,
            "piano": self.piano(),
            "chiave": (chiave[:4] + "-••••-••••-" + chiave[-4:]) if len(chiave) >= 8 else "",
            "chiave_intera": chiave,  # per il campo «mostra» della finestra Pro (resta sul computer)
            "scadenza": dati.get("expires_at") or "",
            "controllata": dati.get("emessa", ""),
            "pagina_pro": prodotto.get("pagina") or dati.get("upgrade_url") or "https://pietrodefilippis.it/software/",
        }

    # -- azioni (fanno rete: chiamarle fuori dal thread della finestra)
    def attiva(self, chiave: str):
        chiave = chiave.strip().upper()
        if len(chiave) < 8:
            return False, "Scrivi la chiave di licenza."
        try:
            r = self._chiama("POST", "/activate/" + urllib.parse.quote(chiave),
                             {"domain": self.dominio, "product_slug": self.slug})
        except Exception:
            return False, "Nessuna connessione: riprova quando sei online."
        dati = (r or {}).get("data")
        if not (r or {}).get("success") or not self._valida(chiave, dati):
            return False, (r or {}).get("message") or "Chiave non valida per questo programma."
        with self._blocco:
            self._stato.update({"chiave": chiave, "risposta": dati})
            self._scrivi()
        if not self.is_pro():
            return False, "La chiave è attiva ma non è Pro."
        return True, "Pro attivato. Grazie!"

    def riscatta(self, codice: str):
        """Codice Pro (regalo/promozione): il server lo cambia in una chiave, che poi si attiva qui."""
        codice = "".join(c for c in codice.strip().upper() if c.isalnum() or c == "-")
        if len(codice) < 4:
            return False, "Scrivi il codice."
        try:
            r = self._chiama("POST", "/riscatta-codice", {"codice": codice, "slug": self.slug, "domain": self.dominio})
        except Exception:
            return False, "Nessuna connessione: riprova quando sei online."
        if not (r or {}).get("ok") or not (r or {}).get("chiave"):
            return False, (r or {}).get("message") or "Codice non valido."
        return self.attiva(r["chiave"])

    def attiva_o_codice(self, testo: str):
        """Il campo del passo 3 accetta sia la chiave (XXXX-XXXX-XXXX-XXXX) sia un codice Pro."""
        t = testo.strip().upper()
        parti = t.split("-")
        if len(parti) == 4 and all(len(p) == 4 and p.isalnum() for p in parti):
            ok, msg = self.attiva(t)
            if ok or "non trovata" not in msg.lower():
                return ok, msg
        return self.riscatta(t)

    @property
    def codice_donazione(self) -> str:
        """Codice da scrivere nella nota di PayPal: Pietro ritrova la donazione di questo computer.
        Es. tk-tv → TKTV-4F7Q2A (sempre lo stesso per lo stesso programma sullo stesso computer)."""
        nome = "".join(c for c in self.slug.upper() if c.isalnum())[:6]
        return f"{nome}-{self.dispositivo[:6].upper()}"

    def richiedi_pro(self, email: str, nome: str = "", nota: str = ""):
        """«Ho donato: mandami la chiave»: la richiesta arriva a Pietro, che manda la chiave per email."""
        email = email.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            return False, "Scrivi un indirizzo email valido."
        nota = (f"Codice donazione: {self.codice_donazione}. " + nota.strip()).strip()
        try:
            r = self._chiama("POST", "/richiesta-pro", {"slug": self.slug, "email": email, "nome": nome.strip(),
                                                         "device": self.dominio, "nota": nota})
        except Exception:
            return False, "Nessuna connessione: riprova quando sei online."
        return bool((r or {}).get("ok")), (r or {}).get("message") or "Richiesta non inviata."

    def disattiva(self):
        chiave = self._stato.get("chiave", "")
        if chiave:
            try:
                self._chiama("POST", "/deactivate/" + urllib.parse.quote(chiave), {"domain": self.dominio})
            except Exception:
                pass
        with self._blocco:
            self._stato.pop("chiave", None)
            self._stato.pop("risposta", None)
            self._scrivi()

    def ricontrolla(self, forza=False):
        chiave = self._stato.get("chiave", "")
        dati = self._stato.get("risposta") or {}
        if not chiave:
            return
        if not forza and time.time() - self._secondi(dati.get("emessa", "")) < RICONTROLLO:
            return
        try:
            r = self._chiama("GET", "/validate/" + urllib.parse.quote(chiave),
                             {"domain": self.dominio, "product_slug": self.slug})
        except Exception:
            return  # senza internet: vale la tolleranza
        nuovi = (r or {}).get("data")
        if (r or {}).get("success") and self._valida(chiave, nuovi):
            with self._blocco:
                self._stato["risposta"] = nuovi
                self._scrivi()
        elif isinstance(nuovi, dict) and nuovi.get("status") in ("invalid", "expired", "revoked", "inactive"):
            # il server dice che non vale più su questo dispositivo
            with self._blocco:
                self._stato.pop("risposta", None)
                self._scrivi()

    def segnale(self):
        """Una volta al giorno, SOLO col consenso: questo programma è in uso (conteggio delle installazioni)."""
        if self.consenso_statistiche() is not True:
            return
        oggi = time.strftime("%Y-%m-%d")
        if self._stato.get("segnale") == oggi:
            return
        try:
            r = self._chiama("POST", "/ping-app", {
                "slug": self.slug, "version": self.versione, "device": self.dispositivo,
                "platform": piattaforma(), "os": versione_sistema(), "plan": self.piano()})
        except Exception:
            return
        if (r or {}).get("ok"):
            with self._blocco:
                self._stato["segnale"] = oggi
                self._scrivi()

    def avvia(self):
        """All'avvio del programma: segnale del giorno (solo col consenso), in sottofondo. Nient'altro va in rete."""
        def lavoro():
            try:
                self.segnale()
            except Exception:
                pass
        threading.Thread(target=lavoro, name="tk-licenza", daemon=True).start()
