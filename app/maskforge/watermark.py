"""批量水印：给一批图加上 Logo / 文字水印。

- 默认放在模特身上偏右的位置（小臂或大腿上），用姿态模型找手肘、手腕、髋、膝盖，避开脸和已经打的码；
  找不到人时放在右侧偏下。也可以改成固定角落。
- 每张图的水印都能单独拖动、缩放、自由旋转（和打码页的码一样操作），调过的会记住。
- 水印库：可以存好几个图片 / 文字水印，随时换；可以只换某一张。
- 平铺防盗：整张图斜着铺一层很淡的水印。
- 很长的详情图：每隔一屏自动再放一个。
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QIcon, QImage, QImageReader, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QProgressDialog, QVBoxLayout, QWidget)

from .model import Layer, load_qimage
from .widgets import Card, ColorButton, Segmented, SliderRow, button, muted, row, scroll_page

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
PREVIEW_LONG = 1600          # 预览用的图最长边（导出时按原图尺寸重新算）

# 九宫格位置
CORNERS = [("tl", "左上"), ("tc", "上中"), ("tr", "右上"), ("ml", "左中"), ("mc", "正中"), ("mr", "右中"),
           ("bl", "左下"), ("bc", "下中"), ("br", "右下")]

NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP, L_KNEE, R_KNEE = range(15)


# ================================================================ 水印库
class WatermarkLibrary:
    """水印图案都存在数据目录的 watermarks 文件夹里（透明 PNG）。
    image() 同时认打码用的贴图（画打过码的图时要用到），所以可以直接交给画布 / 导出用。"""

    def __init__(self, stickers, folder=None):
        from .config import data_dir
        self.stickers = stickers
        self.folder = Path(folder) if folder else data_dir() / "watermarks"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, QImage] = {}

    def items(self) -> list[tuple[str, str]]:
        files = [f for f in self.folder.iterdir() if f.is_file() and f.suffix.lower() == ".png"]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return [(f"wm:{f.name}", f.stem) for f in files]

    def image(self, sid: str) -> QImage:
        if sid and sid.startswith("wm:"):
            img = self._cache.get(sid)
            if img is None:
                img = QImage(str(self.folder / sid[3:]))
                if img.isNull():
                    img = _placeholder_mark()
                self._cache[sid] = img
            return img
        return self.stickers.image(sid)

    def exists(self, sid: str | None) -> bool:
        return bool(sid) and sid.startswith("wm:") and (self.folder / sid[3:]).exists()

    def _target(self, stem: str) -> Path:
        stem = re.sub(r'[\\/:*?"<>|\s]+', "_", stem)[:40] or "水印"
        t = self.folder / f"{stem}.png"
        n = 2
        while t.exists():
            t = self.folder / f"{stem}_{n}.png"
            n += 1
        return t

    def add_image(self, src) -> str:
        r = QImageReader(str(src))
        r.setAutoTransform(True)
        img = r.read()
        if img.isNull():
            raise ValueError("无法读取这张图片")
        if max(img.width(), img.height()) > 1600:
            img = img.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        img = trim_transparent(img.convertToFormat(QImage.Format.Format_ARGB32))
        t = self._target(Path(src).stem)
        if not img.save(str(t), "PNG"):
            raise ValueError("保存水印失败")
        return f"wm:{t.name}"

    def add_text(self, text: str, font_stem: str | None, color: str, stroke: str | None = None,
                 shadow: bool = False, weight: int | None = None) -> str:
        img = render_text_mark(text, font_stem, color, stroke, shadow, weight)
        t = self._target("文字_" + text[:12])
        if not img.save(str(t), "PNG"):
            raise ValueError("保存水印失败")
        return f"wm:{t.name}"

    def remove(self, sid: str):
        if sid.startswith("wm:"):
            try:
                (self.folder / sid[3:]).unlink()
            except Exception:
                pass
            self._cache.pop(sid, None)


def _placeholder_mark() -> QImage:
    return render_text_mark("水印", None, "#ffffff", "#000000")


def trim_transparent(img: QImage) -> QImage:
    """去掉四周透明的空白（上传的 Logo 常带一大圈透明边，会让大小、位置不好调）。"""
    if not img.hasAlphaChannel():
        return img
    import numpy as np
    w, h = img.width(), img.height()
    ptr = img.constBits()
    a = np.frombuffer(ptr, np.uint8, img.bytesPerLine() * h).reshape(h, img.bytesPerLine())[:, :w * 4]
    alpha = a.reshape(h, w, 4)[:, :, 3]
    ys, xs = np.nonzero(alpha > 8)
    if not len(xs):
        return img
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    pad = 2
    return img.copy(max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad) - max(0, x0 - pad),
                    min(h, y1 + pad) - max(0, y0 - pad))


def render_text_mark(text: str, font_stem: str | None, color: str, stroke: str | None = None,
                     shadow: bool = False, weight: int | None = None) -> QImage:
    """把文字画成一张透明底的水印图（大字号画，缩小时清楚）。"""
    from . import fonts
    f = fonts.qfont(font_stem, weight) if font_stem else QFont("Microsoft YaHei UI")
    if not font_stem and weight:
        f.setWeight(QFont.Weight(int(weight)))
    f.setPixelSize(160)
    fm = QFontMetricsF(f)
    lines = (text or "水印").split("\n")
    sw = 10.0 if stroke else 0.0
    W = int(max(fm.horizontalAdvance(t) for t in lines) + sw * 2 + 40)
    lh = fm.height()
    H = int(lh * len(lines) + sw * 2 + 40)
    img = QImage(max(8, W), max(8, H), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    path = QPainterPath()
    for i, t in enumerate(lines):
        x = (W - fm.horizontalAdvance(t)) / 2
        path.addText(QPointF(x, 20 + sw + fm.ascent() + i * lh), f, t)
    if shadow:
        p.save()
        p.translate(5, 6)
        p.fillPath(path, QColor(0, 0, 0, 90))
        p.restore()
    if stroke:
        pen = QPen(QColor(stroke), sw * 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(path, pen)
    p.fillPath(path, QColor(color))
    p.end()
    return trim_transparent(img)


# ================================================================ 自动摆放（不依赖界面，方便测试）
def _ok(kp, i, thr=0.35) -> bool:
    return kp is not None and kp[i, 2] >= thr


def body_points(kp, prefer: str = "forearm") -> list[tuple[float, float, str]]:
    """模特身上可以放水印的点，按优先顺序：画面右侧的小臂 / 大腿在前。"""
    if kp is None:
        return []
    arms, legs = [], []
    for el, wr in ((L_EL, L_WR), (R_EL, R_WR)):
        if _ok(kp, el) and _ok(kp, wr):
            arms.append(((kp[el, 0] + kp[wr, 0]) / 2, (kp[el, 1] + kp[wr, 1]) / 2, "arm"))
    for hip, kn in ((L_HIP, L_KNEE), (R_HIP, R_KNEE)):
        if _ok(kp, hip) and _ok(kp, kn):
            # 大腿中间偏上一点（靠近膝盖的地方常被挡住）
            legs.append((kp[hip, 0] * 0.55 + kp[kn, 0] * 0.45, kp[hip, 1] * 0.55 + kp[kn, 1] * 0.45, "leg"))
    arms.sort(key=lambda p: -p[0])
    legs.sort(key=lambda p: -p[0])
    return arms + legs if prefer != "thigh" else legs + arms


def face_rect(kp) -> QRectF | None:
    if kp is None:
        return None
    pts = [kp[i, :2] for i in (NOSE, L_EYE, R_EYE, L_EAR, R_EAR) if kp[i, 2] >= 0.35]
    if not pts:
        return None
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    s = max(30.0, (max(xs) - min(xs)) * 1.6)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return QRectF(cx - s, cy - s * 1.2, s * 2, s * 2.4)


def private_rect(kp) -> QRectF | None:
    """两髋之间往下那一块（裆部 / 臀部中间）：水印不要压在这里。"""
    if kp is None or kp[L_HIP, 2] < 0.35 or kp[R_HIP, 2] < 0.35:
        return None
    x1, y1 = float(kp[L_HIP, 0]), float(kp[L_HIP, 1])
    x2, y2 = float(kp[R_HIP, 0]), float(kp[R_HIP, 1])
    d = max(20.0, math.hypot(x2 - x1, y2 - y1))
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return QRectF(cx - d * 0.25, cy - d * 0.15, d * 0.5, d * 0.85)


def corner_point(key: str, W: float, H: float, w: float, h: float, margin: float) -> tuple[float, float]:
    m = min(W, H) * margin
    col = key[1] if len(key) == 2 else "c"
    rowk = key[0]
    x = {"l": m + w / 2, "c": W / 2, "r": W - m - w / 2}[col]
    y = {"t": m + h / 2, "m": H / 2, "b": H - m - h / 2}[rowk]
    return x, y


def auto_marks(W: float, H: float, aspect: float, wc: dict, kp=None, avoid: list[QRectF] | None = None) -> list[dict]:
    """算出这张图默认的水印位置。返回 [{cx, cy, w, h, rot}]（这张图的像素坐标）。
    aspect = 水印图宽 / 高。"""
    avoid = list(avoid or [])
    fr = face_rect(kp)
    if fr is not None:
        avoid.append(fr)
    pr = private_rect(kp)
    if pr is not None:
        avoid.append(pr)
    tall = H > W * 2.0
    w = W * float(wc.get("size", 0.16))
    h = w / max(0.05, aspect)
    rot = float(wc.get("rot", 0.0))
    place = wc.get("place", "body")

    def clamp(x, y):
        x = min(max(x, w / 2), W - w / 2)
        y = min(max(y, h / 2), H - h / 2)
        return x, y

    def free(x, y) -> bool:
        r = QRectF(x - w / 2, y - h / 2, w, h)
        return not any(r.intersects(a) for a in avoid)

    marks = []
    if tall:
        # 详情长图：每一屏（约 1.4 倍宽）放一个，位置按设置的角落 / 右侧
        key = wc.get("corner", "br") if place == "corner" else "mr"
        step = W * 1.4
        x, _y = corner_point(key, W, step, w, h, float(wc.get("margin", 0.03)))
        y = step * (0.62 if place != "corner" else (0.5 if key[0] == "m" else (0.08 if key[0] == "t" else 0.92)))
        n = 0
        while y < H and n < 40:
            cx, cy = clamp(x, y)
            marks.append({"cx": cx, "cy": cy, "w": w, "h": h, "rot": rot})
            if not wc.get("long_repeat", True):
                break
            y += step
            n += 1
        return marks
    if place == "corner":
        cx, cy = corner_point(wc.get("corner", "br"), W, H, w, h, float(wc.get("margin", 0.03)))
        return [{"cx": cx, "cy": cy, "w": w, "h": h, "rot": rot}]
    for (px, py, kind) in body_points(kp, wc.get("prefer", "forearm")):
        # 「身上偏右一点」：在小臂 / 大腿中点的基础上稍微往画面右边挪（大腿往外多挪一点，离裆部远些）
        cx, cy = clamp(px + w * (0.3 if kind == "leg" else 0.15), py)
        if free(cx, cy):
            return [{"cx": cx, "cy": cy, "w": w, "h": h, "rot": rot}]
    # 找不到人（或者都被挡住）：右侧偏下
    for fx, fy in ((0.74, 0.62), (0.74, 0.8), (0.26, 0.8)):
        cx, cy = clamp(W * fx, H * fy)
        if free(cx, cy):
            break
    return [{"cx": cx, "cy": cy, "w": w, "h": h, "rot": rot}]


def draw_tile(p: QPainter, W: float, H: float, mark: QImage, tc: dict):
    """斜着平铺满整张图的淡水印（防盗图）。"""
    if mark is None or mark.isNull():
        return
    w = W * float(tc.get("size", 0.18))
    h = w * mark.height() / max(1, mark.width())
    gap = float(tc.get("gap", 1.2))
    sx, sy = w * (1 + gap), max(h * 3, w * (0.5 + gap * 0.6))
    p.save()
    p.setOpacity(max(0.02, min(1.0, float(tc.get("opacity", 0.12)))))
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.translate(W / 2, H / 2)
    p.rotate(float(tc.get("angle", -30)))
    R = math.hypot(W, H) / 2 + max(sx, sy)
    j = 0
    y = -R
    while y < R:
        off = (sx / 2) if j % 2 else 0.0
        x = -R + off
        while x < R:
            p.drawImage(QRectF(x - w / 2, y - h / 2, w, h), mark)
            x += sx
        y += sy
        j += 1
    p.restore()


# ================================================================ 新建文字水印
class TextMarkDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("新建文字水印")
        self.setMinimumWidth(420)
        from . import fonts
        v = QVBoxLayout(self)
        v.setSpacing(10)
        self.text = QLineEdit()
        self.text.setPlaceholderText("例如：店铺名 / 原创拍摄 盗图必究（可以用 \\n 换行）")
        v.addWidget(QLabel("文字"))
        v.addWidget(self.text)
        self.font = QComboBox()
        self.font.addItem("微软雅黑（电脑自带）", None)
        for g in fonts.group_list():
            for wgt, stem in sorted(g["weights"].items()):
                self.font.addItem(f"{g['name']} {fonts.WEIGHT_NAMES.get(wgt, wgt)}", stem)
        i = self.font.findText("思源黑体 粗体")
        if i >= 0:
            self.font.setCurrentIndex(i)
        v.addWidget(QLabel("字体"))
        v.addWidget(self.font)
        self.color = ColorButton("#ffffff")
        self.stroke_on = QCheckBox("描边")
        self.stroke_on.setChecked(True)
        self.stroke = ColorButton("#333333")
        self.shadow = QCheckBox("阴影")
        v.addLayout(row(QLabel("颜色"), self.color, self.stroke_on, self.stroke, self.shadow))
        self.pv = QLabel()
        self.pv.setMinimumHeight(90)
        self.pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pv.setStyleSheet("background:#8a8f99;border-radius:8px")
        v.addWidget(self.pv)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("保存到水印库")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for sig in (self.text.textChanged, self.font.currentIndexChanged, self.color.colorChanged,
                    self.stroke_on.toggled, self.stroke.colorChanged, self.shadow.toggled):
            sig.connect(self._preview)
        self._preview()

    def values(self) -> dict:
        return {"text": (self.text.text().strip() or "水印").replace("\\n", "\n"),
                "font_stem": self.font.currentData(), "color": self.color._color,
                "stroke": self.stroke._color if self.stroke_on.isChecked() else None,
                "shadow": self.shadow.isChecked()}

    def _preview(self, *_):
        v = self.values()
        img = render_text_mark(v["text"], v["font_stem"], v["color"], v["stroke"], v["shadow"])
        pm = QPixmap.fromImage(img).scaled(360, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.pv.setPixmap(pm)


# ================================================================ 页面
class WatermarkPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cfg = mw.cfg
        self.wc = self.cfg["watermark"]
        self.lib = WatermarkLibrary(mw.library)
        self.items: list[dict] = []        # {"key", "path", "doc_id", "name"}
        self.state: dict[str, dict] = {}   # key -> {"layers": [Layer], "manual": bool, "mark": sid|None, "k": 预览缩放}
        self._prev: dict[str, QImage] = {}
        self._kp: dict[str, object] = {}
        self.cur = -1
        self._loading = False
        self._undo: list[tuple[str, list]] = []
        self._redo: list[tuple[str, list]] = []
        self._film_keys: list[str] = []
        self._auto_loaded = False

        from .canvas import Canvas
        from .pages import page_header
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top, th = page_header("批量水印", "默认放在模特右侧的小臂或大腿上；每张都能单独拖动、缩放、旋转")
        self.b_export = button("导出全部", "Primary")
        self.b_export.clicked.connect(self.export_all)
        th.addWidget(self.b_export)
        v.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(360)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self._build_side())
        body.addWidget(side)

        work = QWidget()
        work.setObjectName("Workspace")
        wv = QVBoxLayout(work)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(0)
        tb = QFrame()
        tb.setObjectName("Toolbar")
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(12, 6, 12, 6)
        self.b_prev = button("‹", "Tool")
        self.b_next = button("›", "Tool")
        for b in (self.b_prev, self.b_next):
            b.setFixedWidth(36)
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:700")
        b_reset = button("恢复自动位置", "Tool", "这张图的水印回到自动算出的位置")
        b_reset.clicked.connect(self.reset_current)
        b_all = button("位置用到全部", "Tool", "把这张图上水印的位置、大小、角度（按比例）用到所有图")
        b_all.clicked.connect(self.apply_to_all)
        b_one = button("只导出这一张", "Tool")
        b_one.clicked.connect(self.export_current)
        for w in (self.b_prev, self.b_next, self.title):
            tbh.addWidget(w)
        tbh.addStretch(1)
        for w in (b_reset, b_all, b_one):
            tbh.addWidget(w)
        wv.addWidget(tb)

        self.canvas = Canvas(self.lib)
        self.canvas.liveEdited.connect(self._live_edit)
        self.canvas.beginEdit.connect(self._begin_edit)
        self.canvas.edited.connect(self._end_edit)
        self.canvas.navigate.connect(self.step)
        self.canvas.filesDropped.connect(self.add_paths)
        wv.addWidget(self.canvas, 1)
        self.hint = muted("拖动水印换位置；拖四个角缩放；拖上方圆形按钮或角外面一点旋转（[ / ] 键每次 5°）；"
                          "按住空格看不带水印的样子；← → 切换图片。")
        self.hint.setContentsMargins(14, 4, 14, 4)
        wv.addWidget(self.hint)

        fb = QFrame()
        fb.setObjectName("FilmBar")
        fv = QVBoxLayout(fb)
        fv.setContentsMargins(10, 6, 10, 2)
        self.film = QListWidget()
        self.film.setObjectName("Film")
        self.film.setViewMode(QListWidget.ViewMode.IconMode)
        self.film.setFlow(QListWidget.Flow.LeftToRight)
        self.film.setWrapping(False)
        self.film.setMovement(QListWidget.Movement.Static)
        self.film.setIconSize(QSize(96, 96))
        self.film.setGridSize(QSize(118, 120))
        self.film.setFixedHeight(130)
        self.film.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.film.currentRowChanged.connect(self._film_changed)
        fv.addWidget(self.film)
        wv.addWidget(fb)
        body.addWidget(work, 1)
        v.addLayout(body, 1)
        self.setAcceptDrops(True)
        self.load_settings()

    # ---------------------------------------------------------------- 侧边栏
    def _build_side(self):
        c0 = Card("要加水印的图")
        self.count = muted("")
        c0.add(self.count)
        b_docs = button("用素材里的图", "", "素材页导入的图（打过码的带着码）")
        b_docs.clicked.connect(self.load_from_docs)
        b_add = button("添加图片…", "", "例如导出好的主图、规格图、详情图；也可以直接把图片或文件夹拖到画布上")
        b_add.clicked.connect(self.add_dialog)
        b_clear = button("清空", "Ghost")
        b_clear.clicked.connect(self.clear_items)
        c0.add(row(b_docs, b_add, b_clear))
        self.use_mask = QCheckBox("素材里的图带上打码")
        self.use_mask.toggled.connect(lambda on: self._set("use_mask", on, rebuild_bg=True))
        c0.add(self.use_mask)

        c1 = Card("水印图案")
        c1.add(muted("点一下：所有图都换成这个。右键：只换当前这张、删除。"))
        self.marks = QListWidget()
        self.marks.setObjectName("Layers")
        self.marks.setViewMode(QListWidget.ViewMode.IconMode)
        self.marks.setIconSize(QSize(72, 44))
        self.marks.setGridSize(QSize(88, 72))
        self.marks.setMovement(QListWidget.Movement.Static)
        self.marks.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.marks.setFixedHeight(160)
        self.marks.itemClicked.connect(self._mark_clicked)
        self.marks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.marks.customContextMenuRequested.connect(self._mark_menu)
        c1.add(self.marks)
        b_up = button("上传图片水印", "", "透明底 PNG 的 Logo 最好")
        b_up.clicked.connect(self.upload_mark)
        b_txt = button("新建文字水印")
        b_txt.clicked.connect(self.new_text_mark)
        c1.add(row(b_up, b_txt))

        c2 = Card("默认位置")
        self.place = Segmented([("body", "模特身上"), ("corner", "固定位置")])
        self.place.changed.connect(lambda k: self._set("place", k, reauto=True, refresh_side=True))
        c2.add(self.place)
        self.prefer = Segmented([("forearm", "小臂优先"), ("thigh", "大腿优先")])
        self.prefer.changed.connect(lambda k: self._set("prefer", k, reauto=True))
        self.prefer_box = QWidget()
        pb = QVBoxLayout(self.prefer_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(6)
        pb.addWidget(self.prefer)
        pb.addWidget(muted("放在画面右侧那条小臂（手肘到手腕）或大腿上，自动避开脸和打的码；认不出人时放在右侧偏下。"))
        c2.add(self.prefer_box)
        self.corner = QComboBox()
        for k, n in CORNERS:
            self.corner.addItem(n, k)
        self.corner.currentIndexChanged.connect(lambda _i: self._set("corner", self.corner.currentData(), reauto=True))
        self.margin = SliderRow("边距", 0, 0.15, 0, " %", factor=100)
        self.margin.valueChanged.connect(lambda v: self._set("margin", round(v, 3), reauto=True))
        self.corner_box = QWidget()
        cb = QVBoxLayout(self.corner_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(6)
        cb.addLayout(row(QLabel("位置"), self.corner))
        cb.addWidget(self.margin)
        c2.add(self.corner_box)
        self.long_repeat = QCheckBox("很长的详情图每一屏放一个")
        self.long_repeat.toggled.connect(lambda on: self._set("long_repeat", on, reauto=True))
        c2.add(self.long_repeat)

        c3 = Card("大小和透明度")
        self.size = SliderRow("大小", 0.03, 0.6, 0, " %", factor=100)
        self.size.valueChanged.connect(lambda v: self._set("size", round(v, 3), resize=True))
        self.opacity = SliderRow("不透明", 0.05, 1.0, 0, " %", factor=100)
        self.opacity.valueChanged.connect(lambda v: self._set("opacity", round(v, 3), restyle=True))
        self.rot = SliderRow("角度", -180, 180, 0, "°")
        self.rot.valueChanged.connect(lambda v: self._set("rot", round(v, 1), reauto=True))
        for w in (self.size, self.opacity, self.rot):
            c3.add(w)
        c3.add(muted("大小按图片宽度的百分比算，不同尺寸的图看起来一样大。调过位置的图，大小和角度保持你调的样子。"))

        c4 = Card("平铺防盗（可选）")
        self.tile_on = QCheckBox("整张图斜着铺一层淡水印")
        self.tile_on.toggled.connect(lambda on: self._set_tile("enabled", on))
        c4.add(self.tile_on)
        self.tile_box = QWidget()
        tb = QVBoxLayout(self.tile_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(6)
        self.tile_op = SliderRow("不透明", 0.02, 0.6, 0, " %", factor=100)
        self.tile_op.valueChanged.connect(lambda v: self._set_tile("opacity", round(v, 3)))
        self.tile_size = SliderRow("大小", 0.05, 0.5, 0, " %", factor=100)
        self.tile_size.valueChanged.connect(lambda v: self._set_tile("size", round(v, 3)))
        self.tile_gap = SliderRow("间距", 0.3, 3.0, 1, " 倍")
        self.tile_gap.valueChanged.connect(lambda v: self._set_tile("gap", round(v, 2)))
        self.tile_angle = SliderRow("角度", -90, 90, 0, "°")
        self.tile_angle.valueChanged.connect(lambda v: self._set_tile("angle", round(v, 1)))
        for w in (self.tile_op, self.tile_size, self.tile_gap, self.tile_angle):
            tb.addWidget(w)
        tb.addWidget(muted("平铺用的是当前选中的水印图案。"))
        c4.add(self.tile_box)

        c5 = Card("导出")
        self.suffix = QLineEdit()
        self.suffix.setPlaceholderText("文件名后缀，例如 _水印")
        self.suffix.textChanged.connect(lambda t: self._set("suffix", t))
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("导出文件夹里的子文件夹名")
        self.folder.textChanged.connect(lambda t: self._set("folder", t.strip() or "水印"))
        c5.add(row(QLabel("后缀"), self.suffix))
        c5.add(row(QLabel("子文件夹"), self.folder))
        c5.add(muted("保持原图尺寸和格式（jpg / png / webp），不会覆盖原图。"))

        area, vv = scroll_page(c0, c1, c2, c3, c4, c5)
        vv.setSpacing(10)
        return area

    def load_settings(self):
        self._loading = True
        wc = self.wc
        self.use_mask.setChecked(bool(wc.get("use_mask", True)))
        self.place.set_value(wc.get("place", "body"))
        self.prefer.set_value(wc.get("prefer", "forearm"))
        self.corner.setCurrentIndex(max(0, self.corner.findData(wc.get("corner", "br"))))
        self.margin.set_value(float(wc.get("margin", 0.03)))
        self.long_repeat.setChecked(bool(wc.get("long_repeat", True)))
        self.size.set_value(float(wc.get("size", 0.16)))
        self.opacity.set_value(float(wc.get("opacity", 0.85)))
        self.rot.set_value(float(wc.get("rot", 0.0)))
        tc = wc.setdefault("tile", {})
        self.tile_on.setChecked(bool(tc.get("enabled")))
        self.tile_op.set_value(float(tc.get("opacity", 0.12)))
        self.tile_size.set_value(float(tc.get("size", 0.18)))
        self.tile_gap.set_value(float(tc.get("gap", 1.2)))
        self.tile_angle.set_value(float(tc.get("angle", -30)))
        self.suffix.setText(wc.get("suffix", "_水印"))
        self.folder.setText(wc.get("folder", "水印"))
        self._loading = False
        self._refresh_side()
        self.reload_marks()

    def _refresh_side(self):
        body = self.wc.get("place", "body") == "body"
        self.prefer_box.setVisible(body)
        self.corner_box.setVisible(not body)
        self.tile_box.setVisible(bool(self.wc.get("tile", {}).get("enabled")))

    def _set(self, key, v, reauto=False, resize=False, restyle=False, rebuild_bg=False, refresh_side=False):
        if self._loading:
            return
        self.wc[key] = v
        self.cfg.save()
        if refresh_side:
            self._refresh_side()
        if rebuild_bg:
            self._prev.clear()
            self._film_keys = []
            self.refresh_film()
        if reauto or resize:
            for key_, st in self.state.items():
                if not st.get("manual"):
                    st["layers"] = None
        if restyle:
            for st in self.state.values():
                for L in st.get("layers") or []:
                    L.opacity = float(v)
        self.show_current()

    def _set_tile(self, key, v):
        if self._loading:
            return
        self.wc.setdefault("tile", {})[key] = v
        self.cfg.save()
        self._refresh_side()
        self.show_current(keep_layers=True)

    # ---------------------------------------------------------------- 水印库
    def reload_marks(self):
        self.marks.clear()
        cur = self.wc.get("mark")
        items = self.lib.items()
        if not items:
            # 第一次用：先放一个文字水印，打开就能看到效果
            try:
                sid = self.lib.add_text("你的店名", None, "#ffffff", "#333333", False, 700)
                self.wc["mark"] = cur = sid
                self.cfg.save()
                items = self.lib.items()
            except Exception:
                pass
        if not self.lib.exists(cur) and items:
            self.wc["mark"] = cur = items[0][0]
        for sid, name in items:
            img = self.lib.image(sid)
            pm = QPixmap(72, 44)
            pm.fill(QColor("#8a8f99"))
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            sc = img.scaled(68, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawImage(QPointF((72 - sc.width()) / 2, (44 - sc.height()) / 2), sc)
            p.end()
            it = QListWidgetItem(QIcon(pm), name[:8])
            it.setData(Qt.ItemDataRole.UserRole, sid)
            it.setToolTip(name)
            self.marks.addItem(it)
            if sid == cur:
                it.setSelected(True)
                self.marks.setCurrentItem(it)

    def current_mark(self) -> str:
        return self.wc.get("mark") or ""

    def _mark_clicked(self, it):
        sid = it.data(Qt.ItemDataRole.UserRole)
        self.wc["mark"] = sid
        self.cfg.save()
        for st in self.state.values():
            if not st.get("mark"):
                self._swap_mark(st, sid)
        self.show_current(keep_layers=True)

    def _swap_mark(self, st: dict, sid: str):
        """换图案时保持位置、宽度不变，高度按新图案的比例。"""
        img = self.lib.image(sid)
        asp = img.width() / max(1, img.height())
        for L in st.get("layers") or []:
            L.sticker = sid
            L.h = L.w / max(0.05, asp)

    def _mark_menu(self, pos):
        it = self.marks.itemAt(pos)
        if not it:
            return
        sid = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        a1 = m.addAction("只换当前这张")
        a2 = m.addAction("删除这个水印")
        act = m.exec(self.marks.mapToGlobal(pos))
        if act is a1:
            st = self._cur_state()
            if st is not None:
                st["mark"] = sid
                self._swap_mark(st, sid)
                self.show_current(keep_layers=True)
        elif act is a2:
            if QMessageBox.question(self, "删除水印", f"从水印库删除「{it.text()}」？") == QMessageBox.StandardButton.Yes:
                self.lib.remove(sid)
                for st in self.state.values():
                    if st.get("mark") == sid:
                        st["mark"] = None
                self.reload_marks()
                for st in self.state.values():
                    if any(L.sticker == sid for L in st.get("layers") or []):
                        self._swap_mark(st, st.get("mark") or self.current_mark())
                self.show_current(keep_layers=True)

    def upload_mark(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择水印图片（透明底 PNG 最好）", "",
                                                "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        last = None
        for f in files:
            try:
                last = self.lib.add_image(f)
            except Exception as e:
                QMessageBox.warning(self, "上传水印", f"{Path(f).name}：{e}")
        if last:
            self.wc["mark"] = last
            self.cfg.save()
            self.reload_marks()
            for st in self.state.values():
                if not st.get("mark"):
                    self._swap_mark(st, last)
            self.show_current(keep_layers=True)

    def new_text_mark(self):
        dlg = TextMarkDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        try:
            sid = self.lib.add_text(v["text"], v["font_stem"], v["color"], v["stroke"], v["shadow"])
        except Exception as e:
            QMessageBox.warning(self, "文字水印", str(e))
            return
        self.wc["mark"] = sid
        self.cfg.save()
        self.reload_marks()
        for st in self.state.values():
            if not st.get("mark"):
                self._swap_mark(st, sid)
        self.show_current(keep_layers=True)

    # ---------------------------------------------------------------- 图片列表
    def on_show(self):
        if not self.items and not self._auto_loaded:
            self._auto_loaded = True
            self.load_from_docs()
        else:
            self.refresh_film()
            self.show_current(keep_layers=True)

    def load_from_docs(self):
        keep = [i for i in self.items if not i.get("doc_id")]
        docs = [{"key": "doc:" + d.id, "path": str(d.path), "doc_id": d.id, "name": d.name} for d in self.mw.docs]
        self.items = docs + keep
        self._after_items_changed()

    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择要加水印的图片", "",
                                                "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if files:
            self.add_paths(files)

    def add_paths(self, paths: list):
        have = {i["key"] for i in self.items}
        added = 0
        for p in paths:
            pp = Path(p)
            files = sorted(f for f in pp.rglob("*") if f.suffix.lower() in IMG_EXTS) if pp.is_dir() else [pp]
            for f in files:
                if f.suffix.lower() not in IMG_EXTS:
                    continue
                key = "file:" + str(f.resolve()).lower()
                if key in have:
                    continue
                have.add(key)
                self.items.append({"key": key, "path": str(f), "doc_id": None, "name": f.name})
                added += 1
        if added:
            self._after_items_changed(select=len(self.items) - added)

    def clear_items(self):
        self.items = []
        self.state.clear()
        self._prev.clear()
        self._after_items_changed()

    def _after_items_changed(self, select: int | None = None):
        keys = {i["key"] for i in self.items}
        for k in list(self.state):
            if k not in keys:
                self.state.pop(k, None)
                self._prev.pop(k, None)
        self.refresh_film()
        if select is not None:
            self.cur = select
        if not (0 <= self.cur < len(self.items)):
            self.cur = 0 if self.items else -1
        self.film.setCurrentRow(self.cur)
        self.show_current()

    def refresh_film(self):
        keys = [i["key"] for i in self.items]
        n_doc = sum(1 for i in self.items if i.get("doc_id"))
        self.count.setText(f"共 {len(self.items)} 张" + (f"（素材 {n_doc} 张，另外添加 {len(self.items) - n_doc} 张）"
                                                        if n_doc and n_doc < len(self.items) else "")
                           if self.items else "还没有图片：点「用素材里的图」，或者把图片 / 文件夹拖到画布上。")
        if keys == self._film_keys:
            return
        self._film_keys = keys
        self.film.blockSignals(True)
        self.film.clear()
        for i in self.items:
            it = QListWidgetItem(self.mw._placeholder, "")
            it.setToolTip(i["name"])
            self.film.addItem(it)
        self.film.blockSignals(False)
        QTimer.singleShot(0, self._fill_thumbs)

    def _fill_thumbs(self):
        for r, i in enumerate(self.items):
            if r >= self.film.count():
                break
            d = self.mw.doc_by_id(i["doc_id"]) if i.get("doc_id") else None
            if d is not None and d.thumb is not None:
                self.film.item(r).setIcon(QIcon(QPixmap.fromImage(d.thumb)))
                continue
            img = self._prev.get(i["key"])
            if img is None and r > 40:
                continue                      # 很多图时只先画前面的，其余点到时再画
            img = img or self.base_image(i)
            if img is not None:
                self.film.item(r).setIcon(QIcon(QPixmap.fromImage(
                    img.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))))
            QApplication.processEvents()

    def _film_changed(self, r):
        if r < 0 or r == self.cur:
            return
        self.cur = r
        self.show_current()

    def step(self, d: int):
        if not self.items:
            return
        self.cur = max(0, min(len(self.items) - 1, self.cur + d))
        self.film.setCurrentRow(self.cur)
        self.show_current()

    # ---------------------------------------------------------------- 底图、自动位置
    def _doc_of(self, item: dict):
        return self.mw.doc_by_id(item["doc_id"]) if item.get("doc_id") else None

    def full_image(self, item: dict) -> QImage | None:
        """原尺寸的底图（素材里的图按设置带上打码）。"""
        d = self._doc_of(item)
        if d is not None:
            img = d.image()
            if img is None:
                return None
            if self.wc.get("use_mask", True) and d.layers:
                from .exporter import render_doc
                fmt = "png" if Path(item["path"]).suffix.lower() == ".png" else "jpg"
                return render_doc(d, img, self.mw.library, {"mode": "none", "format": fmt})
            return img
        return load_qimage(item["path"])

    def base_image(self, item: dict) -> QImage | None:
        """预览用的底图（最长边不超过 PREVIEW_LONG）。"""
        img = self._prev.get(item["key"])
        if img is not None:
            return img
        full = self.full_image(item)
        if full is None:
            return None
        k = min(1.0, PREVIEW_LONG / max(full.width(), full.height()))
        img = full if k >= 1 else full.scaled(round(full.width() * k), round(full.height() * k),
                                             Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        if len(self._prev) > 30:
            self._prev.pop(next(iter(self._prev)))
        self._prev[item["key"]] = img
        st = self.state.setdefault(item["key"], {"layers": None, "manual": False, "mark": None})
        st["k"] = img.width() / max(1, full.width())
        st["full"] = (full.width(), full.height())
        return img

    def keypoints(self, item: dict, img: QImage):
        if item["key"] in self._kp:
            return self._kp[item["key"]]
        kp = None
        try:
            pose = self.mw.get_pose()
            if pose is not None and img.height() <= img.width() * 2.0:
                from .detector import qimage_to_rgb
                small = img if max(img.width(), img.height()) <= 960 else img.scaled(
                    960, 960, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                kp = pose.keypoints(qimage_to_rgb(small))
                if kp is not None:
                    kp = kp.copy()
                    kp[:, 0] *= img.width() / small.width()
                    kp[:, 1] *= img.height() / small.height()
        except Exception:
            kp = None
        self._kp[item["key"]] = kp
        return kp

    def ensure_layers(self, item: dict) -> list[Layer]:
        img = self.base_image(item)
        st = self.state.setdefault(item["key"], {"layers": None, "manual": False, "mark": None})
        if img is None:
            return []
        if st.get("layers") is None:
            sid = st.get("mark") or self.current_mark()
            mark = self.lib.image(sid)
            avoid = []
            d = self._doc_of(item)
            if d is not None and self.wc.get("use_mask", True):
                k = st.get("k", 1.0)
                for L in d.layers:
                    r = max(L.w, L.h) * k
                    avoid.append(QRectF(L.cx * k - r / 2, L.cy * k - r / 2, r, r))
            kp = self.keypoints(item, img) if self.wc.get("place", "body") == "body" else None
            ms = auto_marks(img.width(), img.height(), mark.width() / max(1, mark.height()), self.wc, kp, avoid)
            st["layers"] = [Layer(part="custom", style="sticker", sticker=sid, cx=m["cx"], cy=m["cy"], w=m["w"],
                                  h=m["h"], rot=m["rot"], opacity=float(self.wc.get("opacity", 0.85)))
                            for m in ms]
            st["manual"] = False
        return st["layers"]

    def _cur_item(self):
        return self.items[self.cur] if 0 <= self.cur < len(self.items) else None

    def _cur_state(self):
        it = self._cur_item()
        return self.state.get(it["key"]) if it else None

    def show_current(self, keep_layers: bool = False):
        it = self._cur_item()
        n = len(self.items)
        self.b_prev.setEnabled(self.cur > 0)
        self.b_next.setEnabled(0 <= self.cur < n - 1)
        if it is None:
            self.title.setText("")
            self.canvas.set_doc(None, None)
            return
        img = self.base_image(it)
        if img is None:
            self.title.setText(f"{it['name']}（读不出来）")
            self.canvas.set_doc(None, None)
            return
        layers = self.ensure_layers(it)
        st = self.state[it["key"]]
        self.title.setText(f"{self.cur + 1}/{n}　{it['name']}" + ("　·　已手动调整" if st.get("manual") else ""))
        shown = self._with_tile(img)
        doc = SimpleNamespace(id=it["key"], layers=layers, w=img.width(), h=img.height())
        same = self.canvas.doc is not None and getattr(self.canvas.doc, "id", None) == it["key"]
        if same and keep_layers:
            self.canvas.doc = doc
            self.canvas.ctx.set_image(doc, shown)
            self.canvas.base.set_image(shown)
            self.canvas.rebuild()
        else:
            self.canvas.set_doc(doc, shown)
            if layers:
                self.canvas.select(layers[0].id)

    def _with_tile(self, img: QImage) -> QImage:
        tc = self.wc.get("tile", {})
        if not tc.get("enabled"):
            return img
        out = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_tile(p, out.width(), out.height(), self.lib.image(self.current_mark()), tc)
        p.end()
        return out

    # ---------------------------------------------------------------- 手动调整
    def _snapshot(self, st):
        return [L.to_dict() for L in st.get("layers") or []]

    def _begin_edit(self):
        it, st = self._cur_item(), self._cur_state()
        if it and st:
            self._undo.append((it["key"], self._snapshot(st)))
            self._undo = self._undo[-60:]
            self._redo.clear()

    def _live_edit(self):
        st = self._cur_state()
        if st is not None:
            st["manual"] = True

    def _end_edit(self):
        it, st = self._cur_item(), self._cur_state()
        if it and st:
            st["manual"] = True
            self.title.setText(f"{self.cur + 1}/{len(self.items)}　{it['name']}　·　已手动调整")

    def undo(self):
        self._swap_history(self._undo, self._redo)

    def redo(self):
        self._swap_history(self._redo, self._undo)

    def _swap_history(self, src, dst):
        if not src:
            return
        key, snap = src.pop()
        st = self.state.get(key)
        if st is None:
            return
        dst.append((key, self._snapshot(st)))
        st["layers"] = [Layer.from_dict(d) for d in snap]
        idx = next((i for i, x in enumerate(self.items) if x["key"] == key), None)
        if idx is not None and idx != self.cur:
            self.cur = idx
            self.film.setCurrentRow(idx)
        self.show_current()

    def reset_current(self):
        st = self._cur_state()
        if st is None:
            return
        self._begin_edit()
        st["layers"] = None
        st["manual"] = False
        st["mark"] = None
        self.show_current()

    def apply_to_all(self):
        it, st = self._cur_item(), self._cur_state()
        if not it or not st or not st.get("layers"):
            return
        img = self.base_image(it)
        W, H = img.width(), img.height()
        rel = [(L.cx / W, L.cy / H, L.w / W, L.rot, L.opacity) for L in st["layers"]]
        for other in self.items:
            if other is it:
                continue
            oimg = self.base_image(other)
            if oimg is None:
                continue
            ost = self.state[other["key"]]
            sid = ost.get("mark") or self.current_mark()
            mark = self.lib.image(sid)
            asp = mark.width() / max(1, mark.height())
            ow, oh = oimg.width(), oimg.height()
            ost["layers"] = [Layer(part="custom", style="sticker", sticker=sid, cx=x * ow, cy=y * oh, w=w * ow,
                                   h=w * ow / max(0.05, asp), rot=r, opacity=o) for x, y, w, r, o in rel]
            ost["manual"] = True
        self.mw.status.showMessage(f"已把这张的水印位置用到其余 {len(self.items) - 1} 张", 6000)

    # ---------------------------------------------------------------- 导出
    def render_full(self, item: dict) -> QImage | None:
        """导出用：原尺寸底图 + 平铺 + 水印。"""
        full = self.full_image(item)
        if full is None:
            return None
        layers = self.ensure_layers(item)
        st = self.state[item["key"]]
        k = st.get("k", 1.0) or 1.0
        W, H = full.width(), full.height()
        fmt = "png" if Path(item["path"]).suffix.lower() == ".png" else "jpg"
        base = full.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        tc = self.wc.get("tile", {})
        if tc.get("enabled"):
            p = QPainter(base)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_tile(p, W, H, self.lib.image(self.current_mark()), tc)
            p.end()
        from .exporter import _render
        doc = SimpleNamespace(layers=[L.clone(cx=L.cx / k, cy=L.cy / k, w=L.w / k, h=L.h / k) for L in layers])
        return _render(doc, base, self.lib, W, H, QRectF(0, 0, W, H), QRectF(0, 0, W, H), fmt)

    def _out_dir(self) -> Path | None:
        root = self.mw._ensure_out_dir()
        if root is None:
            return None
        p = root / (self.wc.get("folder") or "水印")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def export_current(self):
        it = self._cur_item()
        if it:
            self._export([it])

    def export_all(self):
        self._export(list(self.items))

    def _export(self, targets: list, out: Path | None = None) -> int:
        if not targets:
            QMessageBox.information(self, "批量水印", "还没有图片：点「用素材里的图」，或者把图片 / 文件夹拖到画布上。")
            return 0
        if self.mw.busy:
            return 0
        out = out or self._out_dir()
        if out is None:
            return 0
        from .exporter import save_image, unique_path
        dlg = QProgressDialog("正在加水印…", "取消", 0, len(targets), self)
        dlg.setWindowTitle("导出水印图")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        taken: set = set()
        ok, errors = 0, []
        self.mw.set_busy(True)
        try:
            for i, it in enumerate(targets):
                if dlg.wasCanceled():
                    break
                dlg.setValue(i)
                dlg.setLabelText(f"正在导出 {i + 1}/{len(targets)}：{it['name']}")
                QApplication.processEvents()
                try:
                    img = self.render_full(it)
                    if img is None:
                        raise RuntimeError("读不出这张图")
                    src = Path(it["path"])
                    ext = src.suffix.lower().lstrip(".")
                    fmt = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}.get(ext, "jpg")
                    name = f"{src.stem}{self.wc.get('suffix', '_水印')}.{fmt}"
                    path = unique_path(out, name, bool(self.cfg["export"].get("overwrite")), taken)
                    if path.resolve() == src.resolve():
                        raise RuntimeError("导出文件和原图同名，为了不覆盖原图已跳过")
                    taken.add(str(path).lower())
                    save_image(img, path, {"format": fmt, "quality": int(self.cfg["export"].get("quality", 92))})
                    ok += 1
                except Exception as e:
                    errors.append(f"{it['name']}：{e}")
            dlg.setValue(len(targets))
        finally:
            dlg.close()
            self.mw.set_busy(False)
        if errors:
            QMessageBox.warning(self, "导出完成", f"已导出 {ok} 张到：\n{out}\n\n有 {len(errors)} 张没有成功：\n"
                                + "\n".join(errors[:8]))
        else:
            self.mw.status.showMessage(f"已导出 {ok} 张加水印的图到 {out}", 10000)
        if ok and self.cfg["export"].get("open_after", True) :
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return ok
