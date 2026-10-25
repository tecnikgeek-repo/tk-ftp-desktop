"""Finestra principale di tk-ftp: connessione rapida in testata, pannello del computer e del server affiancati,
coda trasferimenti e registro in basso. Tutto il lavoro di rete gira fuori dal thread dell'interfaccia."""
import collections
import html
import io
import os
import sys
import threading
import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tkftp import (APP_TITLE, URL_SORGENTE, VERSION, editwatch, filezilla, listing, logos, pro, remote, style, sync,
                   transfers, updater)
from tkftp.util import conta
from tkftp.tk_licenza_qt import benvenuto, dentro_lo_schermo, testata_compatta
from tkftp.dialogs import (
    AboutDialog, CertDialog, ChmodDialog, EditChangedDialog, HostKeyDialog, OverwriteDialog, SettingsDialog,
    UpdateDialog,
)
from tkftp.models import QUEUE_TABS, ProgressDelegate, QueueModel
from tkftp.panes import HintTreeView, HintTreeWidget, LocalPane, RemotePane
from tkftp.session import RemoteSession, count_plan, delete_plan, scan_tree
from tkftp.sitemanager import SiteManager
from tkftp.sites import PROTOCOL_SHORT, Site, SiteStore, default_port, get_password, set_password
from tkftp.style import (
    ACCENT_D, GRAY_500, NAVY, Bridge, TkProgress, check_png, ic, logo_tile, render_icon, shadow, shadow_holder, stylesheet,
    text_btn, tk_choice, tk_info, tk_input, tk_warn, tool_btn,
)
from tkftp.util import (
    APP_ROOT, IS_WIN, Settings, clean_edit_dir, data_dir, ensure_folder_shortcut, human_size, human_speed,
    is_dangerous, is_installed, is_text_file, log_dir, open_in_editor, open_path, reveal, update_uninstall_entry,
)

# frasi in più nella finestra di benvenuto: cosa va in rete e cosa resta sul computer
RIGHE_BENVENUTO = (
    "tk-ftp si collega solo ai server che scegli tu. In più va in rete per cercare gli aggiornamenti "
    "(su pietrodefilippis.it) e, se l'opzione è accesa nelle Impostazioni, per prendere il logo dei tuoi siti dal "
    "loro sito web.",
    "Le password dei siti stanno in " + ("Gestione credenziali di Windows" if IS_WIN else "Portachiavi del Mac") +
    ", mai in chiaro su disco.",
)

