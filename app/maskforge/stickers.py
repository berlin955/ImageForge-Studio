"""码贴图库：内置贴图 + 用户上传的 PNG。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF)

from .config import data_dir

BUILTIN = [
    ("builtin:heart", "爱心"),
    ("builtin:star", "星星"),
    ("builtin:dot", "黑圆"),
    ("builtin:bar", "黑条"),
    ("builtin:pixel", "像素块"),
    ("builtin:cloud", "白云"),
]
_BUILTIN_NAMES = dict(BUILTIN)
USER_EXTS = {".png", ".webp", ".jpg", ".jpeg"}


def _draw_builtin(key: str, size: int = 512) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)
    p.setPen(Qt.PenStyle.NoPen)
    name = key.split(":", 1)[1]
    if name == "heart":
        path = QPainterPath(QPointF(128, 228))
        path.cubicTo(-30, 126, 30, -10, 128, 66)
        path.cubicTo(226, -10, 286, 126, 128, 228)
        g = QLinearGradient(0, 20, 0, 228)
        g.setColorAt(0, QColor("#ff7aa5"))
        g.setColorAt(1, QColor("#f0306d"))
        p.fillPath(path, QBrush(g))
        p.setBrush(QColor(255, 255, 255, 90))
        p.save()
        p.translate(76, 70)
        p.rotate(-35)
        p.drawEllipse(QRectF(-22, -12, 44, 24))
        p.restore()
    elif name == "star":
        poly = QPolygonF()
        import math
        for i in range(10):
            r = 54 if i % 2 else 122
            a = -math.pi / 2 + i * math.pi / 5
            poly.append(QPointF(128 + math.cos(a) * r, 134 + math.sin(a) * r))
        p.setBrush(QColor("#ffc23d"))
        pen = QPen(QColor("#e5951a"), 8)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolygon(poly)
    elif name == "dot":
        p.setBrush(QColor("#16171b"))
        p.drawEllipse(QRectF(8, 8, 240, 240))
    elif name == "bar":
        p.setBrush(QColor("#16171b"))
        p.drawRoundedRect(QRectF(6, 70, 244, 116), 34, 34)
    elif name == "pixel":
        cs = ["#2b2d33", "#3a3d45", "#22242a", "#4a4d56"]
        for y in range(8):
            for x in range(8):
                if ((x - 3.5) ** 2 + (y - 3.5) ** 2) ** 0.5 > 4.2:
                    continue
                p.setBrush(QColor(cs[(x * 7 + y * 3) % 4]))
                p.drawRect(QRectF(x * 32, y * 32, 32, 32))
    elif name == "cloud":
        path = QPainterPath()
        for (x, y, r) in [(70, 140, 58), (128, 108, 74), (190, 140, 58), (128, 160, 62)]:
            path.addEllipse(QPointF(x, y), r, r)
        path = path.simplified()
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor("#cfd4dd"), 6))
        p.drawPath(path)
    p.end()
    return img


class StickerLibrary:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else data_dir() / "stickers"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, QImage] = {}

    def items(self) -> list[tuple[str, str]]:
        res = list(BUILTIN)
        for f in sorted(self.folder.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file() and f.suffix.lower() in USER_EXTS:
                res.append((f"user:{f.name}", f.stem))
        return res

    def name(self, sid: str) -> str:
        if sid in _BUILTIN_NAMES:
            return _BUILTIN_NAMES[sid]
        if sid.startswith("user:"):
            return Path(sid[5:]).stem
        return sid

    def image(self, sid: str) -> QImage:
        img = self._cache.get(sid)
        if img is not None:
            return img
        if sid in _BUILTIN_NAMES:
            img = _draw_builtin(sid)
        elif sid.startswith("user:"):
            img = QImage(str(self.folder / sid[5:]))
            if img.isNull():
                return self.image("builtin:heart")
        else:
            return self.image("builtin:heart")
        self._cache[sid] = img
        return img

    def add(self, src) -> str:
        reader = QImageReader(str(src))
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            raise ValueError("无法读取这张图片")
        m = max(img.width(), img.height())
        if m > 1024:
            img = img.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        stem = re.sub(r'[\\/:*?"<>|]+', "_", Path(src).stem)[:40] or "sticker"
        target = self.folder / f"{stem}.png"
        n = 2
        while target.exists():
            target = self.folder / f"{stem}_{n}.png"
            n += 1
        if not img.save(str(target), "PNG"):
            raise ValueError("保存贴图失败")
        sid = f"user:{target.name}"
        self._cache.pop(sid, None)
        return sid

    def remove(self, sid: str) -> None:
        if not sid.startswith("user:"):
            return
        try:
            (self.folder / sid[5:]).unlink()
        except FileNotFoundError:
            pass
        self._cache.pop(sid, None)

    def exists(self, sid: str) -> bool:
        if sid in _BUILTIN_NAMES:
            return True
        return sid.startswith("user:") and (self.folder / sid[5:]).exists()
