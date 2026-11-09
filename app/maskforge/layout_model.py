"""版面分析模型（PP-DocLayoutV2）：找出设计图里所有「图片」区域。

这个模型专门训练来分析排版：哪里是标题、正文、图片、表格。用它找照片框，
比按颜色和边线猜要可靠得多，深色背景、模糊照片当底色的设计也能分清。
找到的框再交给「贴边校准」吸附到真实的边上，并判断是直角、圆角还是椭圆。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

IMAGE_CLASSES = ("image", "chart")


# 模型不放进安装包（太大，每次更新都要重下），第一次用智能规格 / 智能详情时下载一次
MODEL_SHA256 = "9e678667339df76ef220a72cbddf3ef6504f9f7df89623d6035a4d4497d24c36"
MODEL_SIZE = 131288936


def model_url() -> str:
    from . import REPO
    return f"https://github.com/{REPO}/releases/download/models-v1/layout.onnx"


def downloaded_path() -> Path:
    from .config import data_dir
    return data_dir() / "models" / "layout.onnx"


def layout_model_path() -> Path:
    """优先用安装目录里的（开发时），其次用下载到数据目录里的。"""
    from .config import resource_dir
    p = resource_dir() / "models" / "layout.onnx"
    return p if p.exists() else downloaded_path()


def install_downloaded(tmp_path: str) -> Path:
    import shutil
    dst = downloaded_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp_path, dst)
    return dst


class LayoutModel:
    SIZE = 800

    def __init__(self, path: Path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        meta = self.sess.get_modelmeta().custom_metadata_map
        names = [n.strip() for n in (meta.get("character") or "").splitlines() if n.strip()]
        self.names = names
        self.image_ids = [i for i, n in enumerate(names) if n in IMAGE_CLASSES] or [14, 3]

    def images(self, rgb: np.ndarray, threshold: float = 0.5) -> list[tuple[float, float, float, float, float]]:
        """返回图片区域 [(x1, y1, x2, y2, 置信度)]，原图坐标。长图分段识别。"""
        H, W = rgb.shape[:2]
        if H <= W * 1.8:
            return self._run(rgb, threshold)
        # 详情长图：按 1.4 倍宽度一段、重叠 30% 地切开识别，再合并
        T = int(W * 1.4)
        step = int(T * 0.7)
        found = []
        y = 0
        while True:
            h = min(T, H - y)
            for x1, y1, x2, y2, s in self._run(rgb[y:y + h], threshold):
                # 贴着这一段上下边缘的框可能被切断了，留给相邻那一段
                cut_top = y1 < 3 and y > 0
                cut_bot = y2 > h - 3 and y + h < H
                found.append((x1, y1 + y, x2, y2 + y, s, bool(cut_top or cut_bot)))
            if y + h >= H:
                break
            y += step
        return _merge_vertical(found)

    def elements(self, rgb: np.ndarray, threshold: float = 0.4):
        """除了照片以外的版面元素（文字、标题、印章 / 徽章、竖排字……），用来找压在照片上的东西。
        返回 [(类别, x1, y1, x2, y2, 置信度)]。长图不做（分段后元素太碎）。"""
        H, W = rgb.shape[:2]
        if H > W * 1.8:
            return []
        out = []
        for name, x1, y1, x2, y2, sc in self._raw(rgb):
            if name not in IMAGE_CLASSES and sc >= threshold:
                out.append((name, x1, y1, x2, y2, sc))
        return out

    def _raw(self, rgb: np.ndarray):
        """模型的全部输出（缓存一下：同一张图找照片、找元素只算一次）。"""
        key = (id(rgb), rgb.shape, float(rgb[::97, ::89].mean()))
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        import cv2
        H, W = rgb.shape[:2]
        S = self.SIZE
        x = cv2.resize(rgb, (S, S), interpolation=cv2.INTER_AREA).astype(np.float32)
        x = (x / 255.0).transpose(2, 0, 1)[None]
        feeds = {"im_shape": np.array([[S, S]], np.float32), "image": np.ascontiguousarray(x),
                 "scale_factor": np.array([[S / H, S / W]], np.float32)}
        out = self.sess.run(None, feeds)[0]
        res = []
        for r in out:
            c = int(r[0])
            name = self.names[c] if 0 <= c < len(self.names) else str(c)
            x1, y1, x2, y2 = (float(v) for v in r[2:6])
            res.append((name, max(0.0, x1), max(0.0, y1), min(float(W), x2), min(float(H), y2), float(r[1])))
        self._cache_key, self._cache = key, res
        return res

    def _run(self, rgb: np.ndarray, threshold: float):
        import cv2
        H, W = rgb.shape[:2]
        S = self.SIZE
        x = cv2.resize(rgb, (S, S), interpolation=cv2.INTER_AREA).astype(np.float32)
        x = (x / 255.0).transpose(2, 0, 1)[None]
        feeds = {"im_shape": np.array([[S, S]], np.float32), "image": np.ascontiguousarray(x),
                 "scale_factor": np.array([[S / H, S / W]], np.float32)}
        out = self.sess.run(None, feeds)[0]
        res = []
        for r in out:
            if int(r[0]) in self.image_ids and r[1] >= threshold:
                x1, y1, x2, y2 = (float(v) for v in r[2:6])
                x1, x2 = max(0.0, x1), min(float(W), x2)
                y1, y2 = max(0.0, y1), min(float(H), y2)
                if x2 - x1 > 8 and y2 - y1 > 8:
                    res.append((x1, y1, x2, y2, float(r[1])))
        return _nms(res, 0.5)


def _merge_vertical(boxes):
    """长图分段识别后：同一张照片被切成上下几块的，合并成一块；重复的去掉。"""
    boxes = sorted(boxes, key=lambda b: b[1])
    out: list[list[float]] = []
    for b in boxes:
        b = list(b)
        merged = False
        for o in out:
            xo = max(0.0, min(b[2], o[2]) - max(b[0], o[0])) / max(1.0, min(b[2] - b[0], o[2] - o[0]))
            yo = min(b[3], o[3]) - max(b[1], o[1])
            if xo > 0.85 and yo > -2 and (b[5] or o[5]) and yo < 0.98 * min(b[3] - b[1], o[3] - o[1]) \
                    or xo > 0.85 and yo > 0.6 * min(b[3] - b[1], o[3] - o[1]):
                o[0], o[1] = min(o[0], b[0]), min(o[1], b[1])
                o[2], o[3] = max(o[2], b[2]), max(o[3], b[3])
                o[4] = max(o[4], b[4])
                o[5] = o[5] and b[5]
                merged = True
                break
        if not merged:
            out.append(b)
    return [tuple(o[:5]) for o in out]


def _nms(boxes, thr):
    boxes = sorted(boxes, key=lambda b: -b[4])
    keep = []
    for b in boxes:
        ok = True
        for k in keep:
            ix = max(0.0, min(b[2], k[2]) - max(b[0], k[0]))
            iy = max(0.0, min(b[3], k[3]) - max(b[1], k[1]))
            inter = ix * iy
            a = (b[2] - b[0]) * (b[3] - b[1])
            if inter > thr * min(a, (k[2] - k[0]) * (k[3] - k[1])):
                ok = False
                break
        if ok:
            keep.append(b)
    return keep
