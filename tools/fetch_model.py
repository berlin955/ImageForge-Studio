"""从 nudenet 包里取出 320n.onnx 识别模型，放到 models/。"""
import importlib.util
import shutil
import sys
from pathlib import Path

spec = importlib.util.find_spec("nudenet")
if spec is None or not spec.origin:
    sys.exit("nudenet 没有安装：pip install nudenet")
pkg = Path(spec.origin).parent
cands = sorted(pkg.rglob("*.onnx"))
print("found:", [c.name for c in cands])
model = next((c for c in cands if c.name.lower() == "320n.onnx"), cands[0] if cands else None)
if model is None:
    sys.exit("nudenet 包里没有找到 .onnx 模型")
dest = Path(__file__).resolve().parents[1] / "models"
dest.mkdir(exist_ok=True)
shutil.copy(model, dest / "320n.onnx")
print("model ->", dest / "320n.onnx", (dest / "320n.onnx").stat().st_size, "bytes")

