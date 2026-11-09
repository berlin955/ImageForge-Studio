"""在规格图 / 详情图里找出所有照片区域（不依赖 Qt，方便单独测试）。

思路：设计稿里的照片都有一圈清楚的边（照片和底色之间、或者相框描边），
把这些边连起来后从图片外面往里「灌水」，灌不进去的封闭区域就是候选；
再看区域里的颜色是否丰富（照片颜色多，色块、表格颜色少），留下真正的照片，
最后判断照片框的形状：直角、圆角、胶囊（两头半圆）还是椭圆。
"""
from __future__ import annotations

import numpy as np

WORK_W = 700      # 分析时缩小到的宽度
PAD = 6           # 四周补一圈底色，让贴着图片边缘的照片也能形成封闭区域


def _small(rgb: np.ndarray):
    import cv2
    H, W = rgb.shape[:2]
    k = min(1.0, WORK_W / W)
    if k < 1:
        sm = cv2.resize(rgb, (max(1, int(W * k)), max(1, int(H * k))), interpolation=cv2.INTER_AREA)
    else:
        sm = rgb.copy()
    return sm, k


def background_color(sm: np.ndarray) -> np.ndarray:
    """设计底色：四周边缘上出现最多的那种颜色（照片颜色分散，不会抢到最多）。"""
    border = np.concatenate([sm[0], sm[-1], sm[:, 0], sm[:, -1]]).astype(np.int32)
    q = border // 16
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    top = np.bincount(keys).argmax()
    return border[keys == top].mean(0)


