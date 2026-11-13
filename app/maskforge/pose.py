"""人体姿态（17 个关键点），用来判断模特是正面还是背面。

原理：姿态模型会分出「左肩 / 右肩、左髋 / 右髋」（按人自己的左右）。
正面拍时，人的左肩在画面右边；背面拍时，人的左肩在画面左边。再结合脸是否看得见、
打码模型认出的部位（臀部 → 背面；胸、腹 → 正面），综合打分。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = range(13)


def pose_model_path() -> Path:
    from .config import resource_dir
    return resource_dir() / "models" / "pose.onnx"


class PoseEstimator:
    def __init__(self, path: Path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.name = inp.name
        shp = inp.shape
        self.size = int(shp[2]) if isinstance(shp[2], int) else 640

    def keypoints(self, rgb: np.ndarray) -> np.ndarray | None:
        """返回画面里最主要那个人的关键点 (17, 3)：x, y, 置信度（原图坐标）。没有人时返回 None。"""
        import cv2
        S = self.size
        h, w = rgb.shape[:2]
        k = S / max(w, h)
        nw, nh = max(1, round(w * k)), max(1, round(h * k))
        canvas = np.full((S, S, 3), 114, np.uint8)
        px, py = (S - nw) // 2, (S - nh) // 2
        canvas[py:py + nh, px:px + nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        x = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.sess.run(None, {self.name: x})[0][0]          # (56, N)
        if out.shape[0] != 56:
            out = out.T
        conf = out[4]
        i = int(conf.argmax())
        if conf[i] < 0.25:
            return None
        # 同样可信的人里挑最大的那个
        cand = np.where(conf >= max(0.25, conf[i] * 0.6))[0]
        areas = out[2, cand] * out[3, cand]
        i = int(cand[areas.argmax()])
        kp = out[5:, i].reshape(17, 3).copy()
        kp[:, 0] = (kp[:, 0] - px) / k
        kp[:, 1] = (kp[:, 1] - py) / k
        return kp


def facing_score(kp: np.ndarray | None, labels=(), width: float = 1.0) -> float:
    """> 0 偏正面，< 0 偏背面，绝对值越大越确定。"""
    s = 0.0
    labels = set(labels or ())
    if kp is not None:
        c = kp[:, 2]

        def pair(a, b, wgt):
            nonlocal s
            if c[a] > 0.4 and c[b] > 0.4:
                dx = kp[a, 0] - kp[b, 0]                # 人的左边减右边：正面时为正
                # 左右分得越开越可信；侧身时两点几乎重合，说明不了什么
                strength = min(1.0, abs(dx) / max(1.0, width * 0.22))
                s += wgt * strength * (1 if dx > 0 else -1)

        pair(L_SH, R_SH, 1.2)
        pair(L_HIP, R_HIP, 1.0)
        face = [c[NOSE], c[L_EYE], c[R_EYE]]
        if min(face) > 0.55:
            s += 0.8                                     # 正脸
        elif max(face) < 0.25 and max(c[L_EAR], c[R_EAR]) > 0.5:
            s -= 0.5                                     # 只看得到耳朵、看不到脸：多半是背面
    if labels & {"BUTTOCKS_EXPOSED", "BUTTOCKS_COVERED", "ANUS_EXPOSED", "ANUS_COVERED"}:
        s -= 1.3
    if labels & {"FEMALE_BREAST_EXPOSED", "FEMALE_BREAST_COVERED", "BELLY_EXPOSED", "BELLY_COVERED",
                 "FEMALE_GENITALIA_COVERED", "FEMALE_GENITALIA_EXPOSED"}:
        s += 0.9
    if labels & {"FACE_FEMALE", "FACE_MALE"}:
        s += 0.4
    return s


def facing_of(score: float) -> str | None:
    if score >= 0.35:
        return "front"
    if score <= -0.35:
        return "back"
    return None


def crack_tilt(kp: np.ndarray | None, width: float = 1.0) -> float | None:
    """股沟的倾斜角度（度，顺时针为正，和码的「旋转」一样）。模特侧着身、歪着胯时，
    股沟和两边髋部的连线垂直：码跟着转这个角度就顺着股沟。看不清、或者和脊柱方向对不上时返回 None。"""
    if kp is None:
        return None
    c = kp[:, 2]
    if c[L_HIP] < 0.5 or c[R_HIP] < 0.5:
        return None
    a, b = kp[L_HIP, :2], kp[R_HIP, :2]
    if a[0] > b[0]:
        a, b = b, a
    dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
    if abs(dx) < width * 0.05:
        return None                              # 侧身太厉害，两边髋部叠在一起
    hip = float(np.degrees(np.arctan2(dy, dx)))
    if c[L_SH] > 0.5 and c[R_SH] > 0.5:
        # 脊柱方向（肩膀中点 → 髋部中点）做个核对：差得太多说明姿势很扭，不自动转
        sm = (kp[L_SH, :2] + kp[R_SH, :2]) / 2
        hm = (kp[L_HIP, :2] + kp[R_HIP, :2]) / 2
        vx, vy = float(hm[0] - sm[0]), float(hm[1] - sm[1])
        if vy > 0:
            spine = float(np.degrees(np.arctan2(-vx, vy)))
            if abs(spine - hip) > 25:
                return None
    if abs(hip) < 4:
        return 0.0
    return max(-35.0, min(35.0, hip))
