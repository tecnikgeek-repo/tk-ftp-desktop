"""I due pannelli affiancati: «Questo computer» e «Server», ognuno con albero delle cartelle ed elenco dei file."""
import json
import os

from PySide6.QtCore import QDir, QFileInfo, QFileSystemWatcher, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractFileIconProvider, QColor, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFileSystemModel, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSplitter, QStackedWidget, QTreeView, QTreeWidget, QVBoxLayout, QWidget,
)

from tkftp.util import conta
from tkftp import listing
from tkftp.listing import Entry
from tkftp.models import MIME_LOCAL, MIME_REMOTE, PARENT, FileModel
from tkftp.sites import PROTOCOL_SHORT
from tkftp.style import (
    ACCENT, ACCENT_D, GRAY_400, GRAY_500, NAVY, ic, kind_icon, logo_tile, shadow, site_badge, text_btn,
    tool_btn,
)
from tkftp.util import IS_WIN, human_size


class FolderIcons(QAbstractFileIconProvider):
    """Albero del computer con le stesse cartelle rame del server."""

    def icon(self, what):
        if isinstance(what, QFileInfo):
            if what.isRoot():
                return ic("monitor", NAVY, 16)
            return kind_icon("dir", 16) if what.isDir() else kind_icon("file", 16)
        if what == QAbstractFileIconProvider.IconType.Drive or what == QAbstractFileIconProvider.IconType.Computer:
            return ic("monitor", NAVY, 16)
        return kind_icon("dir", 16)


def draw_hint(view, text, top=0):
    """Scritta grigia al centro di un elenco vuoto."""
    p = QPainter(view.viewport())
    p.setPen(QColor(GRAY_400))
    f = p.font()
    f.setPointSizeF(f.pointSizeF() + 0.5)
    p.setFont(f)
    r = view.viewport().rect().adjusted(24, top, -24, 0)
    p.drawText(r, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)
    p.end()


class HintTreeView(QTreeView):
    def __init__(self, hint=""):
        super().__init__()
        self.hint = hint

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.hint and (self.model() is None or self.model().rowCount() == 0):
            draw_hint(self, self.hint, 30)


class HintTreeWidget(QTreeWidget):
    def __init__(self, hint=""):
        super().__init__()
        self.hint = hint

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.hint and self.topLevelItemCount() == 0:
            draw_hint(self, self.hint, 30)


