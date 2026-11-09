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


# ---------------------------------------------------------------- 贴边校准
def shape_points(x0, y0, x1, y1, shape, radius, n=360):
    """沿形状边缘均匀取点，返回 (n, 2) 数组。"""
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if shape == "ellipse":
        return np.stack([x0 + w / 2 + np.cos(t) * w / 2, y0 + h / 2 + np.sin(t) * h / 2], 1)
    r = min(w, h) * min(0.5, max(0.0, radius))
    # 圆角矩形：四条直边 + 四段圆弧，按周长比例分配点数
    segs = []
    straight = [((x0 + r, y0), (x1 - r, y0)), ((x1, y0 + r), (x1, y1 - r)),
                ((x1 - r, y1), (x0 + r, y1)), ((x0, y1 - r), (x0, y0 + r))]
    arcs = [((x1 - r, y0 + r), -np.pi / 2), ((x1 - r, y1 - r), 0.0), ((x0 + r, y1 - r), np.pi / 2),
            ((x0 + r, y0 + r), np.pi)]
    lens = [np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in straight] + [np.pi * r / 2] * 4
    total = max(1e-6, sum(lens))
    for i in range(4):
        (a, b), L = straight[i], lens[i]
        m = max(2, int(n * L / total))
        u = np.linspace(0, 1, m, endpoint=False)
        segs.append(np.stack([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u], 1))
        (c, a0), La = arcs[i], lens[4 + i]
        if r > 0.5:
            m = max(2, int(n * La / total))
            u = np.linspace(a0, a0 + np.pi / 2, m, endpoint=False)
            segs.append(np.stack([c[0] + np.cos(u) * r, c[1] + np.sin(u) * r], 1))
    return np.concatenate(segs, 0)


def _sample(img, pts):
    h, w = img.shape[:2]
    xi = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
    yi = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
    return img[yi, xi]


def corner_radius(grad, x0, y0, x1, y1, fixed):
    """估计圆角大小（占短边的比例）。贴着整张图边缘的角不算（那里不可能是圆角）。
    直角的框，对角线一进去就碰到边；圆角的框，要走一段才碰到边：走的距离 d 和圆角半径 r 的关系是 d = r·(1 − 1/√2)。"""
    h, w = grad.shape
    side = min(x1 - x0, y1 - y0)
    if side < 20:
        return None
    reach = int(side * 0.16)          # 最多走到胶囊形的程度（d = 0.5·side·0.293）
    ds = []
    corners = [(x0, y0, 1, 1, fixed[0] or fixed[1]), (x1, y0, -1, 1, fixed[2] or fixed[1]),
               (x0, y1, 1, -1, fixed[0] or fixed[3]), (x1, y1, -1, -1, fixed[2] or fixed[3])]
    for cx, cy, sx, sy, fx in corners:
        if fx:
            continue
        prof = []
        for t in range(0, reach):
            xs = int(round(cx + sx * t))
            ys = int(round(cy + sy * t))
            if not (0 <= xs < w and 0 <= ys < h):
                break
            prof.append(grad[max(0, ys - 1):ys + 2, max(0, xs - 1):xs + 2].max())
        if len(prof) < 4:
            continue
        prof = np.array(prof)
        peak = float(prof.max())
        if peak < 15:
            continue
        # 第一个明显的边（强度达到最大值的 60%）
        d = int(np.argmax(prof >= peak * 0.6))
        ds.append(d)
    if not ds:
        return None
    d = float(np.median(ds))
    if len(ds) >= 2 and (max(ds) - min(ds)) > max(4.0, d * 0.6):
        return 0.0                    # 几个角说法不一致：多半是照片内容，按直角算
    r = d / (1 - 1 / np.sqrt(2))
    ratio = r / side
    return 0.0 if ratio < 0.02 else float(min(0.5, ratio))


