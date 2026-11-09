"""把版本号写入 app/maskforge/__init__.py：python tools/set_version.py 1.2.3"""
import re
import sys
from pathlib import Path

v = sys.argv[1].lstrip("vV")
p = Path(__file__).resolve().parents[1] / "app" / "maskforge" / "__init__.py"
s = p.read_text("utf-8")
s = re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{v}"', s)
p.write_text(s, "utf-8")
print(f"version -> {v}")
