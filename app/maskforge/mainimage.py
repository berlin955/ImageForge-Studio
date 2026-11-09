"""批量主图：正方形主图（800/1000/1440）、竖格拼图（2/3/4 格）、左上角品牌角标。"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QProgressDialog, QSpinBox, QVBoxLayout, QWidget)

from . import theme
from .config import data_dir
from .exporter import FORMATS, _render, save_image, unique_path
from .pages import page_header
from .widgets import Card, ColorButton, Segmented, SliderRow, button, muted, row, scroll_page

SIZES = [(800, "800"), (1000, "1000"), (1440, "1440"), (0, "自定义")]
CORNERS = [("tl", "左上"), ("tr", "右上"), ("bl", "左下"), ("br", "右下")]
PROXY = 1400  # 预览用的图片长边


# ================================================================ 计算
def crop_rect_aspect(doc, w: int, h: int, aspect: float, mode: str, ov: dict | None) -> QRectF:
    """在原图上取一块指定宽高比的区域。ov 是手动调整（按比例记录的中心点和缩放）。"""
    ov = ov or {}
    if w / h > aspect:
        bh, bw = h, h * aspect
    else:
        bw, bh = w, w / aspect
    sc = max(0.15, min(1.0, float(ov.get("scale", 1.0))))
    bw, bh = bw * sc, bh * sc
    if "cx" in ov:
        cx, cy = ov["cx"] * w, ov["cy"] * h
    elif mode == "smart" and doc.subject and doc.w:
        k = w / doc.w
        x1, y1, x2, y2 = [v * k for v in doc.subject]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if doc.face and (y2 - y1) > bh * 0.9:
            cy = doc.face[1] * k - bh * 0.06 + bh / 2   # 人比框高：让脸靠上
    else:
        cx, cy = w / 2, h / 2
    x = min(max(cx - bw / 2, 0), w - bw)
    y = min(max(cy - bh / 2, 0), h - bh)
    return QRectF(x, y, bw, bh)


def proxy_of(doc):
    """预览用的中等分辨率图（带码的图层按比例缩放）。"""
    px = getattr(doc, "_proxy", None)
    if px is not None:
        return px
    img = doc.image()
    if img is None:
        return None
    k = min(1.0, PROXY / max(img.width(), img.height()))
    if k < 1.0:
        img = img.scaled(round(img.width() * k), round(img.height() * k),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    doc._proxy = (img, k)
    return doc._proxy


def doc_icon(doc, masked: bool, fallback):
    ic = doc.icon if masked else (doc.icon_plain or doc.icon)
    return ic or fallback


def _scaled_doc(doc, k: float):
    if k == 1.0:
        return doc
    return SimpleNamespace(layers=[L.clone(cx=L.cx * k, cy=L.cy * k, w=L.w * k, h=L.h * k) for L in doc.layers])


_logo_cache: dict[str, QImage] = {}


def logo_image(path: str) -> QImage | None:
    if not path:
        return None
    img = _logo_cache.get(path)
    if img is None:
        img = QImage(path)
        if img.isNull():
            return None
        _logo_cache[path] = img
    return img


def compose(mc: dict, items: list, logo_ov, library, S: int, preview: bool):
    """
    生成一张主图。items: [(doc, ov_dict)]，一张时是单图，多张时是竖格拼图。
    返回 (QImage, 每格信息 [(QRectF 输出位置, doc, ov_dict, QRectF 原图取景, 原图宽, 原图高)], 角标位置 QRectF|None)
    """
    n = len(items)
    collage = n > 1
    mode = mc.get("mode", "smart")
    out = QImage(S, S, QImage.Format.Format_RGB32)
    bg = mc.get("bg", "#ffffff") if collage else mc.get("pad_color", "#ffffff")
    out.fill(QColor(bg))
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    cells = []
    if collage:
        g = float(mc.get("gap", 8)) * S / 800
        cw = (S - g * (n + 1)) / n
        ch = S - 2 * g
        rects = [QRectF(g + i * (cw + g), g, cw, ch) for i in range(n)]
    else:
        rects = [QRectF(0, 0, S, S)]
    for rect, (doc, ov) in zip(rects, items):
        if preview:
            px = proxy_of(doc)
            if px is None:
                continue
            img, k = px
        else:
            img, k = doc.image(), 1.0
            if img is None:
                continue
        w, h = img.width(), img.height()
        fake = _scaled_doc(doc, k) if mc.get("use_mask", True) else SimpleNamespace(layers=[])
        tw, th = max(1, round(rect.width())), max(1, round(rect.height()))
        if not collage and mode == "pad":
            kk = min(tw / w, th / h)
            dw, dh = w * kk, h * kk
            target = QRectF((tw - dw) / 2, (th - dh) / 2, dw, dh)
            cell = _render(fake, img, library, tw, th, QRectF(0, 0, w, h), target, "jpg",
                           mc.get("pad_color", "#ffffff"))
            src = QRectF(0, 0, w, h)
        else:
            src = crop_rect_aspect(doc, w, h, tw / th, mode, ov)
            cell = _render(fake, img, library, tw, th, src, QRectF(0, 0, tw, th), "jpg")
        p.drawImage(rect.topLeft(), cell)
        cells.append((rect, doc, ov, src, w, h))
    logo_rect = None
    lc = mc.get("logo", {})
    if lc.get("enabled"):
        li = logo_image(lc.get("file", ""))
        if li is not None:
            lw = S * float(lc.get("size", 0.2))
            lh = lw * li.height() / max(1, li.width())
            m = S * float(lc.get("margin", 0.03))
            if logo_ov:
                x, y = logo_ov[0] * S, logo_ov[1] * S
            else:
                corner = lc.get("corner", "tl")
                x = m if corner in ("tl", "bl") else S - m - lw
                y = m if corner in ("tl", "tr") else S - m - lh
            x = min(max(x, 0), S - lw)
            y = min(max(y, 0), S - lh)
            logo_rect = QRectF(x, y, lw, lh)
            p.setOpacity(float(lc.get("opacity", 1.0)))
            p.drawImage(logo_rect, li)
            p.setOpacity(1.0)
    p.end()
    return out, cells, logo_rect


# ================================================================ 预览
class MainPreview(QWidget):
    """显示一张主图，拖动调整取景、滚轮缩放、拖动角标，双击恢复自动。"""
    changed = Signal()

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.img: QImage | None = None
        self.cells = []
        self.logo_rect: QRectF | None = None
        self.S = 800          # 预览画的尺寸
        self.real = 800       # 实际导出的尺寸
        self._drag = None
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumSize(360, 360)

    def set_result(self, img, cells, logo_rect, S, real=None):
        self.img, self.cells, self.logo_rect, self.S = img, cells, logo_rect, S
        self.real = real or S
        self.update()

    def _frame(self) -> QRectF:
        m, bottom = 20, 46   # 下方留出两行说明文字的位置
        side = max(10, min(self.width() - 2 * m, self.height() - m - bottom))
        return QRectF((self.width() - side) / 2, m, side, side)

    def _to_out(self, pos) -> QPointF:
        f = self._frame()
        k = self.S / f.width()
        return QPointF((pos.x() - f.x()) * k, (pos.y() - f.y()) * k)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        pal = theme.current()
        p.fillRect(self.rect(), QColor(pal["stage"]))
        f = self._frame()
        if self.img is None:
            p.setPen(QColor(pal["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "导入图片后，这里显示主图效果")
            return
        p.drawImage(f, self.img)
        k = f.width() / self.S
        pen = QPen(QColor(pal["accent"]), 1.5)
        pen.setCosmetic(True)
        if 0 <= self._hover < len(self.cells):
            r = self.cells[self._hover][0]
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(f.x() + r.x() * k, f.y() + r.y() * k, r.width() * k, r.height() * k).adjusted(1, 1, -1, -1))
        if self.logo_rect is not None:
            r = self.logo_rect
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(QRectF(f.x() + r.x() * k, f.y() + r.y() * k, r.width() * k, r.height() * k))
        p.setPen(QColor(pal["fg"]))
        p.drawText(QRectF(0, f.bottom() + 4, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   f"导出尺寸 {self.real}×{self.real}")
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(0, f.bottom() + 22, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   "拖动调位置 · 滚轮缩放 · 双击复原")

    def _cell_at(self, o: QPointF) -> int:
        for i, c in enumerate(self.cells):
            if c[0].contains(o):
                return i
        return -1

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.img is None:
            return
        o = self._to_out(e.position())
        if self.logo_rect is not None and self.logo_rect.contains(o):
            self._drag = {"kind": "logo", "start": o, "x": self.logo_rect.x(), "y": self.logo_rect.y()}
            return
        i = self._cell_at(o)
        if i < 0:
            return
        rect, doc, ov, src, w, h = self.cells[i]
        self._drag = {"kind": "cell", "i": i, "start": o, "cx": src.center().x() / w,
                      "cy": src.center().y() / h, "k": src.width() / rect.width(), "w": w, "h": h}

    def mouseMoveEvent(self, e):
        o = self._to_out(e.position())
        d = self._drag
        if d is None:
            hv = self._cell_at(o) if len(self.cells) > 1 else -1
            if hv != self._hover:
                self._hover = hv
                self.update()
            on_logo = self.logo_rect is not None and self.logo_rect.contains(o)
            self.setCursor(Qt.CursorShape.SizeAllCursor if (on_logo or self._cell_at(o) >= 0)
                           else Qt.CursorShape.ArrowCursor)
            return
        dx, dy = o.x() - d["start"].x(), o.y() - d["start"].y()
        if d["kind"] == "logo":
            self.page.set_logo_pos((d["x"] + dx) / self.S, (d["y"] + dy) / self.S)
        else:
            rect, doc, ov, src, w, h = self.cells[d["i"]]
            ov["cx"] = d["cx"] - dx * d["k"] / d["w"]
            ov["cy"] = d["cy"] - dy * d["k"] / d["h"]
            ov.setdefault("scale", 1.0)
            self.page.schedule_render()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.page.schedule_render()

    def wheelEvent(self, e):
        if self.img is None:
            return
        o = self._to_out(e.position())
        i = self._cell_at(o)
        if i < 0:
            return
        rect, doc, ov, src, w, h = self.cells[i]
        delta = e.angleDelta().y() or e.angleDelta().x()
        if "cx" not in ov:
            ov["cx"], ov["cy"] = src.center().x() / w, src.center().y() / h
        sc = float(ov.get("scale", 1.0)) * (0.92 if delta > 0 else 1 / 0.92)
        ov["scale"] = max(0.15, min(1.0, sc))
        self.page.schedule_render()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        o = self._to_out(e.position())
        if self.logo_rect is not None and self.logo_rect.contains(o):
            self.page.set_logo_pos(None)
            return
        i = self._cell_at(o)
        if i >= 0:
            self.cells[i][2].clear()
            self.page.schedule_render()

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self.update()


# ================================================================ 页面
class MainImagePage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cfg = mw.cfg
        self.mc = self.cfg["mainimg"]
        self.groups: list[dict] = []     # 拼图分组 {"id", "docs": [doc_id], "crops": {doc_id: ov}, "logo": pos}
        self.cur_doc_id: str | None = None
        self.cur_group: str | None = None
        self._loading = False
        self._film_ids: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self.render_now)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, th = page_header("批量主图", "正方形主图智能裁切；需要时可以竖格拼图、加品牌角标")
        self.b_export_all = button("导出全部主图", "Primary")
        self.b_export_all.clicked.connect(self.export_all)
        th.addWidget(self.b_export_all)
        v.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(360)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self._build_settings())
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
        self.b_prev = button("‹", "Tool")
        self.b_next = button("›", "Tool")
        self.b_prev.setFixedWidth(36)
        self.b_next.setFixedWidth(36)
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:700")
        b_reset = button("恢复自动位置", "Tool", "取景和角标都恢复成自动")
        b_reset.clicked.connect(self.reset_current)
        self.b_one = button("只导出这一张", "Tool")
        self.b_one.clicked.connect(self.export_current)
        for w in (self.b_prev, self.b_next, self.title):
            tbh.addWidget(w)
        tbh.addStretch(1)
        tbh.addWidget(b_reset)
        tbh.addWidget(self.b_one)
        wv.addWidget(tb)
        self.preview = MainPreview(self)
        wv.addWidget(self.preview, 1)

        fb = QFrame()
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
        self.film.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.film.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.film.itemClicked.connect(self._film_clicked)
        fv.addWidget(self.film)
        wv.addWidget(fb)
        body.addWidget(work, 1)
        v.addLayout(body, 1)
        self.load_settings()

    # ---------------------------------------------------------------- 设置面板
    def _build_settings(self):
        c0 = Card("用哪个版本的图")
        self.mask_seg = Segmented([("1", "打码后的图"), ("0", "原图（不打码）")])
        self.mask_seg.changed.connect(self._mask_changed)
        c0.add(self.mask_seg)
        c1 = Card("主图尺寸")
        self.size_seg = Segmented([(str(k), t) for k, t in SIZES])
        self.size_seg.changed.connect(self._size_changed)
        c1.add(self.size_seg)
        self.custom = QSpinBox()
        self.custom.setRange(200, 5000)
        self.custom.setSuffix(" px")
        self.custom.valueChanged.connect(lambda v: self._set("custom", v))
        c1.add(self.custom)

        c2 = Card("裁切方式")
        self.mode_seg = Segmented([("smart", "智能裁切"), ("center", "居中裁切"), ("pad", "留白不裁")])
        self.mode_seg.changed.connect(self._mode_changed)
        c2.add(self.mode_seg)
        self.pad_color = ColorButton("#ffffff")
        self.pad_color.colorChanged.connect(lambda c: self._set("pad_color", c))
        self.pad_row = QWidget()
        lab = QLabel("留白颜色")
        lab.setObjectName("Muted")
        self.pad_row.setLayout(row(lab, self.pad_color))
        c2.add(self.pad_row)
        self.mode_hint = muted("")
        c2.add(self.mode_hint)

        c3 = Card("拼图")
        self.layout_seg = Segmented([("single", "单张主图"), ("collage", "竖格拼图")])
        self.layout_seg.changed.connect(self._layout_changed)
        c3.add(self.layout_seg)
        self.collage_box = QWidget()
        cb = QVBoxLayout(self.collage_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(8)
        self.cells_seg = Segmented([("2", "2 格"), ("3", "3 格"), ("4", "4 格")])
        self.cells_seg.changed.connect(self._cells_changed)
        cb.addWidget(self.cells_seg)
        cb.addWidget(muted("2 格适合正面 + 背面，3、4 格适合多种颜色。"))
        self.gap = SliderRow("间距", 0, 40, 0, " px")
        self.gap.valueChanged.connect(lambda v: self._set("gap", int(v)))
        cb.addWidget(self.gap)
        self.bg = ColorButton("#ffffff")
        self.bg.colorChanged.connect(lambda c: self._set("bg", c))
        lab2 = QLabel("背景颜色")
        lab2.setObjectName("Muted")
        cb.addLayout(row(lab2, self.bg))
        b_auto = button("按顺序自动分组")
        b_auto.clicked.connect(self.auto_group)
        b_sel = button("用选中的图新建一组")
        b_sel.clicked.connect(self.group_from_selection)
        cb.addLayout(row(b_auto, b_sel))
        self.group_list = QListWidget()
        self.group_list.setObjectName("Layers")
        self.group_list.setFixedHeight(130)
        self.group_list.itemClicked.connect(self._group_clicked)
        cb.addWidget(self.group_list)
        b_del = button("删除这一组", "Ghost")
        b_del.clicked.connect(self.delete_group)
        cb.addWidget(b_del)
        cb.addWidget(muted("在底部缩略图里按住 Ctrl 选几张，再点「用选中的图新建一组」，格子数会跟着张数走。"))
        c3.add(self.collage_box)

        c4 = Card("品牌角标")
        self.logo_on = QCheckBox("在主图上加 Logo")
        self.logo_on.toggled.connect(lambda on: self._set_logo("enabled", on))
        c4.add(self.logo_on)
        self.logo_pv = QLabel()
        self.logo_pv.setFixedSize(64, 40)
        self.logo_pv.setObjectName("StickerPreview")
        self.logo_pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_logo = button("选择 Logo…")
        b_logo.clicked.connect(self.choose_logo)
        c4.add(row(self.logo_pv, b_logo, None))
        self.corner = Segmented(CORNERS)
        self.corner.changed.connect(self._corner_changed)
        c4.add(self.corner)
        self.l_size = SliderRow("大小", 0.05, 0.45, 0, "%", factor=100)
        self.l_size.valueChanged.connect(lambda v: self._set_logo("size", round(v, 3)))
        self.l_margin = SliderRow("边距", 0.0, 0.1, 1, "%", factor=100)
        self.l_margin.valueChanged.connect(lambda v: self._set_logo("margin", round(v, 4)))
        self.l_op = SliderRow("不透明", 0.1, 1.0, 0, "%", factor=100)
        self.l_op.valueChanged.connect(lambda v: self._set_logo("opacity", round(v, 3)))
        for w in (self.l_size, self.l_margin, self.l_op):
            c4.add(w)
        c4.add(muted("某一张位置不合适，在右边直接拖动 Logo，只影响这一张；双击 Logo 恢复。"))

        c5 = Card("保存")
        self.fmt = Segmented([("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")])
        self.fmt.changed.connect(lambda k: self._set("format", k))
        c5.add(self.fmt)
        self.out_lbl = muted("")
        b_out = button("更改…")
        b_out.clicked.connect(self._choose_out)
        c5.add(row(self.out_lbl, None, b_out))

        area, _ = scroll_page(c0, c1, c2, c3, c4, c5)
        return area

    def _mask_changed(self, k):
        self._set("use_mask", k == "1")
        self._film_ids = []      # 缩略图换成对应版本
        self.refresh()

    def load_settings(self):
        mc = self.mc
        self._loading = True
        size = int(mc.get("size", 800))
        self.size_seg.set_value(str(size) if size in (800, 1000, 1440) else "0")
        self.custom.setValue(int(mc.get("custom", 1200)))
        self.mode_seg.set_value(mc.get("mode", "smart"))
        self.mask_seg.set_value("1" if mc.get("use_mask", True) else "0")
        self.pad_color.set_color(mc.get("pad_color", "#ffffff"))
        self.layout_seg.set_value(mc.get("layout", "single"))
        self.cells_seg.set_value(str(mc.get("cells", 2)))
        self.gap.set_value(mc.get("gap", 8))
        self.bg.set_color(mc.get("bg", "#ffffff"))
        lc = mc["logo"]
        self.logo_on.setChecked(bool(lc.get("enabled")))
        self.corner.set_value(lc.get("corner", "tl"))
        self.l_size.set_value(lc.get("size", 0.2))
        self.l_margin.set_value(lc.get("margin", 0.03))
        self.l_op.set_value(lc.get("opacity", 1.0))
        self.fmt.set_value(mc.get("format", "jpg"))
        self._loading = False
        self._update_controls()

    def _update_controls(self):
        mc = self.mc
        size = int(mc.get("size", 800))
        self.custom.setVisible(size not in (800, 1000, 1440))
        collage = mc.get("layout") == "collage"
        self.collage_box.setVisible(collage)
        self.pad_row.setVisible(mc.get("mode") == "pad" and not collage)
        missing = sum(1 for d in self.mw.docs if d.subject is None and not d.error)
        hints = {"smart": "自动识别人物，让模特在主图中间、脸靠上。",
                 "center": "从图片正中间取正方形。",
                 "pad": "整张图放进正方形，两边留白，不裁掉任何部分（拼图时不适用）。"}
        txt = hints.get(mc.get("mode"), "")
        if mc.get("mode") == "smart" and missing:
            txt += f"\n还有 {missing} 张没识别人物位置，正在后台识别…" if self.mw.busy else f"\n还有 {missing} 张没识别人物位置。"
        self.mode_hint.setText(txt)
        lp = mc["logo"].get("file", "")
        li = logo_image(lp)
        if li is not None:
            self.logo_pv.setPixmap(QPixmap.fromImage(li).scaled(60, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                                                Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_pv.setPixmap(QPixmap())
            self.logo_pv.setText("无")
        out = self.cfg["export"].get("dir") or ""
        self.out_lbl.setText(f"保存到：{out}\\{mc.get('folder', '主图')}" if out else "保存到：还没有选择文件夹")
        n = len(self.targets())
        self.b_export_all.setText(f"导出全部主图（{n} 张）" if n else "导出全部主图")
        self.b_export_all.setEnabled(n > 0 and not self.mw.busy)

    def _set(self, key, v):
        if self._loading:
            return
        self.mc[key] = v
        self.cfg.save()
        self._update_controls()
        self.schedule_render()

    def _set_logo(self, key, v):
        if self._loading:
            return
        self.mc["logo"][key] = v
        self.cfg.save()
        self._update_controls()
        self.schedule_render()

    def _size_changed(self, k):
        self._set("size", int(k) if k != "0" else int(self.custom.value()))

    def _mode_changed(self, k):
        self._set("mode", k)
        if k == "smart":
            self.ensure_subjects()

    def _layout_changed(self, k):
        self._set("layout", k)
        if k == "collage" and not self.groups:
            self.auto_group()
        self.refresh()

    def _cells_changed(self, k):
        self._set("cells", int(k))

    def _corner_changed(self, k):
        self._set_logo("corner", k)
        # 换了角，之前手动拖过的位置作废
        for d in self.mw.docs:
            d.logo_pos = None
        for g in self.groups:
            g["logo"] = None
        self.schedule_render()

    def _choose_out(self):
        if self.mw.choose_out_dir():
            self._update_controls()

    def choose_logo(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择 Logo（透明背景的 PNG 最好）", self.cfg["last_dir"],
                                           "图片 (*.png *.webp *.jpg *.jpeg)")
        if not f:
            return
        folder = data_dir() / "logos"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / Path(f).name
        try:
            if Path(f).resolve() != dest.resolve():
                shutil.copy(f, dest)
        except Exception as e:
            QMessageBox.warning(self, "无法使用这个 Logo", str(e))
            return
        if logo_image(str(dest)) is None:
            QMessageBox.warning(self, "无法使用这个 Logo", "读取不了这张图片。")
            return
        _logo_cache.pop(str(dest), None)
        self.mc["logo"]["file"] = str(dest)
        self.mc["logo"]["enabled"] = True
        self.cfg.save()
        self.load_settings()
        self.schedule_render()

    # ---------------------------------------------------------------- 数据
    def size(self) -> int:
        s = int(self.mc.get("size", 800))
        return s if s > 0 else int(self.mc.get("custom", 1200))

    def collage(self) -> bool:
        return self.mc.get("layout") == "collage"

    def doc(self, did):
        return self.mw.doc_by_id(did)

    def targets(self) -> list:
        if self.collage():
            return [g for g in self.groups if self._group_docs(g)]
        return [d for d in self.mw.docs if not d.error]

    def _group_docs(self, g) -> list:
        return [d for d in (self.doc(i) for i in g["docs"]) if d is not None and not d.error]

    def _items_for_doc(self, d):
        if d.crop is None:
            d.crop = {}
        return [(d, d.crop)], d.logo_pos

    def _items_for_group(self, g):
        docs = self._group_docs(g)
        return [(d, g["crops"].setdefault(d.id, {})) for d in docs], g.get("logo")

    def forget(self, ids: set):
        for g in self.groups:
            g["docs"] = [i for i in g["docs"] if i not in ids]
        self.groups = [g for g in self.groups if g["docs"]]
        self.refresh()

    def auto_group(self):
        n = int(self.mc.get("cells", 2))
        docs = [d for d in self.mw.docs if not d.error]
        self.groups = [{"id": uuid.uuid4().hex[:8], "docs": [d.id for d in docs[i:i + n]], "crops": {}, "logo": None}
                       for i in range(0, len(docs), n) if len(docs[i:i + n]) >= 2]
        self.cur_group = self.groups[0]["id"] if self.groups else None
        self.refresh()

    def group_from_selection(self):
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in self.film.selectedItems()]
        order = [d.id for d in self.mw.docs]
        ids.sort(key=order.index)
        if not 2 <= len(ids) <= 4:
            QMessageBox.information(self, "拼图", "请在底部缩略图里按住 Ctrl 选 2 到 4 张图片。")
            return
        g = {"id": uuid.uuid4().hex[:8], "docs": ids, "crops": {}, "logo": None}
        self.groups.append(g)
        self.cur_group = g["id"]
        self.refresh()

    def delete_group(self):
        self.groups = [g for g in self.groups if g["id"] != self.cur_group]
        self.cur_group = self.groups[0]["id"] if self.groups else None
        self.refresh()

    def set_logo_pos(self, pos):
        if self.collage():
            g = self._current_group()
            if g:
                g["logo"] = pos
        else:
            d = self.doc(self.cur_doc_id)
            if d:
                d.logo_pos = pos
        self.schedule_render()

    def _current_group(self):
        for g in self.groups:
            if g["id"] == self.cur_group:
                return g
        return None

    def reset_current(self):
        if self.collage():
            g = self._current_group()
            if g:
                g["crops"] = {}
                g["logo"] = None
        else:
            d = self.doc(self.cur_doc_id)
            if d:
                d.crop = {}
                d.logo_pos = None
        self.schedule_render()

    def step(self, delta: int):
        if self.collage():
            ids = [g["id"] for g in self.groups]
            if self.cur_group in ids:
                i = max(0, min(len(ids) - 1, ids.index(self.cur_group) + delta))
                self.cur_group = ids[i]
        else:
            ids = [d.id for d in self.mw.docs]
            if self.cur_doc_id in ids:
                i = max(0, min(len(ids) - 1, ids.index(self.cur_doc_id) + delta))
                self.cur_doc_id = ids[i]
        self.refresh()

    # ---------------------------------------------------------------- 识别人物位置
    def ensure_subjects(self):
        if self.mc.get("mode") != "smart" or self.mw.busy:
            return
        if any(d.subject is None and not d.error and not d.detected for d in self.mw.docs):
            self.mw.analyze_subjects(then=self.refresh)
            self._update_controls()

    # ---------------------------------------------------------------- 显示
    def on_show(self):
        self.ensure_subjects()
        self.refresh()

    def refresh(self):
        docs = self.mw.docs
        ids = [d.id for d in docs]
        if self.cur_doc_id not in ids:
            self.cur_doc_id = ids[0] if ids else None
        self.groups = [g for g in self.groups if any(i in ids for i in g["docs"])]
        if self.collage() and self.cur_group not in [g["id"] for g in self.groups]:
            self.cur_group = self.groups[0]["id"] if self.groups else None
        if self._film_ids != ids:
            self.film.clear()
            for d in docs:
                it = QListWidgetItem(doc_icon(d, self.mc.get("use_mask", True), self.mw._placeholder), "")
                it.setData(Qt.ItemDataRole.UserRole, d.id)
                it.setToolTip(d.name)
                self.film.addItem(it)
            self._film_ids = ids
        self.group_list.clear()
        for i, g in enumerate(self.groups):
            names = "、".join(d.name[:10] for d in self._group_docs(g))
            it = QListWidgetItem(f"第 {i + 1} 组（{len(g['docs'])} 格）  {names}")
            it.setData(Qt.ItemDataRole.UserRole, g["id"])
            self.group_list.addItem(it)
            if g["id"] == self.cur_group:
                it.setSelected(True)
        if self.collage():
            self.film_hint.setText("按住 Ctrl 点选几张图，可以新建一组拼图" if docs else "")
            g = self._current_group()
            idx = [g["id"] for g in self.groups].index(self.cur_group) if g else -1
            self.title.setText(f"拼图 第 {idx + 1}/{len(self.groups)} 组" if g else "还没有拼图分组")
        else:
            self.film_hint.setText("点缩略图切换；拖动右边的预览调整取景" if docs else "")
            d = self.doc(self.cur_doc_id)
            self.title.setText(f"{ids.index(d.id) + 1}/{len(ids)}　{d.name}" if d else "")
            if d:
                for i in range(self.film.count()):
                    it = self.film.item(i)
                    if it.data(Qt.ItemDataRole.UserRole) == d.id and not it.isSelected():
                        self.film.setCurrentItem(it)
        self._update_controls()
        self.render_now()

    def update_icon(self, d):
        for i in range(self.film.count()):
            it = self.film.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == d.id and d.icon is not None:
                it.setIcon(doc_icon(d, self.mc.get("use_mask", True), self.mw._placeholder))
        if d.id == self.cur_doc_id or any(d.id in g["docs"] for g in self.groups if g["id"] == self.cur_group):
            self.schedule_render()

    def _film_clicked(self, it):
        did = it.data(Qt.ItemDataRole.UserRole)
        if self.collage():
            for g in self.groups:
                if did in g["docs"]:
                    if QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier:
                        self.cur_group = g["id"]
                        self.refresh()
                    return
            return
        self.cur_doc_id = did
        self.refresh()

    def _group_clicked(self, it):
        self.cur_group = it.data(Qt.ItemDataRole.UserRole)
        self.refresh()

    def schedule_render(self):
        self._timer.start()

    def render_now(self):
        if not self.isVisible() and not getattr(self, "_force", False):
            return
        S = self.size()
        PS = min(S, 900)
        if self.collage():
            g = self._current_group()
            if not g:
                self.preview.set_result(None, [], None, S)
                return
            items, logo = self._items_for_group(g)
        else:
            d = self.doc(self.cur_doc_id)
            if not d:
                self.preview.set_result(None, [], None, S)
                return
            items, logo = self._items_for_doc(d)
        if not items:
            self.preview.set_result(None, [], None, S)
            return
        img, cells, lr = compose(self.mc, items, logo, self.mw.library, PS, preview=True)
        self.preview.set_result(img, cells, lr, PS, S)

    # ---------------------------------------------------------------- 导出
    def _out_dir(self) -> Path | None:
        root = self.mw._ensure_out_dir()
        if root is None:
            return None
        p = root / self.mc.get("folder", "主图")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _name(self, stem: str) -> str:
        ext = FORMATS.get(self.mc.get("format", "jpg"), FORMATS["jpg"])[0]
        return f"{stem}{self.mc.get('suffix', '_主图')}.{ext}"

    def export_current(self):
        if self.collage():
            g = self._current_group()
            self._export([g] if g else [])
        else:
            d = self.doc(self.cur_doc_id)
            self._export([d] if d else [])

    def export_all(self):
        self._export(self.targets())

    def _export(self, targets: list) -> int:
        if not targets or self.mw.busy:
            return 0
        out = self._out_dir()
        if out is None:
            return 0
        S = self.size()
        ex = {"format": self.mc.get("format", "jpg"), "quality": int(self.cfg["export"].get("quality", 92))}
        dlg = QProgressDialog("正在导出主图…", "取消", 0, len(targets), self)
        dlg.setWindowTitle("导出主图")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        taken: set = set()
        ok, errors = 0, []
        self.mw.set_busy(True)
        try:
            for i, t in enumerate(targets):
                if dlg.wasCanceled():
                    break
                dlg.setValue(i)
                QApplication.processEvents()
                if isinstance(t, dict):
                    items, logo = self._items_for_group(t)
                    gi = self.groups.index(t) + 1 if t in self.groups else i + 1
                    stem = f"拼图{gi:02d}_" + "+".join(d.path.stem[:12] for d, _ in items)
                    label = f"拼图 {gi}"
                else:
                    items, logo = self._items_for_doc(t)
                    stem, label = t.path.stem, t.name
                dlg.setLabelText(f"正在导出 {i + 1}/{len(targets)}：{label}")
                try:
                    img, _c, _l = compose(self.mc, items, logo, self.mw.library, S, preview=False)
                    path = unique_path(out, self._name(stem), bool(self.cfg["export"].get("overwrite")), taken)
                    taken.add(str(path).lower())
                    save_image(img, path, ex)
                    ok += 1
                except Exception as e:
                    errors.append(f"{label}：{e}")
            dlg.setValue(len(targets))
        finally:
            dlg.close()
            self.mw.set_busy(False)
        if errors:
            QMessageBox.warning(self, "导出完成", f"已导出 {ok} 张主图到：\n{out}\n\n有 {len(errors)} 张没有成功：\n"
                                + "\n".join(errors[:8]))
        else:
            self.mw.status.showMessage(f"已导出 {ok} 张主图到 {out}", 10000)
        if ok and self.cfg["export"].get("open_after", True):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return ok
