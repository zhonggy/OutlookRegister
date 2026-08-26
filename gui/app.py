"""桌面 GUI 引导。

只在这一层碰 Qt —— app.py 的 --worker 分支不会导入本模块，
避免注册子进程白白加载一整套 Qt（几十 MB 内存，且无窗口环境下
QApplication 初始化本身可能失败）。
"""

from __future__ import annotations

import sys
from typing import List, Optional


def run(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    # 高 DPI 下不开这个，1.5x 缩放的屏上图标和边框会发虚
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(argv)
    app.setApplicationName("OutlookRegister")
    app.setOrganizationName("OutlookRegister")

    from .single_instance import SingleInstance

    guard = SingleInstance("OutlookRegister-gui")
    if not guard.acquire():
        QMessageBox.warning(
            None, "OutlookRegister",
            "程序已在运行。\n\n"
            "重复启动会让两个窗口各自拉起注册进程，"
            "争抢同一份配置和 profile 目录，因此本次启动已取消。",
        )
        return 0

    from .theme import apply_theme
    apply_theme(app)

    from .main_window import MainWindow

    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(
            None, "启动失败",
            f"界面初始化失败：{exc.__class__.__name__}: {exc}",
        )
        guard.release()
        return 1

    window.show()

    # CI 冒烟测试：OR_SMOKE_EXIT_MS 毫秒后自行退出。必须用 QTimer 而非
    # threading.Timer —— QApplication.quit() 不是线程安全的，从子线程调不会生效。
    import os
    smoke = os.environ.get("OR_SMOKE_EXIT_MS", "").strip()
    if smoke.isdigit():
        QTimer.singleShot(max(200, int(smoke)), app.quit)

    try:
        code = app.exec()
    finally:
        guard.release()
    return code
