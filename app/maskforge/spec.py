"""智能规格 / 智能详情页：选模板 → 往图片位里填你的模特图 → 改文字 → 导出。两个功能共用这一套。"""
from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontDatabase, QFontMetricsF, QIcon, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFontComboBox, QFrame, QGraphicsItem, QGraphicsObject,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QProgressDialog,
                               QSpinBox, QVBoxLayout, QWidget)

from . import theme
from .canvas import ImageItem
from .exporter import FORMATS, _render, save_image, unique_path
from types import SimpleNamespace

from .mainimage import _scaled_doc, crop_rect_aspect, doc_icon, proxy_of
from .pages import page_header
from .spec_engine import (build_template, delete_template, load_templates, save_template,
                          template_bg)
from .widgets import Card, ColorButton, ElideLabel, Segmented, button, muted, row, scroll_page

DEFAULT_FONT = "Microsoft YaHei UI"

KINDS = {
    "spec": {"title": "智能规格", "noun": "规格图", "folder": "规格", "suffix": "_规格",
             "sub": "导入别人的规格图做成模板，换上你的模特图，文字随时改"},
    "detail": {"title": "智能详情", "noun": "详情图", "folder": "详情", "suffix": "_详情",
               "sub": "导入别人的详情长图做成模板，换上你的模特图，文字随时改；导出时按宽度缩放、可以切片"},
}
FRONT = ("FACE_FEMALE", "FACE_MALE")
BACK = ("BUTTOCKS_EXPOSED", "BUTTOCKS_COVERED", "ANUS_EXPOSED", "ANUS_COVERED")


# ================================================================ 绘制（编辑和导出共用）
def text_font(t: dict) -> QFont:
    f = QFont(t.get("family") or DEFAULT_FONT)
    f.setPixelSize(max(4, int(round(t.get("size", 24)))))
    f.setBold(bool(t.get("bold")))
    return f


def text_rect(t: dict) -> QRectF:
    fm = QFontMetricsF(text_font(t))
    w = max(fm.horizontalAdvance(t.get("text") or " "), 8.0)
    h = max(fm.height(), float(t.get("h", 0)))
    return QRectF(0, 0, w, h)


def draw_text(p: QPainter, t: dict, origin: QPointF | None = None):
    f = text_font(t)
    fm = QFontMetricsF(f)
    r = text_rect(t)
    x, y = (origin.x(), origin.y()) if origin is not None else (t["x"], t["y"])
    base = y + (r.height() - (fm.ascent() + fm.descent())) / 2 + fm.ascent()
    p.setFont(f)
    p.setPen(QColor(t.get("color", "#000000")))
    p.drawText(QPointF(x, base), t.get("text", ""))


def render_slot(slot: dict, doc, ov: dict, library, scale: float, preview: bool,
                masked: bool = True) -> QImage | None:
    """把一张图按图片位的比例裁好（带码）。scale：输出像素 / 模板像素。"""
    if doc is None:
        return None
    if preview:
        px = proxy_of(doc)
        if px is None:
            return None
        img, k = px
    else:
        img, k = doc.image(), 1.0
        if img is None:
            return None
    w, h = max(1, round(slot["w"] * scale)), max(1, round(slot["h"] * scale))
    src = crop_rect_aspect(doc, img.width(), img.height(), w / h, "smart", ov)
    fake = _scaled_doc(doc, k) if masked else SimpleNamespace(layers=[])
    return _render(fake, img, library, w, h, src, QRectF(0, 0, w, h), "jpg")


# ================================================================ 画布上的图片位
HANDLE = 10.0
SHAPES = [("rect", "直角"), ("round", "圆角"), ("capsule", "胶囊"), ("ellipse", "椭圆")]


_KEEP_CACHE: dict = {}


def keep_image(tpl_id: str, slot: dict):
    """照片位的保留层（盖在新照片上面的原图像素：边框圆角、徽章、照片上的字）。"""
    k = slot.get("keep")
    if not k:
        return None, 0.0, 0.0
    from .spec_engine import templates_dir
    key = (tpl_id, k["file"])
    img = _KEEP_CACHE.get(key)
    if img is None:
        img = QImage(str(templates_dir() / tpl_id / k["file"]))
        if len(_KEEP_CACHE) > 64:
            _KEEP_CACHE.clear()
        _KEEP_CACHE[key] = img
    return (img if not img.isNull() else None), float(k["x"]), float(k["y"])


def slot_shape_key(slot: dict) -> str:
    if slot.get("shape") == "ellipse":
        return "ellipse"
    r = float(slot.get("radius") or 0)
    return "rect" if r < 0.02 else "capsule" if r >= 0.45 else "round"


def slot_path(slot: dict, r: QRectF) -> QPainterPath:
    """图片位的形状（照片框可能是圆角、胶囊或椭圆）。"""
    path = QPainterPath()
    if slot.get("shape") == "ellipse":
        path.addEllipse(r)
        return path
    rad = float(slot.get("radius") or 0) * min(r.width(), r.height())
    if rad > 0.5:
        path.addRoundedRect(r, rad, rad)
    else:
        path.addRect(r)
    return path