def snap_sides(rgb: np.ndarray, x: float, y: float, w: float, h: float, fixed=None, reach: int | None = None):
    """在原图全分辨率下，逐条边找「真正的照片边」，精确到亚像素。
    每条边只看中间 70% 那一段（避开圆角），沿垂直方向前后搜索：
      · 这条线本身要清楚（两侧颜色差得多）；
      · 线的外侧要是均匀的边框 / 底色（照片里面的线条，比如窗帘褶皱、门框，外侧还是照片纹理，会被排除）；
    再用抛物线插值求亚像素位置。"""
    import cv2
    H, W = rgb.shape[:2]
    if fixed is None:
        fixed = [x <= 0.5, y <= 0.5, x + w >= W - 0.5, y + h >= H - 0.5]
    if reach is None:
        reach = int(max(8, min(w, h) * 0.04))
    lab = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
    out = [x, y, x + w, y + h]
    band_info = []
    for side in range(4):
        if fixed[side]:
            continue
        vertical = side in (0, 2)              # 左右两条边是竖线
        outward = -1 if side in (0, 1) else 1  # 左、上边的外侧在坐标小的一边
        pos = out[side]
        lo, hi = (out[1], out[3]) if vertical else (out[0], out[2])
        a = int(lo + (hi - lo) * 0.15)
        b = int(hi - (hi - lo) * 0.15)
        if b - a < 8:
            continue
        lim = H if not vertical else W

        def line(p):
            if p < 0 or p >= lim:
                return None
            return lab[a:b, p] if vertical else lab[p, a:b]

        scores = []
        edges = []
        offs = list(range(-reach, reach + 1))
        for o in offs:
            p = int(round(pos)) + o
            # 照片边界在像素 p 的起点（左 / 上边）或终点（右 / 下边）：外侧像素和内侧像素
            p_in = p if outward < 0 else p - 1
            p_out = p - 1 if outward < 0 else p
            li, lo_ = line(p_in), line(p_out)
            if li is None or lo_ is None:
                scores.append(-1e9)
                edges.append(0.0)
                continue
            edge = float(np.median(np.abs(li - lo_).sum(1)))
            edges.append(edge)
            # 外侧 3 个像素宽的条带是不是均匀
            strip = [line(p_out + outward * k) for k in range(0, 3)]
            strip = [v for v in strip if v is not None]
            if strip:
                st = np.concatenate(strip, 0)
                unif = float(np.median(np.abs(st - np.median(st, 0)).sum(1)))
            else:
                unif = 0.0
            scores.append(edge - 1.5 * unif)
        sc = np.array(scores)
        best = float(sc.max())
        if best < 12:
            continue                           # 找不到清楚的边，不动
        k = int(sc.argmax())
        # 最强的那条线往里如果还有一条清楚的线，而且两条线之间是一条颜色均匀的带子（边框 / 描边），
        # 照片要贴在里侧那条线上（照片里的线条，比如窗帘褶皱，和边框之间是照片纹理，不是均匀的带子）
        base = int(round(pos))
        for i in sorted(range(len(offs)), key=lambda i: -(-offs[i] * outward)):
            if -offs[i] * outward <= -offs[k] * outward:
                break                          # 只看比最强那条更靠里的
            # 这里只看线本身清不清楚（细边框外侧 3 像素里混着边框和底色，不能按「外侧均匀」扣分）
            if edges[i] < max(12.0, edges[k] * 0.15):
                continue
            p_i, p_k = base + offs[i], base + offs[k]
            lo_p, hi_p = sorted((p_i, p_k))
            if hi_p - lo_p > max(3, min(w, h) * 0.035):
                continue                       # 边框带子不会太宽（太宽的多半是照片里的白墙之类）
            band = [line(q) for q in range(lo_p, hi_p)]
            band = [v for v in band if v is not None]
            if len(band) < 1:
                continue
            # 每一行自己颜色均匀就算（白线 + 抗锯齿过渡这种几行不同色的也行）
            devs = [float(np.median(np.abs(v - np.median(v, 0)).sum(1))) for v in band]
            if float(np.median(devs)) < 10:
                k = i
                break
        frac = 0.0
        # 设计图里的边几乎都对齐整像素：边很清楚（两边相邻位置都弱得多）就直接取整；
        # 只有边是糊的（缩放过的图）才用抛物线插值求亚像素位置
        if 0 < k < len(edges) - 1:
            l_, c_, r_ = edges[k - 1], edges[k], edges[k + 1]
            # 真正糊的边两侧都有渐变；只有一侧强（旁边紧挨着另一条硬边，比如 1 像素描边）不算，直接取整
            if min(l_, r_) > c_ * 0.3 and max(l_, r_) < c_:
                den = l_ - 2 * c_ + r_
                if den < 0:
                    frac = float(np.clip(0.5 * (l_ - r_) / den, -0.5, 0.5))
        out[side] = int(round(pos)) + offs[k] + frac
        # 记下这条边剥掉的边框带子（颜色、粗细），给另外几条边参考
        k0 = int(sc.argmax())
        if k != k0:
            lo_p, hi_p = sorted((base + offs[k], base + offs[k0]))
            bl = [line(q) for q in range(lo_p, hi_p)]
            bl = [v for v in bl if v is not None]
            if bl:
                band_info.append((np.median(np.concatenate(bl, 0), 0), hi_p - lo_p))
    # 同一个相框的描边四边一样粗：有的边量到了描边，另外的边如果紧贴内侧也是同样颜色、同样粗细的一条，也剥掉
    if band_info:
        bcol = np.median(np.array([b[0] for b in band_info]), 0)
        bt = int(round(np.median([b[1] for b in band_info])))
        for side in range(4):
            if fixed[side] or bt < 1:
                continue
            vertical = side in (0, 2)
            inward = 1 if side in (0, 1) else -1
            lo, hi = (out[1], out[3]) if vertical else (out[0], out[2])
            a = int(lo + (hi - lo) * 0.15)
            b = int(hi - (hi - lo) * 0.15)
            p0 = int(round(out[side])) if inward > 0 else int(round(out[side])) - 1
            ok = True
            for t in range(bt):
                q = p0 + inward * t
                if not (0 <= q < (W if vertical else H)):
                    ok = False
                    break
                ln = lab[a:b, q] if vertical else lab[q, a:b]
                if float(np.median(np.abs(ln - bcol).sum(1))) > 30:
                    ok = False
                    break
            if ok:
                out[side] += inward * bt
    return out[0], out[1], out[2] - out[0], out[3] - out[1]


