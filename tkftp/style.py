"""Aspetto di tk-ftp: colori TK (navy + rame #E39A2E come l'app telefono), foglio di stile, icone disegnate
a mano (niente emoji), finestre di dialogo nel nostro stile e ponte thread → interfaccia."""
import math
import os
import sys

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QVBoxLayout,
)

NAVY = "#0f172a"
NAVY_2 = "#1e293b"
NAVY_3 = "#334155"
ACCENT = "#e39a2e"
ACCENT_D = "#b9741a"
ACCENT_H = "#f2b453"      # parte alta del gradiente dei pulsanti
ACCENT_L = "#fbefd9"
ACCENT_LL = "#fdf7ec"
GREEN = "#10b981"
GREEN_L = "#d1fae5"
RED = "#ef4444"
RED_L = "#fee2e2"
BLUE = "#3b82f6"
VIOLET = "#7c3aed"
GRAY_50 = "#f8fafc"
GRAY_100 = "#f1f5f9"
GRAY_200 = "#e2e8f0"
GRAY_300 = "#cbd5e1"
GRAY_400 = "#94a3b8"
GRAY_500 = "#64748b"
GRAY_700 = "#334155"
BG = "#e9edf4"

PROTO_COLOR = {"FTP": "#2e5bff", "FTPS": GREEN, "SFTP": VIOLET}