class SlotItem(QGraphicsObject):
    def __init__(self, page, slot: dict):
        super().__init__()
        self.page = page
        self.slot = slot
        self._cache = None
        self._cache_key = None
        self._drag = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.sync()

    def sync(self):
        self.prepareGeometryChange()
        self.setPos(self.slot["x"], self.slot["y"])
        self.update()

    def rect(self) -> QRectF:
        return QRectF(0, 0, self.slot["w"], self.slot["h"])

    def boundingRect(self) -> QRectF:
        m = HANDLE / max(0.05, self.page.view_scale())
        return self.rect().adjusted(-m, -m, m, m)

    def shape(self):
        if not self.page.edit_mode:
            return slot_path(self.slot, self.rect())
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def fill(self):
        return self.page.fills.get(self.slot["id"])

    def paint(self, p: QPainter, opt, widget=None):
        pal = theme.current()
        r = self.rect()
        f = self.fill()
        doc = self.page.mw.doc_by_id(f["doc"]) if f else None
        path = slot_path(self.slot, r)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setClipPath(path)
        if doc is not None:
            masked = self.page.use_mask()
            key = (doc.id, tuple(sorted(f["ov"].items())), round(r.width()), round(r.height()),
                   len(doc.layers), masked)
            if key != self._cache_key or self._cache is None:
                sc = min(1.0, 1100 / max(r.width(), r.height()))
                self._cache = render_slot(self.slot, doc, f["ov"], self.page.mw.library, sc, preview=True,
                                          masked=masked)
                self._cache_key = key
            if self._cache is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(r, self._cache)
        elif not self.page.exporting:
            # 原来的照片已经抠掉：画成透明格子（和修图软件里的「透明」一样）
            cell = max(6.0, 9.0 / max(0.05, self.page.view_scale()))
            p.fillPath(path, QColor("#f4f4f4"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#d6d6d6"))
            nx, ny = int(r.width() / cell) + 1, int(r.height() / cell) + 1
            for j in range(ny):
                for i in range(j % 2, nx, 2):
                    p.drawRect(QRectF(i * cell, j * cell, cell, cell))
            idx = next((i for i, s in enumerate(self.page.tpl["slots"]) if s is self.slot), 0) + 1 \
                if self.page.tpl else 1
            f2 = QFont(DEFAULT_FONT)
            f2.setPixelSize(max(10, int(min(r.width(), r.height()) * 0.07)))
            f2.setBold(True)
            p.setFont(f2)
            tip = f"照片位 {idx}\n已抠空" if self.page.in_review() else \
                f"{self.slot.get('role', '图片')}\n点一下，再点下面的图片填入"
            box = QRectF(r.center().x() - r.width() * 0.42, r.center().y() - f2.pixelSize() * 1.6,
                         r.width() * 0.84, f2.pixelSize() * 3.2)
            p.setBrush(QColor(20, 22, 30, 170))
            p.drawRoundedRect(box, f2.pixelSize() * 0.5, f2.pixelSize() * 0.5)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, tip)
        p.restore()
        if self.page.tpl:
            kimg, kx, ky = keep_image(self.page.tpl["id"], self.slot)
            if kimg is not None:
                p.drawImage(QPointF(kx - self.slot["x"], ky - self.slot["y"]), kimg)
        if self.page.exporting:
            return
        if doc is None:
            pen = QPen(QColor(pal["muted"]), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        if self.isSelected() or self.page.edit_mode:
            pen = QPen(QColor(pal["accent"]), 2 if self.isSelected() else 1)
            pen.setCosmetic(True)
            if not self.isSelected():
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            if self.page.edit_mode and slot_shape_key(self.slot) != "rect":
                pen.setStyle(Qt.PenStyle.DotLine)
                p.setPen(pen)
                p.drawRect(r)
        if self.page.edit_mode and self.isSelected():
            hs = HANDLE / max(0.05, self.page.view_scale())
            p.setBrush(QColor("#ffffff"))
            for c in self._corners():
                p.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))

    def _corners(self):
        r = self.rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _corner_at(self, pos) -> int:
        t = (HANDLE + 4) / max(0.05, self.page.view_scale())
        for i, c in enumerate(self._corners()):
            if abs(pos.x() - c.x()) <= t and abs(pos.y() - c.y()) <= t:
                return i
        return -1

    def hoverMoveEvent(self, e):
        if self.page.edit_mode:
            cur = Qt.CursorShape.SizeFDiagCursor if self._corner_at(e.pos()) >= 0 else Qt.CursorShape.SizeAllCursor
        else:
            cur = Qt.CursorShape.OpenHandCursor if self.fill() else Qt.CursorShape.PointingHandCursor
        self.setCursor(QCursor(cur))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            e.ignore()
            return
        sc = self.scene()
        if sc and not self.isSelected():
            sc.clearSelection()
        self.setSelected(True)
        s = self.slot
        f = self.fill()
        if self.page.edit_mode:
            ci = self._corner_at(e.pos())
            self._drag = {"mode": "resize" if ci >= 0 else "move", "corner": ci, "start": e.scenePos(),
                          "rect": (s["x"], s["y"], s["w"], s["h"])}
        elif f:
            doc = self.page.mw.doc_by_id(f["doc"])
            px = proxy_of(doc) if doc else None
            if px:
                img, _k = px
                src = crop_rect_aspect(doc, img.width(), img.height(), s["w"] / s["h"], "smart", f["ov"])
                self._drag = {"mode": "pan", "start": e.scenePos(), "cx": src.center().x() / img.width(),
                              "cy": src.center().y() / img.height(), "k": src.width() / s["w"],
                              "iw": img.width(), "ih": img.height()}
        e.accept()

    def mouseMoveEvent(self, e):
        d = self._drag
        if not d:
            return
        dx = e.scenePos().x() - d["start"].x()
        dy = e.scenePos().y() - d["start"].y()
        s = self.slot
        if d["mode"] == "pan":
            ov = self.fill()["ov"]
            ov["cx"] = d["cx"] - dx * d["k"] / d["iw"]
            ov["cy"] = d["cy"] - dy * d["k"] / d["ih"]
            ov.setdefault("scale", 1.0)
            self.update()
        elif d["mode"] == "move":
            x, y, w, h = d["rect"]
            s["x"], s["y"] = x + dx, y + dy
            self.sync()
        else:
            x, y, w, h = d["rect"]
            x2, y2 = x + w, y + h
            c = d["corner"]
            if c in (0, 3):
                x = min(x + dx, x2 - 20)
            else:
                x2 = max(x2 + dx, x + 20)
            if c in (0, 1):
                y = min(y + dy, y2 - 20)
            else:
                y2 = max(y2 + dy, y + 20)
            s["x"], s["y"], s["w"], s["h"] = x, y, x2 - x, y2 - y
            self.sync()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.page.on_template_changed(dirty=self.page.edit_mode)

    def wheelEvent(self, e):
        f = self.fill()
        if self.page.edit_mode or not f:
            e.ignore()
            return
        doc = self.page.mw.doc_by_id(f["doc"])
        px = proxy_of(doc) if doc else None
        if not px:
            return
        img, _k = px
        ov = f["ov"]
        if "cx" not in ov:
            src = crop_rect_aspect(doc, img.width(), img.height(), self.slot["w"] / self.slot["h"], "smart", ov)
            ov["cx"], ov["cy"] = src.center().x() / img.width(), src.center().y() / img.height()
        ov["scale"] = max(0.15, min(1.0, float(ov.get("scale", 1.0)) * (0.92 if e.delta() > 0 else 1 / 0.92)))
        self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        f = self.fill()
        if f and not self.page.edit_mode:
            f["ov"] = {}
            self.update()