class FileView(QTreeView):
    """Elenco file: ordinabile, selezione multipla, trascina e rilascia."""
    dropped = Signal(object, object)   # (mime: dict, entry di destinazione o None)
    activated_entry = Signal(object)
    columns_changed = Signal()

    def __init__(self, model, accept):
        super().__init__()
        self.hint = ""
        self.accept_kinds = accept          # tipi accettati: MIME_REMOTE / MIME_LOCAL / "urls"
        self.setModel(model)
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setIconSize(QSize(18, 18))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h = self.header()
        h.setStretchLastSection(False)
        # Nome: lo spazio che resta, mai sotto NAME_MIN (se proprio non ci sta compare la barra orizzontale);
        # le altre colonne larghe quanto il contenuto (fit_columns) o quanto le ha messe l'utente
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for c in range(1, model.columnCount()):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        h.setMinimumSectionSize(40)
        h.resizeSection(1, 98)
        h.resizeSection(2, 86)
        h.resizeSection(3, 128)
        if model.columnCount() > 4:
            h.resizeSection(4, 94)
            h.resizeSection(5, 84)
            self.set_hidden_columns([2, 5])  # Tipo e Proprietario: si accendono col tasto destro sulle intestazioni
        else:
            self.set_hidden_columns([2])  # Tipo: l'icona colorata dice già che file è; lascia spazio ai nomi
        h.setSortIndicatorShown(True)
        h.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h.customContextMenuRequested.connect(self._header_menu)
        # Nome prende lo spazio libero; le altre colonne larghe quanto il contenuto, finché l'utente non le allarga
        self.user_widths = {}
        self._fitting = False
        h.sectionResized.connect(self._section_resized)
        model.modelReset.connect(lambda: QTimer.singleShot(0, self.fit_columns))
        # doppio clic = apri cartella / azione sul file (nella 1.0.2 questa riga era finita per sbaglio dentro
        # set_user_widths e senza larghezze salvate il doppio clic non faceva niente: tests/test_dblclick.py)
        self.doubleClicked.connect(lambda i: self.activated_entry.emit(self.model().entry(i.row())))

    def fit_columns(self):
        self._fitting = True
        try:
            h = self.header()
            for c in range(1, self.model().columnCount()):
                if self.isColumnHidden(c):
                    continue
                if c in self.user_widths:
                    h.resizeSection(c, self.user_widths[c])
                else:
                    # testo dell'intestazione misurato col suo carattere (11 px grassetto), senza lo spazio fisso
                    # che Qt tiene per la freccia d'ordinamento: le colonne restano strette quanto serve
                    from PySide6.QtGui import QFont, QFontMetrics
                    f = QFont(self.font())
                    f.setPixelSize(11)
                    f.setBold(True)
                    head = QFontMetrics(f).horizontalAdvance(str(self.model().headerData(c, Qt.Orientation.Horizontal)))
                    w = max(self.sizeHintForColumn(c) + 4, head + 16)
                    h.resizeSection(c, max(48, min(w, 220)))
        finally:
            self._fitting = False
        self.layout_name()

    NAME_MIN = 170

    def layout_name(self):
        h = self.header()
        others = sum(h.sectionSize(c) for c in range(1, self.model().columnCount()) if not self.isColumnHidden(c))
        want = max(self.NAME_MIN, self.viewport().width() - others)
        if h.sectionSize(0) != want:
            self._fitting = True
            h.resizeSection(0, want)
            self._fitting = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.layout_name()

    def _section_resized(self, col, _old, new):
        if self._fitting or col == 0 or not self.isVisible() or new <= 0 or self.isColumnHidden(col):
            return
        self.user_widths[col] = new
        self.layout_name()
        self.columns_changed.emit()

    def set_user_widths(self, widths):
        self.user_widths = {int(k): int(v) for k, v in (widths or {}).items() if int(k) > 0}
        self.fit_columns()

    def paintEvent(self, e):
        super().paintEvent(e)
        m = self.model()
        if self.hint and m.folder and not m.entries:
            draw_hint(self, self.hint, 40)

    def set_hidden_columns(self, cols):
        for c in range(1, self.model().columnCount()):
            self.setColumnHidden(c, c in cols)

    def hidden_columns(self):
        return [c for c in range(1, self.model().columnCount()) if self.isColumnHidden(c)]

    def _header_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        for c in range(1, self.model().columnCount()):
            a = m.addAction(self.model().cols[c])
            a.setCheckable(True)
            a.setChecked(not self.isColumnHidden(c))
            a.toggled.connect(lambda on, c=c: (self.setColumnHidden(c, not on), self.fit_columns(),
                                               self.columns_changed.emit()))
        m.exec(self.header().mapToGlobal(pos))

    def selected_entries(self):
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        out = [self.model().entry(r) for r in rows]
        return [e for e in out if e is not None and e.name != PARENT]

    def _mime(self, md):
        if md.hasFormat(MIME_REMOTE) and MIME_REMOTE not in self.accept_kinds:
            return None  # file del server sul pannello del server: niente (e non far partire lo scaricamento)
        if MIME_REMOTE in self.accept_kinds and md.hasFormat(MIME_REMOTE):
            return {"remote": json.loads(bytes(md.data(MIME_REMOTE)).decode("utf-8"))}
        if MIME_LOCAL in self.accept_kinds and md.hasFormat(MIME_LOCAL):
            return {"local": json.loads(bytes(md.data(MIME_LOCAL)).decode("utf-8"))}
        if "urls" in self.accept_kinds and md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if paths:
                return {"local": paths}
        return None

    def dragEnterEvent(self, e):
        if self._mime(e.mimeData()) is not None:
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._mime(e.mimeData()) is not None:
            super().dragMoveEvent(e)
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        data = self._mime(e.mimeData())
        if data is None:
            e.ignore()
            return
        idx = self.indexAt(e.position().toPoint())
        target = self.model().entry(idx.row()) if idx.isValid() else None
        if target is not None and not target.is_dir:
            target = None
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        self.dropped.emit(data, target)


