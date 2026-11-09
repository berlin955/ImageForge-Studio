"""素材页和「即将推出」占位页。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from . import theme
from .widgets import button, muted

STATUS_KEYS = {"todo": "muted", "attention": "warn", "done": "ok", "error": "danger"}
THUMB_SIZES = [("s", "小", 120), ("m", "中", 190), ("l", "大", 300)]
ROLE_STATUS = Qt.ItemDataRole.UserRole + 1
ROLE_KEY = Qt.ItemDataRole.UserRole + 2


class ThumbDelegate(QStyledItemDelegate):
    """素材缩略图：整张图按原比例完整显示在方格里，下面是文件名和状态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.size = 190

    def sizeHint(self, option, index):
        return QSize(self.size + 20, self.size + 58)

    def paint(self, p: QPainter, option, index):
        pal = theme.current()
        p.save()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            p.fillPath(path, QColor(pal["hover"]))
            if selected:
                pen = QPen(QColor(pal["accent"]), 2)
                p.setPen(pen)
                p.drawPath(path)
        S = self.size
        box = QRectF(r.x() + (r.width() - S) / 2, r.y() + 6, S, S)
        p.fillRect(box, QColor(pal["stage"]))
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            pm = icon.pixmap(QSize(int(S * 2), int(S * 2)))
            if not pm.isNull():
                w, h = pm.width(), pm.height()
                k = min(S / w, S / h)
                dw, dh = w * k, h * k
                p.drawPixmap(QRectF(box.x() + (S - dw) / 2, box.y() + (S - dh) / 2, dw, dh), pm,
                             QRectF(0, 0, w, h))
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        f = QFont(option.font)
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetrics(f)
        tr = QRect(int(r.x() + 6), int(box.bottom() + 6), int(r.width() - 12), 18)
        p.setPen(QColor(pal["fg"]))
        p.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideMiddle, tr.width()))
        st = index.data(ROLE_STATUS) or ""
        if st:
            key = index.data(ROLE_KEY) or "muted"
            p.setPen(QColor(pal.get(key, pal["muted"])))
            tr2 = tr.translated(0, 18)
            p.drawText(tr2, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(st, Qt.TextElideMode.ElideRight, tr2.width()))
        p.restore()


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
        from .widgets import Segmented
        self.size_seg = Segmented([(k, t) for k, t, _ in THUMB_SIZES])
        self.size_seg.setFixedWidth(150)
        self.size_seg.setToolTip("缩略图大小")
        self.size_seg.changed.connect(self.set_thumb_size)
        for w in (self.count, self.size_seg, self.b_rm, self.b_clear, b_dir, b_files):
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
        self.delegate = ThumbDelegate(self.grid)
        self.grid.setItemDelegate(self.delegate)
        self.grid.setSpacing(4)
        self.grid.setUniformItemSizes(True)
        self.grid.setMouseTracking(True)
        self.grid.setLayoutMode(QListView.LayoutMode.Batched)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemDoubleClicked.connect(self._open)
        bv.addWidget(self.grid, 1)
        tip = muted("双击图片打开打码编辑。按住 Ctrl 或 Shift 可以多选。右上角可以切换缩略图大小。")
        bv.addWidget(tip)
        v.addWidget(body, 1)
        key = (mw.cfg.data.get("ui") or {}).get("thumb", "m")
        self.size_seg.set_value(key)
        self.set_thumb_size(key, save=False)

    def set_thumb_size(self, key: str, save: bool = True):
        size = dict((k, v) for k, _t, v in THUMB_SIZES).get(key, 190)
        self.delegate.size = size
        self.grid.setGridSize(QSize(size + 20, size + 58))
        self.grid.setIconSize(QSize(size, size))
        self.grid.doItemsLayout()
        self.grid.viewport().update()
        if save:
            self.mw.cfg.data.setdefault("ui", {})["thumb"] = key
            self.mw.cfg.save()

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
        for d in docs:
            it = self._items.get(d.id)
            if it:
                it.setText(d.name)
                st = d.status()
                if st == "attention":
                    it.setData(ROLE_STATUS, d.status_text())
                    it.setData(ROLE_KEY, "warn")
                elif d.layers:
                    it.setData(ROLE_STATUS, f"已打码 · {len(d.layers)} 个码")
                    it.setData(ROLE_KEY, "ok")
                elif st == "error":
                    it.setData(ROLE_STATUS, "读取失败")
                    it.setData(ROLE_KEY, "danger")
                else:
                    it.setData(ROLE_STATUS, f"{d.w}×{d.h}" if d.w else "")
                    it.setData(ROLE_KEY, "muted")

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
