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
    """用户数据目录：%APPDATA%/ImageForge Studio（旧版的 MaskForge Studio 会自动搬过来）"""
    base = Path(os.environ.get("APPDATA") or str(Path.home() / ".config"))
    p = base / "ImageForge Studio"
    if not p.exists():
        old = base / "MaskForge Studio"
        if old.exists():
            try:
                import shutil
                shutil.copytree(old, p)
            except Exception:
                pass
    p.mkdir(parents=True, exist_ok=True)
    return p


def model_path() -> Path:
    """优先用精度更高的 640m 模型，没有时用 320n。"""
    d = resource_dir() / "models"
    for name in ("640m.onnx", "320n.onnx"):
        if (d / name).exists():
            return d / name
    return d / "640m.onnx"


def icon_path() -> Path:
    return resource_dir() / "assets" / "icon.png"


CONFIG_VERSION = 5

DEFAULTS: dict = {
    "config_version": CONFIG_VERSION,
    "theme": "dark",
    "check_update": True,
    "update_mirror": "auto",          # auto | direct | 镜像地址 | custom
    "update_mirror_custom": "",
    "skip_version": "",
    "last_dir": "",
    "detect": {
        "threshold": 0.25,
        "male": False,
    },
    "parts": {
        "lower": {"enabled": True, "covered": True, "style": "mosaic", "sticker": "builtin:heart",
                  "color": "#16171b", "block": 0.018, "scale": 0.58, "opacity": 1.0},
        "crack": {"enabled": True, "covered": True, "style": "mosaic", "sticker": "builtin:bar",
                  "color": "#16171b", "block": 0.016, "scale": 0.5, "opacity": 1.0},
        "areola": {"enabled": True, "covered": False, "style": "sticker", "sticker": "builtin:heart",
                   "color": "#16171b", "block": 0.012, "scale": 0.5, "opacity": 1.0},
        "custom": {"enabled": True, "style": "blur", "sticker": "builtin:star",
                   "color": "#16171b", "block": 0.02, "scale": 1.0, "opacity": 1.0},
    },
    "mainimg": {
        "size": 800,
        "custom": 1200,
        "mode": "smart",          # smart 智能裁切 | center 居中裁切 | pad 留白不裁
        "pad_color": "#ffffff",
        "layout": "single",       # single 单张 | collage 竖格拼图
        "cells": 2,
        "gap": 8,
        "bg": "#ffffff",
        "format": "jpg",
        "suffix": "_主图",
        "folder": "主图",
        "use_mask": True,
        "logo": {"enabled": False, "file": "", "size": 0.2, "margin": 0.03, "opacity": 1.0, "corner": "tl"},
    },
    "spec": {
        "format": "jpg",
        "last_template": "",
        "use_mask": True,
    },
    "export": {
        "dir": "",
        "scope": "all",          # all | skip_attention
        "normal": True,          # 导出普通图（按下面的尺寸）
        "main": {                # 主图（正方形）
            "enabled": False,
            "size": 800,
            "mode": "smart",     # smart 智能裁切 | center 居中裁切 | pad 留白不裁切
            "pad_color": "#ffffff",
            "suffix": "_主图",
            "folder": "主图",
        },
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
                saved = json.loads(self.path.read_text("utf-8"))
                old = int(saved.get("config_version", 1))
                _merge(self.data, saved)
                if old < 2:
                    # v1.0.0 的默认灵敏度偏低，升级时改成新的默认值
                    if abs(float(self.data["detect"].get("threshold", 0.25)) - 0.35) < 1e-6:
                        self.data["detect"]["threshold"] = 0.25
                if old < 3:
                    # v1.0.4：自动码默认缩小一半；用户改过的大小保持不变
                    for key, old_default in (("lower", 1.15), ("crack", 1.0), ("areola", 1.0)):
                        part = self.data["parts"].get(key, {})
                        if abs(float(part.get("scale", old_default)) - old_default) < 1e-6:
                            part["scale"] = DEFAULTS["parts"][key]["scale"]
                if self.data["export"].get("scope") not in ("all", "skip_attention"):
                    self.data["export"]["scope"] = "all"
                self.data["config_version"] = CONFIG_VERSION
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
