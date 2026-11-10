"""「字符」面板：参考 PS 的字符窗口。

- 字体列表直接用你这段字预览（看着挑），按 宋体类 / 黑体类 / 书法艺术字 / 电脑自带 分组
- 粗细单独选（思源、普惠体都有好几档粗细）
- 字号、字距：可以输入、拖滑块，也可以按住「字号」「字距」这几个字左右拖动（PS 的「拖动调整」）
- 颜色：选色或用吸管从原图上吸
- 对齐：改字后以原来那行字为准往左 / 居中 / 往右伸
- 原图 / 现在 对比：改的时候随时看像不像
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QListView, QMenu, QSizePolicy,
                               QSlider, QStyle, QStyledItemDelegate, QStyleOptionComboBox, QStylePainter,
                               QToolButton, QVBoxLayout, QWidget)

from . import fonts
from .widgets import ColorButton, Segmented, button, muted



class ScrubLabel(QLabel):
    """按住左右拖就能调数值的标签（PS 里字号前面那个小图标）。"""

    def __init__(self, text: str, spin: QDoubleSpinBox, step: float = 0.5):
        super().__init__(text)
        self.spin = spin
        self.step = step
        self._x0 = None
        self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.setToolTip("按住左右拖动可以调大调小（按住 Shift 拖得更快）")
        self.setMinimumWidth(30)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._x0 = (e.globalPosition().x(), self.spin.value())

    def mouseMoveEvent(self, e):
        if self._x0 is None:
            return
        x0, v0 = self._x0
        k = 4 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        self.spin.setValue(v0 + (e.globalPosition().x() - x0) * self.step * k)

    def mouseReleaseEvent(self, e):
        self._x0 = None


def _label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setMinimumWidth(30)
    return lb


class FontPicker(QComboBox):
    """字体家族下拉框：展开后每一项都用这个字体把「名字 + 你这段字」画出来，一眼看出像不像。
    收起时只显示字体名（侧边栏窄）。"""
    picked = Signal(str)              # 家族 key

    def __init__(self):
        super().__init__()
        lv = QListView()
        lv.setItemDelegate(QStyledItemDelegate(lv))
        lv.setMinimumWidth(300)
        lv.setUniformItemSizes(False)
        self.setView(lv)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaxVisibleItems(14)
        self.groups: dict[str, dict] = {}
        self._sample = None
        self._busy = False
        self.activated.connect(self._on_activated)

    def rebuild(self, sample: str):
        sample = (sample or "").strip()[:10] or "字体 Aa 123"
        if sample == self._sample and self.count():
            return
        self._sample = sample
        self._busy = True
        cur = self.currentData()
        self.clear()
        self.groups = {}
        last_cat = None
        for g in fonts.group_list() + fonts.system_groups():
            cat = "sys" if g.get("system") else g["cat"]
            if cat != last_cat:
                self.addItem(f"—— {fonts.CAT_NAMES.get(cat, cat)} ——")
                it = self.model().item(self.count() - 1)
                it.setEnabled(False)
                it.setSelectable(False)
                last_cat = cat
            self.groups[g["key"]] = g
            w = min(g["weights"], key=lambda x: abs(x - 400))
            f = fonts.qfont(g["weights"][w], w, g["cat"])
            f.setPixelSize(17)
            self.addItem(f"{g['name']}　{sample}", g["key"])
            self.setItemData(self.count() - 1, f, Qt.ItemDataRole.FontRole)
            self.setItemData(self.count() - 1, g["name"], Qt.ItemDataRole.ToolTipRole)
        i = self.findData(cur) if cur is not None else -1
        self.setCurrentIndex(i)
        self._busy = False

    def paintEvent(self, e):
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        g = self.groups.get(self.currentData())
        opt.currentText = g["name"] if g else "（选择字体）"
        opt.currentIcon = QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)

    def set_group(self, key: str | None):
        self._busy = True
        i = self.findData(key) if key else -1
        self.setCurrentIndex(i)
        self._busy = False
        self.update()

    def _on_activated(self, i):
        if self._busy:
            return
        key = self.itemData(i)
        if key:
            self.picked.emit(key)


class CharPanel(QWidget):
    """改动通过 page.set_text_props({...}) 交给页面。"""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.t: dict | None = None
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(7)

        self.hint = muted("在画布上点一段字（或点上面的文字行）就能调字体、字号、颜色；双击画布上的字可以直接改。")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.compare = QLabel()
        self.compare.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.compare.setToolTip("上：原图　下：现在的样子")
        self.compare.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        v.addWidget(self.compare)

        self.box = QWidget()
        b = QVBoxLayout(self.box)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(7)

        self.picker = FontPicker()
        self.picker.picked.connect(self._pick_group)
        b.addLayout(self._row(_label("字体"), self.picker))

        self.weight = QComboBox()
        self.weight.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.weight.activated.connect(self._pick_weight)
        self.italic = QToolButton()
        self.italic.setText("斜体")
        self.italic.setCheckable(True)
        self.italic.toggled.connect(lambda on: self._emit({"italic": bool(on)}))
        b.addLayout(self._row(_label("粗细"), self.weight, self.italic))

        self.size = QDoubleSpinBox()
        self.size.setRange(4, 600)
        self.size.setDecimals(1)
        self.size.setSingleStep(1)
        self.size.setSuffix(" px")
        self.size.setKeyboardTracking(False)
        self.size.valueChanged.connect(self._size_changed)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(4, 300)
        self.size_slider.valueChanged.connect(lambda v: self._loading or self.size.setValue(float(v)))
        b.addLayout(self._row(ScrubLabel("字号", self.size, 0.25), self.size, self.size_slider))

        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(-60, 300)
        self.spacing.setDecimals(1)
        self.spacing.setSingleStep(0.5)
        self.spacing.setSuffix(" px")
        self.spacing.setKeyboardTracking(False)
        self.spacing.valueChanged.connect(lambda val: self._emit({"spacing": float(val)}))
        self.b_fit = QToolButton()
        self.b_fit.setText("对齐原宽")
        self.b_fit.setToolTip("自动调字距，让这行字和原图那行一样宽")
        self.b_fit.clicked.connect(self._fit_width)
        b.addLayout(self._row(ScrubLabel("字距", self.spacing, 0.1), self.spacing, self.b_fit))

        self.color = ColorButton("#000000")
        self.color.colorChanged.connect(lambda c: self._emit({"color": c}))
        self.color.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.dropper = QToolButton()
        self.dropper.setText("吸管")
        self.dropper.setCheckable(True)
        self.dropper.setToolTip("点一下，再到画布上点原图里的颜色")
        self.dropper.toggled.connect(self.page.set_eyedropper)
        b.addLayout(self._row(_label("颜色"), self.color, self.dropper))

        self.align = Segmented([("left", "靠左"), ("center", "居中"), ("right", "靠右")])
        self.align.changed.connect(lambda k: self._emit({"align": k}))
        self.align.setToolTip("改字以后，以原来那行字为准往哪边伸")
        b.addLayout(self._row(_label("对齐"), self.align))

        self.b_reset = button("恢复原样", "Ghost", "字体、字号、颜色、位置恢复成识别出来的样子（文字内容不变）")
        self.b_reset.clicked.connect(self._reset)
        self.b_apply = button("应用到…", "Ghost", "把这段字的字体、粗细用到其他文字上")
        self.b_apply.clicked.connect(self._apply_menu)
        b.addLayout(self._row(self.b_reset, self.b_apply))
        b.addWidget(muted("快捷键：方向键微调位置（Shift 一次 10 像素）；Ctrl+Shift+> / < 调大调小字号；"
                          "回车或双击直接改字；拖文字框的四个角整体缩放。"))
        v.addWidget(self.box)

        self.dl = QWidget()
        dl = QVBoxLayout(self.dl)
        dl.setContentsMargins(0, 4, 0, 0)
        dl.setSpacing(6)
        dl.addWidget(muted("还没有下载字体包。下载后自动给每段字配上和原图最像的字体"
                           "（思源宋体、思源黑体、阿里巴巴普惠体等，免费商用）。"))
        b_dl = button("下载字体包", "", "只下载一次")
        b_dl.clicked.connect(self.page.download_fonts)
        dl.addWidget(b_dl)
        v.addWidget(self.dl)
        self.load(None)

    @staticmethod
    def _row(*ws) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for w in ws:
            h.addWidget(w)
        return h

    # ---------------------------------------------------------------- 显示
    def load(self, t: dict | None):
        self.t = t
        self._loading = True
        on = t is not None
        self.box.setEnabled(on)
        self.hint.setVisible(not on)
        self.compare.setVisible(on)
        self.dl.setVisible(bool(fonts.PACK_SHA256) and not fonts.has_pack())
        if on:
            self.picker.rebuild(t.get("text", ""))
            info = fonts.stem_info(t.get("font"))
            gkey = info["group"] if info else (t.get("font") if (t.get("font") or "").startswith("sys:") else None)
            self.picker.set_group(gkey)
            self._fill_weights(gkey, t.get("font"))
            self.italic.setChecked(bool(t.get("italic")))
            self.size.setValue(float(t.get("size", 24)))
            self.size_slider.setValue(int(round(min(300, t.get("size", 24)))))
            self.spacing.setValue(float(t.get("spacing") or 0))
            self.color.set_color(t.get("color", "#000000"))
            self.align.set_value(t.get("align") or "left")
            self.b_fit.setEnabled(bool((t.get("orig") or {}).get("text")) or bool(t.get("w")))
            self.b_reset.setEnabled("orig" in t)
        self._loading = False
        if on:
            self.refresh_compare()

    def _fill_weights(self, gkey: str | None, stem: str | None):
        self.weight.clear()
        g = self.picker.groups.get(gkey) if gkey else None
        if not g:
            self.weight.addItem("常规", None)
            self.weight.addItem("加粗", "bold")
            self.weight.setCurrentIndex(1 if self.t and self.t.get("bold") else 0)
            return
        for w in sorted(g["weights"]):
            self.weight.addItem(fonts.WEIGHT_NAMES.get(w, str(w)), g["weights"][w])
        i = self.weight.findData(stem)
        self.weight.setCurrentIndex(max(0, i))

    def refresh_compare(self):
        """稍后再画对比图：不能在画布的信号处理里直接渲染画布（会重入崩溃），打字时也不卡。"""
        if not hasattr(self, "_cmp_timer"):
            from PySide6.QtCore import QTimer
            self._cmp_timer = QTimer(self)
            self._cmp_timer.setSingleShot(True)
            self._cmp_timer.setInterval(60)
            self._cmp_timer.timeout.connect(self.refresh_compare_now)
        self._cmp_timer.start()

    def refresh_compare_now(self):
        if not self.t or not self.isVisible() and not self.page.isVisible():
            return
        pair = self.page.text_preview(self.t)
        if not pair:
            self.compare.clear()
            return
        a, b = pair
        maxw = max(120, self.width() - 4)
        k = min(1.0, maxw / max(1, a.width()), 46 / max(1, a.height()))
        w, h = max(1, int(a.width() * k)), max(1, int(a.height() * k))
        img = QImage(w, h * 2 + 3, QImage.Format.Format_ARGB32)
        img.fill(QColor(128, 128, 128, 90))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, w, h), a)
        p.drawImage(QRectF(0, h + 3, w, h), b)
        p.end()
        self.compare.setPixmap(QPixmap.fromImage(img))

    # ---------------------------------------------------------------- 改动
    def _emit(self, props: dict):
        if self._loading or not self.t:
            return
        self.page.set_text_props(props)
        self.refresh_compare()

    def _size_changed(self, v):
        if self._loading:
            return
        self._loading = True
        self.size_slider.setValue(int(round(min(300, v))))
        self._loading = False
        old = float(self.t.get("size", 24)) if self.t else v
        props = {"size": float(v)}
        # 字号变了，字距按比例跟着变（和 PS 里按比例缩放文字一样，字不会挤在一起或散开）
        if self.t and old > 0 and self.t.get("spacing"):
            props["spacing"] = round(float(self.t["spacing"]) * v / old, 2)
            self._loading = True
            self.spacing.setValue(props["spacing"])
            self._loading = False
        self._emit(props)                 # 和 PS 一样：改字号时基线不动

    def _pick_group(self, key: str):
        if not self.t:
            return
        g = self.picker.groups.get(key)
        if not g:
            return
        cur = int(self.t.get("weight") or (700 if self.t.get("bold") else 400))
        w = min(g["weights"], key=lambda x: abs(x - cur))
        stem = g["weights"][w]
        self._fill_weights(key, stem)
        self._emit({"font": stem, "weight": w, "cat": g["cat"] if not g.get("system") else "sans"})

    def _pick_weight(self, i):
        if not self.t:
            return
        data = self.weight.itemData(i)
        if data in (None, "bold"):
            self._emit({"bold": data == "bold"})
            return
        info = fonts.stem_info(data)
        self._emit({"font": data, "weight": info["weight"] if info else 400})

    def _fit_width(self):
        if not self.t:
            return
        sp = self.page.fit_spacing(self.t)
        if sp is not None:
            self._loading = True
            self.spacing.setValue(sp)
            self._loading = False
            self._emit({"spacing": sp})

    def _reset(self):
        if not self.t or "orig" not in self.t:
            return
        o = self.t["orig"]
        props = {k: o.get(k) for k in ("x", "y", "size", "color", "bold", "family", "font", "weight", "spacing",
                                       "italic")}
        props["align"] = self.t.get("align_auto") or "left"
        if self.t.get("bl_orig"):
            props["bl"] = list(self.t["bl_orig"])
        self.page.set_text_props(props)
        self.load(self.t)

    def _apply_menu(self):
        if not self.t:
            return
        m = QMenu(self)
        auto = self.t.get("font_auto")
        same = [x for x in self.page.tpl["texts"] if auto and x.get("font_auto") == auto and x is not self.t]
        a1 = m.addAction(f"原图里同一种字体的文字（{len(same)} 段）")
        a1.setEnabled(bool(same))
        a2 = m.addAction(f"全部文字（{len(self.page.tpl['texts'])} 段）")
        act = m.exec(self.b_apply.mapToGlobal(QPoint(0, self.b_apply.height())))
        if act is a1:
            self.page.apply_font_to(self.t, same)
        elif act is a2:
            self.page.apply_font_to(self.t, [x for x in self.page.tpl["texts"] if x is not self.t])
