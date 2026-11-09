"""构建时的自检：加载模型、识别、各种码样式、三种格式导出。失败返回非 0。"""
from __future__ import annotations

import math
import tempfile
import traceback
from pathlib import Path


def run_selftest(log_path: str | None = None) -> int:
    lines: list[str] = []

    def log(s):
        lines.append(str(s))
        print(s, flush=True)

    code = 0
    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from . import __version__, theme
        from .config import Config, model_path
        from .detector import Detector, plan_layers
        from .exporter import compute_size, output_name, render_doc, save_image
        from .mainwindow import MainWindow
        from .model import Layer
        from .stickers import StickerLibrary

        log(f"MaskForge Studio v{__version__} selftest")
        tmp = Path(tempfile.mkdtemp(prefix="maskforge-test-"))
        src = tmp / "测试 图片 01.jpg"
        img = QImage(1200, 1600, QImage.Format.Format_RGB32)
        p = QPainter(img)
        g = QRadialGradient(QPointF(600, 700), 900)
        g.setColorAt(0, QColor("#c9b8a3"))
        g.setColorAt(1, QColor("#4a4440"))
        p.fillRect(img.rect(), g)
        for i in range(40):
            p.fillRect(30 * i, 0, 15, 1600, QColor(255, 255, 255, 25))
        p.end()
        assert img.save(str(src), "JPEG", 92), "无法写入测试图片"

        cfg = Config(tmp / "config.json")
        lib = StickerLibrary(tmp / "stickers")
        for sid, _ in lib.items():
            assert not lib.image(sid).isNull(), f"贴图 {sid} 生成失败"
        log(f"stickers ok: {len(lib.items())}")

        mp = model_path()
        assert mp.exists(), f"模型不存在: {mp}"
        det = Detector(mp)
        dets = det.detect(img, 0.25)
        log(f"detector ok: model={mp.name} input={det.size}, detections={len(dets)}")
        fake = [
            {"label": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": (400, 400, 560, 560)},
            {"label": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": (640, 400, 800, 560)},
            {"label": "FEMALE_GENITALIA_EXPOSED", "score": 0.7, "box": (540, 900, 660, 1000)},
            {"label": "BUTTOCKS_EXPOSED", "score": 0.7, "box": (400, 1050, 800, 1350)},
        ]
        planned = plan_layers(fake, 1200, 1600, cfg)
        parts = sorted(l.part for l in planned)
        assert parts == ["areola", "areola", "crack", "lower"], parts
        log(f"planner ok: {parts}")
        cov = plan_layers([{"label": "BUTTOCKS_COVERED", "score": 0.6, "box": (400, 1050, 800, 1350), "crack_x": 640.0},
                           {"label": "FEMALE_BREAST_COVERED", "score": 0.6, "box": (400, 400, 560, 560)}],
                          1200, 1600, cfg)
        assert [l.part for l in cov] == ["crack"] and abs(cov[0].cx - 640) < 1, [(l.part, l.cx) for l in cov]
        log("planner covered ok")

        theme.apply(app, "dark")
        mw = MainWindow(cfg, lib)
        mw.import_paths([str(src)])
        assert mw.cur_doc() is not None, "导入失败"
        doc = mw.cur_doc()
        assert doc.w == 1200 and doc.h == 1600, (doc.w, doc.h)
        for part in ("lower", "crack", "areola", "custom"):
            mw.add_layer(part)
        styles = ["sticker", "mosaic", "blur", "solid"]
        for L, st in zip(doc.layers, styles):
            L.style = st
            L.rot = 20
            L.skew = 10
        doc.layers.append(Layer(part="custom", style="mosaic", cx=100, cy=100, w=300, h=200, rot=-30))
        mw.canvas.rebuild()
        mw.undo()
        mw.redo()
        log(f"editor ok: {len(doc.layers)} layers")
        theme.apply(app, "light")
        mw.apply_theme()

        for fmt in ("jpg", "png", "webp"):
            ex = dict(cfg["export"], format=fmt, mode="long", value=800, dir=str(tmp / "out"))
            out = render_doc(doc, doc.image(), lib, ex)
            k, W, H = compute_size(1200, 1600, ex)
            assert (out.width(), out.height()) == (W, H) == (600, 800), (out.width(), out.height(), W, H)
            path = tmp / "out" / output_name(doc, ex)
            save_image(out, path, ex)
            back = QImage(str(path))
            assert not back.isNull() and back.width() == 600, f"{fmt} 读回失败"
            log(f"export {fmt} ok: {path.name} {path.stat().st_size} bytes")

        # 码确实改变了像素
        ex = dict(cfg["export"], format="png", mode="none")
        plain_doc_layers = doc.layers
        doc.layers = []
        a = render_doc(doc, doc.image(), lib, ex)
        doc.layers = plain_doc_layers
        b = render_doc(doc, doc.image(), lib, ex)
        assert a.pixelColor(600, 800) != b.pixelColor(600, 800) or a.pixelColor(100, 100) != b.pixelColor(100, 100), "打码没有生效"
        log("mask applied ok")

        from .exporter import render_preview
        from .preview import PreviewDialog
        mw._thumb_done(doc.id, doc.image().scaled(300, 400), 1200, 1600)
        pv = render_preview(doc, doc.thumb, lib)
        assert pv is not None and pv.width() == 300, "预览图失败"
        mw._flush_thumbs()
        pd = PreviewDialog(mw)
        assert pd.grid.count() == 1, pd.grid.count()
        pd.close()
        mw.upload_stickers  # 存在
        sid = lib.add(str(src))
        assert lib.exists(sid)
        mw.on_library_changed()
        mw.batch_panel.sync_from_cfg()
        log("preview / stickers ok")
        from .settings import SettingsDialog
        dlg = SettingsDialog(mw)
        dlg.close()
        log("settings ok")
        mw.close()
        log("SELFTEST OK")
    except Exception:
        code = 1
        log("SELFTEST FAILED")
        log(traceback.format_exc())
    if log_path:
        try:
            Path(log_path).write_text("\n".join(lines), "utf-8")
        except Exception:
            pass
    return code
