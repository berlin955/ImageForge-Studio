"""通过 GitHub Releases 检查和下载新版本。"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import REPO, __version__

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = f"MaskForge-Studio/{__version__}"


def parse_version(s: str) -> tuple:
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _ctx():
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def fetch_latest(timeout: float = 10) -> dict:
    req = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    asset = None
    for a in data.get("assets", []):
        n = a.get("name", "")
        if n.lower().endswith(".exe") and "setup" in n.lower():
            asset = a
            break
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "notes": data.get("body") or "",
        "page": data.get("html_url") or "",
        "asset_name": asset.get("name") if asset else "",
        "asset_url": asset.get("browser_download_url") if asset else "",
        "asset_size": asset.get("size", 0) if asset else 0,
    }


class UpdateChecker(QThread):
    found = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(fetch_latest())
        except Exception as e:
            self.failed.emit(str(e))


class Downloader(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, name: str, parent=None):
        super().__init__(parent)
        self.url, self.name = url, name

    def run(self):
        try:
            folder = Path(tempfile.gettempdir()) / "MaskForge-Update"
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / self.name
            tmp = dest.with_suffix(".part")
            req = urllib.request.Request(self.url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    if self.isInterruptionRequested():
                        raise RuntimeError("已取消")
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            os.replace(tmp, dest)
            self.done.emit(str(dest))
        except Exception as e:
            self.failed.emit(str(e))


def launch_installer(path: str) -> None:
    """静默运行安装程序，安装完成后会自动重新打开软件。"""
    import subprocess
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SP-", "/NOCANCEL", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)
