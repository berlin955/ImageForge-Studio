"""打印 app/maskforge/__init__.py 里的版本号。"""
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "maskforge" / "__init__.py"
print(re.search(r'__version__\s*=\s*"([^"]+)"', p.read_text("utf-8")).group(1))
