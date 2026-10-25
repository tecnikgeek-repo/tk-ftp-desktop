"""tk_licenza_qt — finestre comuni dei software TK (PySide6), gemella di tk_licenza.py.

Copia IDENTICA in ogni software TK accanto a tk_licenza.py (originale in Dropbox\\CLAUDE\\tk-software\\librerie).

Dal 2026-10-25 (software libero AGPL-3.0, niente Pro) si usano:
    benvenuto(lic, "tk-pdf", url_sorgente, parent=win, logo=pixmap)   # all'avvio: la prima volta sola
    LicenzeDialog("tk-pdf", VERSION, url_sorgente, cartella_licenze, parent=win).exec()   # da Informazioni
    casella_statistiche(lic)        # QCheckBox per le Impostazioni
    pulsante_caffe(lic), invito_caffe(lic, "tk-pdf", win)   # donazione libera
ProDialog e chiedi_pro restano solo per il codice vecchio (chiedi_pro risponde sempre sì).

Uso vecchio:

    from tkpdf.tk_licenza_qt import ProDialog, chiedi_pro
    ProDialog(lic, "tk-pdf", FUNZIONI_PRO, accento="#e11d48", parent=win,
              funzioni_free=FUNZIONI_FREE, font_icone=icon_font(22), logo=pixmap).exec()
    if not chiedi_pro(lic, "Modifica testo", "tk-pdf", FUNZIONI_PRO, parent=win): return

FUNZIONI_PRO: elenco di voci, ognuna può essere
    "testo"                         (vecchio formato: titolo solo)
    ("Titolo", "spiegazione")
    ("glifo", "Titolo", "spiegazione")   glifo = carattere del font_icone del programma
FUNZIONI_FREE: frasi brevi di cosa resta gratis (facoltativo).

Finestra per chi non ha il Pro: testata colorata, griglia «Cosa ottieni», riga «Resta gratis»,
tre passi in fila: 1) donazione libera 2) «Ho donato: mandami la chiave» 3) incolla la chiave e attiva.
"""
import threading
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

NAVY = "#0f172a"
NAVY_2 = "#1e293b"
NAVY_3 = "#334155"
GRIGIO = "#94a3b8"
CHIARO = "#cbd5e1"
VERDE = "#22c55e"
# colori uguali in TUTTI i software TK (Pietro: «sempre uguale per tutti i software come il tasto dona»):
# Pro = blu della pastiglia PRO dei pannelli TK, caffè = ambra
PRO_BLU = "#3b82f6"
PRO_BLU_SCURO = "#2563eb"
CAFFE = "#f59e0b"
CAFFE_CHIARO = "#fbbf24"


class _Ponte(QObject):
    fatto = Signal(object, bool, str)   # funzione da chiamare, esito, messaggio


def _in_sottofondo(funzione, al_termine):
    """Esegue funzione() fuori dalla finestra e poi al_termine(ok, msg) nella finestra."""
    ponte = _Ponte()
    ponte.fatto.connect(lambda f, ok, msg: f(ok, msg))

    def lavoro():
        try:
            ok, msg = funzione()
        except Exception as e:  # mai bloccare il programma per la licenza
            ok, msg = False, f"Errore: {e}"
        ponte.fatto.emit(al_termine, ok, msg)

    threading.Thread(target=lavoro, daemon=True).start()
    return ponte  # va tenuto vivo finché non risponde


def _voce(f):
    """Normalizza una voce di FUNZIONI_PRO in (glifo, titolo, spiegazione)."""
    if isinstance(f, (tuple, list)):
        if len(f) >= 3:
            return f[0], f[1], f[2]
        if len(f) == 2:
            return "", f[0], f[1]
        return "", f[0], ""
    return "", str(f), ""


def _rgba(colore, alfa):
    c = QColor(colore)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alfa})"


def _scuro(colore, fattore=135):
    return QColor(colore).darker(fattore).name()


def centra(dlg):
    """Mette la finestra al centro: sopra la finestra principale se è visibile e sullo schermo, altrimenti al
    centro dello schermo (all'avvio la principale può non avere ancora una posizione vera)."""
    try:
        if not dlg.testAttribute(Qt.WidgetAttribute.WA_Resized):
            dlg.adjustSize()   # solo se la finestra non ha già una misura sua (resize): non va rimpicciolita
        padre = dlg.parentWidget().window() if dlg.parentWidget() is not None else None
        schermo = None
        if padre is not None and padre.isVisible():
            schermo = padre.screen()
        schermo = schermo or QGuiApplication.screenAt(dlg.cursor().pos()) or QGuiApplication.primaryScreen()
        area = schermo.availableGeometry()
        rif = padre.frameGeometry() if padre is not None and padre.isVisible() and area.intersects(padre.frameGeometry()) else area
        g = dlg.frameGeometry()
        g.moveCenter(rif.center())
        # mai fuori dallo schermo
        x = min(max(g.left(), area.left()), area.right() - g.width())
        y = min(max(g.top(), area.top()), area.bottom() - g.height())
        dlg.move(max(x, area.left()), max(y, area.top()))
    except Exception:
        pass


_SPUNTA = {}


def _spunta_png():
    """Segno di spunta bianco (PNG in una cartella temporanea) per le caselle su fondo scuro: lo stile Qt
    vuole un file per l'immagine dell'indicatore."""
    if "p" in _SPUNTA and __import__("os").path.exists(_SPUNTA["p"]):
        return _SPUNTA["p"]
    import os
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainter, QPen, QPixmap
    pm = QPixmap(40, 40)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(9, 21), QPointF(17, 29), QPointF(31, 12)])
    p.end()
    path = os.path.join(tempfile.gettempdir(), "tk-spunta-bianca.png")
    pm.save(path)
    _SPUNTA["p"] = path
    return path


def _indicatore(selettore):
    """Quadrato della casella: bianco con bordo grigio (si vede su fondo scuro e chiaro), blu con la spunta
    bianca quando è attiva, grigio chiaro quando è disattivata."""
    img = _spunta_png().replace("\\", "/")
    return (f"{selettore}::indicator {{ width:20px; height:20px; border-radius:6px; border:2px solid {GRIGIO};"
            " background:#ffffff; }"
            f"{selettore}::indicator:hover {{ border-color:{PRO_BLU}; }}"
            f"{selettore}::indicator:checked {{ background:{PRO_BLU}; border-color:{PRO_BLU}; image:url({img}); }}"
            f"{selettore}::indicator:checked:hover {{ background:{PRO_BLU_SCURO}; border-color:{PRO_BLU_SCURO}; }}"
            f"{selettore}::indicator:disabled {{ background:#e2e8f0; border-color:#cbd5e1; }}")


def stile_casella(selettore="QCheckBox"):
    """Casella su fondo scuro (testo bianco), con il quadrato comune di _indicatore()."""
    return f"{selettore} {{ color:#ffffff; font-size:13px; spacing:10px; }}" + _indicatore(selettore)


def stile_caselle_globale(*altri_selettori):
    """Da aggiungere IN FONDO al foglio di stile dell'applicazione: TUTTE le caselle del programma con lo stesso
    quadrato ben visibile (il colore del testo resta quello del programma). `altri_selettori` = regole più
    specifiche del programma da riallineare (es. "QFrame#tkcard QCheckBox")."""
    return "QCheckBox { spacing:10px; }" + "".join(_indicatore(s) for s in ("QCheckBox",) + altri_selettori)


class _Centrata:
    """Da mettere prima di QDialog: la finestra si centra appena compare."""

    def showEvent(self, ev):
        super().showEvent(ev)
        if not getattr(self, "_tk_centrata", False):
            self._tk_centrata = True
            centra(self)
            QTimer.singleShot(0, lambda: centra(self))   # dopo che il gestore delle finestre l'ha piazzata


