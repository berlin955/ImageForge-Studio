"""本地部位识别（NudeNet 320n ONNX 模型，onnxruntime 推理）以及把检测结果转换成码。"""
from __future__ import annotations

import math
import os
import threading
from pathlib import Path

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
        if isinstance(size, int) and size > 0:
            self.size = size
        else:
            # 动态尺寸的模型：按文件名决定推理分辨率（640m -> 640，320n -> 320）
            import re
            m = re.match(r"(\d{3,4})", Path(str(model_file)).stem)
            self.size = int(m.group(1)) if m else 640
        self._lock = threading.Lock()

    def _run(self, canvas: np.ndarray) -> np.ndarray:
        blob = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None])
        with self._lock:
            out = self.sess.run(None, {self.input_name: blob})[0]
        o = np.squeeze(out, 0)
        if o.shape[0] == 4 + len(LABELS) and o.shape[1] != 4 + len(LABELS):
            o = o.T
        return o

    def detect(self, image: QImage, threshold: float = 0.25, flip_tta: bool = True) -> list[dict]:
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

        outs = [self._run(canvas)]
        if flip_tta:
            # 左右翻转再识别一次，合并结果，提高检出率
            o2 = self._run(np.ascontiguousarray(canvas[:, ::-1, :]))
            o2[:, 0] = S - o2[:, 0]
            outs.append(o2)
        o = np.concatenate(outs, 0)

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
            if c >= len(LABELS):
                continue
            idx = np.where(cls == c)[0]
            for k in _nms(xyxy[idx], sc[idx]):
                i = idx[k]
                res.append({"label": LABELS[int(c)], "score": float(sc[i]),
                            "box": tuple(float(v) for v in xyxy[i])})

        res = merge_buttocks(res)
        gray = rgb.astype(np.float32).mean(2)
        for d in res:
            if d["label"].startswith("BUTTOCKS"):
                cx_ = _crack_x(gray, np.array(d["box"]) * scale)
                if cx_ is not None:
                    d["crack_x"] = cx_ / scale
        return res


def subject_of(dets: list[dict]):
    """所有识别结果的外框当作「人物范围」，另外返回最上面那张脸的位置。用于主图裁切。"""
    if not dets:
        return None, None
    xs1, ys1, xs2, ys2 = zip(*[d["box"] for d in dets])
    subject = (min(xs1), min(ys1), max(xs2), max(ys2))
    faces = [d["box"] for d in dets if d["label"].startswith("FACE")]
    face = min(faces, key=lambda b: b[1]) if faces else None
    return subject, face


def merge_buttocks(dets: list[dict]) -> list[dict]:
    """模型常把左右两半臀部识别成两个框，合并成一个，股沟只打一个码。"""
    butt = [d for d in dets if d["label"].startswith("BUTTOCKS")]
    others = [d for d in dets if not d["label"].startswith("BUTTOCKS")]
    groups: list[dict] = []
    for d in sorted(butt, key=lambda d: d["box"][0]):
        x1, y1, x2, y2 = d["box"]
        for g in groups:
            gx1, gy1, gx2, gy2 = g["box"]
            v_overlap = min(y2, gy2) - max(y1, gy1)
            gap = max(x1, gx1) - min(x2, gx2)     # 负数表示横向有重叠
            width = max(x2 - x1, gx2 - gx1)
            if v_overlap > 0.4 * min(y2 - y1, gy2 - gy1) and gap < 0.35 * width:
                g["box"] = (min(x1, gx1), min(y1, gy1), max(x2, gx2), max(y2, gy2))
                if d["label"].endswith("EXPOSED"):
                    g["label"] = d["label"]
                g["score"] = max(g["score"], d["score"])
                break
        else:
            groups.append(dict(d))
    return others + groups