def corner_radii(rgb: np.ndarray, x: float, y: float, w: float, h: float):
    """逐个角量圆角半径（像素）。返回 [左上, 右上, 左下, 右下]，量不了的是 None。
    从角尖沿对角线往里走：
      · 先可能经过角尖外面的底色（圆角外面那一小块），
      · 再经过边框色（紧贴照片边外侧那种颜色，比如白边），
      · 穿过边框后遇到的第一个别的颜色就是照片（哪怕照片的颜色和底色一样，也不会弄错）。
    走过的距离 d 和圆角半径 r 的关系：d = r·(1 − 1/√2)。"""
    H, W = rgb.shape[:2]
    img = rgb.astype(np.float32)
    side = min(w, h)
    reach = int(side * 0.16) + 2
    X0, Y0, X1, Y1 = x, y, x + w, y + h
    res = []
    for cx, cy, sx, sy in ((X0, Y0, 1, 1), (X1 - 1, Y0, -1, 1), (X0, Y1 - 1, 1, -1), (X1 - 1, Y1 - 1, -1, -1)):
        if (sx > 0 and X0 <= 0.5) or (sx < 0 and X1 >= W - 0.5) or (sy > 0 and Y0 <= 0.5) or (sy < 0 and Y1 >= H - 0.5):
            res.append(None)               # 贴着整张图边缘：不可能是圆角
            continue
        oy = int(round(cy - sy))
        xs = [int(round(cx + sx * k)) for k in range(int(side * 0.2), int(side * 0.3))]
        xs = [v for v in xs if 0 <= v < W]
        if not (0 <= oy < H) or len(xs) < 3:
            res.append(None)
            continue
        frame = np.median(img[oy, xs], axis=0)          # 紧贴照片边外侧的颜色（边框 / 底色）
        tips = [img[int(round(cy - sy * k)), int(round(cx - sx * k))] for k in range(1, 4)
                if 0 <= cx - sx * k < W and 0 <= cy - sy * k < H]
        tip = np.median(np.array(tips), axis=0) if tips else frame   # 角尖外面的底色

        def like(p_, c_):
            return np.abs(p_ - c_).sum() <= 45

        d = None
        seen_frame = False
        for t in range(0, reach):
            px, py = int(round(cx + sx * t)), int(round(cy + sy * t))
            if not (0 <= px < W and 0 <= py < H):
                break
            p1 = img[py, px]
            if like(p1, frame):
                seen_frame = True
                continue
            if like(p1, tip) and not seen_frame:
                continue
            px2, py2 = int(round(cx + sx * (t + 1))), int(round(cy + sy * (t + 1)))
            if 0 <= px2 < W and 0 <= py2 < H:
                p2 = img[py2, px2]
                if like(p2, frame) or (like(p2, tip) and not seen_frame):
                    continue                   # 抗锯齿的过渡像素：再看下一个
            d = t
            break
        if d is None:
            res.append(None)
        else:
            res.append(0.0 if d < 2 else (d + 0.5) / (1 - 1 / np.sqrt(2)))
    return res


