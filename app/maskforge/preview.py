"""打码效果总览：一键打码后先在这里看全部结果，再决定保存或逐张调整。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QVBoxLayout)

from . import theme
from .exporter import render_preview
from .widgets import Segmented, button, muted

STATUS_KEYS = {"todo": "muted", "done": "accent", "none": "warn", "ok": "ok", "error": "danger"}


class PreviewDialog(QDialog):
    EDIT = 2
    SAVE = 3

    def __init__(self, mw, title: str = "打码预览"):
        super().__init__(mw)
        self.mw = mw
        self.picked = -1
        self.setWindowTitle(title)
        self.resize(1180, 800)
        self.setMinimumSize(820, 560)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(12)

        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("BigTitle")
        self.summary = muted("")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(t)
        col.addWidget(self.summary)
        head.addLayout(col, 1)
        self.filter = Segmented([("all", "全部"), ("attention", "需要注意"), ("masked", "已打码")])
        self.filter.setFixedWidth(300)
        self.filter.set_value("all")
        self.filter.changed.connect(lambda _k: self._fill())
        head.addWidget(self.filter, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(head)

        self.grid = QListWidget()
        self.grid.setObjectName("Film")
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(220, 220))
        self.grid.setGridSize(QSize(244, 278))
        self.grid.setSpacing(6)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.itemDoubleClicked.connect(self._open)
        v.addWidget(self.grid, 1)

        foot = QHBoxLayout()
        foot.addWidget(muted("双击任意一张进入编辑，手动调整码的位置和大小。「需要注意」是 AI 没有找到部位的图片。"), 1)
        b_close = button("关闭")
        b_close.clicked.connect(self.reject)
        b_review = button("逐张审核")
        b_review.clicked.connect(self._review)
        self.b_save = button("保存全部", "Primary")
        self.b_save.setMinimumWidth(140)
        self.b_save.clicked.connect(lambda: self.done(self.SAVE))
        foot.addWidget(b_close)
        foot.addWidget(b_review)
        foot.addWidget(self.b_save)
        v.addLayout(foot)
        self._fill()

    def _fill(self):
        mw = self.mw
        mode = self.filter.value() or "all"
        pal = theme.current()
        self.grid.clear()
        n_mask = sum(1 for d in mw.docs if d.layers)
        n_none = sum(1 for d in mw.docs if d.status() in ("none", "todo", "error"))
        self.summary.setText(f"共 {len(mw.docs)} 张　·　已打码 {n_mask} 张　·　需要注意 {n_none} 张")
        for i, d in enumerate(mw.docs):
            st = d.status()
            if mode == "attention" and st not in ("none", "todo", "error"):
                continue
            if mode == "masked" and not d.layers:
                continue
            thumb = mw.thumb_for(d)
            img = render_preview(d, thumb, mw.library) if thumb is not None else None
            icon = QIcon(QPixmap.fromImage(img)) if img is not None and not img.isNull() else QIcon()
            name = d.name if len(d.name) <= 26 else d.name[:12] + "…" + d.name[-12:]
            it = QListWidgetItem(icon, f"{name}\n{d.status_text()}")
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setForeground(QColor(pal[STATUS_KEYS[st]]))
            it.setToolTip(str(d.path))
            self.grid.addItem(it)
        self.b_save.setText(f"保存全部 {len(mw.export_targets())} 张")

    def _open(self, it):
        self.picked = it.data(Qt.ItemDataRole.UserRole)
        self.done(self.EDIT)

    def _review(self):
        for i, d in enumerate(self.mw.docs):
            if d.status() in ("none", "done", "todo"):
                self.picked = i
                break
        else:
            self.picked = 0
        self.done(self.EDIT)