def _crack_x(gray: np.ndarray, box) -> float | None:
    """在臀部框里找最暗的一条竖线（股沟的阴影），返回 x 坐标（缩略图坐标）。"""
    x1, y1, x2, y2 = [float(v) for v in box]
    bw, bh = x2 - x1, y2 - y1
    if bw < 12 or bh < 12:
        return None
    H, W = gray.shape
    r0, r1 = int(max(0, y1 + bh * 0.15)), int(min(H, y1 + bh * 0.75))
    c0, c1 = int(max(0, x1 + bw * 0.22)), int(min(W, x1 + bw * 0.78))
    if r1 - r0 < 4 or c1 - c0 < 6:
        return None
    region = gray[r0:r1, c0:c1]
    prof = region.mean(0)
    k = max(3, int(bw * 0.06) | 1)
    kern = np.ones(k) / k
    sm = np.convolve(np.pad(prof, k // 2, mode="edge"), kern, mode="valid")
    # 偏向中间：离中心越远，越需要明显更暗才会被选中
    xs = np.arange(len(sm))
    center = (len(sm) - 1) / 2
    penalty = (np.abs(xs - center) / max(1.0, center)) ** 2 * (sm.std() + 1.0) * 1.2
    j = int(np.argmin(sm + penalty))
    # 对比不明显就不调整
    if sm.max() - sm[j] < 6:
        return None
    return c0 + j + 0.5


# 每个部位接受哪些识别结果；带 COVERED 的是「有遮挡」（丁字裤、薄纱、珍珠链等）
PART_LABELS = {
    "lower": {"exposed": ["FEMALE_GENITALIA_EXPOSED"], "covered": ["FEMALE_GENITALIA_COVERED"]},
    "crack": {"exposed": ["BUTTOCKS_EXPOSED", "ANUS_EXPOSED"], "covered": ["BUTTOCKS_COVERED", "ANUS_COVERED"]},
    "areola": {"exposed": ["FEMALE_BREAST_EXPOSED"], "covered": ["FEMALE_BREAST_COVERED"]},
}


def plan_layers(dets: list[dict], img_w: int, img_h: int, cfg) -> list[Layer]:
    """把模型检测框转换成各部位的码。"""
    parts = cfg["parts"]
    male = cfg["detect"].get("male", False)
    lab2part = {}
    for part, groups in PART_LABELS.items():
        p = parts.get(part) or {}
        if not p.get("enabled", True):
            continue
        for lab in groups["exposed"]:
            lab2part[lab] = part
        if p.get("covered", part != "areola"):
            for lab in groups["covered"]:
                lab2part[lab] = part
    if male and parts.get("lower", {}).get("enabled", True):
        lab2part["MALE_GENITALIA_EXPOSED"] = "lower"

    cands: list[Layer] = []
    for d in dets:
        lab = d["label"]
        part = lab2part.get(lab)
        if not part:
            continue
        x1, y1, x2, y2 = d["box"]
        bw, bh = x2 - x1, y2 - y1
        if bw < 2 or bh < 2:
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if part == "lower":
            w, h = bw, bh
            if lab.endswith("COVERED"):
                w, h = bw * 0.85, bh * 0.85
        elif lab.startswith("ANUS"):
            w, h = bw * 1.3, bh * 2.2
        elif part == "crack":
            # 臀部框里的股沟：一条竖长的区域，位置按阴影微调
            cx = d.get("crack_x", cx)
            w, h = bw * 0.26, bh * 0.82
            cy = y1 + bh * 0.47
        else:  # areola
            s = min(bw, bh) * 0.44
            w, h = s, s
            cy = y1 + bh * 0.56
        p = parts[part]
        k = float(p.get("scale", 1.0))
        cands.append(Layer(part=part, style=p["style"], sticker=p["sticker"], color=p["color"],
                           block=p["block"], opacity=p.get("opacity", 1.0),
                           cx=cx, cy=cy, w=max(6.0, w * k), h=max(6.0, h * k),
                           auto=True, score=d["score"]))

    # 同一部位重叠的结果只保留分数高的
    cands.sort(key=lambda l: l.score, reverse=True)
    kept: list[Layer] = []
    for l in cands:
        # 乳晕左右各一个；下体、股沟靠得近的只留一个
        f = 0.5 if l.part == "areola" else 1.2
        dup = any(k.part == l.part and math.hypot(k.cx - l.cx, k.cy - l.cy) < f * max(k.w, k.h, l.w, l.h)
                  for k in kept)
        if not dup:
            kept.append(l)
    # 从背后拍时，模型会把两腿之间识别成「下体」，和股沟在同一条竖线上，只留股沟一个码
    cracks = [l for l in kept if l.part == "crack"]
    if cracks:
        def behind(low: Layer) -> bool:
            for c in cracks:
                dx = abs(low.cx - c.cx)
                dy = low.cy - c.cy
                if dx < max(c.w, low.w) * 1.2 and -0.2 * c.h < dy < c.h * 1.8:
                    return True
            return False
        kept = [l for l in kept if not (l.part == "lower" and behind(l))]
    kept.sort(key=lambda l: (l.cy, l.cx))
    return kept