def corner_radius_px(rgb: np.ndarray, x: float, y: float, w: float, h: float):
    """整个照片位用的圆角（占短边比例），取各角里第二小的（个别角量偏了不影响）。返回 (比例, 量到的角数)。"""
    rs = [r for r in corner_radii(rgb, x, y, w, h) if r is not None]
    if not rs:
        return None, 0
    rs.sort()
    r = rs[1] if len(rs) >= 3 else rs[0]
    side = min(w, h)
    return (0.0 if r < 2 else float(min(0.5, r / side))), len(rs)


def trim_uniform_margins(rgb: np.ndarray, x: float, y: float, w: float, h: float, max_frac: float = 0.16,
                         ignore=()):
    """照片位里面如果还包着一圈颜色均匀的边（拍立得白边、纯色相框），往里收到真正的照片为止。
    逐行（逐列）往里看：这一行颜色几乎一样、而且和最外面那行颜色接近，就算边框。"""
    H, W = rgb.shape[:2]
    X0, Y0, X1, Y1 = int(round(x)), int(round(y)), int(round(x + w)), int(round(y + h))
    X0, Y0, X1, Y1 = max(0, X0), max(0, Y0), min(W, X1), min(H, Y1)
    if X1 - X0 < 20 or Y1 - Y0 < 20:
        return x, y, w, h
    reg = rgb[Y0:Y1, X0:X1].astype(np.float32)
    rh, rw = reg.shape[:2]
    # 边框带子上常常写着字（比如黑色底栏上的「建议体重」）：文字的像素用这一行其余像素的中位色代替，不参与判断
    skip = np.zeros((rh, rw), bool)
    for bx0, by0, bx1, by1 in ignore:
        ix0, iy0 = int(max(X0, bx0 - 2)) - X0, int(max(Y0, by0 - 2)) - Y0
        ix1, iy1 = int(min(X1, bx1 + 2)) - X0, int(min(Y1, by1 + 2)) - Y0
        if ix1 > ix0 and iy1 > iy0:
            skip[iy0:iy1, ix0:ix1] = True
    if skip.any():
        reg = reg.copy()
        for yy in np.where(skip.any(1))[0]:
            row_ok = ~skip[yy]
            if row_ok.any():
                reg[yy, skip[yy]] = np.median(reg[yy, row_ok], 0)

    def depth(lines, limit):
        """lines: 从外往里的一行行像素 (n, len, 3)。返回要剥掉的厚度（没有就是 0）。
        可以连着剥好几层：背景线、阴影线、白纸边……每一行只要「自己颜色均匀」（85% 以上的像素
        和这一行的主色接近，允许回形针、贴纸压着）就算边框；遇到第一行不均匀的就停。
        停下的地方必须是「突然」变成照片：慢慢过渡的（比如照片里的暗墙）不算边框。"""
        if len(lines) < 4:
            return 0

        def frac(ln, ref):
            return float((np.abs(ln - ref).sum(1) < 30).mean())

        d = 0
        last = None
        for ln in lines[:limit]:
            core = ln[int(len(ln) * 0.04):int(len(ln) * 0.96)]
            ref = np.median(core, axis=0)
            if frac(core, ref) < 0.85:
                break
            last = ref
            d += 1
        if d == 0 or d >= limit or d + 2 >= len(lines) or last is None:
            return 0
        after = (frac(lines[d], last) + frac(lines[d + 1], last)) / 2
        return d if after < 0.45 else 0

    ly, lx = int(rh * max_frac), int(rw * max_frac)
    top = depth(reg, ly)
    bot = depth(reg[::-1], ly)
    lef = depth(reg.transpose(1, 0, 2), lx)
    rig = depth(reg.transpose(1, 0, 2)[::-1], lx)
    # 只有一两像素的「边」多半是抗锯齿，不算
    top, bot, lef, rig = [v if v >= 3 else 0 for v in (top, bot, lef, rig)]
    return x + lef, y + top, w - lef - rig, h - top - bot


