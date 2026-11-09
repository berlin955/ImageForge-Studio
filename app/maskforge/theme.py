"""主题配色与样式表。"""
from __future__ import annotations

from string import Template

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPalette, QPen

from .config import data_dir

PALETTES = {
    "dark": {  # 深夜蓝
        "label": "深夜蓝", "is_dark": True,
        "bg": "#0f1116", "side": "#151821", "card": "#1b1f2a", "card2": "#232836", "hover": "#2a3040",
        "line": "#2a2f3d", "fg": "#e8eaf0", "muted": "#8c93a5", "accent": "#8fa3ff",
        "accent_ink": "#0b0f22", "accent_soft": "rgba(143,163,255,40)", "ok": "#4fc28a",
        "warn": "#e8b04c", "danger": "#ff6b6b", "stage": "#0a0c10",
    },
    "graphite": {  # 石墨金
        "label": "石墨金", "is_dark": True,
        "bg": "#121212", "side": "#181818", "card": "#1f1f1f", "card2": "#282828", "hover": "#303030",
        "line": "#323232", "fg": "#ecebe8", "muted": "#9a978f", "accent": "#f0b35a",
        "accent_ink": "#1d1407", "accent_soft": "rgba(240,179,90,40)", "ok": "#6cc58f",
        "warn": "#f0b35a", "danger": "#ff7b6b", "stage": "#0b0b0b",
    },
    "forest": {  # 墨绿
        "label": "墨绿", "is_dark": True,
        "bg": "#0d1411", "side": "#121b17", "card": "#17221d", "card2": "#1e2b25", "hover": "#25342d",
        "line": "#26352e", "fg": "#e4eee9", "muted": "#88a096", "accent": "#5fd3a0",
        "accent_ink": "#062016", "accent_soft": "rgba(95,211,160,38)", "ok": "#5fd3a0",
        "warn": "#e2c15a", "danger": "#ff7a7a", "stage": "#080d0b",
    },
    "plum": {  # 暮紫
        "label": "暮紫", "is_dark": True,
        "bg": "#120f18", "side": "#18141f", "card": "#1f1a28", "card2": "#282132", "hover": "#30283c",
        "line": "#30283b", "fg": "#ece8f3", "muted": "#9a91aa", "accent": "#c49bff",
        "accent_ink": "#1b0b33", "accent_soft": "rgba(196,155,255,40)", "ok": "#5ec99a",
        "warn": "#ebb35c", "danger": "#ff7591", "stage": "#0b090f",
    },
    "light": {  # 云白
        "label": "云白", "is_dark": False,
        "bg": "#eef0f4", "side": "#f8f9fb", "card": "#ffffff", "card2": "#f2f4f7", "hover": "#e8ebf1",
        "line": "#dde1e8", "fg": "#191c23", "muted": "#646c7b", "accent": "#4a60dc",
        "accent_ink": "#ffffff", "accent_soft": "rgba(74,96,220,28)", "ok": "#1d9560",
        "warn": "#b07c0c", "danger": "#d23c3c", "stage": "#d6d9e0",
    },
    "sakura": {  # 樱粉
        "label": "樱粉", "is_dark": False,
        "bg": "#f7eef1", "side": "#fdf7f9", "card": "#ffffff", "card2": "#f9eff3", "hover": "#f3e3e9",
        "line": "#ecd9e0", "fg": "#2a1d23", "muted": "#8a6f7a", "accent": "#d9567f",
        "accent_ink": "#ffffff", "accent_soft": "rgba(217,86,127,28)", "ok": "#2f9a6b",
        "warn": "#b9780f", "danger": "#d0384f", "stage": "#e7d8de",
    },
}

THEME_ORDER = ["dark", "graphite", "forest", "plum", "light", "sakura"]

_state = {"name": "dark"}


def current() -> dict:
    return PALETTES[_state["name"]]


def name() -> str:
    return _state["name"]


