"""智能规格：把一张别人的规格图变成模板。

1. 找照片框：用人物识别找到模特，再沿着照片边缘往外扩，得到整个照片框（图片位）。
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


def find_slots(rgb: np.ndarray, dets: list[dict]) -> list[dict]:
    """返回图片位列表 [{"x","y","w","h"}]（原图坐标），按从左到右、从上到下排序。"""
    H, W = rgb.shape[:2]
    k = min(1.0, 900 / max(W, H))
    if k < 1:
        idx_y = (np.arange(int(H * k)) / k).astype(int)
        idx_x = (np.arange(int(W * k)) / k).astype(int)
        small = rgb[idx_y][:, idx_x]
    else:
        small = rgb
    gray = small.astype(np.float32).mean(2)
    seeds = _cluster_people(dets, W, H)
    rects = []
    for s in seeds:
        sx = [v * k for v in s]
        x1, y1, x2, y2 = expand_to_frame(gray, sx)
        rects.append([x1 / k, y1 / k, x2 / k, y2 / k])
    # 重叠很多的合并成一个
    merged: list[list] = []
    for r in sorted(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True):
        dup = False
        for m in merged:
            ix = max(0, min(r[2], m[2]) - max(r[0], m[0]))
            iy = max(0, min(r[3], m[3]) - max(r[1], m[1]))
            if ix * iy > 0.6 * (r[2] - r[0]) * (r[3] - r[1]):
                dup = True
                break
        if not dup:
            merged.append(r)
    merged.sort(key=lambda r: (round(r[0] / max(1, W) * 4), r[1]))
    return [{"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1]} for r in merged]


# ================================================================ 找文字、擦文字
_ocr = None
last_error = ""   # 最近一次文字识别失败的原因


def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _inside(cx: float, cy: float, slots: list[dict]) -> bool:
    return any(s["x"] <= cx <= s["x"] + s["w"] and s["y"] <= cy <= s["y"] + s["h"] for s in slots)


def find_texts(rgb: np.ndarray, slots: list[dict], min_score: float = 0.5):
    """返回 (文字图层列表, 需要擦掉的像素蒙版)。照片框里面的字不算。"""
    H, W = rgb.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    texts = []
    global last_error
    try:
        result, _ = get_ocr()(rgb[:, :, ::-1].copy())
        last_error = ""
    except Exception as e:
        import traceback
        last_error = f"{e}\n{traceback.format_exc()}"
        result = None
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
        texts.append({
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "x": float(x1), "y": float(y1), "w": float(w), "h": float(h),
            "size": max(8.0, float(h) * 0.86),
            "color": "#%02x%02x%02x" % tuple(int(c) for c in color[:3]),
            "bold": density > 0.30,
            "family": "",
        })
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
def build_template(path: str, detector, name: str = "") -> dict:
    """分析一张规格图，生成模板并保存，返回模板数据。"""
    from .model import load_qimage
    img = load_qimage(path)
    if img is None:
        raise ValueError("读取不了这张图片")
    rgb = qimage_to_rgb(img)
    H, W = rgb.shape[:2]
    dets = detector.detect(img, 0.2) if detector is not None else []
    slots = find_slots(rgb, dets)
    texts, mask = find_texts(rgb, slots)
    clean = erase(rgb, mask)
    tid = uuid.uuid4().hex[:10]
    folder = templates_dir() / tid
    folder.mkdir(parents=True, exist_ok=True)
    rgb_to_qimage(clean).save(str(folder / "bg.png"), "PNG")
    img.save(str(folder / "original.png"), "PNG")
    roles = ["正面", "背面"] + [f"图片{i}" for i in range(3, 10)]
    for i, s in enumerate(slots):
        s["id"] = uuid.uuid4().hex[:8]
        s["role"] = roles[i] if i < len(roles) else f"图片{i + 1}"
        s["radius"] = 0.0
    tpl = {"id": tid, "kind": "spec", "name": name or Path(path).stem, "w": W, "h": H,
           "slots": slots, "texts": texts}
    save_template(tpl)
    return tpl


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
                res.append(t)
        except Exception:
            pass
    return res


def template_bg(tpl: dict) -> QImage:
    return QImage(str(templates_dir() / tpl["id"] / "bg.png"))


def delete_template(tpl: dict) -> None:
    shutil.rmtree(templates_dir() / tpl["id"], ignore_errors=True)
