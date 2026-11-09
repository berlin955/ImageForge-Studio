"""左侧功能面板：批量处理 / 编辑 / 导出。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSpinBox, QWidget)

from .config import PARTS, PART_NAMES, STYLE_NAMES, STYLES
from .exporter import compute_size, output_name
from .widgets import (Card, ColorButton, Segmented, SliderRow, button, muted, row,
                      scroll_page)



# ---------------------------------------------------------------- 批量处理
class BatchPanel(QWidget):
    MAIN_PARTS = [p for p in PARTS if p[0] != "custom"]

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        cfg = mw.cfg
        self._loading = False

        # 1 素材
        c1 = Card("① 导入图片")
        self.stat = QLabel("还没有导入图片")
        self.stat.setObjectName("Stat")
        c1.add(self.stat)
        c1.add(muted("支持 JPG / PNG / WebP / BMP / TIFF，也可以直接把图片或文件夹拖进右侧窗口。"))
        b_files = button("导入图片…", tip="Ctrl+O")
        b_dir = button("导入文件夹…")
        b_files.clicked.connect(mw.import_dialog)
        b_dir.clicked.connect(mw.import_folder_dialog)
        c1.add(row(b_files, b_dir))
        b_rm = button("移除当前图片")
        b_clear = button("清空列表", "Danger")
        b_rm.clicked.connect(mw.remove_current)
        b_clear.clicked.connect(mw.clear_all)
        c1.add(row(b_rm, b_clear))

        # 2 打码样式
        c2 = Card("② 用什么码")
        c2.add(muted("一键打码会按这里的设置给每个部位贴码。点「上传」换成你自己的码图，透明背景的 PNG 效果最好。"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.part_checks, self.style_combos, self.stk_combos, self.previews = {}, {}, {}, {}
        for i, (k, n) in enumerate(self.MAIN_PARTS):
            r = i * 2
            cb = QCheckBox(n)
            cb.toggled.connect(lambda on, key=k: self._part_set(key, "enabled", on))
            pv = QLabel()
            pv.setFixedSize(40, 40)
            pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pv.setObjectName("StickerPreview")
            st = QComboBox()
            for sk, sn in STYLES:
                st.addItem(sn, sk)
            st.setFixedWidth(86)
            st.currentIndexChanged.connect(lambda _i, key=k: self._style_changed(key))
            sc = QComboBox()
            sc.setIconSize(QSize(22, 22))
            sc.currentIndexChanged.connect(lambda _i, key=k: self._sticker_changed(key))
            up = button("上传…", "", f"上传一张码图，{n}改用这张图")
            up.clicked.connect(lambda _=False, key=k: self._upload_for(key))
            grid.addWidget(pv, r, 0, 2, 1)
            grid.addWidget(cb, r, 1, 1, 3)
            grid.addWidget(st, r + 1, 1)
            grid.addWidget(sc, r + 1, 2)
            grid.addWidget(up, r + 1, 3)
            self.part_checks[k], self.style_combos[k], self.stk_combos[k], self.previews[k] = cb, st, sc, pv
        grid.setColumnStretch(2, 1)
        c2.add(grid)
        b_apply = button("把这些样式换到已打的码上", "", "已经打好码的图片也换成上面的样式")
        b_apply.clicked.connect(self._apply_all)
        c2.add(b_apply)
        c2.add(muted("码的大小、马赛克颗粒、有遮挡时是否打码等，在左下角「设置 → 识别与打码」。"))

        # 3 一键打码
        c3 = Card("③ 一键打码")
        c3.add(muted("AI 在本机识别所有未处理的图片并贴码，完成后打开预览，可以逐张检查再保存。"))
        self.sens = SliderRow("灵敏度", 20, 90, 0, "%")
        self.sens.valueChanged.connect(self._sens_changed)
        c3.add(self.sens)
        self.b_auto = button("一键打码", "Primary")
        self.b_auto.setMinimumHeight(40)
        self.b_auto.clicked.connect(mw.auto_mask)
        c3.add(self.b_auto)
        self.b_redetect = button("全部重新识别")
        self.b_redetect.clicked.connect(lambda: mw.detect(mode="all", then=mw.open_preview))
        c3.add(self.b_redetect)
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.hide()
        self.prog_txt = muted("")
        self.prog_txt.hide()
        self.b_stop = button("停止")
        self.b_stop.hide()
        self.b_stop.clicked.connect(mw.stop_detect)
        c3.add(self.prog)
        c3.add(row(self.prog_txt, None, self.b_stop))

        # 4 预览与保存
        c4 = Card("④ 预览并保存")
        self.review = QLabel("")
        self.review.setWordWrap(True)
        c4.add(self.review)
        self.b_preview = button("预览全部效果")
        self.b_preview.clicked.connect(mw.open_preview)
        b_next = button("逐张审核")
        b_next.clicked.connect(mw.next_pending)
        c4.add(row(self.b_preview, b_next))
        self.out_lbl = muted("")
        b_out = button("更改…")
        b_out.clicked.connect(mw.choose_out_dir)
        c4.add(row(self.out_lbl, None, b_out))
        self.b_save = button("保存全部", "Primary")
        self.b_save.setMinimumHeight(40)
        self.b_save.clicked.connect(mw.export_batch)
        c4.add(self.b_save)
        c4.add(muted("尺寸、格式和文件名在「导出」标签里设置。"))

        area, _ = scroll_page(c1, c2, c3, c4)
        from PySide6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(area)
        self.reload_stickers()
        self.sync_from_cfg()

    # ---- 配置 ----
    def reload_stickers(self):
        lib = self.mw.library
        self._loading = True
        for k, sc in self.stk_combos.items():
            sc.clear()
            for sid, name in lib.items():
                sc.addItem(QIcon(QPixmap.fromImage(lib.image(sid))), name, sid)
            sc.setCurrentIndex(max(0, sc.findData(self.mw.cfg.part(k)["sticker"])))
        self._loading = False

    def sync_from_cfg(self):
        cfg = self.mw.cfg
        self._loading = True
        for k, _n in self.MAIN_PARTS:
            p = cfg.part(k)
            self.part_checks[k].setChecked(p.get("enabled", True))
            self.style_combos[k].setCurrentIndex(max(0, self.style_combos[k].findData(p["style"])))
            self.stk_combos[k].setCurrentIndex(max(0, self.stk_combos[k].findData(p["sticker"])))
            self._update_row(k)
        self.sens.set_value(round((1 - cfg["detect"]["threshold"]) * 100))
        self._loading = False
        self.refresh()

    def _update_row(self, k):
        on = self.part_checks[k].isChecked()
        style = self.style_combos[k].currentData()
        self.style_combos[k].setEnabled(on)
        self.stk_combos[k].setEnabled(on and style == "sticker")
        pv = self.previews[k]
        p = self.mw.cfg.part(k)
        if style == "sticker":
            img = self.mw.library.image(p["sticker"])
            pm = QPixmap.fromImage(img).scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
            pv.setPixmap(pm)
            pv.setText("")
        else:
            pv.setPixmap(QPixmap())
            pv.setText({"mosaic": "▦", "blur": "◌", "solid": "■"}.get(style, ""))
        pv.setEnabled(on)

    def _part_set(self, key, attr, v):
        if self._loading:
            return
        self.mw.cfg.part(key)[attr] = v
        self.mw.cfg.save()
        self._update_row(key)

    def _style_changed(self, key):
        self._part_set(key, "style", self.style_combos[key].currentData())

    def _sticker_changed(self, key):
        sid = self.stk_combos[key].currentData()
        if sid:
            self._part_set(key, "sticker", sid)

    def _sens_changed(self, v: float):
        if self._loading:
            return
        self.mw.cfg["detect"]["threshold"] = round(1 - v / 100, 3)
        self.mw.cfg.save()

    def _upload_for(self, key):
        sid = self.mw.upload_stickers()
        if not sid:
            return
        p = self.mw.cfg.part(key)
        p["style"] = "sticker"
        p["sticker"] = sid
        p["enabled"] = True
        self.mw.cfg.save()
        self.sync_from_cfg()
        self.mw.status.showMessage(f"{PART_NAMES.get(key, key)}已改用你上传的码图", 5000)

    def _apply_all(self):
        for k, _n in self.MAIN_PARTS:
            self.mw.apply_part_style(k)

    # ---- 状态 ----
    def refresh(self):
        docs = self.mw.docs
        n = len(docs)
        self.stat.setText(f"{n} 张图片" if n else "还没有导入图片")
        cnt = {"todo": 0, "done": 0, "none": 0, "ok": 0, "error": 0}
        for d in docs:
            cnt[d.status()] += 1
        txt = (f"已确认 {cnt['ok']}　·　待审核 {cnt['done']}　·　未检出 {cnt['none']}　·　未处理 {cnt['todo']}"
               + (f"　·　读取失败 {cnt['error']}" if cnt["error"] else ""))
        self.review.setText(txt if n else "导入并打码后，在这里预览和保存。")
        out = self.mw.cfg["export"].get("dir") or ""
        self.out_lbl.setText(f"保存到：{out}" if out else "保存到：还没有选择文件夹")
        self.out_lbl.setToolTip(out)
        busy = self.mw.busy
        self.b_auto.setEnabled(n > 0 and not busy)
        self.b_redetect.setEnabled(n > 0 and not busy)
        self.b_preview.setEnabled(n > 0 and not busy)
        targets = self.mw.export_targets()
        self.b_save.setEnabled(bool(targets) and not busy)
        self.b_save.setText(f"保存全部 {len(targets)} 张" if targets else "保存全部")

    def set_progress(self, i: int, total: int, text: str):
        running = total > 0 and i < total
        self.prog.setVisible(running)
        self.prog_txt.setVisible(running)
        self.b_stop.setVisible(running)
        if total:
            self.prog.setValue(int(i * 100 / total))
        self.prog_txt.setText(text)


# ---------------------------------------------------------------- 编辑
class EditPanel(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._loading = False

        # 添加码
        c1 = Card("添加码")
        g = QGridLayout()
        g.setSpacing(6)
        self.part_btns = {}
        for i, (k, n) in enumerate(PARTS):
            b = button(f"＋ {n}", "Part")
            b.clicked.connect(lambda _=False, key=k: mw.add_layer(key))
            self.part_btns[k] = b
            g.addWidget(b, i // 2, i % 2)
        c1.add(g)
        c1.add(muted("也可以双击图片，在点击的位置添加上次选的部位。"))

        # 本图的码
        c2 = Card("本图的码")
        self.layer_list = QListWidget()
        self.layer_list.setObjectName("Layers")
        self.layer_list.setMaximumHeight(150)
        self.layer_list.itemClicked.connect(self._pick_layer)
        self.no_layers = muted("这张图还没有码。点上面的按钮添加，或者在「批量处理」里自动识别。")
        c2.add(self.layer_list)
        c2.add(self.no_layers)

        # 当前码
        self.c3 = Card("当前选中的码")
        self.part_combo = QComboBox()
        for k, n in PARTS:
            self.part_combo.addItem(n, k)
        self.part_combo.currentIndexChanged.connect(self._part_changed)
        lab = QLabel("部位")
        lab.setObjectName("Muted")
        lab.setFixedWidth(52)
        self.c3.add(row(lab, self.part_combo))
        self.style_seg = Segmented(STYLES)
        self.style_seg.changed.connect(self._style_changed)
        self.c3.add(self.style_seg)

        self.stk_list = QListWidget()
        self.stk_list.setObjectName("Stickers")
        self.stk_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.stk_list.setIconSize(QSize(42, 42))
        self.stk_list.setGridSize(QSize(54, 54))
        self.stk_list.setMovement(QListWidget.Movement.Static)
        self.stk_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.stk_list.setFixedHeight(120)
        self.stk_list.itemClicked.connect(self._sticker_changed)
        self.c3.add(self.stk_list)
        self.b_upload = button("上传码图…", "", "上传后直接用在这个码上")
        self.b_upload.clicked.connect(self._upload)
        self.c3.add(self.b_upload)

        self.block = SliderRow("颗粒", 0.004, 0.08, 1, "%", factor=100)
        self.block.editStarted.connect(self._push)
        self.block.valueChanged.connect(lambda v: self._set("block", v))
        self.c3.add(self.block)
        self.color = ColorButton()
        self.color.colorChanged.connect(self._color_changed)
        clab = QLabel("颜色")
        clab.setObjectName("Muted")
        clab.setFixedWidth(52)
        self.color_row = QWidget()
        self.color_row.setLayout(row(clab, self.color))
        self.c3.add(self.color_row)

        self.sw = SliderRow("宽度", 4, 4000, 0, " px")
        self.sh = SliderRow("高度", 4, 4000, 0, " px")
        self.srot = SliderRow("旋转", -180, 180, 0, "°")
        self.sskew = SliderRow("倾斜", -60, 60, 0, "°")
        self.sop = SliderRow("不透明", 0.1, 1.0, 0, "%", factor=100)
        for w, attr in ((self.sw, "w"), (self.sh, "h"), (self.srot, "rot"),
                        (self.sskew, "skew"), (self.sop, "opacity")):
            w.editStarted.connect(self._push)
            w.valueChanged.connect(lambda v, a=attr: self._set(a, v))
            self.c3.add(w)
        b_flip = button("水平翻转")
        b_dup = button("复制", tip="Ctrl+D")
        b_del = button("删除", "Danger", "Delete")
        b_flip.clicked.connect(self._flip)
        b_dup.clicked.connect(mw.duplicate_layer)
        b_del.clicked.connect(mw.delete_layer)
        self.c3.add(row(b_flip, b_dup, b_del))
        b_def = button("把这个码的样式设为该部位默认")
        b_def.clicked.connect(mw.set_layer_as_default)
        self.c3.add(b_def)

        # 本图操作
        c4 = Card("本图操作")
        self.b_redetect = button("重新识别本图")
        self.b_redetect.clicked.connect(lambda: mw.detect(mode="current"))
        self.b_prev = button("沿用上一张的码")
        self.b_prev.clicked.connect(mw.copy_prev_layers)
        b_clear = button("清空本图的码", "Danger")
        b_clear.clicked.connect(mw.clear_layers)
        b_undo = button("撤销", tip="Ctrl+Z")
        b_redo = button("重做", tip="Ctrl+Y")
        b_undo.clicked.connect(mw.undo)
        b_redo.clicked.connect(mw.redo)
        c4.add(row(self.b_redetect, self.b_prev))
        c4.add(row(b_undo, b_redo, b_clear))
        b_ok = button("确认并下一张", "Primary", "Enter")
        b_ok.clicked.connect(mw.confirm_next)
        c4.add(b_ok)

        c5 = Card("操作提示")
        c5.add(muted(
            "拖动码：移动　·　拖四个角：缩放（按住 Shift 等比）\n"
            "拖顶部圆点：旋转（按住 Shift 每次 15°）\n"
            "滚轮：缩放画面　·　Shift+滚轮：缩放选中的码　·　Alt+滚轮：旋转选中的码\n"
            "右键或中键拖动：平移画面　·　按住空格：看原图\n"
            "方向键：微调选中的码，没选中时切换图片\n"
            "Ctrl+Z / Ctrl+Y 撤销重做　·　Ctrl+D 复制　·　Delete 删除　·　Enter 确认并下一张"))

        area, _ = scroll_page(c1, c2, self.c3, c4, c5)
        from PySide6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(area)
        self.reload_stickers()
        self.refresh()

    # ---- 刷新 ----
    def reload_stickers(self):
        lib = self.mw.library
        self.stk_list.clear()
        for sid, name in lib.items():
            it = QListWidgetItem(QIcon(QPixmap.fromImage(lib.image(sid))), "")
            it.setToolTip(name)
            it.setData(Qt.ItemDataRole.UserRole, sid)
            self.stk_list.addItem(it)

    def refresh(self):
        mw = self.mw
        if not hasattr(mw, "canvas"):
            return
        doc = mw.cur_doc()
        L = mw.canvas.selected_layer()
        self._loading = True
        for k, b in self.part_btns.items():
            b.setCheckable(True)
            b.setChecked(k == mw.active_part)
        self.layer_list.clear()
        if doc:
            for i, l in enumerate(doc.layers):
                txt = f"{i + 1}.  {PART_NAMES.get(l.part, l.part)}　{STYLE_NAMES.get(l.style, '')}"
                if l.auto:
                    txt += f"　· 自动 {int(l.score * 100)}%"
                it = QListWidgetItem(txt)
                it.setData(Qt.ItemDataRole.UserRole, l.id)
                self.layer_list.addItem(it)
                if L and l.id == L.id:
                    it.setSelected(True)
        has = bool(doc and doc.layers)
        self.layer_list.setVisible(has)
        self.no_layers.setVisible(not has)
        self.b_redetect.setEnabled(bool(doc) and not mw.busy)
        prev = mw.prev_doc()
        self.b_prev.setEnabled(bool(prev and prev.layers))

        self.c3.setVisible(L is not None)
        if L is not None:
            self.part_combo.setCurrentIndex(max(0, self.part_combo.findData(L.part)))
            self.style_seg.set_value(L.style)
            self.stk_list.setVisible(L.style == "sticker")
            self.b_upload.setVisible(L.style == "sticker")
            self.block.setVisible(L.style in ("mosaic", "blur"))
            self.block.lbl.setText("颗粒" if L.style == "mosaic" else "强度")
            self.color_row.setVisible(L.style == "solid")
            self.color.set_color(L.color)
            for i in range(self.stk_list.count()):
                it = self.stk_list.item(i)
                it.setSelected(it.data(Qt.ItemDataRole.UserRole) == L.sticker)
            self.block.set_value(L.block)
            m = max(doc.w, doc.h, 100) * 1.2 if doc else 4000
            self.sw.set_range(4, m)
            self.sh.set_range(4, m)
            self.sop.set_value(L.opacity)
            self.sync_geometry()
        self._loading = False

    def sync_geometry(self):
        L = self.mw.canvas.selected_layer()
        if not L:
            return
        self.sw.set_value(L.w)
        self.sh.set_value(L.h)
        self.srot.set_value(L.rot)
        self.sskew.set_value(L.skew)

    # ---- 编辑 ----
    def _pick_layer(self, it):
        self.mw.canvas.select(it.data(Qt.ItemDataRole.UserRole))

    def _push(self):
        if not self._loading:
            self.mw.begin_edit()

    def _set(self, attr, v):
        if self._loading:
            return
        self.mw.edit_layer(lambda L: setattr(L, attr, v), push=False)

    def _part_changed(self, _i):
        if self._loading:
            return
        key = self.part_combo.currentData()
        self.mw.edit_layer(lambda L: setattr(L, "part", key), rebuild_panel=True)

    def _style_changed(self, key):
        if self._loading:
            return
        self.mw.edit_layer(lambda L: setattr(L, "style", key), rebuild_panel=True)

    def _sticker_changed(self, it):
        if self._loading:
            return
        sid = it.data(Qt.ItemDataRole.UserRole)
        self.mw.edit_layer(lambda L: setattr(L, "sticker", sid))

    def _upload(self):
        sid = self.mw.upload_stickers()
        if sid:
            self.mw.edit_layer(lambda L: setattr(L, "sticker", sid), rebuild_panel=True)

    def _color_changed(self, c):
        self.mw.edit_layer(lambda L: setattr(L, "color", c))

    def _flip(self):
        self.mw.edit_layer(lambda L: setattr(L, "flip", not L.flip))


# ---------------------------------------------------------------- 导出
class ExportPanel(QWidget):
    MODES = [("none", "保持原尺寸"), ("long", "按长边"), ("width", "按宽度"),
             ("height", "按高度"), ("percent", "按百分比")]

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        ex = mw.cfg["export"]
        self._loading = True

        c1 = Card("保存位置")
        self.dir_edit = QLineEdit(ex.get("dir", ""))
        self.dir_edit.setPlaceholderText("选择输出文件夹")
        self.dir_edit.editingFinished.connect(self._dir_changed)
        b_dir = button("浏览…")
        b_dir.clicked.connect(mw.choose_out_dir)
        c1.add(row(self.dir_edit, b_dir))
        self.scope = Segmented([("all", "全部图片"), ("confirmed", "仅已确认")])
        self.scope.changed.connect(lambda k: self._set("scope", k))
        c1.add(self.scope)

        c2 = Card("调整尺寸")
        self.mode = QComboBox()
        for k, n in self.MODES:
            self.mode.addItem(n, k)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.value = QSpinBox()
        self.value.setRange(1, 20000)
        self.value.valueChanged.connect(lambda v: self._set("value", v))
        c2.add(row(self.mode, self.value))
        self.no_up = QCheckBox("小图不放大")
        self.no_up.toggled.connect(lambda on: self._set("no_upscale", on))
        c2.add(self.no_up)

        c3 = Card("格式")
        self.fmt = Segmented([("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")])
        self.fmt.changed.connect(self._fmt_changed)
        c3.add(self.fmt)
        self.quality = SliderRow("质量", 50, 100, 0)
        self.quality.valueChanged.connect(lambda v: self._set("quality", int(v)))
        c3.add(self.quality)

        c4 = Card("文件名")
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("前缀")
        self.suffix = QLineEdit()
        self.suffix.setPlaceholderText("后缀")
        self.prefix.textChanged.connect(lambda t: self._set("prefix", t))
        self.suffix.textChanged.connect(lambda t: self._set("suffix", t))
        c4.add(row(self.prefix, self.suffix))
        self.overwrite = QCheckBox("同名文件直接覆盖（不勾选则自动加编号）")
        self.overwrite.toggled.connect(lambda on: self._set("overwrite", on))
        c4.add(self.overwrite)
        self.open_after = QCheckBox("导出完成后打开文件夹")
        self.open_after.toggled.connect(lambda on: self._set("open_after", on))
        c4.add(self.open_after)
        self.preview = muted("")
        c4.add(self.preview)

        c5 = Card("开始导出")
        c5.add(muted("先按原图打码，再缩放到目标尺寸，码不会变糊。原图不会被修改。"))
        self.warn = muted("", "Warn")
        c5.add(self.warn)
        self.b_batch = button("批量导出", "Primary", "Ctrl+E")
        self.b_batch.setMinimumHeight(40)
        self.b_batch.clicked.connect(mw.export_batch)
        self.b_one = button("只导出当前图片")
        self.b_one.clicked.connect(mw.export_current)
        c5.add(self.b_batch)
        c5.add(self.b_one)

        area, _ = scroll_page(c1, c2, c3, c4, c5)
        from PySide6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(area)
        self.load()

    def load(self):
        ex = self.mw.cfg["export"]
        self._loading = True
        self.dir_edit.setText(ex.get("dir", ""))
        self.scope.set_value(ex.get("scope", "all"))
        self.mode.setCurrentIndex(max(0, self.mode.findData(ex.get("mode", "long"))))
        self.value.setValue(int(ex.get("value", 1600)))
        self.no_up.setChecked(bool(ex.get("no_upscale", True)))
        self.fmt.set_value(ex.get("format", "jpg"))
        self.quality.set_value(ex.get("quality", 92))
        self.prefix.setText(ex.get("prefix", ""))
        self.suffix.setText(ex.get("suffix", ""))
        self.overwrite.setChecked(bool(ex.get("overwrite", False)))
        self.open_after.setChecked(bool(ex.get("open_after", True)))
        self._loading = False
        self._update_ui()

    def _set(self, key, v):
        if self._loading:
            return
        self.mw.cfg["export"][key] = v
        self.mw.cfg.save()
        self._update_ui()

    def _dir_changed(self):
        self._set("dir", self.dir_edit.text().strip())
        self.mw.batch_panel.refresh()

    def _mode_changed(self, _i):
        if self._loading:
            return
        k = self.mode.currentData()
        ex = self.mw.cfg["export"]
        if k == "percent" and ex.get("value", 0) > 400:
            self.value.setValue(50)
        elif k not in ("percent", "none") and ex.get("value", 0) <= 100:
            self.value.setValue(1600)
        self._set("mode", k)

    def _fmt_changed(self, k):
        self._set("format", k)

    def _update_ui(self):
        ex = self.mw.cfg["export"]
        mode = ex.get("mode", "long")
        self.value.setEnabled(mode != "none")
        self.value.setSuffix(" %" if mode == "percent" else " px")
        self.quality.setVisible(ex.get("format") != "png")
        doc = self.mw.cur_doc()
        if doc and doc.w:
            _, W, H = compute_size(doc.w, doc.h, ex)
            self.preview.setText(f"当前图片：{output_name(doc, ex)}\n{doc.w}×{doc.h} → {W}×{H}")
        else:
            self.preview.setText("")
        docs = self.mw.export_targets()
        no_mask = sum(1 for d in docs if not d.layers)
        self.warn.setText(f"其中 {no_mask} 张图片没有码，会原样输出。" if no_mask else "")
        self.warn.setVisible(bool(no_mask))
        self.b_batch.setText(f"批量导出 {len(docs)} 张" if docs else "批量导出")
        self.b_batch.setEnabled(bool(docs) and not self.mw.busy)
        self.b_one.setEnabled(bool(doc) and not self.mw.busy)

    def refresh(self):
        self._update_ui()
