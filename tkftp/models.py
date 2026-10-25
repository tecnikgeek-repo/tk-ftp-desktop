"""Modelli Qt: elenco file (locale e remoto, cartelle sempre in cima) e coda trasferimenti."""
import json
import os
import time

from PySide6.QtCore import QAbstractTableModel, QByteArray, QMetaType, QMimeData, QModelIndex, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from tkftp import transfers
from tkftp.listing import Entry
from tkftp.style import ACCENT, ACCENT_D, GRAY_200, GRAY_500, GREEN, NAVY, RED, ic, kind_icon
from tkftp.util import human_size, human_speed

MIME_REMOTE = "application/x-tkftp-remote"
MIME_LOCAL = "application/x-tkftp-local"
PARENT = ".."


def fmt_time(t):
    if not t:
        return ""
    lt = time.localtime(t)
    return time.strftime("%d/%m/%y %H:%M", lt)  # anno a 2 cifre: colonna più stretta, più spazio ai nomi


class FileModel(QAbstractTableModel):
    """Voci di una cartella. remote=True aggiunge le colonne Permessi e Proprietario."""

    def __init__(self, remote=False, parent=None):
        super().__init__(parent)
        self.remote = remote
        self.cols = ["Nome", "Dimensione", "Tipo", "Modificato"] + (["Permessi", "Proprietario"] if remote else [])
        self.entries = []
        self.folder = ""
        self.show_parent = False
        self._sort = (0, Qt.SortOrder.AscendingOrder)
        self.drag_out = None  # fn(payload) -> percorsi locali: trascinamento verso Esplora file/Finder

    def set_entries(self, folder, entries, show_parent):
        self.beginResetModel()
        self.folder = folder
        self.entries = list(entries)
        self.show_parent = show_parent
        self._apply_sort()
        self.endResetModel()

    def rows(self):
        return ([Entry(PARENT, True)] if self.show_parent else []) + self.entries

    def entry(self, row):
        r = self.rows()
        return r[row] if 0 <= row < len(r) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries) + (1 if self.show_parent else 0)

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.cols[section].upper()
        if role == Qt.ItemDataRole.TextAlignmentRole and section == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        e = self.entry(index.row())
        if e is None:
            return None
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if e.name == PARENT:
                return ".." if c == 0 else ""
            if c == 0:
                return e.name
            if c == 1:
                return "" if e.is_dir else human_size(e.size)
            if c == 2:
                return e.type_label
            if c == 3:
                return fmt_time(e.mtime)
            if c == 4:
                return (("d" if e.is_dir else ("l" if e.is_link else "-")) + e.perms) if e.perms else ""
            if c == 5:
                return e.owner
        elif role == Qt.ItemDataRole.DecorationRole and c == 0:
            return kind_icon("parent" if e.name == PARENT else e.kind)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c == 1:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ForegroundRole and c > 0:
            return QColor(GRAY_500)
        elif role == Qt.ItemDataRole.FontRole and c in (4,):
            f = QFont("Consolas")
            f.setStyleHint(QFont.StyleHint.Monospace)
            return f
        elif role == Qt.ItemDataRole.ToolTipRole and c == 0 and e.name != PARENT:
            tip = e.name
            if e.is_link and e.link_target:
                tip += f"  →  {e.link_target}"
            if not e.is_dir:
                tip += f"\n{human_size(e.size)} · {fmt_time(e.mtime)}"
            return tip
        elif role == Qt.ItemDataRole.UserRole:
            return e
        return None

    def flags(self, index):
        f = super().flags(index)
        if index.isValid():
            e = self.entry(index.row())
            f |= Qt.ItemFlag.ItemIsDropEnabled
            if e and e.name != PARENT:
                f |= Qt.ItemFlag.ItemIsDragEnabled
        else:
            f |= Qt.ItemFlag.ItemIsDropEnabled
        return f

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        self._sort = (column, order)
        self._apply_sort()
        self.layoutChanged.emit()

    def _apply_sort(self):
        col, order = self._sort
        rev = order == Qt.SortOrder.DescendingOrder
        keyf = {
            0: lambda e: e.name.lower(),
            1: lambda e: (e.size, e.name.lower()),
            2: lambda e: (e.ext, e.name.lower()),
            3: lambda e: (e.mtime, e.name.lower()),
            4: lambda e: (e.perms, e.name.lower()),
            5: lambda e: (e.owner.lower(), e.name.lower()),
        }[col]
        dirs = sorted([e for e in self.entries if e.is_dir], key=keyf, reverse=rev)
        files = sorted([e for e in self.entries if not e.is_dir], key=keyf, reverse=rev)
        self.entries = dirs + files  # cartelle sempre in cima, come in FileZilla

    # -------------------------------------------------- trascinamento
    def supportedDropActions(self):
        return Qt.DropAction.CopyAction

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction

    def mimeTypes(self):
        return [MIME_REMOTE if self.remote else MIME_LOCAL, "text/uri-list"]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes})
        ents = [self.entry(r) for r in rows]
        ents = [e for e in ents if e and e.name != PARENT]
        if self.remote:
            payload = [{"path": (self.folder.rstrip("/") + "/" + e.name) if self.folder != "/" else "/" + e.name,
                        "is_dir": e.is_dir, "size": e.size, "mtime": e.mtime} for e in ents]
            if self.drag_out:
                return LazyRemoteMime(payload, self.drag_out)
            md = QMimeData()
            md.setData(MIME_REMOTE, json.dumps(payload).encode("utf-8"))
        else:
            md = QMimeData()
            paths = [os.path.join(self.folder, e.name) for e in ents]
            md.setData(MIME_LOCAL, json.dumps(paths).encode("utf-8"))
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return md


