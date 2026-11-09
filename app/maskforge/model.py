"""图片文档与码图层的数据模型。"""
from __future__ import annotations

import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PySide6.QtGui import QImage, QImageReader


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Layer:
    part: str = "custom"
    style: str = "mosaic"
    sticker: str = "builtin:heart"
    color: str = "#16171b"
    block: float = 0.018          # 马赛克/模糊颗粒，按图片宽度的比例
    cx: float = 0.0               # 中心点（原图像素）
    cy: float = 0.0
    w: float = 60.0
    h: float = 60.0
    rot: float = 0.0              # 旋转角度
    skew: float = 0.0             # 倾斜角度
    flip: bool = False
    opacity: float = 1.0
    auto: bool = False            # 是否由自动识别生成
    score: float = 0.0
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def clone(self, **kw) -> "Layer":
        d = self.to_dict()
        d.update(kw)
        d["id"] = _new_id()
        return Layer.from_dict(d)


def load_qimage(path) -> QImage | None:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # 按 EXIF 方向自动旋转
    img = reader.read()
    if img.isNull():
        return None
    return img


class _ImageCache:
    """最近使用的原图缓存，避免大量大图占满内存。"""

    def __init__(self, size: int = 4):
        self.size = size
        self._d: OrderedDict[str, QImage] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> QImage | None:
        with self._lock:
            img = self._d.get(key)
            if img is not None:
                self._d.move_to_end(key)
            return img

    MAX_PIXELS = 160_000_000   # 约 640MB

    def put(self, key: str, img: QImage) -> None:
        with self._lock:
            self._d[key] = img
            self._d.move_to_end(key)
            while len(self._d) > 1 and (len(self._d) > self.size or
                                        sum(i.width() * i.height() for i in self._d.values()) > self.MAX_PIXELS):
                self._d.popitem(last=False)

    def drop(self, key: str) -> None:
        with self._lock:
            self._d.pop(key, None)


IMAGE_CACHE = _ImageCache(3)


class ImageDoc:
    def __init__(self, path):
        self.id = _new_id()
        self.path = Path(path)
        self.name = self.path.name
        self.w = 0
        self.h = 0
        self.layers: list[Layer] = []
        self.thumb: QImage | None = None     # 长边约 360px 的缩略图
        self.detected = False
        self.reviewed = False                # 手动看过 / 改过就算检查过
        self.subject: tuple | None = None    # AI 识别到的人物范围（原图坐标）
        self.face: tuple | None = None       # 脸的位置，用于主图裁切
        self.crop: dict | None = None        # 手动调整过的主图框 {cx, cy, scale}，按比例记录
        self.logo_pos: tuple | None = None   # 主图角标手动拖过的位置（按输出比例）
        self.icon = None                     # 缩略图图标（带码），各页面共用
        self.labels: list | None = None      # AI 识别到的部位标签，用来判断正面 / 背面
        self.error = ""
        self.hist: list[list[dict]] = []
        self.fut: list[list[dict]] = []

    # ---- 图片 ----
    def image(self) -> QImage | None:
        img = IMAGE_CACHE.get(self.id)
        if img is None:
            img = load_qimage(self.path)
            if img is None:
                self.error = "无法读取图片"
                return None
            IMAGE_CACHE.put(self.id, img)
        self.w, self.h = img.width(), img.height()
        return img

    # ---- 状态 ----
    LOW_SCORE = 0.4

    def attention(self) -> str:
        """需要人看一眼的原因；空字符串表示不需要。"""
        if self.error or self.reviewed or not self.detected:
            return ""
        if not self.layers:
            return "没有检出部位"
        if any(l.auto and l.score < self.LOW_SCORE for l in self.layers):
            return "可信度较低"
        return ""

    def status(self) -> str:
        if self.error:
            return "error"
        if self.attention():
            return "attention"
        if self.layers or self.detected or self.reviewed:
            return "done"
        return "todo"

    def status_text(self) -> str:
        st = self.status()
        if st == "error":
            return "读取失败"
        if st == "attention":
            return "需要注意 · " + self.attention()
        if st == "done":
            return f"已打码 · {len(self.layers)} 个码" if self.layers else "无需打码"
        return "未处理"

    # ---- 撤销 ----
    def snapshot(self) -> list[dict]:
        return [l.to_dict() for l in self.layers]

    def push(self) -> None:
        self.hist.append(self.snapshot())
        if len(self.hist) > 100:
            self.hist.pop(0)
        self.fut.clear()

    def undo(self) -> bool:
        if not self.hist:
            return False
        self.fut.append(self.snapshot())
        self.layers = [Layer.from_dict(d) for d in self.hist.pop()]
        return True

    def redo(self) -> bool:
        if not self.fut:
            return False
        self.hist.append(self.snapshot())
        self.layers = [Layer.from_dict(d) for d in self.fut.pop()]
        return True

    # ---- 跨图片复制（按比例）----
    def normalized(self) -> list[dict]:
        if not self.w or not self.h:
            return []
        out = []
        for l in self.layers:
            d = l.to_dict()
            d["cx"] /= self.w
            d["cy"] /= self.h
            d["w"] /= self.w
            d["h"] /= self.w
            out.append(d)
        return out

    def apply_normalized(self, items: list[dict]) -> list[Layer]:
        res = []
        for d in items:
            d = dict(d)
            d["cx"] *= self.w
            d["cy"] *= self.h
            d["w"] *= self.w
            d["h"] *= self.w
            d["id"] = _new_id()
            d["auto"] = False
            res.append(Layer.from_dict(d))
        return res


_num_re = re.compile(r"(\d+)")


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in _num_re.split(s)]
