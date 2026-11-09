"""图片编辑画布：显示原图和码，支持移动、缩放、旋转、倾斜。导出也复用这里的绘制逻辑。"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPainterPath, QPen,
                           QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from . import theme
from .config import IMAGE_EXTS
from .model import ImageDoc, Layer

HANDLE = 10.0     # 手柄大小（屏幕像素）
ROT_OFF = 30.0    # 旋转手柄离顶部的距离（屏幕像素）


class RenderContext:
    """画布和导出共用的绘制上下文。"""

    def __init__(self, library):
        self.library = library
        self.image: QImage | None = None
        self.doc: ImageDoc | None = None
        self.exporting = False
        self.hide_layers = False
        self.view_scale = 1.0
        self._fx: dict = {}
        # 由画布设置的回调
        self.on_begin_edit = lambda: None
        self.on_live_edit = lambda: None
        self.on_end_edit = lambda: None

    def set_image(self, doc, image):
        self.doc = doc
        self.image = image
        self._fx.clear()

    def effect(self, style: str, block: float):
        """返回 (小图, 目标矩形, 是否平滑)，用于马赛克 / 模糊。"""
        img = self.image
        W, H = img.width(), img.height()
        b = max(2.0, block * W)
        key = (style, round(b, 1))
        hit = self._fx.get(key)
        if hit:
            return hit
        if len(self._fx) > 12:
            self._fx.clear()
        if style == "mosaic":
            sw, sh = max(1, math.ceil(W / b)), max(1, math.ceil(H / b))
            small = img.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            res = (small, QRectF(0, 0, sw * b, sh * b), False)
        else:
            f = max(2.0, b * 0.9)
            sw, sh = max(1, round(W / f)), max(1, round(H / f))
            small = img.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            res = (small, QRectF(0, 0, W, H), True)
        self._fx[key] = res
        return res


class ImageItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.img: QImage | None = None
        self.setZValue(0)

    def set_image(self, img: QImage | None):
        self.prepareGeometryChange()
        self.img = img
        self.update()

    def boundingRect(self) -> QRectF:
        if self.img is None:
            return QRectF()
        return QRectF(0, 0, self.img.width(), self.img.height())

    def paint(self, p, opt, widget=None):
        if self.img is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(QPointF(0, 0), self.img)


class LayerItem(QGraphicsObject):
    def __init__(self, layer: Layer, ctx: RenderContext):
        super().__init__()
        self.layer = layer
        self.ctx = ctx
        self._drag = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.sync()

    # ---- 几何 ----
    def sync(self):
        L = self.layer
        self.prepareGeometryChange()
        self.setPos(L.cx, L.cy)
        shear = QTransform()
        shear.shear(math.tan(math.radians(max(-80.0, min(80.0, L.skew)))), 0)
        rot = QTransform()
        rot.rotate(L.rot)
        self.setTransform(shear * rot)
        self.update()

    def _s(self) -> float:
        return self.ctx.view_scale or 1.0

    def body(self) -> QRectF:
        L = self.layer
        return QRectF(-L.w / 2, -L.h / 2, L.w, L.h)

    def _corners(self):
        r = self.body()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _rot_pt(self) -> QPointF:
        return QPointF(0, -self.layer.h / 2 - ROT_OFF / self._s())

    def boundingRect(self) -> QRectF:
        s = self._s()
        pad = (HANDLE + 4) / s
        top = (ROT_OFF + HANDLE + 4) / s
        r = self.body()
        return r.adjusted(-pad, -top, pad, pad)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.body())
        if self.isSelected() and not self.ctx.exporting:
            t = (HANDLE + 4) / self._s()
            for c in self._corners() + [self._rot_pt()]:
                path.addRect(QRectF(c.x() - t, c.y() - t, 2 * t, 2 * t))
        return path

    def hit(self, pos: QPointF):
        """判断按在哪里：旋转点、四个角（缩放），还是码本身（移动）。"""
        L = self.layer
        inside = self.body().contains(pos)
        if self.isSelected():
            t = (HANDLE + 4) / self._s()
            rp = self._rot_pt()
            if abs(pos.x() - rp.x()) <= t and abs(pos.y() - rp.y()) <= t:
                return "rotate"
            # 码很小时，角的判定范围不能盖住整个码，否则只能缩放、拖不动
            tc = t if not inside else min(t, min(L.w, L.h) * 0.22)
            for c in self._corners():
                if abs(pos.x() - c.x()) <= tc and abs(pos.y() - c.y()) <= tc:
                    return "scale"
        if inside:
            return "move"
        if self.isSelected():
            return "scale" if self._near_corner(pos) else None
        return None

    def _near_corner(self, pos: QPointF) -> bool:
        t = (HANDLE + 4) / self._s()
        return any(abs(pos.x() - c.x()) <= t and abs(pos.y() - c.y()) <= t for c in self._corners())

    # ---- 绘制 ----
    def paint(self, p: QPainter, opt, widget=None):
        L = self.layer
        ctx = self.ctx
        if not ctx.hide_layers:
            r = self.body()
            p.save()
            p.setOpacity(max(0.05, min(1.0, L.opacity)))
            if L.style == "sticker":
                img = ctx.library.image(L.sticker)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                if L.flip:
                    p.scale(-1, 1)
                p.drawImage(r, img)
            elif L.style == "solid":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(L.color))
                rad = min(L.w, L.h) * 0.18
                p.drawRoundedRect(r, rad, rad)
            elif ctx.image is not None:
                path = QPainterPath()
                path.addEllipse(r)
                p.setClipPath(path)
                inv, ok = self.sceneTransform().inverted()
                if ok:
                    p.setTransform(inv * p.transform())
                    small, dest, smooth = ctx.effect(L.style, L.block)
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
                    p.drawImage(dest, small)
            p.restore()
        if self.isSelected() and not ctx.exporting:
            self._paint_handles(p)

    def _paint_handles(self, p: QPainter):
        pal = theme.current()
        acc = QColor(pal["accent"])
        s = self._s()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(acc, 1.5)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.body())
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        rp = self._rot_pt()
        p.drawLine(QPointF(0, -self.layer.h / 2), rp)
        hs = HANDLE / s
        p.setBrush(QColor("#ffffff"))
        for c in self._corners():
            p.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))
        p.setBrush(acc)
        p.drawEllipse(rp, hs * 0.6, hs * 0.6)
        p.restore()

    # ---- 交互 ----
    def hoverMoveEvent(self, e):
        mode = self.hit(e.pos())
        cur = {"rotate": Qt.CursorShape.PointingHandCursor,
               "scale": Qt.CursorShape.SizeFDiagCursor,
               "move": Qt.CursorShape.SizeAllCursor}.get(mode, Qt.CursorShape.ArrowCursor)
        self.setCursor(QCursor(cur))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            e.ignore()
            return
        if not self.isSelected():
            sc = self.scene()
            if sc:
                sc.clearSelection()
            self.setSelected(True)
        mode = self.hit(e.pos()) or "move"
        L = self.layer
        self._drag = {"mode": mode, "start": e.scenePos(), "cx": L.cx, "cy": L.cy,
                      "w": L.w, "h": L.h, "pushed": False}
        e.accept()

    def mouseMoveEvent(self, e):
        d = self._drag
        if not d:
            return
        L = self.layer
        if not d["pushed"]:
            delta = e.scenePos() - d["start"]
            if abs(delta.x()) + abs(delta.y()) < 1.5 / self._s():
                return
            self.ctx.on_begin_edit()
            d["pushed"] = True
        mods = e.modifiers()
        if d["mode"] == "move":
            delta = e.scenePos() - d["start"]
            L.cx = d["cx"] + delta.x()
            L.cy = d["cy"] + delta.y()
        elif d["mode"] == "scale":
            local = self.mapFromScene(e.scenePos())
            w = max(4.0, abs(local.x()) * 2)
            h = max(4.0, abs(local.y()) * 2)
            if mods & Qt.KeyboardModifier.ShiftModifier:
                k = max(w / d["w"], h / d["h"])
                w, h = d["w"] * k, d["h"] * k
            L.w, L.h = w, h
        elif d["mode"] == "rotate":
            sp = e.scenePos()
            a = math.degrees(math.atan2(sp.y() - L.cy, sp.x() - L.cx)) + 90
            if mods & Qt.KeyboardModifier.ShiftModifier:
                a = round(a / 15) * 15
            a = ((a + 540) % 360) - 180
            L.rot = round(a, 1)
        self.sync()
        self.ctx.on_live_edit()

    def mouseReleaseEvent(self, e):
        d = self._drag
        self._drag = None
        if d and d["pushed"]:
            self.ctx.on_end_edit()


class Canvas(QGraphicsView):
    selectionChanged = Signal(object)    # Layer | None
    liveEdited = Signal()
    edited = Signal()
    beginEdit = Signal()
    addRequested = Signal(QPointF)
    filesDropped = Signal(list)
    navigate = Signal(int)
    zoomChanged = Signal(float)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.ctx = RenderContext(library)
        self.ctx.on_begin_edit = self.beginEdit.emit
        self.ctx.on_live_edit = self.liveEdited.emit
        self.ctx.on_end_edit = self.edited.emit
        self.doc: ImageDoc | None = None
        self.items: dict[str, LayerItem] = {}
        self.fit_mode = True
        self._pan = None
        self._nudging = False
        self._graveyard: list = []
        from PySide6.QtCore import QTimer as _QT
        self._grave_timer = _QT(self)
        self._grave_timer.setSingleShot(True)
        self._grave_timer.setInterval(0)
        self._grave_timer.timeout.connect(self._graveyard.clear)
        # 方向键连续微调时，停下来再通知一次，避免每一下都刷新界面和缩略图
        from PySide6.QtCore import QTimer
        self._nudge_timer = QTimer(self)
        self._nudge_timer.setSingleShot(True)
        self._nudge_timer.setInterval(120)
        self._nudge_timer.timeout.connect(self.edited.emit)

        sc = QGraphicsScene(self)
        self.setScene(sc)
        self.base = ImageItem()
        sc.addItem(self.base)
        sc.selectionChanged.connect(self._on_sel)

        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.apply_theme()

    def apply_theme(self):
        self.setBackgroundBrush(QColor(theme.current()["stage"]))
        self.viewport().update()

    # ---- 文档 ----
    def set_doc(self, doc: ImageDoc | None, image: QImage | None):
        self.doc = doc
        self.ctx.set_image(doc, image)
        self.base.set_image(image)
        if image is not None:
            w, h = image.width(), image.height()
            m = max(w, h)
            self.scene().setSceneRect(QRectF(-m, -m, w + 2 * m, h + 2 * m))
        self.rebuild()
        self.fit()

    def rebuild(self, select_id: str | None = None):
        sel = select_id
        if sel is None:
            cur = self.selected_layer()
            sel = cur.id if cur else None
        sc = self.scene()
        sc.blockSignals(True)
        old = list(self.items.values())
        for it in old:
            if it.scene() is sc:
                sc.removeItem(it)
        self.items.clear()
        # 旧的码不要马上释放：Qt 可能还在处理和它们有关的事件（悬停、按键），
        # 立刻释放会导致闪退。等这一轮事件处理完再释放。
        self._graveyard.extend(old)
        if not self._grave_timer.isActive():
            self._grave_timer.start()
        if self.doc and self.ctx.image is not None:
            for i, L in enumerate(self.doc.layers):
                it = LayerItem(L, self.ctx)
                it.setZValue(i + 1)
                sc.addItem(it)
                self.items[L.id] = it
                if L.id == sel:
                    it.setSelected(True)
        sc.blockSignals(False)
        self.viewport().update()
        self.selectionChanged.emit(self.selected_layer())

    def update_layer(self, L: Layer):
        it = self.items.get(L.id)
        if it:
            it.sync()

    def selected_layer(self) -> Layer | None:
        for it in self.scene().selectedItems():
            if isinstance(it, LayerItem):
                return it.layer
        return None

    def select(self, layer_id: str | None):
        sc = self.scene()
        sc.blockSignals(True)
        sc.clearSelection()
        if layer_id and layer_id in self.items:
            self.items[layer_id].setSelected(True)
        sc.blockSignals(False)
        self.viewport().update()
        self.selectionChanged.emit(self.selected_layer())

    def _on_sel(self):
        self.selectionChanged.emit(self.selected_layer())

    def set_peek(self, on: bool):
        if self.ctx.hide_layers != on:
            self.ctx.hide_layers = on
            self.viewport().update()

    # ---- 缩放 ----
    def fit(self):
        self.fit_mode = True
        if self.ctx.image is None:
            return
        r = self.base.boundingRect()
        m = max(r.width(), r.height()) * 0.04
        self.fitInView(r.adjusted(-m, -m, m, m), Qt.AspectRatioMode.KeepAspectRatio)
        self._scale_changed()

    def zoom_to(self, factor: float):
        self.fit_mode = False
        self.setTransform(QTransform.fromScale(factor, factor))
        self.centerOn(self.base.boundingRect().center())
        self._scale_changed()

    def zoom_by(self, f: float):
        s = self.transform().m11()
        f = max(0.02 / s, min(f, 16 / s))
        self.fit_mode = False
        self.scale(f, f)
        self._scale_changed()

    def _scale_changed(self):
        self.ctx.view_scale = self.transform().m11() or 1.0
        for it in self.items.values():
            it.prepareGeometryChange()
            it.update()
        self.zoomChanged.emit(self.ctx.view_scale)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            self.fit()

    def wheelEvent(self, e):
        mods = e.modifiers()
        delta = e.angleDelta().y() or e.angleDelta().x()
        if not delta:
            return
        L = self.selected_layer()
        if L and (mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)):
            self.beginEdit.emit()
            if mods & Qt.KeyboardModifier.AltModifier:
                L.rot = max(-180.0, min(180.0, L.rot + (2 if delta > 0 else -2)))
            else:
                f = 1.05 if delta > 0 else 0.95
                L.w = max(4.0, L.w * f)
                L.h = max(4.0, L.h * f)
            self.update_layer(L)
            self.edited.emit()
            e.accept()
            return
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
        e.accept()

    # ---- 鼠标 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton or (
                e.button() == Qt.MouseButton.RightButton):
            self._pan = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        self.setFocus()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            self.fit_mode = False
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.viewport().unsetCursor()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.ctx.image is not None:
            item = self.itemAt(e.position().toPoint())
            if item is None or item is self.base:
                pt = self.mapToScene(e.position().toPoint())
                r = self.base.boundingRect()
                if r.contains(pt):
                    self.addRequested.emit(pt)
                    return
        super().mouseDoubleClickEvent(e)

    # ---- 键盘 ----
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Space:
            if not e.isAutoRepeat():
                self.set_peek(True)
            e.accept()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.handle_arrow(k, bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier), e.isAutoRepeat())
            e.accept()
            return
        if k == Qt.Key.Key_Escape:
            self.select(None)
            e.accept()
            return
        super().keyPressEvent(e)

    def handle_arrow(self, k, shift: bool, repeat: bool):
        """方向键：选中码时微调位置，没选中时切换图片。"""
        L = self.selected_layer()
        if L is not None and self.doc is not None and L in self.doc.layers:
            # 每次移动 1 个屏幕像素，按住 Shift 移动 10 个
            step = (10 if shift else 1) / max(0.02, self.ctx.view_scale)
            if not repeat:
                self.beginEdit.emit()
            if k == Qt.Key.Key_Left:
                L.cx -= step
            elif k == Qt.Key.Key_Right:
                L.cx += step
            elif k == Qt.Key.Key_Up:
                L.cy -= step
            elif k == Qt.Key.Key_Down:
                L.cy += step
            self.update_layer(L)
            self._nudge_timer.start()
            return
        if repeat:
            return  # 按住不放时不连续切图，避免一下子加载很多大图
        # 切图会重建画布，放到按键事件处理完之后再做，避免在事件处理中途释放对象而闪退
        d = -1 if k in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.navigate.emit(d))

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.set_peek(False)
            e.accept()
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        self.set_peek(False)
        super().focusOutEvent(e)

    # ---- 拖放 ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            e.acceptProposedAction()
