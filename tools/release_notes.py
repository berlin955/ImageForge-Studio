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
# 安装包的 SHA256，软件自动更新时用来校验下载的文件
if len(sys.argv) > 3:
    import hashlib
    for f in sorted(Path(sys.argv[3]).glob("*.exe")):
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        body += f"\n\n<!-- sha256:{f.name}={h} -->"
out.write_text(body, "utf-8")
print(body)
