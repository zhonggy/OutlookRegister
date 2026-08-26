"""关于与更新：版本信息 + 手动检查更新。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

import core
import paths
import updater
import version as appver

from ..tasks import run_async
from ..theme import COLOR_FAIL, COLOR_OK, COLOR_WARN, TEXT_DIM
from ..widgets import (
    KeyValueRow,
    StatusLine,
    button,
    confirm,
    hint_label,
    title_label,
    toolbar,
    warn,
)


class AboutView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(1200)
        self._timer.timeout.connect(self._sync_update_state)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(toolbar(title_label("关于与更新")))

        # ---- 版本 ----
        ver_box = QGroupBox("版本信息")
        ver_layout = QVBoxLayout(ver_box)
        import sys
        rows = {
            "版本": f"v{appver.VERSION}",
            "运行模式": "打包版 (exe)" if getattr(sys, "frozen", False) else "源码模式",
            "数据目录": str(paths.APP_DIR),
            "配置文件": str(paths.CONFIG_PATH),
            "浏览器内核": str(paths.browsers_root()),
        }
        for key, value in rows.items():
            ver_layout.addWidget(KeyValueRow(key, value, elide=len(value) > 40,
                                             key_width=88))
        ver_layout.addWidget(hint_label(
            "config.json、Results、log 都保存在数据目录，更新时不会被覆盖。"))
        layout.addWidget(ver_box)

        # ---- 更新 ----
        upd_box = QGroupBox("手动更新")
        upd_layout = QVBoxLayout(upd_box)

        self.btn_check = button("检查更新", role="primary")
        self.btn_download = button("下载更新")
        self.btn_apply = button("立即重启并更新")
        self.btn_page = button("打开发布页")
        self.btn_check.clicked.connect(self._on_check)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_page.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(appver.RELEASE_PAGE)))
        self.btn_download.setEnabled(False)
        self.btn_apply.setEnabled(False)

        upd_layout.addWidget(toolbar(
            self.btn_check, self.btn_download, self.btn_apply, self.btn_page))

        self.status = StatusLine(timeout_ms=60000)
        upd_layout.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        upd_layout.addWidget(self.bar)

        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("更新说明会显示在这里")
        self.notes.setMaximumHeight(220)
        self.notes.setVisible(False)
        upd_layout.addWidget(self.notes)

        upd_layout.addWidget(hint_label(
            "不会自动更新。更新前请先停止正在运行的注册任务 —— "
            "worker 进程占用程序文件会导致更新失败。<br>"
            "若 GitHub 无法访问，会按设置里的选项尝试使用代理。"))
        layout.addWidget(upd_box)
        layout.addStretch(1)

    # ---------- 更新流程 ----------
    def _on_check(self) -> None:
        self.btn_check.setEnabled(False)
        self.status.show_message("正在查询最新版本…", TEXT_DIM)
        self._timer.start()

        def done(_result: Any) -> None:
            self.btn_check.setEnabled(True)
            self._sync_update_state()

        run_async(updater.check, done, owner=self)

    def _on_download(self) -> None:
        self.btn_download.setEnabled(False)
        self.bar.setVisible(True)
        self._timer.start()
        run_async(updater.download_and_stage,
                  lambda _r: self._sync_update_state(), owner=self)

    def _on_apply(self) -> None:
        if core.register_running():
            warn(self, "无法更新",
                 "注册任务正在运行。\n\n"
                 "worker 进程占用着程序文件，更新会失败。\n"
                 "请先到「启动注册」页点停止。")
            return
        if not confirm(self, "立即更新",
                       "程序将关闭并安装更新，完成后自动重启。\n\n"
                       "config.json、Results、log 会被保留。继续？"):
            return
        result = updater.apply_and_restart()
        self.status.show_result(
            {"ok": result.get("phase") != "error",
             "detail": result.get("message", "")})

    def _sync_update_state(self) -> None:
        snap = updater.snapshot()
        phase = snap.get("phase", "idle")

        self.btn_download.setEnabled(phase == "available")
        self.btn_apply.setEnabled(phase == "ready")

        color = TEXT_DIM
        if phase == "error":
            color = COLOR_FAIL
        elif phase in ("uptodate", "ready"):
            color = COLOR_OK
        elif phase == "available":
            color = COLOR_WARN
        message = snap.get("message") or phase
        self.status.show_message(str(message), color)

        if phase == "downloading":
            self.bar.setVisible(True)
            self.bar.setValue(int(snap.get("percent") or 0))
            size = snap.get("size") or 0
            got = snap.get("downloaded") or 0
            if size:
                self.bar.setFormat(
                    f"{got / 1048576:.1f} / {size / 1048576:.1f} MB  (%p%)")
        elif phase in ("ready", "error", "uptodate"):
            if phase != "downloading":
                self.bar.setVisible(phase == "ready")
                if phase == "ready":
                    self.bar.setValue(100)
                    self.bar.setFormat("下载完成 (100%)")

        notes = snap.get("notes") or ""
        if notes and phase in ("available", "ready"):
            self.notes.setVisible(True)
            if self.notes.toPlainText() != notes:
                self.notes.setPlainText(notes)
        elif phase in ("uptodate", "idle"):
            self.notes.setVisible(False)

        # 终态后停掉轮询，别让定时器空转
        if phase in ("idle", "uptodate", "ready", "error", "restarting"):
            self._timer.stop()

    def update_state(self, snapshot) -> None:
        """占位：本页数据不依赖注册状态快照。"""
        return