STYLE = f"""
QMainWindow {{ background:{BG}; }}
QWidget {{ font-size:13px; color:{NAVY}; }}
QWidget#canvas {{ background:transparent; }}
QScrollArea {{ background:transparent; border:0; }}
QFrame#header {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {NAVY},stop:0.6 #16223b,stop:1 #24324d); border-radius:16px; }}
QFrame#card {{ background:#ffffff; border-radius:16px; }}
QFrame#qc {{ background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.10); border-radius:13px; }}
QLabel#brand {{ color:#fff; font-size:19px; font-weight:800; }}
QLabel#ver {{ color:{GRAY_300}; font-size:11px; }}
QLabel#cardtitle {{ color:{NAVY}; font-size:12px; font-weight:800; letter-spacing:1.5px; }}
QLabel#cardsub {{ color:{GRAY_500}; font-size:12px; }}
QLabel#hint {{ color:{GRAY_500}; font-size:11px; }}
QLabel#field {{ color:{GRAY_500}; font-size:11px; font-weight:700; }}
QLabel#qcl {{ color:{GRAY_400}; font-size:10px; font-weight:800; letter-spacing:1px; }}
QLabel#icobox {{ background:{ACCENT_L}; border-radius:10px; }}
QLabel#pillok {{ background:{GREEN_L}; color:#065f46; border-radius:11px; padding:3px 11px; font-size:11px; font-weight:800; }}
QLabel#pilloff {{ background:{GRAY_100}; color:{GRAY_500}; border-radius:11px; padding:3px 11px; font-size:11px; font-weight:800; }}
QLabel#pillbusy {{ background:{ACCENT_L}; color:{ACCENT_D}; border-radius:11px; padding:3px 11px; font-size:11px; font-weight:800; }}
QLabel#proto {{ border-radius:8px; padding:2px 8px; font-size:10px; font-weight:800; color:#fff; }}
QPushButton {{ background:#fff; border:1px solid {GRAY_300}; border-radius:10px; padding:0 14px; min-height:34px; color:{NAVY}; font-weight:600; }}
QPushButton:hover {{ background:{GRAY_100}; border-color:{GRAY_400}; }}
QPushButton:disabled {{ color:{GRAY_300}; background:{GRAY_50}; border-color:{GRAY_200}; }}
QPushButton#ghost {{ background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.14); color:#fff; }}
QPushButton#ghost:hover {{ background:rgba(255,255,255,.18); }}
QPushButton#ghost:disabled {{ color:rgba(255,255,255,.35); }}
QPushButton#accent {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {ACCENT_H},stop:1 {ACCENT_D}); border:0; color:#fff; font-weight:800; padding:0 18px; }}
QPushButton#accent:hover {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f6c470,stop:1 {ACCENT}); }}
QPushButton#accent:disabled {{ background:{GRAY_300}; color:#fff; }}
QPushButton#navy {{ background:{NAVY}; border:0; color:#fff; font-weight:800; padding:0 16px; }}
QPushButton#navy:hover {{ background:{NAVY_3}; }}
QPushButton#light {{ background:#fff; border:0; color:{NAVY}; font-weight:800; padding:0 16px; }}
QPushButton#light:hover {{ background:{ACCENT_L}; }}
QPushButton#mini {{ min-width:34px; max-width:34px; min-height:34px; max-height:34px; padding:0; border-radius:10px; }}
QPushButton#flat {{ background:transparent; border:0; min-width:32px; max-width:32px; min-height:32px; max-height:32px; padding:0; border-radius:9px; }}
QPushButton#flat:hover {{ background:{GRAY_100}; }}
QPushButton#flat:disabled {{ background:transparent; }}
QPushButton#danger {{ color:#b91c1c; }}
QPushButton#danger:hover {{ background:{RED_L}; border-color:{RED}; }}
QPushButton#tab {{ background:transparent; border:0; border-radius:10px; min-height:32px; padding:0 12px; color:{GRAY_500}; font-weight:700; }}
QPushButton#tab:hover {{ background:{GRAY_100}; color:{NAVY}; }}
QPushButton#tab:checked {{ background:{NAVY}; color:#fff; }}
QPushButton#recent {{ background:#fff; border:1px solid {GRAY_200}; border-radius:14px; text-align:left; padding:10px 14px; min-height:54px; }}
QPushButton#recent:hover {{ border-color:{ACCENT}; background:{ACCENT_LL}; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit#notes {{ background:{GRAY_50}; border:1px solid {GRAY_200}; border-radius:10px; padding:0 12px; min-height:36px; selection-background-color:{ACCENT}; }}
QPlainTextEdit#notes {{ padding:6px 10px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit#notes:focus {{ background:#fff; border:1px solid {ACCENT}; }}
QLineEdit#path {{ background:{GRAY_50}; font-family:Consolas,'SF Mono',Menlo,'DejaVu Sans Mono',monospace; font-size:12px; }}
QLineEdit#qc {{ background:rgba(255,255,255,.95); border:0; border-radius:9px; min-height:32px; padding:0 10px; }}
QLineEdit#qc:focus {{ background:#fff; }}
QComboBox#qc {{ background:rgba(255,255,255,.95); border:0; border-radius:9px; min-height:32px; padding:0 10px; font-weight:700; }}
QComboBox::drop-down {{ border:0; width:24px; }}
QComboBox QAbstractItemView {{ background:#fff; border:1px solid {GRAY_200}; selection-background-color:{ACCENT_L}; selection-color:{NAVY}; outline:0; padding:4px; }}
QSpinBox {{ padding-right:4px; }}
QCheckBox {{ spacing:8px; }}
QCheckBox::indicator {{ width:18px; height:18px; border-radius:5px; border:1px solid {GRAY_300}; background:#fff; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT_D}; image:url(__CHECK__); }}
QTreeView {{ background:#fff; border:1px solid {GRAY_200}; border-radius:12px; outline:0; alternate-background-color:#fbfcfe; selection-background-color:{ACCENT_L}; selection-color:{NAVY}; show-decoration-selected:1; }}
QTreeView::item {{ min-height:28px; padding:0 4px; border:0; }}
QTreeView::item:hover {{ background:{ACCENT_LL}; }}
QTreeView::item:selected {{ background:{ACCENT_L}; color:{NAVY}; }}
QTreeView#tree {{ background:{GRAY_50}; }}
QTreeView#tree::item {{ min-height:26px; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:{GRAY_50}; border:0; border-bottom:1px solid {GRAY_200}; padding:7px 6px; color:{GRAY_500}; font-size:11px; font-weight:800; }}
QHeaderView::section:hover {{ color:{NAVY}; }}
QSplitter::handle {{ background:transparent; }}
QPlainTextEdit#log {{ background:{NAVY}; color:#e2e8f0; border:0; border-radius:12px; padding:8px 10px; font-family:Consolas,'SF Mono',Menlo,'DejaVu Sans Mono',monospace; font-size:12px; selection-background-color:{ACCENT_D}; }}
QMenu {{ background:#fff; border:1px solid {GRAY_200}; border-radius:12px; padding:6px; }}
QMenu::item {{ padding:7px 26px 7px 12px; border-radius:8px; }}
QMenu::item:selected {{ background:{ACCENT_L}; color:{NAVY}; }}
QMenu::item:disabled {{ color:{GRAY_300}; }}
QMenu::separator {{ height:1px; background:{GRAY_200}; margin:5px 8px; }}
QMenu::icon {{ padding-left:8px; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{GRAY_300}; border-radius:5px; min-height:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{GRAY_300}; border-radius:5px; min-width:30px; }}
QPlainTextEdit#log QScrollBar::handle:vertical {{ background:{NAVY_3}; }}
QStatusBar {{ background:transparent; color:{GRAY_500}; }}
QStatusBar::item {{ border:0; }}
QToolTip {{ background:{NAVY}; color:#fff; border:0; padding:5px 8px; }}
QDialog#tk {{ background:transparent; }}
QFrame#tkcard {{ background:{NAVY}; border-radius:20px; border:1px solid {NAVY_3}; }}
QFrame#lightcard {{ background:#eef2f7; border-radius:20px; border:1px solid {GRAY_300}; }}
QFrame#lighthead {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {NAVY},stop:1 #24324d); border-top-left-radius:20px; border-top-right-radius:20px; }}
QDialog#tk QProgressBar {{ background:{NAVY_2}; border:0; border-radius:5px; }}
QDialog#tk QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {ACCENT_D},stop:1 {ACCENT_H}); border-radius:5px; }}
QFrame#tkcard QLabel {{ color:#fff; }}
QFrame#tkcard QFrame#acard {{ background:{NAVY_2}; border-radius:14px; }}
QFrame#tkcard QLabel#atitle {{ color:{ACCENT}; font-size:11px; font-weight:800; letter-spacing:1.5px; }}
QFrame#tkcard QLabel#asub {{ color:{GRAY_300}; }}
QFrame#tkcard QLabel#mono {{ font-family:Consolas,'SF Mono',Menlo,'DejaVu Sans Mono',monospace; font-size:12px; color:#fde68a; }}
QFrame#tkcard QLineEdit, QFrame#tkcard QSpinBox, QFrame#tkcard QComboBox {{ background:{NAVY_2}; border:1px solid {NAVY_3}; color:#fff; }}
QFrame#tkcard QLineEdit:focus, QFrame#tkcard QSpinBox:focus, QFrame#tkcard QComboBox:focus {{ border:1px solid {ACCENT}; background:#26344d; }}
QFrame#tkcard QComboBox QAbstractItemView {{ background:{NAVY_2}; color:#fff; border:1px solid {NAVY_3}; selection-background-color:{ACCENT_D}; selection-color:#fff; }}
QFrame#tkcard QCheckBox {{ color:#fff; }}
QFrame#tkcard QCheckBox::indicator {{ background:{NAVY_2}; border-color:{NAVY_3}; }}
QFrame#tkcard QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QFrame#tkcard QPushButton#choice {{ background:{NAVY_2}; border:1px solid {NAVY_3}; color:#fff; text-align:left; padding:0 14px; min-height:40px; border-radius:12px; }}
QFrame#tkcard QPushButton#choice:hover {{ border-color:{ACCENT}; background:#26344d; }}
QFrame#tkcard QPushButton#choice:default {{ border-color:{ACCENT}; }}
"""


