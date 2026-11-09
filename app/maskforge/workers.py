"""后台任务：识别、缩略图。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThread, Signal
from PySide6.QtGui import QImage, QImageReader


class DetectWorker(QThread):
    progress = Signal(int, int, str)
    result = Signal(str, int, int, object)   # doc_id, w, h, detections
    failed = Signal(str, str)                # doc_id, message
    fatal = Signal(str)
    facing = Signal(str, float)              # doc_id, 正面 / 背面打分

    def __init__(self, items: list[tuple[str, str, str]], threshold: float, get_detector, parent=None):
        super().__init__(parent)
        self.items = items              # (doc_id, path, name)
        self.threshold = threshold
        self.get_detector = get_detector
        self.get_pose = None                 # 可选：姿态模型，用来判断正面 / 背面
        self.pose_error = ""

    def run(self):
        n = len(self.items)
        try:
            det = self.get_detector()
        except Exception as e:  # 模型缺失或运行库异常
            self.fatal.emit(str(e))
            return
        from .model import load_qimage
        for i, (did, path, name) in enumerate(self.items):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, n, name)
            img = load_qimage(path)
            if img is None:
                self.failed.emit(did, "无法读取图片")
                continue
            try:
                dets = det.detect(img, self.threshold)
            except Exception as e:
                self.failed.emit(did, f"识别出错：{e}")
                continue
            self.result.emit(did, img.width(), img.height(), dets)
            if self.get_pose:
                from .pose import facing_score
                labels = [x["label"] for x in dets]
                sc = facing_score(None, labels)
                try:
                    pose = self.get_pose()
                    if pose is not None:
                        from .detector import qimage_to_rgb
                        small = img if max(img.width(), img.height()) <= 1280 else img.scaled(
                            1280, 1280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        kp = pose.keypoints(qimage_to_rgb(small))
                        sc = facing_score(kp, labels, float(small.width()))
                except Exception as e:
                    self.pose_error = str(e)
                self.facing.emit(did, float(sc))   # 姿态模型出问题也照样给结果（只按部位判断），不会卡住
        self.progress.emit(n, n, "")


class _ThumbSignals(QObject):
    done = Signal(str, QImage, int, int)


class ThumbTask(QRunnable):
    def __init__(self, doc_id: str, path: str, size: int = 200):
        super().__init__()
        self.doc_id, self.path, self.size = doc_id, path, size
        self.signals = _ThumbSignals()

    def run(self):
        r = QImageReader(self.path)
        r.setAutoTransform(True)
        img = r.read()
        if img.isNull():
            self.signals.done.emit(self.doc_id, QImage(), 0, 0)
            return
        w, h = img.width(), img.height()
        t = img.scaled(QSize(self.size, self.size), Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        self.signals.done.emit(self.doc_id, t, w, h)
