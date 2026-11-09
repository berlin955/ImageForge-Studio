"""智能打码工坊 MaskForge Studio 启动入口。"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _arg(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main() -> int:
    if "--selftest" in sys.argv:
        from maskforge.selftest import run_selftest
        return run_selftest(_arg("--selftest-log"))

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from maskforge import APP_NAME, APP_NAME_EN, AUTHOR, theme
    from maskforge.config import Config, data_dir
    from maskforge.mainwindow import MainWindow, app_icon
    from maskforge.stickers import StickerLibrary

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("berlin955.MaskForgeStudio")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME_EN)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(AUTHOR)
    app.setWindowIcon(app_icon())

    log_file = data_dir() / "error.log"

    def excepthook(t, v, tb):
        text = "".join(traceback.format_exception(t, v, tb))
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "出错了",
                                 f"软件遇到一个错误，已记录到：\n{log_file}\n\n{v}")
        except Exception:
            pass

    sys.excepthook = excepthook

    cfg = Config()
    theme.apply(app, cfg["theme"])
    lib = StickerLibrary()
    w = MainWindow(cfg, lib)
    w.show()

    files = [a for a in sys.argv[1:] if not a.startswith("--") and os.path.exists(a)]
    if files:
        w.import_paths(files)

    if cfg["check_update"] and getattr(sys, "frozen", False):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: w.check_updates(manual=False))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
