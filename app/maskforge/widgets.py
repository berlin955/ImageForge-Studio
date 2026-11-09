"""通用小部件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QVBoxLayout, QWidget)


class Card(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 14)
        self.lay.setSpacing(10)
        self.title = None
        if title:
            self.title = QLabel(title)
            self.title.setObjectName("CardTitle")
            self.lay.addWidget(self.title)

    def add(self, w):
        if isinstance(w, QWidget):
            self.lay.addWidget(w)
        else:
            self.lay.addLayout(w)
        return w


def muted(text: str, obj: str = "Muted") -> QLabel:
    l = QLabel(text)
    l.setObjectName(obj)
    l.setWordWrap(True)
    return l


def button(text: str, kind: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def row(*widgets, spacing: int = 8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h


def scroll_page(*cards) -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(14, 12, 12, 14)
    v.setSpacing(12)
    for c in cards:
        v.addWidget(c)
    v.addStretch(1)
    area.setWidget(inner)
    return area, v


class SliderRow(QWidget):
    """标签 + 滑块 + 数值框。"""
    valueChanged = Signal(float)
    editStarted = Signal()

    def __init__(self, label: str, lo: float, hi: float, decimals: int = 0, suffix: str = "",
                 factor: float = 1.0, parent=None):
        super().__init__(parent)
        self._mul = 10 ** decimals
        self._factor = factor          # 显示值 = 实际值 * factor
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.lbl = QLabel(label)
        self.lbl.setFixedWidth(52)
        self.lbl.setObjectName("Muted")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(78)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin.setKeyboardTracking(False)
        self.set_range(lo, hi)
        h.addWidget(self.lbl)
        h.addWidget(self.slider, 1)
        h.addWidget(self.spin)
        self.slider.sliderPressed.connect(self.editStarted.emit)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self._block = False

    def set_range(self, lo: float, hi: float):
        self._block = True
        self.slider.setRange(int(round(lo * self._factor * self._mul)), int(round(hi * self._factor * self._mul)))
        self.spin.setRange(lo * self._factor, hi * self._factor)
        self._block = False

    def value(self) -> float:
        return self.spin.value() / self._factor

    def set_value(self, v: float):
        self._block = True
        d = v * self._factor
        if d > self.spin.maximum():
            self.slider.setMaximum(int(round(d * self._mul)))
            self.spin.setMaximum(d)
        self.spin.setValue(d)
        self.slider.setValue(int(round(d * self._mul)))
        self._block = False

    def _from_slider(self, iv: int):
        if self._block:
            return
        self._block = True
        self.spin.setValue(iv / self._mul)
        self._block = False
        if not self.slider.isSliderDown():
            self.editStarted.emit()
        self.valueChanged.emit(self.value())

    def _from_spin(self, v: float):
        if self._block:
            return
        self._block = True
        self.slider.setValue(int(round(v * self._mul)))
        self._block = False
        self.editStarted.emit()
        self.valueChanged.emit(self.value())


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], cols: int = 0, parent=None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.btns: dict[str, QPushButton] = {}
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(4)
        cols = cols or len(options)
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.group.addButton(b)
            self.btns[key] = b
            g.addWidget(b, i // cols, i % cols)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))

    def set_value(self, key: str):
        b = self.btns.get(key)
        if b:
            b.setChecked(True)

    def value(self) -> str:
        for k, b in self.btns.items():
            if b.isChecked():
                return k
        return ""


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#16171b", parent=None):
        super().__init__(parent)
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._paint()

    def set_color(self, c: str):
        self._color = c
        self._paint()

    def _paint(self):
        self.setText(self._color.upper())
        fg = "#ffffff" if QColor(self._color).lightness() < 128 else "#111111"
        self.setStyleSheet(f"QPushButton{{background:{self._color};color:{fg};border-radius:6px;}}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, "选择颜色")
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit(c.name())


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setObjectName("Line")
    f.setStyleSheet("QFrame#Line{border:none;border-top:1px solid palette(mid);}")
    return f
