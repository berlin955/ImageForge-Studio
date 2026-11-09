"""通过 GitHub Releases 检查和下载新版本。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
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


# 直连 GitHub 不通时依次尝试的下载加速镜像（下载后都会校验 SHA256，校验不通过不会安装）
MIRRORS = [
    "",
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]

_SHA_RE = re.compile(r"sha256:([^\s=]+)=([0-9a-fA-F]{64})")


def fetch_latest(timeout: float = 10) -> dict:
    req = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    body = data.get("body") or ""
    asset = None
    for a in data.get("assets", []):
        n = a.get("name", "")
        if n.lower().endswith(".exe") and "setup" in n.lower():
            asset = a
            break
    sha = ""
    if asset:
        dg = asset.get("digest") or ""
        if dg.lower().startswith("sha256:"):
            sha = dg.split(":", 1)[1]
        for name, h in _SHA_RE.findall(body):
            if name == asset.get("name"):
                sha = h
    notes = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "notes": notes,
        "page": data.get("html_url") or "",
        "asset_name": asset.get("name") if asset else "",
        "asset_url": asset.get("browser_download_url") if asset else "",
        "asset_size": asset.get("size", 0) if asset else 0,
        "sha256": sha.lower(),
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
    status = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, name: str, sha256: str = "", size: int = 0, parent=None):
        super().__init__(parent)
        self.url, self.name, self.sha256, self.size = url, name, sha256.lower(), size

    def _get(self, url: str, tmp: Path) -> None:
        """下载到 tmp，支持断点续传。"""
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
            if have and r.status != 206:
                have = 0  # 服务器不支持续传，从头开始
            total = int(r.headers.get("Content-Length") or 0) + have
            if self.size:
                total = self.size
            with open(tmp, "ab" if have else "wb") as f:
                got = have
                while True:
                    if self.isInterruptionRequested():
                        raise InterruptedError("已取消")
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
        if self.size and tmp.stat().st_size < self.size:
            raise IOError("下载不完整")

    def _verify(self, path: Path) -> bool:
        if not self.sha256:
            return True
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower() == self.sha256

    def run(self):
        folder = Path(tempfile.gettempdir()) / "MaskForge-Update"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / self.name
        tmp = dest.with_suffix(".part")
        errors = []
        for mirror in MIRRORS:
            if mirror and not self.sha256:
                continue  # 没有校验值时只用官方地址
            label = "GitHub" if not mirror else mirror.split("/")[2]
            for attempt in range(3):
                if self.isInterruptionRequested():
                    self.failed.emit("已取消")
                    return
                self.status.emit(f"正在从 {label} 下载" + (f"（第 {attempt + 1} 次）" if attempt else ""))
                try:
                    if not (self.size and tmp.exists() and tmp.stat().st_size == self.size):
                        self._get(mirror + self.url, tmp)
                    if not self._verify(tmp):
                        tmp.unlink(missing_ok=True)
                        raise IOError("文件校验不通过")
                    os.replace(tmp, dest)
                    self.done.emit(str(dest))
                    return
                except InterruptedError:
                    self.failed.emit("已取消")
                    return
                except Exception as e:
                    errors.append(f"{label}: {e}")
                    msg = str(e)
                    if "校验" in msg or "404" in msg or "403" in msg:
                        tmp.unlink(missing_ok=True)
                        break  # 这个来源不行，换下一个
                    time.sleep(1.5 * (attempt + 1))
            # 换来源前清掉半截文件，避免拼接不同来源的数据
            tmp.unlink(missing_ok=True)
        self.failed.emit("；".join(errors[-3:]) or "下载失败")


def launch_installer(path: str) -> None:
    """静默运行安装程序，安装完成后会自动重新打开软件。"""
    import subprocess
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SP-", "/NOCANCEL", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)
