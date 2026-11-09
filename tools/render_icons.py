"""把功能栏图标画成一张预览图（各主题），检查设计用：python tools/render_icons.py 输出.png"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from maskforge import theme
from maskforge.icons import NAMES, make_icon

LABELS = {"assets": "素材", "mask": "智能打码", "main": "批量主图", "spec": "智能规格", "detail": "智能详情",
          "watermark": "批量水印", "templates": "模板库", "theme": "主题", "settings": "设置"}
cell, rows = 96, len(theme.THEME_ORDER)
img = QImage(cell * len(NAMES), cell * rows * 2, QImage.Format.Format_ARGB32)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
for r, key in enumerate(theme.THEME_ORDER):
    pal = theme.PALETTES[key]
    for half in (0, 1):
        y0 = (r * 2 + half) * cell
        p.fillRect(0, y0, img.width(), cell, QColor(pal["bg"]))
        for i, n in enumerate(NAMES):
            icon = make_icon(n, pal["muted"], pal["accent"], 36)
            pm = icon.pixmap(36, 36, mode=icon.Mode.Normal, state=icon.State.On if half else icon.State.Off)
            p.drawPixmap(i * cell + 30, y0 + 14, pm)
            p.setPen(QColor(pal["accent"] if half else pal["muted"]))
            f = QFont("Microsoft YaHei UI", 10)
            p.setFont(f)
            p.drawText(QRectF(i * cell, y0 + 56, cell, 24), Qt.AlignmentFlag.AlignCenter, LABELS[n])
p.end()
out = sys.argv[1] if len(sys.argv) > 1 else "nav_icons_preview.png"
img.save(out)
print("saved", out)
