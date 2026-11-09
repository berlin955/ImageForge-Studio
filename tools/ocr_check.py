"""诊断文字识别是否可用。"""
import sys
import traceback

import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    img = np.full((200, 600, 3), 30, np.uint8)
    import cv2
    cv2.putText(img, "6757 WHITE", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 255, 255), 6)
    res, el = eng(img)
    print("OCR RESULT:", res)
except Exception:
    traceback.print_exc()
    sys.exit(1)
