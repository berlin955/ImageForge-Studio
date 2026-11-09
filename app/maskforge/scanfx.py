"""导入模板时的「扫描」动画：网点波纹 + 扫描光带，识别完成后照片框沿形状描出光边。"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QLabel, QStyleOptionGraphicsItem


class ScanOverlay(QGraphicsObject):
    """盖在图片上的动画层。scanning 阶段网点流动；reveal() 之后照片框、文字框依次亮起。"""

    DOT_PX = 13.0        # 网点在屏幕上的间距（像素）
    REVEAL_SEC = 1.6

    def __init__(self, rect: QRectF, accent: str, view_scale, path_of=None):
        super().__init__()
        self._rect = QRectF(rect)
        self.accent = QColor(accent)
        self.view_scale = view_scale          # 返回当前视图缩放的函数，网点按屏幕大小画
        self.path_of = path_of                # slot -> QPainterPath（场景坐标）
        self.t0 = time.monotonic()
        self.reveal_t0: float | None = None
        self.slots: list = []
        self.texts: list = []
        self.on_finished = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setZValue(50)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def boundingRect(self) -> QRectF:
        return self._rect

    # ------------------------------------------------------------------
    def reveal(self, slots: list, texts: list, on_finished=None):
        self.slots, self.texts = slots, texts
        self.on_finished = on_finished
        self.reveal_t0 = time.monotonic()

    def stop(self):
        self.timer.stop()

    def _tick(self):
        if self.reveal_t0 is not None:
            n = len(self.slots) + len(self.texts)
            total = self.REVEAL_SEC + 0.12 * n + 0.35
            if time.monotonic() - self.reveal_t0 > total:
                self.timer.stop()
                cb, self.on_finished = self.on_finished, None
                if cb:
                    cb()
                return
        self.update()

    # ------------------------------------------------------------------
    def paint(self, p: QPainter, opt: QStyleOptionGraphicsItem, widget=None):
        now = time.monotonic()
        t = now - self.t0
        fade = 1.0
        rp = 0.0
        if self.reveal_t0 is not None:
            rp = min(1.0, (now - self.reveal_t0) / self.REVEAL_SEC)
            fade = 1.0 - rp
        vis = opt.exposedRect.intersected(self._rect) if not opt.exposedRect.isEmpty() else self._rect
        k = max(1e-3, self.view_scale())
        sp = self.DOT_PX / k
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 暗一点的底，网点更显眼
        p.fillRect(vis, QColor(8, 10, 18, int(120 * fade + 25 * (1 - fade) * (1 - rp))))
        if fade > 0.01:
            self._dots(p, vis, sp, t, fade, k)
            self._band(p, vis, t, fade)
        if self.reveal_t0 is not None:
            self._outlines(p, now - self.reveal_t0, k)

    def _dots(self, p: QPainter, vis: QRectF, sp: float, t: float, fade: float, k: float):
        # 按亮度分档，每档一次 drawPoints，几千个点也不卡
        buckets: list[list[QPointF]] = [[] for _ in range(6)]
        x0 = math.floor(vis.left() / sp) * sp
        y0 = math.floor(vis.top() / sp) * sp
        nx = int(vis.width() / sp) + 2
        ny = int(vis.height() / sp) + 2
        for j in range(ny):
            y = y0 + j * sp
            gj = int(y / sp)
            for i in range(nx):
                x = x0 + i * sp
                gi = int(x / sp)
                # 斜向流动的波纹 + 每个点自己的闪烁
                w = math.sin((gi + gj) * 0.32 - t * 3.2) * 0.5 + 0.5
                h = (gi * 73856093 ^ gj * 19349663) & 1023
                tw = math.sin(t * 5.0 + h) * 0.5 + 0.5
                v = w * 0.7 + tw * 0.3
                buckets[min(5, int(v * 6))].append(QPointF(x + sp / 2, y + sp / 2))
        c = QColor(self.accent)
        for b, pts in enumerate(buckets):
            if not pts:
                continue
            a = (0.12 + 0.88 * (b / 5) ** 1.6) * fade
            c.setAlphaF(min(1.0, a))
            pen = QPen(c, 1.2 + b * 0.55)     # 越亮的点越大
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPoints(QPolygonF(pts))

    def _band(self, p: QPainter, vis: QRectF, t: float, fade: float):
        r = self._rect
        period = 2.4
        ph = (t % period) / period
        bh = max(r.height(), r.width()) * 0.16
        cy = r.top() - bh + ph * (r.height() + 2 * bh)
        g = QLinearGradient(0, cy - bh, 0, cy + bh * 0.15)
        c0 = QColor(self.accent)
        c0.setAlphaF(0.0)
        c1 = QColor(self.accent)
        c1.setAlphaF(0.32 * fade)
        g.setColorAt(0.0, c0)
        g.setColorAt(0.92, c1)
        g.setColorAt(1.0, c0)
        p.fillRect(QRectF(vis.left(), cy - bh, vis.width(), bh * 1.15).intersected(vis), g)
        line = QColor(255, 255, 255, int(200 * fade))
        pen = QPen(line, 1.6)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawLine(QPointF(vis.left(), cy), QPointF(vis.right(), cy))

    def _outlines(self, p: QPainter, dt: float, k: float):
        for i, s in enumerate(self.slots):
            prog = max(0.0, min(1.0, (dt - 0.25 - i * 0.15) / 0.75))
            if prog <= 0:
                continue
            path = self.path_of(s) if self.path_of else _rect_path(s)
            fill = QColor(self.accent)
            fill.setAlphaF(0.16 * prog)
            p.fillPath(path, fill)
            pts = _partial(path, prog)
            poly = QPolygonF(pts)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for wdt, a in ((11, 0.10), (6, 0.22), (2.4, 1.0)):
                c = QColor(self.accent) if wdt > 3 else QColor(255, 255, 255)
                c.setAlphaF(a)
                pen = QPen(c, wdt)
                pen.setCosmetic(True)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                if prog >= 1:
                    p.drawPath(path)          # 描完了直接画真实形状，角不会被折线切歪
                else:
                    p.drawPolyline(poly)
            if prog < 1 and pts:
                head = pts[-1]
                c = QColor(255, 255, 255, 230)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                rr = 5 / k
                p.drawEllipse(head, rr, rr)
        base = 0.25 + len(self.slots) * 0.15 + 0.4
        for j, tx in enumerate(self.texts):
            u = (dt - base - j * 0.06) / 0.5
            if u <= 0:
                continue
            a = math.sin(min(1.0, u) * math.pi) if u < 1 else 0.35
            c = QColor(self.accent)
            c.setAlphaF(0.85 * a)
            pen = QPen(c, 1.6)
            pen.setCosmetic(True)
            p.setPen(pen)
            c2 = QColor(self.accent)
            c2.setAlphaF(0.18 * a)
            p.setBrush(c2)
            m = 4 / k
            p.drawRoundedRect(QRectF(tx["x"] - m, tx["y"] - m, tx["w"] + 2 * m, tx["h"] + 2 * m), 3 / k, 3 / k)


def _rect_path(s: dict) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(s["x"], s["y"], s["w"], s["h"]))
    return path


def _partial(path: QPainterPath, prog: float, steps: int = 900) -> list:
    """沿形状取点画「描边中」的那一段。按真实长度均匀取点（pointAtPercent 本来就是按长度），
    点要够密，圆角处才不会被连成折线、看起来歪掉。"""
    n = max(2, int(steps * prog))
    return [path.pointAtPercent(min(1.0, prog * i / (n - 1))) for i in range(n)]


class ScanStatus(QLabel):
    """画布底部居中的状态胶囊：正在识别模特… / 找到 3 个图片位"""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._dots = 0
        self._base = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.hide()

    def style_for(self, accent: str):
        self.setStyleSheet(
            "QLabel{background:rgba(10,12,20,0.82);color:#ffffff;border:1px solid %s;"
            "border-radius:16px;padding:7px 18px;font-size:13px;}" % accent)

    def show_text(self, text: str, animate: bool = True):
        self._base = text
        self._dots = 0
        self.setText(text + ("…" if animate else ""))
        if animate:
            self.timer.start(420)
        else:
            self.timer.stop()
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.setText(self._base + "." * self._dots + " " * (3 - self._dots))
        self.adjustSize()
        self._place()

    def _place(self):
        vw = self.view.viewport()
        self.move((self.view.width() - self.width()) // 2, vw.height() - self.height() - 22)

    def finish(self):
        self.timer.stop()
        self.hide()