QSS = Template("""
* { font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif; font-size: 13px; outline: none; }
QWidget { color: $fg; }
QMainWindow, QDialog, #Workspace { background: $bg; }
#TopBar { background: $side; border-bottom: 1px solid $line; }
#Side { background: $side; border-right: 1px solid $line; }
#SideFoot { background: $side; border-top: 1px solid $line; }
#Toolbar { background: $bg; border-bottom: 1px solid $line; }
#FilmBar { background: $side; border-top: 1px solid $line; }

QLabel#Brand { font-size: 16px; font-weight: 700; }
QLabel#BrandSub { color: $muted; font-size: 10px; letter-spacing: 1px; }
QLabel#BigTitle { font-size: 22px; font-weight: 700; }
QLabel#Hero { font-size: 20px; font-weight: 700; }
QLabel#Muted { color: $muted; font-size: 12px; }
QLabel#Warn { color: $warn; font-size: 12px; }
QLabel#Count { color: $muted; font-size: 12px; }
QLabel#StickerPreview { background: $card2; border: 1px solid $line; border-radius: 9px; color: $muted; font-size: 18px; }

QFrame#Card, QFrame#Section { background: $card; border: 1px solid $line; border-radius: 12px; }
QFrame#Drop { background: $card; border: 2px dashed $line; border-radius: 14px; }
QLabel#CardTitle { color: $muted; font-size: 12px; font-weight: 700; }
QPushButton#SectionHead { background: transparent; border: none; text-align: left; padding: 2px 0;
                          font-size: 13px; font-weight: 700; color: $fg; }
QPushButton#SectionHead:hover { color: $accent; }

QPushButton { background: $card2; border: 1px solid $line; border-radius: 8px; padding: 7px 12px; min-height: 18px; }
QPushButton:hover { background: $hover; border-color: $accent; }
QPushButton:pressed { background: $line; }
QPushButton:disabled { color: $muted; border-color: $line; background: $card; }
QPushButton#Primary { background: $accent; color: $accent_ink; border: 1px solid $accent; font-weight: 700; }
QPushButton#Primary:hover { border-color: $fg; }
QPushButton#Primary:disabled { background: $card2; color: $muted; border-color: $line; }
QPushButton#Big { min-height: 26px; font-size: 14px; }
QPushButton#Danger { color: $danger; }
QPushButton#Ghost { background: transparent; border: 1px solid transparent; color: $muted; padding: 6px 8px; }
QPushButton#Ghost:hover { color: $fg; background: $hover; border-color: transparent; }
QPushButton#Link { background: transparent; border: none; color: $accent; padding: 2px; text-decoration: underline; }
QPushButton#Tool { background: transparent; border: 1px solid transparent; padding: 6px 10px; }
QPushButton#Tool:hover { background: $hover; border-color: $line; }
QPushButton#Tool:checked { background: $accent_soft; border-color: $accent; }
QPushButton#Chip { background: $card2; border: 1px solid $line; border-radius: 15px; padding: 6px 12px; font-weight: 600; }
QPushButton#Chip:hover { border-color: $accent; color: $accent; }
QPushButton#Chip:checked { background: $accent_soft; border-color: $accent; color: $fg; }
QPushButton#Step { background: transparent; border: 1px solid transparent; border-radius: 16px; padding: 6px 14px;
                   color: $muted; font-weight: 600; }
QPushButton#Step:hover { background: $hover; color: $fg; }
QPushButton#StepDone { background: $accent_soft; border: 1px solid transparent; border-radius: 16px; padding: 6px 14px;
                       color: $fg; font-weight: 700; }
QPushButton#Seg { border-radius: 7px; padding: 6px 4px; }
QPushButton#Seg:checked { background: $accent; color: $accent_ink; border-color: $accent; font-weight: 700; }
QPushButton#Swatch { border-radius: 10px; padding: 0; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $card2; border: 1px solid $line; border-radius: 8px; padding: 5px 9px; min-height: 18px;
    selection-background-color: $accent; selection-color: $accent_ink; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: $muted; background: $card; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $line; selection-background-color: $accent;
    selection-color: $accent_ink; outline: none; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }

QSlider::groove:horizontal { height: 4px; background: $line; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $fg; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: $accent; }
QSlider::handle:horizontal:disabled { background: $muted; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid $muted; border-radius: 5px; background: $card2; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:checked:disabled { background: $line; border-color: $line; }
QCheckBox:disabled { color: $muted; }

QProgressBar { background: $card2; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $line; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $line; border-radius: 3px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QListWidget { background: transparent; border: none; outline: none; }
QListWidget#Film { background: $side; }
QListWidget#Film::item { border: 1px solid transparent; border-radius: 10px; padding: 4px; color: $fg; }
QListWidget#Film::item:selected { background: $accent_soft; border-color: $accent; }
QListWidget#Film::item:hover { background: $hover; }
QListWidget#Grid::item { border: 1px solid transparent; border-radius: 12px; padding: 6px; }
QListWidget#Grid::item:selected { background: $accent_soft; border-color: $accent; }
QListWidget#Grid::item:hover { background: $hover; }
QListWidget#Stickers::item { border: 1px solid $line; border-radius: 9px; background: $card2; padding: 2px; }
QListWidget#Stickers::item:selected { border: 2px solid $accent; }
QListWidget#Layers::item { border: 1px solid $line; border-radius: 8px; background: $card2; padding: 7px 9px; margin: 2px 0; }
QListWidget#Layers::item:hover { border-color: $accent; }
QListWidget#Layers::item:selected { border-color: $accent; color: $fg; background: $accent_soft; }
QListWidget#Nav { background: $side; border-right: 1px solid $line; padding: 10px; }
QListWidget#Nav::item { padding: 10px 12px; border-radius: 8px; margin: 1px 0; }
QListWidget#Nav::item:selected { background: $accent_soft; color: $fg; }
QListWidget#Nav::item:hover { background: $hover; }

QStatusBar { background: $side; color: $muted; border-top: 1px solid $line; }
QStatusBar::item { border: none; }
QToolTip { background: $card; color: $fg; border: 1px solid $line; padding: 5px 7px; border-radius: 6px; }
QMenu { background: $card; border: 1px solid $line; padding: 5px; border-radius: 8px; }
QMenu::item { padding: 7px 20px; border-radius: 6px; }
QMenu::item:selected { background: $accent; color: $accent_ink; }
QMenu::indicator { width: 0; }
QProgressDialog, QMessageBox { background: $bg; }
""")