def edge_map(sm: np.ndarray, lo: int = 25, hi: int = 60, close: int = 5) -> np.ndarray:
    """边缘图（亮度和颜色的边都算），已经连成线；四周补的一圈全部当作边。"""
    import cv2
    pad = cv2.copyMakeBorder(sm, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
    lab = cv2.cvtColor(np.ascontiguousarray(pad), cv2.COLOR_RGB2LAB)
    e = np.zeros(pad.shape[:2], np.uint8)
    for c in range(3):
        e |= cv2.Canny(cv2.GaussianBlur(lab[:, :, c], (3, 3), 0), lo, hi)
    e = cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    e[:PAD, :] = 255
    e[-PAD:, :] = 255
    e[:, :PAD] = 255
    e[:, -PAD:] = 255
    return e


def outside_mask(sm: np.ndarray, e: np.ndarray) -> np.ndarray:
    """设计底色区域：从四周边缘上是底色的点出发「灌水」，能灌到的地方。"""
    import cv2
    bgc = background_color(sm).astype(np.float32)
    h, w = sm.shape[:2]
    ff = e.copy()
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    dist = np.abs(sm.astype(np.float32) - bgc).sum(2)
    # 只从边缘上「连续一长段都是底色」的地方开始灌：照片里偶尔有一小段颜色和底色很像（比如皮肤），不能算
    sides = [[(x, 0) for x in range(w)], [(x, h - 1) for x in range(w)],
             [(0, y) for y in range(h)], [(w - 1, y) for y in range(h)]]
    for side in sides:
        need = max(12, int(len(side) * 0.04))
        run: list = []
        for x, y in side + [(-1, -1)]:
            if x >= 0 and dist[y, x] < 30:
                run.append((x, y))
                continue
            if len(run) >= need:
                for rx, ry in run[::4]:
                    if ff[ry + PAD, rx + PAD] == 0:
                        cv2.floodFill(ff, mask, (rx + PAD, ry + PAD), 128)
            run = []
    return ff == 128


def color_richness(sm: np.ndarray, reg: np.ndarray) -> int:
    """区域里用到的颜色种类（每个通道分 16 档）。照片通常几十种以上，色块 / 表格只有几种。"""
    import cv2
    r = cv2.erode(reg, np.ones((7, 7), np.uint8)) > 0
    n = int(r.sum())
    if n < 50:
        return 0
    q = (sm[r] // 16).astype(np.int32)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    cnt = np.bincount(keys, minlength=4096)
    return int((cnt > n * 0.002).sum())


def fit_shape(reg: np.ndarray):
    """返回 (x, y, w, h, shape, radius)：shape 为 rect / ellipse，radius 是圆角占短边的比例（0~0.5）。"""
    import cv2
    ys, xs = np.nonzero(reg)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    w, h = x1 - x0, y1 - y0
    m = (reg[y0:y1, x0:x1] > 0)
    area = m.sum()

    def iou(cand):
        inter = (cand & m).sum()
        return inter / max(1, area + cand.sum() - inter)

    best = (-1.0, "rect", 0.0)
    for ratio in (0.0, 0.04, 0.08, 0.12, 0.18, 0.25, 0.33, 0.42, 0.5):
        c = np.zeros((h, w), np.uint8)
        r = int(round(min(w, h) * ratio))
        if r <= 0:
            c[:] = 1
        else:
            cv2.rectangle(c, (r, 0), (w - 1 - r, h - 1), 1, -1)
            cv2.rectangle(c, (0, r), (w - 1, h - 1 - r), 1, -1)
            for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
                cv2.circle(c, (cx, cy), r, 1, -1)
        s = iou(c > 0)
        if s > best[0] + 0.004:      # 差不多时选更简单的形状
            best = (s, "rect", ratio)
    c = np.zeros((h, w), np.uint8)
    cv2.ellipse(c, (w // 2, h // 2), (max(1, w // 2), max(1, h // 2)), 0, 0, 360, 1, -1)
    s = iou(c > 0)
    if s > best[0] + 0.004:
        best = (s, "ellipse", 0.5)
    return float(x0), float(y0), float(w), float(h), best[1], float(best[2]), float(best[0])


# 先用标准灵敏度找；照片和底色分得不够清楚时，用更灵敏的一档再找一次
STRICT = (25, 60, 5)
SENSITIVE = (12, 32, 9)


def find_regions(rgb: np.ndarray, min_area: float = 0.025, min_colors: int = 30, level=STRICT) -> list[dict]:
    """返回照片区域列表（原图坐标）：{x, y, w, h, shape, radius, colors, fit, photo}。"""
    import cv2
    H, W = rgb.shape[:2]
    sm, k = _small(rgb)
    h, w = sm.shape[:2]
    e = edge_map(sm, *level)
    enclosed = (~outside_mask(sm, e)).astype(np.uint8)
    enclosed = cv2.morphologyEx(enclosed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    enclosed = enclosed[PAD:-PAD, PAD:-PAD]
    n, lbl, st, _ = cv2.connectedComponentsWithStats(enclosed, 8)
    out = []
    for i in range(1, n):
        x, y, ww, hh, a = st[i]
        if a < min_area * h * w or ww < 0.10 * w or hh < 0.05 * h:
            continue
        reg = (lbl == i).astype(np.uint8)
        # 把区域里的小洞补上（照片里的文字、细节不影响外形）
        cnts, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        reg = np.zeros_like(reg)
        cv2.drawContours(reg, cnts, -1, 1, -1)
        colors = color_richness(sm, reg)
        fx, fy, fw, fh, shape, radius, fit = fit_shape(reg)
        if fit < 0.80:
            continue      # 形状太不规则，多半是几块东西粘在一起，不当作照片框
        # 往里收一点，避开相框的描边；贴着整张图边缘的那一侧不收
        ins = max(1.0, min(fw, fh) * 0.006)
        l = 0 if fx <= 1 else ins
        t = 0 if fy <= 1 else ins
        r = 0 if fx + fw >= w - 1 else ins
        b = 0 if fy + fh >= h - 1 else ins
        X, Y = (fx + l) / k, (fy + t) / k
        X2, Y2 = (fx + fw - r) / k, (fy + fh - b) / k
        if fx <= 1:
            X = 0.0
        if fy <= 1:
            Y = 0.0
        if fx + fw >= w - 1:
            X2 = float(W)
        if fy + fh >= h - 1:
            Y2 = float(H)
        out.append({"x": X, "y": Y, "w": X2 - X, "h": Y2 - Y, "shape": shape, "radius": radius,
                    "colors": colors, "fit": round(fit, 3), "photo": colors >= min_colors})
    return out