def stylesheet(check_png):
    return STYLE.replace("__CHECK__", check_png.replace("\\", "/"))


# --------------------------------------------------------------------------- icone
_icon_cache = {}


def ic(name, color="#ffffff", size=20):
    """Icone a tratto disegnate a mano (stessa famiglia di tk-listino)."""
    key = (name, color, size)
    if key in _icon_cache:
        return _icon_cache[key]
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * 2 / 24, size * 2 / 24)
    pen = QPen(QColor(color), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    L = lambda *a: p.drawLine(QPointF(a[0], a[1]), QPointF(a[2], a[3]))  # noqa: E731
    R = lambda x, y, w, h, r=2: p.drawRoundedRect(QRectF(x, y, w, h), r, r)  # noqa: E731
    C = lambda x, y, r: p.drawEllipse(QPointF(x, y), r, r)  # noqa: E731

    def poly(*pts, close=False):
        path = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(QPointF(*pt))
        if close:
            path.closeSubpath()
        p.drawPath(path)

    if name == "plus":
        L(12, 5, 12, 19); L(5, 12, 19, 12)
    elif name == "close":
        L(7, 7, 17, 17); L(17, 7, 7, 17)
    elif name == "check":
        poly((5, 12.5), (10, 17), (19, 7))
    elif name == "up":
        poly((6, 14), (12, 8), (18, 14))
    elif name == "down":
        poly((6, 10), (12, 16), (18, 10))
    elif name == "right":
        poly((10, 6), (16, 12), (10, 18))
    elif name == "copy":
        R(9, 9, 11, 11); poly((15, 9), (15, 5), (5, 5), (5, 15), (9, 15))
    elif name == "trash":
        L(5, 7, 19, 7); R(7, 7, 10, 13); poly((9, 7), (9, 4), (15, 4), (15, 7)); L(10, 11, 10, 17); L(14, 11, 14, 17)
    elif name == "folder":
        poly((3, 7), (3, 19), (21, 19), (21, 9), (11, 9), (9, 6), (3, 6), (3, 7))
    elif name == "folder-plus":
        poly((3, 7), (3, 19), (21, 19), (21, 9), (11, 9), (9, 6), (3, 6), (3, 7)); L(12, 11.5, 12, 16.5); L(9.5, 14, 14.5, 14)
    elif name == "parent":
        poly((9, 14), (4, 9), (9, 4)); poly((4, 9), (14, 9), (20, 15), (20, 20))
    elif name == "home":
        poly((3, 11), (12, 4), (21, 11)); poly((6, 9.5), (6, 20), (18, 20), (18, 9.5)); R(10, 14, 4, 6, 1)
    elif name == "refresh":
        p.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 270 * 16); poly((17, 3), (19, 8), (14, 9))
    elif name == "upload":
        L(12, 15, 12, 4); poly((7, 9), (12, 4), (17, 9)); poly((4, 15), (4, 20), (20, 20), (20, 15))
    elif name == "download":
        L(12, 4, 12, 15); poly((7, 10), (12, 15), (17, 10)); poly((4, 15), (4, 20), (20, 20), (20, 15))
    elif name == "server":
        R(4, 4, 16, 7, 2); R(4, 13, 16, 7, 2); L(8, 7.5, 8.1, 7.5); L(8, 16.5, 8.1, 16.5); L(13, 7.5, 16, 7.5); L(13, 16.5, 16, 16.5)
    elif name == "plug":
        L(9, 3, 9, 7); L(15, 3, 15, 7); poly((6, 7), (18, 7), (18, 11), (15, 15), (9, 15), (6, 11), (6, 7)); L(12, 15, 12, 21)
    elif name == "unplug":
        L(9, 3, 9, 7); L(15, 3, 15, 7); poly((6, 7), (18, 7), (18, 11), (15, 15), (9, 15), (6, 11), (6, 7)); L(12, 15, 12, 21); L(3, 3, 21, 21)
    elif name == "key":
        C(8, 15, 4); L(11, 12, 20, 3); L(17, 6, 20, 9); L(15, 8, 17, 10)
    elif name == "lock":
        R(5, 11, 14, 10, 3); p.drawArc(QRectF(8, 4, 8, 12), 0, 180 * 16); L(8, 10, 8, 11); L(16, 10, 16, 11); L(12, 15, 12, 17)
    elif name == "shield":
        poly((12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6), close=True); poly((8.5, 12), (11, 14.5), (15.5, 9.5))
    elif name == "eye":
        path = QPainterPath(QPointF(2, 12)); path.quadTo(12, 3, 22, 12); path.quadTo(12, 21, 2, 12); p.drawPath(path); C(12, 12, 3)
    elif name == "search":
        C(10.5, 10.5, 6.5); L(15.5, 15.5, 20, 20)
    elif name == "edit":
        poly((4, 20), (4, 16), (15, 5), (19, 9), (8, 20), (4, 20)); L(13, 7, 17, 11)
    elif name == "info":
        C(12, 12, 9); L(12, 11, 12, 17); L(12, 7.5, 12, 7.6)
    elif name == "gear":
        C(12, 12, 3); C(12, 12, 6.5)
        for k in range(8):
            a = k * math.pi / 4
            L(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a), 12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a))
    elif name == "alert":
        poly((12, 3), (22, 20), (2, 20), (12, 3)); L(12, 10, 12, 14); L(12, 17, 12, 17.1)
    elif name == "help":
        C(12, 12, 9); L(12, 17, 12, 17.1); p.drawArc(QRectF(9, 7, 6, 6), 120 * 16, -250 * 16)
    elif name == "list":
        for y in (6, 12, 18):
            L(9, y, 20, y); L(4.5, y, 4.6, y)
    elif name == "terminal":
        R(3, 4, 18, 16, 3); poly((7, 9), (10, 12), (7, 15)); L(12, 15, 16, 15)
    elif name == "stop":
        R(6, 6, 12, 12, 2)
    elif name == "retry":
        p.drawArc(QRectF(4, 4, 16, 16), 90 * 16, 270 * 16); poly((9, 1.5), (12, 4), (9, 6.5))
    elif name == "broom":
        L(15, 3, 10, 12); poly((6, 12), (14, 12), (17, 21), (3, 21), close=True); L(8, 16, 7, 21); L(12, 16, 12, 21)
    elif name == "import":
        L(12, 3, 12, 14); poly((7, 9), (12, 14), (17, 9)); poly((4, 14), (4, 20), (20, 20), (20, 14))
    elif name == "export":
        L(12, 14, 12, 3); poly((7, 8), (12, 3), (17, 8)); poly((4, 14), (4, 20), (20, 20), (20, 14))
    elif name == "share":
        C(6, 12, 2.5); C(18, 6, 2.5); C(18, 18, 2.5); L(8.2, 10.8, 15.8, 7.2); L(8.2, 13.2, 15.8, 16.8)
    elif name == "cloud":
        path = QPainterPath(QPointF(7, 18)); path.cubicTo(1, 18, 2, 10, 8, 11); path.cubicTo(9, 5, 17, 5, 17, 11)
        path.cubicTo(23, 11, 23, 18, 17, 18); path.closeSubpath(); p.drawPath(path)
    elif name == "monitor":
        R(3, 4, 18, 12, 2); L(9, 20, 15, 20); L(12, 16, 12, 20)
    elif name == "globe":
        C(12, 12, 9); p.drawEllipse(QRectF(8, 3, 8, 18)); L(3, 12, 21, 12)
    elif name == "swap":
        L(7, 4, 7, 18); poly((3, 8), (7, 4), (11, 8)); L(17, 20, 17, 6); poly((13, 16), (17, 20), (21, 16))
    elif name == "link":
        p.drawArc(QRectF(3, 8, 10, 8), 90 * 16, 180 * 16); p.drawArc(QRectF(11, 8, 10, 8), -90 * 16, 180 * 16); L(8, 12, 16, 12)
        L(8, 8, 10, 8); L(8, 16, 10, 16); L(14, 8, 16, 8); L(14, 16, 16, 16)
    elif name == "file":
        poly((6, 3), (14, 3), (19, 8), (19, 21), (6, 21), (6, 3)); poly((14, 3), (14, 8), (19, 8))
    elif name == "file-plus":
        poly((6, 3), (14, 3), (19, 8), (19, 21), (6, 21), (6, 3)); L(12.5, 11, 12.5, 17); L(9.5, 14, 15.5, 14)
    elif name == "clock":
        C(12, 12, 9); poly((12, 7), (12, 12), (15.5, 14))
    elif name == "user":
        C(12, 8, 4); p.drawArc(QRectF(4, 13, 16, 14), 0, 180 * 16)
    elif name == "open":
        poly((3, 7), (3, 19), (19, 19), (21, 11), (8, 11), (6, 19)); poly((3, 7), (9, 7), (11, 9), (18, 9), (18, 11))
    elif name == "image":
        R(3, 4, 18, 16, 3); C(9, 10, 2); poly((4, 19), (10, 13), (14, 17), (17, 14), (21, 18))
    elif name == "dot":
        p.setBrush(QColor(color)); C(12, 12, 4)
    p.end()
    pm.setDevicePixelRatio(2)
    icon = QIcon(pm)
    _icon_cache[key] = icon
    return icon