LOG_COLORS = {"status": "#cbd5e1", "cmd": "#f2b453", "resp": "#86efac", "error": "#fca5a5"}
LOG_LABEL = {"status": "Stato", "cmd": "Comando", "resp": "Risposta", "error": "Errore"}
QUICK_PROTOCOLS = [("ftp", "FTP"), ("ftps", "FTPS"), ("ftps-implicit", "FTPS impl."), ("sftp", "SFTP"),
                   ("ftp-plain", "FTP chiaro")]


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.store = SiteStore()
        self.bridge = Bridge()
        self.sync = sync.SharedSync(self.store, settings)
        self.session = None
        self.site = None
        self.quick = False
        self.closing_for_update = False
        self.manifest = None
        self._log_lock = threading.Lock()
        self._log_buf = collections.deque()
        self._tm_dirty = threading.Event()
        self.edits = editwatch.EditWatcher()
        self._edit_items = {}
        self._sync_pending = False
        self.tm = transfers.TransferManager(
            parallel=int(settings.value("parallel", 2)), ask_overwrite=self._ask_overwrite_thread,
            log=self._log_thread, changed=self._tm_changed, policy=settings.value("policy", "ask"),
            ask_changed=self._ask_changed_thread)
        import queue
        style.LOGOS["enabled"] = bool(settings.value("show_logos", True))
        self.rete = False  # niente rete (loghi, aggiornamenti) prima della risposta al benvenuto: vedi avvio()
        self._open_sm = None
        self._logo_q = queue.Queue()
        self._logo_pending = set()
        threading.Thread(target=self._logo_worker, daemon=True, name="loghi").start()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(render_icon(256)))
        self.resize(1440, 900)
        self._build()
        # su finestre strette la testata perde le scritte (restano le icone); la finestra non esce dallo schermo (MacBook)
        testata_compatta(self, [(self.qc_label, ""), (self.qc_go, ""), (self.siti_btn, ""), (self.fz_btn, "")], 1300)
        self._restore()
        dentro_lo_schermo(self)
        self.store.listeners.append(self._store_changed)
        for keys, fn in (("Ctrl+S", self.open_sites), ("F5", self._refresh_focused), ("Ctrl+L", self.qc_host.setFocus),
                         ("Ctrl+Q", self.close)):
            QShortcut(QKeySequence(keys), self, activated=fn)
        self.t_queue = QTimer(self, interval=300, timeout=self._refresh_queue)
        self.t_queue.start()
        self.t_log = QTimer(self, interval=120, timeout=self._flush_log)
        self.t_log.start()
        self.t_edit = QTimer(self, interval=1000, timeout=self._poll_edits)
        self.t_edit.start()
        self.t_sync = QTimer(self, interval=30000, timeout=self._check_shared)
        self.t_sync.start()
        self.t_sync_write = QTimer(self, singleShot=True, interval=1200, timeout=self._write_shared)
        self.t_remote_refresh = QTimer(self, singleShot=True, interval=700,
                                       timeout=lambda: self.remote_pane.refresh() if self.connected else None)
        QTimer.singleShot(300, self._check_shared)
        self.t_logos = QTimer(self, singleShot=True, interval=1500, timeout=self._request_all_logos)
        QTimer.singleShot(1200, self.ensure_shortcut)
        # copie della modifica al volo rimaste da sessioni vecchie (non più seguite): via, in sottofondo
        threading.Thread(target=clean_edit_dir, daemon=True, name="pulizia-modifica").start()

    def avvio(self):
        """Con la finestra aperta: benvenuto (solo la prima volta), poi rete, FileZilla e invito al caffè."""
        lic = pro.licenza()
        if "--selftest" not in sys.argv:
            benvenuto(lic, APP_TITLE, URL_SORGENTE, parent=self, logo=logo_tile(96), righe_extra=RIGHE_BENVENUTO)
        self.rete = True
        QTimer.singleShot(300, self._first_run)
        QTimer.singleShot(1000, self._request_all_logos)
        QTimer.singleShot(2000, lambda: self.check_updates(False))
        if lic is not None and "--selftest" not in sys.argv:
            lic.avvia()  # segnale giornaliero, solo col consenso dato nel benvenuto o nelle Impostazioni
        pro.invito(self)

    # ================================================================== interfaccia
    def _build(self):
        central = QWidget(objectName="canvas")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(0)

        header = QFrame(objectName="header")
        shadow(header, 24, 6, 70)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(logo_tile(44))
        hl.addWidget(icon)
        hl.addSpacing(4)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel(APP_TITLE, objectName="brand"))
        col.addWidget(QLabel(f"Versione {VERSION}", objectName="ver"))
        hl.addLayout(col)
        hl.addSpacing(14)

        qc = QFrame(objectName="qc")
        ql = QHBoxLayout(qc)
        ql.setContentsMargins(10, 7, 7, 7)
        ql.setSpacing(6)
        self.qc_label = QLabel("CONNESSIONE RAPIDA", objectName="qcl")
        ql.addWidget(self.qc_label)
        self.qc_proto = QComboBox(objectName="qc")
        for k, lab in QUICK_PROTOCOLS:
            self.qc_proto.addItem(lab, k)
        self.qc_proto.setFixedWidth(104)
        self.qc_proto.setToolTip("Protocollo")
        self.qc_host = QLineEdit(objectName="qc")
        self.qc_host.setPlaceholderText("Indirizzo del server")
        self.qc_host.setToolTip("Es. ftp.miosito.it, oppure sftp://utente@host:porta/cartella")
        self.qc_host.setMinimumWidth(100)
        hist = list(self.settings.value("quick_hosts", []) or [])
        comp = QCompleter(hist, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.qc_host.setCompleter(comp)
        self.qc_user = QLineEdit(objectName="qc")
        self.qc_user.setPlaceholderText("Utente")
        self.qc_user.setFixedWidth(90)
        self.qc_pass = QLineEdit(objectName="qc")
        self.qc_pass.setPlaceholderText("Password")
        self.qc_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.qc_pass.setFixedWidth(90)
        self.qc_port = QLineEdit(objectName="qc")
        self.qc_port.setPlaceholderText("Porta")
        self.qc_port.setFixedWidth(56)
        for w in (self.qc_proto, self.qc_host, self.qc_user, self.qc_pass, self.qc_port):
            ql.addWidget(w, 1 if w is self.qc_host else 0)
        for w in (self.qc_host, self.qc_user, self.qc_pass, self.qc_port):
            w.returnPressed.connect(self.quick_connect)
        self.qc_go = text_btn("plug", "Connetti", self.quick_connect, "#fff", "accent")
        self.qc_go.setMinimumHeight(32)
        ql.addWidget(self.qc_go)
        hl.addWidget(qc, 1)
        hl.addSpacing(6)

        self.update_btn = text_btn("refresh", "Aggiorna", self.show_update_dialog, "#fff", "accent")
        self.update_btn.hide()
        hl.addWidget(self.update_btn)
        self.siti_btn = text_btn("server", "Siti", self.open_sites, "#fff", "ghost", "Gestore siti (Ctrl+S)")
        hl.addWidget(self.siti_btn)
        self.fz_btn = text_btn("swap", "FileZilla", None, "#fff", "ghost", "Importa ed esporta i siti di FileZilla")
        m = QMenu(self)
        m.addAction(QAction(ic("import", NAVY, 16), "Importa da FileZilla installato", self, triggered=self.import_installed))
        m.addAction(QAction(ic("open", NAVY, 16), "Importa un file sitemanager.xml…", self, triggered=self.import_file))
        m.addSeparator()
        m.addAction(QAction(ic("export", NAVY, 16), "Esporta per FileZilla…", self, triggered=self.export_file))
        m.addSeparator()
        m.addAction(QAction(ic("share", NAVY, 16), "Siti condivisi col telefono…", self, triggered=self.open_settings))
        self.fz_btn.setMenu(m)
        hl.addWidget(self.fz_btn)
        hl.addWidget(tool_btn("gear", "Impostazioni", self.open_settings, "#ffffff", "ghost"))
        hl.addWidget(tool_btn("info", "Informazioni e aggiornamenti", self.act_about, "#ffffff", "ghost"))
        for b in header.findChildren(QPushButton):
            if b.objectName() == "ghost" and not b.text():
                b.setFixedSize(38, 38)
        root.addWidget(shadow_holder(header, 16, 6, 16, 18))

        # ogni card sta in un contenitore con margini: l'ombra sfuma tutta attorno agli angoli arrotondati
        # (senza, lo splitter la tagliava dritta sul bordo della card)
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.setHandleWidth(2)
        self.hsplit = QSplitter()
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.setHandleWidth(2)
        self.local_pane = LocalPane(bool(self.settings.value("show_hidden", False)))
        self.remote_pane = RemotePane()
        self.hsplit.addWidget(shadow_holder(self.local_pane, 14, 6, 10, 16))
        self.hsplit.addWidget(shadow_holder(self.remote_pane, 10, 6, 14, 16))
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(shadow_holder(self._bottom(), 14, 6, 14, 18))
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 1)
        self.vsplit.setSizes([600, 250])
        root.addWidget(self.vsplit, 1)
        self.setCentralWidget(central)

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet(f"color:{GRAY_500}; padding-right:16px;")
        self.speed_label.setMinimumWidth(230)  # «↑ 2 ↓ 0 · 14,7 MB/s» intero, non tagliato sul bordo
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar().addPermanentWidget(self.speed_label)
        self.statusBar().setSizeGripEnabled(False)

        # collegamenti dei pannelli
        lp, rp = self.local_pane, self.remote_pane
        lp.on_file_activated = self._local_activated
        lp.btn_mkdir.clicked.connect(self.local_mkdir)
        lp.view.customContextMenuRequested.connect(self._local_menu)
        lp.view.dropped.connect(self._drop_on_local)
        rp.on_file_activated = self._remote_activated
        rp.navigate.connect(self.remote_list)
        rp.want_list.connect(lambda p, tree: self.remote_list(p, tree_only=tree))
        rp.btn_mkdir.clicked.connect(self.remote_mkdir)
        rp.view.customContextMenuRequested.connect(self._remote_menu)
        rp.view.dropped.connect(self._drop_on_remote)
        rp.btn_disconnect.clicked.connect(self.disconnect)
        rp.btn_cancel_connect.clicked.connect(self.disconnect)
        rp.btn_save_site.clicked.connect(self.save_quick_site)
        rp.btn_open_sites.clicked.connect(self.open_sites)
        rp.btn_import_fz.clicked.connect(self.import_installed)
        for view, fn in ((lp.view, self._local_key), (rp.view, self._remote_key)):
            view.installEventFilter(self)
            view._keyfn = fn
        for pane, key in ((lp, "cols_local"), (rp, "cols_remote")):
            saved = self.settings.value(key)
            if isinstance(saved, list):
                pane.view.set_hidden_columns(saved)
            widths = self.settings.value(key.replace("cols_", "colw_"))
            if isinstance(widths, dict):
                pane.view.set_user_widths(widths)
            pane.view.columns_changed.connect(
                lambda p=pane, k=key: (self.settings.setValue(k, p.view.hidden_columns()),
                                       self.settings.setValue(k.replace("cols_", "colw_"),
                                                              {str(c): w for c, w in p.view.user_widths.items()})))
        rp.model.drag_out = self._drag_out
        self._refresh_recent()

    def _bottom(self):
        card = QFrame(objectName="card")
        shadow(card, 20, 4, 38)
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tabs = {}
        for i, (key, icon_name, label) in enumerate((("coda", "swap", "Coda"), ("falliti", "alert", "Non riusciti"),
                                                     ("completati", "check", "Completati"),
                                                     ("modifica", "edit", "In modifica"),
                                                     ("registro", "terminal", "Registro"))):
            b = QPushButton(label, objectName="tab")
            b.setCheckable(True)
            b.setIcon(ic(icon_name, GRAY_500, 16))
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.toggled.connect(lambda on, k=key, btn=b, n=icon_name: self._tab_toggled(k, on, btn, n))
            self.tab_group.addButton(b, i)
            bar.addWidget(b)
            self.tabs[key] = (b, label)
        bar.addStretch(1)
        self.b_retry = text_btn("retry", "Riprova", self._retry_failed, NAVY, "", "Rimetti in coda i non riusciti")
        self.b_cancel_all = text_btn("stop", "Annulla tutto", self._cancel_all, NAVY, "danger")
        self.b_clear = text_btn("broom", "Pulisci", self._clear_tab, NAVY, "", "Togli dalla lista")
        self.b_stop_edit = text_btn("close", "Smetti di seguire", self._stop_edit, NAVY, "")
        self.b_upload_edit = text_btn("upload", "Carica ora", self._upload_edit_now, NAVY, "")
        self.b_clear_log = text_btn("broom", "Svuota", lambda: self.log_view.clear(), NAVY, "")
        for b in (self.b_retry, self.b_cancel_all, self.b_clear, self.b_upload_edit, self.b_stop_edit, self.b_clear_log):
            b.setMinimumHeight(32)
            bar.addWidget(b)
        v.addLayout(bar)

        self.bstack = QStackedWidget()
        self.qviews = {}
        hints = {"coda": "Nessun trasferimento in coda · trascina i file da un pannello all'altro",
                 "falliti": "Nessun trasferimento non riuscito", "completati": "Ancora nessun trasferimento completato"}
        for key in ("coda", "falliti", "completati"):
            qv = HintTreeView(hints[key])
            qm = QueueModel(self.tm, key, qv)
            qv.setModel(qm)
            qv.setRootIsDecorated(False)
            qv.setAlternatingRowColors(True)
            qv.setUniformRowHeights(True)
            qv.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            qv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            qv.setItemDelegateForColumn(3, ProgressDelegate(qv))
            qv.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            qv.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            qv.customContextMenuRequested.connect(lambda pos, v=qv: self._queue_menu(v, pos))
            h = qv.header()
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            h.resizeSection(0, 240)
            h.resizeSection(2, 90)
            h.resizeSection(3, 230)
            h.resizeSection(4, 170)
            h.setStretchLastSection(False)
            h.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
            self.qviews[key] = (qv, qm)
            self.bstack.addWidget(qv)
        self.edit_view = HintTreeWidget("Fai doppio clic su un file del server per modificarlo: quando lo salvi, "
                                        "tk-ftp lo ricarica da solo")
        self.edit_view.setHeaderLabels(["FILE", "SERVER", "STATO", "COPIA LOCALE"])
        self.edit_view.setRootIsDecorated(False)
        self.edit_view.setAlternatingRowColors(True)
        self.edit_view.header().resizeSection(0, 240)
        self.edit_view.header().resizeSection(1, 260)
        self.edit_view.header().resizeSection(2, 220)
        self.edit_view.itemDoubleClicked.connect(lambda it, _c: self._reopen_edit(it))
        self.bstack.addWidget(self.edit_view)
        self.log_view = QPlainTextEdit(objectName="log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFont(QFont("Consolas" if IS_WIN else "Menlo", 9))
        self.bstack.addWidget(self.log_view)
        v.addWidget(self.bstack, 1)
        self.tabs["coda"][0].setChecked(True)
        return card

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # finestre strette (portatili da 1366): via l'etichetta della connessione rapida, i campi restano
        self.qc_label.setVisible(self.width() >= 1480)

    def _tab_toggled(self, key, on, btn, icon_name):
        btn.setIcon(ic(icon_name, "#ffffff" if on else GRAY_500, 16))
        if not on:
            return
        order = ["coda", "falliti", "completati", "modifica", "registro"]
        self.bstack.setCurrentIndex(order.index(key))
        self.b_retry.setVisible(key == "falliti")
        self.b_cancel_all.setVisible(key == "coda")
        self.b_clear.setVisible(key in ("falliti", "completati"))
        self.b_stop_edit.setVisible(key == "modifica")
        self.b_upload_edit.setVisible(key == "modifica")
        self.b_clear_log.setVisible(key == "registro")

    def show_tab(self, key):
        self.tabs[key][0].setChecked(True)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.KeyPress and hasattr(obj, "_keyfn"):
            if obj._keyfn(ev):
                return True
        return super().eventFilter(obj, ev)

    def _restore(self):
        geo = self.settings.value("geometry", "")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        for name in ("hsplit", "vsplit"):
            st = self.settings.value(name, "")
            if st:
                getattr(self, name).restoreState(QByteArray.fromBase64(st.encode()))
        start = self.settings.value("last_local", "") or os.path.expanduser("~")
        self.local_pane.load(start if os.path.isdir(start) else os.path.expanduser("~"))

    # ================================================================== registro
    def _log_thread(self, kind, text):
        with self._log_lock:
            self._log_buf.append((time.strftime("%H:%M:%S"), kind, text))

    def _flush_log(self):
        with self._log_lock:
            items = list(self._log_buf)
            self._log_buf.clear()
        if not items:
            return
        lines = []
        for t, kind, text in items[-800:]:
            col = LOG_COLORS.get(kind, "#e2e8f0")
            if kind == "resp" and text[:1] in ("4", "5"):
                col = LOG_COLORS["error"]
            lines.append(f'<span style="color:#64748b">{t}</span>&nbsp;&nbsp;<span style="color:{col}"><b>'
                         f'{LOG_LABEL.get(kind, kind)}:</b>&nbsp;{html.escape(text)}</span>')
        self.log_view.appendHtml("<br>".join(lines))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def status(self, text, ms=6000):
        self.statusBar().showMessage(text, ms)

    # ================================================================== connessione
    @property
    def connected(self):
        return self.session is not None and self.site is not None and self.remote_pane.stack.currentIndex() == 2

    def quick_connect(self):
        raw = self.qc_host.text().strip()
        if not raw:
            self.qc_host.setFocus()
            return
        proto = self.qc_proto.currentData()
        user = self.qc_user.text().strip()
        port = 0
        path = ""
        low = raw.lower()
        for scheme, p in (("sftp://", "sftp"), ("ftps://", "ftps-implicit"), ("ftpes://", "ftps"), ("ftp://", "ftp")):
            if low.startswith(scheme):
                proto = p
                raw = raw[len(scheme):]
                break
        if "/" in raw:
            raw, path = raw.split("/", 1)
            path = "/" + path
        if "@" in raw:
            u, raw = raw.rsplit("@", 1)
            user = user or u
        if raw.count(":") == 1:
            raw, ps = raw.split(":")
            port = int(ps) if ps.isdigit() else 0
        if self.qc_port.text().strip().isdigit():
            port = int(self.qc_port.text().strip())
        site = Site(name=raw, host=raw, port=port or default_port(proto), protocol=proto, user=user,
                    logon="normal" if user else "anonymous", remote_dir=path)
        hist = [h for h in (self.settings.value("quick_hosts", []) or []) if h != self.qc_host.text().strip()]
        self.settings.setValue("quick_hosts", ([self.qc_host.text().strip()] + hist)[:15])
        self.connect_site(site, self.qc_pass.text(), quick=True)

    def connect_site(self, site, password=None, quick=False):
        self.disconnect(silent=True)
        if password is None:
            password = get_password(site) if site.logon in ("normal", "key") else ""
        self.site = site
        self.quick = quick
        is_key = site.logon == "key"
        self.session = RemoteSession(site, "" if is_key else password, password if is_key else "", self._log_thread)
        self._log_thread("status", f"— {site.title} ({PROTOCOL_SHORT.get(site.protocol)}) —")
        self.remote_pane.show_busy(f"Connessione a {site.title}…")
        self._connect_attempt()

    def _connect_attempt(self):
        sess = self.session
        sess.connect(self.bridge.wrap(lambda home: self._connected(sess, home)),
                     self.bridge.wrap(lambda exc: self._connect_failed(sess, exc)))

    def _connected(self, sess, home):
        if sess is not self.session:
            return
        site = self.site
        if not self.quick:
            self.store.touch(site)
        self.remote_pane.show_connected(site, home, self.quick)
        start = site.remote_dir or home
        self.remote_list(start, fallback=home)
        if site.local_dir and os.path.isdir(site.local_dir):
            self.local_pane.load(site.local_dir)
        self.setWindowTitle(f"{APP_TITLE} — {site.title}")
        self.status(f"Connesso a {site.title}")

    def _connect_failed(self, sess, exc):
        if sess is not self.session:
            return
        site = self.site
        if isinstance(exc, remote.HostKeyQuestion):
            dlg = HostKeyDialog(self, exc)
            dlg.exec()
            if dlg.choice:
                exc.accept()
                return self._connect_attempt()
            return self.disconnect()
        if isinstance(exc, remote.CertQuestion):
            dlg = CertDialog(self, exc)
            dlg.exec()
            if dlg.choice:
                exc.accept()
                return self._connect_attempt()
            return self.disconnect()
        if isinstance(exc, remote.PlainQuestion):
            if tk_choice(self, "Connessione non protetta",
                         f"{exc.host} non accetta connessioni protette (TLS): utente, password e file viaggerebbero "
                         "in chiaro e chi è sulla stessa rete potrebbe leggerli.\n\nContinuo lo stesso? La scelta "
                         "vale per questo server.", [("Annulla", "ghost"), ("Continua in chiaro", "accent")],
                         "warn") == 1:
                exc.accept()
                return self._connect_attempt()
            return self.disconnect()
        if isinstance(exc, remote.NeedPassword):
            phrase = exc.kind == "passphrase"
            r = tk_input(self, "Frase della chiave" if phrase else "Password", str(exc), "", "Connetti", password=True,
                         remember=None if self.quick else ("Ricorda la frase" if phrase else "Ricorda la password"),
                         kind="key" if phrase else "lock")
            if r is None:
                return self.disconnect()
            text, keep = r if isinstance(r, tuple) else (r, False)
            if phrase:
                sess.passphrase = text
            else:
                sess.password = text
            if keep and not self.quick:
                if not phrase and site.logon == "ask":
                    site.logon = "normal"
                    self.store.upsert(site, None)
                try:
                    set_password(site, text)
                except OSError:
                    pass
            return self._connect_attempt()
        msg = remote.friendly_error(exc)
        self._log_thread("error", msg)
        if isinstance(exc, remote.AuthError) and site.logon in ("normal", "ask"):
            r = tk_input(self, "Accesso negato", f"{msg}\nRiprova con un'altra password per {site.user}@{site.host}:",
                         "", "Riprova", password=True,
                         remember=None if self.quick else "Ricorda la password", kind="lock")
            if r is not None:
                text, keep = r if isinstance(r, tuple) else (r, False)
                sess.password = text
                if keep and not self.quick:
                    try:
                        set_password(site, text)
                    except OSError:
                        pass
                return self._connect_attempt()
            return self.disconnect()
        self.disconnect()
        tk_warn(self, f"Connessione a {site.title} non riuscita", msg)

    def disconnect(self, silent=False):
        if self.session is not None:
            self.session.close()
        self.session = None
        self.site = None
        self.quick = False
        self.remote_pane.show_welcome()
        self.setWindowTitle(APP_TITLE)
        self._refresh_recent()
        if not silent:
            self.status("Disconnesso")

    def save_quick_site(self):
        if not self.site:
            return
        s = self.site
        self.store.upsert(s, self.session.password or None if self.session else None)
        self.quick = False
        self.remote_pane.btn_save_site.hide()
        self.status(f"«{s.title}» salvato nel gestore siti")

    def _refresh_recent(self):
        sites = self.store.recent(6) or sorted(self.store.sites, key=lambda s: s.title.lower())[:6]
        self.remote_pane.set_recent(sites, lambda s: self.connect_site(s))

    # ================================================================== elenco remoto
    def remote_list(self, path, tree_only=False, fallback=None, keep=False):
        if self.session is None or not path:
            return
        sess = self.session

        def ok(entries):
            if sess is not self.session:
                return
            if tree_only:
                self.remote_pane.fill_tree_only(path, entries)
            else:
                self.remote_pane.show_listing(path, entries, keep=keep)

        def err(exc):
            if sess is not self.session:
                return
            if isinstance(exc, (remote.HostKeyQuestion, remote.CertQuestion, remote.NeedPassword, remote.PlainQuestion)):
                return self._connect_failed(sess, exc)
            msg = remote.friendly_error(exc)
            self._log_thread("error", f"{path}: {msg}")
            if fallback and fallback != path:
                self.remote_list(fallback)
                return
            if not tree_only:
                self.remote_pane.footer.setText(f"Non riesco ad aprire {path}: {msg}")
                self.remote_pane.path_edit.setText(self.remote_pane.path)
        sess.submit(lambda c: c.listdir(path), self.bridge.wrap(ok), self.bridge.wrap(err))

    def _remote_job(self, fn, done_msg="", refresh=True):
        if self.session is None:
            return
        sess = self.session

        def ok(_r):
            if done_msg:
                self.status(done_msg)
            if refresh and sess is self.session:
                self.remote_pane.refresh()

        def err(exc):
            msg = remote.friendly_error(exc)
            self._log_thread("error", msg)
            tk_warn(self, APP_TITLE, msg)
            if refresh and sess is self.session:
                self.remote_pane.refresh()
        sess.submit(fn, self.bridge.wrap(ok), self.bridge.wrap(err))

    # ================================================================== trasferimenti
    def _creds(self):
        s = self.session
        return (self.site, s.password, s.passphrase) if s else (None, "", "")

    def upload_paths(self, paths, remote_dir=None):
        if not self.connected:
            tk_info(self, APP_TITLE, "Prima collegati a un server: poi puoi caricare i file.")
            return
        remote_dir = remote_dir or self.remote_pane.path
        site, pw, pp = self._creds()
        items = []
        for p in paths:
            p = os.path.normpath(p)
            name = os.path.basename(p.rstrip("\\/"))
            if os.path.isdir(p):
                items.append(transfers.Item("up", p, listing.join(remote_dir, name), site, pw, pp, is_dir=True))
            elif os.path.isfile(p):
                st = os.stat(p)
                items.append(transfers.Item("up", p, listing.join(remote_dir, name), site, pw, pp, st.st_size,
                                            mtime=st.st_mtime))
        if items:
            self.tm.add(items)
            self.show_tab("coda")
            self.status(f"{conta(len(items), 'elemento', 'elementi')} in coda per il caricamento")

    def download_entries(self, entries, local_dir=None):
        """entries = [(percorso remoto, Entry)]"""
        if not self.connected:
            return
        local_dir = local_dir or self.local_pane.path
        if not local_dir:
            tk_info(self, APP_TITLE, "Scegli prima una cartella del computer a sinistra.")
            return
        site, pw, pp = self._creds()
        items = []
        for path, e in entries:
            loc = os.path.join(local_dir, transfers._safe_local(e.name))
            items.append(transfers.Item("down", loc, path, site, pw, pp, e.size, is_dir=e.is_dir, mtime=e.mtime))
        if items:
            self.tm.add(items)
            self.show_tab("coda")
            self.status(f"{conta(len(items), 'elemento', 'elementi')} in coda per lo scaricamento")

    def _drag_out(self, payload):
        """Trascinamento dal pannello del server verso Esplora file/Finder: al rilascio scarica i file (e le cartelle)
        in una cartella temporanea passando dalla coda, tiene viva l'interfaccia e restituisce i percorsi che chi
        riceve copierà dove sono stati lasciati."""
        import tempfile
        import uuid
        from PySide6.QtCore import QEventLoop
        if not self.connected or not payload:
            return []
        tag = uuid.uuid4().hex[:10]
        base = os.path.join(tempfile.gettempdir(), "tk-ftp-trascina", tag)
        os.makedirs(base, exist_ok=True)
        site, pw, pp = self._creds()
        items, out = [], []
        for d in payload:
            name = transfers._safe_local(listing.basename(d["path"]))
            loc = os.path.join(base, name)
            out.append(loc)
            items.append(transfers.Item("down", loc, d["path"], site, pw, pp, int(d.get("size") or 0),
                                        is_dir=bool(d.get("is_dir")), mtime=float(d.get("mtime") or 0),
                                        force="overwrite", tag=tag))
        self.tm.add(items)
        self.show_tab("coda")
        self.status(f"Scarico {conta(len(items), 'elemento trascinato', 'elementi trascinati')}…", 0)
        loop = QEventLoop()
        t = QTimer(interval=150)
        t.timeout.connect(lambda: loop.quit() if not self.tm.group_pending(tag) else None)
        t.start()
        loop.exec()
        t.stop()
        bad = [it for it in self.tm.group_items(tag) if it.status != transfers.DONE]
        self.status("Trascinamento: " + (f"{conta(len(bad), 'file non riuscito', 'file non riusciti')}" if bad
                                         else "file pronti, li copia Esplora file"))
        return [p for p in out if os.path.exists(p)]

    def _ask_overwrite_thread(self, item, src, dst):
        return self.bridge.call_blocking(lambda: OverwriteDialog.ask(self, item, src, dst))

    def _tm_changed(self, item):
        self._tm_dirty.set()
        if item.status in (transfers.DONE, transfers.FAILED, transfers.CANCELLED, transfers.SKIPPED):
            self.bridge.post(lambda it=item: self._transfer_finished(it))

    def _transfer_finished(self, item):
        w = self._edit_items.pop(item.id, None)
        if w is not None:
            self._edit_transfer_done(w, item)
        if item.status == transfers.DONE and item.direction == "up" and self.connected \
                and item.site is self.site and listing.parent(item.remote).rstrip("/") == self.remote_pane.path.rstrip("/"):
            self.t_remote_refresh.start()
        if item.status == transfers.DONE and item.direction == "up" and item.is_dir and self.connected:
            self.t_remote_refresh.start()

    def _refresh_queue(self):
        if self._tm_dirty.is_set() or self.tm.running_count():
            self._tm_dirty.clear()
            for key, (qv, qm) in self.qviews.items():
                qm.refresh()
            with self.tm.lock:
                counts = {k: sum(1 for it in self.tm.items if it.status in v) for k, v in QUEUE_TABS.items()}
                running = [it for it in self.tm.items if it.status == transfers.RUNNING]
            for key in QUEUE_TABS:
                b, label = self.tabs[key]
                n = counts.get(key)
                b.setText(f"{label}  {n}" if n else label)
            up = sum(1 for it in running if it.direction == "up")
            down = len(running) - up
            speed = sum(it.speed for it in running)
            txt = f"↑ {up}   ↓ {down}" + (f"   ·   {human_speed(speed)}" if speed > 0 else "")
            self.speed_label.setText(txt if running else "")
            self.b_cancel_all.setEnabled(bool(counts.get("coda")))

    def _retry_failed(self):
        qv, qm = self.qviews["falliti"]
        sel = [qm.items[i.row()] for i in qv.selectionModel().selectedRows()] or list(qm.items)
        for it in sel:
            self.tm.retry(it)
        self._tm_dirty.set()
        self.show_tab("coda")

    def _cancel_all(self):
        if self.tm.pending_count() and tk_choice(self, "Annullare tutto?", "I trasferimenti in corso e in coda si fermano.",
                                                 [("No", "ghost"), ("Annulla tutto", "accent")], "warn") == 1:
            self.tm.cancel_all()
            self._tm_dirty.set()

    def _clear_tab(self):
        key = "falliti" if self.tabs["falliti"][0].isChecked() else "completati"
        qv, qm = self.qviews[key]
        sel = [qm.items[i.row()] for i in qv.selectionModel().selectedRows()]
        if sel:
            self.tm.remove(sel)
        else:
            self.tm.clear(set(QUEUE_TABS[key]))
        self._tm_dirty.set()

    def _queue_menu(self, qv, pos):
        qm = qv.model()
        rows = sorted({i.row() for i in qv.selectionModel().selectedRows()})
        items = [qm.items[r] for r in rows if r < len(qm.items)]
        if not items:
            return
        m = QMenu(self)
        if any(it.status in (transfers.WAITING, transfers.RUNNING) for it in items):
            m.addAction(QAction(ic("stop", NAVY, 16), "Annulla", self,
                                triggered=lambda: [self.tm.cancel(it) for it in items]))
        if any(it.status in (transfers.FAILED, transfers.CANCELLED, transfers.SKIPPED) for it in items):
            m.addAction(QAction(ic("retry", NAVY, 16), "Riprova", self,
                                triggered=lambda: ([self.tm.retry(it) for it in items], self._tm_dirty.set())))
        m.addAction(QAction(ic("folder", NAVY, 16), "Mostra il file sul computer", self,
                            triggered=lambda: reveal(items[0].local) if os.path.exists(items[0].local)
                            else open_path(os.path.dirname(items[0].local))))
        if any(it.status not in (transfers.RUNNING,) for it in items):
            m.addSeparator()
            m.addAction(QAction(ic("broom", NAVY, 16), "Togli dalla lista", self,
                                triggered=lambda: (self.tm.remove(items), self._tm_dirty.set())))
        m.exec(qv.viewport().mapToGlobal(pos))

    # ================================================================== modifica al volo
    def edit_remote(self, path, entry, ask_script=True):
        if not self.connected:
            return
        if ask_script and is_dangerous(entry.name) and tk_choice(
                self, "È un programma o uno script",
                f"«{entry.name}» è un file che il computer può eseguire. tk-ftp lo apre solo come testo, nel tuo "
                "editor (mai eseguito). Continuo?", [("Annulla", "ghost"), ("Apri come testo", "accent")], "warn") != 1:
            return
        site, pw, pp = self._creds()
        local = editwatch.local_copy_path(site, path)
        w = self.edits.get(local)
        if w is not None and w.busy:
            self.status(f"«{entry.name}» si sta già caricando sul server")
            return
        if w is not None and w.dirty:
            r = tk_choice(self, "Modifiche non caricate",
                          f"La tua copia di «{entry.name}» ha modifiche che non sono ancora sul server. Se lo riscarico "
                          "dal server le perdi.", [("Annulla", "ghost"), ("Riscarica dal server", "ghost"),
                                                   ("Apri la mia copia", "accent")], "warn")
            if r == 2:
                self._reopen_edit_file(w)
            if r != 1:
                return
        os.makedirs(os.path.dirname(local), exist_ok=True)
        it = transfers.Item("down", local, path, site, pw, pp, entry.size, force="overwrite", mtime=entry.mtime)
        it.track = True  # com'è il file sul server dopo lo scaricamento: serve per accorgersi se cambia
        self._edit_items[it.id] = editwatch.Watched(local, path, site, pw, pp)
        self._edit_items[it.id].opening = True
        self.tm.add([it])
        self.status(f"Apro «{entry.name}» per modificarlo…")

    def _edit_transfer_done(self, w, item):
        after = item.remote_after
        if getattr(w, "opening", False):
            if item.status != transfers.DONE:
                tk_warn(self, APP_TITLE, f"Non riesco ad aprire «{w.name}»:\n{item.error or 'scaricamento annullato'}")
                return
            w.opening = False
            w = self.edits.add(editwatch.Watched(w.local, w.remote, w.site, w.password, w.passphrase))
            w.always = self.edits.get(w.local).always
            w.remote_sig = (after.size, after.mtime) if after is not None else (item.done, item.mtime)
            self._reopen_edit_file(w)
            w.state = "Aperto nell'editor"
            self.status(f"«{w.name}» aperto: quando lo salvi, tk-ftp lo ricarica sul server")
        else:
            w.busy = False
            if item.status == transfers.DONE:
                w.base = getattr(w, "pending_sig", w.base)
                w.dirty = w._sig() != w.base
                if after is not None:
                    w.remote_sig = (after.size, after.mtime)
                w.state = "Caricato alle " + time.strftime("%H:%M:%S")
                self.status(f"«{w.name}» ricaricato su {w.site.title}")
            else:
                # resta da caricare («Carica ora» o il prossimo salvataggio): niente domanda ripetuta ogni secondo
                self.edits.accept_current(w)
                w.dirty = True
                w.state = ("Non caricato: il file sul server è cambiato" if item.status == transfers.SKIPPED and
                           item.error else "Caricamento non riuscito: " + (item.error or "annullato"))
                self._log_thread("error", f"{w.name}: {w.state}")
        self._refresh_edits()

    def _ask_changed_thread(self, item, entry):
        """Dal thread del trasferimento: il file sul server è cambiato dopo che l'hai aperto. Sovrascrivo?"""
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(entry.mtime)) if entry.mtime else "data sconosciuta"
        return self.bridge.call_blocking(lambda: tk_choice(
            self, "Il file sul server è cambiato",
            f"«{item.name}» su {item.site.title} è stato modificato dopo che l'hai aperto (ora: {human_size(entry.size)}, "
            f"{when}). Forse l'ha cambiato qualcun altro: se carichi la tua copia, quelle modifiche si perdono.",
            [("Non caricare", "ghost"), ("Sovrascrivi lo stesso", "accent")], "warn") == 1)

    def _poll_edits(self):
        for w in self.edits.poll():
            if w.always or self.settings.value("edit_autoupload", False):
                self._upload_edit(w)
                continue
            w.busy = True
            dlg = EditChangedDialog(self, w.name, w.site.title)
            dlg.exec()
            w.busy = False
            if dlg.choice in ("yes", "always"):
                w.always = dlg.choice == "always"
                self._upload_edit(w)
            else:
                self.edits.accept_current(w)
                w.dirty = True
                w.state = "Modificato, non caricato"
                self._refresh_edits()

    def _upload_edit(self, w):
        w.busy = True
        w.pending_sig = w._sig()
        w.state = "Caricamento…"
        it = transfers.Item("up", w.local, w.remote, w.site, w.password, w.passphrase, os.path.getsize(w.local),
                            force="overwrite")
        it.expect = getattr(w, "remote_sig", None)  # se sul server non è più quello scaricato: si chiede
        it.track = True
        self._edit_items[it.id] = w
        self.tm.add([it])
        self._refresh_edits()

    def _refresh_edits(self):
        self.edit_view.clear()
        for w in self.edits.files.values():
            it = QTreeWidgetItem([w.name, f"{w.site.title}  {w.remote}", w.state, w.local])
            it.setIcon(0, ic("edit", ACCENT_D, 16))
            it.setData(0, Qt.ItemDataRole.UserRole, w.local)
            self.edit_view.addTopLevelItem(it)
        n = len(self.edits.files)
        b, label = self.tabs["modifica"]
        b.setText(f"{label}  {n}" if n else label)

    def _sel_edit(self):
        it = self.edit_view.currentItem()
        return self.edits.get(it.data(0, Qt.ItemDataRole.UserRole)) if it else None

    def _reopen_edit(self, it):
        w = self.edits.get(it.data(0, Qt.ItemDataRole.UserRole))
        if w and os.path.exists(w.local):
            self._reopen_edit_file(w)

    def _reopen_edit_file(self, w):
        try:
            open_in_editor(w.local, self.settings.value("editor", ""))
        except Exception as exc:  # noqa: BLE001
            tk_warn(self, APP_TITLE, f"Non riesco ad aprire l'editor:\n{exc}")

    def _stop_edit(self):
        w = self._sel_edit()
        if w is None:
            return
        if w.dirty and tk_choice(self, "Modifiche non caricate", f"«{w.name}» ha modifiche non ancora sul server. "
                                 "Smetto di seguirlo lo stesso?", [("No", "ghost"), ("Sì, smetti", "accent")], "warn") != 1:
            return
        self.edits.remove(w)
        self._refresh_edits()

    def _upload_edit_now(self):
        w = self._sel_edit()
        if w is not None and not w.busy:
            self._upload_edit(w)

    # ================================================================== pannello locale
    def _local_activated(self, e):
        path = self.local_pane.join(e.name)
        if self.settings.value("dbl_local", "upload") == "upload" and self.connected:
            self.upload_paths([path])
        else:
            open_path(path)

    def _local_key(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Backspace:
            self.local_pane.go_up()
        elif k == Qt.Key.Key_Delete:
            self.local_delete()
        elif k == Qt.Key.Key_F2:
            self.local_rename()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            ents = self.local_pane.view.selected_entries()
            if len(ents) == 1:
                self.local_pane._activated(ents[0])
        else:
            return False
        return True

    def _local_menu(self, pos):
        sel = self.local_pane.selected_paths()
        m = QMenu(self)
        if sel:
            a = QAction(ic("upload", ACCENT_D, 16), "Carica sul server", self,
                        triggered=lambda: self.upload_paths([p for p, _ in sel]))
            a.setEnabled(self.connected)
            m.addAction(a)
            if len(sel) == 1:
                m.addAction(QAction(ic("open", NAVY, 16), "Apri", self, triggered=lambda: open_path(sel[0][0])))
                m.addAction(QAction(ic("folder", NAVY, 16), "Mostra nella cartella", self,
                                    triggered=lambda: reveal(sel[0][0])))
            m.addSeparator()
        m.addAction(QAction(ic("folder-plus", NAVY, 16), "Nuova cartella", self, triggered=self.local_mkdir))
        if len(sel) == 1:
            m.addAction(QAction(ic("edit", NAVY, 16), "Rinomina (F2)", self, triggered=self.local_rename))
        if sel:
            m.addAction(QAction(ic("trash", "#b91c1c", 16), "Sposta nel cestino (Canc)", self, triggered=self.local_delete))
            m.addSeparator()
            m.addAction(QAction(ic("copy", NAVY, 16), "Copia percorso", self,
                                triggered=lambda: QGuiApplication.clipboard().setText("\n".join(p for p, _ in sel))))
        m.addAction(QAction(ic("refresh", NAVY, 16), "Aggiorna (F5)", self, triggered=self.local_pane.refresh))
        m.exec(self.local_pane.view.viewport().mapToGlobal(pos))

    def local_mkdir(self):
        if not self.local_pane.path:
            return
        name = tk_input(self, "Nuova cartella", f"Dentro {self.local_pane.path}", "Nuova cartella", "Crea")
        if name and name.strip():
            try:
                os.mkdir(os.path.join(self.local_pane.path, name.strip()))
            except OSError as exc:
                tk_warn(self, APP_TITLE, f"Non riesco a creare la cartella:\n{exc.strerror or exc}")
            self.local_pane.refresh()

    def local_rename(self):
        sel = self.local_pane.selected_paths()
        if len(sel) != 1:
            return
        path, e = sel[0]
        name = tk_input(self, "Rinomina", f"Nuovo nome per «{e.name}»", e.name, "Rinomina")
        if name and name.strip() and name.strip() != e.name:
            dst = os.path.join(os.path.dirname(path), name.strip())
            if os.path.exists(dst) and name.strip().lower() != e.name.lower():
                tk_warn(self, APP_TITLE, f"Nella cartella c'è già «{name.strip()}»: scegli un altro nome.")
                return
            try:
                os.rename(path, dst)  # sul Mac sostituirebbe in silenzio un file che c'è già: controllato sopra
            except OSError as exc:
                tk_warn(self, APP_TITLE, f"Non riesco a rinominare:\n{exc.strerror or exc}")
            self.local_pane.refresh()

    def local_delete(self):
        from PySide6.QtCore import QFile
        sel = self.local_pane.selected_paths()
        if not sel:
            return
        what = f"«{sel[0][1].name}»" if len(sel) == 1 else f"{len(sel)} elementi"
        if tk_choice(self, "Spostare nel cestino?", f"{what} dal computer (puoi " + ("recuperarlo" if len(sel) == 1 else "recuperarli") + " dal cestino).",
                     [("Annulla", "ghost"), ("Sposta nel cestino", "accent")], "warn") != 1:
            return
        bad = []
        for p, _e in sel:
            r = QFile.moveToTrash(p)
            if not (r[0] if isinstance(r, tuple) else r):
                bad.append(os.path.basename(p))
        if bad:
            tk_warn(self, APP_TITLE, "Non riesco a spostare nel cestino:\n" + "\n".join(bad))
        self.local_pane.refresh()

    def _drop_on_local(self, data, target):
        if "remote" not in data:
            return
        folder = self.local_pane.join(target.name) if target is not None and target.name != ".." else self.local_pane.path
        if target is not None and target.name == "..":
            folder = os.path.dirname(self.local_pane.path.rstrip("\\/"))
        ents = [(d["path"], listing.Entry(listing.basename(d["path"]), d["is_dir"], d.get("size", 0), d.get("mtime", 0)))
                for d in data["remote"]]
        self.download_entries(ents, folder)

    # ================================================================== pannello remoto
    def _remote_activated(self, e):
        path = listing.join(self.remote_pane.path, e.name)
        if self.settings.value("dbl_remote", "edit") == "edit" and is_text_file(e.name):
            self.edit_remote(path, e)
        else:
            # col doppio clic si apre al volo solo un file di testo; programmi, script, immagini, archivi…
            # si scaricano e basta (per modificarli: tasto destro → Modifica al volo)
            self.download_entries([(path, e)])

    def _remote_key(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Backspace:
            self.remote_pane.go_up()
        elif k == Qt.Key.Key_Delete:
            self.remote_delete()
        elif k == Qt.Key.Key_F2:
            self.remote_rename()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            ents = self.remote_pane.view.selected_entries()
            if len(ents) == 1:
                self.remote_pane._activated(ents[0])
        else:
            return False
        return True

    def _remote_menu(self, pos):
        if not self.connected:
            return
        sel = self.remote_pane.selected_paths()
        files = [(p, e) for p, e in sel if not e.is_dir]
        m = QMenu(self)
        if sel:
            m.addAction(QAction(ic("download", "#2563eb", 16), "Scarica", self, triggered=lambda: self.download_entries(sel)))
            if len(files) == 1 and len(sel) == 1:
                m.addAction(QAction(ic("edit", ACCENT_D, 16), "Modifica al volo", self,
                                    triggered=lambda: self.edit_remote(*files[0])))
            m.addSeparator()
        m.addAction(QAction(ic("folder-plus", NAVY, 16), "Nuova cartella", self, triggered=self.remote_mkdir))
        m.addAction(QAction(ic("file-plus", NAVY, 16), "Nuovo file", self, triggered=self.remote_new_file))
        if len(sel) == 1:
            m.addAction(QAction(ic("edit", NAVY, 16), "Rinomina (F2)", self, triggered=self.remote_rename))
        if sel:
            m.addAction(QAction(ic("lock", NAVY, 16), "Permessi…", self, triggered=self.remote_chmod))
            m.addAction(QAction(ic("trash", "#b91c1c", 16), "Elimina (Canc)", self, triggered=self.remote_delete))
            m.addSeparator()
            m.addAction(QAction(ic("copy", NAVY, 16), "Copia percorso", self,
                                triggered=lambda: QGuiApplication.clipboard().setText("\n".join(p for p, _ in sel))))
            m.addAction(QAction(ic("link", NAVY, 16), "Copia indirizzo (URL)", self,
                                triggered=lambda: QGuiApplication.clipboard().setText("\n".join(self._url(p) for p, _ in sel))))
        m.addAction(QAction(ic("refresh", NAVY, 16), "Aggiorna (F5)", self, triggered=self.remote_pane.refresh))
        m.exec(self.remote_pane.view.viewport().mapToGlobal(pos))

    def _url(self, path):
        s = self.site
        scheme = {"sftp": "sftp", "ftps-implicit": "ftps"}.get(s.protocol, "ftp")
        port = "" if s.port == default_port(s.protocol) else f":{s.port}"
        user = f"{s.user}@" if s.user else ""
        return f"{scheme}://{user}{s.host}{port}{path}"

    def remote_mkdir(self):
        if not self.connected:
            return
        name = tk_input(self, "Nuova cartella sul server", f"Dentro {self.remote_pane.path}", "nuova-cartella", "Crea")
        if name and name.strip():
            p = listing.join(self.remote_pane.path, name.strip())
            self._remote_job(lambda c: c.mkdir(p), f"Cartella «{name.strip()}» creata")

    def remote_new_file(self):
        if not self.connected:
            return
        name = tk_input(self, "Nuovo file sul server", f"Dentro {self.remote_pane.path}", "nuovo.txt", "Crea e modifica")
        if not name or not name.strip():
            return
        name = name.strip()
        p = listing.join(self.remote_pane.path, name)
        sess = self.session

        def make(c):
            # mai sopra un file che c'è già: «Nuovo file» lo azzererebbe
            if c.stat(p) is not None:
                raise remote.RemoteError(f"Sul server c'è già «{name}»: scegli un altro nome (per modificare quello "
                                         "che c'è, fai doppio clic sul file).")
            c.upload(io.BytesIO(b""), p)

        def ok(_r):
            if sess is self.session:
                self.remote_pane.refresh()
                self.edit_remote(p, listing.Entry(name, False, 0, time.time()))
        sess.submit(make, self.bridge.wrap(ok), self.bridge.wrap(lambda e: tk_warn(self, APP_TITLE, remote.friendly_error(e))))

    def remote_rename(self):
        sel = self.remote_pane.selected_paths()
        if len(sel) != 1 or self.session is None:
            return
        path, e = sel[0]
        name = tk_input(self, "Rinomina sul server", f"Nuovo nome per «{e.name}»", e.name, "Rinomina")
        if not name or not name.strip() or name.strip() == e.name:
            return
        new = name.strip()
        dst = listing.join(listing.parent(path), new)
        done = f"«{e.name}» rinominato in «{new}»"
        sess = self.session
        if new.lower() == e.name.lower():  # cambia solo maiuscole/minuscole: è lo stesso file
            self._remote_job(lambda c: c.rename(path, dst), done)
            return

        def exists(st):
            if sess is not self.session:
                return
            if st is None:
                return self._remote_job(lambda c: c.rename(path, dst), done)
            if st.is_dir or e.is_dir:
                return tk_warn(self, APP_TITLE, f"Sul server c'è già «{new}»: scegli un altro nome.")
            if tk_choice(self, "Il nome è già usato", f"Sul server c'è già un file «{new}» "
                         f"({human_size(st.size)}). Se rinomini «{e.name}», quello che c'è viene sostituito e si perde.",
                         [("Annulla", "ghost"), ("Sostituisci", "accent")], "warn") == 1:
                self._remote_job(lambda c: _rename_over(c, path, dst), done)
        sess.submit(lambda c: c.stat(dst), self.bridge.wrap(exists),
                    self.bridge.wrap(lambda exc: tk_warn(self, APP_TITLE, remote.friendly_error(exc))))

    def remote_delete(self):
        sel = self.remote_pane.selected_paths()
        if not sel or not self.connected:
            return
        what = f"«{sel[0][1].name}»" if len(sel) == 1 else f"{len(sel)} elementi"
        dirs = any(e.is_dir and not e.is_link for _, e in sel)
        site = self.site
        if not dirs:
            if tk_choice(self, "Eliminare dal server?", f"{what} da {site.title}. Non si può annullare.",
                         [("Annulla", "ghost"), ("Elimina", "accent")], "warn") != 1:
                return
            self.status("Eliminazione in corso…", 0)
            self._remote_job(lambda c: delete_plan(c, [(p, "file") for p, _e in sel]),
                             ("Eliminato " if len(sel) == 1 else "Eliminati ") + what)
            return
        # cartelle: prima si conta cosa c'è dentro (senza seguire i collegamenti), poi si chiede col numero esatto
        self._scan_then(sel, "Conto gli elementi da eliminare…", lambda plan: self._confirm_delete(plan, what, site))

    def _scan_then(self, sel, msg, then):
        sess = self.session
        if sess is None:
            return
        self.status(msg, 0)

        def scan(c):
            plan = []
            for p, e in sel:
                plan += scan_tree(c, p, e.is_dir and not e.is_link, self._log_thread)
            return plan

        def ok(plan):
            self.statusBar().clearMessage()
            if sess is self.session:
                then(plan)
        sess.submit(scan, self.bridge.wrap(ok),
                    self.bridge.wrap(lambda exc: (self.statusBar().clearMessage(),
                                                  tk_warn(self, APP_TITLE, remote.friendly_error(exc)))))

    def _confirm_delete(self, plan, what, site):
        files, folders = count_plan(plan)
        links = sum(1 for _p, k in plan if k == "link")
        detail = f"{conta(files, 'file', 'file')} e {conta(folders, 'cartella', 'cartelle')}" + (
            f" (di cui {conta(links, 'collegamento', 'collegamenti')}: si toglie solo il collegamento, non quello a cui "
            "punta)" if links else "")
        if tk_choice(self, "Eliminare dal server?", f"{what} da {site.title}: in tutto {detail}. Non si può annullare.",
                     [("Annulla", "ghost"), ("Elimina " + conta(len(plan), "elemento", "elementi"), "accent")],
                     "warn") != 1:
            return
        self.status("Eliminazione in corso…", 0)
        self._remote_job(lambda c: delete_plan(c, plan), f"Eliminati {conta(len(plan), 'elemento', 'elementi')}")

    def remote_chmod(self):
        sel = self.remote_pane.selected_paths()
        if not sel:
            return
        names = sel[0][1].name if len(sel) == 1 else f"{len(sel)} elementi"
        dlg = ChmodDialog(self, names, sel[0][1].perms, any(e.is_dir for _, e in sel))
        dlg.exec()
        if not dlg.choice or len(dlg.octal.text()) != 3:
            return
        octal = dlg.octal.text()
        if not (dlg.recursive.isChecked() and any(e.is_dir and not e.is_link for _, e in sel)):
            self._remote_job(lambda c: [c.chmod(p, octal) for p, _e in sel], f"Permessi {octal} applicati")
            return

        def confirm(plan):
            # i collegamenti si saltano: il chmod cambierebbe i permessi di quello a cui puntano
            todo = [p for p, k in plan if k != "link"]
            files, folders = count_plan([(p, k) for p, k in plan if k != "link"])
            if tk_choice(self, "Cambiare i permessi?", f"Permessi {octal} su {conta(files, 'file', 'file')} e "
                         f"{conta(folders, 'cartella', 'cartelle')}.", [("Annulla", "ghost"), ("Applica", "accent")],
                         "lock") != 1:
                return
            self._remote_job(lambda c: [c.chmod(p, octal) for p in todo],
                             f"Permessi {octal} applicati a {conta(len(todo), 'elemento', 'elementi')}")
        self._scan_then(sel, "Conto gli elementi…", confirm)

    def _drop_on_remote(self, data, target):
        if "local" not in data:
            return
        folder = self.remote_pane.path
        if target is not None:
            folder = listing.parent(folder) if target.name == ".." else listing.join(folder, target.name)
        self.upload_paths(data["local"], folder)

    def _refresh_focused(self):
        w = QApplication.focusWidget()
        if w is not None and self.remote_pane.isAncestorOf(w):
            self.remote_pane.refresh()
        else:
            self.local_pane.refresh()

    # ================================================================== loghi dei siti
    def _logo_worker(self):
        """Thread dei loghi: uno alla volta, timeout brevi; mai sul thread dell'interfaccia."""
        while True:
            site, force = self._logo_q.get()
            if site is None:
                return
            if not style.LOGOS["enabled"]:
                continue
            try:
                logos.update(site, force=force)
            except Exception as exc:  # noqa: BLE001
                self._log_thread("error", f"Logo di {site.title}: {exc}")
            self.bridge.post(lambda sid=site.id: self._logo_ready(sid))

    def request_logo(self, site, force=False):
        if not self.rete or not style.LOGOS["enabled"] or site is None or (site.id in self._logo_pending and not force):
            return
        if force or logos.needs_fetch(site):
            self._logo_pending.add(site.id)
            self._logo_q.put((site.copy(), force))

    def _request_all_logos(self):
        for s in list(self.store.sites):
            self.request_logo(s)

    def _logo_ready(self, site_id):
        self._logo_pending.discard(site_id)
        style.clear_badge_cache(site_id)
        self._refresh_recent()
        if self.connected and self.site is not None and self.site.id == site_id:
            self.remote_pane.set_site_icon(self.site)
        if self._open_sm is not None:
            self._open_sm.logo_changed(site_id)

    # ================================================================== siti, FileZilla, condivisione
    def open_sites(self, select_id=None):
        dlg = SiteManager(self, self.store, {"import": self.import_installed, "export": self.export_file,
                                             "logo": self.request_logo, "logo_changed": self._logo_ready},
                          select_id or (self.site.id if self.site and not self.quick else None), settings=self.settings)
        dlg.connect_site.connect(lambda s: QTimer.singleShot(0, lambda: self.connect_site(s)))
        self._open_sm = dlg
        try:
            dlg.exec()
        finally:
            self._open_sm = None
        self._refresh_recent()

    def _first_run(self):
        if self.settings.value("fz_asked", False) or "--selftest" in sys.argv:
            return
        path = filezilla.installed_sitemanager()
        self.settings.setValue("fz_asked", True)
        if not path or self.store.sites:
            return
        try:
            n = len(filezilla.read_file(path).sites)
        except Exception:
            return
        if n and tk_choice(self, "Ho trovato FileZilla", f"Sul computer c'è FileZilla con {conta(n, 'sito salvato', 'siti salvati')}. "
                           "Vuoi importarli? Gruppi, cartelle, chiavi e password restano come in FileZilla.",
                           [("Non ora", "ghost"), ("Importa i siti", "accent")], "server") == 1:
            self._import(path)

    def import_installed(self):
        path = filezilla.installed_sitemanager()
        if not path:
            if tk_choice(self, "FileZilla non trovato", "Su questo computer non trovo i siti di FileZilla. "
                         "Vuoi scegliere un file sitemanager.xml?", [("No", "ghost"), ("Scegli il file", "accent")],
                         "info") == 1:
                self.import_file()
            return
        self._import(path)

    def import_file(self):
        path = QFileDialog.getOpenFileName(self, "Importa siti (FileZilla)", os.path.expanduser("~"),
                                           "Siti FileZilla (*.xml);;Tutti i file (*)")[0]
        if path:
            self._import(path)

    def _import(self, path):
        try:
            res = filezilla.read_file(path, sync.get_phrase() or None)
            if res.encrypted and (res.wrong_phrase or not sync.get_phrase()):
                phrase = tk_input(self, "Password cifrate", "Il file contiene password cifrate da tk-ftp: "
                                  "scrivi la frase segreta (oppure Annulla per importare i siti senza password).",
                                  "", "Importa", password=True, kind="key")
                if phrase:
                    res = filezilla.read_file(path, phrase)
        except Exception as exc:  # noqa: BLE001
            tk_warn(self, APP_TITLE, f"Non riesco a leggere il file:\n{exc}")
            return
        if not res.sites:
            tk_info(self, APP_TITLE, "Nel file non ci sono siti da importare.")
            return
        added, updated = self.store.merge(res.sites)
        notes = []
        if res.locked:
            notes.append(f"{conta(res.locked, 'password è protetta', 'password sono protette')} dalla password principale di FileZilla: "
                         "inseriscile nel gestore siti.")
        if res.skipped:
            notes.append(f"{conta(res.skipped, 'sito con protocollo non supportato (HTTP, S3…) non importato', 'siti con protocolli non supportati (HTTP, S3…) non importati')}.")
        if res.wrong_phrase:
            notes.append("Frase segreta errata: password cifrate non importate.")
        if res.old_phone:
            notes.append(f"Attenzione: {conta(res.old_phone, 'password viene', 'password vengono')} da un'esportazione "
                         "vecchia dell'app tk-ftp per telefono, dove erano solo codificate (chiunque abbia il file le "
                         "può leggere). Rifai l'esportazione con l'app aggiornata e cancella il file vecchio.")
        self._refresh_recent()
        tk_info(self, "Importazione completata", f"Siti nuovi: {added} · aggiornati: {updated}." +
                ("\n\n" + "\n".join(notes) if notes else ""))

    def export_file(self):
        if not self.store.sites:
            tk_info(self, APP_TITLE, "Non ci sono siti da esportare.")
            return
        path = QFileDialog.getSaveFileName(self, "Esporta per FileZilla",
                                           os.path.join(os.path.expanduser("~"), "Documents", "siti-tk-ftp.xml"),
                                           "Siti FileZilla (*.xml)")[0]
        if not path:
            return
        r = tk_choice(self, "Includere le password?", "FileZilla salva le password solo codificate (non cifrate): "
                      "chi ha il file le può leggere. Includile solo se il file resta al sicuro.",
                      [("Annulla", "ghost"), ("Senza password", "ghost"), ("Con le password", "accent")], "lock")
        if r <= 0:
            return
        pws = {s.id: get_password(s) for s in self.store.sites} if r == 2 else {}
        try:
            filezilla.write_file(path, self.store.sites, pws, include_passwords=(r == 2))
        except OSError as exc:
            tk_warn(self, APP_TITLE, f"Non riesco a scrivere il file:\n{exc}")
            return
        tk_info(self, "Esportazione completata", f"{conta(len(self.store.sites), 'sito', 'siti')} in\n{path}\n\n"
                "In FileZilla: File → Importa. Dall'app tk-ftp sul telefono: Importa.")

    def _store_changed(self):
        self.t_logos.start()  # siti nuovi o cambiati (sito web, host, nome)
        if self.sync.enabled() and not self._sync_pending:
            self.t_sync_write.start()

    def _write_shared(self):
        try:
            self.sync.write()
        except Exception as exc:  # noqa: BLE001
            self._log_thread("error", f"Cartella condivisa: {exc}")

    def _check_shared(self):
        try:
            self._sync_pending = True
            r = self.sync.check()
        except Exception as exc:  # noqa: BLE001
            self._log_thread("error", f"Cartella condivisa: {exc}")
            return
        finally:
            self._sync_pending = False
        if r:
            added, updated, warn = r
            if added or updated:
                self.status(f"Cartella condivisa: {conta(added, 'sito nuovo', 'siti nuovi')}, {conta(updated, 'aggiornato', 'aggiornati')}")
                self._refresh_recent()
                self.t_sync_write.start()
            if warn:
                self._log_thread("error", warn)

    def open_settings(self):
        dlg = SettingsDialog(self, self.settings, sync.get_phrase())
        dlg.exec()
        if not dlg.choice:
            return
        vals = dlg.values()
        old_shared = (self.settings.value("shared_dir", ""), self.settings.value("shared_pw", False))
        for k, v in vals.items():
            self.settings.setValue(k, v)
        try:
            if vals["shared_pw"] and dlg.phrase.text() != sync.get_phrase():
                sync.set_phrase(dlg.phrase.text())
        except OSError as exc:
            tk_warn(self, APP_TITLE, f"Non riesco a salvare la frase segreta nel portachiavi:\n{exc}")
        if bool(vals["show_logos"]) != style.LOGOS["enabled"]:
            style.LOGOS["enabled"] = bool(vals["show_logos"])  # spento: nessuna richiesta di rete per i loghi
            style.clear_badge_cache()
            self._refresh_recent()
            if self.connected and self.site is not None:
                self.remote_pane.set_site_icon(self.site)
            self._request_all_logos()
        self.tm.set_parallel(vals["parallel"])
        self.tm.policy = vals["policy"]
        if self.local_pane.show_hidden != vals["show_hidden"]:
            self.local_pane.show_hidden = vals["show_hidden"]
            self.local_pane.refresh()
        if vals["shared_dir"] and (vals["shared_dir"], vals["shared_pw"]) != old_shared:
            self.settings.setValue("shared_mtime", 0)
            self._check_shared()
            self._write_shared()
            self.status(f"Siti condivisi in {self.sync.path()}")

    # ================================================================== aggiornamenti e Informazioni
    def act_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
        if dlg.check:
            self.check_updates(True)

    def ensure_shortcut(self):
        if not IS_WIN or not is_installed():
            return
        update_uninstall_entry()
        if self.settings.value("lnk_root", "") == APP_ROOT:
            return

        def work():
            try:
                ensure_folder_shortcut()
                self.settings.setValue("lnk_root", APP_ROOT)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def check_updates(self, manual):
        if not manual and time.time() - float(self.settings.value("last_check", 0)) < updater.CHECK_INTERVAL:
            cached = self.settings.value("available", "")
            if cached and updater.is_newer(cached):
                self.update_btn.setText(f"Aggiorna a {cached}")
                self.update_btn.show()
            return
        if manual:
            self.status("Controllo aggiornamenti…", 0)

        def work():
            try:
                m, err = updater.fetch_manifest(), ""
            except Exception as exc:  # noqa: BLE001
                m, err = None, str(exc)
            self.bridge.post(lambda: self._checked(m, err, manual))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, manifest, error, manual):
        self.statusBar().clearMessage()
        if manifest is None:
            if manual:
                tk_warn(self, APP_TITLE, f"Impossibile controllare gli aggiornamenti.\nVerifica la connessione a internet.\n\n{error}")
            return
        self.settings.setValue("last_check", time.time())
        version = str(manifest["version"])
        if not updater.is_newer(version):
            self.settings.setValue("available", "")
            self.update_btn.hide()
            if manual:
                tk_info(self, APP_TITLE, f"Hai già l'ultima versione di {APP_TITLE} ({VERSION}).")
            return
        self.manifest = manifest
        self.settings.setValue("available", version)
        self.update_btn.setText(f"Aggiorna a {version}")
        self.update_btn.show()
        if manual or self.settings.value("skip_version", "") != version:
            self.show_update_dialog()

    def show_update_dialog(self):
        m = self.manifest
        if m is None:
            self.check_updates(True)
            return
        dlg = UpdateDialog(self, m)
        dlg.exec()
        if dlg.choice == "skip":
            self.settings.setValue("skip_version", str(m["version"]))
        elif dlg.choice == "go":
            self.start_update()

    def start_update(self):
        asset = updater.asset_for(self.manifest)
        if asset is None:
            tk_info(self, APP_TITLE, "Questa versione non è ancora disponibile per il tuo sistema.")
            return
        if not is_installed():
            tk_info(self, APP_TITLE, "Stai usando la versione di sviluppo: l'aggiornamento automatico funziona "
                                     "solo con il programma installato.")
            return
        if self.tm.pending_count():
            tk_info(self, APP_TITLE, "Aspetta che finiscano i trasferimenti, poi aggiorna.")
            return
        dest = os.path.join(updater.download_dir(), os.path.basename(asset["url"].split("?")[0]))
        prog = TkProgress(self, "Aggiornamento in corso", f"Scarico {APP_TITLE} {self.manifest['version']}", True)
        prog.show()
        state = {"cancel": False}
        prog.canceled.connect(lambda: state.__setitem__("cancel", True))

        def work():
            try:
                updater.download(asset["url"], dest, asset.get("sha256"),
                                 lambda d, t: self.bridge.post(lambda: prog.set_progress(
                                     d, t, f"{human_size(d)} di {human_size(t)}")), lambda: state["cancel"])
                self.bridge.post(lambda: on_ok(dest))
            except InterruptedError:
                self.bridge.post(prog.close)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.bridge.post(lambda: (prog.close(), tk_warn(self, APP_TITLE, f"Aggiornamento non riuscito:\n{msg}")))

        def on_ok(path):
            prog.bar.setRange(0, 0)
            prog.set_status("Installazione dell'aggiornamento…")
            try:
                updater.apply_update(path, new_version=str(self.manifest["version"]))
            except Exception as exc:  # noqa: BLE001
                prog.close()
                tk_warn(self, APP_TITLE, f"Aggiornamento non riuscito:\n{exc}")
                return
            self.closing_for_update = True
            QTimer.singleShot(300, QApplication.instance().quit)
        threading.Thread(target=work, daemon=True).start()

    # ================================================================== chiusura
    def closeEvent(self, e):
        if not self.closing_for_update:
            dirty = [w for w in self.edits.files.values() if w.dirty or w.busy]
            if self.tm.pending_count() or dirty:
                txt = []
                if self.tm.pending_count():
                    txt.append(f"{conta(self.tm.pending_count(), 'trasferimento non è finito', 'trasferimenti non sono finiti')}")
                if dirty:
                    txt.append(f"{conta(len(dirty), 'file modificato non è ancora', 'file modificati non sono ancora')} sul server")
                if tk_choice(self, "Chiudere tk-ftp?", " e ".join(txt) + ".", [("Resta", "ghost"), ("Chiudi", "accent")],
                             "warn") != 1:
                    e.ignore()
                    return
        self.settings.setValue("geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.settings.setValue("hsplit", bytes(self.hsplit.saveState().toBase64()).decode())
        self.settings.setValue("vsplit", bytes(self.vsplit.saveState().toBase64()).decode())
        if self.local_pane.path:
            self.settings.setValue("last_local", self.local_pane.path)
        if self.session is not None:
            self.session.close()
        self.tm.shutdown()
        import shutil
        import tempfile
        shutil.rmtree(os.path.join(tempfile.gettempdir(), "tk-ftp-trascina"), ignore_errors=True)
        for w in list(self.edits.files.values()):
            if not w.dirty:
                try:
                    os.remove(w.local)
                except OSError:
                    pass
        e.accept()


def _rename_over(c, src, dst):
    """Rinomina sopra un file che esiste (l'utente ha confermato): se il server non sovrascrive da solo,
    prima toglie quello vecchio."""
    try:
        c.rename(src, dst)
    except Exception:  # noqa: BLE001
        if c.stat(dst) is None or c.stat(src) is None:
            raise
        c.delete(dst)
        c.rename(src, dst)


# ====================================================================== avvio
def cli_update_test(argv):
    url = argv[argv.index("--update-test") + 1]
    log = os.path.join(log_dir(), "update-test.log")

    def write(msg):
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

    try:
        m = updater.fetch_manifest(url)
        write(f"manifest {m['version']} (installata {VERSION})")
        if not updater.is_newer(m["version"]):
            write("nessun aggiornamento")
            return 0
        asset = updater.asset_for(m)
        if asset is None:
            write("nessun file valido per questo sistema (manca o non è firmato): aggiornamento rifiutato")
            return 1
        dest = os.path.join(updater.download_dir(), os.path.basename(asset["url"].split("?")[0]))
        updater.download(asset["url"], dest, asset.get("sha256"))
        write(f"scaricato e verificato: {dest}")
        if not is_installed():
            write("versione di sviluppo: aggiornamento non applicato")
            return 3
        updater.apply_update(dest, relaunch="--no-relaunch" not in argv, new_version=m["version"])
        write("installazione avviata")
        return 0
    except Exception as exc:  # noqa: BLE001
        write(f"ERRORE: {exc}")
        return 1


def runtime_check():
    """Verifica che il pacchetto abbia tutto: TLS, cifratura delle password condivise, chiavi SSH (paramiko,
    cryptography, bcrypt, nacl). Ritorna un testo «OK …» o solleva un'eccezione."""
    import ssl
    import tempfile
    import paramiko
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    ssl.create_default_context()
    s = Site(name="prova", host="h", user="u")
    data = filezilla.build([s], {s.id: "pàss"}, phrase="frase di prova")
    assert filezilla.parse(data, "frase di prova").sites[0].password == "pàss"
    k = ed25519.Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                          serialization.BestAvailableEncryption(b"frase"))
    tmp = os.path.join(tempfile.mkdtemp(), "chiave")
    with open(tmp, "wb") as fh:
        fh.write(pem)
    c = remote.SftpClient(Site(protocol="sftp", logon="key", keyfile=tmp), passphrase="frase")
    key = c._load_key(tmp)
    assert key.get_name() == "ssh-ed25519" and key.sign_ssh_data(b"tk-ftp").asbytes()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="red"/></svg>'
    img = logos._decode(svg, "image/svg+xml", "logo.svg")
    assert img is not None and img.width() == logos.SIZE, "QtSvg mancante: loghi SVG"
    rsa = paramiko.RSAKey.generate(1024)
    sig = rsa.sign_ssh_data(b"tk-ftp")
    assert rsa.verify_ssh_sig(b"tk-ftp", paramiko.Message(sig.asbytes()))
    from tkftp.util import licenses_dir
    lic_dir = licenses_dir()
    assert os.path.isfile(os.path.join(lic_dir, "COPYING-AGPL-3.0.txt")), f"licenze mancanti ({lic_dir})"
    return f"OK paramiko {paramiko.__version__} · {ssl.OPENSSL_VERSION} · {len(os.listdir(lic_dir))} licenze"


def dialogs_check(win):
    """Selftest: le finestre del software libero si costruiscono (senza mostrarle)."""
    from tkftp.tk_licenza_qt import BenvenutoDialog, LicenzeDialog
    from tkftp.util import licenses_dir
    lic = pro.licenza()
    for d in (BenvenutoDialog(None, APP_TITLE, URL_SORGENTE, win, logo_tile(96), RIGHE_BENVENUTO),
              LicenzeDialog(APP_TITLE, VERSION, URL_SORGENTE, licenses_dir(), win), AboutDialog(win),
              SettingsDialog(win, win.settings, "")):
        d.deleteLater()
    assert lic is not None and lic.sbloccato() and not lic.free_pro()


def _quiet_thread_errors():
    """Il thread di prefetch di paramiko si lamenta quando chiudiamo la connessione a metà (annulla): niente rumore."""
    old = threading.excepthook

    def hook(args):
        if isinstance(args.exc_value, (OSError, EOFError)) and "prefetch" in str(getattr(args.thread, "name", "")) + \
                str(args.exc_traceback.tb_frame.f_code.co_name if args.exc_traceback else ""):
            return
        old(args)
    threading.excepthook = hook


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        import tempfile
        os.environ.setdefault("TKFTP_DATI", tempfile.mkdtemp(prefix="tkftp-selftest-"))
        os.environ.setdefault("TKFTP_VAULT_SERVICE", "tk-ftp-selftest")
    if "--update-test" in argv:
        sys.exit(cli_update_test(argv))
    if "--vault-test" in argv:
        out = argv[argv.index("--vault-test") + 1]
        os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-selftest"
        from tkftp import vault
        try:
            vault.SERVICE = "tk-ftp-selftest"
            vault.set_secret("prova", "pàssword di prova")
            ok = vault.get_secret("prova") == "pàssword di prova"
            vault.delete_secret("prova")
            res = "OK portachiavi" if ok and vault.get_secret("prova") is None else "ERRORE lettura diversa"
        except Exception as exc:  # noqa: BLE001
            res = f"ERRORE {exc}"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(res)
        return
    _quiet_thread_errors()
    app = QApplication(sys.argv)
    # memoria del programma (benvenuto, consenso alle statistiche, invito al caffè): nessuna funzione a pagamento
    app.licenza = pro.crea_licenza(VERSION)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    import PySide6
    from PySide6.QtCore import QLibraryInfo, QTranslator
    tr = QTranslator(app)
    for folder in (os.path.join(os.path.dirname(PySide6.__file__), "translations"),
                   QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        if tr.load("qtbase_it", folder):
            app.installTranslator(tr)
            break
    if IS_WIN:
        app.setFont(QFont("Segoe UI", 10))
    settings = Settings()
    from tkftp.tk_licenza_qt import stile_caselle_globale
    app.setStyleSheet(stylesheet(check_png(os.path.join(data_dir(), "spunta.png"))) + stile_caselle_globale("QFrame#tkcard QCheckBox"))
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TecnikGeek.tk-ftp")
        except Exception:
            pass
    win = MainWindow(settings)
    if "--selftest" in argv:
        out = argv[argv.index("--selftest") + 1]
        try:
            res = runtime_check()
            dialogs_check(win)
        except Exception as exc:  # noqa: BLE001
            res = f"ERRORE {exc.__class__.__name__}: {exc}"
        with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(res)
        win.resize(1440, 900)
        win.show()
        QTimer.singleShot(900, lambda: (win.grab().save(out), app.quit()))
        app.exec()
        win.tm.shutdown()
        return
    win.show()
    QTimer.singleShot(0, win.avvio)  # benvenuto con la finestra già disegnata, poi rete e invito al caffè
    sys.exit(app.exec())
