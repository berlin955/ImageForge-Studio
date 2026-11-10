"""智能规格：把一张别人的规格图变成模板。

1. 找照片：模特连同照片背景整块找出来（直角、圆角、胶囊、椭圆形的照片框都行），做成图片位。
2. 找文字：OCR 识别图上的文字（照片框里面的字不算），记下位置、大小、颜色。
3. 擦字：把识别到的文字从背景上擦掉、补好，文字改成可编辑的图层。
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from .config import data_dir
from .detector import qimage_to_rgb


def templates_dir() -> Path:
    p = data_dir() / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ================================================================ 找照片框
def _cluster_people(dets: list[dict], w: int, h: int) -> list[tuple]:
    """把人体各部位的识别框按人分组，返回每个人的外框。"""
    boxes = [d["box"] for d in dets]
    if not boxes:
        return []
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def grow(b, k=0.25):
        x1, y1, x2, y2 = b
        dx, dy = (x2 - x1) * k, (y2 - y1) * k
        return x1 - dx, y1 - dy, x2 + dx, y2 + dy

    for i in range(n):
        for j in range(i + 1, n):
            a, b = grow(boxes[i]), grow(boxes[j])
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])
    res = []
    for bs in groups.values():
        x1 = min(b[0] for b in bs)
        y1 = min(b[1] for b in bs)
        x2 = max(b[2] for b in bs)
        y2 = max(b[3] for b in bs)
        if (x2 - x1) * (y2 - y1) > w * h * 0.004:
            res.append((x1, y1, x2, y2))
    return res


def _edge_maps(gray: np.ndarray):
    gy = np.abs(np.diff(gray, axis=0))      # 横线（上下边）
    gx = np.abs(np.diff(gray, axis=1))      # 竖线（左右边）
    return gy, gx


def expand_to_frame(gray: np.ndarray, seed: tuple, thr: float = 16.0) -> tuple:
    """从人物框出发，四个方向往外找照片的边：
    一条横（竖）线上大部分像素都有明显的明暗变化，而且线外侧是平整的设计底色，就是照片边。
    碰到整张图的边缘也算。"""
    H, W = gray.shape
    gy, gx = _edge_maps(gray)
    x1, y1, x2, y2 = [int(round(v)) for v in seed]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W - 1, x2), min(H - 1, y2)

    def flat(a: np.ndarray) -> bool:
        return a.size > 0 and float(a.std()) < 14.0

    for _ in range(3):  # 交替扩展几轮，范围会越来越准
        # 上边
        top = 0
        for y in range(y1, 0, -1):
            row = gy[y - 1, x1:x2 + 1]
            if row.size and (row > thr).mean() > 0.55 and flat(gray[max(0, y - 6):y - 1, x1:x2 + 1]):
                top = y
                break
        # 下边
        bottom = H - 1
        for y in range(y2, H - 1):
            row = gy[y, x1:x2 + 1]
            if row.size and (row > thr).mean() > 0.55 and flat(gray[y + 2:y + 7, x1:x2 + 1]):
                bottom = y
                break
        # 左边
        left = 0
        for x in range(x1, 0, -1):
            col = gx[top:bottom + 1, x - 1]
            if col.size and (col > thr).mean() > 0.55 and flat(gray[top:bottom + 1, max(0, x - 6):x - 1]):
                left = x
                break
        # 右边
        right = W - 1
        for x in range(x2, W - 1):
            col = gx[top:bottom + 1, x]
            if col.size and (col > thr).mean() > 0.55 and flat(gray[top:bottom + 1, x + 2:x + 7]):
                right = x
                break
        if (left, top, right, bottom) == (x1, y1, x2, y2):
            break
        x1, y1, x2, y2 = left, top, right, bottom
    return float(x1), float(y1), float(x2 + 1), float(y2 + 1)


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def find_slots(rgb: np.ndarray, dets: list[dict], blocks: bool = False, text_boxes=(), layout_boxes=None) -> list[dict]:
    """找出图上所有照片（模特连同照片背景整块），返回图片位列表
    [{"x","y","w","h","shape","radius"}]（原图坐标）。

    1. 封闭的照片框（直角、圆角、胶囊、椭圆都行）：看边缘围起来的区域，颜色丰富的是照片；
    2. 识别到模特、但不在上面这些框里的：从模特往外找照片的直边；
    3. 详情长图：再补上没有模特的照片块（面料特写等）。
    text_boxes：识别到的文字框 (x1, y1, x2, y2)，主要是文字的区域不当作照片。"""
    from .photo_regions import SENSITIVE, STRICT, find_regions
    H, W = rgb.shape[:2]
    parts = [d["box"] for d in dets
             if (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]) > W * H * 0.0008]
    slots: list[dict] = []

    def rect_of(s):
        return (s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"])

    def center_in(b, r):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]

    def uncovered():
        return [b for b in parts if not any(center_in(b, rect_of(s)) for s in slots)]

    def take_regions(level, only_people: bool):
        try:
            regions = find_regions(rgb, level=level)
        except Exception:
            return
        for reg in sorted(regions, key=lambda g: g["w"] * g["h"], reverse=True):
            r = rect_of(reg)
            person = any(center_in(b, r) for b in parts)
            if only_people and not any(center_in(b, r) for b in uncovered()):
                continue
            if not person:
                if not reg["photo"]:
                    continue
                if max(reg["w"] / max(1, reg["h"]), reg["h"] / max(1, reg["w"])) > 4:
                    continue      # 细长条多半是装饰条、标题底框
                txt = sum(_overlap(r, t) for t in text_boxes)
                if txt > 0.08 * _area(r):
                    continue      # 主要是文字（标题框、尺码表）
            if _area(r) > 0.9 * W * H and len(parts) and len(_cluster_people(dets, W, H)) > 1:
                continue          # 一整张图都被当成一块，说明边没找准
            if any(_overlap(r, rect_of(s)) > 0.5 * min(_area(r), _area(rect_of(s))) for s in slots):
                continue
            slots.append({"x": reg["x"], "y": reg["y"], "w": reg["w"], "h": reg["h"],
                          "shape": reg["shape"], "radius": reg["radius"]})

    if layout_boxes:
        # 有版面分析模型：直接用它找到的图片区域，形状参考边缘找到的封闭区域（圆角、胶囊、椭圆）
        try:
            hints = find_regions(rgb)
        except Exception:
            hints = []
        for x1, y1, x2, y2, _sc in sorted(layout_boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
            r = (x1, y1, x2, y2)
            if _area(r) < 0.01 * W * H:
                continue
            if any(_overlap(r, rect_of(s)) > 0.5 * min(_area(r), _area(rect_of(s))) for s in slots):
                continue
            shape, rad = "rect", 0.0
            best = None
            for g in hints:
                gr = rect_of(g)
                inter = _overlap(r, gr)
                iou = inter / max(1.0, _area(r) + _area(gr) - inter)
                if iou > 0.75 and (best is None or iou > best[0]):
                    best = (iou, g)
            if best:
                shape, rad = best[1]["shape"], best[1]["radius"]
            # 只有真的贴着整张图边缘（差一两个像素）才吸过去；留了边距的相框不能把边距吃掉
            if x1 < W * 0.003:
                x1 = 0.0
            if y1 < H * 0.003:
                y1 = 0.0
            if x2 > W * 0.997:
                x2 = float(W)
            if y2 > H * 0.997:
                y2 = float(H)
            slots.append({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "shape": shape, "radius": rad})
    else:
        take_regions(STRICT, only_people=False)
        if uncovered():
            take_regions(SENSITIVE, only_people=True)
    people = _cluster_people([{"box": b} for b in uncovered()], W, H)

    # 模特不在上面的照片框里：从模特往外扩，找照片的直边
    k = min(1.0, 900 / W)   # 按宽度缩小；长图不能按长边缩，否则会缩得太小
    if k < 1:
        idx_y = (np.arange(int(H * k)) / k).astype(int)
        idx_x = (np.arange(int(W * k)) / k).astype(int)
        small = rgb[idx_y][:, idx_x]
    else:
        small = rgb
    gray = small.astype(np.float32).mean(2)
    for p in sorted(people, key=_area, reverse=True):
        cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
        if any(s["x"] <= cx <= s["x"] + s["w"] and s["y"] <= cy <= s["y"] + s["h"] for s in slots):
            continue
        x1, y1, x2, y2 = expand_to_frame(gray, [v * k for v in p])
        r = (x1 / k, y1 / k, x2 / k, y2 / k)
        # 扩出去压到了别的照片：从那张照片的边切开，留下模特这一侧
        for s in slots:
            o = rect_of(s)
            if _overlap(r, o) <= 0:
                continue
            cuts = []
            if cx >= o[2]:
                cuts.append((o[2], r[1], r[2], r[3]))
            if cx <= o[0]:
                cuts.append((r[0], r[1], o[0], r[3]))
            if cy >= o[3]:
                cuts.append((r[0], o[3], r[2], r[3]))
            if cy <= o[1]:
                cuts.append((r[0], r[1], r[2], o[1]))
            if cuts:
                r = max(cuts, key=_area)
        if _area(r) < _area(p) * 0.5:
            mx, my = (p[2] - p[0]) * 0.08, (p[3] - p[1]) * 0.05
            r = (max(0, p[0] - mx), max(0, p[1] - my), min(W, p[2] + mx), min(H, p[3] + my))
        slots.append({"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1], "shape": "rect", "radius": 0.0})

    # 贴边校准：把每个照片位的轮廓（含圆角大小）吸附到真实的相框边上
    from .photo_regions import refine_shape, trim_uniform_margins
    for s in slots:
        if s.get("shape", "rect") == "rect" and float(s.get("radius") or 0) < 0.3:
            x, y, w, h = trim_uniform_margins(rgb, s["x"], s["y"], s["w"], s["h"], ignore=text_boxes)
            if w > s["w"] * 0.6 and h > s["h"] * 0.6:
                s.update({"x": x, "y": y, "w": w, "h": h})
    for s in slots:
        try:
            x, y, w, h, shape, rad = refine_shape(rgb, s["x"], s["y"], s["w"], s["h"],
                                                  s.get("shape", "rect"), float(s.get("radius") or 0))
            if w > s["w"] * 0.85 and h > s["h"] * 0.85:
                s.update({"x": x, "y": y, "w": w, "h": h, "shape": shape, "radius": rad})
        except Exception:
            pass
    # 最后一步：原图全分辨率下逐条边对齐到像素级（椭圆没有直边，不做）
    from .photo_regions import snap_sides
    for s in slots:
        if s.get("shape") == "ellipse" or float(s.get("radius") or 0) >= 0.45:
            continue
        try:
            x, y, w, h = snap_sides(rgb, s["x"], s["y"], s["w"], s["h"])
            if abs(w - s["w"]) < max(12, s["w"] * 0.07) and abs(h - s["h"]) < max(12, s["h"] * 0.07):
                s.update({"x": x, "y": y, "w": w, "h": h})
        except Exception:
            pass
    # 圆角也在全分辨率下重新量一遍（照片外面有一圈描边时，之前容易量小）
    from .photo_regions import corner_radius_px
    for s in slots:
        if s.get("shape") == "ellipse" or float(s.get("radius") or 0) >= 0.3:
            continue
        try:
            r, n_c = corner_radius_px(rgb, s["x"], s["y"], s["w"], s["h"])
            if r is not None and n_c >= 2:
                s["radius"] = r
            elif float(s.get("radius") or 0) < 0.03:
                s["radius"] = 0.0
        except Exception:
            pass
    # 不能超出整张图
    for s in slots:
        x0, y0 = max(0.0, s["x"]), max(0.0, s["y"])
        x1, y1 = min(float(W), s["x"] + s["w"]), min(float(H), s["y"] + s["h"])
        s.update({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})

    if blocks:
        for b in photo_blocks(gray):
            b = [v / k for v in b]
            if any(_overlap(b, rect_of(s)) > 0.3 * min(_area(b), _area(rect_of(s))) for s in slots):
                continue
            slots.append({"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1], "shape": "rect", "radius": 0.0})
    if H > 1.6 * W:   # 长图：从上到下
        slots.sort(key=lambda s: (s["y"], s["x"]))
    else:
        slots.sort(key=lambda s: (round(s["x"] / max(1, W) * 4), s["y"]))
    return slots


def photo_blocks(gray: np.ndarray, min_h_ratio: float = 0.22) -> list[list]:
    """找没有模特的照片块（比如面料特写）：被平整底色上下隔开、内部纹理丰富的区域。"""
    H, W = gray.shape
    if H < 40 or W < 40:
        return []
    # 每一行是不是「平整」的（设计底色）
    row_std = gray.std(1)
    flat = row_std < 9.0
    blocks = []
    y = 0
    while y < H:
        if flat[y]:
            y += 1
            continue
        y0 = y
        while y < H and not flat[y]:
            y += 1
        y1 = y
        if y1 - y0 < W * min_h_ratio:
            continue
        band = gray[y0:y1]
        busy_col = band.std(0) > 12.0
        # 同一行里并排的几张照片：按中间平整的竖条分开
        x = 0
        while x < W:
            if not busy_col[x]:
                x += 1
                continue
            x0 = x
            gap = 0
            while x < W and gap < 8:
                gap = 0 if busy_col[x] else gap + 1
                x += 1
            x1 = x - gap
            if x1 - x0 < W * 0.15:
                continue
            region = band[:, x0:x1]
            # 照片的纹理分布比较均匀；一大段文字的话，大部分是底色
            busy = (np.abs(region - np.median(region)) > 18).mean()
            if busy < 0.35:
                continue
            blocks.append([float(x0), float(y0), float(x1), float(y1)])
    return blocks


# ================================================================ 找文字、擦文字
_ocr = None
last_error = ""   # 最近一次文字识别失败的原因


def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ocr_tiled(rgb: np.ndarray) -> list:
    """文字识别。长图分段识别（每段高约 1.5 倍宽，相邻段有重叠），再把结果合起来。"""
    H, W = rgb.shape[:2]
    eng = get_ocr()
    if H <= 2.0 * W:
        res, _ = eng(rgb[:, :, ::-1].copy())
        return res or []
    T = int(W * 1.5)
    step = int(T * 0.82)
    out = []
    y = 0
    while True:
        y1 = min(H, y + T)
        tile = rgb[y:y1, :, ::-1].copy()
        res, _ = eng(tile)
        for box, text, score in res or []:
            pts = [[float(px), float(py) + y] for px, py in box]
            # 段与段重叠的地方会识别两次，位置几乎一样的同一段字只留一个
            cy = sum(p[1] for p in pts) / 4
            cx = sum(p[0] for p in pts) / 4
            dup = any(t == text and abs(sum(p[1] for p in b) / 4 - cy) < 12 and abs(sum(p[0] for p in b) / 4 - cx) < 12
                      for b, t, _s in out)
            if not dup:
                out.append([pts, text, score])
        if y1 >= H:
            break
        y += step
    return out


def detect_tiled(detector, rgb: np.ndarray, threshold: float = 0.2) -> list[dict]:
    """人物识别。长图分段识别，否则人太小认不出来。"""
    if detector is None:
        return []
    H, W = rgb.shape[:2]
    if H <= 1.6 * W:
        return detector.detect_rgb(rgb, threshold)
    T = int(W * 1.25)
    step = int(T * 0.75)
    dets = []
    y = 0
    while True:
        h = min(T, H - y)
        for d in detector.detect_rgb(rgb[y:y + h], threshold):
            x1, y1, x2, y2 = d["box"]
            dets.append({**d, "box": (x1, y1 + y, x2, y2 + y)})
        if y + h >= H:
            break
        y += step
    return dets


def _inside(cx: float, cy: float, slots: list[dict]) -> bool:
    return any(s["x"] <= cx <= s["x"] + s["w"] and s["y"] <= cy <= s["y"] + s["h"] for s in slots)


def run_ocr(rgb: np.ndarray) -> list:
    global last_error
    try:
        res = ocr_tiled(rgb)
        last_error = ""
        return res or []
    except Exception as e:
        import traceback
        last_error = f"{e}\n{traceback.format_exc()}"
        return []


def find_texts(rgb: np.ndarray, slots: list[dict], min_score: float = 0.5, ocr=None):
    """返回 (文字图层列表, 需要擦掉的像素蒙版)。照片框里面的字不算。"""
    H, W = rgb.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    texts = []
    result = run_ocr(rgb) if ocr is None else ocr
    for item in result or []:
        box, text, score = item[0], item[1], float(item[2])
        text = (text or "").strip()
        if not text or score < min_score:
            continue
        pts = np.array(box, dtype=np.float32)
        x1, y1 = pts.min(0)
        x2, y2 = pts.max(0)
        w, h = x2 - x1, y2 - y1
        if _inside((x1 + x2) / 2, (y1 + y2) / 2, slots):
            continue
        if h > w * 1.6 and len(text) > 1:
            continue  # 竖排文字先不处理，保留原样
        pad = max(2, int(h * 0.12))
        X1, Y1 = int(max(0, x1 - pad)), int(max(0, y1 - pad))
        X2, Y2 = int(min(W, x2 + pad)), int(min(H, y2 + pad))
        region = rgb[Y1:Y2, X1:X2].astype(np.int32)
        if region.size == 0:
            continue
        ring = np.concatenate([region[0], region[-1], region[:, 0], region[:, -1]])
        bg = np.median(ring, axis=0)
        diff = np.abs(region - bg).sum(2)
        stroke = diff > 70
        color = np.median(region[stroke], axis=0) if stroke.any() else np.array([0, 0, 0])
        density = float(stroke.mean())
        m = stroke.astype(np.uint8)
        try:
            import cv2
            m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=2)
        except Exception:
            pass
        mask[Y1:Y2, X1:X2] = np.maximum(mask[Y1:Y2, X1:X2], m * 255)
        t = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "x": float(x1), "y": float(y1), "w": float(w), "h": float(h),
            "size": max(8.0, float(h) * 0.86),
            "color": "#%02x%02x%02x" % tuple(int(c) for c in color[:3]),
            "bold": density > 0.30,
            "family": "",
            "patch": [int(X1), int(Y1), int(X2), int(Y2)],   # 改字时要擦掉的原字范围
        }
        t["orig"] = {k: t[k] for k in ORIG_KEYS}
        texts.append(t)
    texts.sort(key=lambda t: (t["y"], t["x"]))
    return texts, mask


def erase(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return rgb
    import cv2
    bgr = rgb[:, :, ::-1].copy()
    out = cv2.inpaint(bgr, mask, 5, cv2.INPAINT_TELEA)
    return out[:, :, ::-1].copy()


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    h, w = rgb.shape[:2]
    rgb = np.ascontiguousarray(rgb.astype(np.uint8))
    return QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


# ================================================================ 生成 / 保存模板
def build_template(path: str, detector, name: str = "", kind: str = "spec", progress=None, layout=None,
                   inpainter=None) -> dict:
    """分析一张规格图，生成模板并保存，返回模板数据。"""
    # 这一步在后台线程里跑，全程只用 numpy / OpenCV，不碰 Qt 的图片对象
    import cv2
    try:
        data = np.fromfile(str(path), np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        bgr = None
    if bgr is None:
        raise ValueError("读取不了这张图片")
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    H, W = rgb.shape[:2]
    say = progress or (lambda _m: None)
    say("正在识别模特")
    dets = detect_tiled(detector, rgb, 0.2)
    say("正在识别文字")
    ocr = run_ocr(rgb)
    boxes = []
    for item in ocr:
        pts = np.array(item[0], dtype=np.float32)
        boxes.append((*pts.min(0), *pts.max(0)))
    say("正在寻找照片边框")
    lboxes = None
    if layout is not None:
        try:
            lboxes = layout.images(rgb)
        except Exception:
            lboxes = None
    slots = find_slots(rgb, dets, blocks=(kind == "detail" and not lboxes), text_boxes=boxes, layout_boxes=lboxes)
    texts, mask = find_texts(rgb, slots, ocr=ocr)
    say("正在擦除原来的文字")
    if inpainter is not None and texts:
        # AI 去字：直接把整个文字框交给它补（浅色小字、描边、阴影都能一起擦干净）
        box = np.zeros(mask.shape, np.uint8)
        for t in texts:
            x1, y1, x2, y2 = t["patch"]
            box[max(0, y1 - 1):y2 + 1, max(0, x1 - 1):x2 + 1] = 255
        try:
            clean = inpainter.inpaint(rgb, box)
        except Exception:
            clean = erase(rgb, mask)
    else:
        clean = erase(rgb, mask)
    tid = uuid.uuid4().hex[:10]
    folder = templates_dir() / tid
    folder.mkdir(parents=True, exist_ok=True)
    for name_, arr in (("bg.png", clean), ("original.png", rgb)):
        ok, buf = cv2.imencode(".png", np.ascontiguousarray(arr[:, :, ::-1]))
        if not ok:
            raise IOError("保存模板图片失败")
        buf.tofile(str(folder / name_))
    th = rgb if H <= W * 1.4 else rgb[:int(W * 1.4)]
    tw = 360
    th = cv2.resize(th, (tw, max(1, int(th.shape[0] * tw / th.shape[1]))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(th[:, :, ::-1]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    if ok:
        buf.tofile(str(folder / "thumb.jpg"))
    roles = ["正面", "背面"] + [f"图片{i}" for i in range(3, 100)] if kind == "spec" \
        else [f"图片{i}" for i in range(1, 200)]
    for i, s in enumerate(slots):
        s["id"] = uuid.uuid4().hex[:8]
        s["role"] = roles[i] if i < len(roles) else f"图片{i + 1}"
        s.setdefault("shape", "rect")
        s.setdefault("radius", 0.0)
    say("正在保留压在照片上的元素")
    try:
        make_keep_layers(rgb, slots, folder, layout, inpainter, ocr)
    except Exception:
        pass
    tpl = {"id": tid, "kind": kind, "name": name or default_name(path, kind), "w": W, "h": H,
           "slots": slots, "texts": texts,
           "ocr_error": (last_error.strip().splitlines() or [""])[-1][:300] if last_error else "",
           "ocr_raw": len(ocr), "confirmed": False}
    save_template(tpl)
    return tpl


OVERLAY_CLASSES = {"seal", "text", "paragraph_title", "doc_title", "vertical_text", "header_image", "footer_image",
                   "aside_text", "number", "figure_title", "header", "footer", "vision_footnote"}


def make_keep_layers(rgb, slots, folder, layout=None, inpainter=None, ocr=()):
    """给每个照片位做一层「保留层」：换图后盖在新照片上面的原图像素（带透明度）。
    1. 四个角上照片框外侧颜色的像素（白边、底色、描边圆弧）——角对得再不准也不会露原图、压边框；
    2. 压在照片上的元素：徽章 / 印章、照片上的字、回形针这类——用 AI 把它们擦掉再和原图比，差出来的就是元素本身。"""
    import cv2
    from .photo_regions import corner_keep_mask, element_mask
    H, W = rgb.shape[:2]
    # 压在照片上的元素框：版面模型认出的非照片元素 + 文字识别的框
    boxes = []
    if layout is not None:
        try:
            for name_, x1, y1, x2, y2, sc in layout.elements(rgb):
                if name_ in OVERLAY_CLASSES:
                    boxes.append((x1, y1, x2, y2))
        except Exception:
            pass
    for item in ocr or ():
        pts = np.array(item[0], dtype=np.float32)
        boxes.append((*pts.min(0), *pts.max(0)))
    el_mask = np.zeros((H, W), np.uint8)
    for s in slots:
        r = (s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"])
        for b in boxes:
            inter = _overlap(r, b)
            ab = _area(b)
            if ab <= 0 or inter < 0.3 * ab or ab > 0.25 * _area(r):
                continue
            x1, y1, x2, y2 = (int(max(0, b[0] - 3)), int(max(0, b[1] - 3)), int(min(W, b[2] + 3)), int(min(H, b[3] + 3)))
            el_mask[y1:y2, x1:x2] = 255
    clean_el = None
    if el_mask.any() and inpainter is not None:
        try:
            clean_el = inpainter.inpaint(rgb, el_mask)
        except Exception:
            clean_el = None
    for s in slots:
        keep, (X0, Y0) = corner_keep_mask(rgb, s["x"], s["y"], s["w"], s["h"], s.get("shape", "rect"),
                                          float(s.get("radius") or 0))
        bh, bw = keep.shape
        if clean_el is not None:
            sub = el_mask[Y0:Y0 + bh, X0:X0 + bw] > 0
            if sub.any():
                em = element_mask(rgb, clean_el, (X0, Y0, X0 + bw, Y0 + bh))
                keep = np.maximum(keep, em * sub)
        if keep.max() < 0.05:
            s.pop("keep", None)
            continue
        rgba = np.dstack([rgb[Y0:Y0 + bh, X0:X0 + bw], (keep * 255).astype(np.uint8)])
        fn = f"keep_{uuid.uuid4().hex[:8]}.png"
        ok, buf = cv2.imencode(".png", np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]]))
        if ok:
            buf.tofile(str(folder / fn))
            s["keep"] = {"file": fn, "x": float(X0), "y": float(Y0)}


def default_name(path: str, kind: str) -> str:
    """模板默认名字：文件名有意义就用文件名；像 93f31607-61c0-… 这种乱码，就用「规格模板 11-10 14:32」。"""
    import re
    import time
    stem = Path(path).stem
    junk = (re.fullmatch(r"[0-9a-fA-F\-_]{12,}", stem) or re.fullmatch(r"(image|img|IMG|微信图片|下载)[_\- ]?[0-9_\-]*", stem)
            or len(stem) > 40)
    if stem and not junk:
        return stem
    return ("规格模板 " if kind == "spec" else "详情模板 ") + time.strftime("%m-%d %H:%M")


def save_template(tpl: dict) -> None:
    folder = templates_dir() / tpl["id"]
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "template.json.tmp"
    tmp.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(folder / "template.json")


def load_templates(kind: str = "spec") -> list[dict]:
    res = []
    for f in sorted(templates_dir().glob("*/template.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            t = json.loads(f.read_text("utf-8"))
            if t.get("kind", "spec") == kind:
                if not isinstance(t.get("name"), str) or not t.get("name"):
                    # 旧版本有时把模板名存坏了（存成 false），这里修回来
                    t["name"] = "规格模板" if kind == "spec" else "详情模板"
                    try:
                        f.write_text(json.dumps(t, ensure_ascii=False, indent=1), "utf-8")
                    except Exception:
                        pass
                res.append(t)
        except Exception:
            pass
    return res


def template_bg(tpl: dict) -> QImage:
    return QImage(str(templates_dir() / tpl["id"] / "bg.png"))


ORIG_KEYS = ("text", "x", "y", "size", "color", "bold", "family")


def text_changed(t: dict) -> bool:
    """这段字有没有被改过（内容、位置、字号、颜色、字体）。没改过就保留原图上的字，一个像素都不动。"""
    o = t.get("orig")
    if not o or "patch" not in t:
        return True          # 手动加的字、旧版模板：照常画
    for k in ORIG_KEYS:
        a, b = t.get(k), o.get(k)
        if isinstance(a, float) or isinstance(b, float):
            if abs(float(a or 0) - float(b or 0)) > 0.5:
                return True
        elif a != b:
            return True
    return False


def composite_bg(tpl: dict) -> QImage:
    """模板底图：原图为主；改过的字，把原字那一块换成擦干净的底。"""
    from PySide6.QtGui import QPainter
    folder = templates_dir() / tpl["id"]
    orig = QImage(str(folder / "original.png"))
    clean = QImage(str(folder / "bg.png"))
    if orig.isNull() or not any("orig" in t for t in tpl.get("texts", [])):
        return clean            # 旧版模板没有原图信息：用擦干净的底
    changed = [t for t in tpl["texts"] if "patch" in t and text_changed(t)]
    if not changed or clean.isNull():
        return orig
    out = orig.convertToFormat(QImage.Format.Format_RGB32)
    p = QPainter(out)
    for t in changed:
        x1, y1, x2, y2 = t["patch"]
        p.drawImage(x1, y1, clean, x1, y1, x2 - x1, y2 - y1)
    p.end()
    return out


def delete_template(tpl: dict) -> None:
    shutil.rmtree(templates_dir() / tpl["id"], ignore_errors=True)
