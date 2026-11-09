"""AI 去字（LaMa 修补模型）：把要擦掉的文字区域按周围的花纹、渐变、纹理补出来。

比 OpenCV 自带的修补好得多：深色花纹标题框、渐变底、纹理底上擦字都看不出痕迹。
模型第一次用时下载（和照片识别模型一起），没有模型时退回到 OpenCV 修补。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SIZE = 512


MODEL_SHA256 = "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6"
MODEL_SIZE = 208044816


def model_url() -> str:
    from . import REPO
    return f"https://github.com/{REPO}/releases/download/models-v1/lama.onnx"


def downloaded_path() -> Path:
    from .config import data_dir
    return data_dir() / "models" / "lama.onnx"


def inpaint_model_path() -> Path:
    from .config import data_dir, resource_dir
    p = resource_dir() / "models" / "lama.onnx"
    return p if p.exists() else data_dir() / "models" / "lama.onnx"


class Inpainter:
    def __init__(self, path: Path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])

    def _run(self, crop: np.ndarray, m: np.ndarray) -> np.ndarray:
        import cv2
        ch, cw = crop.shape[:2]
        x = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        mm = (cv2.resize(m, (SIZE, SIZE), interpolation=cv2.INTER_NEAREST) > 0).astype(np.float32)
        out = self.sess.run(None, {"image": x.transpose(2, 0, 1)[None], "mask": mm[None, None]})[0][0]
        out = out.transpose(1, 2, 0)
        if out.max() <= 1.5:
            out = out * 255.0
        return cv2.resize(np.clip(out, 0, 255).astype(np.uint8), (cw, ch), interpolation=cv2.INTER_CUBIC)

    def inpaint(self, rgb: np.ndarray, mask: np.ndarray, progress=None) -> np.ndarray:
        """mask > 0 的地方补出来。离得近的几块字合成一组一起补（上下文更完整，也更快）。"""
        import cv2
        H, W = rgb.shape[:2]
        if not mask.any():
            return rgb
        res = rgb.copy()
        grow = max(8, int(min(H, W) * 0.03))
        groups = cv2.dilate((mask > 0).astype(np.uint8), np.ones((grow, grow), np.uint8))
        n, lbl, st, _ = cv2.connectedComponentsWithStats(groups, 8)
        for i in range(1, n):
            x, y, w, h, _a = st[i]
            sub = (lbl[y:y + h, x:x + w] == i) & (mask[y:y + h, x:x + w] > 0)
            if not sub.any():
                continue
            # 周围留一圈上下文；正方形裁切，避免缩放到 512 时被压扁
            side = int(max(w, h) * 1.5) + 32
            cx, cy = x + w / 2, y + h / 2
            X0 = int(max(0, min(W - side, cx - side / 2))) if side < W else 0
            Y0 = int(max(0, min(H - side, cy - side / 2))) if side < H else 0
            X1, Y1 = min(W, X0 + side), min(H, Y0 + side)
            m = np.zeros((Y1 - Y0, X1 - X0), np.uint8)
            m[y - Y0:y - Y0 + h, x - X0:x - X0 + w][sub] = 255
            crop = res[Y0:Y1, X0:X1]
            out = self._run(crop, m)
            a = cv2.GaussianBlur((m > 0).astype(np.float32), (5, 5), 0)[..., None]
            res[Y0:Y1, X0:X1] = (crop * (1 - a) + out * a).astype(np.uint8)
            if progress:
                progress(i, n - 1)
        return res