def _check_icon(color: str) -> str:
    """生成对勾图片，返回给样式表用的路径。"""
    folder = data_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"check_{color.strip('#')}_v1.png"
    if not path.exists():
        img = QImage(36, 36, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 4.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path_ = QPainterPath(QPointF(8.5, 18.5))
        path_.lineTo(15, 25)
        path_.lineTo(27.5, 11)
        p.drawPath(path_)
        p.end()
        img.save(str(path), "PNG")
    return str(path).replace("\\", "/")


def apply(app, theme_name: str) -> None:
    if theme_name not in PALETTES:
        theme_name = "dark"
    _state["name"] = theme_name
    p = {k: v for k, v in PALETTES[theme_name].items() if isinstance(v, str)}
    p["check"] = _check_icon(p["accent_ink"])
    app.setStyle("Fusion")
    pal = QPalette()
    c = QColor
    pal.setColor(QPalette.ColorRole.Window, c(p["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, c(p["fg"]))
    pal.setColor(QPalette.ColorRole.Base, c(p["card2"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, c(p["card"]))
    pal.setColor(QPalette.ColorRole.Text, c(p["fg"]))
    pal.setColor(QPalette.ColorRole.Button, c(p["card2"]))
    pal.setColor(QPalette.ColorRole.ButtonText, c(p["fg"]))
    pal.setColor(QPalette.ColorRole.Highlight, c(p["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, c(p["accent_ink"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, c(p["card"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, c(p["fg"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, c(p["muted"]))
    pal.setColor(QPalette.ColorRole.Link, c(p["accent"]))
    pal.setColor(QPalette.ColorRole.Mid, c(p["line"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(**p))
