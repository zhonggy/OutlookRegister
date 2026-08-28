"""启动注册：参数 → 启停 → 进度 → 实时日志 → 导出结果。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

import core

from ..tasks import run_async
from ..theme import (
    COLOR_FAIL,
    COLOR_OK,
    COLOR_WARN,
    TEXT_DIM,
    log_level_color,
    register_state_color,
)
from ..widgets import (
    KeyValueRow,
    StatusLine,
    button,
    confirm,
    hint_label,
    spinbox,
    title_label,
    toolbar,
)

#: 日志区最多保留的行数。无上限时长跑几小时会吃掉几百 MB 内存
MAX_LOG_BLOCKS = 4000


class RegisterView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._stopping = False
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(toolbar(title_label("启动注册")))

        # ---- 任务参数 ----
        param_box = QGroupBox("任务参数")
        grid = QGridLayout(param_box)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        def _lbl(text: str) -> QLabel:
            # 与系统设置页同规范：110px 右对齐，让输入框左缘垂直成线
            label = QLabel(text)
            label.setFixedWidth(110)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return label

        cfg = core.load_config()
        self.sp_tasks = spinbox(1, 100000, int(cfg.get("tasks") or 1))
        self.sp_concurrent = spinbox(1, 64, int(cfg.get("concurrent_flows") or 1), digits=3)

        grid.addWidget(_lbl("注册数量"), 0, 0)
        grid.addWidget(self.sp_tasks, 0, 1)
        grid.addWidget(_lbl("并发数"), 0, 2)
        grid.addWidget(self.sp_concurrent, 0, 3)
        grid.setColumnStretch(4, 1)
        grid.addWidget(
            hint_label("并发数受代理端口数限制。端口池模式下建议不超过可用端口数量。"),
            1, 0, 1, 5,
        )
        layout.addWidget(param_box)

        # ---- 操作 ----
        self.btn_start = button("开始注册", role="primary")
        self.btn_stop = button("停止", role="danger")
        self.btn_check = button("连通检查")
        self.btn_clear = button("清空日志")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_check.clicked.connect(self._on_check)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_stop.setEnabled(False)

        layout.addWidget(toolbar(
            self.btn_start, self.btn_stop, self.btn_check, self.btn_clear,
        ))

        self.status = StatusLine()
        layout.addWidget(self.status)

        # ---- 进度 ----
        prog_box = QGroupBox("进度")
        prog_layout = QVBoxLayout(prog_box)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        prog_layout.addWidget(self.bar)

        self.rows: Dict[str, KeyValueRow] = {
            "state": KeyValueRow("状态"),
            "counts": KeyValueRow("完成情况"),
            "started": KeyValueRow("启动时间"),
        }
        for row in self.rows.values():
            prog_layout.addWidget(row)
        layout.addWidget(prog_box)

        # ---- 日志 ----
        log_box = QGroupBox("实时日志")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setProperty("role", "log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_BLOCKS)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setPlaceholderText("等待日志输出…")
        log_layout.addWidget(self.log)

        export_row = QHBoxLayout()
        self.btn_export_oauth = button("导出 oauth2.txt")
        self.btn_export_recovery = button("导出辅助邮箱记录")
        self.btn_open_dir = button("打开结果目录")
        self.btn_push = button("推送到 Manager")
        self.btn_export_oauth.clicked.connect(
            lambda: self._export(core.OAUTH_FILE, "oauth2.txt"))
        self.btn_export_recovery.clicked.connect(
            lambda: self._export(core.RECOVERY_FILE, "recovery_emails.txt"))
        self.btn_open_dir.clicked.connect(self._open_results_dir)
        self.btn_push.clicked.connect(self._on_push)
        for btn in (self.btn_export_oauth, self.btn_export_recovery,
                    self.btn_open_dir, self.btn_push):
            export_row.addWidget(btn)
        export_row.addStretch(1)
        log_layout.addLayout(export_row)

        layout.addWidget(log_box, 1)

    # ---------- 操作 ----------
    def _on_start(self) -> None:
        tasks = self.sp_tasks.value()
        concurrent = self.sp_concurrent.value()
        result = core.start_register(tasks, concurrent)
        self.status.show_result(result)
        if result.get("ok"):
            self.log.clear()
            core.reset_log_cursor()

    def _on_stop(self) -> None:
        if not confirm(self, "停止注册",
                       "将请求注册进程优雅退出。\n\n"
                       "它会先写出统计汇总、再关闭浏览器并清理临时 profile，"
                       "可能需要等十几秒。"):
            return
        self._stopping = True
        self.btn_stop.setEnabled(False)
        self.status.show_message("正在停止，等待汇总与清理…", COLOR_WARN)
        run_async(core.stop_register, self._on_stopped, owner=self)

    def _on_stopped(self, result: Any) -> None:
        self._stopping = False
        self.status.show_result(result if isinstance(result, dict) else {"ok": False})

    def _on_check(self) -> None:
        self.btn_check.setEnabled(False)
        self.status.show_message("正在检查代理连通性…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_check.setEnabled(True)
            self.status.show_result(result if isinstance(result, dict) else {"ok": False})

        run_async(core.check_connectivity, done, owner=self)

    def _on_clear(self) -> None:
        result = core.clear_log_and_stats()
        self.log.clear()
        self.bar.setValue(0)
        self.status.show_result(result)

    def _on_push(self) -> None:
        self.btn_push.setEnabled(False)
        self.status.show_message("正在推送…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_push.setEnabled(True)
            self.status.show_result(result if isinstance(result, dict) else {"ok": False})

        run_async(core.push_to_manager, done, owner=self)

    def _export(self, src: str, default_name: str) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "导出到", default_name, "文本文件 (*.txt);;所有文件 (*)")
        if not dest:
            return
        self.status.show_result(core.export_file(src, dest))

    def _open_results_dir(self) -> None:
        os.makedirs(core.RESULTS_DIR, exist_ok=True)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(core.RESULTS_DIR))

    # ---------- 刷新 ----------
    def update_state(self, snapshot: Dict[str, Any]) -> None:
        reg = snapshot.get("register") or {}
        running = bool(reg.get("running"))

        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running and not self._stopping)
        for widget in (self.sp_tasks, self.sp_concurrent):
            widget.setEnabled(not running)

        state = reg.get("state", "waiting")
        text = reg.get("state_text", "-")
        if running and reg.get("pid"):
            text = f"{text} (PID {reg['pid']})"
        self.rows["state"].set_value(text, register_state_color(state))

        total = reg.get("task_total") or 0
        success = reg.get("success", 0)
        failed = reg.get("failed", 0)
        if total:
            self.rows["counts"].set_value(
                f"{reg.get('completed', 0)}/{total}　成功 {success}　失败 {failed}"
            )
        else:
            self.rows["counts"].set_value("-", TEXT_DIM)
        self.rows["started"].set_value(reg.get("started_at") or "-")
        self.bar.setValue(int(reg.get("percent") or 0))

    def poll_logs(self) -> None:
        """增量读取运行日志。worker 写文件，GUI 定时读新增字节。"""
        lines = core.read_log_incremental()
        if not lines:
            return
        at_bottom = self._at_bottom()
        for line in lines:
            self._append_line(line)
        if at_bottom:
            self.log.moveCursor(QTextCursor.End)

    def _at_bottom(self) -> bool:
        """滚动条在底部时才自动跟随 —— 用户往上翻看历史时不该被拽回去。"""
        bar = self.log.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _append_line(self, line: str) -> None:
        color = self._line_color(line)
        text = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log.appendHtml(f'<span style="color:{color};white-space:pre">{text}</span>')

    @staticmethod
    def _line_color(line: str) -> str:
        upper = line.upper()
        for token in ("[FAIL]", "[ERROR]", "ERROR", "失败"):
            if token in upper or token in line:
                return log_level_color("FAIL")
        for token in ("[OK]", "[SUCCESS]", "成功"):
            if token in upper or token in line:
                return log_level_color("OK")
        if "[WARN]" in upper or "WARNING" in upper:
            return log_level_color("WARN")
        return "#d6dce5"