class LazyRemoteMime(QMimeData):
    """File del server trascinati fuori dal programma (Esplora file, Finder, altre app).
    Annuncia «text/uri-list» ma scarica solo quando chi riceve chiede i dati, cioè al rilascio: Qt chiama
    retrieveData dentro il trascinamento; qui lo scaricamento passa dalla coda (avanzamento visibile) e un ciclo
    di eventi annidato tiene viva l'interfaccia finché i file sono pronti in una cartella temporanea.
    Dentro tk-ftp (pannello del computer) vale invece il formato interno MIME_REMOTE, senza scaricare due volte."""

    def __init__(self, payload, provider):
        super().__init__()
        self.payload = payload
        self.provider = provider
        self.setData(MIME_REMOTE, json.dumps(payload).encode("utf-8"))
        self._paths = None
        self._busy = False

    def formats(self):
        return [MIME_REMOTE, "text/uri-list"]

    def hasFormat(self, mime):
        return mime in self.formats()

    def retrieveData(self, mime, preferred):
        if mime == "text/uri-list":
            if self._paths is None and not self._busy:
                self._busy = True
                try:
                    self._paths = list(self.provider(self.payload) or [])
                finally:
                    self._busy = False
            urls = [QUrl.fromLocalFile(p) for p in (self._paths or [])]
            try:
                want_bytes = preferred.id() == QMetaType.Type.QByteArray.value
            except Exception:
                want_bytes = False
            if want_bytes:
                text = "".join(u.toString(QUrl.ComponentFormattingOption.FullyEncoded) + "\r\n" for u in urls)
                return QByteArray(text.encode("utf-8"))
            return urls  # QMimeData.urls() (e quindi CF_HDROP su Windows) vuole una lista di QUrl, non testo
        return super().retrieveData(mime, preferred)


# --------------------------------------------------------------------------- coda
QUEUE_TABS = {
    "coda": (transfers.WAITING, transfers.RUNNING),
    "falliti": (transfers.FAILED, transfers.CANCELLED),
    "completati": (transfers.DONE, transfers.SKIPPED),
}


