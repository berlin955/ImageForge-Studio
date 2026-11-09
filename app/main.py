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

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from maskforge import APP_NAME, APP_NAME_EN, AUTHOR, __version__, theme
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

    # 记录闪退（程序直接退出）时的现场，方便排查
    try:
        import faulthandler
        _crash = open(data_dir() / "crash.log", "a", encoding="utf-8")
        _crash.write(f"\n===== start v{__version__} =====\n")
        _crash.flush()
        faulthandler.enable(file=_crash, all_threads=True)
    except Exception:
        pass

    state = {"last": 0.0, "showing": False}

    def show_error(msg):
        if state["showing"]:
            return
        state["showing"] = True
        try:
            QMessageBox.critical(None, "出错了",
                                 f"软件遇到一个错误，已记录到：\n{log_file}\n\n{msg}\n\n"
                                 "软件可以继续使用。如果反复出现，请把这个文件发给作者。")
        finally:
            state["showing"] = False

    def excepthook(t, v, tb):
        import time
        text = "".join(traceback.format_exception(t, v, tb))
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + f"v{__version__}\n" + text + "\n")
        except Exception:
            pass
        now = time.time()
        if now - state["last"] > 5:
            state["last"] = now
            # 不在出错的地方（可能是绘制中）直接弹窗，放到下一轮事件循环
            QTimer.singleShot(0, lambda: show_error(v))

    sys.excepthook = excepthook

    cfg = Config()
    from maskforge.updater import set_preference
    set_preference(cfg["update_mirror"], cfg["update_mirror_custom"])
    theme.apply(app, cfg["theme"])
    lib = StickerLibrary()
    w = MainWindow(cfg, lib)
    w.show()

    files = [a for a in sys.argv[1:] if not a.startswith("--") and os.path.exists(a)]
    if files:
        w.import_paths(files)

    if cfg["check_update"] and getattr(sys, "frozen", False):
        QTimer.singleShot(2500, lambda: w.check_updates(manual=False))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