class TextItem(QGraphicsObject):
    def __init__(self, page, t: dict):
        super().__init__()
        self.page = page
        self.t = t
        self._start = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(5)
        self.sync()

    def sync(self):
        self.prepareGeometryChange()
        self.setPos(self.t["x"], self.t["y"])
        self.update()
        self.page.schedule_bg_refresh()

    def boundingRect(self) -> QRectF:
        return text_rect(self.t).adjusted(-3, -3, 3, 3)

    def paint(self, p: QPainter, opt, widget=None):
        from .spec_engine import text_changed
        if text_changed(self.t):
            draw_text(p, self.t, QPointF(0, 0))     # 没改过的字，原图上就有，不重画
        if self.page.in_review() and not self.isSelected() and not self.page.exporting:
            c = QColor(theme.current()["accent"])
            pen = QPen(c, 1.3, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            c.setAlphaF(0.12)
            p.setBrush(c)
            p.drawRect(self.boundingRect())
        if self.isSelected() and not self.page.exporting:
            pen = QPen(QColor(theme.current()["accent"]), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.boundingRect())

    def hoverMoveEvent(self, e):
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            e.ignore()
            return
        sc = self.scene()
        if sc and not self.isSelected():
            sc.clearSelection()
        self.setSelected(True)
        self._start = (e.scenePos(), self.t["x"], self.t["y"])
        e.accept()

    def mouseMoveEvent(self, e):
        if not self._start:
            return
        sp, x, y = self._start
        self.t["x"] = x + e.scenePos().x() - sp.x()
        self.t["y"] = y + e.scenePos().y() - sp.y()
        self.sync()

    def mouseReleaseEvent(self, e):
        if self._start:
            self._start = None
            self.page.on_template_changed(dirty=True)


class SpecView(QGraphicsView):
    newSlot = Signal(QRectF)

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._band = None
        self._band_item = None
        self.fit_mode = True
        self.apply_theme()

    def apply_theme(self):
        self.setBackgroundBrush(QColor(theme.current()["stage"]))

    def long_mode(self) -> bool:
        r = self.scene().sceneRect()
        return r.width() > 0 and r.height() > r.width() * 1.6

    def fit(self):
        self.fit_mode = True
        r = self.scene().sceneRect()
        if r.width() <= 0:
            return
        if self.long_mode():
            # 长图按宽度铺满，上下滚动查看
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            vw = max(50, self.viewport().width() - 24)
            k = vw / r.width()
            from PySide6.QtGui import QTransform
            self.setTransform(QTransform.fromScale(k, k))
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            m = max(r.width(), r.height()) * 0.03
            self.fitInView(r.adjusted(-m, -m, m, m), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            self.fit()

    def wheelEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if isinstance(item, SlotItem) and item.fill() and not self.page.edit_mode:
            super().wheelEvent(e)
            return
        if self.long_mode() and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            QGraphicsView.wheelEvent(self, e)   # 长图：滚轮上下滚动，按住 Ctrl 才缩放
            return
        f = 1.15 if (e.angleDelta().y() or e.angleDelta().x()) > 0 else 1 / 1.15
        self.fit_mode = False
        self.scale(f, f)
        for it in self.scene().items():
            if isinstance(it, SlotItem):
                it.prepareGeometryChange()

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if self.page.edit_mode and e.button() == Qt.MouseButton.LeftButton and not isinstance(item, (SlotItem, TextItem)):
            self._band = self.mapToScene(e.position().toPoint())
            from PySide6.QtWidgets import QGraphicsRectItem
            self._band_item = QGraphicsRectItem()
            pen = QPen(QColor(theme.current()["accent"]), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._band_item.setPen(pen)
            self._band_item.setZValue(50)
            self.scene().addItem(self._band_item)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._band is not None:
            p = self.mapToScene(e.position().toPoint())
            self._band_item.setRect(QRectF(self._band, p).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._band is not None:
            r = self._band_item.rect()
            self.scene().removeItem(self._band_item)
            self._band_item = None
            self._band = None
            if r.width() > 20 and r.height() > 20:
                self.newSlot.emit(r)
            return
        super().mouseReleaseEvent(e)


# ================================================================ 后台：生成模板
class TemplateWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)
    stage = Signal(str)
    layout = None
    inpainter = None

    def __init__(self, path: str, get_detector, kind: str = "spec", parent=None):
        super().__init__(parent)
        self.path, self.get_detector, self.kind = path, get_detector, kind

    def run(self):
        try:
            self.stage.emit("正在加载识别模型")
            try:
                det = self.get_detector()
            except Exception:
                det = None
            self.done.emit(build_template(self.path, det, kind=self.kind, progress=self.stage.emit,
                                          layout=self.layout, inpainter=self.inpainter))
        except Exception as e:
            self.failed.emit(str(e))


# ================================================================ 页面
class TemplatePage(QWidget):
    kind = "spec"

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cfg = mw.cfg
        self.info = KINDS[self.kind]
        self.sc = self.cfg[self.kind]
        self.templates: list[dict] = []
        self.tpl: dict | None = None
        self.fills: dict[str, dict] = {}      # slot_id -> {"doc": doc_id, "ov": {...}}
        self.edit_mode = False
        self.exporting = False
        self.dirty = False
        self.scanning = False
        self._film_ids: list[str] = []
        self._loading = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, th = page_header(self.info["title"], self.info["sub"])
        b_imp = button("导入新模板…")
        b_imp.clicked.connect(self.import_template)
        self.b_export = button(f"导出这张{self.info['noun']}", "Primary")
        self.b_export.clicked.connect(self.export_current)
        th.addWidget(b_imp)
        th.addWidget(self.b_export)
        v.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(360)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self._build_side())
        body.addWidget(side)

        work = QWidget()
        work.setObjectName("Workspace")
        wv = QVBoxLayout(work)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(0)
        tb = QFrame()
        tb.setObjectName("Toolbar")
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(12, 6, 12, 6)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:700")
        self.b_edit = button("调整模板", "Tool", "移动、缩放图片位，或在空白处拖出新的图片位")
        self.b_edit.setCheckable(True)
        self.b_edit.toggled.connect(self.set_edit_mode)
        b_orig = button("看原图", "Tool", f"按住查看导入时的原始{self.info['noun']}")
        b_orig.pressed.connect(lambda: self._show_original(True))
        b_orig.released.connect(lambda: self._show_original(False))
        b_fit = button("适应窗口", "Tool")
        b_fit.clicked.connect(lambda: self.view.fit())
        tbh.addWidget(self.title)
        tbh.addStretch(1)
        for w in (self.b_edit, b_orig, b_fit):
            tbh.addWidget(w)
        wv.addWidget(tb)
        self.view = SpecView(self)
        self.view.newSlot.connect(self.add_slot)
        self.view.scene().selectionChanged.connect(self._sel_changed)
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.addStretch(1)
        e1 = QLabel(f"还没有{self.info['title'][2:]}模板")
        e1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e1.setStyleSheet("font-size:20px;font-weight:700")
        e2 = muted(f"点右上角「导入新模板」，选一张你喜欢的{self.info['noun']}。\n软件会自动找出照片框和文字，做成模板。")
        e2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eb = button("导入新模板…", "Primary")
        eb.setFixedWidth(180)
        eb.clicked.connect(self.import_template)
        ev.addWidget(e1)
        ev.addWidget(e2)
        ev.addSpacing(10)
        ev.addWidget(eb, 0, Qt.AlignmentFlag.AlignCenter)
        ev.addStretch(1)
        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.view)
        wv.addWidget(self.stack, 1)

        fb = QFrame()
        self.film_bar = fb
        fb.setObjectName("FilmBar")
        fv = QVBoxLayout(fb)
        fv.setContentsMargins(10, 6, 10, 2)
        fv.setSpacing(2)
        self.film_hint = muted("")
        fv.addWidget(self.film_hint)
        self.film = QListWidget()
        self.film.setObjectName("Film")
        self.film.setViewMode(QListWidget.ViewMode.IconMode)
        self.film.setFlow(QListWidget.Flow.LeftToRight)
        self.film.setWrapping(False)
        self.film.setMovement(QListWidget.Movement.Static)
        self.film.setIconSize(QSize(96, 96))
        self.film.setGridSize(QSize(118, 120))
        self.film.setFixedHeight(130)
        self.film.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.film.itemClicked.connect(self._film_clicked)
        fv.addWidget(self.film)
        wv.addWidget(fb)
        body.addWidget(work, 1)
        v.addLayout(body, 1)
        self.reload_templates()

    # ---------------------------------------------------------------- 左侧
    def use_mask(self) -> bool:
        return bool(self.sc.get("use_mask", True))

    def _mask_changed(self, k):
        self._save_sc("use_mask", k == "1")
        self._film_ids = []
        self.refresh()
        for it in getattr(self, "slot_items", {}).values():
            it.update()

    def _build_side(self):
        cr = Card("识别结果")
        self.review_card = cr
        self.review_sum = QLabel("")
        self.review_sum.setWordWrap(True)
        self.review_sum.setStyleSheet("font-size:15px;font-weight:600;")
        cr.add(self.review_sum)
        cr.add(muted("格子花纹 = 已经抠空的照片位（模特连同照片背景）。\n"
                     "虚线框 = 识别出来的文字。文字保持原样不动；"
                     "在下面「文字」里改了哪段，才会擦掉那段原字、换成新字。"))
        b_adj = button("调整识别结果", "", "拖动照片位的边角改范围，或在空白处拖出漏掉的照片位")
        b_adj.clicked.connect(lambda: self.b_edit.setChecked(not self.b_edit.isChecked()))
        b_redo = button("重新识别", "Ghost")
        b_redo.clicked.connect(self.rescan)
        cr.add(row(b_adj, None, b_redo))
        b_ok = button("没问题，下一步：填入素材", "Primary")
        b_ok.clicked.connect(self.confirm_review)
        cr.add(b_ok)
        c0 = Card("用哪个版本的图")
        self.mask_seg = Segmented([("1", "打码后的图"), ("0", "原图（不打码）")])
        self.mask_seg.changed.connect(self._mask_changed)
        c0.add(self.mask_seg)
        c1 = Card("模板")
        self.tpl_combo = QComboBox()
        self.tpl_combo.setIconSize(QSize(28, 28))
        # 名字很长时不把左侧面板撑宽（之前右半边的按钮会被挤出去看不见）
        self.tpl_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tpl_combo.setMinimumContentsLength(8)
        self.tpl_combo.currentIndexChanged.connect(self._tpl_selected)
        c1.add(self.tpl_combo)
        b_lib = button("模板库…", "", "看预览图选模板")
        b_lib.clicked.connect(self.open_library)
        b_ren = button("重命名", "Ghost")
        b_ren.clicked.connect(self.rename_current_template)
        c1.add(row(b_lib, None, b_ren))
        self.b_save = button("保存模板", "", "把图片位和文字的位置、样式存进模板，下次直接用")
        self.b_save.clicked.connect(self.save_current_template)
        b_del = button("删除模板", "Ghost")
        b_del.clicked.connect(self.delete_current_template)
        c1.add(row(self.b_save, None, b_del))
        self.tpl_hint = muted("")
        c1.add(self.tpl_hint)

        c2 = Card("图片位")
        self.slot_list = QListWidget()
        self.slot_list.setObjectName("Layers")
        self.slot_list.setIconSize(QSize(36, 36))
        self.slot_list.itemClicked.connect(self._slot_clicked)
        c2.add(self.slot_list)
        b_auto = button("自动填图（正面 / 背面）" if self.kind == "spec" else "自动填图", "Primary")
        b_auto.clicked.connect(self.auto_fill)
        b_clear = button("清空选中图片位", "Ghost")
        b_clear.clicked.connect(self.clear_selected_slot)
        c2.add(b_auto)
        c2.add(row(b_clear, None))
        self.b_del_slot = button("删除选中图片位", "Ghost")
        self.b_del_slot.clicked.connect(self.delete_selected_slot)
        c2.add(self.b_del_slot)
        self.shape_box = QWidget()
        shl = QVBoxLayout(self.shape_box)
        shl.setContentsMargins(0, 0, 0, 0)
        shl.setSpacing(4)
        shl.addWidget(muted("选中图片位的形状"))
        self.shape_seg = Segmented(SHAPES)
        self.shape_seg.changed.connect(self._set_shape)
        shl.addWidget(self.shape_seg)
        c2.add(self.shape_box)
        c2.add(muted("先点一个图片位，再点下面的素材填进去。填好后在图上拖动调位置，滚轮缩放，双击恢复。"))

        c3 = Card("文字")
        self.text_box = QWidget()
        self.text_lay = QVBoxLayout(self.text_box)
        self.text_lay.setContentsMargins(0, 0, 0, 0)
        self.text_lay.setSpacing(6)
        c3.add(self.text_box)
        b_add = button("＋ 添加文字")
        b_add.clicked.connect(self.add_text)
        self.b_del_text = button("删除选中文字", "Ghost")
        self.b_del_text.clicked.connect(self.delete_selected_text)
        c3.add(row(b_add, None, self.b_del_text))
        self.style_box = QWidget()
        sb = QVBoxLayout(self.style_box)
        sb.setContentsMargins(0, 4, 0, 0)
        sb.setSpacing(8)
        self.font_combo = QFontComboBox()
        self.font_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_combo.setMinimumContentsLength(8)
        self.font_combo.setWritingSystem(QFontDatabase.WritingSystem.SimplifiedChinese)
        self.font_combo.currentFontChanged.connect(lambda f: self._set_text("family", f.family()))
        sb.addWidget(self.font_combo)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 400)
        self.size_spin.setSuffix(" px")
        self.size_spin.valueChanged.connect(lambda v: self._set_text("size", float(v)))
        self.color_btn = ColorButton("#000000")
        self.color_btn.colorChanged.connect(lambda c: self._set_text("color", c))
        self.bold = QCheckBox("加粗")
        self.bold.toggled.connect(lambda on: self._set_text("bold", on))
        sb.addLayout(row(self.size_spin, self.color_btn, self.bold))
        b_all_font = button("所有文字都用这个字体", "Ghost")
        b_all_font.clicked.connect(self._font_to_all)
        sb.addWidget(b_all_font)
        c3.add(self.style_box)

        c4 = Card("导出")
        self.fmt = Segmented([("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")])
        self.fmt.changed.connect(lambda k: self._save_sc("format", k))
        c4.add(self.fmt)
        self.out_lbl = ElideLabel("")   # 路径太长时中间省略，不会把面板撑宽
        b_out = button("更改…")
        b_out.clicked.connect(lambda: (self.mw.choose_out_dir(), self._update_side()))
        c4.add(row(self.out_lbl, None, b_out))
        if self.kind == "detail":
            self.width_seg = Segmented([("750", "750 宽"), ("790", "790 宽"), ("1440", "1440 宽")])
            self.width_seg.changed.connect(lambda k: self._save_sc("width", int(k)))
            self.width_seg.set_value(str(self.sc.get("width", 790)))
            c4.add(self.width_seg)
            self.slice_combo = QComboBox()
            for v, t in ((0, "不切片，导出一整张"), (1000, "每 1000 像素切一段"), (1500, "每 1500 像素切一段"),
                         (2000, "每 2000 像素切一段")):
                self.slice_combo.addItem(t, v)
            self.slice_combo.setCurrentIndex(max(0, self.slice_combo.findData(int(self.sc.get("slice", 0)))))
            self.slice_combo.currentIndexChanged.connect(
                lambda _i: self._save_sc("slice", int(self.slice_combo.currentData())))
            c4.add(self.slice_combo)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(f"文件名，例如 6757白色{self.info['suffix']}")
        c4.add(self.name_edit)

        self.fill_cards = (c0, c2, c4)
        area, _ = scroll_page(cr, c0, c1, c2, c3, c4)
        self.fmt.set_value(self.sc.get("format", "jpg"))
        self.mask_seg.set_value("1" if self.sc.get("use_mask", True) else "0")
        return area

    # ---------------------------------------------------------------- 识别结果确认
    def in_review(self) -> bool:
        return bool(self.tpl) and not self.tpl.get("confirmed", True)

    def _apply_review_ui(self):
        if not hasattr(self, "film_bar") or not hasattr(self, "review_card"):
            return
        rv = self.in_review()
        self.review_card.setVisible(rv)
        for c in self.fill_cards:
            c.setVisible(not rv)
        self.film_bar.setVisible(not rv)
        if rv:
            n_s, n_t = len(self.tpl["slots"]), len(self.tpl["texts"])
            self.review_sum.setText(f"抠空了 {n_s} 个照片位，识别出 {n_t} 段文字")

    def confirm_review(self, name: str | None = None):
        if not self.tpl:
            return
        if name is None:
            from .template_lib import ask_name
            name = ask_name(self, "给模板起个名字", self.tpl.get("name", ""))
            if not name:
                return
        self.tpl["name"] = name
        self.tpl["confirmed"] = True
        if self.b_edit.isChecked():
            self.b_edit.setChecked(False)
        save_template(self.tpl)
        self.dirty = False
        self.reload_templates(select=self.tpl["id"])
        if self.mw.docs:
            self.auto_fill()
        self.mw.status.showMessage("模板已保存。点照片位再点下面的素材可以换图；拖动调位置，滚轮缩放。", 10000)

    def rescan(self):
        if not self.tpl:
            return
        from .spec_engine import templates_dir
        src = templates_dir() / self.tpl["id"] / "original.png"
        if not src.exists():
            QMessageBox.warning(self, "重新识别", "找不到这个模板的原图。")
            return
        old = self.tpl
        self.start_scan(str(src), replace=old)

    def _save_sc(self, k, v):
        self.sc[k] = v
        self.cfg.save()

    # ---------------------------------------------------------------- 模板
    def reload_templates(self, select: str | None = None):
        self.templates = load_templates(self.kind)
        self._loading = True
        self.tpl_combo.clear()
        from .template_lib import icon_for
        for t in self.templates:
            self.tpl_combo.addItem(icon_for(t, 44), t.get("name", "模板"), t["id"])
        self._loading = False
        sel = select or (self.tpl["id"] if self.tpl else None) or self.sc.get("last_template")
        idx = max(0, self.tpl_combo.findData(sel)) if self.templates else -1
        if idx >= 0:
            self.tpl_combo.setCurrentIndex(idx)
            self._tpl_selected(idx)
        else:
            self.tpl = None
            self.build_scene()

    def _tpl_selected(self, idx):
        if self._loading or idx < 0 or idx >= len(self.templates):
            return
        if self.dirty and self.tpl and self.tpl["id"] != self.templates[idx]["id"]:
            r = QMessageBox.question(self, "保存模板", f"模板「{self.tpl.get('name')}」改过了，要保存吗？")
            if r == QMessageBox.StandardButton.Yes:
                save_template(self.tpl)
        self.tpl = copy.deepcopy(self.templates[idx])
        self.sc["last_template"] = self.tpl["id"]
        self.cfg.save()
        self.dirty = False
        keep = {s["id"]: self.fills[s["id"]] for s in self.tpl["slots"] if s["id"] in self.fills}
        self.fills = keep
        self.build_scene()

    def import_template(self):
        f, _ = QFileDialog.getOpenFileName(self, f"选择一张{self.info['noun']}", self.cfg["last_dir"],
                                           "图片 (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not f:
            return
        self.ensure_layout_model(lambda: self.start_scan(f))

    def ensure_layout_model(self, then):
        """第一次用时下载 AI 模型（照片识别、AI 去字），一次提示、依次下载；不想下载也可以先用普通识别。"""
        from . import inpaint, layout_model
        need = []
        for mod, label in ((layout_model, "照片识别"), (inpaint, "AI 去字")):
            path = mod.layout_model_path() if mod is layout_model else mod.inpaint_model_path()
            if not path.exists() and mod.MODEL_SHA256:
                need.append((mod, label))
        if not need or self.cfg.data.get("layout_declined"):
            then()
            return
        total = sum(m.MODEL_SIZE for m, _ in need)
        box = QMessageBox(self)
        box.setWindowTitle("下载 AI 模型")
        box.setText(f"第一次使用需要下载 AI 模型（{'、'.join(l for _, l in need)}，共约 {total // 1048576} MB，只下载一次）。\n\n"
                    "照片识别：深色背景、模糊照片当底色的模板也能准确找出照片框；\n"
                    "AI 去字：擦掉原来的字时，把花纹、渐变底一起补回来。")
        b_dl = box.addButton("现在下载", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("先用普通识别", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not b_dl:
            then()
            return
        from .updater import Downloader
        dlg = QProgressDialog("正在下载 AI 模型…", "取消", 0, 1000, self)
        dlg.setWindowTitle("下载 AI 模型")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)
        state = {"done_bytes": 0, "i": 0, "w": None, "cancel": False}

        def finish(msg=None):
            dlg.close()
            self.mw._layout = "unset"
            self.mw._inpainter = "unset"
            if msg and msg != "已取消":
                QMessageBox.warning(self, "下载 AI 模型",
                                    f"下载没成功：{msg}\n\n这次先用普通识别；下次导入模板时会再试。"
                                    "也可以在「设置 → 更新」里换一条下载线路。")
            then()

        def start_next():
            if state["i"] >= len(need):
                finish()
                return
            mod, label = need[state["i"]]
            name = "layout.onnx" if mod is layout_model else "lama.onnx"
            w = Downloader(mod.model_url(), name, mod.MODEL_SHA256, mod.MODEL_SIZE, self)
            state["w"] = w
            dlg.setLabelText(f"正在下载{label}模型（{state['i'] + 1}/{len(need)}）…")
            w.progress.connect(lambda got, _tot: dlg.setValue(int((state["done_bytes"] + got) * 1000 / max(1, total))))
            w.status.connect(lambda m, lb=label: dlg.setLabelText(f"{lb}：{m}"))

            def ok(path, mod=mod):
                try:
                    import shutil
                    dst = mod.downloaded_path()
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(path, dst)
                except Exception as e:
                    finish(f"保存模型失败：{e}")
                    return
                state["done_bytes"] += mod.MODEL_SIZE
                state["i"] += 1
                start_next()

            w.done.connect(ok)
            w.failed.connect(finish)
            w.start()

        dlg.canceled.connect(lambda: state["w"] and state["w"].requestInterruption())
        start_next()

    # ---------------------------------------------------------------- 导入动画
    def start_scan(self, path: str, replace: dict | None = None):
        from .model import load_qimage
        from .scanfx import ScanOverlay, ScanStatus
        img = load_qimage(path)
        if img is None:
            QMessageBox.warning(self, "导入失败", "读取不了这张图片")
            return
        self.scanning = True
        self._scan_replace = replace
        if self.b_edit.isChecked():
            self.b_edit.setChecked(False)
        self.set_edit_mode(False)
        self.tpl = None
        sc = self.view.scene()
        old = list(sc.items())
        for it in old:
            sc.removeItem(it)
        self._grave = old
        QTimer.singleShot(0, lambda: setattr(self, "_grave", []))
        self.slot_items, self.text_items = {}, {}
        self.stack.setCurrentIndex(1)
        bg = ImageItem()
        bg.set_image(img)
        sc.addItem(bg)
        r = QRectF(0, 0, img.width(), img.height())
        sc.setSceneRect(r)
        pal = theme.current()
        ov = ScanOverlay(r, pal["accent"], self.view_scale,
                         lambda s: slot_path(s, QRectF(s["x"], s["y"], s["w"], s["h"])))
        sc.addItem(ov)
        self._scan = ov
        if not hasattr(self, "scan_status"):
            self.scan_status = ScanStatus(self.view)
        self.scan_status.style_for(pal["accent"])
        self.scan_status.show_text("正在准备")
        QTimer.singleShot(0, self.view.fit)
        self._scan_started = time.monotonic()
        self._update_side()
        w = TemplateWorker(path, self.mw.get_detector, self.kind, self)
        w.layout = self.mw.get_layout()      # 版面分析模型在界面线程里先加载好
        w.inpainter = self.mw.get_inpainter()
        self._tw = w
        # 注意：后台线程发出的信号要连到界面对象的方法上（会排队到界面线程执行），不能连 lambda
        w.stage.connect(self.scan_status.show_text)
        w.done.connect(self._scan_done)
        w.failed.connect(self._scan_failed)
        w.start()

    def _scan_done(self, tpl: dict):
        # 至少扫一会儿再出结果，不然动画一闪而过
        wait = max(0, int((1.4 - (time.monotonic() - self._scan_started)) * 1000))
        QTimer.singleShot(wait, lambda: self._scan_reveal(tpl))

    def _scan_reveal(self, tpl: dict):
        n_s, n_t = len(tpl["slots"]), len(tpl["texts"])
        self.scan_status.show_text(f"找到 {n_s} 个照片位、{n_t} 段文字", animate=False)
        self._scan.reveal(tpl["slots"], tpl["texts"], lambda: self._scan_finish(tpl))

    def _scan_finish(self, tpl: dict):
        self.scanning = False
        self._scan.stop()
        self.scan_status.finish()
        old = getattr(self, "_scan_replace", None)
        if old and old.get("id") != tpl["id"]:
            tpl["name"] = old.get("name", tpl["name"])
            save_template(tpl)
            delete_template(old)
        self._scan_replace = None
        self.reload_templates(select=tpl["id"])

    def _scan_failed(self, msg: str):
        self.scanning = False
        if getattr(self, "_scan", None):
            self._scan.stop()
        self.scan_status.finish()
        self.reload_templates()
        QMessageBox.warning(self, "导入失败", msg)

    def open_library(self):
        from .template_lib import TemplatePicker
        dlg = TemplatePicker(self.kind, self.tpl["id"] if self.tpl else None, self)
        dlg.exec()
        self.reload_templates(select=dlg.result_tpl["id"] if dlg.result_tpl else None)

    def rename_current_template(self):
        from .template_lib import rename
        if self.tpl and rename(self, self.tpl):
            self.reload_templates(select=self.tpl["id"])

    def save_current_template(self):
        if not self.tpl:
            return
        save_template(self.tpl)
        self.dirty = False
        self.reload_templates(select=self.tpl["id"])
        self.mw.status.showMessage(f"模板「{self.tpl.get('name')}」已保存", 4000)

    def delete_current_template(self):
        if not self.tpl:
            return
        r = QMessageBox.question(self, "删除模板", f"删除模板「{self.tpl.get('name')}」？这个操作不能撤销。")
        if r != QMessageBox.StandardButton.Yes:
            return
        delete_template(self.tpl)
        self.tpl = None
        self.fills = {}
        self.reload_templates()

    def on_template_changed(self, dirty: bool = False):
        if dirty:
            self.dirty = True
        self._update_side()

    def set_edit_mode(self, on: bool):
        self.edit_mode = on
        for it in self.view.scene().items():
            if isinstance(it, SlotItem):
                it.prepareGeometryChange()
                it.update()
        self._update_side()

    def _composite(self) -> QImage:
        from .spec_engine import composite_bg, text_changed
        self._bg_sig = tuple(t["id"] for t in self.tpl["texts"] if text_changed(t))
        return composite_bg(self.tpl)

    def schedule_bg_refresh(self):
        """改了字以后，把原字那块换成擦干净的底（稍等一下再换，打字时不卡）。"""
        if not hasattr(self, "_bg_timer"):
            self._bg_timer = QTimer(self)
            self._bg_timer.setSingleShot(True)
            self._bg_timer.setInterval(120)
            self._bg_timer.timeout.connect(self._refresh_bg)
        self._bg_timer.start()

    def _refresh_bg(self):
        from .spec_engine import text_changed
        if not self.tpl or not hasattr(self, "bg_item"):
            return
        sig = tuple(t["id"] for t in self.tpl["texts"] if text_changed(t))
        if sig != self._bg_sig:
            self.bg_item.set_image(self._composite())

    def _show_original(self, on: bool):
        if not self.tpl:
            return
        from .spec_engine import templates_dir
        img = QImage(str(templates_dir() / self.tpl["id"] / "original.png")) if on else self._composite()
        self.bg_item.set_image(img)
        for it in self.view.scene().items():
            if isinstance(it, (SlotItem, TextItem)):
                it.setVisible(not on)

    # ---------------------------------------------------------------- 画布
    def view_scale(self) -> float:
        return self.view.transform().m11() or 1.0

    def build_scene(self):
        sc = self.view.scene()
        sc.blockSignals(True)
        old = list(sc.items())
        for it in old:
            sc.removeItem(it)
        self._grave = old  # 等下一轮事件再释放，避免闪退
        QTimer.singleShot(0, lambda: setattr(self, "_grave", []))
        sc.blockSignals(False)
        self.slot_items: dict[str, SlotItem] = {}
        self.text_items: dict[str, TextItem] = {}
        if not self.tpl:
            self.stack.setCurrentIndex(0)
            self._update_side()
            return
        self.stack.setCurrentIndex(1)
        self.bg_item = ImageItem()
        self._bg_sig = None
        self.bg_item.set_image(self._composite())
        sc.addItem(self.bg_item)
        sc.setSceneRect(QRectF(0, 0, self.tpl["w"], self.tpl["h"]))
        for s in self.tpl["slots"]:
            it = SlotItem(self, s)
            sc.addItem(it)
            self.slot_items[s["id"]] = it
        for t in self.tpl["texts"]:
            it = TextItem(self, t)
            sc.addItem(it)
            self.text_items[t["id"]] = it
        QTimer.singleShot(0, self.view.fit)
        self._rebuild_text_rows()
        self._update_side()

    def _sel_changed(self):
        self._update_side()

    def selected(self):
        for it in self.view.scene().selectedItems():
            return it
        return None

    def add_slot(self, r: QRectF):
        if not self.tpl:
            return
        n = len(self.tpl["slots"])
        roles = ["正面", "背面"]
        s = {"id": uuid.uuid4().hex[:8], "x": r.x(), "y": r.y(), "w": r.width(), "h": r.height(),
             "role": (roles[n] if n < 2 else f"图片{n + 1}") if self.kind == "spec" else f"图片{n + 1}",
             "shape": "rect", "radius": 0.0}
        self.tpl["slots"].append(s)
        it = SlotItem(self, s)
        self.view.scene().addItem(it)
        self.slot_items[s["id"]] = it
        self.view.scene().clearSelection()
        it.setSelected(True)
        self.dirty = True
        self._update_side()

    def _set_shape(self, key: str):
        it = self.selected()
        if self._loading or not isinstance(it, SlotItem):
            return
        s = it.slot
        if key == "ellipse":
            s["shape"], s["radius"] = "ellipse", 0.5
        else:
            s["shape"] = "rect"
            s["radius"] = {"rect": 0.0, "round": 0.12, "capsule": 0.5}[key]
        it.update()
        self.dirty = True
        self._update_side()

    def delete_selected_slot(self):
        it = self.selected()
        if not isinstance(it, SlotItem) or not self.tpl:
            return
        sid = it.slot["id"]
        self.tpl["slots"] = [s for s in self.tpl["slots"] if s["id"] != sid]
        self.fills.pop(sid, None)
        self.dirty = True
        self.build_scene()

    def clear_selected_slot(self):
        it = self.selected()
        if isinstance(it, SlotItem):
            self.fills.pop(it.slot["id"], None)
            it.update()
            self._update_side()

    def fill_slot(self, sid: str, doc_id: str):
        self.fills[sid] = {"doc": doc_id, "ov": {}}
        it = self.slot_items.get(sid)
        if it:
            it.update()
        self._update_side()

    def auto_fill(self):
        if not self.tpl or not self.mw.docs:
            if not self.mw.docs:
                QMessageBox.information(self, "自动填图", "先在「素材」或「智能打码」里导入这一款的模特图。")
            return
        need = lambda d: d.labels is None or (d.facing is None and self.mw.has_pose())
        if any(need(d) and not d.error for d in self.mw.docs):
            if self.mw.busy:
                self.mw.status.showMessage("正在识别，请稍等…", 3000)
                return
            self.mw.analyze_subjects(then=self.auto_fill, labels=True)
            self.mw.status.showMessage("正在识别哪些是正面、哪些是背面…", 4000)
            return
        docs = [d for d in self.mw.docs if not d.error]
        from .pose import facing_of, facing_score

        def score(d):
            # 有姿态模型时用它的打分；没有时只按部位判断
            return d.facing if d.facing is not None else facing_score(None, d.labels or [])
        fronts = sorted([d for d in docs if facing_of(score(d)) == "front"], key=score, reverse=True)
        backs = sorted([d for d in docs if facing_of(score(d)) == "back"], key=score)
        used = set()

        def take(pool):
            for d in pool:
                if d.id not in used:
                    used.add(d.id)
                    return d
            return None

        for s in self.tpl["slots"]:
            role = s.get("role", "")
            d = take(fronts) if role == "正面" else take(backs) if role == "背面" else None
            d = d or take(docs)
            if d is None and self.kind == "detail" and docs:
                used.clear()          # 详情图的图片位多，素材不够就从头再用一遍
                d = take(docs)
            if d:
                self.fills[s["id"]] = {"doc": d.id, "ov": {}}
        for it in self.slot_items.values():
            it.update()
        self._update_side()

    def _film_clicked(self, it):
        did = it.data(Qt.ItemDataRole.UserRole)
        if not self.tpl:
            return
        sel = self.selected()
        if isinstance(sel, SlotItem):
            sid = sel.slot["id"]
        else:
            empty = [s["id"] for s in self.tpl["slots"] if s["id"] not in self.fills]
            sid = empty[0] if empty else None
            if sid is None:
                self.mw.status.showMessage("先在图上点一下要换的图片位", 4000)
                return
        self.fill_slot(sid, did)

    def _slot_clicked(self, it):
        sid = it.data(Qt.ItemDataRole.UserRole)
        si = self.slot_items.get(sid)
        if si:
            self.view.scene().clearSelection()
            si.setSelected(True)

    # ---------------------------------------------------------------- 文字
    def _rebuild_text_rows(self):
        while self.text_lay.count():
            w = self.text_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.text_edits: dict[str, QLineEdit] = {}
        if not self.tpl:
            return
        for t in self.tpl["texts"]:
            e = QLineEdit(t["text"])
            e.textEdited.connect(lambda txt, tid=t["id"]: self._edit_text(tid, txt))
            e.installEventFilter(self)
            e.setProperty("tid", t["id"])
            self.text_lay.addWidget(e)
            self.text_edits[t["id"]] = e
        if not self.tpl["texts"]:
            err = (self.tpl or {}).get("ocr_error")
            if err:
                lbl = muted(f"文字识别出错了：{err}\n\n可以先点「添加文字」手动加；把这行错误发给作者能更快修好。")
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.text_lay.addWidget(lbl)
            else:
                self.text_lay.addWidget(muted("没有识别到文字，可以点「添加文字」。"))

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.FocusIn and isinstance(obj, QLineEdit) and obj.property("tid"):
            ti = self.text_items.get(obj.property("tid"))
            if ti and not ti.isSelected():
                self.view.scene().clearSelection()
                ti.setSelected(True)
        return False

    def _edit_text(self, tid, txt):
        for t in self.tpl["texts"]:
            if t["id"] == tid:
                t["text"] = txt
                ti = self.text_items.get(tid)
                if ti:
                    ti.sync()
        self.dirty = True

    def add_text(self):
        if not self.tpl:
            return
        size = max(18.0, self.tpl["w"] * 0.04)
        t = {"id": uuid.uuid4().hex[:8], "text": "新文字", "x": self.tpl["w"] * 0.1, "y": self.tpl["h"] * 0.1,
             "w": 0, "h": size * 1.2, "size": size, "color": "#222222", "bold": False, "family": ""}
        self.tpl["texts"].append(t)
        it = TextItem(self, t)
        self.view.scene().addItem(it)
        self.text_items[t["id"]] = it
        self._rebuild_text_rows()
        self.view.scene().clearSelection()
        it.setSelected(True)
        self.dirty = True
        e = self.text_edits.get(t["id"])
        if e:
            e.setFocus()
            e.selectAll()

    def delete_selected_text(self):
        it = self.selected()
        if not isinstance(it, TextItem) or not self.tpl:
            return
        tid = it.t["id"]
        self.tpl["texts"] = [t for t in self.tpl["texts"] if t["id"] != tid]
        self.dirty = True
        self.build_scene()

    def _set_text(self, key, v):
        if self._loading:
            return
        it = self.selected()
        if isinstance(it, TextItem):
            it.t[key] = v
            it.sync()
            self.dirty = True

    def _font_to_all(self):
        if not self.tpl:
            return
        fam = self.font_combo.currentFont().family()
        for t in self.tpl["texts"]:
            t["family"] = fam
        for it in self.text_items.values():
            it.sync()
        self.dirty = True

    # ---------------------------------------------------------------- 左侧状态
    def _update_side(self):
        self._apply_review_ui()
        tpl = self.tpl
        self.title.setText(f"{tpl.get('name')}　{tpl['w']}×{tpl['h']}" + ("　·　未保存" if self.dirty else "")
                           if tpl else "")
        self.b_export.setEnabled(bool(tpl))
        self.b_save.setEnabled(bool(tpl))
        self.tpl_hint.setText(f"{len(tpl['slots'])} 个图片位 · {len(tpl['texts'])} 段文字" if tpl
                              else "还没有模板，点右上角「导入新模板」")
        sel = self.selected()
        self.slot_list.clear()
        if tpl:
            for s in tpl["slots"]:
                f = self.fills.get(s["id"])
                d = self.mw.doc_by_id(f["doc"]) if f else None
                it = QListWidgetItem(doc_icon(d, self.use_mask(), QIcon()) if d else QIcon(),
                                     f"{s.get('role', '图片')}　" + (d.name[:18] if d else "未填图"))
                it.setData(Qt.ItemDataRole.UserRole, s["id"])
                self.slot_list.addItem(it)
                if isinstance(sel, SlotItem) and sel.slot["id"] == s["id"]:
                    it.setSelected(True)
        self.slot_list.setFixedHeight(min(200, 44 * max(1, self.slot_list.count()) + 6))
        self.b_del_slot.setVisible(self.edit_mode)
        is_slot = isinstance(sel, SlotItem)
        self.shape_box.setVisible(self.edit_mode and is_slot)
        if is_slot:
            self._loading = True
            self.shape_seg.set_value(slot_shape_key(sel.slot))
            self._loading = False
        is_text = isinstance(sel, TextItem)
        self.style_box.setVisible(is_text)
        self.b_del_text.setEnabled(is_text)
        if is_text:
            self._loading = True
            t = sel.t
            self.font_combo.setCurrentFont(QFont(t.get("family") or DEFAULT_FONT))
            self.size_spin.setValue(int(round(t.get("size", 24))))
            self.color_btn.set_color(t.get("color", "#000000"))
            self.bold.setChecked(bool(t.get("bold")))
            self._loading = False
        out = self.cfg["export"].get("dir") or ""
        self.out_lbl.setText(f"保存到：{out}\\{self.info['folder']}" if out else "保存到：还没有选择文件夹")
        n = len(self.mw.docs)
        self.film_hint.setText("点一个图片位，再点这里的图片填进去" if n else "还没有素材：先在「素材」或「智能打码」里导入模特图")

    # ---------------------------------------------------------------- 显示
    def on_show(self):
        self.refresh()

    def refresh(self):
        ids = [d.id for d in self.mw.docs]
        if self._film_ids != ids:
            self.film.clear()
            for d in self.mw.docs:
                it = QListWidgetItem(doc_icon(d, self.use_mask(), self.mw._placeholder), "")
                it.setData(Qt.ItemDataRole.UserRole, d.id)
                it.setToolTip(d.name)
                self.film.addItem(it)
            self._film_ids = ids
            self.fills = {k: v for k, v in self.fills.items() if v["doc"] in ids}
            for it in getattr(self, "slot_items", {}).values():
                it.update()
        self._update_side()

    def update_icon(self, d):
        for i in range(self.film.count()):
            it = self.film.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == d.id and d.icon is not None:
                it.setIcon(doc_icon(d, self.use_mask(), self.mw._placeholder))
        for sid, f in self.fills.items():
            if f["doc"] == d.id and sid in getattr(self, "slot_items", {}):
                self.slot_items[sid].update()

    def apply_theme(self):
        self.view.apply_theme()

    # ---------------------------------------------------------------- 导出
    def render_output(self) -> QImage | None:
        tpl = self.tpl
        if not tpl:
            return None
        W, H = int(tpl["w"]), int(tpl["h"])
        out = QImage(W, H, QImage.Format.Format_RGB32)
        out.fill(QColor("#ffffff"))
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        from .spec_engine import composite_bg, text_changed
        p.drawImage(QRectF(0, 0, W, H), composite_bg(tpl))
        for s in tpl["slots"]:
            f = self.fills.get(s["id"])
            doc = self.mw.doc_by_id(f["doc"]) if f else None
            img = render_slot(s, doc, f["ov"], self.mw.library, 1.0, preview=False,
                              masked=self.use_mask()) if doc else None
            if img is not None:
                rr = QRectF(s["x"], s["y"], s["w"], s["h"])
                p.save()
                p.setClipPath(slot_path(s, rr))
                p.drawImage(rr, img)
                p.restore()
            kimg, kx, ky = keep_image(tpl["id"], s)
            if kimg is not None:
                p.drawImage(QPointF(kx, ky), kimg)
        for t in tpl["texts"]:
            if text_changed(t):
                draw_text(p, t)
        p.end()
        return out

    def finalize(self, img: QImage) -> list[QImage]:
        """规格图原样输出；详情图按设置的宽度缩放，再按高度切成几段。"""
        if self.kind != "detail":
            return [img]
        w = int(self.sc.get("width", 790))
        if w and img.width() != w:
            img = img.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        step = int(self.sc.get("slice", 0))
        if not step or img.height() <= step * 1.15:
            return [img]
        pieces, y = [], 0
        while y < img.height():
            h = min(step, img.height() - y)
            if img.height() - (y + h) < step * 0.15:   # 最后一段太短，并到这一段里
                h = img.height() - y
            pieces.append(img.copy(0, y, img.width(), h))
            y += h
        return pieces

    def export_current(self):
        if not self.tpl or self.mw.busy:
            return
        empty = [s.get("role") for s in self.tpl["slots"] if s["id"] not in self.fills]
        if empty:
            r = QMessageBox.question(self, "导出", f"还有 {len(empty)} 个图片位没填图（{'、'.join(empty)}），"
                                                   f"会显示原{self.info['noun']}的背景。继续导出吗？")
            if r != QMessageBox.StandardButton.Yes:
                return
        root = self.mw._ensure_out_dir()
        if root is None:
            return
        out = root / self.info["folder"]
        out.mkdir(parents=True, exist_ok=True)
        name = self.name_edit.text().strip()
        if not name:
            first = next((self.mw.doc_by_id(f["doc"]) for f in self.fills.values()), None)
            name = (first.path.stem if first else self.tpl.get("name", self.info["folder"])) + self.info["suffix"]
        fmt = self.sc.get("format", "jpg")
        ext = FORMATS.get(fmt, FORMATS["jpg"])[0]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            img = self.render_output()
            ex = {"format": fmt, "quality": int(self.cfg["export"].get("quality", 92))}
            ow = bool(self.cfg["export"].get("overwrite"))
            pieces = self.finalize(img)
            if len(pieces) == 1:
                path = unique_path(out, f"{name}.{ext}", ow, set())
                save_image(pieces[0], path, ex)
            else:
                taken: set = set()
                for i, piece in enumerate(pieces, 1):
                    path = unique_path(out, f"{name}_{i:02d}.{ext}", ow, taken)
                    taken.add(str(path).lower())
                    save_image(piece, path, ex)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "导出失败", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.mw.status.showMessage(f"已导出{self.info['noun']}：{path}", 10000)
        if self.cfg["export"].get("open_after", True):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return path


class SpecPage(TemplatePage):
    kind = "spec"


class DetailPage(TemplatePage):
    kind = "detail"
