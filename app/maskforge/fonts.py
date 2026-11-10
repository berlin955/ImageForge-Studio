"""字体：内置的免费字体包 + 「原图这行字像哪种字体」自动匹配。

字体包（思源宋体 / 思源黑体各种粗细、阿里巴巴普惠体、阿里妈妈字体，都是免费商用）第一次用智能规格时下载，
放在数据目录的 fonts 文件夹里，启动时注册给 Qt。

自动匹配（不需要 Qt，可以在后台线程跑）：
  把原图这行字的笔画抠出来（原图减去 AI 擦干净的底），用每个候选字体把同样的字画一遍，
  缩放到同样大小后比较笔画重合度和笔画粗细，挑最像的那个；同时算出字号、字间距和基线位置，
  这样改字以后新字刚好落在原来的位置、大小和粗细都对得上。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

# 字体包（models-v1/fonts.zip）。重新生成字体包后改这两个数
PACK_SHA256 = "efd34d8a80f5cc40cdb30c483cff636b81b45ad40c419330ee154e4df74a4f43"
PACK_SIZE = 56083407

# 文件名 → （显示名、类别）。类别：serif 宋体类，sans 黑体类，art 书法 / 艺术字
GROUPS = [
    ("SourceHanSerif", "思源宋体", "serif"),
    ("SourceHanSans", "思源黑体", "sans"),
    ("AlibabaPuHuiTi", "阿里巴巴普惠体", "sans"),
    ("AlimamaShuHeiTi", "阿里妈妈数黑体", "sans"),
    ("AlimamaFangYuanTi", "阿里妈妈方圆体", "sans"),
    ("AlimamaAgile", "阿里妈妈灵动体", "art"),
    ("AlimamaDongFangDaKai", "阿里妈妈东方大楷", "art"),
    ("AlimamaDaoLiTi", "阿里妈妈刀隶体", "art"),
]
CAT_NAMES = {"serif": "宋体类", "sans": "黑体类", "art": "书法 / 艺术字", "sys": "电脑自带"}

WEIGHT_WORDS = [
    ("extralight", 200), ("ultralight", 200), ("thin", 100), ("light", 300), ("normal", 350),
    ("regular", 400), ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800),
    ("ultrabold", 800), ("bold", 700), ("heavy", 900), ("black", 900),
]
WEIGHT_NAMES = {100: "极细", 200: "特细", 300: "细体", 350: "标准", 400: "常规", 500: "中等", 600: "半粗",
                700: "粗体", 800: "特粗", 900: "超粗"}

# 字体包没下载时的退路：电脑自带字体
SYSTEM_FALLBACK = {"serif": ["SimSun", "宋体", "NSimSun"], "sans": ["Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑"],
                   "art": ["KaiTi", "楷体", "STKaiti"]}
SYSTEM_GROUPS = [("sys:Microsoft YaHei", "微软雅黑", "sans"), ("sys:SimSun", "宋体", "serif"),
                 ("sys:SimHei", "黑体", "sans"), ("sys:KaiTi", "楷体", "art"), ("sys:FangSong", "仿宋", "serif")]


def pack_url() -> str:
    from . import REPO
    return f"https://github.com/{REPO}/releases/download/models-v1/fonts.zip"


def fonts_dir() -> Path:
    from .config import data_dir
    return data_dir() / "fonts"


def _bundled_dir() -> Path:
    from .config import resource_dir
    return resource_dir() / "fonts"


def font_files() -> list[Path]:
    out = []
    for d in (_bundled_dir(), fonts_dir()):
        try:
            if d.exists():
                out += sorted(p for p in d.iterdir() if p.suffix.lower() in (".otf", ".ttf"))
        except Exception:
            pass
    seen, res = set(), []
    for p in out:
        if p.stem.lower() not in seen:
            seen.add(p.stem.lower())
            res.append(p)
    return res


def has_pack() -> bool:
    return any(_group_of(p.stem)[0] for p in font_files())


def install_pack(zip_path: str) -> int:
    import zipfile
    d = fonts_dir()
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            base = Path(name).name
            if base and Path(base).suffix.lower() in (".otf", ".ttf"):
                (d / base).write_bytes(z.read(name))
                n += 1
    return n


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _group_of(stem: str):
    n = _norm(stem)
    for key, name, cat in GROUPS:
        if n.startswith(_norm(key)):
            return key, name, cat
    return None, None, None


def weight_of(stem: str) -> int:
    n = _norm(stem.split("-", 1)[-1] if "-" in stem else stem)
    # 阿里巴巴普惠体 3.0 用数字表示粗细：35 / 45 / 55 / 65 / 75 / 85 / 95 / 105 / 115
    m = re.search(r"(?:^|-)(\d{2,3})(?:-|$)", stem)
    for word, w in WEIGHT_WORDS:
        if word in n:
            return w
    if m:
        v = int(m.group(1))
        table = {35: 300, 45: 400, 55: 400, 65: 500, 75: 600, 85: 700, 95: 800, 105: 900, 115: 900}
        if v in table:
            return table[v]
    return 400


def catalog() -> list[dict]:
    """字体包里的所有字体：[{stem, path, group, name, cat, weight}]"""
    res = []
    for p in font_files():
        key, name, cat = _group_of(p.stem)
        if not key:
            key, name, cat = p.stem.split("-")[0], p.stem.split("-")[0], "sans"
        res.append({"stem": p.stem, "path": str(p), "group": key, "name": name, "cat": cat,
                    "weight": weight_of(p.stem)})
    return res


def group_list() -> list[dict]:
    """按字体家族汇总：[{key, name, cat, weights: {400: stem, 700: stem}}]，宋体类在前。"""
    order = {k: i for i, (k, _, _) in enumerate(GROUPS)}
    g: dict[str, dict] = {}
    for f in catalog():
        e = g.setdefault(f["group"], {"key": f["group"], "name": f["name"], "cat": f["cat"], "weights": {}})
        # 同一个粗细有好几个文件时（例如 45 Light 和 55 Regular 都算常规），留第一个
        e["weights"].setdefault(f["weight"], f["stem"])
    return sorted(g.values(), key=lambda e: (order.get(e["key"], 99), e["name"]))


def stem_info(stem: str | None) -> dict | None:
    if not stem:
        return None
    for f in catalog():
        if f["stem"] == stem:
            return f
    return None


# ================================================================ Qt 部分
_registered: dict[str, str] = {}      # stem -> Qt 里的字体名
_reg_done = False


def register_all() -> int:
    """把字体包注册给 Qt（启动时、下载完字体包后各调一次）。"""
    global _reg_done
    from PySide6.QtGui import QFontDatabase
    n = 0
    for p in font_files():
        if p.stem in _registered:
            continue
        fid = QFontDatabase.addApplicationFont(str(p))
        if fid < 0:
            continue
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            _registered[p.stem] = fams[0]
            n += 1
    _reg_done = True
    return n


def qfont(stem: str | None, weight: int | None = None, cat: str | None = None):
    """字体包里的某个字体（按文件名找）；没有字体包时退回电脑自带的同类字体。"""
    from PySide6.QtGui import QFont, QFontDatabase
    if not _reg_done:
        register_all()
    if stem and stem.startswith("sys:"):
        f = QFont(stem[4:])
        f.setWeight(QFont.Weight(int(weight or 400)))
        return f
    fam = _registered.get(stem or "")
    if fam:
        f = QFont(fam)
        info = stem_info(stem)
        w = int(weight or (info["weight"] if info else 400))
        f.setWeight(QFont.Weight(w))
        # 同一个家族名下有多种粗细时，按样式名精确挑中这个文件
        style = stem.split("-")[-1] if "-" in stem else ""
        styles = QFontDatabase.styles(fam)
        for s in styles:
            if _norm(s) == _norm(style):
                f.setStyleName(s)
                break
        return f
    info = stem_info(stem)
    c = cat or (info["cat"] if info else None) or _group_of(stem or "")[2] or "sans"
    have = set(QFontDatabase.families())
    fam = next((x for x in SYSTEM_FALLBACK.get(c, []) if x in have), "Microsoft YaHei UI")
    f = QFont(fam)
    w = int(weight or (info["weight"] if info else weight_of(stem or "")))
    f.setWeight(QFont.Weight.Bold if w >= 600 else QFont.Weight.Normal)
    return f


def system_groups() -> list[dict]:
    from PySide6.QtGui import QFontDatabase
    have = set(QFontDatabase.families())
    res = []
    for key, name, cat in SYSTEM_GROUPS:
        fam = key[4:]
        if fam in have or name in have:
            res.append({"key": key if fam in have else "sys:" + name, "name": name, "cat": "sys",
                        "weights": {400: key if fam in have else "sys:" + name}, "system": True})
    return res


# ================================================================ 自动匹配（不用 Qt）
def ink_alpha(orig: np.ndarray, clean: np.ndarray | None) -> np.ndarray:
    """原图这块里每个像素「有多像字」（0 = 底，1 = 笔画中心），边缘的抗锯齿是中间值。
    和擦干净的底比；没有干净底时和四周的底色比。"""
    o = orig.astype(np.int32)
    if clean is not None and clean.shape == orig.shape:
        d = np.abs(o - clean.astype(np.int32)).sum(2)
    else:
        ring = np.concatenate([o[0], o[-1], o[:, 0], o[:, -1]])
        d = np.abs(o - np.median(ring, axis=0)).sum(2)
    if d.max() < 40:
        return np.zeros(d.shape, np.float32)
    import cv2
    d8 = np.clip(d / max(1, d.max()) * 255, 0, 255).astype(np.uint8)
    thr, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    rough = d8 > max(thr, 40)
    if not rough.any():
        return np.zeros(d.shape, np.float32)
    full = max(80.0, float(np.percentile(d8[rough], 85)))
    a = np.clip(d8.astype(np.float32) / full, 0, 1)
    a[d8 < 20] = 0
    return a


def ink_mask(orig: np.ndarray, clean: np.ndarray | None) -> np.ndarray:
    """笔画蒙版：按「笔画颜色和底色正中间」来切（边缘那圈过渡色只算一半），笔画粗细才准。"""
    return ink_alpha(orig, clean) > 0.5


def ink_color(orig: np.ndarray, clean: np.ndarray | None, m: np.ndarray) -> str | None:
    """字的颜色：取笔画中心（和底色差得最多的那一半像素），不取边缘那圈和底色混在一起的。"""
    import cv2
    if not m.any():
        return None
    o = orig.astype(np.int32)
    core = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if core.sum() < 8:
        core = m
    if clean is not None and clean.shape == orig.shape:
        d = np.abs(o - clean.astype(np.int32)).sum(2)
    else:
        ring = np.concatenate([o[0], o[-1], o[:, 0], o[:, -1]])
        d = np.abs(o - np.median(ring, axis=0)).sum(2)
    v = d[core]
    sel = core & (d >= np.percentile(v, 50))
    c = np.median(o[sel], axis=0)
    return "#%02x%02x%02x" % tuple(int(x) for x in c[:3])


def _bbox(m: np.ndarray):
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _main_band(m: np.ndarray) -> np.ndarray:
    """只留这一行字所在的那条横带：框边上蹭进来的照片边、花纹不算。"""
    rows = m.mean(1)
    if rows.max() <= 0:
        return m
    on = rows >= rows.max() * 0.12
    best, cur, start = (0, 0, 0), 0, 0
    for i, v in enumerate(list(on) + [False]):
        if v:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best[0]:
                best = (cur, start, i)
            cur = 0
    _, a, b = best
    ext = max(1, int((b - a) * 0.12))
    out = np.zeros_like(m)
    out[max(0, a - ext):b + ext] = m[max(0, a - ext):b + ext]
    return out


def _rows_near(m: np.ndarray) -> np.ndarray:
    rows = m.any(1)
    if not rows.any():
        return rows[:, None]
    ys = np.nonzero(rows)[0]
    out = np.zeros_like(rows)
    out[max(0, ys[0] - 2):ys[-1] + 3] = True
    return out[:, None]


def _stroke_stats(m: np.ndarray) -> tuple[float, float]:
    """(笔画粗细, 粗细对比度)。宋体横细竖粗，对比度低；黑体横竖一样粗，对比度接近 1。"""
    import cv2
    if not m.any():
        return 0.0, 1.0
    dt = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
    ridge = (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8))) & (dt > 0.5)
    v = dt[ridge]
    if v.size < 10:
        return float(dt.max()) * 2, 1.0
    lo, hi = np.percentile(v, 25), np.percentile(v, 85)
    return float(hi) * 2, float(lo / max(1e-3, hi))


def _stroke(m: np.ndarray) -> float:
    """平均笔画粗细（像素）：用距离变换在笔画中心线上的值估计。"""
    import cv2
    if not m.any():
        return 0.0
    dt = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
    v = dt[dt >= np.percentile(dt[m], 70)]
    return float(np.median(v)) * 2 if v.size else 0.0


def _render(path: str, text: str, size: int):
    """用 PIL 把字画出来；返回 (笔画蒙版, 基线 y, 起点 x)。"""
    from PIL import Image, ImageDraw, ImageFont
    font = _pil_font(path, size)
    pad = size
    w = int(font.getlength(text) + pad * 2 + size)
    h = size * 3
    img = Image.new("L", (max(8, w), h), 0)
    ImageDraw.Draw(img).text((pad, size * 2), text, font=font, fill=255, anchor="ls")
    return np.asarray(img) > 127, size * 2, pad


_pil_cache: dict = {}


def _pil_font(path: str, size: int):
    from PIL import ImageFont
    k = (path, size)
    if k not in _pil_cache:
        if len(_pil_cache) > 200:
            _pil_cache.clear()
        _pil_cache[k] = ImageFont.truetype(path, size)
    return _pil_cache[k]


def _downscale(m: np.ndarray, k: float) -> np.ndarray:
    """把渲染出来的字缩到原图的大小（笔画粗细要在同样的像素尺度下比较）。"""
    import cv2
    h, w = m.shape
    nh, nw = max(1, int(round(h * k))), max(1, int(round(w * k)))
    return cv2.resize(m.astype(np.uint8) * 255, (nw, nh), interpolation=cv2.INTER_AREA) > 127


def _blur(m: np.ndarray, s: float) -> np.ndarray:
    import cv2
    k = max(3, int(s * 3) | 1)
    return cv2.GaussianBlur(m.astype(np.float32), (k, k), s)


def _char_corr(om, ob, rm, path, text, rs, pad, rx0, ry0, ry1, k, spacing, sig):
    """逐个字对齐后比较（原图字距常常不均匀，整行一起拉伸会错位，错位时粗字体反而占便宜）。
    从左到右一个字一个字找：每个字在上一个字后面一小段范围里找最贴合的位置，这样中间空了一大格
    （识别时漏掉的空格）也跟得上。返回 (按笔画多少加权的平均相似度, 每个字在原图里的左边位置)。"""
    import cv2
    font = _pil_font(path, rs)
    ih, iw = om.shape
    xs = 0.0
    tot, wsum = 0.0, 0.0
    cursor = 0.0                      # 上一个字在原图里的右边（含字体留的空）
    ink_end = 0                       # 上一个字的笔画在原图里结束的位置
    colink = om.any(0)
    placed = []                       # (第几个字, 原图里的左边, 字宽, 按字体本来该在的左边)
    for i, ch in enumerate(text):
        adv = font.getlength(ch)
        a, b = int(pad + xs), int(np.ceil(pad + xs + adv))
        xs += adv
        if ch.isspace() or b <= a:
            cursor += adv * k
            continue
        cell = rm[ry0:ry1, a:b]
        if not cell.any():
            continue
        cols = np.nonzero(cell.any(0))[0]
        c0, c1 = a + cols[0], a + cols[-1] + 1
        glyph = rm[ry0:ry1, c0:c1].astype(np.float32)
        gw, gh = max(1, int(round((c1 - c0) * k))), ih
        if gw >= iw:
            continue
        g = _blur(cv2.resize(glyph, (gw, gh), interpolation=cv2.INTER_AREA), sig)
        if g.sum() < 1:
            continue
        lead = (c0 - a) * k                # 字左边本来就留的空
        # 只跳过原图里真正空白的地方：从上一个字的笔画结束处往后找到下一处有笔画的列，
        # 这个字的笔画就从那里开始（模板已经裁到笔画左边，不用管字体里字左右留的空，
        # 「：」「，」这种留空很多的标点也不会把后面的字带偏）
        nxt = int(min(iw - 1, max(0, ink_end)))
        while nxt < iw - 1 and not colink[nxt]:
            nxt += 1
        # 上一个字估得偏窄时 nxt 会落在它自己的笔画里：往右多给半个字的余量
        if placed:
            lo = int(max(0, ink_end - ih * 0.15))
            hi = int(min(iw, max(nxt, ink_end + ih * 0.5) + gw + ih * 0.15))
        else:
            # 第一个字：行首可能有识别时漏掉的装饰（「·」「|」），在前面一段里自由找
            lo, hi = 0, int(min(iw, ih * 1.2 + gw))
        if hi - lo < gw:
            break
        res = cv2.matchTemplate(ob[:, lo:hi].astype(np.float32), g.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        # 离预计位置（下一处笔画开始的地方）越远越扣分：「：」这种只有两个点的小字
        # 很容易在后面那个字的笔画里找到更「像」的地方
        r1 = res[0]
        pos = lo + np.arange(len(r1))
        j = int(np.argmax(r1 - (0.5 * np.abs(pos - nxt) / ih if placed else 0)))
        best = float(r1[j])
        wgt = float(g.sum())
        tot += best * wgt
        wsum += wgt
        x_at = lo + j
        placed.append((i, x_at, gw, lead, (b - c1) * k))
        cursor = x_at + gw + (b - c1) * k
        ink_end = x_at + gw
    # 没对上的字（原图里放不下了）按 0 分算，防止只对上前几个字的字体占便宜
    missing = sum(1 for ch in text if not ch.isspace()) - len(placed)
    if missing > 0 and wsum > 0:
        wsum += wsum / max(1, len(placed)) * missing
    return (tot / wsum if wsum > 0 else 0.0), placed


def _gaps(placed, k_size):
    """相邻两个字之间比字体本来的间隔多出来多少（像素）。"""
    out = []
    for (i1, x1, w1, l1, r1), (i2, x2, w2, l2, r2) in zip(placed, placed[1:]):
        if i2 == i1 + 1:
            out.append((i2, (x2 - l2) - (x1 + w1 + r1)))
    return out


def match_font(orig: np.ndarray, clean: np.ndarray | None, text: str, cands: list[dict] | None = None) -> dict | None:
    """原图这一块（只含这行字）最像哪个字体。返回 {font, size, spacing, bl:(x, 基线 y), score}；
    坐标相对这一块的左上角。认不出（字太小、抠不出笔画）时返回 None。"""
    import cv2
    text = (text or "").strip()
    if not text:
        return None
    alpha = ink_alpha(orig, clean)
    m = _main_band(alpha > 0.5)
    alpha = np.where(m.any(1)[:, None] | _rows_near(m), alpha, 0)
    bb = _bbox(m)
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    ih, iw = y1 - y0, x1 - x0
    if ih < 6 or iw < 4:
        return None
    om = m[y0:y1, x0:x1]
    oa = alpha[y0:y1, x0:x1]
    # 笔画粗细放大到每个字约 96 像素高再量（小字的笔画只有 1、2 个像素，直接量分不出粗细）
    U = int(np.clip(round(96 / ih), 1, 6))
    up = cv2.resize(oa, (iw * U, ih * U), interpolation=cv2.INTER_CUBIC) > 0.5
    o_th, o_ct = _stroke_stats(up)
    o_stroke = o_th / (ih * U)
    cands = cands if cands is not None else catalog()
    if not cands:
        return None
    n = len(text)
    rs = int(min(220, max(40, ih * U * 1.2)))
    best = None
    allsc: dict = {}
    sig = max(0.6, ih / 40)
    ob = _blur(oa, sig)
    for c in cands:
        try:
            rm, base, pad = _render(c["path"], text, rs)
        except Exception:
            continue
        rb = _bbox(rm)
        if rb is None:
            continue
        rx0, ry0, rx1, ry1 = rb
        rh, rw = ry1 - ry0, rx1 - rx0
        k = ih / max(1, rh)                       # 渲染字号 → 原图的缩放
        size = rs * k
        # 字间距：原图墨迹宽度和按这个字号画出来的宽度差多少，平均分到每个字之间
        spacing = (iw - rw * k) / max(1, n - 1) if n > 1 else 0.0
        if spacing > size * 0.8 or spacing < -size * 0.25:
            continue                              # 圆形徽章、弯曲排列的字：不是一行普通的字
        corr, placed = _char_corr(om, ob, rm, c["path"], text, rs, pad, rx0, ry0, ry1, k, spacing, sig)
        gaps = _gaps(placed, size)
        space_at = []
        if len(gaps) >= 2:
            # 字距用中位数（不被一个大空格带偏）；比中位数宽出半个字以上的地方，原图多半有个空格
            med = float(np.median([g for _, g in gaps]))
            if -size * 0.25 < med < size * 0.8:
                spacing = med
            colink = om.any(0)
            pos = {p[0]: p for p in placed}
            for i, g in gaps:
                if g - med <= size * 0.5 or text[i - 1].isspace() or text[i].isspace():
                    continue
                a = pos[i - 1]
                gx0, gx1 = int(a[1] + a[2]), int(pos[i][1])
                # 两个字之间那段原图必须真的是空的
                if gx1 - gx0 > size * 0.45 and not colink[gx0 + 1:gx1 - 1].any():
                    space_at.append(i)
        r_th, r_ct = _stroke_stats(rm[ry0:ry1, rx0:rx1])
        r_stroke = r_th / max(1, rh)
        sw = abs(r_stroke - o_stroke) / max(0.02, o_stroke)
        # 字太小时对比度量不准，权重跟着字高减小
        ct_w = 0.6 * min(1.0, max(0.0, (ih - 8) / 16))
        score = corr - 0.35 * min(1.0, sw) - ct_w * abs(r_ct - o_ct) - (0.04 if c.get("cat") == "art" else 0.0) \
            - 0.02 * min(4.0, abs(spacing) / max(1.0, size * 0.1))
        allsc[c["stem"]] = (score, size, spacing, (x0 - (rx0 - pad) * k, y0 + (base - ry0) * k), space_at)
        if best is None or score > best["score"]:
            # 基线和起点：渲染图里墨迹到基线 / 起点的距离，按比例换到原图
            bl_y = y0 + (base - ry0) * k
            bl_x = x0 - (rx0 - pad) * k
            best = {"font": c["stem"], "cat": c.get("cat"), "weight": c.get("weight", 400),
                    "size": round(size, 2), "spacing": round(spacing, 2),
                    "bl": (round(bl_x, 2), round(bl_y, 2)), "score": round(score, 4), "corr": round(corr, 4),
                    "space_at": space_at}
    if best is not None:
        best["all"] = allsc
        best["color"] = ink_color(orig, clean, m)
        best["ink_h"] = ih
    return best


def _from_all(r: dict, stem: str, cands: list[dict]) -> dict:
    """同一行字换成另一个候选字体时的字号、字距、基线。"""
    sc, size, spacing, bl, space_at = r["all"][stem]
    c = next(c for c in cands if c["stem"] == stem)
    out = dict(r)
    out.update({"font": stem, "cat": c.get("cat"), "weight": c.get("weight", 400), "size": round(size, 2),
                "spacing": round(spacing, 2), "bl": (round(bl[0], 2), round(bl[1], 2)), "score": round(sc, 4),
                "space_at": space_at})
    return out


def match_texts(orig_rgb: np.ndarray, clean_rgb: np.ndarray | None, texts: list[dict], progress=None) -> int:
    """给模板里每段识别出来的字配上最像的字体（原样不动的字保持原图像素，配好的字体只在改字后用到）。"""
    cands = catalog()
    if not cands:
        return 0
    H, W = orig_rgb.shape[:2]
    done = 0
    found = []
    weak = []
    for i, t in enumerate(texts):
        if "patch" not in t:
            continue
        x1, y1, x2, y2 = (int(v) for v in t["patch"])
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        o = orig_rgb[y1:y2, x1:x2]
        c = clean_rgb[y1:y2, x1:x2] if clean_rgb is not None else None
        try:
            r = match_font(o, c, t.get("text", ""), cands)
        except Exception:
            r = None
        if progress:
            progress(i + 1, len(texts))
        if not r or r["score"] < 0.3:
            weak.append(t)                       # 字被框切掉一截、花体字…认不准，等会跟着最像的那行走
            continue
        found.append((t, r, x1, y1))
    # 一张图里颜色一样、大小差不多的几行字，几乎都是同一个字体：一起投票选，
    # 比每行各选各的稳（短短几个字的那行单独选很容易选歪）
    groups: list[list] = []
    for item in found:
        t, r = item[0], item[1]
        col = _hex(t.get("color", "#000000"))
        for g in groups:
            t2, r2 = g[0][0], g[0][1]
            if np.abs(col - _hex(t2.get("color", "#000000"))).sum() < 90 and \
                    0.8 < r["ink_h"] / max(1, r2["ink_h"]) < 1.25:
                g.append(item)
                break
        else:
            groups.append([item])
    for g in groups:
        if len(g) > 1:
            common = set.intersection(*(set(it[1]["all"]) for it in g))
            if common:
                # 按每行字的长度加权（字多的那行更可信）
                def total(stem):
                    return sum(it[1]["all"][stem][0] * min(12, len(it[0].get("text", ""))) for it in g)
                stem = max(common, key=total)
                for it in g:
                    own = it[1]
                    # 某一行自己特别确定是别的字体（分差很大）时，尊重它自己的
                    if own["score"] - own["all"][stem][0] < 0.08:
                        it[1].update(_from_all(own, stem, cands))
        for t, r, x1, y1 in g:
            apply_match(t, r, x1, y1)
            done += 1
    # 认不准的那几行：用颜色最接近、大小最接近的那行的字体（只换字体，字号、位置不动）
    for t in weak:
        if not found:
            break
        col = _hex(t.get("color", "#000000"))
        h = float(t.get("h", 1))
        ref = min(found, key=lambda it: np.abs(col - _hex(it[0].get("color", "#000000"))).sum() / 255
                  + abs(np.log(max(1.0, it[1]["ink_h"]) / max(1.0, h * 0.8))))
        rt = ref[0]
        o = t.get("orig")
        vals = {"font": rt["font"], "weight": rt.get("weight", 400), "cat": rt.get("cat")}
        t.update(vals)
        t["font_auto"] = rt["font"]
        if o is not None:
            o.update(vals)
        done += 1
    return done


def _hex(c: str) -> np.ndarray:
    c = (c or "#000000").lstrip("#")
    try:
        return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.int32)
    except Exception:
        return np.zeros(3, np.int32)


def apply_match(t: dict, r: dict, ox: float, oy: float):
    """把匹配结果写进文字图层，原图记录（orig）也一起写，这样没改过的字仍然算「没改」。"""
    o = t.get("orig")
    unchanged_size = o is None or abs(float(t.get("size", 0)) - float(o.get("size", 0))) < 0.5
    unchanged_color = o is None or t.get("color") == o.get("color")
    vals = {"font": r["font"], "weight": r["weight"], "spacing": r["spacing"], "cat": r.get("cat"),
            "bl": [round(ox + r["bl"][0] - t["x"], 2), round(oy + r["bl"][1] - t["y"], 2)]}
    if unchanged_size:
        vals["size"] = r["size"]
    if unchanged_color and r.get("color"):
        vals["color"] = r["color"]
    # 识别时漏掉的空格补回来（只在字没被改过时补，原图记录一起补）
    sp = r.get("space_at") or []
    if sp and (o is None or t.get("text") == o.get("text")):
        txt = t.get("text", "")
        for i in sorted(sp, reverse=True):
            if 0 < i < len(txt):
                txt = txt[:i] + " " + txt[i:]
        vals["text"] = txt
    t.update(vals)
    t["font_auto"] = r["font"]
    t["bl_orig"] = list(vals["bl"])
    if o is not None:
        for k in ("font", "weight", "spacing", "size", "color", "text"):
            if k in vals:
                o[k] = vals[k]
