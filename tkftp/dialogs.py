"""Finestre di tk-ftp: Informazioni, Impostazioni, aggiornamento, file già esistente, chiave SSH, certificato,
permessi, file modificato. Tutte nel nostro stile (scheda navy senza barra di sistema)."""
import os
import time

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout,
)

from tkftp import APP_TITLE, VERSION
from tkftp.listing import octal_to_perms, perms_to_octal
from tkftp.style import ACCENT, TkDialog, ic, kind_badge, logo_tile, text_btn, tk_warn
from tkftp.util import IS_LINUX, IS_MAC, human_size


PHRASE_MIN = 12  # frase segreta della cartella condivisa: minimo per quelle nuove


def _fmt(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "data sconosciuta"


class UpdateDialog(TkDialog):
    """Aggiornamento disponibile: novità e tre scelte."""

    def __init__(self, parent, manifest):
        super().__init__(parent, 460)
        self.choice = "later"
        self.head(logo_tile(52), f"È disponibile {APP_TITLE} {manifest['version']}",
                  f"Stai usando la versione {VERSION}" +
                  (f" · pubblicata il {manifest['date']}" if manifest.get("date") else ""))
        notes = manifest.get("notes") or []
        if notes:
            card = QFrame(objectName="acard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)
            cl.addWidget(QLabel("NOVITÀ", objectName="atitle"))
            for n in notes:
                lab = QLabel("•  " + str(n))
                lab.setWordWrap(True)
                lab.setStyleSheet("font-size:13px; font-weight:600;")
                cl.addWidget(lab)
            self.body.addWidget(card)
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, value in (("Salta questa versione", "skip"), ("Più tardi", "later")):
            b = QPushButton(label)
            b.setObjectName("ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._pick(v))
            row.addWidget(b)
        row.addStretch(1)
        go = text_btn("refresh", "Aggiorna ora", lambda: self._pick("go"), "#fff", "accent")
        go.setDefault(True)
        row.addWidget(go)
        self.body.addLayout(row)


class OverwriteDialog(TkDialog):
    """Il file di destinazione esiste già: cosa fare (anche per tutti i file in coda)."""
    ACTIONS = [("overwrite", "upload", "Sovrascrivi", "sostituisce il file che c'è"),
               ("newer", "clock", "Se è più recente", "sovrascrive solo se è più nuovo"),
               ("resume", "right", "Riprendi", "continua un file interrotto"),
               ("rename", "copy", "Rinomina", "li tiene entrambi: «nome (1)»"),
               ("skip", "close", "Salta", "lascia stare questo file")]

    def __init__(self, parent, item, src, dst):
        super().__init__(parent, 520)
        up = item.direction == "up"
        self.head(kind_badge("ask"), "Il file esiste già", f"«{item.name}» " + ("sul server" if up else "sul computer"))
        cards = QHBoxLayout()
        cards.setSpacing(10)
        for title, e, where in (("QUELLO CHE ARRIVA", src, "dal computer" if up else "dal server"),
                                ("QUELLO CHE C'È", dst, "sul server" if up else "sul computer")):
            card = QFrame(objectName="acard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cl.addWidget(QLabel(title, objectName="atitle"))
            v = QLabel(f"{human_size(e.size)}\n{_fmt(e.mtime)}\n{where}")
            v.setStyleSheet("font-size:13px; font-weight:600;")
            cl.addWidget(v)
            cards.addWidget(card, 1)
        self.body.addLayout(cards)
        self.choice = "skip"
        for value, icon, label, sub in self.ACTIONS:
            b = QPushButton(f"  {label}   ·   {sub}")
            b.setObjectName("choice")
            b.setIcon(ic(icon, ACCENT, 18))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._pick(v))
            if value == "overwrite":
                b.setDefault(True)
            if value == "resume" and dst.size >= src.size:
                b.setEnabled(False)
            self.body.addWidget(b)
        self.all = QCheckBox("Fai lo stesso per tutti i file di questa coda")
        self.body.addWidget(self.all)

    @staticmethod
    def ask(parent, item, src, dst):
        dlg = OverwriteDialog(parent, item, src, dst)
        dlg.exec()
        return (dlg.choice or "skip"), dlg.all.isChecked()


class HostKeyDialog(TkDialog):
    def __init__(self, parent, q):
        super().__init__(parent, 500)
        changed = bool(q.old)
        self.head(kind_badge("error" if changed else "key"),
                  "Attenzione: la chiave del server è cambiata!" if changed else "Server SSH nuovo",
                  f"{q.host}:{q.port}")
        text = ("La chiave che il server mostra non è quella che conoscevi. Può succedere se il server è stato "
                "reinstallato o spostato; altrimenti qualcuno potrebbe essersi messo in mezzo. Se non sai il perché, "
                "chiedi al tuo hosting prima di continuare." if changed else
                "È la prima volta che ti colleghi a questo server. Se l'impronta qui sotto è quella che ti ha dato il "
                "tuo hosting, fidati: tk-ftp la ricorda e la controlla a ogni connessione.")
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("font-size:13px; color:#e2e8f0;")
        self.body.addWidget(lab)
        self.info_card("TIPO DI CHIAVE", q.keytype)
        self.info_card("IMPRONTA", q.fingerprint, mono=True)
        if changed:
            self.info_card("IMPRONTA CHE CONOSCEVI", q.old.get("impronta", ""), mono=True)
        self.buttons([("Annulla", "ghost", False),
                      ("Sostituisci e connetti" if changed else "Fidati e connetti", "ghost" if changed else "accent", True)])


class CertDialog(TkDialog):
    def __init__(self, parent, q):
        super().__init__(parent, 500)
        self.head(kind_badge("error" if q.changed else "lock"),
                  "Il certificato del server è cambiato" if q.changed else "Certificato da confermare",
                  f"{q.host}:{q.port} · {q.reason}")
        lab = QLabel("La connessione è cifrata, ma tk-ftp non può verificare chi c'è dall'altra parte. Succede spesso "
                     "con i server degli hosting (certificato intestato al server e non al tuo dominio). Se ti fidi, "
                     "tk-ftp ricorda questo certificato e non te lo chiede più.")
        lab.setWordWrap(True)
        lab.setStyleSheet("font-size:13px; color:#e2e8f0;")
        self.body.addWidget(lab)
        info = q.info or {}
        self.info_card("INTESTATO A", f"{info.get('soggetto') or '—'}   ·   emesso da {info.get('emittente') or '—'}"
                       f"   ·   scade il {info.get('scadenza') or '—'}")
        fp = q.sha256.upper()
        self.info_card("IMPRONTA SHA-256", ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)), mono=True)
        self.buttons([("Annulla", "ghost", False), ("Fidati sempre", "accent", True)])


class ChmodDialog(TkDialog):
    def __init__(self, parent, names, perms, has_dirs):
        super().__init__(parent, 440)
        self.head(kind_badge("lock"), "Permessi", names)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for c, t in enumerate(("Lettura", "Scrittura", "Esecuzione")):
            lab = QLabel(t.upper(), objectName="atitle")
            grid.addWidget(lab, 0, c + 1)
        self.boxes = []
        for r, who in enumerate(("Proprietario", "Gruppo", "Tutti gli altri")):
            grid.addWidget(QLabel(who), r + 1, 0)
            for c in range(3):
                b = QCheckBox()
                b.toggled.connect(self._from_boxes)
                grid.addWidget(b, r + 1, c + 1, Qt.AlignmentFlag.AlignCenter)
                self.boxes.append(b)
        self.body.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel("Valore numerico"))
        self.octal = QLineEdit(perms_to_octal(perms) or "644")
        self.octal.setValidator(QRegularExpressionValidator(QRegularExpression("[0-7]{3}")))
        self.octal.setFixedWidth(90)
        self.octal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.octal.textEdited.connect(self._from_octal)
        row.addWidget(self.octal)
        row.addStretch(1)
        self.body.addLayout(row)
        self.recursive = QCheckBox("Applica anche a tutto il contenuto delle cartelle")
        self.recursive.setVisible(has_dirs)
        self.body.addWidget(self.recursive)
        self._from_octal(self.octal.text())
        self.buttons([("Annulla", "ghost", False), ("Applica", "accent", True)])

    def _from_octal(self, text):
        if len(text) != 3:
            return
        p = octal_to_perms(text)
        for b, ch in zip(self.boxes, p):
            b.blockSignals(True)
            b.setChecked(ch != "-")
            b.blockSignals(False)

    def _from_boxes(self):
        p = "".join("rwx"[i % 3] if b.isChecked() else "-" for i, b in enumerate(self.boxes))
        self.octal.setText(perms_to_octal(p))


