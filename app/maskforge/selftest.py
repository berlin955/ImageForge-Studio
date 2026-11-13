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
        if log_path:   # 边跑边写，万一中途闪退也能看到停在哪一步
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(str(s) + "\n")
            except Exception:
                pass

    code = 0
    if log_path:
        try:
            import faulthandler
            _fh = open(str(log_path) + ".crash", "w", encoding="utf-8")
            faulthandler.enable(file=_fh, all_threads=True)
            from PySide6.QtCore import qInstallMessageHandler

            def _qt_msg(mode, ctx, msg):
                log(f"[qt {int(mode.value) if hasattr(mode, 'value') else mode}] {msg}")
            qInstallMessageHandler(_qt_msg)
        except Exception as e:
            log(f"faulthandler: {e}")
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
        assert abs(cov[0].cy - (1050 + 300 * 0.54)) < 1, cov[0].cy      # 默认比框中间略靠下
        tl = plan_layers([{"label": "BUTTOCKS_EXPOSED", "score": 0.6, "box": (400, 1050, 800, 1350), "tilt": 20.0}],
                         1200, 1600, cfg)
        assert abs(tl[0].rot - 20) < 0.01 and tl[0].cx < 600, (tl[0].rot, tl[0].cx)   # 往下挪的方向也跟着斜
        from .pose import crack_tilt
        import numpy as _np
        kp = _np.zeros((17, 3), _np.float32)
        kp[11] = (300, 500, 0.9)
        kp[12] = (200, 460, 0.9)          # 画面右边那个髋高 40 像素：顺时针转约 21.8°
        assert abs(crack_tilt(kp, 600) - 21.8) < 0.5, crack_tilt(kp, 600)
        kp[5], kp[6] = (330, 200, 0.9), (190, 200, 0.9)
        assert crack_tilt(kp, 600) is None or abs(crack_tilt(kp, 600) - 21.8) < 0.5
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
        import time as _t0
        import numpy as _npp
        _a = _t0.monotonic()
        _pe = mw.get_pose()
        log(f"pose load: {_pe is not None} {_t0.monotonic() - _a:.1f}s")
        if _pe is not None:
            _a = _t0.monotonic()
            _kp = _pe.keypoints(_npp.full((900, 600, 3), 200, _npp.uint8))
            log(f"pose run: {_t0.monotonic() - _a:.2f}s -> {None if _kp is None else _kp.shape}")
        # ---- 智图工坊：功能栏、素材页、批量主图 ----
        for key in mw.page_keys:
            mw.show_page(key)
            app.processEvents()
        # 打开批量主图页会在后台识别人物位置，等它做完
        for _ in range(300):
            if not mw.busy:
                break
            QTest.qWait(100)
        if mw.busy:
            log(f"busy: worker={type(mw._worker).__name__ if mw._worker else None} "
                f"pose_err={getattr(mw._worker, 'pose_error', '')!r}")
        assert not mw.busy, "后台识别人物位置没有结束"
        assert all(d.subject is not None for d in mw.docs), "没有识别出人物位置"
        log("subject analysis ok")
        mw.show_page("assets")
        mw.assets_page.refresh()
        assert mw.assets_page.grid.count() == len(mw.docs), "素材页图片数量不对"
        for k in ("s", "l", "m"):
            mw.assets_page.set_thumb_size(k)
            app.processEvents()
        it0 = mw.assets_page.grid.item(0)
        assert it0.text() == mw.docs[0].name, it0.text()
        mw.assets_page.grid.grab()   # 实际画一遍缩略图，确认绘制不出错
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
        # 「原图（不打码）」模式：和打码版不一样，且与不带码的渲染一致
        mc.update(size=800, mode="center", layout="single", use_mask=True)
        lg_en = mc["logo"]["enabled"]
        mc["logo"]["enabled"] = False
        a1, _c, _l = compose(mc, [(d0, {})], None, lib, 800, preview=False)
        mc["use_mask"] = False
        a2, _c, _l = compose(mc, [(d0, {})], None, lib, 800, preview=False)
        mc["use_mask"] = True
        mc["logo"]["enabled"] = lg_en
        assert a1 != a2, "主图「原图」模式没有去掉码"
        log("main image plain mode ok")
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
        # ---- 智能规格：生成模板（文字识别 + 擦字）、填图、改字、导出 ----
        from PySide6.QtGui import QFont
        from .spec_engine import build_template, find_slots, load_templates
        tpl_src = tmp / "规格模板.png"
        # 测试环境里 Qt 没有系统字体，文字用 OpenCV 画
        import cv2
        import numpy as _np
        arr = _np.full((1000, 1000, 3), 233, _np.uint8)
        _rng = _np.random.default_rng(3)
        # 左边：贴着上下边的直角照片；右边：胶囊形相框里的照片（带描边）
        arr[:, :480] = _rng.integers(30, 220, (1000, 480, 3), dtype=_np.uint8)
        cap = _np.zeros((1000, 1000), _np.uint8)
        cv2.rectangle(cap, (560, 470), (900, 650), 1, -1)
        cv2.circle(cap, (730, 470), 170, 1, -1)
        cv2.circle(cap, (730, 650), 170, 1, -1)
        tex = _rng.integers(30, 220, (1000, 1000, 3), dtype=_np.uint8)
        arr[cap > 0] = tex[cap > 0]
        ring = cv2.dilate(cap, _np.ones((9, 9), _np.uint8)) - cap
        arr[ring > 0] = (150, 120, 90)
        arr[60:180, 560:960] = 17
        cv2.putText(arr, "6757 WHITE", (585, 145), cv2.FONT_HERSHEY_SIMPLEX, 1.9, (255, 255, 255), 5, cv2.LINE_AA)
        cv2.putText(arr, "SIZE 80-125", (600, 920), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (50, 50, 50), 3, cv2.LINE_AA)
        ok_, buf = cv2.imencode(".png", arr)
        buf.tofile(str(tpl_src))
        tpl = build_template(str(tpl_src), None, "测试规格")
        texts = " | ".join(t["text"] for t in tpl["texts"])
        log(f"spec ocr: {texts}")
        from . import spec_engine as _se
        if _se.last_error:
            log("ocr error: " + _se.last_error)
        assert any("6757" in t["text"] for t in tpl["texts"]), f"没有识别出文字：{texts}"
        from .spec_engine import template_bg
        bgimg = template_bg(tpl)
        t0 = next(t for t in tpl["texts"] if "6757" in t["text"])
        # 原来白字的位置应该被擦成接近黑色底
        cx, cy = int(t0["x"] + t0["w"] * 0.3), int(t0["y"] + t0["h"] * 0.5)
        assert bgimg.pixelColor(cx, cy).lightness() < 90, f"文字没有擦干净：{bgimg.pixelColor(cx, cy).name()}"
        log(f"spec text erased ok: color={t0['color']} size={t0['size']:.0f}")
        assert load_templates("spec") and load_templates("spec")[0]["id"] == tpl["id"]
        sp = mw.spec_page
        mw.show_page("spec")
        sp.reload_templates(select=tpl["id"])
        app.processEvents()
        log(f"spec slots: {[(s['role'], int(s['x']), int(s['y']), int(s['w']), int(s['h']), s.get('shape'), s.get('radius')) for s in tpl['slots']]}")
        assert len(sp.tpl["slots"]) == 2, sp.tpl["slots"]
        s0, s1 = sp.tpl["slots"]
        assert s0["x"] < 5 and abs(s0["w"] - 480) < 15 and s0["h"] > 980, s0
        assert abs(s1["x"] - 560) < 15 and abs(s1["y"] - 300) < 15 and abs(s1["h"] - 520) < 20, s1
        from .spec import slot_shape_key
        assert slot_shape_key(s0) == "rect" and slot_shape_key(s1) in ("capsule", "ellipse"), (s0, s1)
        sp.set_edit_mode(True)
        from PySide6.QtCore import QRectF as _R
        sp.add_slot(_R(10, 10, 50, 50))
        sp.view.scene().clearSelection()
        sp.slot_items[sp.tpl["slots"][-1]["id"]].setSelected(True)
        sp._set_shape("ellipse")
        assert sp.tpl["slots"][-1]["shape"] == "ellipse"
        sp.delete_selected_slot()
        sp.set_edit_mode(False)
        assert len(sp.tpl["slots"]) == 2
        for d in mw.docs:
            d.labels = None
        mw.docs[0].labels, mw.docs[1].labels = ["FACE_FEMALE"], ["BUTTOCKS_EXPOSED"]
        mw.docs[0].facing, mw.docs[1].facing = 2.0, -2.0
        sp.auto_fill()
        roles = {s["role"]: sp.fills.get(s["id"], {}).get("doc") for s in sp.tpl["slots"]}
        assert roles.get("正面") == mw.docs[0].id and roles.get("背面") == mw.docs[1].id, roles
        t_edit = next(iter(sp.text_edits.values()))
        t_edit.setText("7039 粉色")
        t_edit.textEdited.emit("7039 粉色")
        sp.save_current_template()
        out_img = sp.render_output()
        assert out_img.width() == 1000 and out_img.height() == 1000
        # 没改过的字保持原图像素；改过的字才擦掉重画
        from .spec_engine import text_changed
        from .spec import text_rect
        tz = next(t for t in sp.tpl["texts"] if "SIZE" in t["text"].upper())
        assert not text_changed(tz), "没动过的字被当成改过了"
        assert text_changed(next(t for t in sp.tpl["texts"] if t["text"] == "7039 粉色"))
        org = QImage(str(tpl_src))
        dark = min(((org.pixelColor(x, y).lightness(), x, y)
                    for x in range(int(tz["x"]), int(tz["x"] + tz["w"]), 2)
                    for y in range(int(tz["y"]), int(tz["y"] + tz["h"]), 2)))
        assert abs(out_img.pixelColor(dark[1], dark[2]).lightness() - dark[0]) < 12, "原字被改动了"
        log("keep original text ok")
        # ---- 字符面板（参考 PS）：选中文字 → 面板可用；字号、吸管、恢复原样、画布上缩放、直接改字 ----
        from PySide6.QtCore import QPointF as _QP
        ti = next(it for it in sp.text_items.values() if "SIZE" in it.t["text"].upper())
        cp = sp.char_panel
        sp.view.scene().clearSelection()
        assert cp.t is None and not cp.box.isEnabled(), "没选中文字时面板应该是灰的"
        ti.setSelected(True)
        app.processEvents()
        assert cp.t is ti.t and cp.box.isEnabled(), "选中文字后面板没有跟上"
        assert cp.picker.count() > 0, "字体列表是空的"
        size0 = float(ti.t["size"])
        cp.size.setValue(size0 + 6)
        assert abs(ti.t["size"] - (size0 + 6)) < 0.1 and text_changed(ti.t), ti.t["size"]
        app.processEvents()
        cp.refresh_compare_now()
        assert cp.compare.pixmap() is not None and not cp.compare.pixmap().isNull(), "对比图没画出来"
        pv = sp.text_preview(ti.t)
        assert pv and not pv[0].isNull() and pv[0].size() == pv[1].size(), "原图 / 现在 对比图出错"
        sp.set_eyedropper(True)
        sp.pick_color_at(_QP(5, 5))               # 左上角是照片位里的随机像素
        assert not sp.eyedrop and ti.t["color"] == QImage(str(tpl_src)).pixelColor(5, 5).name(), ti.t["color"]
        cp._reset()
        assert not text_changed(ti.t), "恢复原样后应该和原图一样"
        # 拖右下角放大一倍：字号翻倍，左上角不动
        r0 = ti.mapRectToScene(text_rect(ti.t))
        ti._begin_scale("br", r0.bottomRight())

        class _Ev:
            def __init__(self, p):
                self._p = p

            def scenePos(self):
                return self._p
        ti.mouseMoveEvent(_Ev(r0.topLeft() + (r0.bottomRight() - r0.topLeft()) * 2))
        ti.mouseReleaseEvent(_Ev(r0.topLeft()))
        r1 = ti.mapRectToScene(text_rect(ti.t))
        assert abs(ti.t["size"] / size0 - 2) < 0.05, ti.t["size"]
        assert abs(r1.left() - r0.left()) < 3 and abs(r1.top() - r0.top()) < 3, (r0, r1)
        cp._reset()
        # 画布上直接改字
        sp.start_inline_edit(ti)
        ed = sp._inline[0]
        ed.setText("SIZE 90-140")
        ed.textEdited.emit("SIZE 90-140")
        ed.returnPressed.emit()
        assert ti.t["text"] == "SIZE 90-140" and sp.text_edits[ti.t["id"]].text() == "SIZE 90-140"
        assert getattr(sp, "_inline", None) is None
        sp.view.grab()
        log("char panel ok")
        sp.name_edit.setText("测试规格图")
        path = sp.export_current()
        assert path and Path(path).exists(), path
        log(f"spec export ok: {Path(path).name}")
        # ---- 导入动画：扫描 → 照片框描边 → 进入模板 ----
        import time as _time
        n_before = len(load_templates("spec"))
        sp.start_scan(str(tpl_src))
        t_start = _time.monotonic()
        frames = 0
        while sp.scanning and _time.monotonic() - t_start < 120:
            app.processEvents()
            if frames < 40:
                sp.view.grab()        # 强制画几帧，检查动画绘制不出错
                frames += 1
            _time.sleep(0.02)
        assert not sp.scanning, "导入动画没有结束"
        assert sp.tpl and len(sp.tpl["slots"]) == 2 and len(load_templates("spec")) == n_before + 1, sp.tpl
        log(f"scan animation ok: {frames} frames, {_time.monotonic() - t_start:.1f}s")
        assert sp.in_review() and not sp.film_bar.isVisibleTo(sp), "识别完应该先显示识别结果"
        sp.view.grab()
        # 真的点一下「确认」按钮（之前按钮把 False 当名字传进去，存坏了模板名）
        from . import template_lib as _tl
        _ask = _tl.ask_name
        _tl.ask_name = lambda *a, **k: "测试命名模板"
        try:
            from PySide6.QtWidgets import QPushButton
            ok_btn = [b for b in sp.findChildren(QPushButton) if "下一步：填入素材" in b.text()]
            assert ok_btn, "找不到确认按钮"
            ok_btn[0].click()
        finally:
            _tl.ask_name = _ask
        assert sp.tpl["name"] == "测试命名模板", sp.tpl.get("name")
        sp.reload_templates()
        from .template_lib import TemplatePicker, ensure_thumb
        assert not ensure_thumb(sp.tpl).isNull(), "模板没有预览图"
        pk = TemplatePicker("spec", sp.tpl["id"], mw)
        assert pk.grid.count() >= 2 and pk.grid.current_tpl()["id"] == sp.tpl["id"]
        pk.deleteLater()
        mw.show_page("templates")
        mw.templates_page.on_show()
        assert mw.templates_page.grids["spec"].count() >= 2
        mw.templates_page._use(sp.tpl)
        assert mw.spec_page.tpl["id"] == sp.tpl["id"]
        log("template library ok")
        # 左侧面板不能被撑得比可见区域宽（之前右半边按钮被切掉）
        from PySide6.QtWidgets import QScrollArea
        for pg in (mw.spec_page, mw.detail_page):
            sa = pg.findChild(QScrollArea)
            if sa and sa.widget():
                log(f"panel width: content {sa.widget().minimumSizeHint().width()} / visible {sa.viewport().width()}")
                from PySide6.QtWidgets import QWidget as _QW
                wide = [(c.minimumSizeHint().width(), type(c).__name__, c.objectName(),
                         (getattr(c, "text", lambda: "")() if hasattr(c, "text") else "")[:20])
                        for c in sa.widget().findChildren(_QW) if c.minimumSizeHint().width() > 300]
                for wdt in sorted(wide, key=lambda x: x[0])[:12]:
                    log(f"   wide: {wdt}")
                assert sa.widget().minimumSizeHint().width() <= sa.viewport().width() + 2, \
                    f"面板内容太宽：{sa.widget().minimumSizeHint().width()} > {sa.viewport().width()}"
        from .spec_engine import default_name
        assert default_name("C:/x/93f31607-61c0-4001-a64a-1e38779a243f.png", "spec").startswith("规格模板")
        assert default_name("C:/x/7114黑色.png", "spec") == "7114黑色"
        log("side panel width ok")
        assert not sp.in_review() and sp.film_bar.isVisibleTo(sp) and sp.tpl.get("confirmed")
        log("review step ok")
        # ---- 正面 / 背面判断 ----
        from .pose import facing_of, facing_score, pose_model_path, PoseEstimator
        kp = _np.zeros((17, 3), _np.float32)
        kp[5] = (300, 200, 0.9); kp[6] = (200, 200, 0.9)      # 左肩在画面右边 → 正面
        kp[11] = (290, 400, 0.9); kp[12] = (210, 400, 0.9)
        kp[0] = (250, 120, 0.9); kp[1] = (260, 110, 0.9); kp[2] = (240, 110, 0.9)
        assert facing_of(facing_score(kp, [], 500)) == "front"
        kb = kp.copy()
        kb[[5, 6, 11, 12], 0] = kb[[6, 5, 12, 11], 0]            # 左右对调 → 背面
        kb[0:3, 2] = 0.05
        assert facing_of(facing_score(kb, ["BUTTOCKS_COVERED"], 500)) == "back"
        # 回头看镜头的背面照：脸看得见，但肩、髋和臀部都说是背面
        kt = kb.copy()
        kt[0:3, 2] = 0.9
        assert facing_of(facing_score(kt, ["BUTTOCKS_EXPOSED", "FACE_FEMALE"], 500)) == "back"
        if pose_model_path().exists():
            pe = PoseEstimator(pose_model_path())
            blank = _np.full((600, 400, 3), 230, _np.uint8)
            log(f"pose model ok: size {pe.size}, blank -> {pe.keypoints(blank) is None}")
            assert mw.get_pose() is not None
        else:
            log("pose model missing")
        log("facing ok")
        # ---- 中文文字识别（仿真实规格图：米色底、深色标题框、胶囊相框）----
        import os as _os
        font_file = next((f for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc",
                                      r"C:\Windows\Fonts\simhei.ttf",
                                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if _os.path.exists(f)), None)
        if font_file:
            from PIL import Image as _PI, ImageDraw as _PD, ImageFont as _PF
            zh = _np.full((800, 800, 3), (233, 218, 203), _np.uint8)
            zh[:, :430] = _rng.integers(30, 220, (800, 430, 3), dtype=_np.uint8)
            cap = _np.zeros((800, 800), _np.uint8)
            cv2.rectangle(cap, (480, 380), (780, 560), 1, -1)
            cv2.circle(cap, (630, 380), 150, 1, -1)
            cv2.circle(cap, (630, 560), 150, 1, -1)
            tex = _rng.integers(30, 220, (800, 800, 3), dtype=_np.uint8)
            zh[cap > 0] = tex[cap > 0]
            ring = cv2.dilate(cap, _np.ones((5, 5), _np.uint8)) - cap
            zh[ring > 0] = (230, 190, 160)
            pim = _PI.fromarray(zh)
            dr = _PD.Draw(pim)
            dr.rounded_rectangle((470, 60, 790, 120), 30, fill=(74, 52, 40))
            dr.text((520, 66), "7114 黑色", font=_PF.truetype(font_file, 40), fill=(255, 255, 255))
            dr.text((520, 150), "{含：单件露臀内裤}", font=_PF.truetype(font_file, 24), fill=(90, 70, 60))
            dr.text((500, 740), "建议体重：80-115斤", font=_PF.truetype(font_file, 24), fill=(90, 70, 60))
            zh_src = tmp / "中文规格.png"
            pim.save(str(zh_src))
            log(f"layout model: {mw.get_layout() is not None}")
            log(f"inpainter: {mw.get_inpainter() is not None}")
            ztpl = build_template(str(zh_src), mw.get_detector(), "中文规格", layout=mw.get_layout(),
                                  inpainter=mw.get_inpainter())
            log(f"zh keep layers: {[bool(s.get('keep')) for s in ztpl['slots']]}")
            zt = " | ".join(t["text"] for t in ztpl["texts"])
            log(f"zh ocr: {zt} (raw {ztpl.get('ocr_raw')}, err {ztpl.get('ocr_error')!r})")
            log(f"zh slots: {[(int(s['x']), int(s['y']), int(s['w']), int(s['h']), s.get('radius')) for s in ztpl['slots']]}")
            assert "7114" in zt and "体重" in zt, f"中文没有识别出来：{zt}"
            assert len(ztpl["slots"]) == 2, ztpl["slots"]
            from . import fonts as _fonts
            log(f"font pack: {len(_fonts.catalog())} fonts, registered {_fonts.register_all()}")
            if _fonts.has_pack():
                log("zh fonts: " + " | ".join(f"{t['text']}={t.get('font')} {t.get('size', 0):.1f}px sp{t.get('spacing', 0)}"
                                               for t in ztpl["texts"]))
                assert any(t.get("font") for t in ztpl["texts"]), "没有自动匹配字体"
                assert not any(text_changed(t) for t in ztpl["texts"]), "匹配字体后没改过的字被当成改过了"
                # 测试图是用微软雅黑（黑体类）画的：应该配上黑体类，不是宋体
                t7 = next(t for t in ztpl["texts"] if "7114" in t["text"])
                assert _fonts.stem_info(t7["font"])["cat"] == "sans", t7["font"]
                # 用自动匹配的字体画出来的字，大小、位置要和原字对得上
                from .spec import text_font
                from PySide6.QtGui import QFontMetricsF as _FM
                r7 = text_rect(t7)
                log(f"7114 rect {r7.left() + t7['x']:.0f},{r7.top() + t7['y']:.0f} {r7.width():.0f}x{r7.height():.0f}; "
                    f"family {text_font(t7).family()} / {_FM(text_font(t7)).ascent():.1f}")
                assert 500 <= r7.left() + t7["x"] <= 545, r7
        else:
            log("zh ocr skipped: no font")
        # ---- 智能详情：长图模板（分段照片 + 文字），按宽度导出并切片 ----
        rng = _np.random.default_rng(7)
        H_ = 4200
        arr = _np.full((H_, 1000, 3), 245, _np.uint8)
        blocks_ = [(260, 1160), (1400, 2300), (2560, 3460)]
        for y0, y1 in blocks_:
            noise = rng.integers(40, 200, (y1 - y0, 900, 3), dtype=_np.uint8)
            arr[y0:y1, 50:950] = noise   # 测试用的「照片」：纹理丰富的区块
        cv2.putText(arr, "NEW ARRIVAL", (250, 170), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (40, 40, 40), 5, cv2.LINE_AA)
        cv2.putText(arr, "SOFT COTTON 95", (240, 3700), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (40, 40, 40), 4, cv2.LINE_AA)
        det_src = tmp / "详情模板.png"
        ok_, buf = cv2.imencode(".png", arr)
        buf.tofile(str(det_src))
        dtpl = build_template(str(det_src), None, "测试详情", kind="detail")
        log(f"detail slots: {[(s['role'], int(s['y']), int(s['h'])) for s in dtpl['slots']]}")
        log(f"detail ocr: {' | '.join(t['text'] for t in dtpl['texts'])}")
        assert dtpl["kind"] == "detail" and len(dtpl["slots"]) >= 3, dtpl["slots"]
        assert any("ARRIVAL" in t["text"].upper() for t in dtpl["texts"]), dtpl["texts"]
        assert load_templates("detail") and not any(t["id"] == dtpl["id"] for t in load_templates("spec"))
        dp = mw.detail_page
        mw.show_page("detail")
        dp.reload_templates(select=dtpl["id"])
        app.processEvents()
        assert dp.view.long_mode()
        dp.auto_fill()
        assert len(dp.fills) == len(dp.tpl["slots"]), (len(dp.fills), len(dp.tpl["slots"]))
        dp.width_seg.set_value("790")
        dp._save_sc("width", 790)
        dp._save_sc("slice", 1500)
        dp.name_edit.setText("测试详情图")
        path = dp.export_current()
        parts = sorted((tmp / "out" / "详情").glob("测试详情图_*"))
        assert len(parts) >= 2, parts
        heights = [QImage(str(f)).height() for f in parts]
        assert all(QImage(str(f)).width() == 790 for f in parts), "详情宽度应为 790"
        assert abs(sum(heights) - round(H_ * 790 / 1000)) <= 2, heights
        log(f"detail export ok: {len(parts)} pieces {heights}")
        dp._save_sc("slice", 0)
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
    return code
