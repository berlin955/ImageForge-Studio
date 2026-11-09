"""从 CHANGELOG.md 取出某个版本的更新说明：python tools/release_notes.py 1.0.0 notes.md"""
import re
import sys
from pathlib import Path

ver = sys.argv[1].lstrip("vV")
out = Path(sys.argv[2])
text = Path(__file__).resolve().parents[1].joinpath("CHANGELOG.md").read_text("utf-8")
m = re.search(rf"^## v?{re.escape(ver)}\b.*?$\n(.*?)(?=^## |\Z)", text, re.S | re.M)
body = m.group(1).strip() if m else "更新内容见项目主页。"
body += "\n\n**安装**：下载 `MaskForge-Studio-Setup-*.exe` 双击安装。已安装的用户打开软件会自动提示更新。"
out.write_text(body, "utf-8")
print(body)
