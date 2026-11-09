"""版面分析模型（PP-DocLayoutV2）：找出设计图里所有「图片」区域。

这个模型专门训练来分析排版：哪里是标题、正文、图片、表格。用它找照片框，
比按颜色和边线猜要可靠得多，深色背景、模糊照片当底色的设计也能分清。
找到的框再交给「贴边校准」吸附到真实的边上，并判断是直角、圆角还是椭圆。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

IMAGE_CLASSES = ("image", "chart")


def layout_model_path() -> Path:
    from .config import resource_dir
    return resource_dir() / "models" / "layout.onnx"


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
                found.append((x1, y1 + y, x2, y2 + y, s - 0.2 * (cut_top + cut_bot)))
            if y + h >= H:
                break
            y += step
        return _nms(found, 0.5)

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
