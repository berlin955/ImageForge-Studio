"""主窗口：顶部流程条，左侧功能区，右侧看图和缩略图。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import (QActionGroup, QColor, QDesktopServices, QIcon, QImage, QKeySequence,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QAbstractSlider,
                               QAbstractSpinBox, QApplication, QButtonGroup, QComboBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog, QScrollBar,
                               QPushButton, QStackedWidget, QStatusBar, QTextEdit, QVBoxLayout,
                               QWidget)

from . import APP_NAME, APP_NAME_EN, AUTHOR, __version__, theme
from .canvas import Canvas
from .config import IMAGE_EXTS, PART_NAMES, icon_path, model_path
from .detector import Detector, plan_layers, subject_of
from .exporter import output_name, render_doc, render_preview, save_image, unique_path
from .model import IMAGE_CACHE, ImageDoc, Layer, natural_key
from .panels import ExportDialog, SidePanel
from .updater import Downloader, UpdateChecker, is_newer, launch_installer
from .widgets import button
from .workers import DetectWorker, ThumbTask

STATUS_COLORS = {"todo": "muted", "attention": "warn", "done": "ok", "error": "danger"}


def count_status(docs) -> dict:
    cnt = {"todo": 0, "attention": 0, "done": 0, "error": 0}
    for d in docs:
        cnt[d.status()] += 1
    return cnt


def app_icon() -> QIcon:
    p = icon_path()
    return QIcon(str(p)) if p.exists() else QIcon()


class MainWindow(QMainWindow):
    def __init__(self, cfg, library):
        super().__init__()
        self.cfg = cfg
        self.library = library
        self.docs: list[ImageDoc] = []
        self.cur = -1
        self.active_part = "lower"
        self.busy = False
        self.film_filter = "all"
        self._detector = None
        self._det_lock = threading.Lock()
        self._worker = None
        self._upd = None
        self._dl = None
        self._after_detect = None
        self._replace = False
        self._det_found = 0
        self._det_docs = 0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._thumb_tasks: list[ThumbTask] = []
        self._thumb_dirty: set[str] = set()
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(300)
        self._thumb_timer.timeout.connect(self._flush_thumbs)

        self.setWindowTitle(f"{APP_NAME}  {APP_NAME_EN}")
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)
        self._build()
        self._shortcuts()
        QApplication.instance().installEventFilter(self)
        self.refresh_all()

    # ================================================================= 界面
    def _build(self):
        # 「智能打码」页
        self.mask_page = QWidget()
        root = QVBoxLayout(self.mask_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部：打码流程 ----
        top = QFrame()
        top.setObjectName("TopBar")
        th = QHBoxLayout(top)
        th.setContentsMargins(16, 8, 12, 8)
        th.setSpacing(10)
        pt = QLabel("智能打码")
        pt.setObjectName("Brand")
        th.addWidget(pt)
        th.addSpacing(24)
        self.steps = []
        for i, (title, fn, tip) in enumerate((
                ("导入", self.import_dialog, "导入图片或文件夹"),
                ("一键打码", self.auto_mask, "AI 识别并自动贴码"),
                ("检查", self.next_pending, "跳到下一张需要注意的图片"),
                ("导出", self.export_batch, "按导出设置批量保存"))):
            b = QPushButton()
            b.setObjectName("Step")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            self.steps.append((b, title))
            th.addWidget(b)
            if i < 3:
                arrow = QLabel("›")
                arrow.setObjectName("Muted")
                th.addWidget(arrow)
        th.addStretch(1)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ---- 左侧功能区 ----
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(384)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        self.side = SidePanel(self)
        sv.addWidget(self.side)
        body.addWidget(side)

        # ---- 右侧看图 ----
        work = QWidget()
        work.setObjectName("Workspace")
        wv = QVBoxLayout(work)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(0)

        tb = QFrame()
        tb.setObjectName("Toolbar")
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(12, 6, 12, 6)
        tbh.setSpacing(6)
        self.b_prev = button("‹", "Tool", "上一张（← 或 PageUp）")
        self.b_next = button("›", "Tool", "下一张（→ 或 PageDown）")
        self.b_prev.setFixedWidth(36)
        self.b_next.setFixedWidth(36)
        self.b_prev.clicked.connect(lambda: self.go(self.cur - 1))
        self.b_next.clicked.connect(lambda: self.go(self.cur + 1))
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet("font-weight:700")
        self.state_lbl = QLabel("")
        tbh.addWidget(self.b_prev)
        tbh.addWidget(self.b_next)
        tbh.addSpacing(6)
        tbh.addWidget(self.name_lbl)
        tbh.addSpacing(8)
        tbh.addWidget(self.state_lbl)
        tbh.addStretch(1)
        self.b_peek = button("对比原图", "Tool", "按住空格也可以")
        self.b_peek.setCheckable(True)
        self.b_peek.toggled.connect(lambda on: self.canvas.set_peek(on))
        self.b_fit = button("适应窗口", "Tool", "F")
        self.b_100 = button("100%", "Tool")
        self.zoom_lbl = QLabel("")
        self.zoom_lbl.setObjectName("Muted")
        self.zoom_lbl.setFixedWidth(46)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for w in (self.b_peek, self.b_fit, self.b_100, self.zoom_lbl):
            tbh.addWidget(w)
        wv.addWidget(tb)

        self.canvas = Canvas(self.library)
        self.b_fit.clicked.connect(self.canvas.fit)
        self.b_100.clicked.connect(lambda: self.canvas.zoom_to(1.0))
        self.canvas.zoomChanged.connect(lambda s: self.zoom_lbl.setText(f"{round(s * 100)}%"))
        self.canvas.selectionChanged.connect(lambda _l: self.side.refresh())
        self.canvas.beginEdit.connect(self.begin_edit)
        self.canvas.liveEdited.connect(self.side.sync_geometry)
        self.canvas.edited.connect(self._on_edited)
        self.canvas.addRequested.connect(lambda pt: self.add_layer(self.active_part, pt.x(), pt.y()))
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.navigate.connect(lambda d: self.go(self.cur + d))

        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.addStretch(1)
        e1 = QLabel("把模特图片或文件夹拖到这里")
        e1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e1.setStyleSheet("font-size:20px;font-weight:700")
        e2 = QLabel("导入 → 一键打码 → 检查 → 导出")
        e2.setObjectName("Muted")
        e2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(e1)
        ev.addSpacing(6)
        ev.addWidget(e2)
        ev.addStretch(1)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.empty)
        self.view_stack.addWidget(self.canvas)
        wv.addWidget(self.view_stack, 1)

        fb = QFrame()
        fb.setObjectName("FilmBar")
        fv = QVBoxLayout(fb)
        fv.setContentsMargins(10, 6, 10, 2)
        fv.setSpacing(2)
        fh = QHBoxLayout()
        fh.setSpacing(6)
        self.filter_group = QButtonGroup(self)
        self.filter_btns = {}
        for key, text in (("all", "全部"), ("check", "需要注意"), ("ok", "已打码")):
            b = button(text, "Chip")
            b.setCheckable(True)
            self.filter_group.addButton(b)
            self.filter_btns[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_film_filter(k))
            fh.addWidget(b)
        self.filter_btns["all"].setChecked(True)
        fh.addStretch(1)
        self.film_hint = QLabel("")
        self.film_hint.setObjectName("Muted")
        fh.addWidget(self.film_hint)
        fv.addLayout(fh)
        self.film = QListWidget()
        self.film.setObjectName("Film")
        self.film.setViewMode(QListWidget.ViewMode.IconMode)
        self.film.setFlow(QListWidget.Flow.LeftToRight)
        self.film.setWrapping(False)
        self.film.setMovement(QListWidget.Movement.Static)
        self.film.setIconSize(QSize(104, 104))
        self.film.setGridSize(QSize(136, 150))
        self.film.setFixedHeight(160)
        self.film.setUniformItemSizes(True)
        self.film.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.film.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.film.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.film.currentRowChanged.connect(self._film_changed)
        fv.addWidget(self.film)
        wv.addWidget(fb)
        body.addWidget(work, 1)
        root.addLayout(body, 1)

        self._build_shell()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._placeholder = self._make_placeholder()

    # ---- 外壳：左侧功能栏 + 各功能页 ----
    NAV = [
        ("assets", "▦", "素材"),
        ("mask", "◐", "智能打码"),
        ("main", "▣", "批量主图"),
        ("spec", "▤", "智能规格"),
        ("detail", "☰", "智能详情"),
        ("watermark", "◎", "批量水印"),
        ("templates", "❖", "模板库"),
    ]

    def _build_shell(self):
        from .pages import AssetsPage, ComingSoonPage
        from .mainimage import MainImagePage
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("NavRail")
        nav.setFixedWidth(88)
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(8, 12, 8, 10)
        nv.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(36, 36))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setToolTip(f"{APP_NAME} {APP_NAME_EN}  v{__version__}")
        nv.addWidget(logo)
        brand = QLabel(APP_NAME)
        brand.setObjectName("NavBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nv.addWidget(brand)
        nv.addSpacing(10)

        self.pages = QStackedWidget()
        self.page_keys: list[str] = []
        self.nav_group = QButtonGroup(self)
        self.nav_btns = {}
        self.assets_page = AssetsPage(self)
        self.main_page = MainImagePage(self)
        built = {"assets": self.assets_page, "mask": self.mask_page, "main": self.main_page}
        soon = {
            "spec": ("智能规格", "导入一张喜欢的规格图，自动挖空原来的模特照片、识别文字，换成你的模特图，文字可以随时修改。"),
            "detail": ("智能详情", "和智能规格一样换模特、改文字，支持很长的详情图，导出时可以自动切成几段。"),
            "watermark": ("批量水印", "给打码图、主图、规格图、详情图批量加上你的 Logo，透明度、位置、大小可调，每张还能单独挪位置。"),
            "templates": ("模板库", "保存好的规格、详情、主图模板都在这里，下次新款直接套用。"),
        }
        for key, _glyph, text in self.NAV:
            b = self._nav_button(text, "mask" if key == "mask" else key)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_btns[key] = b
            nv.addWidget(b)
            page = built.get(key) or ComingSoonPage(*soon[key])
            self.pages.addWidget(page)
            self.page_keys.append(key)
        nv.addStretch(1)
        self.b_theme = self._nav_button("主题", "theme")
        self.b_theme.clicked.connect(self._theme_menu)
        b_set = self._nav_button("设置", "settings")
        b_set.setToolTip("Ctrl+,")
        b_set.clicked.connect(lambda: self.open_settings())
        nv.addWidget(self.b_theme)
        nv.addWidget(b_set)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("Muted")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nv.addWidget(ver)

        h.addWidget(nav)
        h.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.show_page("assets")

    def _nav_button(self, text: str, icon: str):
        from PySide6.QtWidgets import QToolButton
        b = QToolButton()
        b.setObjectName("NavBtn")
        b.setText(text)
        b.setProperty("nav_icon", icon)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(26, 26))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedWidth(72)
        self._nav_all = getattr(self, "_nav_all", []) + [b]
        self._paint_nav_icon(b)
        return b

    def _paint_nav_icon(self, b):
        from .icons import make_icon
        pal = theme.current()
        b.setIcon(make_icon(b.property("nav_icon"), pal["muted"], pal["accent"]))

    def current_page(self) -> str:
        i = self.pages.currentIndex()
        return self.page_keys[i] if 0 <= i < len(self.page_keys) else ""

    def show_page(self, key: str):
        if key not in self.page_keys:
            return
        self.pages.setCurrentIndex(self.page_keys.index(key))
        self.nav_btns[key].setChecked(True)
        page = self.pages.currentWidget()
        if hasattr(page, "on_show"):
            page.on_show()
        if key == "mask":
            self.canvas.setFocus()

    def _make_placeholder(self) -> QIcon:
        pm = QPixmap(104, 104)
        pm.fill(QColor(theme.current()["card2"]))
        return QIcon(pm)

    def _shortcuts(self):
        for k, fn in (("Ctrl+O", self.import_dialog), ("Ctrl+E", self.export_batch),
                      ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                      ("PgDown", lambda: QTimer.singleShot(0, lambda: self.go(self.cur + 1))),
                      ("PgUp", lambda: QTimer.singleShot(0, lambda: self.go(self.cur - 1))),
                      ("Ctrl+,", self.open_settings), ("Ctrl+D", self.duplicate_layer)):
            s = QShortcut(QKeySequence(k), self)
            s.activated.connect(fn)

    def _theme_menu(self):
        m = QMenu(self)
        grp = QActionGroup(m)
        for key in theme.THEME_ORDER:
            pal = theme.PALETTES[key]
            pm = QPixmap(14, 14)
            pm.fill(QColor(pal["accent"]))
            a = m.addAction(QIcon(pm), pal["label"])
            a.setCheckable(True)
            a.setChecked(key == theme.name())
            grp.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
        m.exec(self.b_theme.mapToGlobal(self.b_theme.rect().bottomLeft()))

    def set_theme(self, key: str):
        self.cfg["theme"] = key
        self.cfg.save()
        self.apply_theme()

    # ================================================================= 数据
    def cur_doc(self) -> ImageDoc | None:
        return self.docs[self.cur] if 0 <= self.cur < len(self.docs) else None

    def prev_doc(self) -> ImageDoc | None:
        return self.docs[self.cur - 1] if 1 <= self.cur < len(self.docs) else None

    def doc_by_id(self, did: str) -> ImageDoc | None:
        for d in self.docs:
            if d.id == did:
                return d
        return None

    def export_targets(self) -> list[ImageDoc]:
        if self.cfg["export"].get("scope") == "skip_attention":
            return [d for d in self.docs if not d.error and d.status() != "attention"]
        return [d for d in self.docs if not d.error]

    # ================================================================= 导入
    def import_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", self.cfg["last_dir"], f"图片 ({exts})")
        if files:
            self.cfg["last_dir"] = str(Path(files[0]).parent)
            self.cfg.save()
            self.import_paths(files)

    def import_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", self.cfg["last_dir"])
        if d:
            self.cfg["last_dir"] = d
            self.cfg.save()
            self.import_paths([d])

    def import_paths(self, paths: list[str]):
        files: list[Path] = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                files += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
            elif p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
        files.sort(key=lambda f: natural_key(str(f)))
        have = {str(d.path).lower() for d in self.docs}
        new = []
        for f in files:
            key = str(f).lower()
            if key not in have:
                have.add(key)
                new.append(ImageDoc(f))
        if not new:
            self.status.showMessage("没有找到新的图片", 4000)
            return
        first = len(self.docs)
        self.docs += new
        for d in new:
            it = QListWidgetItem(self._placeholder, self._film_text(d))
            it.setData(Qt.ItemDataRole.UserRole, d.id)
            it.setToolTip(str(d.path))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.film.addItem(it)
            task = ThumbTask(d.id, str(d.path), 360)
            task.setAutoDelete(False)
            task.signals.done.connect(self._thumb_done)
            self._thumb_tasks.append(task)
            self.pool.start(task)
        self.status.showMessage(f"已导入 {len(new)} 张图片", 6000)
        self.go(first)

    def _thumb_done(self, did, img: QImage, w, h):
        self._thumb_tasks = [t for t in self._thumb_tasks if t.doc_id != did]
        d = self.doc_by_id(did)
        if not d:
            return
        if img.isNull():
            d.error = "无法读取图片"
        else:
            d.thumb = img
            if not d.w:
                d.w, d.h = w, h
        self._set_film_icon(d)
        self._update_film_item(self.docs.index(d))

    def thumb_for(self, d: ImageDoc) -> QImage | None:
        if d.thumb is None and not d.error:
            img = d.image()
            if img is not None:
                d.thumb = img.scaled(360, 360, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        return d.thumb

    def _set_film_icon(self, d: ImageDoc):
        if d.thumb is None or d not in self.docs:
            return
        img = render_preview(d, d.thumb, self.library)
        if img is None or img.isNull():
            return
        d.icon = QIcon(QPixmap.fromImage(img))
        it = self.film.item(self.docs.index(d))
        if it:
            it.setIcon(d.icon)
        if hasattr(self, "assets_page"):
            self.assets_page.update_icon(d)
            self.main_page.update_icon(d)

    def mark_thumb_dirty(self, d: ImageDoc | None = None):
        d = d or self.cur_doc()
        if d:
            self._thumb_dirty.add(d.id)
            self._thumb_timer.start()

    def _flush_thumbs(self):
        ids, self._thumb_dirty = self._thumb_dirty, set()
        for did in ids:
            d = self.doc_by_id(did)
            if d:
                self._set_film_icon(d)

    def _film_text(self, d: ImageDoc) -> str:
        name = d.name if len(d.name) <= 16 else d.name[:7] + "…" + d.name[-7:]
        return f"{name}\n{d.status_text()}"

    def _status_color(self, d: ImageDoc) -> str:
        return theme.current()[STATUS_COLORS[d.status()]]

    def _update_film_item(self, row: int):
        it = self.film.item(row)
        if not it or row >= len(self.docs):
            return
        d = self.docs[row]
        it.setText(self._film_text(d))
        it.setForeground(QColor(self._status_color(d)))
        self._apply_filter_row(row)

    def _apply_filter_row(self, row: int):
        d = self.docs[row]
        st = d.status()
        f = self.film_filter
        hide = (f == "check" and st not in ("attention", "error")) or (f == "ok" and st != "done")
        self.film.setRowHidden(row, hide and row != self.cur)

    def set_film_filter(self, key: str):
        self.film_filter = key
        for i in range(len(self.docs)):
            self._apply_filter_row(i)
        self.filter_btns[key].setChecked(True)

    def remove_current(self):
        d = self.cur_doc()
        if not d or self.busy:
            return
        i = self.cur
        IMAGE_CACHE.drop(d.id)
        self.docs.pop(i)
        self.film.blockSignals(True)
        self.film.takeItem(i)
        self.film.blockSignals(False)
        self.cur = -1
        self.go(min(i, len(self.docs) - 1))

    def remove_docs(self, ids: set):
        if self.busy or not ids:
            return
        keep = []
        for i in range(len(self.docs) - 1, -1, -1):
            d = self.docs[i]
            if d.id in ids:
                IMAGE_CACHE.drop(d.id)
                self.docs.pop(i)
                self.film.blockSignals(True)
                self.film.takeItem(i)
                self.film.blockSignals(False)
        self.cur = -1
        if hasattr(self, "main_page"):
            self.main_page.forget(ids)
        self.go(0)

    def clear_all(self):
        if not self.docs or self.busy:
            return
        r = QMessageBox.question(self, "清空列表",
                                 f"从列表中移除全部 {len(self.docs)} 张图片？\n（只是移出列表，不会删除你电脑上的文件）")
        if r != QMessageBox.StandardButton.Yes:
            return
        for d in self.docs:
            IMAGE_CACHE.drop(d.id)
        self.docs.clear()
        self.film.blockSignals(True)
        self.film.clear()
        self.film.blockSignals(False)
        self.cur = -1
        self.canvas.set_doc(None, None)
        self.refresh_all()

    # ================================================================= 切换图片
    def _film_changed(self, row: int):
        if row != self.cur and 0 <= row < len(self.docs):
            self.go(row)

    def go(self, i: int):
        if not self.docs:
            self.cur = -1
            self.canvas.set_doc(None, None)
            self.refresh_all()
            return
        i = max(0, min(i, len(self.docs) - 1))
        old = self.cur
        self.cur = i
        d = self.docs[i]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            img = d.image()
        finally:
            QApplication.restoreOverrideCursor()
        self.canvas.set_doc(d, img)
        self.film.blockSignals(True)
        self.film.setCurrentRow(i)
        self.film.blockSignals(False)
        if 0 <= old < len(self.docs):
            self._apply_filter_row(old)
        self._update_film_item(i)
        it = self.film.item(i)
        if it:
            self.film.scrollToItem(it)
        self.refresh_all()
        self.canvas.setFocus()

    def next_pending(self):
        if not self.docs:
            return
        order = list(range(self.cur + 1, len(self.docs))) + list(range(0, self.cur + 1))
        for i in order:
            if self.docs[i].status() == "attention":
                self.go(i)
                return
        self.status.showMessage("没有需要注意的图片了，可以导出了", 5000)

    def confirm_next(self):
        d = self.cur_doc()
        if not d:
            return
        # 看过了：这张不再算「需要注意」，跳到下一张需要注意的
        d.reviewed = True
        self._update_film_item(self.cur)
        self.refresh_all()
        self.next_pending()

    # ================================================================= 刷新
    def refresh_all(self):
        d = self.cur_doc()
        self.view_stack.setCurrentIndex(1 if d else 0)
        n = len(self.docs)
        self.name_lbl.setText(f"{d.name}" if d else "")
        if d:
            self.state_lbl.setText(f"{self.cur + 1}/{n}　·　{d.status_text()}" + (f"　·　{d.w}×{d.h}" if d.w else ""))
            self.state_lbl.setStyleSheet(f"color:{self._status_color(d)}")
        else:
            self.state_lbl.setText("")
        self.b_prev.setEnabled(self.cur > 0)
        self.b_next.setEnabled(0 <= self.cur < n - 1)
        self._update_steps()
        self.side.refresh()
        if hasattr(self, "assets_page"):
            self.assets_page.refresh()
            self.main_page.refresh()

    def _update_steps(self):
        n = len(self.docs)
        cnt = count_status(self.docs)
        masked = n - cnt["todo"] - cnt["error"]
        states = [
            (n > 0, f"① 导入  {n}" if n else "① 导入"),
            (n > 0 and cnt["todo"] == 0, f"② 一键打码  {masked}/{n}" if n else "② 一键打码"),
            (n > 0 and cnt["todo"] == 0 and cnt["attention"] == 0,
             f"③ 需要注意  {cnt['attention']}" if cnt["attention"] else "③ 检查"),
            (False, "④ 导出"),
        ]
        for (b, _t), (done, text) in zip(self.steps, states):
            b.setText(text)
            b.setObjectName("StepDone" if done else "Step")
            b.style().unpolish(b)
            b.style().polish(b)
        need = cnt["attention"]
        self.film_hint.setText(f"{need} 张需要注意" if need else "")

    def _refresh_doc_state(self):
        if self.cur >= 0:
            self._update_film_item(self.cur)
            self.mark_thumb_dirty()
        self.refresh_all()

    # ================================================================= 编辑
    def begin_edit(self):
        d = self.cur_doc()
        if d:
            d.push()
            d.reviewed = True

    def _on_edited(self):
        self.side.sync_geometry()
        if self.cur >= 0:
            self._update_film_item(self.cur)
            self.mark_thumb_dirty()

    def edit_layer(self, fn, push: bool = True, rebuild_panel: bool = False):
        d = self.cur_doc()
        L = self.canvas.selected_layer()
        if not d or not L:
            return
        if push:
            d.push()
        d.reviewed = True
        fn(L)
        self.canvas.update_layer(L)
        self.mark_thumb_dirty(d)
        if rebuild_panel:
            self.side.refresh()

    def add_layer(self, part: str, x: float | None = None, y: float | None = None):
        d = self.cur_doc()
        if not d or not d.w:
            self.status.showMessage("先导入图片", 3000)
            return
        self.active_part = part
        p = self.cfg.part(part)
        base = {"lower": (0.10, 0.07), "crack": (0.045, 0.10), "areola": (0.045, 0.045),
                "custom": (0.10, 0.10)}[part]
        if x is None:
            n = len(d.layers)
            x = d.w / 2 + (n % 5) * d.w * 0.03
            y = d.h / 2 + (n % 5) * d.w * 0.03
        d.push()
        L = Layer(part=part, style=p["style"], sticker=p["sticker"], color=p["color"], block=p["block"],
                  opacity=p.get("opacity", 1.0), cx=x, cy=y, w=base[0] * d.w, h=base[1] * d.w)
        d.layers.append(L)
        d.reviewed = True
        self.canvas.rebuild(select_id=L.id)
        self._refresh_doc_state()
        self.status.showMessage(f"已添加{PART_NAMES.get(part, part)}的码。双击图片可以在点击的位置继续添加", 5000)

    def duplicate_layer(self):
        d = self.cur_doc()
        L = self.canvas.selected_layer()
        if not d or not L:
            return
        d.push()
        off = max(8.0, d.w * 0.03)
        n = L.clone(cx=L.cx + off, cy=L.cy + off, auto=False)
        d.layers.append(n)
        self.canvas.rebuild(select_id=n.id)
        self._refresh_doc_state()

    def delete_layer(self):
        d = self.cur_doc()
        L = self.canvas.selected_layer()
        if not d or not L:
            return
        d.push()
        d.layers = [l for l in d.layers if l.id != L.id]
        d.reviewed = True
        self.canvas.rebuild(select_id="")
        self._refresh_doc_state()

    def clear_layers(self):
        d = self.cur_doc()
        if not d or not d.layers:
            return
        d.push()
        d.layers = []
        self.canvas.rebuild(select_id="")
        self._refresh_doc_state()

    def copy_prev_layers(self):
        d, p = self.cur_doc(), self.prev_doc()
        if not d or not p or not p.layers:
            return
        if not p.w:
            p.image()
        d.push()
        d.layers += d.apply_normalized(p.normalized())
        self.canvas.rebuild(select_id="")
        self._refresh_doc_state()
        self.status.showMessage(f"已沿用上一张的 {len(p.layers)} 个码", 4000)

    def set_layer_as_default(self):
        L = self.canvas.selected_layer()
        if not L:
            return
        self.cfg.part(L.part).update(style=L.style, sticker=L.sticker, color=L.color,
                                     block=L.block, opacity=L.opacity)
        self.cfg.save()
        self.side.sync_from_cfg()
        self.status.showMessage(f"已设为「{PART_NAMES.get(L.part, L.part)}」的默认样式", 5000)

    def undo(self):
        d = self.cur_doc()
        if d and d.undo():
            self.canvas.rebuild()
            self._refresh_doc_state()

    def redo(self):
        d = self.cur_doc()
        if d and d.redo():
            self.canvas.rebuild()
            self._refresh_doc_state()

    # ================================================================= 识别
    def get_detector(self):
        with self._det_lock:
            if self._detector is None:
                mp = model_path()
                if not mp.exists():
                    raise FileNotFoundError(f"没有找到识别模型：{mp}")
                self._detector = Detector(mp)
            return self._detector

    def detect(self, mode: str = "pending", then=None):
        if self.busy or not self.docs:
            return
        if mode == "current":
            d = self.cur_doc()
            targets = [d] if d else []
        elif mode == "all":
            if any(d.layers for d in self.docs):
                r = QMessageBox.question(self, "全部重新识别",
                                         "重新识别会替换所有图片上已有的码（包括手动调整过的），继续吗？")
                if r != QMessageBox.StandardButton.Yes:
                    return
            targets = [d for d in self.docs if not d.error]
        else:
            targets = [d for d in self.docs if not d.detected and not d.layers and not d.error]
        if not targets:
            if then:
                then()
            else:
                self.status.showMessage("没有需要识别的图片", 4000)
            return
        self._analyze = False
        self._replace = mode in ("all", "current")
        self._after_detect = then
        self._det_found = 0
        self._det_docs = len(targets)
        self.set_busy(True)
        self.side.set_progress(0, len(targets), "正在加载识别模型…")
        w = DetectWorker([(d.id, str(d.path), d.name) for d in targets],
                         float(self.cfg["detect"]["threshold"]), self.get_detector, self)
        w.progress.connect(self._det_progress)
        w.result.connect(self._det_result)
        w.failed.connect(self._det_failed)
        w.fatal.connect(self._det_fatal)
        w.finished.connect(self._det_finished)
        self._worker = w
        w.start()

    def analyze_subjects(self, then=None):
        """只识别人物位置（给主图智能裁切用），不打码。"""
        if self.busy:
            return
        targets = [d for d in self.docs if d.subject is None and not d.error and not d.detected]
        if not targets:
            if then:
                then()
            return
        self._analyze = True
        self._replace = False
        self._after_detect = then
        self._det_found = 0
        self._det_docs = len(targets)
        self.set_busy(True)
        w = DetectWorker([(d.id, str(d.path), d.name) for d in targets],
                         float(self.cfg["detect"]["threshold"]), self.get_detector, self)
        w.result.connect(self._det_result)
        w.failed.connect(self._det_failed)
        w.fatal.connect(self._det_fatal)
        w.finished.connect(self._det_finished)
        self._worker = w
        self.status.showMessage(f"正在识别 {len(targets)} 张图的人物位置…", 4000)
        w.start()

    def stop_detect(self):
        if self._worker:
            self._worker.requestInterruption()
            self._after_detect = None

    def _det_progress(self, i, n, name):
        self.side.set_progress(i, n, f"正在识别 {i + 1}/{n}　{name}" if i < n else "")

    def _det_result(self, did, w, h, dets):
        d = self.doc_by_id(did)
        if not d:
            return
        d.w, d.h = w, h
        d.subject, d.face = subject_of(dets)
        if getattr(self, "_analyze", False):
            if d.subject is None:
                d.subject = (0.0, 0.0, float(w), float(h))
            return
        layers = plan_layers(dets, w, h, self.cfg)
        if self._replace or not d.layers:
            d.push()
            d.layers = layers
            d.reviewed = False
        d.detected = True
        d.error = ""
        self._det_found += len(layers)
        row = self.docs.index(d)
        self._update_film_item(row)
        self.mark_thumb_dirty(d)
        if row == self.cur:
            self.canvas.rebuild(select_id="")
            self.refresh_all()

    def _det_failed(self, did, msg):
        d = self.doc_by_id(did)
        if d:
            d.error = msg
            self._update_film_item(self.docs.index(d))

    def _det_fatal(self, msg):
        self._after_detect = None
        QMessageBox.critical(self, "识别模型无法启动", f"{msg}\n\n可以先手动添加码，或者重新安装软件。")

    def _det_finished(self):
        self._worker = None
        self.set_busy(False)
        self.side.set_progress(0, 0, "")
        if getattr(self, "_analyze", False):
            self._analyze = False
            self.status.showMessage("人物位置识别完成", 5000)
        else:
            self.status.showMessage(f"识别完成：{self._det_docs} 张图片，共 {self._det_found} 个码", 8000)
        self.refresh_all()
        then, self._after_detect = self._after_detect, None
        if then:
            QTimer.singleShot(0, then)

    def set_busy(self, on: bool):
        self.busy = on
        self.refresh_all()

    # ================================================================= 打码与预览
    def auto_mask(self):
        """一键打码：识别所有未处理的图片，完成后打开预览。"""
        if not self.docs:
            self.import_dialog()
            return
        if self.busy:
            return
        self.detect(mode="pending", then=self.open_preview)

    def open_preview(self):
        if not self.docs:
            return
        self._flush_thumbs()
        from .preview import PreviewDialog
        dlg = PreviewDialog(self)
        r = dlg.exec()
        if r == PreviewDialog.EDIT and dlg.picked >= 0:
            self.go(dlg.picked)
        elif r == PreviewDialog.SAVE:
            self.export_batch()

    # ================================================================= 导出
    def open_export_settings(self):
        ExportDialog(self).exec()
        self.refresh_all()

    def choose_out_dir(self) -> bool:
        cur = self.cfg["export"].get("dir") or self.cfg["last_dir"]
        d = QFileDialog.getExistingDirectory(self, "选择保存位置", cur)
        if not d:
            return False
        self.cfg["export"]["dir"] = d
        self.cfg.save()
        self.side.refresh()
        return True

    def _ensure_out_dir(self) -> Path | None:
        if not self.cfg["export"].get("dir") and not self.choose_out_dir():
            return None
        p = Path(self.cfg["export"]["dir"])
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "无法使用这个文件夹", str(e))
            return None
        return p

    def export_current(self):
        d = self.cur_doc()
        if d:
            self._export([d])

    def export_batch(self):
        docs = self.export_targets()
        if not docs:
            if not self.docs:
                self.import_dialog()
                return
            QMessageBox.information(self, "没有可导出的图片",
                                    "导出范围设成了「仅已确认」，但还没有确认任何图片。\n"
                                    "可以按 Enter 逐张确认，或者在「导出设置」里改成「全部图片」。")
            return
        self._export(docs)

    def _export(self, docs: list[ImageDoc]) -> int:
        if self.busy:
            return 0
        out = self._ensure_out_dir()
        if out is None:
            return 0
        ex = dict(self.cfg["export"])
        self.set_busy(True)
        dlg = QProgressDialog("正在导出…", "取消", 0, len(docs), self)
        dlg.setWindowTitle("导出")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        taken: set = set()
        ok, errors = 0, []
        try:
            for i, d in enumerate(docs):
                if dlg.wasCanceled():
                    break
                dlg.setValue(i)
                dlg.setLabelText(f"正在导出 {i + 1}/{len(docs)}：{d.name}")
                QApplication.processEvents()
                img = d.image()
                if img is None:
                    errors.append(f"{d.name}：无法读取")
                    continue
                try:
                    res = render_doc(d, img, self.library, ex)
                    path = unique_path(out, output_name(d, ex), bool(ex.get("overwrite")), taken)
                    taken.add(str(path).lower())
                    save_image(res, path, ex)
                    ok += 1
                except Exception as e:
                    errors.append(f"{d.name}：{e}")
            dlg.setValue(len(docs))
        finally:
            dlg.close()
            self.set_busy(False)
        if errors:
            QMessageBox.warning(self, "导出完成",
                                f"已导出 {ok} 张图片到：\n{out}\n\n有 {len(errors)} 张没有成功：\n"
                                + "\n".join(errors[:8]))
        else:
            self.status.showMessage(f"已导出 {ok} 张图片到 {out}", 10000)
        if ok and ex.get("open_after", True):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return ok

    # ================================================================= 码图
    def upload_stickers(self) -> str | None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择码图（透明背景的 PNG 最好）",
                                                self.cfg["last_dir"], "图片 (*.png *.webp *.jpg *.jpeg)")
        if not files:
            return None
        last, bad = None, []
        for f in files:
            try:
                last = self.library.add(f)
            except Exception as e:
                bad.append(f"{Path(f).name}：{e}")
        self.on_library_changed()
        if bad:
            QMessageBox.warning(self, "部分码图没有加入", "\n".join(bad))
        if last:
            self.status.showMessage(f"已加入 {len(files) - len(bad)} 张码图", 5000)
        return last

    def apply_part_style(self, part: str):
        p = self.cfg.part(part)
        n = 0
        for d in self.docs:
            hit = [l for l in d.layers if l.part == part]
            if not hit:
                continue
            d.push()
            for l in hit:
                l.style, l.sticker, l.color, l.block = p["style"], p["sticker"], p["color"], p["block"]
                n += 1
            self.mark_thumb_dirty(d)
        self.canvas.rebuild()
        self.side.refresh()
        if n:
            self.status.showMessage(f"已更新 {n} 个「{PART_NAMES.get(part, part)}」的码", 5000)

    # ================================================================= 设置与主题
    def open_settings(self, page: int = 0):
        from .settings import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.nav.setCurrentRow(page)
        dlg.exec()
        self.on_settings_changed()

    def on_settings_changed(self):
        self.side.reload_stickers()
        self.side.sync_from_cfg()

    def on_library_changed(self):
        self.side.reload_stickers()
        self.canvas.viewport().update()
        for d in self.docs:
            self.mark_thumb_dirty(d)

    def apply_theme(self):
        theme.apply(QApplication.instance(), self.cfg["theme"])
        for b in getattr(self, "_nav_all", []):
            self._paint_nav_icon(b)
        self.canvas.apply_theme()
        self._placeholder = self._make_placeholder()
        for i in range(len(self.docs)):
            self._update_film_item(i)
        self.refresh_all()

    # ================================================================= 更新
    def check_updates(self, manual: bool = False):
        if self._upd is not None and self._upd.isRunning():
            return
        self._upd = UpdateChecker(self)
        self._upd.found.connect(lambda info: self._on_update(info, manual))
        if manual:
            self._upd.failed.connect(lambda e: QMessageBox.warning(
                self, "检查更新失败", f"GitHub 和镜像都连不上：\n{e}\n\n可以在「设置 → 常规 → 更新线路」换一条线路再试。"))
            self.status.showMessage("正在检查更新…", 3000)
        self._upd.start()

    def _on_update(self, info: dict, manual: bool):
        v = info.get("version", "")
        if not v or not is_newer(v):
            if manual:
                QMessageBox.information(self, "检查更新", f"已经是最新版本（v{__version__}）。")
            return
        if not manual and self.cfg["skip_version"] == v:
            return
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"{APP_NAME} v{v} 已发布（当前 v{__version__}）")
        notes = (info.get("notes") or "").strip()
        if notes:
            box.setInformativeText(notes[:900])
        b_now = box.addButton("立即更新", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        b_skip = box.addButton("跳过这个版本", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_skip:
            self.cfg["skip_version"] = v
            self.cfg.save()
            return
        if clicked is not b_now:
            return
        if not info.get("asset_url") or not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(info.get("page") or ""))
            return
        self._download_update(info)

    def _download_update(self, info: dict):
        dlg = QProgressDialog("正在下载新版本…", "取消", 0, 100, self)
        dlg.setWindowTitle("更新")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dl = Downloader(info["asset_url"], info["asset_name"], info.get("sha256", ""),
                        int(info.get("asset_size") or 0), self)
        self._dl = dl
        src = {"text": "正在下载新版本"}

        def prog(got, total):
            if total:
                dlg.setValue(min(100, int(got * 100 / total)))
                dlg.setLabelText(f"{src['text']}… {got / 1048576:.1f} / {total / 1048576:.1f} MB")

        def stat(text):
            src["text"] = text
            dlg.setLabelText(text + "…")

        def done(path):
            dlg.close()
            QMessageBox.information(self, "下载完成", "接下来会关闭软件并安装新版本，安装完成后自动重新打开。")
            try:
                launch_installer(path)
            except Exception as e:
                QMessageBox.warning(self, "无法启动安装程序", f"{e}\n\n安装包在：{path}")
                return
            self.cfg.save()
            dl.wait(5000)
            self._stop_threads()
            QApplication.quit()

        def fail(msg):
            dlg.close()
            if msg == "已取消":
                return
            box = QMessageBox(self)
            box.setWindowTitle("下载失败")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("新版本没有下载成功，可能是网络连不上 GitHub 和镜像。")
            box.setInformativeText(f"详细原因：{msg}\n\n可以稍后再试，或者打开下载页面手动下载安装包。")
            b_retry = box.addButton("重试", QMessageBox.ButtonRole.AcceptRole)
            b_page = box.addButton("打开下载页面", QMessageBox.ButtonRole.ActionRole)
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is b_retry:
                self._download_update(info)
            elif box.clickedButton() is b_page:
                QDesktopServices.openUrl(QUrl(info.get("page") or ""))

        dl.progress.connect(prog)
        dl.status.connect(stat)
        dl.done.connect(done)
        dl.failed.connect(fail)
        dlg.canceled.connect(dl.requestInterruption)
        dl.start()

    # ================================================================= 全局按键和滚轮
    def _typing(self) -> bool:
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QTextEdit, QAbstractSpinBox, QComboBox, QAbstractSlider,
                              QAbstractItemView)) and w is not self.film

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Wheel:
            return self._guard_wheel(obj, ev)
        if t not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not self.isActiveWindow() or QApplication.activeModalWidget() is not None:
            return False
        if self.current_page() != "mask":
            return False
        if self._typing():
            return False
        k = ev.key()
        if t == QEvent.Type.KeyRelease:
            if k == Qt.Key.Key_Space and not ev.isAutoRepeat():
                self.canvas.set_peek(self.b_peek.isChecked())
                return True
            return False
        mods = ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if mods not in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            return False
        if k == Qt.Key.Key_Space:
            if not ev.isAutoRepeat():
                self.canvas.set_peek(True)
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm_next()
            return True
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_layer()
            return True
        if k == Qt.Key.Key_F and mods == Qt.KeyboardModifier.NoModifier:
            self.canvas.fit()
            return True
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Escape):
            if obj is not self.canvas and obj is not self.canvas.viewport():
                if k == Qt.Key.Key_Escape:
                    self.canvas.select(None)
                else:
                    self.canvas.handle_arrow(k, bool(mods & Qt.KeyboardModifier.ShiftModifier),
                                             ev.isAutoRepeat())
                return True
        return False

    def _guard_wheel(self, obj, ev) -> bool:
        """鼠标滚轮经过下拉框、滑块、数字框时不改它们的值，而是继续滚动面板。"""
        if isinstance(obj, QScrollBar):
            return False
        w = obj
        while w is not None and not isinstance(w, (QComboBox, QAbstractSpinBox, QAbstractSlider)):
            if isinstance(w, QAbstractScrollArea) or not isinstance(w, QWidget):
                return False
            w = w.parentWidget()
        if w is None or w.hasFocus():
            return False
        p = w.parentWidget()
        while p is not None and not isinstance(p, QAbstractScrollArea):
            p = p.parentWidget()
        if p is not None:
            QApplication.sendEvent(p.verticalScrollBar(), ev)
        return True

    # ================================================================= 窗口
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths)

    def _stop_threads(self):
        for t in (self._worker, self._upd, self._dl):
            try:
                if t is not None and t.isRunning():
                    t.requestInterruption()
                    t.wait(20000)
            except RuntimeError:
                pass
        self.pool.clear()
        self.pool.waitForDone(10000)

    def closeEvent(self, e):
        self._stop_threads()
        self.cfg.save()
        super().closeEvent(e)