KIND_COLOR = {"code": "#3b82f6", "text": "#64748b", "image": "#10b981", "archive": "#d97706", "doc": "#ef4444",
              "media": "#7c3aed", "file": "#94a3b8"}
_kind_cache = {}


def kind_icon(kind, size=18):
    """Icona piena per gli elenchi: cartella rame, file con la piega colorata secondo il tipo."""
    key = (kind, size)
    if key in _kind_cache:
        return _kind_cache[key]
    s = size * 2
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    if kind in ("dir", "parent"):
        p.setBrush(QColor(ACCENT_D))
        p.drawRoundedRect(QRectF(s * .08, s * .18, s * .40, s * .22), s * .05, s * .05)
        g = QLinearGradient(0, s * .25, 0, s * .85)
        g.setColorAt(0, QColor(ACCENT_H))
        g.setColorAt(1, QColor(ACCENT))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(s * .08, s * .28, s * .84, s * .56), s * .08, s * .08)
        if kind == "parent":
            pen = QPen(QColor("#ffffff"), s * .08)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(s * .36, s * .62))
            path.lineTo(QPointF(s * .50, s * .46))
            path.lineTo(QPointF(s * .64, s * .62))
            p.drawPath(path)
    else:
        col = QColor(KIND_COLOR.get(kind, KIND_COLOR["file"]))
        body = QPainterPath()
        body.moveTo(s * .2, s * .1)
        body.lineTo(s * .58, s * .1)
        body.lineTo(s * .82, s * .34)
        body.lineTo(s * .82, s * .9)
        body.lineTo(s * .2, s * .9)
        body.closeSubpath()
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(GRAY_300), s * .045))
        p.drawPath(body)
        p.setPen(Qt.PenStyle.NoPen)
        fold = QPainterPath()
        fold.moveTo(s * .58, s * .1)
        fold.lineTo(s * .82, s * .34)
        fold.lineTo(s * .58, s * .34)
        fold.closeSubpath()
        p.setBrush(col.lighter(130))
        p.drawPath(fold)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(s * .12, s * .52, s * .5, s * .22), s * .05, s * .05)
    p.end()
    pm.setDevicePixelRatio(2)
    icon = QIcon(pm)
    _kind_cache[key] = icon
    return icon