class Pane(QFrame):
    """Scheda bianca con testata, riga del percorso, albero ed elenco."""
    navigate = Signal(str)

    def __init__(self, icon_name, title, remote):
        super().__init__()
        self.setObjectName("card")
        shadow(self, 20, 4, 38)
        self.remote = remote
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        box = QLabel(objectName="icobox")
        box.setFixedSize(34, 34)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setPixmap(ic(icon_name, ACCENT_D, 18).pixmap(18, 18))
        head.addWidget(box)
        self.icobox = box
        self.icon_name = icon_name
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel(title.upper(), objectName="cardtitle"))
        self.sub = QLabel("", objectName="cardsub")
        col.addWidget(self.sub)
        head.addLayout(col)
        head.addStretch(1)
        self.head_right = QHBoxLayout()
        self.head_right.setSpacing(8)
        head.addLayout(self.head_right)
        lay.addLayout(head)

        self.body = QWidget(objectName="canvas")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.btn_up = tool_btn("parent", "Cartella superiore (Backspace)", self.go_up, NAVY, "flat")
        self.btn_home = tool_btn("home", "Cartella iniziale", self.go_home, NAVY, "flat")
        self.btn_refresh = tool_btn("refresh", "Aggiorna (F5)", self.refresh, NAVY, "flat")
        self.path_edit = QLineEdit(objectName="path")
        self.path_edit.setPlaceholderText("Percorso")
        self.path_edit.returnPressed.connect(lambda: self.navigate.emit(self.path_edit.text().strip()))
        self.btn_mkdir = tool_btn("folder-plus", "Nuova cartella", None, NAVY, "flat")
        for w in (self.btn_up, self.btn_home, self.btn_refresh):
            prow.addWidget(w)
        prow.addWidget(self.path_edit, 1)
        prow.addWidget(self.btn_mkdir)
        bl.addLayout(prow)

        self.split = QSplitter()
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(8)
        self.tree = QTreeView(objectName="tree")
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setMinimumWidth(120)
        self.tree.setAnimated(True)
        self.tree.setIndentation(12)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        # niente scorrimento orizzontale: con le cartelle profonde i nomi sparirebbero a sinistra
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hb = self.tree.horizontalScrollBar()
        hb.valueChanged.connect(lambda v: hb.setValue(0) if v else None)
        self.model = FileModel(remote)
        self.view = FileView(self.model, [MIME_LOCAL, "urls"] if remote else [MIME_REMOTE])
        self.split.addWidget(self.tree)
        self.split.addWidget(self.view)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 4)
        self.split.setSizes([170, 640])
        bl.addWidget(self.split, 1)
        self.footer = QLabel("", objectName="hint")
        bl.addWidget(self.footer)
        lay.addWidget(self.body, 1)
        self.view.selectionModel().selectionChanged.connect(self._update_footer)
        self.path = ""
        self.home = ""

    def _update_footer(self, *a):
        ents = [e for e in self.model.entries]
        nd = sum(1 for e in ents if e.is_dir)
        nf = len(ents) - nd
        tot = sum(e.size for e in ents if not e.is_dir)
        sel = self.view.selected_entries()
        txt = f"{conta(nd, 'cartella', 'cartelle')} · {conta(nf, 'file', 'file')} · {human_size(tot)}"
        if sel:
            ssize = sum(e.size for e in sel if not e.is_dir)
            txt = f"{conta(len(sel), 'selezionato', 'selezionati')} ({human_size(ssize)})  ·  " + txt
        self.footer.setText(txt)

    def go_up(self):
        pass

    def go_home(self):
        if self.home:
            self.navigate.emit(self.home)

    def refresh(self):
        if self.path or not self.remote:
            self.navigate.emit(self.path)


