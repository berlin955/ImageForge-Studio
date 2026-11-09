"""主窗口：左侧功能区，右侧看图。"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QIcon, QImage, QKeySequence,
                           QPainter, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from . import APP_NAME, APP_NAME_EN, AUTHOR, __version__, theme
from .canvas import Canvas
from .config import IMAGE_EXTS, icon_path, model_path
from .detector import Detector, plan_layers
from .exporter import output_name, render_doc, render_preview, save_image, unique_path
from .model import IMAGE_CACHE, ImageDoc, Layer, natural_key
from .panels import BatchPanel, EditPanel, ExportPanel
from .updater import Downloader, UpdateChecker, is_newer, launch_installer
from .widgets import button
from .workers import DetectWorker, ThumbTask

STATUS_COLORS = {"todo": "muted", "done": "accent", "none": "warn", "ok": "ok", "error": "danger"}


def app_icon() -> QIcon:
    p = icon_path()
    if p.exists():
        return QIcon(str(p))
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self, cfg, library):
        super().__init__()
        self.cfg = cfg
        self.library = library
        self.docs: list[ImageDoc] = []
        self.cur = -1
        self.active_part = "lower"
        self.busy = False
        self._detector = None
        self._det_lock = threading.Lock()
        self._worker = None
        self._after_detect = None
        self._edit_pushed = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._thumb_tasks = []
        self._thumb_dirty: set[str] = set()
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(300)
        self._thumb_timer.timeout.connect(self._flush_thumbs)

        self.setWindowTitle(f"{APP_NAME}  {APP_NAME_EN}")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)
        self._build()
        self._shortcuts()
        self.refresh_all()

    # ================================================================= 界面
    def _build(self):
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- 左侧 ----
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(372)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        brand = QWidget()
        bh = QHBoxLayout(brand)
        bh.setContentsMargins(16, 14, 16, 6)
        bh.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(34, 34))
        logo.setFixedSize(34, 34)
        names = QVBoxLayout()
        names.setSpacing(0)
        t1 = QLabel(APP_NAME)
        t1.setObjectName("Brand")
        t2 = QLabel(APP_NAME_EN.upper())
        t2.setObjectName("BrandSub")
        names.addWidget(t1)
        names.addWidget(t2)
        bh.addWidget(logo)
        bh.addLayout(names)
        bh.addStretch(1)
        sv.addWidget(brand)

        tabs = QWidget()
        th = QHBoxLayout(tabs)
        th.setContentsMargins(16, 0, 16, 0)
        th.setSpacing(18)
        self.tab_group = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.batch_panel = BatchPanel(self)
        self.edit_panel = EditPanel(self)
        self.export_panel = ExportPanel(self)
        for i, (text, w) in enumerate((("批量处理", self.batch_panel), ("编辑", self.edit_panel),
                                       ("导出", self.export_panel))):
            b = QPushButton(text)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tab_group.addButton(b, i)
            th.addWidget(b)
            self.stack.addWidget(w)
        th.addStretch(1)
        self.tab_group.idClicked.connect(self.show_tab)
        self.tab_group.button(0).setChecked(True)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setObjectName("SideFooter")
        sv.addWidget(tabs)
        sv.addWidget(sep)
        sv.addWidget(self.stack, 1)

        foot = QFrame()
        foot.setObjectName("SideFooter")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(14, 8, 14, 8)
        b_set = button("⚙  设置")
        b_set.setObjectName("Tool")
        b_set.clicked.connect(self.open_settings)
        ver = QLabel(f"v{__version__} · {AUTHOR}")
        ver.setObjectName("Muted")
        fh.addWidget(b_set)
        fh.addStretch(1)
        fh.addWidget(ver)
        sv.addWidget(foot)
        h.addWidget(side)

        # ---- 右侧 ----
        work = QWidget()
        work.setObjectName("Workspace")
        wv = QVBoxLayout(work)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(0)

        tb = QFrame()
        tb.setObjectName("Toolbar")
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(10, 6, 10, 6)
        tbh.setSpacing(6)
        self.b_prev = button("‹ 上一张", "Tool", "← / PageUp")
        self.b_next = button("下一张 ›", "Tool", "→ / PageDown")
        self.b_prev.clicked.connect(lambda: self.go(self.cur - 1))
        self.b_next.clicked.connect(lambda: self.go(self.cur + 1))
        self.idx_lbl = QLabel("")
        self.idx_lbl.setObjectName("Muted")
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet("font-weight:600")
        self.state_lbl = QLabel("")
        tbh.addWidget(self.b_prev)
        tbh.addWidget(self.idx_lbl)
        tbh.addWidget(self.b_next)
        tbh.addSpacing(10)
        tbh.addWidget(self.name_lbl, 1)
        tbh.addWidget(self.state_lbl)
        tbh.addSpacing(10)
        self.b_peek = button("对比原图", "Tool", "按住空格也可以")
        self.b_peek.setCheckable(True)
        self.b_peek.toggled.connect(lambda on: self.canvas.set_peek(on))
        self.b_fit = button("适应窗口", "Tool", "F")
        self.b_100 = button("100%", "Tool")
        self.zoom_lbl = QLabel("")
        self.zoom_lbl.setObjectName("Muted")
        self.zoom_lbl.setFixedWidth(48)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tbh.addWidget(self.b_peek)
        tbh.addWidget(self.b_fit)
        tbh.addWidget(self.b_100)
        tbh.addWidget(self.zoom_lbl)
        wv.addWidget(tb)

        self.canvas = Canvas(self.library)
        self.b_fit.clicked.connect(self.canvas.fit)
        self.b_100.clicked.connect(lambda: self.canvas.zoom_to(1.0))
        self.canvas.zoomChanged.connect(lambda s: self.zoom_lbl.setText(f"{round(s * 100)}%"))
        self.canvas.selectionChanged.connect(self._on_canvas_sel)
        self.canvas.beginEdit.connect(self.begin_edit)
        self.canvas.liveEdited.connect(self._on_live)
        self.canvas.edited.connect(self._on_edited)
        self.canvas.addRequested.connect(lambda pt: self.add_layer(self.active_part, pt.x(), pt.y()))
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.navigate.connect(lambda d: self.go(self.cur + d))

        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.addStretch(1)
        e1 = QLabel("把模特图片或文件夹拖到这里")
        e1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e1.setStyleSheet("font-size:18px;font-weight:700")
        e2 = QLabel("或在左侧「批量处理」里导入。导入后点「识别未处理的图片」，AI 会自动找出部位并贴码。")
        e2.setObjectName("Muted")
        e2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e2.setWordWrap(True)
        eb = button("导入图片…", "Primary")
        eb.clicked.connect(self.import_dialog)
        eb.setFixedWidth(160)
        ev.addWidget(e1)
        ev.addWidget(e2)
        ev.addSpacing(10)
        ev.addWidget(eb, 0, Qt.AlignmentFlag.AlignCenter)
        ev.addStretch(1)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.empty)
        self.view_stack.addWidget(self.canvas)
        wv.addWidget(self.view_stack, 1)

        self.film = QListWidget()
        self.film.setObjectName("Film")
        self.film.setViewMode(QListWidget.ViewMode.IconMode)
        self.film.setFlow(QListWidget.Flow.LeftToRight)
        self.film.setWrapping(False)
        self.film.setMovement(QListWidget.Movement.Static)
        self.film.setIconSize(QSize(96, 96))
        self.film.setGridSize(QSize(132, 146))
        self.film.setFixedHeight(166)
        self.film.setUniformItemSizes(True)
        self.film.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.film.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.film.currentRowChanged.connect(self._film_changed)
        wv.addWidget(self.film)
        h.addWidget(work, 1)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._placeholder = self._make_placeholder()

    def _make_placeholder(self) -> QIcon:
        pm = QPixmap(96, 96)
        pm.fill(QColor(theme.current()["card2"]))
        return QIcon(pm)

    def _shortcuts(self):
        def sc(keys, fn, ctx=Qt.ShortcutContext.WindowShortcut, widget=None):
            for k in keys if isinstance(keys, (list, tuple)) else [keys]:
                s = QShortcut(QKeySequence(k), widget or self)
                s.setContext(ctx)
                s.activated.connect(fn)

        wsc = Qt.ShortcutContext.WidgetWithChildrenShortcut
        sc("Ctrl+O", self.import_dialog)
        sc("Ctrl+E", self.export_batch)
        sc(["Ctrl+Z"], self.undo)
        sc(["Ctrl+Y", "Ctrl+Shift+Z"], self.redo)
        sc("PgDown", lambda: self.go(self.cur + 1))
        sc("PgUp", lambda: self.go(self.cur - 1))
        sc("Ctrl+,", self.open_settings)
        sc(["Delete", "Backspace"], self.delete_layer, wsc, self.canvas)
        sc("Ctrl+D", self.duplicate_layer, wsc, self.canvas)
        sc(["Return", "Enter"], self.confirm_next, wsc, self.canvas)
        sc("F", self.canvas.fit, wsc, self.canvas)

    def show_tab(self, i: int):
        self.stack.setCurrentIndex(i)
        b = self.tab_group.button(i)
        if b:
            b.setChecked(True)
        if i == 2:
            self.export_panel.refresh()

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
        if self.cfg["export"].get("scope") == "confirmed":
            return [d for d in self.docs if d.confirmed and not d.error]
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
            if key in have:
                continue
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
            task.signals.done.connect(self._thumb_done)
            self._thumb_tasks.append(task)
            self.pool.start(task)
        self.status.showMessage(f"已导入 {len(new)} 张图片", 5000)
        self.go(first)
        self.refresh_all()

    def _thumb_done(self, did, img: QImage, w, h):
        d = self.doc_by_id(did)
        self._thumb_tasks = [t for t in self._thumb_tasks if t.doc_id != did]
        if not d:
            return
        if img.isNull():
            d.error = "无法读取图片"
        else:
            d.thumb = img
            if not d.w:
                d.w, d.h = w, h
        row = self.docs.index(d)
        self._set_film_icon(d)
        self._update_film_item(row)

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
        it = self.film.item(self.docs.index(d))
        if not it:
            return
        img = render_preview(d, d.thumb, self.library)
        if img is not None and not img.isNull():
            it.setIcon(QIcon(QPixmap.fromImage(img)))

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

    def _update_film_item(self, row: int):
        it = self.film.item(row)
        if not it or row >= len(self.docs):
            return
        d = self.docs[row]
        it.setText(self._film_text(d))
        it.setForeground(QColor(theme.current()[STATUS_COLORS[d.status()]] if STATUS_COLORS[d.status()] != "muted"
                                else theme.current()["muted"]))

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
        self.refresh_all()

    def clear_all(self):
        if not self.docs or self.busy:
            return
        r = QMessageBox.question(self, "清空列表", f"从列表中移除全部 {len(self.docs)} 张图片？\n（只是移出列表，不会删除你电脑上的文件）")
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
        it = self.film.item(i)
        if it:
            self.film.scrollToItem(it)
        self._update_film_item(i)
        self.refresh_all()
        self.canvas.setFocus()

    def next_pending(self):
        order = list(range(self.cur + 1, len(self.docs))) + list(range(0, self.cur + 1))
        for i in order:
            if self.docs[i].status() in ("done", "none", "todo"):
                self.go(i)
                return
        self.status.showMessage("没有待审核的图片了", 4000)

    def confirm_next(self):
        d = self.cur_doc()
        if not d:
            return
        d.confirmed = True
        self._update_film_item(self.cur)
        for i in list(range(self.cur + 1, len(self.docs))) + list(range(0, self.cur)):
            if not self.docs[i].confirmed and not self.docs[i].error:
                self.go(i)
                return
        self.refresh_all()
        self.status.showMessage("全部图片都已确认，可以去「导出」了", 6000)

    # ================================================================= 刷新
    def refresh_all(self):
        d = self.cur_doc()
        self.view_stack.setCurrentIndex(1 if d else 0)
        n = len(self.docs)
        self.idx_lbl.setText(f"{self.cur + 1} / {n}" if d else "")
        self.name_lbl.setText(d.name if d else "")
        if d:
            col = theme.current()[STATUS_COLORS[d.status()]] if STATUS_COLORS[d.status()] != "muted" else theme.current()["muted"]
            self.state_lbl.setText(d.status_text() + (f"　{d.w}×{d.h}" if d.w else ""))
            self.state_lbl.setStyleSheet(f"color:{col}")
        else:
            self.state_lbl.setText("")
        self.b_prev.setEnabled(self.cur > 0)
        self.b_next.setEnabled(0 <= self.cur < n - 1)
        self.batch_panel.refresh()
        self.edit_panel.refresh()
        self.export_panel.refresh()

    def _refresh_doc_state(self):
        if self.cur >= 0:
            self._update_film_item(self.cur)
            self.mark_thumb_dirty()
        d = self.cur_doc()
        if d:
            col = theme.current()[STATUS_COLORS[d.status()]] if STATUS_COLORS[d.status()] != "muted" else theme.current()["muted"]
            self.state_lbl.setText(d.status_text() + (f"　{d.w}×{d.h}" if d.w else ""))
            self.state_lbl.setStyleSheet(f"color:{col}")
        self.batch_panel.refresh()

    # ================================================================= 编辑
    def _on_canvas_sel(self, layer):
        self.edit_panel.refresh()
        if layer is not None and self.stack.currentIndex() != 1:
            self.show_tab(1)

    def begin_edit(self):
        d = self.cur_doc()
        if d:
            d.push()

    def _on_live(self):
        self.edit_panel.sync_geometry()

    def _on_edited(self):
        self.edit_panel.sync_geometry()
        self._refresh_doc_state()

    def edit_layer(self, fn, push: bool = True, rebuild_panel: bool = False):
        d = self.cur_doc()
        L = self.canvas.selected_layer()
        if not d or not L:
            return
        if push:
            d.push()
        fn(L)
        self.canvas.update_layer(L)
        self.mark_thumb_dirty(d)
        if rebuild_panel:
            self.edit_panel.refresh()

    def add_layer(self, part: str, x: float | None = None, y: float | None = None):
        d = self.cur_doc()
        if not d or not d.w:
            self.status.showMessage("先导入图片", 3000)
            return
        self.active_part = part
        p = self.cfg.part(part)
        base = {"lower": (0.17, 0.11), "crack": (0.07, 0.17), "areola": (0.075, 0.075),
                "custom": (0.12, 0.12)}[part]
        if x is None:
            n = len(d.layers)
            x = d.w / 2 + (n % 5) * d.w * 0.03
            y = d.h / 2 + (n % 5) * d.w * 0.03
        d.push()
        L = Layer(part=part, style=p["style"], sticker=p["sticker"], color=p["color"], block=p["block"],
                  opacity=p.get("opacity", 1.0), cx=x, cy=y, w=base[0] * d.w, h=base[1] * d.w)
        d.layers.append(L)
        self.canvas.rebuild(select_id=L.id)
        self._refresh_doc_state()
        self.show_tab(1)
        self.edit_panel.refresh()

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
        d.confirmed = d.confirmed and bool(d.layers)
        self.canvas.rebuild(select_id="")
        self._refresh_doc_state()
        self.edit_panel.refresh()

    def clear_layers(self):
        d = self.cur_doc()
        if not d or not d.layers:
            return
        d.push()
        d.layers = []
        d.confirmed = False
        self.canvas.rebuild(select_id="")
        self._refresh_doc_state()
        self.edit_panel.refresh()

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
        self.edit_panel.refresh()
        self.status.showMessage(f"已沿用上一张的 {len(p.layers)} 个码", 4000)

    def set_layer_as_default(self):
        L = self.canvas.selected_layer()
        if not L:
            return
        p = self.cfg.part(L.part)
        p.update(style=L.style, sticker=L.sticker, color=L.color, block=L.block, opacity=L.opacity)
        self.cfg.save()
        from .config import PART_NAMES
        self.status.showMessage(f"已把这个样式设为「{PART_NAMES.get(L.part, L.part)}」的默认样式", 5000)

    def undo(self):
        d = self.cur_doc()
        if d and d.undo():
            self.canvas.rebuild()
            self._refresh_doc_state()
            self.edit_panel.refresh()

    def redo(self):
        d = self.cur_doc()
        if d and d.redo():
            self.canvas.rebuild()
            self._refresh_doc_state()
            self.edit_panel.refresh()

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
        if self.busy:
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
        self._replace = mode in ("all", "current")
        self._after_detect = then
        self._det_found = 0
        self._det_docs = len(targets)
        self.set_busy(True)
        self.batch_panel.set_progress(0, len(targets), "正在加载识别模型…")
        w = DetectWorker([(d.id, str(d.path), d.name) for d in targets],
                         float(self.cfg["detect"]["threshold"]), self.get_detector, self)
        w.progress.connect(self._det_progress)
        w.result.connect(self._det_result)
        w.failed.connect(self._det_failed)
        w.fatal.connect(self._det_fatal)
        w.finished.connect(self._det_finished)
        self._worker = w
        w.start()

    def stop_detect(self):
        if self._worker:
            self._worker.requestInterruption()
            self._after_detect = None

    def _det_progress(self, i, n, name):
        self.batch_panel.set_progress(i, n, f"正在识别 {i + 1}/{n}：{name}" if i < n else "")
        self.status.showMessage(f"正在识别 {min(i + 1, n)}/{n}", 2000)

    def _det_result(self, did, w, h, dets):
        d = self.doc_by_id(did)
        if not d:
            return
        d.w, d.h = w, h
        layers = plan_layers(dets, w, h, self.cfg)
        if self._replace or not d.layers:
            d.push()
            d.layers = layers
            d.confirmed = False
        d.detected = True
        d.error = ""
        self._det_found += len(layers)
        row = self.docs.index(d)
        self._update_film_item(row)
        self.mark_thumb_dirty(d)
        if row == self.cur:
            self.canvas.rebuild(select_id="")
            self._refresh_doc_state()
            self.edit_panel.refresh()

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
        self.batch_panel.set_progress(0, 0, "")
        self.status.showMessage(f"识别完成：{self._det_docs} 张图片，共 {self._det_found} 个码", 8000)
        self.refresh_all()
        then, self._after_detect = self._after_detect, None
        if then:
            QTimer.singleShot(0, then)

    def set_busy(self, on: bool):
        self.busy = on
        self.batch_panel.refresh()
        self.export_panel.refresh()

    # ================================================================= 导出
    def choose_out_dir(self) -> bool:
        cur = self.cfg["export"].get("dir") or self.cfg["last_dir"]
        d = QFileDialog.getExistingDirectory(self, "选择保存位置", cur)
        if not d:
            return False
        self.cfg["export"]["dir"] = d
        self.cfg.save()
        self.export_panel.load()
        self.batch_panel.refresh()
        return True

    def _ensure_out_dir(self) -> Path | None:
        d = self.cfg["export"].get("dir")
        if not d and not self.choose_out_dir():
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
            QMessageBox.information(self, "没有可导出的图片",
                                    "列表里没有符合导出范围的图片。导出范围设成「仅已确认」时，需要先确认图片。")
            return
        self._export(docs)

    def _export(self, docs: list[ImageDoc]) -> int:
        out = self._ensure_out_dir()
        if out is None or self.busy:
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
            self.refresh_all()
        msg = f"已导出 {ok} 张图片到：\n{out}"
        if errors:
            msg += f"\n\n有 {len(errors)} 张没有成功：\n" + "\n".join(errors[:8])
        if errors:
            QMessageBox.warning(self, "导出完成", msg)
        else:
            self.status.showMessage(f"已导出 {ok} 张图片到 {out}", 10000)
        if ok and ex.get("open_after", True):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return ok

    def auto_mask(self):
        """一键打码：识别所有未处理的图片，完成后打开预览。"""
        if not self.docs or self.busy:
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
            self.show_tab(1)
        elif r == PreviewDialog.SAVE:
            self.export_batch()

    # ================================================================= 贴图
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
        """把某个部位的默认样式应用到所有图片上已有的该部位的码。"""
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
        self.edit_panel.refresh()
        from .config import PART_NAMES
        self.status.showMessage(f"已更新 {n} 个「{PART_NAMES.get(part, part)}」的码", 5000)

    # ================================================================= 设置与主题
    def open_settings(self):
        from .settings import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        self.on_settings_changed()

    def on_settings_changed(self):
        self.batch_panel.sync_from_cfg()
        self.batch_panel.reload_stickers()
        self.export_panel.load()
        self.edit_panel.refresh()

    def on_library_changed(self):
        self.edit_panel.reload_stickers()
        self.batch_panel.reload_stickers()
        self.canvas.viewport().update()
        for d in self.docs:
            self.mark_thumb_dirty(d)

    def apply_theme(self):
        app = QApplication.instance()
        theme.apply(app, self.cfg["theme"])
        self.canvas.apply_theme()
        self._placeholder = self._make_placeholder()
        for i in range(len(self.docs)):
            self._update_film_item(i)
        self.refresh_all()

    # ================================================================= 更新
    def check_updates(self, manual: bool = False):
        if getattr(self, "_upd", None) and self._upd.isRunning():
            return
        self._upd = UpdateChecker(self)
        self._upd.found.connect(lambda info: self._on_update(info, manual))
        if manual:
            self._upd.failed.connect(lambda e: QMessageBox.warning(self, "检查更新失败", f"无法连接到 GitHub：\n{e}"))
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
            QApplication.quit()

        def fail(msg):
            dlg.close()
            if msg == "已取消":
                return
            box = QMessageBox(self)
            box.setWindowTitle("下载失败")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("新版本没有下载成功，可能是网络连不上 GitHub。")
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

    # ================================================================= 窗口
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths)

    def closeEvent(self, e):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(3000)
        self.cfg.save()
        super().closeEvent(e)
