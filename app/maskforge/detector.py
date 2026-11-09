"""本地部位识别（NudeNet 320n ONNX 模型，onnxruntime 推理）以及把检测结果转换成码。"""
from __future__ import annotations

import math
import os
import threading

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .model import Layer

LABELS = [
    "FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED",
    "BELLY_COVERED", "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE",
    "BELLY_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
]


def qimage_to_rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, count=bpl * h)
    return buf.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3).copy()


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float = 0.45) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        ovr = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[ovr < iou]
    return keep


class Detector:
    def __init__(self, model_file):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
        self.sess = ort.InferenceSession(str(model_file), sess_options=so,
                                         providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.input_name = inp.name
        size = inp.shape[2] if len(inp.shape) == 4 else None
        self.size = size if isinstance(size, int) and size > 0 else 320
        self._lock = threading.Lock()

    def detect(self, image: QImage, threshold: float = 0.3) -> list[dict]:
        S = self.size
        w, h = image.width(), image.height()
        if w <= 0 or h <= 0:
            return []
        scale = S / max(w, h)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        small = image.scaled(nw, nh, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        rgb = qimage_to_rgb(small)
        canvas = np.zeros((S, S, 3), np.float32)
        px, py = (S - nw) // 2, (S - nh) // 2
        canvas[py:py + nh, px:px + nw] = rgb.astype(np.float32) / 255.0
        blob = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None])

        with self._lock:
            out = self.sess.run(None, {self.input_name: blob})[0]
        o = np.squeeze(out, 0)
        if o.shape[0] == 4 + len(LABELS) and o.shape[1] != 4 + len(LABELS):
            o = o.T
        boxes, cls_scores = o[:, :4], o[:, 4:]
        cls = cls_scores.argmax(1)
        sc = cls_scores.max(1)
        m = sc >= threshold
        if not m.any():
            return []
        boxes, cls, sc = boxes[m], cls[m], sc[m]
        cx, cy, bw, bh = boxes.T
        x1 = (cx - bw / 2 - px) / scale
        y1 = (cy - bh / 2 - py) / scale
        x2 = (cx + bw / 2 - px) / scale
        y2 = (cy + bh / 2 - py) / scale
        xyxy = np.stack([x1, y1, x2, y2], 1)
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clip(0, w)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clip(0, h)

        res = []
        for c in np.unique(cls):
            idx = np.where(cls == c)[0]
            for k in _nms(xyxy[idx], sc[idx]):
                i = idx[k]
                if c >= len(LABELS):
                    continue
                res.append({"label": LABELS[int(c)], "score": float(sc[i]),
                            "box": tuple(float(v) for v in xyxy[i])})
        return res


def plan_layers(dets: list[dict], img_w: int, img_h: int, cfg) -> list[Layer]:
    """把模型检测框转换成各部位的码。"""
    parts = cfg["parts"]
    male = cfg["detect"].get("male", False)
    cands: list[Layer] = []
    for d in dets:
        lab = d["label"]
        x1, y1, x2, y2 = d["box"]
        bw, bh = x2 - x1, y2 - y1
        if bw < 2 or bh < 2:
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if lab == "FEMALE_GENITALIA_EXPOSED" or (male and lab == "MALE_GENITALIA_EXPOSED"):
            part, w, h = "lower", bw, bh
        elif lab == "BUTTOCKS_EXPOSED":
            # 臀部框的中间一条就是股沟
            part, w, h = "crack", bw * 0.30, bh * 0.92
        elif lab == "ANUS_EXPOSED":
            part, w, h = "crack", bw * 1.3, bh * 2.2
        elif lab == "FEMALE_BREAST_EXPOSED":
            s = min(bw, bh) * 0.44
            part, w, h = "areola", s, s
            cy = y1 + bh * 0.56
        else:
            continue
        p = parts.get(part)
        if not p or not p.get("enabled", True):
            continue
        k = float(p.get("scale", 1.0))
        cands.append(Layer(part=part, style=p["style"], sticker=p["sticker"], color=p["color"],
                           block=p["block"], opacity=p.get("opacity", 1.0),
                           cx=cx, cy=cy, w=max(6.0, w * k), h=max(6.0, h * k),
                           auto=True, score=d["score"]))

    # 同一部位重叠的结果只保留面积较大的
    cands.sort(key=lambda l: l.w * l.h, reverse=True)
    kept: list[Layer] = []
    for l in cands:
        dup = False
        for k in kept:
            if k.part != l.part:
                continue
            dist = math.hypot(k.cx - l.cx, k.cy - l.cy)
            if dist < 0.5 * max(k.w, k.h, l.w, l.h):
                dup = True
                break
        if not dup:
            kept.append(l)
    kept.sort(key=lambda l: (l.cy, l.cx))
    return kept
