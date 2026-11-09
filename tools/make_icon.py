"""生成应用图标 assets/icon.png 和 assets/icon.ico（需要 PySide6）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter

app = QGuiApplication(sys.argv)
root = Path(__file__).resolve().parents[1] / "assets"
root.mkdir(exist_ok=True)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.scale(s, s)
    g = QLinearGradient(0, 0, 256, 256)
    g.setColorAt(0, QColor("#232a3d"))
    g.setColorAt(1, QColor("#121520"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
    cells = [(0, 0, .35), (1, 0, .7), (2, 0, .45), (0, 1, .7), (1, 1, 1.0), (2, 1, .6),
             (0, 2, .45), (1, 2, .6), (2, 2, .3)]
    for x, y, a in cells:
        c = QColor("#8fa3ff")
        c.setAlphaF(a)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(52 + x * 54, 52 + y * 54, 46, 46), 10, 10)
    p.end()
    return img


draw(256).save(str(root / "icon.png"))
ok = draw(256).save(str(root / "icon.ico"))
print("icon.png ok, icon.ico", "ok" if ok else "FAILED")
if not ok:
    sys.exit(1)