def refine_shape(rgb: np.ndarray, x: float, y: float, w: float, h: float, shape: str, radius: float):
    """把粗略找到的照片框吸附到真实的边上（原图坐标）。
    在框附近算边缘强度，微调四条边和圆角大小，让形状的轮廓刚好压在最清楚的那条边上；
    如果相框有描边，再往里找描边的内侧，让照片填到描边里面、不盖住描边。"""
    import cv2
    H, W = rgb.shape[:2]
    m = int(max(8, min(w, h) * 0.06))
    cx0, cy0 = int(max(0, x - m)), int(max(0, y - m))
    cx1, cy1 = int(min(W, x + w + m)), int(min(H, y + h + m))
    crop = rgb[cy0:cy1, cx0:cx1]
    if crop.size == 0:
        return x, y, w, h, shape, radius
    k = min(1.0, 900 / max(crop.shape[:2]))
    if k < 1:
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * k)), max(1, int(crop.shape[0] * k))),
                          interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (3, 3), 0)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt((gx ** 2 + gy ** 2).sum(2))
    grad = cv2.GaussianBlur(grad, (3, 3), 0)
    ch, cw = grad.shape
    # 参数换到裁切图坐标
    p = [(x - cx0) * k, (y - cy0) * k, (x + w - cx0) * k, (y + h - cy0) * k, radius]
    p0 = list(p)
    fixed = [x <= 1, y <= 1, x + w >= W - 1, y + h >= H - 1]      # 贴着整张图边缘的边不动
    lim = max(4.0, min(p[2] - p[0], p[3] - p[1]) * 0.025)          # 每条边最多挪这么多
    # 边缘强度封顶：避免被照片里很强的线条（衣服边、身体轮廓）吸过去
    pts0 = shape_points(p[0], p[1], p[2], p[3], shape, p[4])
    cap = float(np.median(_sample(grad, pts0))) * 1.5 + 1.0
    gcap = np.minimum(grad, cap)

    def score(q, g=None):
        if q[2] - q[0] < 10 or q[3] - q[1] < 10:
            return -1.0
        pts = shape_points(q[0], q[1], q[2], q[3], shape, q[4])
        inside = (pts[:, 0] > 1) & (pts[:, 0] < cw - 2) & (pts[:, 1] > 1) & (pts[:, 1] < ch - 2)
        if inside.mean() < 0.5:
            return -1.0
        pts = pts[inside]
        # 外法线方向：边的外侧应该是平整的设计底色 / 描边，里面才是照片
        tan = np.roll(pts, -1, 0) - np.roll(pts, 1, 0)
        nrm = np.stack([tan[:, 1], -tan[:, 0]], 1)
        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1, keepdims=True))
        ctr = np.array([(q[0] + q[2]) / 2, (q[1] + q[3]) / 2])
        flip = ((pts - ctr) * nrm).sum(1) < 0
        nrm[flip] *= -1
        on = _sample(gcap if g is None else g, pts).mean()
        out = _sample(gcap, pts + nrm * 3.0).mean()
        return float(on - 0.8 * out)

    best = score(p)
    # 圆角大小：从每个角沿对角线往里走，看相框的边从哪里开始
    if shape != "ellipse" and radius < 0.3:      # 胶囊形已经由封闭轮廓判断出来了，不再重估
        rr = corner_radius(grad, p[0], p[1], p[2], p[3], fixed)
        if rr is not None:
            q = p[:4] + [rr]
            best, p = score(q), q
    for step in (6.0, 3.0, 1.5, 0.75):
        improved = True
        loops = 0
        while improved and loops < 25:
            improved = False
            loops += 1
            for i in range(5):
                if i < 4 and fixed[i]:
                    continue
                if i == 4 and shape == "ellipse":
                    continue
                for d in (-step, step):
                    q = list(p)
                    q[i] += d if i < 4 else d / max(10.0, min(q[2] - q[0], q[3] - q[1]))
                    if i == 4:
                        q[4] = float(min(0.5, max(0.0, q[4])))
                    elif abs(q[i] - p0[i]) > lim:
                        continue
                    sc = score(q)
                    if sc > best + 1e-3:
                        best, p, improved = sc, q, True
    # 有描边的话，往里找描边内侧那条边
    inset = 0.0
    if best > 0:
        prof = []
        for d in np.arange(0, max(3, min(p[2] - p[0], p[3] - p[1]) * 0.05), 0.75):
            q = [p[0] + d, p[1] + d, p[2] - d, p[3] - d]
            r2 = p[4] * min(p[2] - p[0], p[3] - p[1]) - d
            r2 = max(0.0, r2) / max(1.0, min(q[2] - q[0], q[3] - q[1]))
            prof.append((d, score(q + [r2])))
        ds = np.array([a for a, _ in prof])
        vs = np.array([b for _, b in prof])
        # 先离开主边（强度掉到一半以下），再遇到的第二个峰就是描边内侧
        low = np.where(vs < best * 0.55)[0]
        if len(low):
            j0 = low[0]
            rest = vs[j0:]
            if len(rest) > 2:
                j = j0 + int(rest.argmax())
                if vs[j] > best * 0.45 and ds[j] > 0:
                    inset = ds[j] + 0.75
        if inset > 0:
            # 主边和内侧边之间必须是一圈颜色均匀的描边，否则是照片内容，不算
            d = inset / 2
            q = [p[0] + d, p[1] + d, p[2] - d, p[3] - d]
            r2 = max(0.0, p[4] * min(p[2] - p[0], p[3] - p[1]) - d) / max(1.0, min(q[2] - q[0], q[3] - q[1]))
            band = _sample(crop.astype(np.float32), shape_points(q[0], q[1], q[2], q[3], shape, r2))
            if float(band.std(0).mean()) > 14:
                inset = 0.0
        if inset == 0:
            inset = 0.75
    q = [p[0] + inset * (not fixed[0]), p[1] + inset * (not fixed[1]),
         p[2] - inset * (not fixed[2]), p[3] - inset * (not fixed[3])]
    r_px = p[4] * min(p[2] - p[0], p[3] - p[1]) - inset
    nr = max(0.0, r_px) / max(1.0, min(q[2] - q[0], q[3] - q[1]))
    X0, Y0 = q[0] / k + cx0, q[1] / k + cy0
    X1, Y1 = q[2] / k + cx0, q[3] / k + cy0
    if fixed[0]:
        X0 = 0.0
    if fixed[1]:
        Y0 = 0.0
    if fixed[2]:
        X1 = float(W)
    if fixed[3]:
        Y1 = float(H)
    return X0, Y0, X1 - X0, Y1 - Y0, shape, (0.5 if shape == "ellipse" else float(min(0.5, nr)))


