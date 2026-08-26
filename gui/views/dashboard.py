"""仪表盘：关键指标 + 运行状态 + 环境摘要。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import core
import paths

from ..theme import (
    COLOR_FAIL,
    COLOR_IDLE,
    COLOR_OK,
    COLOR_RUNNING,
    COLOR_WARN,
    TEXT,
    TEXT_DIM,
    register_state_color,
)
from ..widgets import (
    KeyValueRow,
    MetricCard,
    button,
    hint_label,
    title_label,
    toolbar,
)


class DashboardView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.btn_refresh = button("刷新")
        self.btn_refresh.clicked.connect(
            lambda: self.update_state(core.stats_snapshot())
        )
        layout.addWidget(toolbar(title_label("仪表盘"), self.btn_refresh, stretch_at=0))

        # ---- 指标卡 ----
        self.cards: Dict[str, MetricCard] = {
            "success": MetricCard("成功账号", color=COLOR_OK),
            "recovery": MetricCard("辅助邮箱记录", color=COLOR_RUNNING),
            "records": MetricCard("总记录", color=TEXT),
            "failed": MetricCard("失败次数", color=COLOR_FAIL),
            "skipped": MetricCard("放弃任务", color=COLOR_WARN),
        }
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, key in enumerate(
            ["success", "recovery", "records", "failed", "skipped"]
        ):
            grid.addWidget(self.cards[key], 0, index)
        layout.addLayout(grid)

        # ---- 运行状态 ----
        run_box = QGroupBox("运行状态")
        run_layout = QVBoxLayout(run_box)
        self.rows: Dict[str, KeyValueRow] = {
            "state": KeyValueRow("注册进程"),
            "progress": KeyValueRow("本次进度"),
            "started": KeyValueRow("启动时间"),
        }
        for row in self.rows.values():
            run_layout.addWidget(row)
        layout.addWidget(run_box)

        # ---- 环境 ----
        env_box = QGroupBox("环境")
        env_layout = QVBoxLayout(env_box)
        self.env_rows: Dict[str, KeyValueRow] = {
            "kernel": KeyValueRow("浏览器内核", elide=True),
            "proxy": KeyValueRow("代理配置"),
            "data": KeyValueRow("数据目录", elide=True),
        }
        for row in self.env_rows.values():
            env_layout.addWidget(row)
        layout.addWidget(env_box)
        self._fill_env()

        # ---- 最近成功 ----
        recent_box = QGroupBox("最近成功账号")
        recent_layout = QVBoxLayout(recent_box)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["邮箱", "refresh_token"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(180)
        recent_layout.addWidget(self.table)
        recent_layout.addWidget(
            hint_label("完整结果见「启动注册」页的导出按钮，或直接打开 Results 目录。")
        )
        layout.addWidget(recent_box, 1)

    def _fill_env(self) -> None:
        cfg = core.load_config()
        browser = cfg.get("browser") or {}
        exe = (browser.get("executable_path") or "").strip()
        if exe:
            self.env_rows["kernel"].set_value(f"自定义: {exe}")
        else:
            fp = browser.get("fingerprint_enabled")
            mode = "内置 Chromium"
            if fp:
                mode += (f" + 指纹伪装 "
                         f"({browser.get('fingerprint_platform', 'windows')}/"
                         f"{browser.get('fingerprint_brand', 'Chrome')})")
            root = paths.browsers_root()
            self.env_rows["kernel"].set_value(f"{mode} — {root}")

        proxy = cfg.get("proxy") or {}
        host = (proxy.get("host") or "").strip()
        if not host:
            self.env_rows["proxy"].set_value("未配置（直连）", COLOR_WARN)
        elif proxy.get("mode") == "single":
            self.env_rows["proxy"].set_value(
                f"{proxy.get('type', 'http')}://{host}:{proxy.get('single_port')}"
            )
        else:
            self.env_rows["proxy"].set_value(
                f"{proxy.get('type', 'http')}://{host}:"
                f"{proxy.get('port_start')}-{proxy.get('port_end')} 端口池"
            )

        self.env_rows["data"].set_value(str(paths.APP_DIR))

    # ---------- 刷新 ----------
    def update_state(self, snapshot: Dict[str, Any]) -> None:
        self.cards["success"].set_value(snapshot.get("success_total", 0))
        self.cards["recovery"].set_value(snapshot.get("recovery_total", 0))
        self.cards["records"].set_value(snapshot.get("record_total", 0))
        self.cards["failed"].set_value(snapshot.get("failed_total", 0))
        self.cards["skipped"].set_value(snapshot.get("skipped_total", 0))

        reg = snapshot.get("register") or {}
        state = reg.get("state", "waiting")
        text = reg.get("state_text", "-")
        if reg.get("running") and reg.get("pid"):
            text = f"{text} (PID {reg['pid']})"
        self.rows["state"].set_value(text, register_state_color(state))

        total = reg.get("task_total") or 0
        if total:
            self.rows["progress"].set_value(
                f"{reg.get('completed', 0)}/{total} "
                f"（成功 {reg.get('success', 0)}，失败 {reg.get('failed', 0)}）"
            )
        else:
            self.rows["progress"].set_value("-", TEXT_DIM)
        self.rows["started"].set_value(reg.get("started_at") or "-")

        recent = snapshot.get("recent") or []
        self.table.setRowCount(len(recent))
        for row, item in enumerate(recent):
            self.table.setItem(row, 0, QTableWidgetItem(item.get("email", "")))
            token = item.get("refresh_token", "")
            cell = QTableWidgetItem(token[:48] + ("…" if len(token) > 48 else ""))
            cell.setToolTip(token)
            self.table.setItem(row, 1, cell)

    def on_config_changed(self) -> None:
        self._fill_env()