def _draw_symbol(p, x0, y0, s, folder_color="#ffffff", badge=ACCENT, arrows="#ffffff"):
    """Simbolo di tk-ftp come l'icona dell'app telefono: cartella + bollino con le frecce su/giù."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(folder_color))
    p.drawRoundedRect(QRectF(x0 + s * .06, y0 + s * .16, s * .34, s * .26), s * .05, s * .05)
    p.drawRoundedRect(QRectF(x0 + s * .06, y0 + s * .24, s * .74, s * .52), s * .07, s * .07)
    if badge:
        cx, cy, r = x0 + s * .76, y0 + s * .74, s * .22
        p.setBrush(QColor(badge))
        p.drawEllipse(QPointF(cx, cy), r, r)
        w = s * .035
        pen = QPen(QColor(arrows), w)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        for dx, su in ((-.07, True), (.07, False)):
            x = cx + s * dx
            top, bottom = cy - s * .12, cy + s * .12
            p.setPen(pen)
            p.drawLine(QPointF(x, top + (s * .05 if su else 0)), QPointF(x, bottom - (0 if su else s * .05)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(arrows))
            tip = top if su else bottom
            v = 1 if su else -1
            tri = QPainterPath(QPointF(x, tip - v * w * .6))
            tri.lineTo(QPointF(x - s * .06, tip + v * s * .07))
            tri.lineTo(QPointF(x + s * .06, tip + v * s * .07))
            tri.closeSubpath()
            p.drawPath(tri)


def render_icon(size=64):
    """Icona del programma (barra delle applicazioni, collegamenti): quadrato navy, cartella bianca, bollino rame."""
    img = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size * 2
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, QColor(NAVY_2))
    g.setColorAt(1, QColor(NAVY))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(0, 0, s, s), s * .24, s * .24)
    _draw_symbol(p, s * .14, s * .12, s * .76)
    p.end()
    pm = QPixmap.fromImage(img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
    return pm


def logo_tile(size=44):
    """Logo per testata e Informazioni (come LogoTk delle app): quadrato col gradiente rame, simbolo bianco."""
    s = size * 2
    img = QImage(s, s, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor(ACCENT_H))
    g.setColorAt(1, QColor(ACCENT_D))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(0, 0, s, s), s * .28, s * .28)
    _draw_symbol(p, s * .17, s * .15, s * .70, "#ffffff", NAVY, "#ffffff")
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(2)
    return pm


def check_png(path):
    """Spunta bianca per le caselle (il foglio di stile vuole un file)."""
    pm = ic("check", "#ffffff", 14).pixmap(28, 28)
    pm.save(path, "PNG")
    return path


def shadow(widget, blur=30, dy=6, alpha=45):
    e = QGraphicsDropShadowEffect(widget)
    e.setBlurRadius(blur)
    e.setOffset(0, dy)
    e.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(e)


LOGOS = {"enabled": True}
_badge_cache = {}


def clear_badge_cache(site_id=None):
    for k in [k for k in _badge_cache if site_id is None or k[0] == site_id]:
        _badge_cache.pop(k, None)


def site_badge(site, size=22):
    """Badge del sito: il suo logo in un quadrato arrotondato (fondo bianco), oppure la lettera colorata.
    Disegnato a 3× (nitido anche su schermi ad alta risoluzione) e tenuto in memoria."""
    from tkftp import logos
    path = logos.logo_file(site.id) if LOGOS["enabled"] else ""
    stamp = os.path.getmtime(path) if path else 0
    key = (site.id, size, path, stamp, site.title[:1], site.protocol)
    if key in _badge_cache:
        return _badge_cache[key]
    dpr = 3
    s = size * dpr
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    radius = s * .28
    img = QImage(path) if path else QImage()
    if not img.isNull():
        p.setPen(QPen(QColor(GRAY_200), max(1.0, s * .03)))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(s * .015, s * .015, s * .97, s * .97), radius, radius)
        pad = s * .14
        box = s - 2 * pad
        sc = img.scaled(int(box), int(box), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QPointF((s - sc.width()) / 2, (s - sc.height()) / 2), sc)
    else:
        from tkftp.sites import PROTOCOL_SHORT
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PROTO_COLOR.get(PROTOCOL_SHORT.get(site.protocol, "FTP"), NAVY)))
        p.drawRoundedRect(QRectF(0, 0, s, s), radius, radius)
        p.setPen(QColor("#ffffff"))
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(s * .5))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), int(Qt.AlignmentFlag.AlignCenter), (site.title[:1] or "?").upper())
    p.end()
    pm.setDevicePixelRatio(dpr)
    _badge_cache[key] = pm
    return pm


def shadow_holder(card, left=12, top=4, right=12, bottom=16):
    """Contenitore trasparente con margini attorno a una card con ombra. L'ombra di QGraphicsDropShadowEffect viene
    tagliata dal rettangolo del widget padre: se il padre (es. uno splitter) finisce esattamente sul bordo della card,
    sotto gli angoli arrotondati resta un taglio dritto. Qui l'ombra ha spazio per sfumare tutta."""
    from PySide6.QtWidgets import QWidget
    w = QWidget(objectName="canvas")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(left, top, right, bottom)
    lay.addWidget(card)
    return w


