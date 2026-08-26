"""主窗口：侧栏导航 + 页面栈 + 状态栏。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import core
import paths
import version as appver

from .theme import TEXT_DIM, refit_widget_tree, register_state_color
from .views import AboutView, DashboardView, RegisterView, SettingsView
from .widgets import confirm


class MainWindow(QMainWindow):
    #: 轮询间隔。1s 足够跟上日志，又不至于让 CPU 空转
    POLL_MS = 1000

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"OutlookRegister v{appver.VERSION}")
        self.resize(1180, 800)
        self.setMinimumSize(980, 660)

        self._pages: Dict[str, QWidget] = {}
        self._build()
        refit_widget_tree(self)
        # 度量修正后必须重新活动布局，否则旧尺寸会保留到首次显示
        for page in self._pages.values():
            layout = page.layout()
            if layout is not None:
                layout.activate()
        self._start_timers()
        self._refresh()

    # ---------- 构建 ----------
    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.dashboard = DashboardView()
        self.register = RegisterView()
        self.settings = SettingsView(on_saved=self._on_config_saved)
        self.about = AboutView()

        self._pages = {
            "仪表盘": self.dashboard,
            "启动注册": self.register,
            "系统设置": self.settings,
            "关于与更新": self.about,
        }
        for page in self._pages.values():
            self.stack.addWidget(page)

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._build_status_bar()

        self.nav.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        host = QWidget()
        host.setFixedWidth(170)
        host.setStyleSheet("background: #1f2733;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel("OutlookRegister")
        brand.setProperty("role", "brand")
        sub = QLabel(f"v{appver.VERSION}")
        sub.setProperty("role", "brand-sub")

        self.nav = QListWidget()
        self.nav.setProperty("role", "nav")
        self.nav.setFocusPolicy(Qt.NoFocus)
        self.nav.addItems(["仪表盘", "启动注册", "系统设置", "关于与更新"])
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addWidget(self.nav, 1)
        return host

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.st_state = QLabel("就绪")
        self.st_worker = QLabel("注册进程：未运行")
        self.st_success = QLabel("成功 0")
        self.st_data = QLabel(str(paths.APP_DIR))
        self.st_data.setToolTip("数据目录（config.json / Results / log 都在这里）")

        for widget in (self.st_worker, self.st_success, self.st_data):
            widget.setStyleSheet(f"color: {TEXT_DIM};")

        bar.addWidget(self.st_state, 1)
        bar.addPermanentWidget(self.st_worker)
        bar.addPermanentWidget(self.st_success)
        bar.addPermanentWidget(self.st_data)

    # ---------- 定时刷新 ----------
    def _start_timers(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        snapshot = core.stats_snapshot()
        for page in self._pages.values():
            if hasattr(page, "update_state"):
                page.update_state(snapshot)
        # 日志只在注册页读 —— 增量游标是全局的，多处读会互相吃掉行
        self.register.poll_logs()
        self._update_status_bar(snapshot)

    def _update_status_bar(self, snapshot: Dict[str, Any]) -> None:
        reg = snapshot.get("register") or {}
        if reg.get("running"):
            text = f"注册进程：运行中 (PID {reg.get('pid')})"
        else:
            text = f"注册进程：{reg.get('state_text', '未运行')}"
        self.st_worker.setText(text)
        self.st_worker.setStyleSheet(
            f"color: {register_state_color(reg.get('state', 'waiting'))};")
        self.st_success.setText(f"成功 {snapshot.get('success_total', 0)}")

    # ---------- 交互 ----------
    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        self.st_state.setText(self.nav.item(row).text())

    def _on_config_saved(self) -> None:
        self.dashboard.on_config_changed()
        self.st_state.setText("配置已保存")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """注册进程独立于窗口存在，关窗前必须问清楚。

        直接放行会让 worker 变成孤儿进程：仍在跑、仍在写结果，
        但用户以为已经关了 —— 下次启动还会撞上「已有任务正在运行」。
        """
        if core.register_running():
            if not confirm(self, "注册仍在运行",
                           "注册进程仍在后台运行。\n\n"
                           "关闭窗口不会停止它 —— 它会继续注册并写入结果。\n"
                           "要先停止请点「取消」，到「启动注册」页点停止。\n\n"
                           "仍要关闭窗口？"):
                event.ignore()
                return
        self._timer.stop()
        event.accept()
