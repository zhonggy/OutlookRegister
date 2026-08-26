#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OutlookRegister 统一入口（PyInstaller 打包目标）。

模式：
    OutlookRegister.exe                 启动桌面 GUI  —— 默认
    OutlookRegister.exe --worker        注册执行进程（由 GUI 拉起）
    OutlookRegister.exe --version       打印版本

打包后 sys.executable 就是 OutlookRegister.exe，GUI 用 --worker 重入自身，
保持进程隔离：注册崩溃不影响界面，停止 = 向进程发信号触发其清理逻辑。

--worker 分支绝不导入 PySide6：注册进程不需要界面，加载一整套 Qt 只是
白占内存，而且 CREATE_NO_WINDOW 下无窗口环境，Qt 初始化本身可能失败。
"""
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _force_utf8_streams() -> None:
    """标准流切 UTF-8。必须在任何 print 之前执行。

    本项目日志全是中文，而 Windows 上重定向的 stdout 用的是 locale 编码。
    GUI 拉起 worker 时把输出重定向到 log/web_console_run.log，若系统
    locale 是 GBK/cp1252，第一条中文 print 就会 UnicodeEncodeError ——
    worker 直接起不来。

    errors="replace" 而非严格模式：日志里出乱码可以接受，
    因为写不出日志而停工不可以。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


_force_utf8_streams()

import paths  # noqa: E402
import version as appver  # noqa: E402

# 内置 Chromium 必须在任何 patchright 导入之前声明
paths.setup_browsers_env()


def _bootstrap_data_dir(quiet: bool = False) -> None:
    """首次运行：探测写权限 → 建目录 → 从模板生成 config.json。"""
    ok, detail = paths.check_writable()
    if not ok:
        message = (
            "程序目录不可写，无法保存配置和注册结果。\n\n"
            f"{detail}\n\n"
            "请把整个文件夹移到有写权限的位置（如 D:\\OutlookRegister）"
            "后重新运行，不要放在 C:\\Program Files 下。"
        )
        if quiet:
            # GUI 模式：无控制台可看，必须弹窗
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.critical(None, "无法启动", message)
            except Exception:
                pass
        else:
            print("=" * 60)
            print("[FATAL] " + message)
            print("=" * 60)
        sys.exit(1)

    paths.ensure_dirs()

    if not paths.CONFIG_PATH.exists():
        if paths.CONFIG_EXAMPLE.is_file():
            paths.CONFIG_PATH.write_bytes(paths.CONFIG_EXAMPLE.read_bytes())
            if not quiet:
                print(f"[init] 已生成配置文件: {paths.CONFIG_PATH}")
        elif not quiet:
            print(f"[WARN] 缺少配置模板 {paths.CONFIG_EXAMPLE}，请手动创建 config.json")


def _run_worker() -> int:
    import main
    main.run()
    return 0


def _run_gui() -> int:
    import gui
    return gui.run(sys.argv)


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-v"):
        print(appver.DISPLAY_NAME)
        return 0

    is_worker = "--worker" in argv
    _bootstrap_data_dir(quiet=not is_worker)

    if is_worker:
        return _run_worker()
    return _run_gui()


if __name__ == "__main__":
    sys.exit(main())
