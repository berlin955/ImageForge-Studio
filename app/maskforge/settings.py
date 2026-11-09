"""设置窗口。"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from . import APP_NAME, APP_NAME_EN, AUTHOR, REPO_URL, __version__
from .config import PARTS, STYLES, data_dir, model_path
from .widgets import Card, SliderRow, button, muted, row, scroll_page


class SettingsDialog(QDialog):
    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.cfg = mw.cfg
        self.setWindowTitle("设置")
        self.resize(820, 600)
        self.setMinimumSize(720, 520)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(180)
        self.pages = QStackedWidget()
        h.addWidget(self.nav)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.pages, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(16, 8, 16, 14)
        foot.addStretch(1)
        b_done = button("完成", "Primary")
        b_done.clicked.connect(self.accept)
        foot.addWidget(b_done)
        right.addLayout(foot)
        h.addLayout(right, 1)

        for title, page in (("常规", self._page_general()),
                            ("识别与打码", self._page_detect()),
                            ("贴图库", self._page_stickers()),
                            ("关于", self._page_about())):
            self.nav.addItem(QListWidgetItem(title))
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

    # ---------------------------------------------------- 常规
    def _page_general(self):
        c1 = Card("外观")
        self.theme = QComboBox()
        self.theme.addItem("深色", "dark")
        self.theme.addItem("浅色", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.cfg["theme"])))
        self.theme.currentIndexChanged.connect(self._theme_changed)
        lab = QLabel("主题")
        lab.setFixedWidth(80)
        c1.add(row(lab, self.theme, None))

        c2 = Card("更新")
        self.auto_upd = QCheckBox("启动时自动检查新版本")
        self.auto_upd.setChecked(bool(self.cfg["check_update"]))
        self.auto_upd.toggled.connect(lambda on: self._save("check_update", on))
        c2.add(self.auto_upd)
        c2.add(muted(f"当前版本 v{__version__}。新版本发布在 GitHub，检查到后会提示一键更新。"))
        from .updater import BUILTIN_MIRRORS
        self.mirror = QComboBox()
        self.mirror.addItem("自动（先连 GitHub，不通就换镜像）", "auto")
        self.mirror.addItem("GitHub 直连", "direct")
        for m, name in BUILTIN_MIRRORS:
            self.mirror.addItem(f"镜像：{name}", m)
        self.mirror.addItem("自定义镜像…", "custom")
        self.mirror.setCurrentIndex(max(0, self.mirror.findData(self.cfg["update_mirror"])))
        self.mirror_custom = QLineEdit(self.cfg["update_mirror_custom"])
        self.mirror_custom.setPlaceholderText("例如 https://你的镜像地址/ （会拼在 GitHub 链接前面）")
        self.mirror_custom.setVisible(self.cfg["update_mirror"] == "custom")
        self.mirror.currentIndexChanged.connect(self._mirror_changed)
        self.mirror_custom.editingFinished.connect(self._mirror_changed)
        lab2 = QLabel("更新线路")
        lab2.setFixedWidth(80)
        c2.add(row(lab2, self.mirror))
        c2.add(self.mirror_custom)
        c2.add(muted("选中的线路优先使用，连不上时会自动换其他线路。不管走哪条线路，安装包都会核对官方的 SHA256 校验值。"))
        b = button("立即检查更新")
        b.clicked.connect(lambda: self.mw.check_updates(manual=True))
        c2.add(row(b, None))

        c3 = Card("数据")
        c3.add(muted(f"设置和上传的贴图保存在：\n{data_dir()}"))
        b2 = button("打开数据文件夹")
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        b3 = button("恢复默认设置", "Danger")
        b3.clicked.connect(self._reset)
        c3.add(row(b2, b3, None))
        area, _ = scroll_page(c1, c2, c3)
        return area

    def _mirror_changed(self, *_):
        choice = self.mirror.currentData()
        self.mirror_custom.setVisible(choice == "custom")
        self.cfg["update_mirror"] = choice
        self.cfg["update_mirror_custom"] = self.mirror_custom.text().strip()
        self.cfg.save()
        from .updater import set_preference
        set_preference(choice, self.cfg["update_mirror_custom"])

    def _theme_changed(self, _i):
        self._save("theme", self.theme.currentData())
        self.mw.apply_theme()

    def _save(self, key, v):
        self.cfg[key] = v
        self.cfg.save()

    def _reset(self):
        r = QMessageBox.question(self, "恢复默认设置",
                                 "把识别、打码样式和导出设置恢复成默认值？上传的贴图会保留。")
        if r != QMessageBox.StandardButton.Yes:
            return
        import copy
        from .config import DEFAULTS
        self.cfg.data = copy.deepcopy(DEFAULTS)
        self.cfg.save()
        self.mw.on_settings_changed()
        self.mw.apply_theme()
        QMessageBox.information(self, "已恢复", "设置已恢复默认。重新打开设置窗口可以看到新的值。")
        self.accept()

    # ---------------------------------------------------- 识别与打码
    def _page_detect(self):
        c1 = Card("识别")
        self.sens = SliderRow("灵敏度", 20, 90, 0, "%")
        self.sens.set_value(round((1 - self.cfg["detect"]["threshold"]) * 100))
        self.sens.valueChanged.connect(self._sens)
        c1.add(self.sens)
        c1.add(muted("灵敏度越高越容易检出部位，也更容易误判；漏检多就调高，误判多就调低。"))
        self.male = QCheckBox("同时识别男性下体")
        self.male.setChecked(bool(self.cfg["detect"].get("male", False)))
        self.male.toggled.connect(self._male)
        c1.add(self.male)

        cards = [c1]
        self._part_widgets = {}
        lib = self.mw.library
        for key, name in PARTS:
            p = self.cfg.part(key)
            c = Card(f"{name}")
            if key != "custom":
                en = QCheckBox(f"自动识别并给{name}打码")
                en.setChecked(p.get("enabled", True))
                en.toggled.connect(lambda on, k=key: self._part(k, "enabled", on))
                c.add(en)
                cov = QCheckBox("穿着内衣 / 丁字裤 / 薄纱等有遮挡时也打码")
                cov.setChecked(bool(p.get("covered", key != "areola")))
                cov.toggled.connect(lambda on, k=key: self._part(k, "covered", on))
                c.add(cov)
            else:
                c.add(muted("手动添加的自定义码使用这里的样式。"))
            form = QFormLayout()
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            style = QComboBox()
            for k, n in STYLES:
                style.addItem(n, k)
            style.setCurrentIndex(max(0, style.findData(p["style"])))
            stk = QComboBox()
            stk.setIconSize(QSize(20, 20))
            for sid, sname in lib.items():
                stk.addItem(QIcon(QPixmap.fromImage(lib.image(sid))), sname, sid)
            stk.setCurrentIndex(max(0, stk.findData(p["sticker"])))
            stk.setEnabled(p["style"] == "sticker")
            style.currentIndexChanged.connect(
                lambda _i, k=key, s=style, t=stk: (self._part(k, "style", s.currentData()),
                                                   t.setEnabled(s.currentData() == "sticker")))
            stk.currentIndexChanged.connect(lambda _i, k=key, t=stk: self._part(k, "sticker", t.currentData()))
            scale = QDoubleSpinBox()
            scale.setRange(0.1, 3.0)
            scale.setSingleStep(0.05)
            scale.setDecimals(2)
            scale.setSuffix(" 倍")
            scale.setValue(float(p.get("scale", 1.0)))
            scale.valueChanged.connect(lambda v, k=key: self._part(k, "scale", v))
            block = QDoubleSpinBox()
            block.setRange(0.4, 8.0)
            block.setSingleStep(0.1)
            block.setDecimals(1)
            block.setSuffix(" %")
            block.setValue(float(p.get("block", 0.018)) * 100)
            block.valueChanged.connect(lambda v, k=key: self._part(k, "block", round(v / 100, 4)))
            form.addRow("默认样式", style)
            form.addRow("默认贴图", stk)
            if key != "custom":
                form.addRow("码的大小", scale)
            form.addRow("马赛克颗粒", block)
            c.add(form)
            self._part_widgets[key] = stk
            cards.append(c)
        cards[-1].add(muted("「码的大小」是相对 AI 识别范围的倍数，码太小盖不住就调大。"))
        area, _ = scroll_page(*cards)
        return area

    def _sens(self, v):
        self.cfg["detect"]["threshold"] = round(1 - v / 100, 3)
        self.cfg.save()
        self.mw.on_settings_changed()

    def _male(self, on):
        self.cfg["detect"]["male"] = on
        self.cfg.save()

    def _part(self, key, attr, v):
        self.cfg.part(key)[attr] = v
        self.cfg.save()
        self.mw.on_settings_changed()

    # ---------------------------------------------------- 贴图库
    def _page_stickers(self):
        c = Card("贴图库")
        c.add(muted("上传你常用的码图，透明背景的 PNG 效果最好。上传后可以在编辑面板和各部位默认样式里选用。"))
        self.stk_list = QListWidget()
        self.stk_list.setObjectName("Stickers")
        self.stk_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.stk_list.setIconSize(QSize(72, 72))
        self.stk_list.setGridSize(QSize(100, 104))
        self.stk_list.setMovement(QListWidget.Movement.Static)
        self.stk_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.stk_list.setMinimumHeight(300)
        c.add(self.stk_list)
        b_add = button("上传贴图…", "Primary")
        b_del = button("删除选中", "Danger")
        b_add.clicked.connect(self._add_stickers)
        b_del.clicked.connect(self._del_sticker)
        c.add(row(b_add, b_del, None))
        c.add(muted("内置贴图不能删除。删除自己的贴图后，用到它的码会显示为爱心。"))
        self._reload_stickers()
        area, _ = scroll_page(c)
        return area

    def _reload_stickers(self):
        lib = self.mw.library
        self.stk_list.clear()
        for sid, name in lib.items():
            it = QListWidgetItem(QIcon(QPixmap.fromImage(lib.image(sid))), name)
            it.setData(Qt.ItemDataRole.UserRole, sid)
            self.stk_list.addItem(it)
        for key, combo in getattr(self, "_part_widgets", {}).items():
            cur = self.cfg.part(key)["sticker"]
            combo.blockSignals(True)
            combo.clear()
            for sid, sname in lib.items():
                combo.addItem(QIcon(QPixmap.fromImage(lib.image(sid))), sname, sid)
            combo.setCurrentIndex(max(0, combo.findData(cur)))
            combo.blockSignals(False)

    def _add_stickers(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择贴图", "", "图片 (*.png *.webp *.jpg *.jpeg)")
        if not files:
            return
        bad = []
        for f in files:
            try:
                self.mw.library.add(f)
            except Exception as e:
                bad.append(f"{os.path.basename(f)}：{e}")
        self._reload_stickers()
        self.mw.on_library_changed()
        if bad:
            QMessageBox.warning(self, "部分贴图没有加入", "\n".join(bad))

    def _del_sticker(self):
        it = self.stk_list.currentItem()
        if not it:
            return
        sid = it.data(Qt.ItemDataRole.UserRole)
        if not sid.startswith("user:"):
            QMessageBox.information(self, "不能删除", "内置贴图不能删除。")
            return
        self.mw.library.remove(sid)
        for key, _n in PARTS:
            if self.cfg.part(key)["sticker"] == sid:
                self.cfg.part(key)["sticker"] = "builtin:heart"
        self.cfg.save()
        self._reload_stickers()
        self.mw.on_library_changed()

    # ---------------------------------------------------- 关于
    def _page_about(self):
        c = Card()
        t = QLabel(APP_NAME)
        t.setObjectName("BigTitle")
        c.add(t)
        c.add(muted(f"{APP_NAME_EN}　·　版本 v{__version__}"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        items = [
            ("作者", AUTHOR),
            ("项目主页", f'<a href="{REPO_URL}">{REPO_URL}</a>'),
            ("识别模型", f"NudeNet {model_path().stem}（本地运行，图片不会上传）"),
            ("运行环境", f"Python {sys.version.split()[0]} · PySide6"),
        ]
        for i, (k, v) in enumerate(items):
            a = QLabel(k)
            a.setObjectName("Muted")
            b = QLabel(v)
            b.setTextFormat(Qt.TextFormat.RichText)
            b.setOpenExternalLinks(True)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            grid.addWidget(a, i, 0)
            grid.addWidget(b, i, 1)
        c.add(grid)
        b = button("检查更新")
        b.clicked.connect(lambda: self.mw.check_updates(manual=True))
        b2 = button("打开项目主页")
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        c.add(row(b, b2, None))
        c.add(muted("识别模型来自开源项目 NudeNet，遵循其开源协议（AGPL-3.0）。"))
        area, _ = scroll_page(c)
        return area