def mono_font(size=10):
    f = QFont("Consolas" if sys.platform == "win32" else "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(size)
    return f


def tool_btn(icon_name, tip, fn, color=NAVY, name="mini", size=18):
    b = QPushButton()
    b.setObjectName(name)
    b.setIcon(ic(icon_name, color, size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if fn:
        b.clicked.connect(fn)
    return b


def text_btn(icon_name, text, fn, color="#ffffff", name="ghost", tip=""):
    b = QPushButton(text)
    b.setObjectName(name)
    if icon_name:
        b.setIcon(ic(icon_name, color, 18))
        b.setIconSize(QSize(18, 18))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    if fn:
        b.clicked.connect(fn)
    return b


def field(text):
    return QLabel(text.upper(), objectName="field")


# --------------------------------------------------------------------------- ponte thread → interfaccia
class Bridge(QObject):
    """Porta le chiamate dai thread di rete al thread dell'interfaccia."""
    _post = Signal(object)
    _block = Signal(object)

    def __init__(self):
        super().__init__()
        self._post.connect(self._run, Qt.ConnectionType.QueuedConnection)
        self._block.connect(self._run, Qt.ConnectionType.BlockingQueuedConnection)

    @Slot(object)
    def _run(self, fn):
        fn()

    def post(self, fn):
        self._post.emit(fn)

    def wrap(self, fn):
        """Versione di fn chiamabile da qualsiasi thread: gira poi sul thread dell'interfaccia."""
        return lambda *a: self._post.emit(lambda: fn(*a))

    def call_blocking(self, fn):
        """Esegue fn sul thread dell'interfaccia e aspetta il risultato (da chiamare SOLO da un altro thread)."""
        box = {}

        def run():
            box["r"] = fn()
        self._block.emit(run)
        return box.get("r")


# --------------------------------------------------------------------------- finestre di dialogo TK
class TkDialog(QDialog):
    """Finestra nel nostro stile: scheda navy arrotondata con ombra, senza la barra di sistema."""

    def __init__(self, parent, width=460):
        super().__init__(parent)
        self.setObjectName("tk")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(width + 56)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 42)  # spazio per tutta l'ombra (blur 44, giù 12)
        self.card = QFrame(objectName="tkcard")
        shadow(self.card, 44, 12, 110)
        outer.addWidget(self.card)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(26, 24, 26, 24)
        self.body.setSpacing(14)
        self._drag = None

    def head(self, icon_pixmap, title, sub=""):
        row = QHBoxLayout()
        row.setSpacing(14)
        ico = QLabel()
        ico.setPixmap(icon_pixmap)
        ico.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(ico)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet("font-size:19px; font-weight:800; color:#ffffff;")
        col.addWidget(t)
        if sub:
            s = QLabel(sub)
            s.setObjectName("asub")
            s.setWordWrap(True)
            col.addWidget(s)
        row.addLayout(col, 1)
        self.body.addLayout(row)

    def info_card(self, title, value, mono=False):
        card = QFrame(objectName="acard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 11, 16, 11)
        cl.setSpacing(3)
        cl.addWidget(QLabel(title, objectName="atitle"))
        v = QLabel(value)
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if mono:
            v.setObjectName("mono")
        else:
            v.setStyleSheet("font-size:14px; font-weight:600;")
        cl.addWidget(v)
        self.body.addWidget(card)
        return v

    def buttons(self, specs):
        """specs = [(testo, stile, valore)]; ritorna la riga. Il valore scelto va in self.choice."""
        self.choice = None
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for label, style, value in specs:
            b = QPushButton(label)
            b.setObjectName(style)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._pick(v))
            if style == "accent":
                b.setDefault(True)
            row.addWidget(b)
        self.body.addLayout(row)
        return row

    def _pick(self, v):
        self.choice = v
        self.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def kind_badge(kind):
    names = {"info": ("info", "#7dd3fc"), "warn": ("alert", "#fbbf24"), "ask": ("help", ACCENT_H),
             "error": ("alert", "#fca5a5"), "key": ("key", ACCENT_H), "lock": ("lock", "#86efac"),
             "server": ("server", ACCENT_H), "share": ("share", ACCENT_H), "gear": ("gear", ACCENT_H),
             "upload": ("upload", ACCENT_H)}
    name, color = names.get(kind, names["info"])
    box = QPixmap(104, 104)
    box.fill(Qt.GlobalColor.transparent)
    p = QPainter(box)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 22))
    p.drawRoundedRect(0, 0, 104, 104, 32, 32)
    p.drawPixmap(20, 20, ic(name, color, 32).pixmap(64, 64))
    p.end()
    box.setDevicePixelRatio(2)
    return box


