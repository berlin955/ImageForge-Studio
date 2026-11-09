"""导出：先在原图上打码，再缩放到目标尺寸保存。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter
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


def _render(doc, image: QImage, library, W: int, H: int, source: QRectF, target: QRectF,
            fmt: str, fill: str | None = None) -> QImage:
    """把原图 source 区域（含码）画到 W×H 画布的 target 区域。"""
    k = target.width() / max(1.0, source.width())
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
    out = QImage(W, H, QImage.Format.Format_ARGB32 if fmt == "png" else QImage.Format.Format_RGB32)
    if fill:
        out.fill(QColor(fill))
    else:
        out.fill(Qt.GlobalColor.transparent if fmt == "png" else Qt.GlobalColor.white)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(p, target, source, Qt.AspectRatioMode.IgnoreAspectRatio)
    p.end()
    scene.clear()
    return out


def render_doc(doc: ImageDoc, image: QImage, library, ex: dict) -> QImage:
    k, W, H = compute_size(image.width(), image.height(), ex)
    return _render(doc, image, library, W, H, QRectF(0, 0, image.width(), image.height()),
                   QRectF(0, 0, W, H), ex.get("format", "jpg"))


# ---------------------------------------------------------------- 主图（正方形）
def crop_rect(doc: ImageDoc, w: int, h: int, mode: str = "smart") -> QRectF:
    """主图在原图上的正方形裁切范围。"""
    c = doc.crop or {}
    scale = max(0.2, min(1.0, float(c.get("scale", 1.0))))
    side = min(w, h) * scale
    if "cx" in c:
        cx, cy = c["cx"] * w, c["cy"] * h
    elif mode == "smart" and doc.subject:
        x1, y1, x2, y2 = doc.subject
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if doc.face and (y2 - y1) > side * 0.9:
            # 人比框高：让脸靠近上边，身体往下排
            cy = doc.face[1] - side * 0.08 + side / 2
    else:
        cx, cy = w / 2, h / 2
    x = min(max(cx - side / 2, 0), w - side)
    y = min(max(cy - side / 2, 0), h - side)
    return QRectF(x, y, side, side)


def render_main(doc: ImageDoc, image: QImage, library, ex: dict) -> QImage:
    m = ex.get("main", {})
    size = int(m.get("size", 800))
    fmt = ex.get("format", "jpg")
    w, h = image.width(), image.height()
    if m.get("mode") == "pad":
        k = size / max(w, h)
        tw, th = w * k, h * k
        target = QRectF((size - tw) / 2, (size - th) / 2, tw, th)
        return _render(doc, image, library, size, size, QRectF(0, 0, w, h), target, fmt,
                       m.get("pad_color", "#ffffff"))
    src = crop_rect(doc, w, h, m.get("mode", "smart"))
    return _render(doc, image, library, size, size, src, QRectF(0, 0, size, size), fmt)


def main_name(doc: ImageDoc, ex: dict) -> str:
    m = ex.get("main", {})
    ext = FORMATS.get(ex.get("format", "jpg"), FORMATS["jpg"])[0]
    return f"{ex.get('prefix', '')}{doc.path.stem}{m.get('suffix', '_主图')}.{ext}"


def render_preview(doc: ImageDoc, thumb: QImage | None, library) -> QImage | None:
    """在缩略图上画出码，用于预览和缩略图条，不需要读原图。"""
    if thumb is None or thumb.isNull() or not doc.w:
        return thumb
    t = thumb.width() / doc.w
    layers = [L.clone(cx=L.cx * t, cy=L.cy * t, w=L.w * t, h=L.h * t) for L in doc.layers]
    if not layers:
        return thumb
    fake = SimpleNamespace(layers=layers)
    return render_doc(fake, thumb, library, {"mode": "none", "format": "png"})


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