class ProDialog(QDialog):
    def __init__(self, lic, nome_app, funzioni_pro, accento="#e11d48", parent=None,
                 funzioni_free=None, font_icone=None, logo=None):
        super().__init__(parent)
        self.lic = lic
        self.nome_app = nome_app
        self.funzioni = [_voce(f) for f in funzioni_pro]
        self.funzioni_free = list(funzioni_free or [])
        self.font_icone = font_icone
        self.logo = logo
        # il Pro ha lo stesso colore in tutti i programmi: `accento` resta per compatibilità ma non si usa
        accento = PRO_BLU
        self.accento = accento
        self._ponti = []
        self.setWindowTitle(f"{nome_app} Pro")
        a, a_scuro = accento, _scuro(accento)
        self.setStyleSheet(
            f"QDialog {{ background: {NAVY}; }}"
            "QLabel { color: #ffffff; background: transparent; }"
            f"#tkHero {{ border-radius: 18px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {a}, stop:0.55 {a_scuro}, stop:1 {NAVY_2}); }}"
            f"#tkHeroOk {{ border-radius: 18px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 #16a34a, stop:0.6 #166534, stop:1 {NAVY_2}); }}"
            "#tkHeroTitolo { font-size: 26px; font-weight: 800; }"
            "#tkHeroSotto { color: rgba(255,255,255,0.86); font-size: 14px; }"
            "#tkLogo { background: #ffffff; border-radius: 18px; }"
            "#tkPill { background: rgba(255,255,255,0.18); border-radius: 11px; padding: 4px 12px;"
            " font-size: 12px; font-weight: 700; }"
            f"#tkSezione {{ color: {GRIGIO}; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; }}"
            f"#tkCard {{ background: {NAVY_2}; border-radius: 14px; }}"
            f"#tkCardPasso {{ background: {NAVY_2}; border-radius: 16px; border: 1px solid {NAVY_3}; }}"
            f"#tkTile {{ background: {_rgba(a, 0.18)}; border-radius: 12px; color: {a}; }}"
            f"#tkTileOk {{ background: {_rgba(VERDE, 0.18)}; border-radius: 12px; color: {VERDE}; }}"
            "#tkVoceTitolo { font-size: 14px; font-weight: 700; }"
            f"#tkVoceTesto {{ color: {GRIGIO}; font-size: 12px; }}"
            f"#tkNumero {{ background: {a}; border-radius: 15px; font-size: 14px; font-weight: 800; }}"
            "#tkPassoTitolo { font-size: 15px; font-weight: 800; }"
            f"#tkTesto {{ color: {CHIARO}; font-size: 12.5px; }}"
            f"#tkFree {{ background: {_rgba(VERDE, 0.10)}; border: 1px solid {_rgba(VERDE, 0.35)}; border-radius: 12px; }}"
            f"#tkFreeTesto {{ color: {CHIARO}; font-size: 12.5px; }}"
            "#tkValore { color: #ffffff; font-size: 13px; font-weight: 700; }"
            f"#tkCodice {{ background: {NAVY}; border: 1px dashed {a}; border-radius: 10px; padding: 7px 12px;"
            " font-family: Consolas, Menlo, monospace; font-size: 15px; font-weight: 800; letter-spacing: 1px; }"
            "#tkMsg { font-size: 12px; font-weight: 600; }"
            # pastiglie come nei pannelli TK: verde = stato, blu = piano, navy = durata
            "#tkPillOk { background: #16a34a; color: #fff; border-radius: 9px; padding: 3px 10px; font-size: 11px; font-weight: 800; }"
            f"#tkPillPro {{ background: {PRO_BLU}; color: #fff; border-radius: 9px; padding: 3px 10px; font-size: 11px; font-weight: 800; }}"
            f"#tkPillDurata {{ background: {NAVY_3}; color: #fff; border-radius: 9px; padding: 3px 10px; font-size: 11px; font-weight: 800; }}"
            "QPushButton#tkRosso { background: transparent; color: #fca5a5; border: 1px solid rgba(248,113,113,0.5);"
            " border-radius: 10px; padding: 10px 16px; font-size: 13px; font-weight: 700; }"
            "QPushButton#tkRosso:hover { background: rgba(248,113,113,0.12); }"
            f"QLineEdit {{ background: {NAVY}; color: white; border: 1px solid {NAVY_3}; border-radius: 10px;"
            " padding: 8px 12px; font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {a}; }}"
            f"QPushButton#tkChiaro {{ background: {NAVY_3}; color: white; border: 0; border-radius: 10px;"
            " padding: 10px 18px; font-size: 13px; font-weight: 700; }"
            "QPushButton#tkChiaro:hover { background: #3f5168; }"
            f"QPushButton#tkAccento {{ background: {a}; color: white; border: 0; border-radius: 11px;"
            " padding: 11px 16px; font-size: 13px; font-weight: 800; }"
            f"QPushButton#tkAccento:hover {{ background: {a_scuro}; }}"
            "QPushButton#tkLink { background: transparent; color: #cbd5e1; border: 0; padding: 6px 4px;"
            " font-size: 12px; font-weight: 600; text-decoration: underline; }"
            "QPushButton:disabled { background: #475569; color: #94a3b8; }"
            # scorrimento: sugli schermi bassi (MacBook) la finestra non deve uscire dallo schermo
            "QScrollArea, #tkContenuto { background: transparent; border: 0; }"
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }"
            f"QScrollBar::handle:vertical {{ background: {NAVY_3}; border-radius: 4px; min-height: 40px; }}"
            "QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }"
            f"QScrollBar::handle:horizontal {{ background: {NAVY_3}; border-radius: 4px; min-width: 40px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
        )
        esterno = QVBoxLayout(self)
        esterno.setContentsMargins(0, 0, 0, 0)
        self._scorri = QScrollArea()
        self._scorri.setWidgetResizable(True)
        self._scorri.setFrameShape(QFrame.Shape.NoFrame)
        self._scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # solo su schermi molto stretti
        self._contenuto = QWidget()
        self._contenuto.setObjectName("tkContenuto")
        self._scorri.setWidget(self._contenuto)
        self._scorri.viewport().setAutoFillBackground(False)
        esterno.addWidget(self._scorri)
        self.lay = QVBoxLayout(self._contenuto)
        self.lay.setContentsMargins(20, 20, 20, 18)
        self.lay.setSpacing(16)
        self._disegna()

    # ------------------------------------------------------------ pezzi
    def _box(self, nome, verticale=True, margini=(18, 16, 18, 16), spazio=8):
        w = QWidget()
        w.setObjectName(nome)
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        l = QVBoxLayout(w) if verticale else QHBoxLayout(w)
        l.setContentsMargins(*margini)
        l.setSpacing(spazio)
        return w, l

    @staticmethod
    def _testo(s, nome="tkTesto", a_capo=True):
        l = QLabel(s)
        l.setObjectName(nome)
        l.setWordWrap(a_capo)
        return l

    def _pulsante(self, testo, stile="tkChiaro"):
        b = QPushButton(testo)
        b.setObjectName(stile)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(40)
        return b

    def _sezione(self, testo):
        return self._testo(testo.upper(), "tkSezione", False)

    def _tile(self, glifo, ok=False):
        t = QLabel()
        t.setObjectName("tkTileOk" if ok else "tkTile")
        t.setFixedSize(42, 42)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if glifo and self.font_icone is not None and not ok:
            t.setFont(self.font_icone)
            t.setText(glifo)
        else:
            f = QFont(t.font())
            f.setPixelSize(20)
            f.setBold(True)
            t.setFont(f)
            t.setText("✓" if ok or not glifo else glifo)
        return t

    def _svuota(self, layout=None):
        layout = layout or self.lay
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._svuota(it.layout())

    def _hero(self, titolo, sotto, pills, ok=False):
        hero, h = self._box("tkHeroOk" if ok else "tkHero", False, (24, 22, 24, 22), 18)
        if self.logo is not None and not self.logo.isNull():
            ic = QLabel()
            ic.setObjectName("tkLogo")
            dpr = self.logo.devicePixelRatio() or 1
            pm = self.logo.scaled(int(52 * dpr), int(52 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            ic.setPixmap(pm)
            ic.setFixedSize(76, 76)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(self._testo(titolo, "tkHeroTitolo", False))
        col.addWidget(self._testo(sotto, "tkHeroSotto"))
        if pills:
            riga = QHBoxLayout()
            riga.setSpacing(8)
            for p in pills:
                riga.addWidget(self._testo(p, "tkPill", False))
            riga.addStretch(1)
            col.addSpacing(4)
            col.addLayout(riga)
        h.addLayout(col, 1)
        return hero

    def _griglia_funzioni(self, sbloccate=False):
        griglia = QGridLayout()
        griglia.setHorizontalSpacing(12)
        griglia.setVerticalSpacing(12)
        colonne = 2 if len(self.funzioni) > 1 else 1
        for i, (glifo, titolo, spiega) in enumerate(self.funzioni):
            card, l = self._box("tkCard", False, (14, 14, 16, 14), 14)
            card.setMinimumHeight(84)  # due righe di spiegazione: senza, Qt taglia il testo che va a capo
            l.addWidget(self._tile(glifo, sbloccate), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(self._testo(titolo, "tkVoceTitolo"))
            if spiega:
                col.addWidget(self._testo(spiega, "tkVoceTesto"))
            col.addStretch(1)
            l.addLayout(col, 1)
            ultima_sola = colonne == 2 and i == len(self.funzioni) - 1 and i % 2 == 0
            griglia.addWidget(card, i // colonne, i % colonne, 1, 2 if ultima_sola else 1)
        for c in range(colonne):
            griglia.setColumnStretch(c, 1)
        return griglia

    # ------------------------------------------------------------ finestra
    def _disegna(self):
        self._disegna_contenuto()
        self._adatta()

    def _schermo(self):
        s = self.screen() if self.isVisible() else None
        if s is None and self.parent() is not None:
            s = self.parent().screen()
        return (s or QGuiApplication.primaryScreen()).availableGeometry()

    def _adatta(self):
        """Grande quanto il contenuto, ma mai più dello schermo: oltre, scorre."""
        geo = self._schermo()
        self._contenuto.adjustSize()
        voluto = self._contenuto.sizeHint()
        barra = self._scorri.verticalScrollBar().sizeHint().width()
        w = min(max(self.minimumWidth(), min(voluto.width() + barra, 800)), int(geo.width() * 0.95))  # compatta: al massimo 800 px
        h = min(voluto.height() + 2, int(geo.height() * 0.80))  # più bassa dello schermo, anche sul MacBook
        self.resize(w, h)
        if self.isVisible():
            # se è cresciuta (es. dopo l'attivazione) la riporto dentro lo schermo
            x = min(max(self.x(), geo.left()), geo.right() - w)
            y = min(max(self.y(), geo.top()), geo.bottom() - h)
            self.move(x, y)

    def _disegna_contenuto(self):
        self._svuota()
        info = self.lic.info()
        # larghezza minima ridotta sugli schermi piccoli
        self.setMinimumWidth(min(780 if not info["pro"] else 600, int(self._schermo().width() * 0.95)))

        if info["pro"]:
            self.lay.addWidget(self._hero(f"{self.nome_app} Pro è attivo",
                                          "Grazie per il tuo contributo: tutte le funzioni sono sbloccate su questo computer.",
                                          ["PRO", info["piano"].upper() if info["piano"] not in ("", "free", "pro") else "Attivo"],
                                          ok=True))
            if self.funzioni:
                self.lay.addWidget(self._sezione("Funzioni sbloccate"))
                self.lay.addLayout(self._griglia_funzioni(sbloccate=True))
            # riquadro della licenza come nei plugin TK: titolo + «Attiva», chiave nascosta con Mostra, Disattiva
            card, v = self._box("tkCard", True, (18, 16, 18, 18), 12)
            testa = QHBoxLayout()
            testa.addWidget(self._testo("Licenza", "tkPassoTitolo", False))
            testa.addWidget(self._testo("ATTIVA", "tkPillOk", False))
            testa.addStretch(1)
            piano = (info.get("piano") or "pro").upper()
            testa.addWidget(self._testo(piano, "tkPillPro", False))
            if info["scadenza"]:
                try:
                    from datetime import datetime
                    fino = datetime.strptime(info["scadenza"][:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    fino = info["scadenza"][:10]
                testa.addWidget(self._testo(f"FINO AL {fino}", "tkPillDurata", False))
            else:
                testa.addWidget(self._testo("LIFETIME", "tkPillDurata", False))
            v.addLayout(testa)
            riga = QHBoxLayout()
            riga.setSpacing(8)
            campo = QLineEdit(info.get("chiave_intera") or info["chiave"])
            campo.setReadOnly(True)
            campo.setEchoMode(QLineEdit.EchoMode.Password)
            campo.setMinimumHeight(40)
            riga.addWidget(campo, 1)
            mostra = self._pulsante("Mostra")

            def _mostra():
                nascosta = campo.echoMode() == QLineEdit.EchoMode.Password
                campo.setEchoMode(QLineEdit.EchoMode.Normal if nascosta else QLineEdit.EchoMode.Password)
                mostra.setText("Nascondi" if nascosta else "Mostra")
            mostra.clicked.connect(_mostra)
            riga.addWidget(mostra)
            togli = self._pulsante("Disattiva", "tkRosso")
            togli.setToolTip("Libera la chiave per usarla su un altro computer")
            togli.clicked.connect(self._disattiva)
            riga.addWidget(togli)
            v.addLayout(riga)
            v.addWidget(self._testo("La chiave vale su questo computer. Per spostarla premi Disattiva, poi attivala sull'altro.",
                                    "tkVoceTesto"))
            self.lay.addWidget(card)
            piede = QHBoxLayout()
            piede.addStretch(1)
            chiudi = self._pulsante("Chiudi")
            chiudi.clicked.connect(self.accept)
            piede.addWidget(chiudi)
            self.lay.addLayout(piede)
            return

        # ---- Pro gratis per tutti (promozione di Pietro): si vede sopra a tutto
        if info.get("pro_gratis"):
            fino = info.get("pro_gratis_fino") or ""
            box, l = self._box("tkFree", False, (16, 12, 16, 12), 10)
            ok = QLabel("✓")
            ok.setStyleSheet(f"color: {VERDE}; font-size: 18px; font-weight: 800;")
            l.addWidget(ok, 0, Qt.AlignmentFlag.AlignTop)
            l.addWidget(self._testo(
                "<b style='color:#ffffff'>In questo momento il Pro è gratis per tutti"
                + (f" fino al {fino}" if fino else "") + ".</b> Usalo pure: se ti piace, "
                "una donazione lo rende tuo anche dopo.", "tkFreeTesto"), 1)
            self.lay.addWidget(box)

        # ---- testata
        self.lay.addWidget(self._hero(
            f"Sblocca {self.nome_app} Pro",
            f"{len(self.funzioni)} funzioni in più per usare {self.nome_app} al meglio. "
            "Il prezzo lo decidi tu: è una donazione, anche piccola.",
            ["Donazione libera", "Chiave via email", "Pro: 1 computer · Agency: 5"]))

        # ---- cosa ottieni
        if self.funzioni:
            self.lay.addWidget(self._sezione("Cosa ottieni con il Pro"))
            self.lay.addLayout(self._griglia_funzioni())
        if self.funzioni_free:
            box, l = self._box("tkFree", False, (16, 10, 16, 10), 10)
            ok = QLabel("✓")
            ok.setStyleSheet(f"color: {VERDE}; font-size: 16px; font-weight: 800;")
            l.addWidget(ok, 0, Qt.AlignmentFlag.AlignTop)
            l.addWidget(self._testo("<b style='color:#ffffff'>Resta gratis per sempre:</b> "
                                    + " · ".join(self.funzioni_free), "tkFreeTesto"), 1)
            self.lay.addWidget(box)

        # ---- come si sblocca: tre passi in fila
        self.lay.addWidget(self._sezione("Come si sblocca · 3 passi"))
        passi = QHBoxLayout()
        passi.setSpacing(12)

        def passo(n, titolo, testo):
            card, v = self._box("tkCardPasso", True, (16, 16, 16, 16), 10)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            testa = QHBoxLayout()
            testa.setSpacing(10)
            num = QLabel(str(n))
            num.setObjectName("tkNumero")
            num.setFixedSize(30, 30)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            testa.addWidget(num)
            testa.addWidget(self._testo(titolo, "tkPassoTitolo", False), 1)
            v.addLayout(testa)
            v.addWidget(self._testo(testo))
            passi.addWidget(card, 1)
            return v

        v = passo(1, "Fai una donazione", "Con PayPal, della cifra che vuoi. È il tuo contributo allo sviluppo "
                                          f"di {self.nome_app}.")
        codice = getattr(self.lic, "codice_donazione", "")
        if codice:
            v.addWidget(self._testo("Nella nota di PayPal scrivi questo codice: così so che sei tu.", "tkVoceTesto"))
            riga = QHBoxLayout()
            riga.setSpacing(8)
            cod = self._testo(codice, "tkCodice", False)
            cod.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            riga.addWidget(cod, 1)
            copia = self._pulsante("Copia")
            copia.setMinimumHeight(36)

            def _copia():
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(codice)
                copia.setText("Copiato ✓")
            copia.clicked.connect(_copia)
            riga.addWidget(copia)
            v.addLayout(riga)
        v.addStretch(1)
        dona = self._pulsante("Dona con PayPal", "tkAccento")
        dona.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info["donazione"])))
        v.addWidget(dona)

        v = passo(2, "Ricevi la chiave", "L'email del tuo conto PayPal: la chiave arriva lì.")
        self.email = QLineEdit()
        self.email.setPlaceholderText("Email del conto PayPal")
        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Nome (facoltativo)")
        v.addWidget(self.email)
        v.addWidget(self.nome)
        v.addStretch(1)
        self.invia = self._pulsante("Ho donato: mandami la chiave")
        self.invia.clicked.connect(self._richiedi)
        v.addWidget(self.invia)
        self.msg_rich = self._testo("", "tkMsg")
        self.msg_rich.hide()
        v.addWidget(self.msg_rich)

        v = passo(3, "Attiva il Pro", "Incolla la chiave che ti arriva per email, oppure scrivi un codice Pro.")
        self.chiave = QLineEdit()
        self.chiave.setPlaceholderText("Chiave o codice Pro")
        v.addWidget(self.chiave)
        v.addStretch(1)
        self.attiva_btn = self._pulsante("Attiva il Pro", "tkAccento")
        self.attiva_btn.clicked.connect(self._attiva)
        v.addWidget(self.attiva_btn)
        self.msg_att = self._testo("", "tkMsg")
        self.msg_att.hide()
        v.addWidget(self.msg_att)
        self.lay.addLayout(passi)
        for campo in (self.email, self.nome, self.chiave):
            campo.setMinimumHeight(38)

        piede = QHBoxLayout()
        piede.addWidget(self._testo("Hai già una chiave o un codice Pro? Vai direttamente al passo 3.", "tkVoceTesto", False))
        piede.addStretch(1)
        chiudi = self._pulsante("Chiudi")
        chiudi.clicked.connect(self.accept)
        piede.addWidget(chiudi)
        self.lay.addLayout(piede)

    @staticmethod
    def _esito(label, ok, msg):
        label.setStyleSheet(f"color: {'#4ade80' if ok else '#fca5a5'};")
        label.setText(msg)
        label.setVisible(bool(msg))

    def _richiedi(self):
        self.invia.setEnabled(False)
        self.invia.setText("Invio…")
        email, nome = self.email.text(), self.nome.text()

        def fine(ok, msg):
            self.invia.setEnabled(True)
            self.invia.setText("Ho donato: mandami la chiave")
            self._esito(self.msg_rich, ok, msg)

        self._ponti.append(_in_sottofondo(lambda: self.lic.richiedi_pro(email, nome), fine))

    def _attiva(self):
        self.attiva_btn.setEnabled(False)
        self.attiva_btn.setText("Attivo…")
        chiave = self.chiave.text()

        def fine(ok, msg):
            if ok:
                self._disegna()
                return
            self.attiva_btn.setEnabled(True)
            self.attiva_btn.setText("Attiva il Pro")
            self._esito(self.msg_att, ok, msg)

        self._ponti.append(_in_sottofondo(lambda: self.lic.attiva_o_codice(chiave), fine))

    def _disattiva(self):
        if QMessageBox.question(self, self.nome_app, "Disattivare il Pro su questo computer?\n"
                                "La chiave si libera e puoi attivarla su un altro.") != QMessageBox.StandardButton.Yes:
            return
        self._ponti.append(_in_sottofondo(lambda: (self.lic.disattiva(), (True, ""))[1], lambda ok, msg: self._disegna()))


def dentro_lo_schermo(win, larghezza=None, altezza=None):
    """Misura e posizione della finestra principale sempre dentro lo schermo (MacBook e portatili piccoli).
    Da chiamare al posto di resize() e dopo restoreGeometry(): una misura salvata su uno schermo più grande
    non deve far uscire la finestra (bordi irraggiungibili, pulsanti tagliati)."""
    from PySide6.QtCore import QRect
    schermo = win.screen() or QGuiApplication.primaryScreen()
    geo = schermo.availableGeometry()
    w = min(larghezza or win.width(), int(geo.width() * 0.94))
    h = min(altezza or win.height(), int(geo.height() * 0.92))
    win.resize(max(w, win.minimumWidth()), max(h, win.minimumHeight()))
    if not geo.contains(QRect(win.pos(), win.size())):
        win.move(geo.left() + max(0, (geo.width() - win.width()) // 2),
                 geo.top() + max(0, (geo.height() - win.height()) // 2))


class _TestataCompatta(QObject):
    def __init__(self, win, voci, soglia):
        super().__init__(win)
        self.win, self.soglia, self.compatta = win, soglia, None
        self.voci = [(b, b.text(), corto) for b, corto in voci]
        for b, pieno, _ in self.voci:
            if not b.toolTip():
                b.setToolTip(pieno.strip())
        win.installEventFilter(self)
        geo = (win.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        self.aggiorna(min(win.width(), int(geo.width() * 0.94)))

    def aggiorna(self, larghezza=None):
        c = (larghezza or self.win.width()) < self.soglia
        if c == self.compatta:
            return
        self.compatta = c
        for b, pieno, corto in self.voci:
            b.setText(corto if c else pieno)

    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() == QEvent.Type.Resize:
            self.aggiorna()
        return False


def testata_compatta(win, voci, soglia):
    """Sotto `soglia` px di larghezza i pulsanti della testata perdono il testo (resta l'icona, il testo va nel
    suggerimento): così la finestra si stringe anche su un MacBook. `voci` = [(pulsante, testo corto)], di solito
    «» per i pulsanti con l'icona. `soglia` va scelta più larga del minimo della finestra col testo intero.
    Da chiamare dopo aver costruito la testata e prima di dentro_lo_schermo()."""
    win._tk_testata_compatta = _TestataCompatta(win, voci, soglia)
    return win._tk_testata_compatta


def ha_donato(lic) -> bool:
    """Vero se su questo computer c'è una chiave Pro attiva (anche con l'interruttore Free/Pro spento)."""
    try:
        return lic is not None and lic.is_pro()
    except Exception:
        return False


def pulsante_caffe(lic, testo="Offrimi un caffè", nome_oggetto=""):
    """Pulsante ambra «Offrimi un caffè» (come la card dei plugin TK), sempre visibile nelle Impostazioni.
    `nome_oggetto` = lo stesso objectName dei pulsanti vicini (es. "ghost", "tkChiaro"): così prende
    altezza, margini e arrotondamento del programma e cambia solo i colori.
    None a chi ha una chiave Pro attiva: ha già donato, non gli si chiede il caffè (Pietro, 24/10)."""
    if ha_donato(lic):
        return None
    try:
        url = lic.info()["donazione"] if lic is not None else "https://pietrodefilippis.it/donazione/"
    except Exception:
        url = "https://pietrodefilippis.it/donazione/"
    b = _pulsante_colorato(testo, nome_oggetto, CAFFE, CAFFE_CHIARO, "#1f2937")
    b.setToolTip("Un contributo libero per lo sviluppo, quando vuoi")
    b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return b


def pulsante_pro(testo, al_clic, nome_oggetto=""):
    """Pulsante «Sblocca … Pro» / «… Pro attivo»: blu Pro, uguale in tutti i programmi.
    `nome_oggetto` come per pulsante_caffe: misura e forma del programma, colore del Pro."""
    b = _pulsante_colorato(testo, nome_oggetto, PRO_BLU, PRO_BLU_SCURO, "#ffffff")
    b.clicked.connect(al_clic)
    return b


def _pulsante_colorato(testo, nome_oggetto, fondo, fondo_hover, testo_colore):
    b = QPushButton(testo)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if nome_oggetto:
        # solo i colori: misura e forma restano quelle dei pulsanti del programma
        b.setObjectName(nome_oggetto)
        b.setStyleSheet(f"QPushButton {{ background: {fondo}; color: {testo_colore}; border: 0; font-weight: 800; }}"
                        f"QPushButton:hover {{ background: {fondo_hover}; }}")
    else:
        b.setStyleSheet(f"QPushButton {{ background: {fondo}; color: {testo_colore}; border: 0; border-radius: 10px;"
                        " padding: 10px 16px; font-size: 13px; font-weight: 800; }"
                        f"QPushButton:hover {{ background: {fondo_hover}; }}")
    return b


CAFFE_PRIMA = 8000              # ms dopo l'apertura del programma
CAFFE_OGNI = 30 * 86400         # non più di una volta al mese…
CAFFE_AVVII = 10                # …e solo dopo almeno 10 avvii dall'ultima volta
CAFFE_DOPO_DONO = 90 * 86400    # chi ha premuto «Offrimi un caffè» non lo rivede per 3 mesi


class CaffeDialog(_Centrata, QDialog):
    """Invito al caffè: piccolo, una riga, due pulsanti e «Non mostrarlo più»."""

    def __init__(self, lic, nome_app, parent=None, logo=None):
        super().__init__(parent)
        self.lic = lic
        self.setWindowTitle(nome_app)
        self.setFixedWidth(440)
        self.setStyleSheet(
            f"QDialog {{ background: {NAVY}; }} QLabel {{ color: #ffffff; background: transparent; }}"
            "#tkTazza { background: rgba(245,158,11,0.16); border-radius: 16px; color: #f59e0b; font-size: 26px; font-weight: 800; }"
            "#tkTit { font-size: 18px; font-weight: 800; }"
            f"#tkTesto {{ color: {CHIARO}; font-size: 13px; }}"
            f"QPushButton#tkChiaro {{ background: {NAVY_3}; color: white; border: 0; border-radius: 10px;"
            " padding: 10px 16px; font-size: 13px; font-weight: 700; }"
            "QPushButton#tkLink { background: transparent; color: #94a3b8; border: 0; font-size: 12px; text-decoration: underline; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 16)
        lay.setSpacing(14)
        testa = QHBoxLayout()
        testa.setSpacing(14)
        ic = QLabel()
        ic.setObjectName("tkTazza")
        ic.setFixedSize(56, 56)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if logo is not None and not logo.isNull():
            dpr = logo.devicePixelRatio() or 1
            pm = logo.scaled(int(40 * dpr), int(40 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            ic.setPixmap(pm)
        else:
            ic.setText("♥")
        testa.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        tit = QLabel(f"Ti piace {nome_app}?")
        tit.setObjectName("tkTit")
        col.addWidget(tit)
        t = QLabel(f"{nome_app} è gratis. Se ti è utile, offrimi un caffè: mi aiuta a migliorarlo e a crearne altri.")
        t.setObjectName("tkTesto")
        t.setWordWrap(True)
        col.addWidget(t)
        testa.addLayout(col, 1)
        lay.addLayout(testa)
        riga = QHBoxLayout()
        riga.setSpacing(8)
        mai = QPushButton("Non mostrarlo più")
        mai.setObjectName("tkLink")
        mai.setCursor(Qt.CursorShape.PointingHandCursor)
        mai.clicked.connect(self._mai)
        riga.addWidget(mai)
        riga.addStretch(1)
        dopo = QPushButton("Più tardi")
        dopo.setObjectName("tkChiaro")
        dopo.setCursor(Qt.CursorShape.PointingHandCursor)
        dopo.clicked.connect(self.reject)
        riga.addWidget(dopo)
        caffe = pulsante_caffe(lic, nome_oggetto="tkChiaro")
        if caffe is not None:
            caffe.clicked.connect(self._offerto)
            riga.addWidget(caffe)
        lay.addLayout(riga)

    def _offerto(self):
        self.lic.ricorda("caffe_offerto", time.time())
        self.accept()

    def _mai(self):
        self.lic.ricorda("caffe_mai", True)
        self.reject()


def invito_caffe(lic, nome_app, parent=None, logo=None, puo_mostrare=None):
    """Da chiamare una volta all'avvio, dopo aver aperto la finestra. Mostra l'invito al caffè al primo
    avvio e poi al massimo una volta al mese (dopo almeno 10 avvii), mai a chi ha il Pro con una chiave,
    mai dopo «Non mostrarlo più». `puo_mostrare()` falso (es. un video in corso) = si riprova tra un minuto."""
    if lic is None:
        return
    try:
        avvii = int(lic.ricordo("caffe_avvii", 0) or 0) + 1
        lic.ricorda("caffe_avvii", avvii)
        if lic.ricordo("caffe_mai", False) or ha_donato(lic):
            return
        ora = time.time()
        ultimo = float(lic.ricordo("caffe_ultimo", 0) or 0)
        if ora - float(lic.ricordo("caffe_offerto", 0) or 0) < CAFFE_DOPO_DONO:
            return
        if ultimo and (ora - ultimo < CAFFE_OGNI or avvii < CAFFE_AVVII):
            return
    except Exception:
        return
    tentativi = {"n": 0}

    def mostra():
        from PySide6.QtWidgets import QApplication
        occupato = QApplication.activeModalWidget() is not None or (puo_mostrare is not None and not puo_mostrare())
        if occupato:
            tentativi["n"] += 1
            if tentativi["n"] <= 20:
                QTimer.singleShot(60000, mostra)
            return
        lic.ricorda("caffe_ultimo", time.time())
        lic.ricorda("caffe_avvii", 0)
        CaffeDialog(lic, nome_app, parent, logo).exec()

    QTimer.singleShot(CAFFE_PRIMA, mostra)


def chiedi_pro(lic, funzione, nome_app, funzioni_pro, accento="#e11d48", parent=None, **finestra) -> bool:
    """Prima di una funzione Pro: vero se si può usare, altrimenti spiega e offre il Pro.
    `finestra` passa a ProDialog funzioni_free, font_icone e logo."""
    if lic is None or lic.sbloccato():
        return True
    scelta = QMessageBox(parent)
    scelta.setWindowTitle(nome_app)
    scelta.setText(f"«{funzione}» fa parte di {nome_app} Pro.")
    scelta.setInformativeText("Il Pro si sblocca con una donazione libera.")
    scopri = scelta.addButton("Scopri il Pro", QMessageBox.ButtonRole.AcceptRole)
    scelta.addButton("Non ora", QMessageBox.ButtonRole.RejectRole)
    scelta.exec()
    if scelta.clickedButton() is scopri:
        ProDialog(lic, nome_app, funzioni_pro, accento, parent, **finestra).exec()
    return lic.sbloccato()


# ------------------------------------------------------------------ software libero (dal 2026-10-25)
TERMINI = "https://pietrodefilippis.it/termini-e-condizioni/"
PRIVACY = "https://pietrodefilippis.it/privacy-policy/"
AGPL = "https://www.gnu.org/licenses/agpl-3.0.html"
AUTORE = "Pietro De Filippis (TecnikGeek)"

TESTO_STATISTICHE = ("Aiutami a contare le installazioni: una volta al giorno il programma invia il suo nome, "
                     "la versione e il sistema operativo, con un codice casuale. Niente file, nomi, email o "
                     "contenuti. Puoi cambiare idea quando vuoi, nelle Impostazioni o in Informazioni.")


def _link(testo, url):
    return f'<a href="{url}" style="color:#93c5fd;">{testo}</a>'


def casella_statistiche(lic, testo="Invia statistiche anonime di utilizzo"):
    """Casella per le Impostazioni: accende o spegne il segnale giornaliero (consenso dell'utente)."""
    from PySide6.QtWidgets import QCheckBox
    c = QCheckBox(testo)
    c.setObjectName("tkCasella")
    c.setStyleSheet(stile_casella("QCheckBox#tkCasella"))
    # in HTML il suggerimento va a capo (in testo semplice resta una riga lunga quanto lo schermo)
    c.setToolTip(f"<p style='max-width:360px'>{TESTO_STATISTICHE}</p>")
    c.setChecked(bool(lic is not None and lic.consenso_statistiche()))
    if lic is not None:
        c.toggled.connect(lambda v: lic.imposta_statistiche(v))
    return c


class BenvenutoDialog(_Centrata, QDialog):
    """Prima apertura: software libero, nessuna garanzia, privacy e consenso alle statistiche (spento di default)."""

    def __init__(self, lic, nome_app, url_sorgente, parent=None, logo=None, righe_extra=()):
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox
        self.lic = lic
        self.setWindowTitle(nome_app)
        self.setMinimumWidth(500)
        self.setMaximumWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background: {NAVY}; }} QLabel {{ color: #ffffff; background: transparent; }}"
            "#tkTit { font-size: 19px; font-weight: 800; }"
            f"#tkTesto {{ color: {CHIARO}; font-size: 13px; }}"
            f"#tkBox {{ background: {NAVY_2}; border: 1px solid {NAVY_3}; border-radius: 12px; }}"
            + stile_casella() +
            f"QPushButton#tkPrimo {{ background: {PRO_BLU}; color: white; border: 0; border-radius: 10px;"
            " padding: 11px 22px; font-size: 14px; font-weight: 800; }"
            f"QPushButton#tkPrimo:hover {{ background: {PRO_BLU_SCURO}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(14)
        testa = QHBoxLayout()
        testa.setSpacing(14)
        if logo is not None and not logo.isNull():
            ic = QLabel()
            dpr = logo.devicePixelRatio() or 1
            pm = logo.scaled(int(48 * dpr), int(48 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            ic.setPixmap(pm)
            testa.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        tit = QLabel(f"Benvenuto in {nome_app}")
        tit.setObjectName("tkTit")
        testa.addWidget(tit, 1)
        lay.addLayout(testa)

        righe = [
            f"{nome_app} è <b>software libero e gratuito</b>, con tutte le funzioni, sotto licenza "
            f"{_link('GNU AGPL-3.0', AGPL)}: puoi usarlo, studiarlo, modificarlo e condividerlo "
            f"({_link('codice sorgente', url_sorgente)}).",
            "È fornito <b>così com'è, senza alcuna garanzia</b> (licenza, sezioni 15 e 16): tieni una copia dei "
            "tuoi file importanti.",
        ] + list(righe_extra) + [
            "I tuoi file e i tuoi dati restano su questo computer. "
            f"{_link('Privacy', PRIVACY)} · {_link('Termini', TERMINI)}",
        ]
        # i testi scorrono se lo schermo è basso (es. 1366×768 con la barra, righe in più del programma)
        corpo = QWidget()
        corpo.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(corpo)
        cl.setContentsMargins(0, 0, 6, 0)
        cl.setSpacing(12)
        for r in righe:
            t = QLabel(r)
            t.setObjectName("tkTesto")
            t.setWordWrap(True)
            t.setTextFormat(Qt.TextFormat.RichText)
            t.setOpenExternalLinks(True)
            cl.addWidget(t)
        scorri = QScrollArea()
        scorri.setWidget(corpo)
        scorri.setWidgetResizable(True)
        scorri.setFrameShape(QFrame.Shape.NoFrame)
        scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scorri.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        schermo = QGuiApplication.primaryScreen()
        alto = schermo.availableGeometry().height() if schermo is not None else 800
        scorri.setMaximumHeight(max(160, alto - 330))   # resta posto per titolo, casella e «Inizia»
        corpo.adjustSize()
        scorri.setMinimumHeight(min(corpo.sizeHint().height() + 4, max(160, alto - 330)))
        lay.addWidget(scorri, 1)

        box = QFrame()
        box.setObjectName("tkBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(6)
        self.casella = QCheckBox("Invia statistiche anonime di utilizzo")
        self.casella.setChecked(False)
        bl.addWidget(self.casella)
        sp = QLabel(TESTO_STATISTICHE)
        sp.setObjectName("tkTesto")
        sp.setWordWrap(True)
        bl.addWidget(sp)
        lay.addWidget(box)

        riga = QHBoxLayout()
        riga.addStretch(1)
        ok = QPushButton("Inizia")
        ok.setObjectName("tkPrimo")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        riga.addWidget(ok)
        lay.addLayout(riga)

    def done(self, r):
        # anche chiudendo con la X la scelta vale (casella spenta = niente statistiche)
        if self.lic is not None:
            self.lic.imposta_statistiche(self.casella.isChecked())
            self.lic.ricorda("benvenuto_agpl", True)
        super().done(r)


def benvenuto(lic, nome_app, url_sorgente, parent=None, logo=None, righe_extra=()):
    """Da chiamare all'avvio, con la finestra aperta: la mostra una volta sola (poi mai più).
    `righe_extra` = frasi in più del programma (es. tk-desk: «usalo solo con chi conosci»)."""
    if lic is None or lic.ricordo("benvenuto_agpl", False):
        return
    BenvenutoDialog(lic, nome_app, url_sorgente, parent, logo, righe_extra).exec()


CONTATTI = "https://pietrodefilippis.it/contatti/"


class InformazioniDialog(_Centrata, QDialog):
    """Finestra «Informazioni» UGUALE in tutti i software TK (cambia solo il colore d'accento).

    Scheda navy arrotondata senza barra di sistema, trascinabile: logo, nome e descrizione; schede Versione,
    Sviluppatore, I tuoi dati, Privacy (statistiche + caselle del programma); «Controlla aggiornamenti»;
    «Licenze e codice sorgente» + «Offrimi un caffè»; «Icona sul Desktop» + «Chiudi»; Termini · Privacy · Contatti.

        InformazioniDialog(lic, "tk-pdf", VERSION, "Lettore ed editor PDF", logo, "#e11d48",
                           dati=[("I tuoi dati", cartella)], url_sorgente=URL_SORGENTE,
                           cartella_licenze=..., su_aggiornamenti=fn, su_icona_desktop=fn_o_None,
                           caselle=[(QCheckBox, "spiegazione")], pulsanti=[("Testo", fn)], parent=win).exec()

    `su_aggiornamenti` si chiama DOPO la chiusura della finestra. Un pulsante di `pulsanti` può restituire un
    testo nuovo per sé (es. «Pulsanti con testo: SÌ»).
    """

    LARGHEZZA = 480

    def __init__(self, lic, nome_app, versione, descrizione, logo, accento, dati=(), url_sorgente="",
                 cartella_licenze="", su_aggiornamenti=None, su_icona_desktop=None, caselle=(), pulsanti=(),
                 parent=None):
        super().__init__(parent)
        self.lic = lic
        self._dopo = None
        self._drag = None
        self.setWindowTitle(f"Informazioni — {nome_app}")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        scuro = _scuro(accento, 125)
        chiaro = QColor(accento).lighter(150).name()
        self.setStyleSheet(
            f"#tkInfoCarta {{ background:{NAVY}; border:1px solid {NAVY_3}; border-radius:20px; }}"
            "QLabel { color:#ffffff; background:transparent; }"
            f"#tkInfoKicker {{ color:{accento}; font-size:11px; font-weight:800; letter-spacing:2px; }}"
            "#tkInfoNome { font-size:22px; font-weight:800; }"
            f"#tkInfoDesc {{ color:{CHIARO}; font-size:13px; }}"
            f"#tkInfoScheda {{ background:{NAVY_2}; border-radius:12px; }}"
            f"#tkInfoTitolo {{ color:{accento}; font-size:11px; font-weight:800; letter-spacing:1px; }}"
            "#tkInfoValore { font-size:13px; font-weight:600; }"
            f"#tkInfoNota {{ color:{GRIGIO}; font-size:12px; }}"
            f"#tkInfoLink {{ color:{chiaro}; font-size:12px; font-weight:700; }}"
            # altezza fissata QUI (il foglio vince su setFixedHeight): uguale in tutti i programmi, qualunque stile abbiano
            "QPushButton { border:0; border-radius:10px; padding:0 14px; min-height:42px; max-height:42px;"
            " font-size:13px; font-weight:700; }"
            f"QPushButton#tkInfoAccento {{ background:{accento}; color:#ffffff; }}"
            f"QPushButton#tkInfoAccento:hover {{ background:{scuro}; }}"
            f"QPushButton#tkInfoChiaro {{ background:{NAVY_2}; color:#ffffff; border:1px solid {NAVY_3}; }}"
            f"QPushButton#tkInfoChiaro:hover {{ background:{NAVY_3}; }}"
            f"QScrollArea, #tkInfoCorpo {{ background:transparent; border:0; }}"
            f"QScrollBar:vertical {{ background:transparent; width:8px; margin:6px 2px; }}"
            f"QScrollBar::handle:vertical {{ background:{NAVY_3}; border-radius:3px; min-height:30px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }"
            + stile_casella())
        fuori = QVBoxLayout(self)
        fuori.setContentsMargins(26, 20, 26, 32)
        carta = QFrame()
        carta.setObjectName("tkInfoCarta")
        try:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            ombra = QGraphicsDropShadowEffect(carta)
            ombra.setBlurRadius(44)
            ombra.setOffset(0, 12)
            ombra.setColor(QColor(0, 0, 0, 110))
            carta.setGraphicsEffect(ombra)
        except Exception:
            pass
        fuori.addWidget(carta)
        cl = QVBoxLayout(carta)
        cl.setContentsMargins(0, 0, 0, 0)
        self._scorri = QScrollArea()
        self._scorri.setWidgetResizable(True)
        self._scorri.setFrameShape(QFrame.Shape.NoFrame)
        self._scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._corpo = QWidget()
        self._corpo.setObjectName("tkInfoCorpo")
        lay = QVBoxLayout(self._corpo)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        self._scorri.setWidget(self._corpo)
        cl.addWidget(self._scorri)

        kicker = QLabel("INFORMAZIONI")
        kicker.setObjectName("tkInfoKicker")
        lay.addWidget(kicker)
        testa = QHBoxLayout()
        testa.setSpacing(16)
        tile = QLabel()
        tile.setFixedSize(68, 68)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if logo is not None and not logo.isNull():
            dpr = logo.devicePixelRatio() or 1
            pm = logo.scaled(int(68 * dpr), int(68 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            tile.setPixmap(pm)
        testa.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        n = QLabel(nome_app)
        n.setObjectName("tkInfoNome")
        col.addWidget(n)
        d = QLabel(descrizione)
        d.setObjectName("tkInfoDesc")
        d.setWordWrap(True)
        col.addWidget(d)
        testa.addLayout(col, 1)
        lay.addLayout(testa)

        schede = [("Versione", f"{versione} · tutte le funzioni, gratis", ""),
                  ("Licenza", "Software libero · GNU AGPL-3.0", "Fornito così com'è, senza alcuna garanzia."),
                  ("Sviluppatore", f"TecnikGeek · {_link('pietrodefilippis.it', 'https://pietrodefilippis.it')}", "")]
        schede += [(t, v, nota) for t, v, *resto in dati for nota in [resto[0] if resto else ""]]
        for titolo, valore, nota in schede:
            lay.addWidget(self._scheda(titolo, valore, nota))

        # privacy: statistiche (consenso) + caselle del programma, con la spiegazione sempre visibile
        priv = QFrame()
        priv.setObjectName("tkInfoScheda")
        pl = QVBoxLayout(priv)
        pl.setContentsMargins(16, 12, 16, 14)
        pl.setSpacing(6)
        t = QLabel("PRIVACY")
        t.setObjectName("tkInfoTitolo")
        pl.addWidget(t)
        tutte = [(casella_statistiche(lic), "Una volta al giorno: nome, versione e sistema, con un codice casuale. "
                                            "Niente file né contenuti.")] + list(caselle)
        for casella, spiega in tutte:
            casella.setToolTip("")
            casella.setStyleSheet("")          # prende lo stile della finestra (uguale ovunque)
            pl.addWidget(casella)
            if spiega:
                s = QLabel(spiega)
                s.setObjectName("tkInfoNota")
                s.setWordWrap(True)
                s.setContentsMargins(30, 0, 0, 4)
                pl.addWidget(s)
        lay.addWidget(priv)

        for testo, fn in pulsanti:
            b = self._pulsante(testo, "tkInfoChiaro")
            b.clicked.connect(lambda _=False, b=b, fn=fn: self._extra(b, fn))
            lay.addWidget(b)
        if su_aggiornamenti is not None:
            agg = self._pulsante("Controlla aggiornamenti", "tkInfoAccento")
            agg.clicked.connect(lambda: self._chiudi_e(su_aggiornamenti))
            lay.addWidget(agg)
        riga = QHBoxLayout()
        riga.setSpacing(8)
        lic_b = self._pulsante("Licenze e codice sorgente", "tkInfoChiaro")
        lic_b.clicked.connect(lambda: LicenzeDialog(nome_app, versione, url_sorgente, cartella_licenze, self).exec())
        riga.addWidget(lic_b, 1)
        caffe = pulsante_caffe(lic, nome_oggetto="tkInfoChiaro")
        if caffe is not None:
            caffe.setFixedHeight(self.ALTEZZA_PULSANTE)
            riga.addWidget(caffe, 1)
        lay.addLayout(riga)
        riga2 = QHBoxLayout()
        riga2.setSpacing(8)
        if su_icona_desktop is not None:
            ico = self._pulsante("Icona sul Desktop", "tkInfoChiaro")
            ico.clicked.connect(su_icona_desktop)
            riga2.addWidget(ico, 1)
        chiudi = self._pulsante("Chiudi", "tkInfoChiaro")
        chiudi.clicked.connect(self.accept)
        riga2.addWidget(chiudi, 1)
        lay.addLayout(riga2)
        link = QLabel(f"<a href='{TERMINI}' style='color:{chiaro};text-decoration:none;'>Termini</a> &nbsp;·&nbsp; "
                      f"<a href='{PRIVACY}' style='color:{chiaro};text-decoration:none;'>Privacy</a> &nbsp;·&nbsp; "
                      f"<a href='{CONTATTI}' style='color:{chiaro};text-decoration:none;'>Contatti</a>")
        link.setObjectName("tkInfoLink")
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(link)
        self._misura()

    def _scheda(self, titolo, valore, nota=""):
        f = QFrame()
        f.setObjectName("tkInfoScheda")
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(3)
        t = QLabel(titolo.upper())
        t.setObjectName("tkInfoTitolo")
        v.addWidget(t)
        x = QLabel(valore)
        x.setObjectName("tkInfoValore")
        x.setWordWrap(True)
        x.setTextFormat(Qt.TextFormat.RichText)
        x.setOpenExternalLinks(True)
        x.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        v.addWidget(x)
        if nota:
            s = QLabel(nota)
            s.setObjectName("tkInfoNota")
            s.setWordWrap(True)
            v.addWidget(s)
        return f

    ALTEZZA_PULSANTE = 42

    @staticmethod
    def _pulsante(testo, nome):
        b = QPushButton(testo)
        b.setObjectName(nome)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedHeight(InformazioniDialog.ALTEZZA_PULSANTE)   # uguale in tutti i programmi, qualunque stile abbiano
        return b

    def _extra(self, b, fn):
        nuovo = fn()
        if isinstance(nuovo, str) and nuovo:
            b.setText(nuovo)

    def _chiudi_e(self, fn):
        self._dopo = fn
        self.accept()

    def done(self, r):
        super().done(r)
        if self._dopo is not None:
            fn, self._dopo = self._dopo, None
            QTimer.singleShot(0, fn)

    def _misura(self):
        """Larghezza fissa, altezza sul testo vero; oltre lo schermo il contenuto scorre."""
        self.setFixedWidth(self.LARGHEZZA + 52)
        utile = self.LARGHEZZA - 2 - self._scorri.verticalScrollBar().sizeHint().width()
        alto = self._corpo.layout().totalHeightForWidth(utile)
        if alto <= 0:
            alto = self._corpo.sizeHint().height()
        schermo = QGuiApplication.primaryScreen()
        massimo = (schermo.availableGeometry().height() - 40) if schermo is not None else 900
        self.resize(self.LARGHEZZA + 52, min(alto + 2 + 52, massimo))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class LicenzeDialog(_Centrata, QDialog):
    """Informazioni → «Licenze e codice sorgente»: AGPL del programma + licenze dei componenti inclusi.
    `cartella_licenze` = cartella `licenze/` del pacchetto (un file .txt per componente)."""

    def __init__(self, nome_app, versione, url_sorgente, cartella_licenze, parent=None):
        super().__init__(parent)
        import os
        from PySide6.QtWidgets import QListWidget, QPlainTextEdit
        self.setWindowTitle(f"{nome_app} — Licenze")
        self.resize(760, 560)
        self.setStyleSheet(
            f"QDialog {{ background: {NAVY}; }} QLabel {{ color: #ffffff; background: transparent; }}"
            f"#tkTesto {{ color: {CHIARO}; font-size: 13px; }}"
            f"QListWidget, QPlainTextEdit {{ background: {NAVY_2}; color: #e2e8f0; border: 1px solid {NAVY_3};"
            " border-radius: 10px; font-size: 12px; }"
            f"QListWidget::item:selected {{ background: {PRO_BLU}; color: white; }}"
            f"QPushButton {{ background: {NAVY_3}; color: white; border: 0; border-radius: 10px; padding: 9px 16px;"
            " font-weight: 700; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        t = QLabel(f"<b>{nome_app} {versione}</b> © 2026 {AUTORE}.<br>"
                   f"Software libero sotto licenza {_link('GNU Affero General Public License v3.0', AGPL)}, "
                   "senza alcuna garanzia.<br>"
                   f"Codice sorgente di questa versione: {_link(url_sorgente, url_sorgente)}<br>"
                   f"Il nome e il logo «{nome_app}» non sono coperti dalla licenza: una copia modificata "
                   "deve usare un nome diverso.")
        t.setObjectName("tkTesto")
        t.setWordWrap(True)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setOpenExternalLinks(True)
        lay.addWidget(t)
        corpo = QHBoxLayout()
        self.elenco = QListWidget()
        self.elenco.setFixedWidth(230)
        self.testo = QPlainTextEdit()
        self.testo.setReadOnly(True)
        corpo.addWidget(self.elenco)
        corpo.addWidget(self.testo, 1)
        lay.addLayout(corpo, 1)
        self._file = []
        try:
            nomi = sorted(os.listdir(cartella_licenze),
                          key=lambda n: (not n.upper().startswith("COPYING"), n.lower()))
            for nome in nomi:
                if nome.lower().endswith((".txt", ".md")) or nome.upper().startswith(("COPYING", "LICENSE")):
                    self._file.append(os.path.join(cartella_licenze, nome))
                    self.elenco.addItem(os.path.splitext(nome)[0])
        except Exception:
            pass
        if not self._file:
            self.testo.setPlainText(f"Testi delle licenze non trovati. Li trovi nel codice sorgente: {url_sorgente}")
        self.elenco.currentRowChanged.connect(self._mostra)
        if self._file:
            self.elenco.setCurrentRow(0)
        riga = QHBoxLayout()
        riga.addStretch(1)
        chiudi = QPushButton("Chiudi")
        chiudi.clicked.connect(self.accept)
        riga.addWidget(chiudi)
        lay.addLayout(riga)

    def _mostra(self, i):
        if 0 <= i < len(self._file):
            try:
                with open(self._file[i], encoding="utf-8", errors="replace") as fh:
                    self.testo.setPlainText(fh.read())
            except Exception as e:
                self.testo.setPlainText(f"Non riesco a leggere il file: {e}")