# ---------------------------------------------------------------- 保留层（盖在新照片上面的原图像素）
def corner_keep_mask(rgb: np.ndarray, x: float, y: float, w: float, h: float, shape: str, radius: float):
    """照片位四个角「圆弧外侧」那一小块保留原图像素（白边、底色、描边的圆弧）。
    每个角用自己量出来的圆角半径，纯几何计算、1 像素抗锯齿，不靠颜色猜，不会漏进照片里。
    返回和照片位外接矩形一样大的 0~1 浮点蒙版，以及它的左上角坐标。"""
    H, W = rgb.shape[:2]
    X0, Y0 = int(np.floor(x)), int(np.floor(y))
    X1, Y1 = int(np.ceil(x + w)), int(np.ceil(y + h))
    X0, Y0, X1, Y1 = max(0, X0), max(0, Y0), min(W, X1), min(H, Y1)
    bw, bh = X1 - X0, Y1 - Y0
    keep = np.zeros((bh, bw), np.float32)
    if shape == "ellipse" or radius >= 0.45 or bw < 20 or bh < 20:
        return keep, (X0, Y0)
    side = min(w, h)
    slot_r = radius * side
    radii = corner_radii(rgb, x, y, w, h)
    # 各角的半径不能比整个照片位的半径大太多（个别角量偏了，比如照片角落正好是暗色），方角的只留抗锯齿那一点
    cap = 2.0 if slot_r < 1.5 else slot_r * 1.3 + 2
    for (cx, cy, sx, sy), r in zip(((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)), radii):
        if r is None:
            continue
        r = float(min(r, cap))
        if r < 1.5:
            continue
        # 圆心在角尖往里 r 的位置；圆弧外侧（离圆心比 r 远、又在角落那个 r×r 方块里）就是要保留的
        ccx, ccy = cx + sx * r, cy + sy * r
        xa = int(np.floor(min(cx, ccx))) - 1
        xb = int(np.ceil(max(cx, ccx))) + 1
        ya = int(np.floor(min(cy, ccy))) - 1
        yb = int(np.ceil(max(cy, ccy))) + 1
        xa, ya = max(X0, xa), max(Y0, ya)
        xb, yb = min(X1, xb), min(Y1, yb)
        if xb <= xa or yb <= ya:
            continue
        yy, xx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
        px, py = xx + 0.5, yy + 0.5                       # 像素中心
        in_corner = ((px - ccx) * sx < 0) & ((py - ccy) * sy < 0)
        dist = np.sqrt((px - ccx) ** 2 + (py - ccy) ** 2)
        a = np.clip(dist - r + 0.5, 0, 1) * in_corner      # 1 像素抗锯齿
        keep[ya - Y0:yb - Y0, xa - X0:xb - X0] = np.maximum(keep[ya - Y0:yb - Y0, xa - X0:xb - X0], a)
    return keep, (X0, Y0)


