"""深色 / 浅色主题。"""
from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QPalette

PALETTES = {
    "dark": {
        "bg": "#111317", "side": "#16191f", "card": "#1c2027", "card2": "#232832",
        "line": "#2b313c", "fg": "#e6e8ee", "muted": "#8a91a0", "accent": "#8fa3ff",
        "accent_ink": "#0c1024", "accent_soft": "rgba(143,163,255,38)", "ok": "#4fc28a",
        "warn": "#e2b04a", "danger": "#ff6b6b", "stage": "#0b0d10",
    },
    "light": {
        "bg": "#eceef3", "side": "#f7f8fa", "card": "#ffffff", "card2": "#f2f4f7",
        "line": "#dce0e7", "fg": "#191c23", "muted": "#626a79", "accent": "#4a60dc",
        "accent_ink": "#ffffff", "accent_soft": "rgba(74,96,220,30)", "ok": "#1d9560",
        "warn": "#b07c0c", "danger": "#d23c3c", "stage": "#d3d6de",
    },
}

_state = {"name": "dark"}


def current() -> dict:
    return PALETTES[_state["name"]]


def name() -> str:
    return _state["name"]


QSS = Template("""
* { font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif; font-size: 13px; }
QWidget { color: $fg; }
QMainWindow, QDialog, #Workspace { background: $bg; }
#Side { background: $side; border-right: 1px solid $line; }
#SideFooter { border-top: 1px solid $line; }
QFrame#Card { background: $card; border: 1px solid $line; border-radius: 10px; }
QLabel#CardTitle { color: $muted; font-size: 12px; font-weight: 700; }
QLabel#Muted { color: $muted; font-size: 12px; }
QLabel#Warn { color: $warn; font-size: 12px; }
QLabel#Brand { font-size: 17px; font-weight: 700; }
QLabel#BrandSub { color: $muted; font-size: 11px; }
QLabel#BigTitle { font-size: 22px; font-weight: 700; }
QLabel#Stat { font-size: 20px; font-weight: 700; }

QPushButton { background: $card2; border: 1px solid $line; border-radius: 7px; padding: 6px 12px; min-height: 20px; }
QPushButton:hover { border-color: $accent; }
QPushButton:pressed { background: $line; }
QPushButton:disabled { color: $muted; border-color: $line; background: $card; }
QPushButton#Primary { background: $accent; color: $accent_ink; border-color: $accent; font-weight: 700; }
QPushButton#Primary:hover { background: $accent; border-color: $fg; }
QPushButton#Primary:disabled { background: $card2; color: $muted; border-color: $line; }
QPushButton#Big { min-height: 30px; font-size: 14px; }
QPushButton#Danger { color: $danger; }
QPushButton#Tab { background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
                  color: $muted; font-weight: 700; font-size: 14px; padding: 10px 4px; }
QPushButton#Tab:checked { color: $fg; border-bottom-color: $accent; }
QPushButton#Tab:hover { color: $fg; }
QPushButton#Seg { border-radius: 6px; padding: 5px 4px; }
QPushButton#Seg:checked { background: $accent; color: $accent_ink; border-color: $accent; font-weight: 700; }
QPushButton#Part { padding: 8px 6px; font-weight: 600; }
QPushButton#Part:checked { border-color: $accent; color: $accent; }
QPushButton#Tool { background: transparent; border: 1px solid transparent; padding: 5px 9px; }
QPushButton#Tool:hover { border-color: $line; background: $card2; }
QPushButton#Tool:checked { background: $accent_soft; border-color: $accent; color: $fg; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $card2; border: 1px solid $line; border-radius: 6px; padding: 4px 8px; min-height: 20px;
    selection-background-color: $accent; selection-color: $accent_ink; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: $muted; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $line; selection-background-color: $accent;
    selection-color: $accent_ink; outline: none; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }

QSlider::groove:horizontal { height: 4px; background: $line; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $fg; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:disabled { background: $muted; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $line; border-radius: 4px; background: $card2; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:hover { border-color: $accent; }

QProgressBar { background: $card2; border: 1px solid $line; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $line; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $line; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QListWidget { background: transparent; border: none; outline: none; }
QListWidget#Film { background: $side; border-top: 1px solid $line; }
QListWidget#Film::item { border: 1px solid transparent; border-radius: 8px; padding: 4px; color: $fg; }
QListWidget#Film::item:selected { background: $accent_soft; border-color: $accent; }
QListWidget#Film::item:hover { background: $card2; }
QListWidget#Stickers::item { border: 1px solid $line; border-radius: 8px; background: $card2; padding: 2px; }
QListWidget#Stickers::item:selected { border: 2px solid $accent; }
QListWidget#Layers::item { border: 1px solid $line; border-radius: 6px; background: $card2; padding: 6px 8px; margin: 2px 0; }
QListWidget#Layers::item:selected { border-color: $accent; color: $fg; background: $accent_soft; }
QListWidget#Nav { background: $side; border-right: 1px solid $line; padding: 8px; }
QListWidget#Nav::item { padding: 10px 12px; border-radius: 7px; margin: 1px 0; }
QListWidget#Nav::item:selected { background: $accent_soft; color: $fg; }

#Toolbar { background: $side; border-bottom: 1px solid $line; }
QStatusBar { background: $side; color: $muted; border-top: 1px solid $line; }
QStatusBar::item { border: none; }
QToolTip { background: $card; color: $fg; border: 1px solid $line; padding: 4px 6px; }
QMenu { background: $card; border: 1px solid $line; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 5px; }
QMenu::item:selected { background: $accent; color: $accent_ink; }
QProgressDialog, QMessageBox { background: $bg; }
""")


def apply(app, theme_name: str) -> None:
    if theme_name not in PALETTES:
        theme_name = "dark"
    _state["name"] = theme_name
    p = PALETTES[theme_name]
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
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(**p))
