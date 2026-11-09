"""配置、路径和常量。"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

PARTS = [
    ("lower", "下体"),
    ("crack", "股沟"),
    ("areola", "乳晕"),
    ("custom", "自定义"),
]
PART_NAMES = dict(PARTS)

STYLES = [
    ("sticker", "贴图"),
    ("mosaic", "马赛克"),
    ("blur", "模糊"),
    ("solid", "色块"),
]
STYLE_NAMES = dict(STYLES)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def resource_dir() -> Path:
    """模型、图标等随程序发布的资源所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # 源码运行：app/maskforge/config.py -> 仓库根目录
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """用户数据目录：%APPDATA%/MaskForge Studio"""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "MaskForge Studio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def model_path() -> Path:
    return resource_dir() / "models" / "320n.onnx"


def icon_path() -> Path:
    return resource_dir() / "assets" / "icon.png"


DEFAULTS: dict = {
    "theme": "dark",
    "check_update": True,
    "skip_version": "",
    "last_dir": "",
    "detect": {
        "threshold": 0.35,
        "male": False,
    },
    "parts": {
        "lower": {"enabled": True, "style": "mosaic", "sticker": "builtin:heart",
                  "color": "#16171b", "block": 0.018, "scale": 1.15, "opacity": 1.0},
        "crack": {"enabled": True, "style": "mosaic", "sticker": "builtin:bar",
                  "color": "#16171b", "block": 0.016, "scale": 1.0, "opacity": 1.0},
        "areola": {"enabled": True, "style": "sticker", "sticker": "builtin:heart",
                   "color": "#16171b", "block": 0.012, "scale": 1.0, "opacity": 1.0},
        "custom": {"enabled": True, "style": "blur", "sticker": "builtin:star",
                   "color": "#16171b", "block": 0.02, "scale": 1.0, "opacity": 1.0},
    },
    "export": {
        "dir": "",
        "scope": "all",          # all | confirmed
        "mode": "long",          # none | long | width | height | percent
        "value": 1600,
        "no_upscale": True,
        "format": "jpg",         # jpg | png | webp
        "quality": 92,
        "prefix": "",
        "suffix": "_打码",
        "overwrite": False,
        "open_after": True,
    },
}


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v)
        else:
            base[k] = v


class Config:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else data_dir() / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        try:
            if self.path.exists():
                _merge(self.data, json.loads(self.path.read_text("utf-8")))
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def part(self, key: str) -> dict:
        return self.data["parts"].get(key) or self.data["parts"]["custom"]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.path)
        except Exception:
            pass
