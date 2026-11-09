"""导出：先在原图上打码，再缩放到目标尺寸保存。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QImageWriter, QPainter
from PySide6.QtWidgets import QGraphicsScene

from .canvas import ImageItem, LayerItem, RenderContext
from .model import ImageDoc

FORMATS = {"jpg": ("jpg", b"jpeg"), "png": ("png", b"png"), "webp": ("webp", b"webp")}


def compute_size(w: int, h: int, ex: dict) -> tuple[float, int, int]:
    mode, v = ex.get("mode", "none"), float(ex.get("value") or 0)
    k = 1.0
    if mode == "long" and v > 0:
        k = v / max(w, h)
    elif mode == "width" and v > 0:
        k = v / w
    elif mode == "height" and v > 0:
        k = v / h
    elif mode == "percent" and v > 0:
        k = v / 100.0
    if ex.get("no_upscale", True):
        k = min(k, 1.0)
    k = max(k, 0.01)
    return k, max(1, round(w * k)), max(1, round(h * k))


def output_name(doc: ImageDoc, ex: dict) -> str:
    ext = FORMATS.get(ex.get("format", "jpg"), FORMATS["jpg"])[0]
    return f"{ex.get('prefix', '')}{doc.path.stem}{ex.get('suffix', '')}.{ext}"


def unique_path(folder: Path, name: str, overwrite: bool, taken: set) -> Path:
    p = folder / name
    if overwrite and str(p).lower() not in taken:
        return p
    stem, suf = p.stem, p.suffix
    n = 2
    while p.exists() or str(p).lower() in taken:
        p = folder / f"{stem}({n}){suf}"
        n += 1
    return p


def render_doc(doc: ImageDoc, image: QImage, library, ex: dict) -> QImage:
    k, W, H = compute_size(image.width(), image.height(), ex)
    ctx = RenderContext(library)
    ctx.exporting = True
    ctx.set_image(doc, image)
    ctx.view_scale = k
    scene = QGraphicsScene()
    base = ImageItem()
    base.set_image(image)
    scene.addItem(base)
    for i, L in enumerate(doc.layers):
        it = LayerItem(L, ctx)
        it.setZValue(i + 1)
        scene.addItem(it)
    fmt = ex.get("format", "jpg")
    out = QImage(W, H, QImage.Format.Format_ARGB32 if fmt == "png" else QImage.Format.Format_RGB32)
    out.fill(Qt.GlobalColor.transparent if fmt == "png" else Qt.GlobalColor.white)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(p, QRectF(0, 0, W, H), QRectF(0, 0, image.width(), image.height()),
                 Qt.AspectRatioMode.IgnoreAspectRatio)
    p.end()
    scene.clear()
    return out


def save_image(img: QImage, path: Path, ex: dict) -> None:
    fmt = FORMATS.get(ex.get("format", "jpg"), FORMATS["jpg"])[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    w = QImageWriter(str(path), fmt)
    if fmt in (b"jpeg", b"webp"):
        w.setQuality(int(ex.get("quality", 92)))
    if fmt == b"jpeg" and img.hasAlphaChannel():
        img = img.convertToFormat(QImage.Format.Format_RGB32)
    if not w.write(img):
        raise RuntimeError(w.errorString() or "写入文件失败")
