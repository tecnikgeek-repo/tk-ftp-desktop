"""Gestore siti: gruppi e siti a sinistra, scheda del sito a destra (si salva da sola mentre scrivi)."""
import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit,
    QScrollArea, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tkftp.util import conta
from tkftp import APP_TITLE
from tkftp.sites import LOGONS, PROTOCOLS, PROTOCOL_SHORT, Site, default_port, get_password, set_password
from tkftp.style import (
    GRAY_500, NAVY, PROTO_COLOR, field, ic, kind_icon, logo_tile, shadow, site_badge, text_btn, tk_choice, tk_input,
    tool_btn,
)


def avatar(site, size=22):
    """Logo del sito (se c'è) o lettera colorata."""
    from tkftp.style import site_badge
    pm = site_badge(site, size)
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Mode.Selected)  # sulla riga selezionata Qt colorerebbe il logo
    return icon


def _letter_avatar(site, size=22):
    short = PROTOCOL_SHORT.get(site.protocol, "FTP")
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(PROTO_COLOR.get(short, NAVY)))
    p.drawRoundedRect(0, 0, size * 2, size * 2, size * .6, size * .6)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 1.0))
    p.setFont(f)
    p.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), (site.title[:1] or "?").upper())
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class SiteManager(QDialog):
    connect_site = Signal(object)

    def __init__(self, parent, store, actions=None, select_id=None, settings=None):
        super().__init__(parent)
        self.store = store
        # gruppi aperti: ricordati tra ricostruzioni, riaperture del Gestore e riavvii (chiave = percorso del gruppo)
        self.settings = settings
        self.open_groups = set((settings.value("gruppi_aperti", []) if settings else []) or [])
        self._restoring = False
        self._first_build = True
        self.actions = actions or {}
        self.setObjectName("tk")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(1080, 720)
        self.current = None
        self._loading = False
        self._drag = None
        self.save_timer = QTimer(self, singleShot=True, interval=500)
        self.save_timer.timeout.connect(self._save)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 42)  # spazio per tutta l'ombra
        card = QFrame(objectName="lightcard")
        shadow(card, 44, 12, 110)
        outer.addWidget(card)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        head = QFrame(objectName="lighthead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 14, 16, 14)
        hl.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_tile(40))
        hl.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel("Gestore siti")
        t.setStyleSheet("color:#fff; font-size:18px; font-weight:800;")
        col.addWidget(t)
        self.count = QLabel("")
        self.count.setStyleSheet("color:#cbd5e1; font-size:11px;")
        col.addWidget(self.count)
        hl.addLayout(col)
        hl.addStretch(1)
        if self.actions.get("import"):
            hl.addWidget(text_btn("import", "Importa da FileZilla", self.actions["import"], "#fff", "ghost"))
        if self.actions.get("export"):
            hl.addWidget(text_btn("export", "Esporta per FileZilla", self.actions["export"], "#fff", "ghost"))
        hl.addWidget(tool_btn("close", "Chiudi (Esc)", self.accept, "#ffffff", "mini"))
        hl.itemAt(hl.count() - 1).widget().setStyleSheet(
            "QPushButton { background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.14); }"
            "QPushButton:hover { background:rgba(255,255,255,.2); }")
        cl.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(18, 16, 18, 18)
        body.setSpacing(16)
        cl.addLayout(body, 1)

        # ---------------- elenco
        left = QFrame(objectName="card")
        left.setFixedWidth(330)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca per nome, indirizzo o utente")
        self.search.addAction(ic("search", GRAY_500, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(22, 22))
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.currentItemChanged.connect(self._picked)
        self.tree.itemDoubleClicked.connect(self._double)
        self.tree.itemExpanded.connect(lambda it: self._group_toggled(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._group_toggled(it, False))
        ll.addWidget(self.tree, 1)
        br = QHBoxLayout()
        br.setSpacing(6)
        br.addWidget(text_btn("plus", "Sito", self.new_site, "#fff", "accent", "Nuovo sito"))
        br.addWidget(text_btn("folder-plus", "Gruppo", self.new_group, NAVY, "", "Nuovo gruppo"))
        br.addStretch(1)
        br.addWidget(tool_btn("copy", "Duplica il sito", self.duplicate, NAVY))
        br.addWidget(tool_btn("trash", "Elimina", self.delete, "#b91c1c"))
        ll.addLayout(br)
        body.addWidget(left)

        # ---------------- scheda del sito
        right = QFrame(objectName="card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(22, 18, 22, 16)
        rl.setSpacing(12)
        top = QHBoxLayout()
        self.big = QLabel()
        self.big.setFixedSize(48, 48)
        top.addWidget(self.big)
        tc = QVBoxLayout()
        tc.setSpacing(0)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:20px; font-weight:800;")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("cardsub")
        tc.addWidget(self.title)
        tc.addWidget(self.subtitle)
        top.addLayout(tc, 1)
        self.saved = QLabel("")
        self.saved.setObjectName("hint")
        top.addWidget(self.saved, 0, Qt.AlignmentFlag.AlignTop)
        rl.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_w = QWidget(objectName="canvas")
        scroll.setWidget(form_w)
        g = QGridLayout(form_w)
        g.setContentsMargins(0, 0, 6, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(5)
        self.f_name = QLineEdit()
        self.f_name.setPlaceholderText("Es. Sito del cliente")
        self.f_group = QComboBox()
        self.f_group.setEditable(True)
        self.f_group.lineEdit().setPlaceholderText("Nessun gruppo")
        self.f_proto = QComboBox()
        for k, lab, _n in PROTOCOLS:
            self.f_proto.addItem(lab, k)
        self.f_host = QLineEdit()
        self.f_host.setPlaceholderText("ftp.esempio.it")
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_logon = QComboBox()
        for k, lab in LOGONS:
            self.f_logon.addItem(lab, k)
        self.f_user = QLineEdit()
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.eye = self.f_pass.addAction(ic("eye", GRAY_500, 16), QLineEdit.ActionPosition.TrailingPosition)
        self.eye.triggered.connect(lambda: self.f_pass.setEchoMode(
            QLineEdit.EchoMode.Normal if self.f_pass.echoMode() == QLineEdit.EchoMode.Password else QLineEdit.EchoMode.Password))
        self.f_key = QLineEdit()
        self.f_key.setPlaceholderText("Percorso del file della chiave privata (OpenSSH)")
        self.f_rdir = QLineEdit()
        self.f_rdir.setPlaceholderText("Es. /public_html (vuoto = quella del server)")
        self.f_ldir = QLineEdit()
        self.f_ldir.setPlaceholderText("Cartella del computer da aprire (facoltativa)")
        self.f_mode = QComboBox()
        self.f_mode.addItem("Passiva (consigliata)", True)
        self.f_mode.addItem("Attiva", False)
        self.f_notes = QPlainTextEdit(objectName="notes")
        self.f_notes.setFixedHeight(64)
        self.l_pass = field("Password")
        self.l_key = field("File chiave")
        self.l_mode = field("Modalità di trasferimento")
        key_row = QHBoxLayout()
        key_row.addWidget(self.f_key, 1)
        self.b_key = text_btn("key", "Sfoglia…", self._pick_key, NAVY, "")
        key_row.addWidget(self.b_key)
        self.f_web = QLineEdit()
        self.f_web.setPlaceholderText("Es. miosito.it (facoltativo)")
        self.f_web.setToolTip("Se è vuoto, tk-ftp prova a dedurlo dall'host e dal nome del sito")
        web_row = QHBoxLayout()
        web_row.addWidget(self.f_web, 1)
        web_row.addWidget(text_btn("refresh", "Aggiorna logo", self._logo_refresh, NAVY, "",
                                   "Cerca di nuovo il logo del sito"))
        web_row.addWidget(text_btn("image", "Scegli immagine…", self._logo_pick, NAVY, "",
                                   "Usa un'immagine tua come logo di questo sito"))
        ldir_row = QHBoxLayout()
        ldir_row.addWidget(self.f_ldir, 1)
        ldir_row.addWidget(text_btn("folder", "Sfoglia…", self._pick_ldir, NAVY, ""))
        r = 0

        def put(label, w, col=0, span=1):
            g.addWidget(label if isinstance(label, QLabel) else field(label), r, col, 1, span)
            if isinstance(w, QHBoxLayout):
                g.addLayout(w, r + 1, col, 1, span)
            else:
                g.addWidget(w, r + 1, col, 1, span)

        put("Nome", self.f_name, 0)
        put("Gruppo", self.f_group, 1)
        r += 2
        put("Protocollo", self.f_proto, 0)
        put("Accesso", self.f_logon, 1)
        r += 2
        hp = QHBoxLayout()
        hp.addWidget(self.f_host, 1)
        hp.addWidget(QLabel(":"))
        self.f_port.setFixedWidth(90)
        # campo numerico pulito: le frecce dello spinbox con il nostro stile uscivano tagliate
        self.f_port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.f_port.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hp.addWidget(self.f_port)
        put("Indirizzo del server (host) e porta", hp, 0, 2)
        r += 2
        put("Utente", self.f_user, 0)
        put(self.l_pass, self.f_pass, 1)
        r += 2
        put(self.l_key, key_row, 0, 2)
        self.key_widgets = [self.l_key, self.f_key, self.b_key]
        r += 2
        put("Cartella remota iniziale", self.f_rdir, 0)
        put(self.l_mode, self.f_mode, 1)
        r += 2
        put("Cartella locale iniziale", ldir_row, 0, 2)
        r += 2
        self.l_web = field("Sito web (per il logo)")
        put(self.l_web, web_row, 0, 2)
        r += 2
        put("Note", self.f_notes, 0, 2)
        r += 2
        g.setRowStretch(r, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        rl.addWidget(scroll, 1)
        self.form = form_w

        foot = QHBoxLayout()
        self.hint = QLabel("Le password vanno nel portachiavi del sistema, mai in chiaro su disco.")
        self.hint.setObjectName("hint")
        foot.addWidget(self.hint, 1)
        foot.addWidget(text_btn("", "Chiudi", self.accept, NAVY, ""))
        self.b_connect = text_btn("plug", "Connetti", self._connect, "#fff", "accent")
        foot.addWidget(self.b_connect)
        rl.addLayout(foot)
        body.addWidget(right, 1)

        for w in (self.f_name, self.f_host, self.f_user, self.f_pass, self.f_key, self.f_rdir, self.f_ldir, self.f_web):
            w.textEdited.connect(self._changed)
        self.f_group.editTextChanged.connect(self._changed)
        self.f_proto.currentIndexChanged.connect(self._proto_changed)
        self.f_logon.currentIndexChanged.connect(self._changed)
        self.f_mode.currentIndexChanged.connect(self._changed)
        self.f_port.valueChanged.connect(self._changed)
        self.f_notes.textChanged.connect(self._changed)
        if select_id is None and self.store.recent(1):
            select_id = self.store.recent(1)[0].id  # senza sito in uso: l'ultimo usato
        self.rebuild(select_id)

    # -------------------------------------------------- elenco
    def rebuild(self, select_id=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}

        def group_item(path):
            if not path:
                return self.tree.invisibleRootItem()
            if path in groups:
                return groups[path]
            parent, _, name = path.rpartition("/")
            it = QTreeWidgetItem(group_item(parent), [name])
            it.setIcon(0, kind_icon("dir", 18))
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
            it.setData(0, Qt.ItemDataRole.UserRole, ("group", path))
            groups[path] = it
            return it

        for gname in sorted(set(self.store.groups) | {s.group for s in self.store.sites if s.group}, key=str.lower):
            group_item(gname)
        target = None
        for s in sorted(self.store.sites, key=lambda s: s.title.lower()):
            it = QTreeWidgetItem(group_item(s.group), [s.title])
            it.setIcon(0, avatar(s))
            it.setToolTip(0, f"{PROTOCOL_SHORT.get(s.protocol)} · {s.user + '@' if s.user else ''}{s.host}:{s.port}")
            it.setData(0, Qt.ItemDataRole.UserRole, ("site", s.id))
            if s.id == select_id:
                target = it
        self.tree.blockSignals(False)
        if self._first_build and target is not None:
            # alla prima apertura del Gestore: aperto il gruppo del sito scelto (e i suoi genitori), gli altri come salvati
            g = self.store.get(select_id).group if select_id and self.store.get(select_id) else ""
            while g:
                self.open_groups.add(g)
                g = g.rpartition("/")[0]
            self._save_groups()
        self._first_build = False
        self._groups = groups
        self._apply_groups()
        self.f_group.blockSignals(True)
        cur = self.f_group.currentText()
        self.f_group.clear()
        self.f_group.addItem("")
        self.f_group.addItems(sorted(set(self.store.groups) | {s.group for s in self.store.sites if s.group}, key=str.lower))
        self.f_group.setEditText(cur)
        self.f_group.blockSignals(False)
        ng = len(set(self.store.groups) | {s.group for s in self.store.sites if s.group})
        self.count.setText(f"{conta(len(self.store.sites), 'sito', 'siti')} · {conta(ng, 'gruppo', 'gruppi')}")
        if target is None:
            target = self._first_site(self.tree.invisibleRootItem())
        if target is not None:
            # niente scorrimento automatico: Qt riaprirebbe il gruppo chiuso che contiene il sito selezionato
            self.tree.setAutoScroll(False)
            self._restoring = True
            self.tree.setCurrentItem(target)
            self._restoring = False
            self.tree.setAutoScroll(True)
        else:
            self._show(None)
        self._filter(self.search.text())

    def _apply_groups(self):
        """Stato aperto/chiuso salvato su tutti i gruppi."""
        self._restoring = True
        for path, it in getattr(self, "_groups", {}).items():
            it.setExpanded(path in self.open_groups)
        self._restoring = False

    def _group_toggled(self, it, opened):
        if self._restoring or self.search.text().strip():
            return  # ricostruzione o ricerca: non è una scelta dell'utente
        kind, val = it.data(0, Qt.ItemDataRole.UserRole)
        if kind != "group":
            return
        (self.open_groups.add if opened else self.open_groups.discard)(val)
        self._save_groups()

    def _save_groups(self):
        if self.settings is not None:
            self.settings.setValue("gruppi_aperti", sorted(self.open_groups))

    def _first_site(self, node):
        for i in range(node.childCount()):
            c = node.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole)[0] == "site":
                return c
            f = self._first_site(c)
            if f:
                return f
        return None

    def _filter(self, text):
        t = text.strip().lower()

        def walk(node):
            any_visible = False
            for i in range(node.childCount()):
                c = node.child(i)
                kind, val = c.data(0, Qt.ItemDataRole.UserRole)
                if kind == "group":
                    vis = walk(c) or (t and t in val.lower())
                else:
                    s = self.store.get(val)
                    vis = not t or any(t in x.lower() for x in (s.title, s.host, s.user)) if s else False
                c.setHidden(not vis)
                if kind == "group" and t:
                    self._restoring = True
                    c.setExpanded(bool(vis))  # durante la ricerca: aperti i gruppi con risultati
                    self._restoring = False
                any_visible |= bool(vis)
            return any_visible
        walk(self.tree.invisibleRootItem())
        if not t:
            self._apply_groups()  # ricerca svuotata: si torna allo stato salvato

    def _picked(self, cur, _prev):
        self._flush()
        if cur is None:
            return
        kind, val = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "site":
            self._show(self.store.get(val))
        else:
            self._show(None, group=val)

    def _double(self, it, _col):
        kind, val = it.data(0, Qt.ItemDataRole.UserRole)
        if kind == "site":
            self._connect()
        else:
            self.rename_group(val)

    # -------------------------------------------------- scheda
    def _show(self, site, group=""):
        self._loading = True
        self.current = site
        self.form.setEnabled(site is not None)
        self.b_connect.setEnabled(site is not None)
        if site is None:
            self.big.setPixmap(kind_icon("dir", 24).pixmap(48, 48) if group else QPixmap())
            self.title.setText(group.rsplit("/", 1)[-1] if group else "Nessun sito")
            n = sum(1 for s in self.store.sites if s.group == group or s.group.startswith(group + "/")) if group else 0
            self.subtitle.setText(f"Gruppo con {conta(n, 'sito', 'siti')} · doppio clic per rinominarlo" if group else
                                  "Crea un sito con «+ Sito» oppure importa i siti da FileZilla")
            for w in (self.f_name, self.f_host, self.f_user, self.f_pass, self.f_key, self.f_rdir, self.f_ldir,
                      self.f_web):
                w.clear()
            self.f_notes.clear()
            self.new_group_hint = group
            self._loading = False
            return
        self.big.setPixmap(site_badge(site, 48))
        self._titles()
        self.f_name.setText(site.name)
        self.f_group.setEditText(site.group)
        self.f_proto.setCurrentIndex(max(0, self.f_proto.findData(site.protocol)))
        self.f_host.setText(site.host)
        self.f_port.setValue(int(site.port or default_port(site.protocol)))
        self.f_logon.setCurrentIndex(max(0, self.f_logon.findData(site.logon)))
        self.f_user.setText(site.user)
        self.f_pass.setText(get_password(site))
        self.f_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_key.setText(site.keyfile)
        self.f_rdir.setText(site.remote_dir)
        self.f_ldir.setText(site.local_dir)
        self.f_web.setText(getattr(site, "website", ""))
        self._web_last = getattr(site, "website", "")
        self._logo_hint()
        self.f_mode.setCurrentIndex(0 if site.passive else 1)
        self.f_notes.setPlainText(site.notes)
        self.saved.setText("")
        self._loading = False
        self._visibility()

    def _titles(self):
        s = self.current
        if s is None:
            return
        self.title.setText(s.title or "Nuovo sito")
        self.subtitle.setText(f"{PROTOCOL_SHORT.get(s.protocol)} · {s.user + '@' if s.user else ''}{s.host or '—'}:{s.port}")

    def _visibility(self):
        proto = self.f_proto.currentData()
        logon = self.f_logon.currentData()
        is_key = proto == "sftp" and logon == "key"
        for w in self.key_widgets:
            w.setVisible(is_key)
        self.l_pass.setText("FRASE DELLA CHIAVE (SE C'È)" if is_key else "PASSWORD")
        show_pw = logon in ("normal", "key")
        self.l_pass.setVisible(show_pw)
        self.f_pass.setVisible(show_pw)
        ftp = proto != "sftp"
        self.l_mode.setVisible(ftp)
        self.f_mode.setVisible(ftp)

    def _proto_changed(self):
        if self._loading or self.current is None:
            return
        old = self.current.protocol
        new = self.f_proto.currentData()
        if self.f_port.value() == default_port(old):
            self.f_port.blockSignals(True)
            self.f_port.setValue(default_port(new))
            self.f_port.blockSignals(False)
        if new != "sftp" and self.f_logon.currentData() == "key":
            self.f_logon.setCurrentIndex(self.f_logon.findData("normal"))
        self._changed()

    def _changed(self, *a):
        if self._loading or self.current is None:
            return
        s = self.current
        s.name = self.f_name.text().strip()
        s.group = self.f_group.currentText().strip().strip("/")
        s.protocol = self.f_proto.currentData()
        s.host = self.f_host.text().strip()
        s.port = self.f_port.value()
        s.logon = self.f_logon.currentData()
        s.user = self.f_user.text().strip()
        s.keyfile = self.f_key.text().strip()
        s.remote_dir = self.f_rdir.text().strip()
        s.local_dir = self.f_ldir.text().strip()
        s.website = self.f_web.text().strip()
        s.passive = bool(self.f_mode.currentData())
        s.notes = self.f_notes.toPlainText()
        self._titles()
        self._visibility()
        self.saved.setText("Salvataggio…")
        self.save_timer.start()

    def _save(self):
        s = self.current
        if s is None:
            return
        pw = self.f_pass.text() if s.logon in ("normal", "key") else ""
        cur = self.tree.currentItem()
        is_cur = cur is not None and cur.data(0, Qt.ItemDataRole.UserRole) == ("site", s.id)
        regroup = is_cur and self._group_of(cur) != s.group
        retitle = is_cur and cur.text(0) != s.title
        self.store.upsert(s, None)
        try:
            if pw != get_password(s):
                set_password(s, pw)
        except OSError as exc:
            self.saved.setText("")
            tk_choice(self, APP_TITLE, f"Non riesco a salvare la password nel portachiavi:\n{exc}", [("OK", "accent")], "warn")
            return
        self.saved.setText("Salvato")
        if getattr(s, "website", "") != getattr(self, "_web_last", None) and self.actions.get("logo"):
            # sito web cambiato: il logo si cerca subito, senza premere «Aggiorna logo»
            self._web_last = s.website
            self.actions["logo"](s, True)
            self.saved.setText("Cerco il logo…")
        if regroup:
            self.rebuild(s.id)
        elif retitle:
            it = self.tree.currentItem()
            it.setText(0, s.title)
            it.setIcon(0, avatar(s))

    def _flush(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save()

    def _group_of(self, it):
        p = it.parent()
        return p.data(0, Qt.ItemDataRole.UserRole)[1] if p is not None else ""

    # -------------------------------------------------- azioni
    def _selected_group(self):
        it = self.tree.currentItem()
        if it is None:
            return ""
        kind, val = it.data(0, Qt.ItemDataRole.UserRole)
        return val if kind == "group" else (self.store.get(val).group if self.store.get(val) else "")

    def new_site(self, group=None):
        self._flush()
        s = Site(name="Nuovo sito", group=self._selected_group() if group is None else group)
        self.store.upsert(s, None)
        self.rebuild(s.id)
        self.f_name.setFocus()
        self.f_name.selectAll()

    def new_group(self):
        parent = self._selected_group()
        r = tk_input(self, "Nuovo gruppo", "Nome del gruppo (con «/» crei un sottogruppo)", "", "Crea")
        if not r or not r.strip():
            return
        name = r.strip().strip("/")
        if parent and "/" not in name:
            name = f"{parent}/{name}"
        self.store.groups.append(name)
        self.store.save()
        self.rebuild()
        self._select_group(name)

    def _select_group(self, name):
        def walk(node):
            for i in range(node.childCount()):
                c = node.child(i)
                if c.data(0, Qt.ItemDataRole.UserRole) == ("group", name):
                    self.tree.setCurrentItem(c)
                    return True
                if walk(c):
                    return True
            return False
        walk(self.tree.invisibleRootItem())

    def rename_group(self, name):
        r = tk_input(self, "Rinomina gruppo", "Nuovo nome", name, "Rinomina")
        if r and r.strip() and r.strip() != name:
            self.store.rename_group(name, r.strip())
            self.rebuild()
            self._select_group(r.strip().strip("/"))

    def duplicate(self):
        self._flush()
        if self.current is None:
            return
        c = self.current.copy()
        import uuid
        c.id = uuid.uuid4().hex
        c.name = (self.current.title + " (copia)")
        c.last_used = 0
        self.store.upsert(c, get_password(self.current) or None)
        self.rebuild(c.id)

    def delete(self):
        it = self.tree.currentItem()
        if it is None:
            return
        kind, val = it.data(0, Qt.ItemDataRole.UserRole)
        if kind == "site":
            s = self.store.get(val)
            if s and tk_choice(self, "Eliminare il sito?", f"«{s.title}» e la sua password salvata.",
                               [("Annulla", "ghost"), ("Elimina", "accent")], "warn") == 1:
                self.save_timer.stop()
                self.current = None
                self.store.delete(val)
                self.rebuild()
        else:
            if tk_choice(self, "Eliminare il gruppo?", f"«{val}»: i suoi siti restano e passano al gruppo superiore.",
                         [("Annulla", "ghost"), ("Elimina il gruppo", "accent")], "warn") == 1:
                self.store.delete_group(val)
                self.rebuild()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QMenu(self)
        if it is None:
            m.addAction(QAction(ic("plus", NAVY, 16), "Nuovo sito", self, triggered=lambda: self.new_site("")))
            m.addAction(QAction(ic("folder-plus", NAVY, 16), "Nuovo gruppo", self, triggered=self.new_group))
        else:
            self.tree.setCurrentItem(it)
            kind, val = it.data(0, Qt.ItemDataRole.UserRole)
            if kind == "site":
                m.addAction(QAction(ic("plug", NAVY, 16), "Connetti", self, triggered=self._connect))
                m.addAction(QAction(ic("copy", NAVY, 16), "Duplica", self, triggered=self.duplicate))
                m.addSeparator()
                m.addAction(QAction(ic("trash", "#b91c1c", 16), "Elimina", self, triggered=self.delete))
            else:
                m.addAction(QAction(ic("plus", NAVY, 16), "Nuovo sito in questo gruppo", self,
                                    triggered=lambda: self.new_site(val)))
                m.addAction(QAction(ic("folder-plus", NAVY, 16), "Nuovo sottogruppo", self, triggered=self.new_group))
                m.addAction(QAction(ic("edit", NAVY, 16), "Rinomina gruppo", self,
                                    triggered=lambda: self.rename_group(val)))
                m.addSeparator()
                m.addAction(QAction(ic("trash", "#b91c1c", 16), "Elimina gruppo", self, triggered=self.delete))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # -------------------------------------------------- logo
    def _logo_refresh(self):
        self._flush()
        if self.current is not None and self.actions.get("logo"):
            self.actions["logo"](self.current, True)
            self.saved.setText("Cerco il logo…")

    def _logo_pick(self):
        self._flush()
        if self.current is None:
            return
        path = QFileDialog.getOpenFileName(self, "Logo del sito", os.path.expanduser("~"),
                                           "Immagini (*.png *.jpg *.jpeg *.svg *.ico *.webp *.gif)")[0]
        if not path:
            return
        from tkftp import logos
        try:
            logos.set_manual(self.current, path)
        except Exception as exc:  # noqa: BLE001
            tk_choice(self, APP_TITLE, f"Non riesco a usare questa immagine:\n{exc}", [("OK", "accent")], "warn")
            return
        if self.actions.get("logo_changed"):
            self.actions["logo_changed"](self.current.id)
        self.logo_changed(self.current.id)

    def _logo_hint(self):
        """Suggerimento discreto accanto al campo quando la ricerca automatica non ha trovato il logo."""
        from tkftp import logos
        failed = self.current is not None and logos.last_failed(self.current.id)
        self.l_web.setText("SITO WEB (PER IL LOGO)" + ("  ·  LOGO NON TROVATO: SCRIVI L'INDIRIZZO DEL SITO" if failed else ""))
        self.l_web.setStyleSheet("color:#b45309;" if failed else "")

    def logo_changed(self, site_id):
        """Il logo di un sito è cambiato: ridisegna le sue icone."""
        from tkftp.style import clear_badge_cache
        clear_badge_cache(site_id)

        def walk(node):
            for i in range(node.childCount()):
                c = node.child(i)
                kind, val = c.data(0, Qt.ItemDataRole.UserRole)
                if kind == "site" and val == site_id and self.store.get(val):
                    c.setIcon(0, avatar(self.store.get(val)))
                walk(c)
        walk(self.tree.invisibleRootItem())
        if self.current is not None and self.current.id == site_id:
            self.big.setPixmap(site_badge(self.current, 48))
            self._logo_hint()
            if self.saved.text() == "Cerco il logo…":
                self.saved.setText("Logo aggiornato")

    def _pick_key(self):
        start = os.path.dirname(self.f_key.text()) if self.f_key.text() else os.path.join(os.path.expanduser("~"), ".ssh")
        path = QFileDialog.getOpenFileName(self, "File della chiave privata", start if os.path.isdir(start) else "")[0]
        if path:
            self.f_key.setText(os.path.normpath(path))
            self._changed()

    def _pick_ldir(self):
        path = QFileDialog.getExistingDirectory(self, "Cartella locale iniziale", self.f_ldir.text() or os.path.expanduser("~"))
        if path:
            self.f_ldir.setText(os.path.normpath(path))
            self._changed()

    def _connect(self):
        self._flush()
        s = self.current
        if s is None:
            return
        if not s.host:
            tk_choice(self, APP_TITLE, "Scrivi l'indirizzo del server (host).", [("OK", "accent")], "warn")
            self.f_host.setFocus()
            return
        self.accept()
        self.connect_site.emit(s)

    def accept(self):
        self._flush()
        super().accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 90:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
