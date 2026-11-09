"""素材页和「即将推出」占位页。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .widgets import button, muted

STATUS_KEYS = {"todo": "muted", "attention": "warn", "done": "ok", "error": "danger"}


def page_header(title: str, sub: str = "") -> tuple[QFrame, QHBoxLayout]:
    top = QFrame()
    top.setObjectName("TopBar")
    h = QHBoxLayout(top)
    h.setContentsMargins(18, 10, 14, 10)
    h.setSpacing(10)
    col = QVBoxLayout()
    col.setSpacing(0)
    t = QLabel(title)
    t.setObjectName("Brand")
    col.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("Muted")
        col.addWidget(s)
    h.addLayout(col)
    h.addStretch(1)
    return top, h


class AssetsPage(QWidget):
    """这一批商品图片。所有功能共用这里导入的图片。"""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._items: dict[str, QListWidgetItem] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, h = page_header("素材", "导入一次，打码、主图、规格、详情都用这批图")
        self.count = QLabel("")
        self.count.setObjectName("Count")
        b_files = button("导入图片…", "Primary", "Ctrl+O")
        b_files.clicked.connect(mw.import_dialog)
        b_dir = button("导入文件夹…")
        b_dir.clicked.connect(mw.import_folder_dialog)
        self.b_rm = button("移出选中", "Ghost")
        self.b_rm.clicked.connect(self._remove_selected)
        self.b_clear = button("清空", "Ghost")
        self.b_clear.clicked.connect(mw.clear_all)
        for w in (self.count, self.b_rm, self.b_clear, b_dir, b_files):
            h.addWidget(w)
        v.addWidget(top)

        body = QWidget()
        body.setObjectName("Workspace")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(16, 12, 16, 12)
        bv.setSpacing(10)
        self.empty = QFrame()
        self.empty.setObjectName("Drop")
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(30, 60, 30, 60)
        e1 = QLabel("把这一款的模特图拖到这里")
        e1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e1.setStyleSheet("font-size:20px;font-weight:700")
        e2 = muted("支持一次导入多张或整个文件夹。导入后可以去「智能打码」「批量主图」等功能。")
        e2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eb = button("选择图片…", "Primary")
        eb.setFixedWidth(180)
        eb.clicked.connect(mw.import_dialog)
        ev.addWidget(e1)
        ev.addWidget(e2)
        ev.addSpacing(10)
        ev.addWidget(eb, 0, Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(self.empty)

        self.grid = QListWidget()
        self.grid.setObjectName("Grid")
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(190, 190))
        self.grid.setGridSize(QSize(214, 246))
        self.grid.setSpacing(6)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemDoubleClicked.connect(self._open)
        bv.addWidget(self.grid, 1)
        tip = muted("双击图片打开打码编辑。按住 Ctrl 或 Shift 可以多选。")
        bv.addWidget(tip)
        v.addWidget(body, 1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        docs = self.mw.docs
        ids = [d.id for d in docs]
        self.empty.setVisible(not docs)
        self.grid.setVisible(bool(docs))
        self.b_rm.setEnabled(bool(docs) and not self.mw.busy)
        self.b_clear.setEnabled(bool(docs) and not self.mw.busy)
        self.count.setText(f"{len(docs)} 张" if docs else "")
        if list(self._items.keys()) != ids:
            self.grid.clear()
            self._items.clear()
            for d in docs:
                it = QListWidgetItem(d.icon or self.mw._placeholder, "")
                it.setData(Qt.ItemDataRole.UserRole, d.id)
                it.setToolTip(str(d.path))
                it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                self.grid.addItem(it)
                self._items[d.id] = it
        pal = theme.current()
        for d in docs:
            it = self._items.get(d.id)
            if it:
                name = d.name if len(d.name) <= 22 else d.name[:10] + "…" + d.name[-10:]
                mark = "　· 已打码" if d.layers else ""
                it.setText(name + mark)
                it.setForeground(QColor(pal["warn"] if d.status() == "attention" else pal["fg"]))

    def update_icon(self, d):
        it = self._items.get(d.id)
        if it and d.icon is not None:
            it.setIcon(d.icon)

    def _open(self, it):
        did = it.data(Qt.ItemDataRole.UserRole)
        for i, d in enumerate(self.mw.docs):
            if d.id == did:
                self.mw.go(i)
                self.mw.show_page("mask")
                return

    def _remove_selected(self):
        ids = {it.data(Qt.ItemDataRole.UserRole) for it in self.grid.selectedItems()}
        if not ids:
            self.mw.status.showMessage("先选中要移出的图片", 3000)
            return
        self.mw.remove_docs(ids)


class ComingSoonPage(QWidget):
    def __init__(self, title: str, desc: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, _h = page_header(title)
        v.addWidget(top)
        body = QWidget()
        body.setObjectName("Workspace")
        bv = QVBoxLayout(body)
        bv.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(560)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(28, 26, 28, 26)
        cv.setSpacing(10)
        t = QLabel(title)
        t.setObjectName("BigTitle")
        cv.addWidget(t)
        tag = QLabel("下一个版本推出")
        tag.setObjectName("Warn")
        cv.addWidget(tag)
        d = muted(desc)
        d.setStyleSheet("font-size:13px")
        cv.addWidget(d)
        bv.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        bv.addStretch(2)
        v.addWidget(body, 1)