def element_mask(orig: np.ndarray, clean: np.ndarray, box, thr: float = 28.0):
    """压在照片上的元素（徽章、回形针、照片上的字）的精确蒙版：
    原图和「AI 把这块擦掉以后」的图对比，差得多的就是元素本身。返回 box 大小的 0~1 蒙版。
    AI 补出来的照片纹理和原照片本来就不完全一样，所以要求差值能明显分成「元素」和「背景」两档，
    而且元素只占框里的一部分；整块都不一样的（多半是照片本身），不算元素。"""
    import cv2
    x0, y0, x1, y1 = box
    a = orig[y0:y1, x0:x1].astype(np.float32)
    b = clean[y0:y1, x0:x1].astype(np.float32)
    d = np.abs(a - b).sum(2)
    if d.size == 0 or d.max() < thr * 2:
        return np.zeros(d.shape, np.float32)
    d8 = np.clip(d, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = max(float(t), thr * 1.5)
    hard = d > t
    frac = float(hard.mean())
    if frac > 0.45:
        return np.zeros(d.shape, np.float32)
    # 两档要分得开：元素部分的差值明显大于背景部分
    lo = float(np.median(d[~hard])) if (~hard).any() else 0.0
    hi = float(np.median(d[hard])) if hard.any() else 0.0
    if hi < lo * 2.5 + thr:
        return np.zeros(d.shape, np.float32)
    m = np.clip((d - lo * 1.5) / max(1.0, (hi - lo * 1.5)), 0, 1).astype(np.float32)
    m[~cv2.dilate(hard.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = 0
    return m