class SettingsDialog(TkDialog):
    POLICY = [("ask", "Chiedi ogni volta"), ("overwrite", "Sovrascrivi"), ("newer", "Sovrascrivi se più recente"),
              ("resume", "Riprendi"), ("skip", "Salta")]

    def __init__(self, parent, settings, phrase):
        super().__init__(parent, 820)
        self.s = settings
        self.head(kind_badge("gear"), "Impostazioni", "Trasferimenti, doppio clic, modifica al volo, siti condivisi")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        def card(title):
            f = QFrame(objectName="acard")
            v = QVBoxLayout(f)
            v.setContentsMargins(16, 12, 16, 14)
            v.setSpacing(8)
            v.addWidget(QLabel(title, objectName="atitle"))
            return f, v

        def combo(options, current):
            c = QComboBox()
            for k, lab in options:
                c.addItem(lab, k)
            i = c.findData(current)
            c.setCurrentIndex(max(0, i))
            return c

        c1, v1 = card("TRASFERIMENTI")
        r = QHBoxLayout()
        r.addWidget(QLabel("Trasferimenti in parallelo"))
        r.addStretch(1)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 10)
        self.parallel.setValue(int(settings.value("parallel", 2)))
        self.parallel.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.parallel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.parallel.setFixedWidth(64)
        r.addWidget(text_btn("", "−", lambda: self.parallel.stepBy(-1), "#fff", "ghost"))
        r.addWidget(self.parallel)
        r.addWidget(text_btn("", "+", lambda: self.parallel.stepBy(1), "#fff", "ghost"))
        v1.addLayout(r)
        v1.addWidget(QLabel("Se il file esiste già"))
        self.policy = combo(self.POLICY, settings.value("policy", "ask"))
        v1.addWidget(self.policy)
        grid.addWidget(c1, 0, 0)

        c2, v2 = card("DOPPIO CLIC")
        v2.addWidget(QLabel("Su un file del server"))
        self.dbl_remote = combo([("edit", "Modifica al volo"), ("download", "Scarica")],
                                settings.value("dbl_remote", "edit"))
        v2.addWidget(self.dbl_remote)
        v2.addWidget(QLabel("Su un file del computer"))
        self.dbl_local = combo([("upload", "Carica sul server"), ("open", "Apri")], settings.value("dbl_local", "upload"))
        v2.addWidget(self.dbl_local)
        grid.addWidget(c2, 0, 1)

        c3, v3 = card("MODIFICA AL VOLO")
        v3.addWidget(QLabel("Programma per modificare i file"))
        er = QHBoxLayout()
        self.editor = QLineEdit(settings.value("editor", ""))
        self.editor.setPlaceholderText("Quello del sistema")
        self.editor.setReadOnly(True)
        er.addWidget(self.editor, 1)
        er.addWidget(text_btn("", "Scegli…", self._pick_editor, "#fff", "ghost"))
        er.addWidget(text_btn("", "Predefinito", lambda: self.editor.setText(""), "#fff", "ghost"))
        v3.addLayout(er)
        self.autoupload = QCheckBox("Quando salvi il file, ricaricalo sul server senza chiedere")
        self.autoupload.setChecked(bool(settings.value("edit_autoupload", False)))
        v3.addWidget(self.autoupload)
        self.hidden = QCheckBox("Mostra i file nascosti del computer")
        self.hidden.setChecked(bool(settings.value("show_hidden", False)))
        v3.addWidget(self.hidden)
        self.logos = QCheckBox("Mostra il logo dei siti (lo cerca sul loro sito web)")
        self.logos.setChecked(bool(settings.value("show_logos", True)))
        v3.addWidget(self.logos)
        from tkftp import pro
        from tkftp.tk_licenza_qt import casella_statistiche
        self.stats = casella_statistiche(pro.licenza())  # si salva subito al clic (consenso dell'utente)
        v3.addWidget(self.stats)
        grid.addWidget(c3, 1, 0)

        c4, v4 = card("SITI CONDIVISI COL TELEFONO")
        hint = QLabel("tk-ftp tiene i siti anche in una cartella condivisa (per esempio una cartella nel cloud), nel file "
                      "«tk-ftp-siti.xml»: dall'app tk-ftp sul telefono lo apri con Importa.")
        hint.setWordWrap(True)
        hint.setObjectName("asub")
        v4.addWidget(hint)
        dr = QHBoxLayout()
        self.shared = QLineEdit(settings.value("shared_dir", ""))
        self.shared.setPlaceholderText("Nessuna cartella condivisa")
        self.shared.setReadOnly(True)
        dr.addWidget(self.shared, 1)
        dr.addWidget(text_btn("", "Scegli…", self._pick_shared, "#fff", "ghost"))
        dr.addWidget(text_btn("", "Togli", lambda: self.shared.setText(""), "#fff", "ghost"))
        v4.addLayout(dr)
        self.shared_pw = QCheckBox("Includi le password, cifrate con una frase segreta")
        self.shared_pw.setChecked(bool(settings.value("shared_pw", False)))
        v4.addWidget(self.shared_pw)
        self.old_phrase = phrase or ""
        self.phrase = QLineEdit(phrase)
        self.phrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.phrase.setPlaceholderText(f"Frase segreta (almeno {PHRASE_MIN} caratteri)")
        self.phrase.setToolTip("La stessa frase su ogni computer e sul telefono")
        v4.addWidget(self.phrase)
        self.shared_pw.toggled.connect(self.phrase.setEnabled)
        self.phrase.setEnabled(self.shared_pw.isChecked())
        grid.addWidget(c4, 1, 1)
        for v in (v1, v2, v3, v4):
            v.addStretch(1)  # contenuto in alto anche quando la scheda vicina è più alta
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        # caffè: sempre ben visibile nelle Impostazioni (come la card «Offrimi un caffè» dei plugin TK)
        caffe = pro.pulsante_caffe("ghost")   # None a chi ha già donato con una chiave vecchia: niente card
        if caffe is not None:
            c5, v5 = card("OFFRIMI UN CAFFÈ")
            r5 = QHBoxLayout()
            r5.setSpacing(14)
            t5 = QLabel(f"{APP_TITLE} è gratis. Se ti è utile, un caffè mi aiuta a migliorarlo e a crearne altri.")
            t5.setWordWrap(True)
            t5.setObjectName("asub")
            r5.addWidget(t5, 1)
            caffe.setMinimumWidth(190)
            r5.addWidget(caffe)
            v5.addLayout(r5)
            self.body.addWidget(c5)
        self.buttons([("Annulla", "ghost", False), ("Salva", "accent", True)])
        self._accept = self.accept
        self.accept = self._validate  # noqa: assegnazione voluta: controllo prima di chiudere

    def _validate(self):
        # una frase NUOVA deve avere almeno 12 caratteri; quella già salvata (anche di 8) continua a valere,
        # così gli altri computer e il telefono che la usano non vanno riconfigurati
        p = self.phrase.text()
        if self.choice and self.shared_pw.isChecked() and self.shared.text() and \
                (len(p) < 8 or (p != self.old_phrase and len(p) < PHRASE_MIN)):
            tk_warn(self, APP_TITLE, f"La frase segreta deve avere almeno {PHRASE_MIN} caratteri: meglio qualche "
                                     "parola che non c'entra niente, es. «gatto lampada nuvola 7».")
            self.choice = None
            return
        self._accept()

    def _pick_editor(self):
        if IS_MAC:
            path = QFileDialog.getOpenFileName(self, "Scegli il programma per modificare i file", "/Applications",
                                               "Applicazioni (*.app)")[0]
        elif IS_LINUX:
            path = QFileDialog.getOpenFileName(self, "Scegli il programma per modificare i file", "/usr/bin",
                                               "Programmi (*)")[0]
        else:
            start = os.environ.get("ProgramFiles", "C:\\")
            path = QFileDialog.getOpenFileName(self, "Scegli il programma per modificare i file", start,
                                               "Programmi (*.exe)")[0]
        if path:
            self.editor.setText(os.path.normpath(path))

    def _pick_shared(self):
        start = self.shared.text() or os.path.join(os.path.expanduser("~"), "Dropbox")
        path = QFileDialog.getExistingDirectory(self, "Cartella condivisa (es. una cartella nel cloud)",
                                                start if os.path.isdir(start) else os.path.expanduser("~"))
        if path:
            self.shared.setText(os.path.normpath(path))

    def values(self):
        return {
            "parallel": self.parallel.value(),
            "policy": self.policy.currentData(),
            "dbl_remote": self.dbl_remote.currentData(),
            "dbl_local": self.dbl_local.currentData(),
            "editor": self.editor.text(),
            "edit_autoupload": self.autoupload.isChecked(),
            "show_hidden": self.hidden.isChecked(),
            "show_logos": self.logos.isChecked(),
            "shared_dir": self.shared.text(),
            "shared_pw": self.shared_pw.isChecked(),
        }


class EditChangedDialog(TkDialog):
    def __init__(self, parent, name, host):
        super().__init__(parent, 440)
        self.head(kind_badge("upload"), "File modificato", f"«{name}»")
        lab = QLabel(f"Hai salvato delle modifiche. Lo ricarico su {host}?")
        lab.setWordWrap(True)
        lab.setStyleSheet("font-size:14px; color:#e2e8f0;")
        self.body.addWidget(lab)
        self.buttons([("Non ora", "ghost", "no"), ("Sempre per questo file", "ghost", "always"), ("Carica", "accent", "yes")])