def tk_choice(parent, title, text, buttons, kind="ask", sub=""):
    """Domanda con più pulsanti [(testo, 'accent'|'ghost'|'danger')]. Ritorna l'indice scelto (-1 se chiusa)."""
    dlg = TkDialog(parent, 440)
    dlg.head(kind_badge(kind), title, sub)
    if text:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.RichText if text.startswith("<") else Qt.TextFormat.PlainText)
        lab.setStyleSheet("font-size:14px; color:#e2e8f0;")
        dlg.body.addWidget(lab)
    dlg.buttons([(label, "ghost" if style == "danger" else style, i) for i, (label, style) in enumerate(buttons)])
    dlg.exec()
    return -1 if dlg.choice is None else dlg.choice


def tk_input(parent, title, label, text="", ok="OK", password=False, remember=None, kind="ask"):
    """Chiede una riga di testo. Con remember=testo mostra una casella; ritorna (testo, casella) o None."""
    dlg = TkDialog(parent, 440)
    dlg.head(kind_badge(kind), title, label)
    edit = QLineEdit(text)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    dlg.body.addWidget(edit)
    box = None
    if remember:
        box = QCheckBox(remember)
        dlg.body.addWidget(box)
    edit.returnPressed.connect(lambda: dlg._pick("ok"))
    dlg.buttons([("Annulla", "ghost", None), (ok, "accent", "ok")])
    edit.setFocus()
    edit.selectAll()
    dlg.exec()
    if dlg.choice != "ok":
        return None
    return (edit.text(), box.isChecked() if box else False) if remember else edit.text()


def tk_info(parent, title, text):
    tk_choice(parent, title, text, [("OK", "accent")], "info")


def tk_warn(parent, title, text):
    tk_choice(parent, title, text, [("OK", "accent")], "warn")


class TkProgress(TkDialog):
    """Barra di avanzamento nel nostro stile (aggiornamento del programma)."""
    canceled = Signal()

    def __init__(self, parent, title, sub, cancelable=False):
        super().__init__(parent, 420)
        self.head(logo_tile(52), title, sub)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setRange(0, 0)
        self.body.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("asub")
        self.body.addWidget(self.status)
        if cancelable:
            row = QHBoxLayout()
            row.addStretch(1)
            b = QPushButton("Annulla")
            b.setObjectName("ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda: (self.canceled.emit(), self.close()))
            row.addWidget(b)
            self.body.addLayout(row)

    def set_progress(self, done, total, text=""):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
        self.status.setText(text)

    def set_status(self, text):
        self.status.setText(text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(e)