# =========================================================================== locale
class LocalPane(Pane):
    def __init__(self, show_hidden=False):
        super().__init__("monitor", "Questo computer", False)
        self.show_hidden = show_hidden
        self.sub.setText("I file sul tuo computer")
        self.home = os.path.expanduser("~")
        self.fs = QFileSystemModel(self)
        self._icons = FolderIcons()
        self.fs.setIconProvider(self._icons)
        self.fs.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.fs.setRootPath("")
        self.fs.setReadOnly(True)
        self.tree.setModel(self.fs)
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.clicked.connect(lambda i: self.navigate.emit(self.fs.filePath(i)))
        self.fs.directoryLoaded.connect(self._tree_loaded)
        self._tree_target = ""
        self.view.hint = "Cartella vuota"
        self.navigate.connect(self.load)
        self.watch = QFileSystemWatcher(self)
        self._reload = QTimer(self, singleShot=True, interval=350)
        self._reload.timeout.connect(lambda: self.load(self.path, keep=True))
        self.watch.directoryChanged.connect(lambda _p: self._reload.start())
        self.view.activated_entry.connect(self._activated)
        self.on_file_activated = None  # impostato dalla finestra principale

    def _activated(self, e):
        if e is None:
            return
        if e.name == PARENT:
            self.go_up()
        elif e.is_dir:
            self.load(self.join(e.name))
        elif self.on_file_activated:
            self.on_file_activated(e)

    def join(self, name):
        if not self.path:
            return name  # unità («C:\»)
        return os.path.join(self.path, name)

    def go_up(self):
        if not self.path:
            return
        p = os.path.dirname(self.path.rstrip("\\/")) if not self._is_root(self.path) else ""
        if IS_WIN and p and len(p) == 2 and p[1] == ":":
            p += "\\"
        self.load(p if (p or IS_WIN) else "/")

    @staticmethod
    def _is_root(p):
        return (IS_WIN and len(p.rstrip("\\/")) <= 2) or p == "/"

    def load(self, path, keep=False):
        path = os.path.expanduser(path) if path else ""
        if path and "~" in path and os.path.isdir(path):
            path = os.path.realpath(path)  # nomi brevi 8.3 (TECNIK~1) → nomi veri, come nell'albero
        if path and not os.path.isdir(path):
            self.footer.setText(f"Cartella non trovata: {path}")
            return
        try:
            if not path:
                ents = [Entry(d.absolutePath().replace("/", "\\"), True) for d in QDir.drives()]
            else:
                ents = listing.local_entries(path, self.show_hidden)
        except OSError as exc:
            self.footer.setText(f"Non riesco ad aprire la cartella: {exc.strerror or exc}")
            return
        sel = {e.name for e in self.view.selected_entries()} if keep else set()
        if self.watch.directories():
            self.watch.removePaths(self.watch.directories())
        if path:
            self.watch.addPath(path)
        self.path = path
        self.model.set_entries(path, ents, bool(path))
        self.path_edit.setText(path or "Questo PC")
        if sel:
            for r in range(self.model.rowCount()):
                if self.model.entry(r).name in sel:
                    self.view.selectionModel().select(
                        self.model.index(r, 0), self.view.selectionModel().SelectionFlag.Select
                        | self.view.selectionModel().SelectionFlag.Rows)
        if path and not keep:
            self._tree_target = path
            self._tree_select()
        self._update_footer()

    def _tree_select(self):
        idx = self.fs.index(QDir.fromNativeSeparators(self._tree_target))
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.tree.expand(idx)
            self.tree.horizontalScrollBar().setValue(0)  # i nomi restano leggibili anche nelle cartelle profonde

    def _tree_loaded(self, folder):
        # l'albero carica le cartelle un po' alla volta: appena c'è quella giusta la seleziona
        t = os.path.normcase(os.path.normpath(self._tree_target)) if self._tree_target else ""
        f = os.path.normcase(os.path.normpath(folder))
        if t and t.startswith(f):
            self._tree_select()
            if f in (t, os.path.dirname(t)):
                self._tree_target = ""  # arrivati: da qui in poi l'albero lo muove l'utente
                QTimer.singleShot(350, lambda: self.tree.scrollTo(self.tree.currentIndex(),
                                                                  QAbstractItemView.ScrollHint.PositionAtCenter))

    def selected_paths(self):
        return [(self.join(e.name), e) for e in self.view.selected_entries()]


