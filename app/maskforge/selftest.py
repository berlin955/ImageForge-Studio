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
        if mp.stem.startswith("640"):
            assert det.size == 640, f"640 模型的推理分辨率不对：{det.size}"
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
        from .detector import merge_buttocks
        stacked = plan_layers(merge_buttocks([
            {"label": "BUTTOCKS_EXPOSED", "score": 0.7, "box": (400, 1000, 800, 1300)},
            {"label": "ANUS_EXPOSED", "score": 0.5, "box": (580, 1250, 620, 1290)},
            {"label": "BUTTOCKS_EXPOSED", "score": 0.4, "box": (420, 1150, 780, 1450)}]), 1200, 1600, cfg)
        assert [l.part for l in stacked] == ["crack"], [(l.part, l.cy) for l in stacked]
        halves = merge_buttocks([{"label": "BUTTOCKS_EXPOSED", "score": 0.6, "box": (400, 1000, 600, 1300)},
                                 {"label": "BUTTOCKS_EXPOSED", "score": 0.6, "box": (590, 1010, 800, 1310)}])
        assert len(halves) == 1, halves
        back = plan_layers([{"label": "BUTTOCKS_EXPOSED", "score": 0.7, "box": (400, 900, 800, 1250)},
                            {"label": "FEMALE_GENITALIA_EXPOSED", "score": 0.5, "box": (570, 1230, 630, 1290)}],
                           1200, 1600, cfg)
        assert [l.part for l in back] == ["crack"], [(l.part, l.cx, l.cy) for l in back]
        front = plan_layers([{"label": "FEMALE_GENITALIA_EXPOSED", "score": 0.6, "box": (540, 900, 660, 1000)}],
                            1200, 1600, cfg)
        assert [l.part for l in front] == ["lower"]
        log("one crack mask ok")

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

        # ---- 模拟真实操作：拖动很小的码、按住方向键 ----
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtTest import QTest
        src2 = tmp / "测试 图片 02.jpg"
        assert img.save(str(src2), "JPEG", 90)
        mw.import_paths([str(src2)])
        mw.go(0)
        mw.resize(1400, 900)
        mw.show()
        mw.activateWindow()
        app.processEvents()
        mw.canvas.fit()
        app.processEvents()
        doc = mw.cur_doc()
        mw.add_layer("areola")                     # 小码
        L = doc.layers[-1]
        app.processEvents()
        s0 = mw.canvas.transform().m11()
        vp = mw.canvas.viewport()
        start = mw.canvas.mapFromScene(QPointF(L.cx, L.cy))
        cx0, cy0, w0 = L.cx, L.cy, L.w
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for i in range(1, 9):
            QTest.mouseMove(vp, start + QPoint(6 * i, 4 * i))
            app.processEvents()
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(48, 32))
        app.processEvents()
        moved = (L.cx - cx0) * s0
        assert abs(L.w - w0) < 1e-6, f"小码被缩放了而不是移动：{w0} -> {L.w}"
        assert moved > 30, f"小码没有被拖动：移动了 {moved:.1f} 像素"
        log(f"drag small mask ok: moved {moved:.0f}px on screen")

        # 选中码时按住方向键（含自动重复），焦点在画布和在缩略图条两种情况
        mw.canvas.select(L.id)
        mw.canvas.setFocus()
        cx1 = L.cx
        for target in (mw.canvas, mw.film):
            target.setFocus()
            for i in range(40):
                ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier,
                               "", i > 0)
                QApplication.sendEvent(target, ev)
                if i % 5 == 0:
                    app.processEvents()
            QApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Right,
                                                     Qt.KeyboardModifier.NoModifier))
            app.processEvents()
        assert L.cx > cx1, "方向键没有移动选中的码"
        QTest.qWait(300)
        mw.undo()
        mw.redo()
        log(f"arrow nudge ok: {L.cx - cx1:.1f}")

        # 没选中码时：方向键切换图片，按住不放也不会连续乱切
        mw.canvas.select(None)
        for i in range(30):
            ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, "", i > 0)
            QApplication.sendEvent(mw.canvas, ev)
            app.processEvents()
        QTest.qWait(50)
        assert mw.cur == 1, f"按住方向键切图异常：当前第 {mw.cur + 1} 张"
        QApplication.sendEvent(mw.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))
        QTest.qWait(50)
        assert mw.cur == 0, mw.cur
        for f in ("check", "ok", "all"):
            mw.set_film_filter(f)
            QApplication.sendEvent(mw.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
            app.processEvents()
        QTest.qWait(400)
        mw.go(0)
        app.processEvents()
        if mw.cur_doc().layers:
            Lh = mw.cur_doc().layers[0]
            QTest.mouseMove(vp, mw.canvas.mapFromScene(QPointF(Lh.cx, Lh.cy)))
            app.processEvents()
        mw.canvas.select(None)
        for i in range(6):
            mw.film.setFocus()
            QApplication.sendEvent(mw.windowHandle(), QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right if i % 2 == 0 else Qt.Key.Key_Left,
                                                                Qt.KeyboardModifier.NoModifier))
            QTest.qWait(30)
        log("arrow navigation ok")
        doc = mw.docs[0]
        mw.go(0)
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
        assert pd.grid.count() == len(mw.docs), (pd.grid.count(), len(mw.docs))
        pd.close()
        mw.upload_stickers  # 存在
        sid = lib.add(str(src))
        assert lib.exists(sid)
        mw.on_library_changed()
        mw.side.sync_from_cfg()
        from .panels import ExportDialog
        ed = ExportDialog(mw)
        ed.close()
        for key in theme.THEME_ORDER:
            mw.set_theme(key)
        mw.set_film_filter("check")
        mw.set_film_filter("all")
        mw.add_layer("crack")
        mw.side.refresh()
        assert mw.side.s_layer.isVisibleTo(mw.side), "选中码后应显示码的属性"
        log("preview / stickers ok")
        # ---- 智图工坊：功能栏、素材页、批量主图 ----
        for key in mw.page_keys:
            mw.show_page(key)
            app.processEvents()
        # 打开批量主图页会在后台识别人物位置，等它做完
        for _ in range(300):
            if not mw.busy:
                break
            QTest.qWait(100)
        assert not mw.busy, "后台识别人物位置没有结束"
        assert all(d.subject is not None for d in mw.docs), "没有识别出人物位置"
        log("subject analysis ok")
        mw.show_page("assets")
        mw.assets_page.refresh()
        assert mw.assets_page.grid.count() == len(mw.docs), "素材页图片数量不对"
        from .mainimage import compose, crop_rect_aspect
        d0 = mw.docs[0]
        d0.subject, d0.face = (300.0, 200.0, 900.0, 1500.0), (520.0, 220.0, 680.0, 400.0)
        r = crop_rect_aspect(d0, 1200, 1600, 1.0, "smart", {})
        assert abs(r.width() - 1200) < 1 and r.y() < 400, f"智能裁切位置不对：{r}"
        r2 = crop_rect_aspect(d0, 1200, 1600, 0.5, "smart", {"cx": 0.5, "cy": 0.5, "scale": 0.5})
        assert abs(r2.width() / r2.height() - 0.5) < 1e-6, r2
        mp = mw.main_page
        mp._force = True
        mc = mw.cfg["mainimg"]
        logo_file = tmp / "logo.png"
        lg = QImage(300, 120, QImage.Format.Format_ARGB32)
        lg.fill(QColor(220, 30, 80, 200))
        assert lg.save(str(logo_file))
        mc["logo"].update(enabled=True, file=str(logo_file))
        for size, mode in ((800, "smart"), (1000, "center"), (1440, "pad")):
            mc.update(size=size, mode=mode, layout="single")
            img, cells, lr = compose(mc, [(d0, {})], None, lib, size, preview=False)
            assert img.width() == size and img.height() == size, (img.width(), size)
            assert lr is not None and lr.x() < size * 0.2 and lr.y() < size * 0.2, f"角标不在左上角：{lr}"
        img, cells, lr = compose(mc, [(d0, {})], (0.6, 0.7), lib, 800, preview=False)
        assert abs(lr.x() - 480) < 2 and abs(lr.y() - 560) < 2, f"单张手动挪角标无效：{lr}"
        mc.update(layout="collage", mode="smart", cells=2, gap=10)
        mp.auto_group()
        assert mp.groups and len(mp.groups[0]["docs"]) == 2, mp.groups
        for n in (2, 3, 4):
            items = [(mw.docs[i % len(mw.docs)], {}) for i in range(n)]
            img, cells, lr = compose(mc, items, None, lib, 1000, preview=True)
            assert len(cells) == n and img.width() == 1000, (len(cells), img.width())
            assert all(c[0].height() > c[0].width() for c in cells), "竖格拼图的格子应该是竖长的"
        mp.refresh()
        mw.cfg["export"]["dir"] = str(tmp / "out")
        mw.cfg["export"]["open_after"] = False
        n_ok = mp._export(mp.targets())
        files = list((tmp / "out" / "主图").glob("*"))
        assert n_ok == len(mp.targets()) and files, (n_ok, files)
        mc.update(layout="single")
        n_ok = mp._export(mp.targets())
        files = sorted((tmp / "out" / "主图").glob("*"))
        back = QImage(str(files[-1]))
        assert back.width() == 800 or back.width() == mc["size"], back.width()
        log(f"main image ok: {len(files)} files")
        mw.show_page("mask")
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
