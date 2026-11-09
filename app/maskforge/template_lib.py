"""模板库：带预览图的模板列表，可以起名字、改名、删除、一键使用。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from .spec_engine import delete_template, load_templates, save_template, templates_dir

KIND_NAMES = {"spec": "规格图模板", "detail": "详情图模板"}
THUMB_W = 360


def thumb_path(tpl: dict) -> Path:
    return templates_dir() / tpl["id"] / "thumb.jpg"


def ensure_thumb(tpl: dict) -> QImage:
    """模板的预览图：原图缩小；详情长图只取上面一截。没有就现做一张。"""
    p = thumb_path(tpl)
    img = QImage(str(p))
    if not img.isNull():
        return img
    src = QImage(str(templates_dir() / tpl["id"] / "original.png"))
    if src.isNull():
        src = QImage(str(templates_dir() / tpl["id"] / "bg.png"))
    if src.isNull():
        return QImage()
    if src.height() > src.width() * 1.4:
        src = src.copy(0, 0, src.width(), int(src.width() * 1.4))
    img = src.scaledToWidth(THUMB_W, Qt.TransformationMode.SmoothTransformation)
    try:
        img.save(str(p), "JPG", 88)
    except Exception:
        pass
    return img


def icon_for(tpl: dict, box: int) -> QIcon:
    img = ensure_thumb(tpl)
    if img.isNull():
        return QIcon()
    pm = QPixmap.fromImage(img.scaled(box, box, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
    return QIcon(pm)


def ask_name(parent, title: str, current: str) -> str | None:
    name, ok = QInputDialog.getText(parent, title, "模板名称（例如：黑色胶囊框-两图）：", text=current)
    name = (name or "").strip()
    return name if ok and name else None


def rename(parent, tpl: dict) -> bool:
    name = ask_name(parent, "重命名模板", tpl.get("name", ""))
    if not name:
        return False
    tpl["name"] = name
    save_template(tpl)
    return True


class TemplateGrid(QListWidget):
    """模板预览图网格。"""
    chosen = Signal(dict)

    def __init__(self, kind: str, size: int = 180, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.box = size
        self.setObjectName("TplGrid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 28, size + 52))
        self.setWordWrap(True)
        self.setSpacing(6)
        self.itemDoubleClicked.connect(lambda it: self.chosen.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.reload()

    def reload(self, select: str | None = None):
        self.clear()
        for t in load_templates(self.kind):
            it = QListWidgetItem(icon_for(t, self.box), t.get("name") or "未命名模板")
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip(f"{t.get('name')}\n{len(t.get('slots', []))} 个照片位 · {len(t.get('texts', []))} 段文字 · "
                          f"{int(t.get('w', 0))}×{int(t.get('h', 0))}")
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.addItem(it)
            if select and t["id"] == select:
                self.setCurrentItem(it)

    def current_tpl(self) -> dict | None:
        it = self.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None


def _actions(parent, grid: TemplateGrid, on_use) -> QHBoxLayout:
    h = QHBoxLayout()
    b_use = QPushButton("使用这个模板")
    b_use.setObjectName("Primary")
    b_ren = QPushButton("重命名")
    b_del = QPushButton("删除")
    b_del.setObjectName("Ghost")

    def use():
        t = grid.current_tpl()
        if t:
            on_use(t)

    def ren():
        t = grid.current_tpl()
        if t and rename(parent, t):
            grid.reload(select=t["id"])

    def dele():
        t = grid.current_tpl()
        if not t:
            return
        if QMessageBox.question(parent, "删除模板", f"删除模板「{t.get('name')}」？这个操作不能撤销。") \
                == QMessageBox.StandardButton.Yes:
            delete_template(t)
            grid.reload()

    b_use.clicked.connect(use)
    b_ren.clicked.connect(ren)
    b_del.clicked.connect(dele)
    grid.chosen.connect(on_use)
    h.addWidget(b_use)
    h.addWidget(b_ren)
    h.addStretch(1)
    h.addWidget(b_del)
    return h


class TemplatePicker(QDialog):
    """在规格 / 详情页里点「模板库…」弹出来选模板。"""

    def __init__(self, kind: str, current: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(KIND_NAMES.get(kind, "模板"))
        self.resize(900, 640)
        self.result_tpl: dict | None = None
        v = QVBoxLayout(self)
        self.grid = TemplateGrid(kind, 180, self)
        self.grid.reload(select=current)
        v.addWidget(self.grid, 1)
        v.addLayout(_actions(self, self.grid, self._use))

    def _use(self, t: dict):
        self.result_tpl = t
        self.accept()


class TemplatesPage(QWidget):
    """左侧「模板库」：规格图和详情图模板都在这里管理。"""

    def __init__(self, mw):
        super().__init__()
        from .pages import page_header
        from .widgets import Segmented
        self.mw = mw
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, th = page_header("模板库", "导入过的规格图、详情图模板都在这里，双击直接打开使用")
        self.seg = Segmented([("spec", "规格图模板"), ("detail", "详情图模板")])
        self.seg.changed.connect(self._kind)
        th.addWidget(self.seg)
        v.addWidget(top)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(18, 14, 18, 14)
        self.grids = {}
        for k in ("spec", "detail"):
            g = TemplateGrid(k, 210, body)
            self.grids[k] = g
            bv.addWidget(g, 1)
        self.acts = {}
        for k, g in self.grids.items():
            w = QWidget()
            w.setLayout(_actions(self, g, self._use))
            self.acts[k] = w
            bv.addWidget(w)
        v.addWidget(body, 1)
        self.seg.set_value("spec")
        self._kind("spec")

    def _kind(self, k: str):
        self.kind = k
        for kk in self.grids:
            self.grids[kk].setVisible(kk == k)
            self.acts[kk].setVisible(kk == k)

    def on_show(self):
        for g in self.grids.values():
            g.reload()

    def _use(self, t: dict):
        page = self.mw.spec_page if t.get("kind", "spec") == "spec" else self.mw.detail_page
        self.mw.show_page(t.get("kind", "spec"))
        page.reload_templates(select=t["id"])