# =========================================================================== remoto
class SiteTile(QFrame):
    clicked = Signal()

    def __init__(self, site):
        super().__init__()
        self.setObjectName("tile")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"QFrame#tile {{ background:#fff; border:1px solid #e2e8f0; border-radius:14px; }}"
                           f"QFrame#tile:hover {{ border-color:{ACCENT}; background:#fdf7ec; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(10)
        av = QLabel()
        av.setFixedSize(38, 38)
        av.setStyleSheet("background:transparent;")
        av.setPixmap(site_badge(site, 38))  # logo del sito, o la lettera colorata
        short = PROTOCOL_SHORT.get(site.protocol, "FTP")
        lay.addWidget(av)
        col = QVBoxLayout()
        col.setSpacing(1)
        n = QLabel(site.title)
        n.setStyleSheet("font-weight:800; background:transparent;")
        h = QLabel(f"{short} · {site.user + '@' if site.user else ''}{site.host}")
        h.setStyleSheet(f"color:{GRAY_500}; font-size:11px; background:transparent;")
        col.addWidget(n)
        col.addWidget(h)
        lay.addLayout(col, 1)
        arrow = QLabel()
        arrow.setPixmap(ic("right", GRAY_400, 16).pixmap(16, 16))
        arrow.setStyleSheet("background:transparent;")
        lay.addWidget(arrow)
        self.setMinimumWidth(230)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class RemotePane(Pane):
    want_list = Signal(str, bool)   # (percorso, solo per l'albero)

    def __init__(self):
        super().__init__("server", "Server", True)
        self.sub.setText("Non connesso")
        self.pill = QLabel("NON CONNESSO", objectName="pilloff")
        self.head_right.addWidget(self.pill)
        self.btn_save_site = text_btn("plus", "Salva sito", None, NAVY, "", "Salva questa connessione rapida nel gestore siti")
        self.btn_save_site.hide()
        self.head_right.addWidget(self.btn_save_site)
        self.btn_disconnect = text_btn("unplug", "Disconnetti", None, NAVY, "", "Chiudi la connessione")
        self.btn_disconnect.hide()
        self.head_right.addWidget(self.btn_disconnect)

        self.tmodel = QStandardItemModel(self)
        self.tree.setModel(self.tmodel)
        self.tree.setAnimated(False)  # l'albero si rifà spesso: senza animazione niente righe sovrapposte
        self.view.hint = "Cartella vuota · trascina qui i file dal computer"
        self.tree.clicked.connect(lambda i: self.navigate.emit(i.data(Qt.ItemDataRole.UserRole)))
        self.tree.expanded.connect(self._expanded)
        self.nodes = {}
        self.cache = {}

        # pagine: benvenuto / connessione in corso / elenco
        self.stack = QStackedWidget()
        layout = self.layout()
        layout.removeWidget(self.body)
        self.stack.addWidget(self._welcome_page())
        self.stack.addWidget(self._busy_page())
        self.stack.addWidget(self.body)
        layout.addWidget(self.stack, 1)
        self.view.activated_entry.connect(self._activated)
        self.on_file_activated = None

    # -------------------------------------------------- pagine
    def _welcome_page(self):
        w = QWidget(objectName="canvas")
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 10, 20, 10)
        v.addStretch(1)
        logo = QLabel()
        logo.setPixmap(logo_tile(76))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo)
        v.addSpacing(8)
        t = QLabel("Collegati a un server")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size:22px; font-weight:800;")
        v.addWidget(t)
        s = QLabel("Scegli un sito dal gestore, oppure scrivi indirizzo, utente e password\n"
                   "nella connessione rapida in alto. FTP, FTPS e SFTP.")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet(f"color:{GRAY_500};")
        v.addWidget(s)
        v.addSpacing(10)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_open_sites = text_btn("server", "Apri il gestore siti", None, "#fff", "accent")
        self.btn_import_fz = text_btn("import", "Importa siti", None, NAVY, "")
        row.addWidget(self.btn_open_sites)
        row.addWidget(self.btn_import_fz)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(18)
        self.recent_title = QLabel("SITI RECENTI", objectName="cardtitle")
        self.recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.recent_title)
        self.recent_box = QWidget(objectName="canvas")
        self.recent_grid = QGridLayout(self.recent_box)
        self.recent_grid.setSpacing(10)
        self.recent_grid.setContentsMargins(0, 6, 0, 0)
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(self.recent_box)
        hb.addStretch(1)
        v.addLayout(hb)
        v.addStretch(2)
        return w

    def set_recent(self, sites, on_click):
        while self.recent_grid.count():
            it = self.recent_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.recent_title.setVisible(bool(sites))
        for i, s in enumerate(sites[:6]):
            tile = SiteTile(s)
            tile.clicked.connect(lambda s=s: on_click(s))
            self.recent_grid.addWidget(tile, i // 2, i % 2)

    def _busy_page(self):
        w = QWidget(objectName="canvas")
        v = QVBoxLayout(w)
        v.addStretch(1)
        logo = QLabel()
        logo.setPixmap(logo_tile(64))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo)
        self.busy_label = QLabel("Connessione in corso…")
        self.busy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.busy_label.setStyleSheet("font-size:17px; font-weight:800;")
        v.addWidget(self.busy_label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedSize(260, 8)
        bar.setStyleSheet(f"QProgressBar {{ background:#e2e8f0; border:0; border-radius:4px; }}"
                          f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:4px; }}")
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(bar)
        hb.addStretch(1)
        v.addLayout(hb)
        self.btn_cancel_connect = QPushButton("Annulla")
        self.btn_cancel_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        hb2 = QHBoxLayout()
        hb2.addStretch(1)
        hb2.addWidget(self.btn_cancel_connect)
        hb2.addStretch(1)
        v.addLayout(hb2)
        v.addStretch(2)
        return w

    # -------------------------------------------------- stato
    def show_welcome(self):
        self.stack.setCurrentIndex(0)
        self.sub.setText("Non connesso")
        self.pill.setText("NON CONNESSO")
        self.pill.setObjectName("pilloff")
        self.pill.setStyle(self.pill.style())
        self.btn_disconnect.hide()
        self.btn_save_site.hide()
        self.set_site_icon(None)
        self.path = ""
        self.cache.clear()
        self.tmodel.clear()
        self.nodes.clear()
        self.model.set_entries("", [], False)

    def show_busy(self, text):
        self.busy_label.setText(text)
        self.stack.setCurrentIndex(1)
        self.pill.setText("CONNESSIONE…")
        self.pill.setObjectName("pillbusy")
        self.pill.setStyle(self.pill.style())

    def show_connected(self, site, home, quick):
        self.home = home
        self.stack.setCurrentIndex(2)
        short = PROTOCOL_SHORT.get(site.protocol, "FTP")
        secure = site.protocol in ("sftp", "ftps", "ftps-implicit")
        self.sub.setText(f"{site.title}  ·  {site.user + '@' if site.user else ''}{site.host}:{site.port}")
        self.pill.setText(f"{short} · {'PROTETTA' if secure else 'CONNESSO'}")
        self.pill.setObjectName("pillok")
        self.pill.setStyle(self.pill.style())
        self.btn_disconnect.show()
        self.btn_save_site.setVisible(quick)
        self.set_site_icon(site)
        self.tmodel.clear()
        self.nodes.clear()
        self.cache.clear()
        root = QStandardItem(kind_icon("dir", 16), "/")
        root.setData("/", Qt.ItemDataRole.UserRole)
        root.setEditable(False)
        self.tmodel.appendRow(root)
        self.nodes["/"] = root

    def set_site_icon(self, site):
        """Testata del pannello: logo del sito connesso al posto dell'icona del server."""
        if site is None:
            self.icobox.setObjectName("icobox")
            self.icobox.setStyleSheet("")
            self.icobox.setPixmap(ic(self.icon_name, ACCENT_D, 18).pixmap(18, 18))
        else:
            self.icobox.setStyleSheet("background:transparent;")
            self.icobox.setPixmap(site_badge(site, 34))
        self.icobox.setStyle(self.icobox.style())

    def set_tls_label(self, text):
        self.pill.setText(text)

    # -------------------------------------------------- elenco
    def _activated(self, e):
        if e is None:
            return
        if e.name == PARENT:
            self.go_up()
        elif e.is_dir:
            self.navigate.emit(listing.join(self.path, e.name))
        elif self.on_file_activated:
            self.on_file_activated(e)

    def go_up(self):
        if self.path and self.path != "/":
            self.navigate.emit(listing.parent(self.path))

    def show_listing(self, path, entries, keep=False):
        self.cache[path] = entries
        sel = {e.name for e in self.view.selected_entries()} if keep else set()
        self.path = path
        self.model.set_entries(path, entries, path != "/")
        self.path_edit.setText(path)
        if sel:
            for r in range(self.model.rowCount()):
                if self.model.entry(r).name in sel:
                    self.view.selectionModel().select(
                        self.model.index(r, 0), self.view.selectionModel().SelectionFlag.Select
                        | self.view.selectionModel().SelectionFlag.Rows)
        self._fill_tree(path, entries)
        self._update_footer()

    def _node(self, path):
        if path in self.nodes:
            return self.nodes[path]
        parent = self._node(listing.parent(path))
        it = QStandardItem(kind_icon("dir", 16), listing.basename(path))
        it.setData(path, Qt.ItemDataRole.UserRole)
        it.setEditable(False)
        parent.appendRow(it)
        self.nodes[path] = it
        return it

    def _fill_tree(self, path, entries):
        node = self._node(path)
        dirs = sorted([e for e in entries if e.is_dir], key=lambda e: e.name.lower())
        existing = {node.child(r).data(Qt.ItemDataRole.UserRole): r for r in range(node.rowCount())}
        wanted = [listing.join(path, e.name) for e in dirs]
        if list(existing) != wanted:
            self._forget_below(path)  # removeRows cancella anche i nodi più in basso
            node.removeRows(0, node.rowCount())
            for e, p in zip(dirs, wanted):
                it = QStandardItem(kind_icon("dir", 16), e.name)
                it.setData(p, Qt.ItemDataRole.UserRole)
                it.setEditable(False)
                ph = QStandardItem("…")  # segnaposto: si carica quando si apre
                ph.setData(None, Qt.ItemDataRole.UserRole)
                ph.setEditable(False)
                it.appendRow(ph)
                node.appendRow(it)
                self.nodes[p] = it
        idx = self.tmodel.indexFromItem(node)
        p = idx
        while p.isValid():
            self.tree.expand(p)
            p = p.parent()
        self.tree.setCurrentIndex(idx)
        self.tree.scrollTo(idx)

    def _forget_below(self, path):
        prefix = path.rstrip("/") + "/"
        for p in [x for x in self.nodes if x != path and x.startswith(prefix)]:
            self.nodes.pop(p, None)

    def _expanded(self, idx):
        it = self.tmodel.itemFromIndex(idx)
        if it and it.rowCount() == 1 and it.child(0).data(Qt.ItemDataRole.UserRole) is None:
            path = it.data(Qt.ItemDataRole.UserRole)
            if path in self.cache:
                self._fill_children_only(path, self.cache[path])
            else:
                self.want_list.emit(path, True)

    def fill_tree_only(self, path, entries):
        self.cache[path] = entries
        self._fill_children_only(path, entries)

    def _fill_children_only(self, path, entries):
        node = self.nodes.get(path)
        if node is None:
            return
        self._forget_below(path)
        node.removeRows(0, node.rowCount())
        for e in sorted([e for e in entries if e.is_dir], key=lambda e: e.name.lower()):
            p = listing.join(path, e.name)
            it = QStandardItem(kind_icon("dir", 16), e.name)
            it.setData(p, Qt.ItemDataRole.UserRole)
            it.setEditable(False)
            ph = QStandardItem("…")
            ph.setData(None, Qt.ItemDataRole.UserRole)
            it.appendRow(ph)
            node.appendRow(it)
            self.nodes[p] = it

    def selected_paths(self):
        return [(listing.join(self.path, e.name), e) for e in self.view.selected_entries()]

    def refresh(self):
        if self.path:
            self.cache.pop(self.path, None)
            self.navigate.emit(self.path)
