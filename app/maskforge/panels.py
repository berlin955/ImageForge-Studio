"""左侧功能区（一列从上到下：素材 → 一键打码 → 当前图片 → 选中的码 → 码的样式）和导出设置窗口。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .config import PARTS, PART_NAMES, STYLE_NAMES, STYLES
from .exporter import compute_size, output_name
from .widgets import (Card, ColorButton, Segmented, SliderRow, button, muted, row,
                      scroll_page)

MAIN_PARTS = [p for p in PARTS if p[0] != "custom"]


class Section(QFrame):
    """可以折叠的分组。"""

    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.head = QPushButton()
        self.head.setObjectName("SectionHead")
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.clicked.connect(self.toggle)
        self.extra = QLabel("")
        self.extra.setObjectName("Count")
        head.addWidget(self.head, 1)
        head.addWidget(self.extra)
        v.addLayout(head)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        v.addWidget(self.body)
        self._title = title
        self.set_collapsed(collapsed)

    def set_title(self, t: str):
        self._title = t
        self._paint()

    def _paint(self):
        self.head.setText(("▸  " if self.collapsed else "▾  ") + self._title)

    def set_collapsed(self, c: bool):
        self.collapsed = c
        self.body.setVisible(not c)
        self._paint()

    def toggle(self):
        self.set_collapsed(not self.collapsed)

    def add(self, w):
        if isinstance(w, QWidget):
            self.lay.addWidget(w)
        else:
            self.lay.addLayout(w)
        return w


def _label(text: str, width: int = 52) -> QLabel:
    l = QLabel(text)
    l.setObjectName("Muted")
    l.setFixedWidth(width)
    return l


class SidePanel(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------------------------------------------------ 没有图片时：大号导入区
        self.drop = QFrame()
        self.drop.setObjectName("Drop")
        dv = QVBoxLayout(self.drop)
        dv.setContentsMargins(20, 26, 20, 22)
        dv.setSpacing(10)
        t = QLabel("导入模特图片")
        t.setObjectName("Hero")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(t)
        d2 = muted("把图片或整个文件夹拖进来，\n或者点下面的按钮选择。")
        d2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(d2)
        b1 = button("选择图片…", "Primary", "Ctrl+O")
        b1.setMinimumHeight(40)
        b1.clicked.connect(mw.import_dialog)
        b2 = button("选择文件夹…")
        b2.clicked.connect(mw.import_folder_dialog)
        dv.addWidget(b1)
        dv.addWidget(b2)

        # ------------------------------------------------ 素材（有图片时）
        self.s_files = Section("素材")
        self.files_lbl = QLabel("")
        self.files_lbl.setStyleSheet("font-size:15px;font-weight:700")
        bi = button("＋ 图片")
        bi.clicked.connect(mw.import_dialog)
        bd = button("＋ 文件夹")
        bd.clicked.connect(mw.import_folder_dialog)
        self.s_files.add(row(self.files_lbl, None, bi, bd))
        brm = button("移出当前图片", "Ghost")
        brm.clicked.connect(mw.remove_current)
        bcl = button("清空列表", "Ghost")
        bcl.clicked.connect(mw.clear_all)
        self.s_files.add(row(brm, bcl, None))

        # ------------------------------------------------ 一键打码
        self.s_auto = Section("一键打码")
        self.part_checks = {}
        pr = QHBoxLayout()
        pr.setSpacing(14)
        for k, n in MAIN_PARTS:
            cb = QCheckBox(n)
            cb.toggled.connect(lambda on, key=k: self._part_set(key, "enabled", on))
            self.part_checks[k] = cb
            pr.addWidget(cb)
        pr.addStretch(1)
        self.s_auto.add(pr)
        self.sens = SliderRow("灵敏度", 20, 90, 0, "%")
        self.sens.valueChanged.connect(self._sens_changed)
        self.s_auto.add(self.sens)
        self.b_auto = button("一键打码", "Primary")
        self.b_auto.setMinimumHeight(42)
        self.b_auto.clicked.connect(mw.auto_mask)
        self.s_auto.add(self.b_auto)
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog_txt = muted("")
        self.b_stop = button("停止", "Ghost")
        self.b_stop.clicked.connect(mw.stop_detect)
        self.prog_box = QWidget()
        pv = QVBoxLayout(self.prog_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(6)
        pv.addWidget(self.prog)
        pv.addLayout(row(self.prog_txt, None, self.b_stop))
        self.prog_box.hide()
        self.s_auto.add(self.prog_box)
        self.b_redo_all = button("全部重新识别", "Ghost", "换了码的大小或样式后，用这个让所有图片重新打码")
        self.b_redo_all.clicked.connect(lambda: mw.detect(mode="all", then=mw.open_preview))
        self.auto_hint = muted("")
        self.s_auto.add(row(self.auto_hint, None, self.b_redo_all))

        # ------------------------------------------------ 当前图片
        self.s_img = Section("当前图片")
        g = QGridLayout()
        g.setSpacing(6)
        self.add_btns = {}
        for i, (k, n) in enumerate(PARTS):
            b = button(f"＋ {n}", "Chip", "添加到图片中间；也可以先点这里，再双击图片上的位置")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, key=k: mw.add_layer(key))
            self.add_btns[k] = b
            g.addWidget(b, 0, i)
        self.s_img.add(g)
        self.layer_list = QListWidget()
        self.layer_list.setObjectName("Layers")
        self.layer_list.itemClicked.connect(lambda it: mw.canvas.select(it.data(Qt.ItemDataRole.UserRole)))
        self.no_layers = muted("这张图还没有码。点「一键打码」自动识别，或者用上面的按钮手动添加。")
        self.s_img.add(self.layer_list)
        self.s_img.add(self.no_layers)
        self.b_redetect = button("重新识别本图")
        self.b_redetect.clicked.connect(lambda: mw.detect(mode="current"))
        self.b_prev = button("沿用上一张")
        self.b_prev.clicked.connect(mw.copy_prev_layers)
        self.s_img.add(row(self.b_redetect, self.b_prev))
        b_undo = button("↶ 撤销", "Ghost", "Ctrl+Z")
        b_undo.clicked.connect(mw.undo)
        b_redo = button("↷ 重做", "Ghost", "Ctrl+Y")
        b_redo.clicked.connect(mw.redo)
        b_clear = button("清空本图", "Ghost")
        b_clear.clicked.connect(mw.clear_layers)
        self.s_img.add(row(b_undo, b_redo, None, b_clear))

        # ------------------------------------------------ 选中的码
        self.s_layer = Section("选中的码")
        self.part_combo = QComboBox()
        for k, n in PARTS:
            self.part_combo.addItem(n, k)
        self.part_combo.currentIndexChanged.connect(self._part_changed)
        self.s_layer.add(row(_label("部位"), self.part_combo))
        self.style_seg = Segmented(STYLES)
        self.style_seg.changed.connect(self._style_changed)
        self.s_layer.add(self.style_seg)
        self.stk_list = QListWidget()
        self.stk_list.setObjectName("Stickers")
        self.stk_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.stk_list.setIconSize(QSize(40, 40))
        self.stk_list.setGridSize(QSize(52, 52))
        self.stk_list.setMovement(QListWidget.Movement.Static)
        self.stk_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.stk_list.setFixedHeight(112)
        self.stk_list.itemClicked.connect(self._sticker_changed)
        self.s_layer.add(self.stk_list)
        self.b_upload = button("上传码图…", "Ghost", "上传后直接用在这个码上")
        self.b_upload.clicked.connect(self._upload_for_layer)
        self.s_layer.add(self.b_upload)
        self.block = SliderRow("颗粒", 0.004, 0.08, 1, "%", factor=100)
        self.block.editStarted.connect(self._push)
        self.block.valueChanged.connect(lambda v: self._set("block", v))
        self.s_layer.add(self.block)
        self.color = ColorButton()
        self.color.colorChanged.connect(lambda c: mw.edit_layer(lambda L: setattr(L, "color", c)))
        self.color_row = QWidget()
        self.color_row.setLayout(row(_label("颜色"), self.color))
        self.s_layer.add(self.color_row)
        self.sw = SliderRow("宽度", 4, 4000, 0, " px")
        self.sh = SliderRow("高度", 4, 4000, 0, " px")
        self.srot = SliderRow("旋转", -180, 180, 0, "°")
        self.sskew = SliderRow("倾斜", -60, 60, 0, "°")
        self.sop = SliderRow("不透明", 0.1, 1.0, 0, "%", factor=100)
        for w, attr in ((self.sw, "w"), (self.sh, "h"), (self.srot, "rot"),
                        (self.sskew, "skew"), (self.sop, "opacity")):
            w.editStarted.connect(self._push)
            w.valueChanged.connect(lambda v, a=attr: self._set(a, v))
            self.s_layer.add(w)
        b_flip = button("翻转")
        b_flip.clicked.connect(lambda: mw.edit_layer(lambda L: setattr(L, "flip", not L.flip)))
        b_dup = button("复制", tip="Ctrl+D")
        b_dup.clicked.connect(mw.duplicate_layer)
        b_del = button("删除", "Danger", "Delete")
        b_del.clicked.connect(mw.delete_layer)
        self.s_layer.add(row(b_flip, b_dup, b_del))
        b_def = button("设为这个部位的默认样式", "Ghost")
        b_def.clicked.connect(mw.set_layer_as_default)
        self.s_layer.add(b_def)
        self.s_layer.add(muted("旋转：拖码上方的圆形按钮，或者按住四个角外面一点点拖；"
                               "[ / ] 键每次转 5°（Shift 1°），Alt+滚轮也能转；双击圆形按钮摆正。"))

        # ------------------------------------------------ 码的样式（默认折叠）
        self.s_style = Section("码的样式", collapsed=True)
        self.s_style.add(muted("一键打码给每个部位用什么码。点「上传」换成你自己的码图，透明背景的 PNG 最好。"))
        sg = QGridLayout()
        sg.setHorizontalSpacing(6)
        sg.setVerticalSpacing(6)
        sg.setColumnStretch(2, 1)
        self.style_combos, self.stk_combos, self.previews = {}, {}, {}
        for i, (k, n) in enumerate(MAIN_PARTS):
            r = i * 2
            pvw = QLabel()
            pvw.setFixedSize(40, 40)
            pvw.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pvw.setObjectName("StickerPreview")
            name = QLabel(n)
            name.setStyleSheet("font-weight:600")
            st = QComboBox()
            for sk, sn in STYLES:
                st.addItem(sn, sk)
            st.setFixedWidth(84)
            st.currentIndexChanged.connect(lambda _i, key=k: self._style_default_changed(key))
            sc = QComboBox()
            sc.setIconSize(QSize(20, 20))
            sc.currentIndexChanged.connect(lambda _i, key=k: self._sticker_default_changed(key))
            up = button("上传", "", f"上传一张码图，{n}改用这张图")
            up.clicked.connect(lambda _=False, key=k: self._upload_for(key))
            sg.addWidget(pvw, r, 0, 2, 1)
            sg.addWidget(name, r, 1, 1, 3)
            sg.addWidget(st, r + 1, 1)
            sg.addWidget(sc, r + 1, 2)
            sg.addWidget(up, r + 1, 3)
            self.style_combos[k], self.stk_combos[k], self.previews[k] = st, sc, pvw
        self.s_style.add(sg)
        b_apply = button("换到已经打好的码上")
        b_apply.clicked.connect(lambda: [mw.apply_part_style(k) for k, _ in MAIN_PARTS])
        b_more = button("更多选项…", "Ghost", "码的大小、颗粒、有遮挡时是否打码")
        b_more.clicked.connect(lambda: mw.open_settings(page=1))
        self.s_style.add(row(b_apply, None, b_more))

        area, v = scroll_page(self.drop, self.s_files, self.s_auto, self.s_img, self.s_layer, self.s_style)
        v.setSpacing(10)
        outer.addWidget(area, 1)

        # ------------------------------------------------ 底部固定操作区
        foot = QFrame()
        foot.setObjectName("SideFoot")
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(14, 10, 14, 12)
        fv.setSpacing(8)
        self.foot_stat = muted("")
        fv.addWidget(self.foot_stat)
        self.b_preview = button("预览全部")
        self.b_preview.clicked.connect(mw.open_preview)
        self.b_ok = button("没问题，看下一张需要注意的", tip="Enter")
        self.b_ok.clicked.connect(mw.confirm_next)
        fv.addLayout(row(self.b_preview, self.b_ok))
        self.b_export = button("导出", "Primary", "Ctrl+E")
        self.b_export.setMinimumHeight(40)
        self.b_export.clicked.connect(mw.export_batch)
        self.b_exset = button("导出设置", "", "保存位置、尺寸、格式、文件名")
        self.b_exset.setMinimumHeight(40)
        self.b_exset.clicked.connect(mw.open_export_settings)
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(self.b_export, 1)
        h.addWidget(self.b_exset)
        fv.addLayout(h)
        outer.addWidget(foot)

        self.reload_stickers()
        self.sync_from_cfg()

    # ================================================= 刷新
    def refresh(self):
        mw = self.mw
        if not hasattr(mw, "canvas"):
            return
        docs = mw.docs
        n = len(docs)
        has = n > 0
        self.drop.setVisible(not has)
        for s in (self.s_files, self.s_auto, self.s_img):
            s.setVisible(has)
        from .mainwindow import count_status
        cnt = count_status(docs)
        self.files_lbl.setText(f"{n} 张图片")
        pending = cnt["todo"]
        busy = mw.busy
        self.b_auto.setText(f"一键打码  ·  {pending} 张未处理" if pending else "一键打码")
        self.b_auto.setEnabled(has and not busy and pending > 0)
        self.b_redo_all.setEnabled(has and not busy)
        self.auto_hint.setText("全部已打码" if has and not pending else "")
        self.s_auto.extra.setText(f"{n - pending}/{n}" if has else "")

        doc = mw.cur_doc()
        self.s_img.set_title(f"当前图片  {mw.cur + 1}/{n}" if doc else "当前图片")
        self.s_img.extra.setText(doc.status_text() if doc else "")
        L = mw.canvas.selected_layer()
        self.layer_list.clear()
        if doc:
            for l in doc.layers:
                txt = f"{PART_NAMES.get(l.part, l.part)}　·　{STYLE_NAMES.get(l.style, '')}"
                if l.auto:
                    txt += f"　·　自动 {int(l.score * 100)}%"
                it = QListWidgetItem(txt)
                it.setData(Qt.ItemDataRole.UserRole, l.id)
                self.layer_list.addItem(it)
                if L and l.id == L.id:
                    it.setSelected(True)
        hl = bool(doc and doc.layers)
        self.layer_list.setVisible(hl)
        self.layer_list.setFixedHeight(min(150, 40 * max(1, self.layer_list.count()) + 6))
        self.no_layers.setVisible(not hl)
        for k, b in self.add_btns.items():
            b.setChecked(k == mw.active_part)
        self.b_redetect.setEnabled(bool(doc) and not busy)
        prev = mw.prev_doc()
        self.b_prev.setEnabled(bool(prev and prev.layers))

        self.foot_stat.setText(
            (f"已打码 {cnt['done']}　·　需要注意 {cnt['attention']}"
             + (f"　·　未处理 {cnt['todo']}" if cnt["todo"] else "")) if has else "导入图片后开始")
        targets = mw.export_targets()
        self.b_export.setText(f"导出 {len(targets)} 张" if targets else "导出")
        self.b_export.setEnabled(bool(targets) and not busy)
        self.b_preview.setEnabled(has and not busy)
        self.b_ok.setEnabled(bool(doc) and cnt["attention"] > 0)
        self.refresh_selection()

    def refresh_selection(self):
        mw = self.mw
        doc = mw.cur_doc()
        L = mw.canvas.selected_layer()
        self.s_layer.setVisible(L is not None)
        if L is None:
            return
        self._loading = True
        self.s_layer.set_collapsed(False)
        self.s_layer.set_title(f"选中的码  ·  {PART_NAMES.get(L.part, L.part)}")
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
        was = self._loading
        self._loading = True
        self.sw.set_value(L.w)
        self.sh.set_value(L.h)
        self.srot.set_value(L.rot)
        self.sskew.set_value(L.skew)
        self._loading = was

    def set_progress(self, i: int, total: int, text: str):
        running = total > 0 and i < total
        self.prog_box.setVisible(running)
        if total:
            self.prog.setValue(int(i * 100 / total))
        self.prog_txt.setText(text)

    # ================================================= 选中的码
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

    def _upload_for_layer(self):
        sid = self.mw.upload_stickers()
        if sid:
            self.mw.edit_layer(lambda L: setattr(L, "sticker", sid), rebuild_panel=True)

    # ================================================= 默认样式
    def reload_stickers(self):
        lib = self.mw.library
        self._loading = True
        self.stk_list.clear()
        for sid, name in lib.items():
            it = QListWidgetItem(QIcon(QPixmap.fromImage(lib.image(sid))), "")
            it.setToolTip(name)
            it.setData(Qt.ItemDataRole.UserRole, sid)
            self.stk_list.addItem(it)
        for k, sc in self.stk_combos.items():
            sc.clear()
            for sid, name in lib.items():
                sc.addItem(QIcon(QPixmap.fromImage(lib.image(sid))), name, sid)
            sc.setCurrentIndex(max(0, sc.findData(self.mw.cfg.part(k)["sticker"])))
        self._loading = False
        for k, _ in MAIN_PARTS:
            self._update_style_row(k)

    def sync_from_cfg(self):
        cfg = self.mw.cfg
        self._loading = True
        for k, _n in MAIN_PARTS:
            p = cfg.part(k)
            self.part_checks[k].setChecked(p.get("enabled", True))
            self.style_combos[k].setCurrentIndex(max(0, self.style_combos[k].findData(p["style"])))
            self.stk_combos[k].setCurrentIndex(max(0, self.stk_combos[k].findData(p["sticker"])))
        self.sens.set_value(round((1 - cfg["detect"]["threshold"]) * 100))
        self._loading = False
        for k, _ in MAIN_PARTS:
            self._update_style_row(k)
        self.refresh()

    def _update_style_row(self, k):
        p = self.mw.cfg.part(k)
        style = p["style"]
        on = p.get("enabled", True)
        self.style_combos[k].setEnabled(on)
        self.stk_combos[k].setEnabled(on and style == "sticker")
        pv = self.previews[k]
        if style == "sticker":
            img = self.mw.library.image(p["sticker"])
            pv.setPixmap(QPixmap.fromImage(img).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
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
        self._update_style_row(key)

    def _style_default_changed(self, key):
        self._part_set(key, "style", self.style_combos[key].currentData())

    def _sticker_default_changed(self, key):
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
        p.update(style="sticker", sticker=sid, enabled=True)
        self.mw.cfg.save()
        self.reload_stickers()
        self.sync_from_cfg()
        self.mw.status.showMessage(f"{PART_NAMES.get(key, key)}已改用你上传的码图", 5000)


# ---------------------------------------------------------------- 导出设置
class ExportDialog(QDialog):
    MODES = [("none", "保持原尺寸"), ("long", "按长边"), ("width", "按宽度"),
             ("height", "按高度"), ("percent", "按百分比")]

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle("导出设置")
        self.resize(540, 740)
        self._loading = True

        c1 = Card("保存位置")
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择输出文件夹")
        self.dir_edit.editingFinished.connect(lambda: self._set("dir", self.dir_edit.text().strip()))
        b_dir = button("浏览…")
        b_dir.clicked.connect(self._choose_dir)
        c1.add(row(self.dir_edit, b_dir))
        self.scope = Segmented([("all", "全部图片"), ("skip_attention", "跳过需要注意的")])
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
        self.fmt.changed.connect(lambda k: self._set("format", k))
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

        area, _ = scroll_page(c1, c2, c3, c4)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(area, 1)
        foot = QFrame()
        foot.setObjectName("SideFoot")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(16, 10, 16, 12)
        self.warn = muted("", "Warn")
        fh.addWidget(self.warn, 1)
        b_close = button("完成")
        b_close.clicked.connect(self.accept)
        self.b_one = button("只导出当前")
        self.b_one.clicked.connect(lambda: self._go(self.mw.export_current))
        self.b_all = button("导出", "Primary")
        self.b_all.setMinimumWidth(120)
        self.b_all.clicked.connect(lambda: self._go(self.mw.export_batch))
        fh.addWidget(b_close)
        fh.addWidget(self.b_one)
        fh.addWidget(self.b_all)
        v.addWidget(foot)
        self.load()

    def _go(self, fn):
        self.accept()
        fn()

    def _choose_dir(self):
        if self.mw.choose_out_dir():
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
        self._update()

    def _set(self, key, v):
        if self._loading:
            return
        self.mw.cfg["export"][key] = v
        self.mw.cfg.save()
        self._update()
        self.mw.side.refresh()

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

    def _update(self):
        ex = self.mw.cfg["export"]
        mode = ex.get("mode", "long")
        self.value.setEnabled(mode != "none")
        self.value.setSuffix(" %" if mode == "percent" else " px")
        self.quality.setVisible(ex.get("format") != "png")
        doc = self.mw.cur_doc()
        if doc and doc.w:
            _, W, H = compute_size(doc.w, doc.h, ex)
            self.preview.setText(f"例如：{output_name(doc, ex)}　{doc.w}×{doc.h} → {W}×{H}")
        else:
            self.preview.setText("")
        docs = self.mw.export_targets()
        no_mask = sum(1 for d in docs if not d.layers)
        self.warn.setText(f"{no_mask} 张没有码，会原样导出" if no_mask else "")
        self.b_all.setText(f"导出 {len(docs)} 张" if docs else "导出")
        self.b_all.setEnabled(bool(docs) and not self.mw.busy)
        self.b_one.setEnabled(bool(doc) and not self.mw.busy)
