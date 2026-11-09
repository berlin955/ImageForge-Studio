"""把导入动画的几个瞬间画成一张预览图（检查效果用）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QApplication, QGraphicsScene, QStyleOptionGraphicsItem

app = QApplication([])
from maskforge.scanfx import ScanOverlay

W, H = 700, 700
src = QImage(W, H, QImage.Format.Format_RGB32)
src.fill(QColor("#ead9c8"))
p = QPainter(src)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QRadialGradient(QPointF(170, 330), 380)
g.setColorAt(0, QColor("#d9b8a6")); g.setColorAt(1, QColor("#3a3036"))
p.fillRect(QRectF(0, 0, 340, H), g)
cap = QPainterPath(); cap.addRoundedRect(QRectF(400, 210, 260, 400), 130, 130)
g2 = QRadialGradient(QPointF(530, 400), 260)
g2.setColorAt(0, QColor("#e2c1ad")); g2.setColorAt(1, QColor("#262228"))
p.fillPath(cap, g2)
p.setPen(QColor("#4a3428")); p.setBrush(QColor("#4a3428"))
p.drawRoundedRect(QRectF(410, 70, 240, 50), 25, 25)
p.end()

slots = [{"x": 0, "y": 0, "w": 340, "h": H, "shape": "rect", "radius": 0},
         {"x": 400, "y": 210, "w": 260, "h": 400, "shape": "rect", "radius": 0.5}]
texts = [{"x": 440, "y": 78, "w": 180, "h": 34}, {"x": 450, "y": 640, "w": 160, "h": 26}]


def path_of(s):
    pp = QPainterPath()
    r = QRectF(s["x"], s["y"], s["w"], s["h"])
    rad = s["radius"] * min(r.width(), r.height())
    pp.addRoundedRect(r, rad, rad) if rad else pp.addRect(r)
    return pp


def frame(setup):
    ov = ScanOverlay(QRectF(0, 0, W, H), "#8fa3ff", lambda: 1.0, path_of)
    ov.timer.stop()
    setup(ov)
    img = QImage(W, H, QImage.Format.Format_RGB32)
    q = QPainter(img)
    q.drawImage(0, 0, src)
    opt = QStyleOptionGraphicsItem()
    opt.exposedRect = QRectF(0, 0, W, H)
    ov.paint(q, opt)
    q.end()
    return img


now = time.monotonic()
shots = [
    frame(lambda o: setattr(o, "t0", now - 0.6)),
    frame(lambda o: setattr(o, "t0", now - 1.5)),
    frame(lambda o: (o.reveal(slots, texts), setattr(o, "reveal_t0", now - 0.8))),
    frame(lambda o: (o.reveal(slots, texts), setattr(o, "reveal_t0", now - 2.0))),
]
out = QImage(W * 2 + 10, H * 2 + 10, QImage.Format.Format_RGB32)
out.fill(QColor("#111"))
q = QPainter(out)
for i, im in enumerate(shots):
    q.drawImage((i % 2) * (W + 10), (i // 2) * (H + 10), im)
q.end()
out.scaled(out.width() // 2, out.height() // 2, Qt.AspectRatioMode.KeepAspectRatio,
           Qt.TransformationMode.SmoothTransformation).save(sys.argv[1] if len(sys.argv) > 1 else "scan_preview.png")
