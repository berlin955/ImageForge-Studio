"""生成 latest.json（随 Release 发布，镜像线路检查更新时读取）。
用法：python tools/latest_json.py 版本号 notes.md 安装包目录"""
import hashlib
import json
import re
import sys
from pathlib import Path

ver = sys.argv[1].lstrip("vV")
notes = re.sub(r"<!--.*?-->", "", Path(sys.argv[2]).read_text("utf-8"), flags=re.S).strip()
folder = Path(sys.argv[3])
repo = "berlin955/ImageForge-Studio"
exe = next(iter(sorted(folder.glob("*Setup*.exe"))), None)
info = {"version": ver, "tag": f"v{ver}", "notes": notes,
        "page": f"https://github.com/{repo}/releases/tag/v{ver}"}
if exe:
    info.update({
        "asset_name": exe.name,
        "asset_url": f"https://github.com/{repo}/releases/download/v{ver}/{exe.name}",
        "asset_size": exe.stat().st_size,
        "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
    })
(folder / "latest.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps({k: v for k, v in info.items() if k != "notes"}, ensure_ascii=False))