class QueueModel(QAbstractTableModel):
    cols = ["File", "Da → A", "Dimensione", "Avanzamento", "Stato"]

    def __init__(self, manager, tab="coda", parent=None):
        super().__init__(parent)
        self.manager = manager
        self.tab = tab
        self.items = []

    def refresh(self):
        with self.manager.lock:
            wanted = QUEUE_TABS[self.tab]
            new = [it for it in self.manager.items if it.status in wanted]
        if self.tab == "completati":
            new.sort(key=lambda it: -(it.finished or 0))
        if [id(x) for x in new] == [id(x) for x in self.items]:
            if new:
                self.dataChanged.emit(self.index(0, 0), self.index(len(new) - 1, len(self.cols) - 1))
            return False
        self.beginResetModel()
        self.items = new
        self.endResetModel()
        return True

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.cols[section].upper()
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not (0 <= index.row() < len(self.items)):
            return None
        it = self.items[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return it.name + ("  (cartella)" if it.is_dir else "")
            if c == 1:
                ldir = it.local if it.is_dir else os.path.dirname(it.local)
                rdir = it.remote if it.is_dir else (it.remote.rsplit("/", 1)[0] or "/")
                server = f"{it.site.title}  {rdir}"
                return f"{ldir}   →   {server}" if it.direction == "up" else f"{server}   →   {ldir}"
            if c == 2:
                return human_size(it.size) if it.size else ""
            if c == 4:
                if it.status == transfers.FAILED:
                    return it.error or "Non riuscito"
                return transfers.STATUS_LABEL.get(it.status, it.status)
        elif role == Qt.ItemDataRole.DecorationRole and c == 0:
            return ic("upload" if it.direction == "up" else "download", ACCENT_D if it.direction == "up" else "#2563eb", 16)
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 4 and it.status == transfers.FAILED:
                return QColor(RED)
            if c == 4 and it.status == transfers.DONE:
                return QColor("#047857")
            if c in (1, 2):
                return QColor(GRAY_500)
        elif role == Qt.ItemDataRole.ToolTipRole:
            return f"{it.name}\nLocale: {it.local}\nServer: {it.site.title} {it.remote}" + (
                f"\nErrore: {it.error}" if it.error else "")
        elif role == Qt.ItemDataRole.UserRole:
            return it
        return None


class ProgressDelegate(QStyledItemDelegate):
    """Colonna «Avanzamento»: barra arrotondata navy → rame con percentuale e velocità."""

    def paint(self, painter, option, index):
        it = index.data(Qt.ItemDataRole.UserRole)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#fbefd9"))
        if it is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 0, -6, 0)
        bar = QRectF(r.left(), r.center().y() - 4, min(130.0, r.width() * .5), 8)
        path = QPainterPath()
        path.addRoundedRect(bar, 4, 4)
        painter.fillPath(path, QColor(GRAY_200))
        frac = it.fraction
        if frac > 0:
            done = QRectF(bar.left(), bar.top(), max(8.0, bar.width() * frac), bar.height())
            dp = QPainterPath()
            dp.addRoundedRect(done, 4, 4)
            col = {transfers.FAILED: QColor(RED), transfers.DONE: QColor(GREEN)}.get(it.status)
            if col is None:
                from PySide6.QtGui import QLinearGradient
                g = QLinearGradient(done.topLeft(), done.topRight())
                g.setColorAt(0, QColor(NAVY))
                g.setColorAt(1, QColor(ACCENT))
                painter.fillPath(dp, g)
            else:
                painter.fillPath(dp, col)
        txt = f"{int(frac * 100)}%"
        if it.status == transfers.RUNNING and it.speed:
            txt += f" · {human_speed(it.speed)}"
        painter.setPen(QColor(NAVY if it.status == transfers.RUNNING else GRAY_500))
        tr = QRectF(bar.right() + 10, r.top(), r.right() - bar.right() - 10, r.height())
        painter.drawText(tr, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), txt)
        painter.restore()
