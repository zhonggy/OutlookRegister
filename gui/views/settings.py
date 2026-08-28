"""系统设置：可视化编辑 config.json。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import core

from ..tasks import run_async
from ..theme import TEXT_DIM
from ..widgets import (
    StatusLine,
    button,
    hint_label,
    spinbox,
    title_label,
    toolbar,
)

#: 表单标签固定宽度（px）。所有标签右对齐后，输入框左缘形成垂直直线，
#: 不再因标签长短不一直接导致“锯齿状”错位。最长标签 ≈8 个全角字符可容纳
FORM_LABEL_WIDTH = 110


def _lbl(text: str):
    """固定宽度、右对齐的表单标签。空串占位用于让无标签行（勾选框等）
    的控件也对齐到同一竖线。"""
    label = QLabel(text)
    label.setFixedWidth(FORM_LABEL_WIDTH)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def _combo(options, current) -> QComboBox:
    """options: [(value, label), ...]"""
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    index = box.findData(current)
    box.setCurrentIndex(index if index >= 0 else 0)
    return box


def _form(box: QGroupBox) -> QFormLayout:
    """统一的表单布局。

    WrapLongRows：窗口窄时把标签换到输入框上方，让输入框拿到全宽。
    两列布局下长 URL 字段否则只剩 170px，基本看不全。
    """
    form = QFormLayout(box)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(8)
    return form


class SettingsView(QWidget):
    """保存后写回 config.json。下次启动注册生效（运行中的 worker 不受影响）。"""

    def __init__(self, on_saved=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._on_saved = on_saved
        self._build()
        self.reload()

    # ---------- 构建 ----------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self.btn_save = button("保存配置", role="primary")
        self.btn_reload = button("重新载入")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_reload.clicked.connect(self.reload)
        outer.addWidget(toolbar(
            title_label("系统设置"), self.btn_save, self.btn_reload, stretch_at=0))

        self.status = StatusLine()
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._grid = QGridLayout(host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

        self._boxes = [
            self._build_basic(),
            self._build_proxy(),
            self._build_oauth(),
            self._build_browser(),
            self._build_temp_mail(),
            self._build_resin(),
            self._build_manager(),
            self._build_update(),
        ]
        self._columns = 0
        self._relayout(2)

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def _relayout(self, columns: int) -> None:
        """在一列/两列之间切换。

        两列布局在窗口变窄时会把 URL 输入框挤到 100px 左右，根本没法看；
        横向滚动条又难用。因此窗口窄时直接改单列。
        """
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, box in enumerate(self._boxes):
            row, col = divmod(index, columns)
            self._grid.addWidget(box, row, col)
        for col in range(2):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)
        rows = (len(self._boxes) + columns - 1) // columns
        self._grid.setRowStretch(rows, 1)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout(2 if self.width() >= 1000 else 1)

    def _build_basic(self) -> QGroupBox:
        box = QGroupBox("基础")
        form = _form(box)
        self.f_suffix = QLineEdit()
        self.f_headless = QCheckBox("无头模式（不显示浏览器窗口）")
        self.f_wait = spinbox(1, 300, 15, digits=4)
        self.f_page_timeout = spinbox(5, 600, 45, digits=4)
        self.f_captcha_retry = spinbox(0, 20, 3, digits=3)
        self.f_captcha_strategy = _combo(
            [(0, "0 — 全自动"),
             (1, "1 — 手动过验证码，其余自动"),
             (2, "2 — 验证码后交人工，不跑 OAuth")], 0)
        self.f_batch = spinbox(1, 100000, 300)

        form.addRow(_lbl("邮箱后缀"), self.f_suffix)
        form.addRow(_lbl(""), self.f_headless)
        form.addRow(_lbl("填表节奏基准(秒)"), self.f_wait)
        form.addRow(_lbl("页面打开超时（秒）"), self.f_page_timeout)
        form.addRow(_lbl("验证码额外重试"), self.f_captcha_retry)
        form.addRow(_lbl("验证码策略"), self.f_captcha_strategy)
        form.addRow(_lbl("单批成功上限"), self.f_batch)
        form.addRow(hint_label(
            "有头模式在 Linux 上需要 xvfb；Windows 桌面环境可直接使用。"))
        return box

    def _build_proxy(self) -> QGroupBox:
        box = QGroupBox("代理")
        form = _form(box)
        self.f_proxy_mode = _combo(
            [("single", "single — 单端口"), ("multiple", "multiple — 端口池")], "single")
        self.f_proxy_type = _combo([("http", "HTTP"), ("socks5", "SOCKS5")], "http")
        self.f_proxy_host = QLineEdit()
        self.f_proxy_host.setPlaceholderText("留空 = 直连不走代理")
        self.f_single_port = spinbox(0, 65535, 0, digits=5)
        self.f_port_start = spinbox(0, 65535, 0, digits=5)
        self.f_port_end = spinbox(0, 65535, 0, digits=5)
        self.f_max_per = spinbox(1, 10000, 20, digits=4)

        self.btn_check_proxy = button("连通检查")
        self.btn_check_proxy.clicked.connect(self._on_check_proxy)
        self.proxy_status = StatusLine()

        form.addRow(_lbl("模式"), self.f_proxy_mode)
        form.addRow(_lbl("协议"), self.f_proxy_type)
        form.addRow(_lbl("主机"), self.f_proxy_host)
        form.addRow(_lbl("单端口"), self.f_single_port)
        form.addRow(_lbl("起始端口"), self.f_port_start)
        form.addRow(_lbl("结束端口"), self.f_port_end)
        form.addRow(_lbl("每端口最多选中"), self.f_max_per)
        form.addRow(_lbl(""), self.btn_check_proxy)
        form.addRow(self.proxy_status)
        return box

    def _build_oauth(self) -> QGroupBox:
        box = QGroupBox("OAuth2")
        form = _form(box)
        self.f_oauth_enabled = QCheckBox("启用 OAuth2（获取 refresh_token）")
        self.f_client_id = QLineEdit()
        self.f_client_id.setProperty("role", "mono")
        self.f_redirect = QLineEdit()
        self.f_scopes = QLineEdit()

        form.addRow(_lbl(""), self.f_oauth_enabled)
        form.addRow(_lbl("Client ID"), self.f_client_id)
        form.addRow(_lbl("Redirect URL"), self.f_redirect)
        form.addRow(_lbl("Scopes（逗号分隔）"), self.f_scopes)
        form.addRow(hint_label("关闭时注册成功即计成功，不再拉取 token。"))
        return box

    def _build_browser(self) -> QGroupBox:
        box = QGroupBox("浏览器")
        form = _form(box)
        self.f_fp_enabled = QCheckBox("启用指纹伪装")
        self.f_fp_platform = _combo(
            [("windows", "Windows"), ("macos", "macOS"), ("linux", "Linux"),
             ("android", "Android"), ("ios", "iOS")], "windows")
        self.f_fp_brand = _combo(
            [("Chrome", "Chrome"), ("Edge", "Edge"),
             ("Firefox", "Firefox"), ("Safari", "Safari")], "Chrome")
        self.f_browser_exe = QLineEdit()
        self.f_browser_exe.setPlaceholderText("留空 = 用内置 Chromium")

        form.addRow(_lbl(""), self.f_fp_enabled)
        form.addRow(_lbl("指纹平台"), self.f_fp_platform)
        form.addRow(_lbl("指纹品牌"), self.f_fp_brand)
        form.addRow(_lbl("自定义内核路径"), self.f_browser_exe)
        form.addRow(hint_label(
            "指纹伪装改写 Canvas/WebGL/UA 等特征，降低自动化识别。<br>"
            "自定义内核可指向 fingerprint-chromium 的 chrome.exe。"))
        return box

    def _build_temp_mail(self) -> QGroupBox:
        box = QGroupBox("临时邮箱（辅助邮箱绑定）")
        form = _form(box)
        self.f_tm_enabled = QCheckBox("启用自动绑定辅助邮箱")
        self.f_tm_type = _combo(
            [("cloud_mail", "cloud_mail"), ("cf_temp_mail", "CF Temp Mail")],
            "cloud_mail")
        self.f_tm_url = QLineEdit()
        self.f_tm_admin = QLineEdit()
        self.f_tm_pass = QLineEdit()
        self.f_tm_pass.setEchoMode(QLineEdit.Password)
        self.f_tm_domain = QLineEdit()
        self.f_tm_prefix = QLineEdit()
        self.f_tm_timeout = spinbox(10, 900, 120, digits=4)
        self.f_tm_poll = spinbox(1, 60, 3, digits=3)

        form.addRow(_lbl(""), self.f_tm_enabled)
        form.addRow(_lbl("类型"), self.f_tm_type)
        form.addRow(_lbl("API 地址"), self.f_tm_url)
        form.addRow(_lbl("管理员邮箱"), self.f_tm_admin)
        form.addRow(_lbl("管理员密码"), self.f_tm_pass)
        form.addRow(_lbl("域名"), self.f_tm_domain)
        form.addRow(_lbl("本地部分前缀"), self.f_tm_prefix)
        form.addRow(_lbl("验证码超时（秒）"), self.f_tm_timeout)
        form.addRow(_lbl("轮询间隔（秒）"), self.f_tm_poll)
        form.addRow(hint_label(
            "仅在微软弹出「让我们来保护你的帐户」时使用。关闭则走跳过逻辑。"))
        return box

    def _build_resin(self) -> QGroupBox:
        box = QGroupBox("Resin 粘性代理池")
        form = _form(box)
        self.f_resin_enabled = QCheckBox("启用 Resin")
        self.f_resin_url = QLineEdit()
        self.f_resin_url.setPlaceholderText("http://127.0.0.1:2260/my-token")
        self.f_resin_platform = QLineEdit()

        self.btn_test_resin = button("测试连接与粘性")
        self.btn_test_resin.clicked.connect(self._on_test_resin)
        self.resin_status = StatusLine()

        form.addRow(_lbl(""), self.f_resin_enabled)
        form.addRow(_lbl("URL（含 Token）"), self.f_resin_url)
        form.addRow(_lbl("Platform"), self.f_resin_platform)
        form.addRow(_lbl(""), self.btn_test_resin)
        form.addRow(self.resin_status)
        form.addRow(hint_label(
            "启用后浏览器与 OAuth 都走 Resin 粘性 IP，Account 取邮箱前缀。"))
        return box

    def _build_manager(self) -> QGroupBox:
        box = QGroupBox("Outlook Manager 对接")
        form = _form(box)
        self.f_om_enabled = QCheckBox("注册成功后自动推送")
        self.f_om_url = QLineEdit()
        self.f_om_url.setPlaceholderText("http://IP:18327/api/v1/ingest/accounts")
        self.f_om_key = QLineEdit()
        self.f_om_key.setEchoMode(QLineEdit.Password)
        self.f_om_key.setPlaceholderText("omk_xxx")

        self.btn_test_om = button("测试连接")
        self.btn_push_om = button("手动推送")
        self.btn_test_om.clicked.connect(self._on_test_manager)
        self.btn_push_om.clicked.connect(self._on_push_manager)
        self.om_status = StatusLine()

        form.addRow(_lbl(""), self.f_om_enabled)
        form.addRow(_lbl("API 地址"), self.f_om_url)
        form.addRow(_lbl("API Key"), self.f_om_key)
        form.addRow(_lbl(""), toolbar(self.btn_test_om, self.btn_push_om))
        form.addRow(self.om_status)
        return box

    def _build_update(self) -> QGroupBox:
        box = QGroupBox("更新与代理池")
        form = _form(box)
        self.f_upd_use_proxy = QCheckBox("检查更新时复用注册代理")
        self.f_upd_proxy = QLineEdit()
        self.f_upd_proxy.setPlaceholderText("留空则按上面的选项自动决定")
        self.f_upd_token = QLineEdit()
        self.f_upd_token.setEchoMode(QLineEdit.Password)
        self.f_upd_token.setPlaceholderText("仓库为私有时才需要")

        self.f_pp_enabled = QCheckBox("启动时拉起外部代理池")
        self.f_pp_exe = QLineEdit()
        self.f_pp_exe.setPlaceholderText("easy_proxies.exe 完整路径")
        self.f_pp_config = QLineEdit()
        self.f_pp_port = spinbox(0, 65535, 9091, digits=5)

        form.addRow(_lbl(""), self.f_upd_use_proxy)
        form.addRow(_lbl("更新专用代理"), self.f_upd_proxy)
        form.addRow(_lbl("GitHub Token"), self.f_upd_token)
        form.addRow(_lbl(""), self.f_pp_enabled)
        form.addRow(_lbl("代理池程序"), self.f_pp_exe)
        form.addRow(_lbl("代理池配置"), self.f_pp_config)
        form.addRow(_lbl("代理池管理端口"), self.f_pp_port)
        form.addRow(hint_label(
            "GitHub API 在部分网络下不通，可指定代理。<br>"
            "代理池由外部程序提供，仅在源码模式的一键启动脚本中使用。"))
        return box

    # ---------- 载入 / 保存 ----------
    def reload(self) -> None:
        cfg = core.load_config()
        if cfg.get("_error"):
            self.status.show_result(
                {"ok": False, "detail": f"配置读取失败: {cfg['_error']}"})
            return

        p = cfg.get("proxy") or {}
        o = cfg.get("oauth2") or {}
        b = cfg.get("browser") or {}
        t = cfg.get("temp_mail") or {}
        r = cfg.get("resin") or {}
        om = cfg.get("outlook_manager") or {}
        u = cfg.get("update") or {}
        pp = cfg.get("proxy_pool") or {}

        def _set_combo(box: QComboBox, value) -> None:
            index = box.findData(value)
            if index >= 0:
                box.setCurrentIndex(index)

        self.f_suffix.setText(cfg.get("email_suffix") or "@outlook.com")
        self.f_headless.setChecked(bool(cfg.get("headless")))
        self.f_wait.setValue(int(cfg.get("bot_protection_wait") or 15))
        self.f_page_timeout.setValue(int(cfg.get("page_open_timeout") or 45))
        self.f_captcha_retry.setValue(int(cfg.get("max_captcha_retries") or 0))
        _set_combo(self.f_captcha_strategy, int(cfg.get("captcha_strategy") or 0))
        self.f_batch.setValue(int(cfg.get("batch_success_limit") or 300))

        _set_combo(self.f_proxy_mode, p.get("mode") or "single")
        _set_combo(self.f_proxy_type, p.get("type") or "http")
        self.f_proxy_host.setText(p.get("host") or "")
        self.f_single_port.setValue(int(p.get("single_port") or 0))
        self.f_port_start.setValue(int(p.get("port_start") or 0))
        self.f_port_end.setValue(int(p.get("port_end") or 0))
        self.f_max_per.setValue(int(p.get("max_per_proxy") or 20))

        self.f_oauth_enabled.setChecked(bool(o.get("enable_oauth2", True)))
        self.f_client_id.setText(o.get("client_id") or "")
        self.f_redirect.setText(o.get("redirect_url") or "http://localhost")
        self.f_scopes.setText(", ".join(o.get("Scopes") or []))

        self.f_fp_enabled.setChecked(bool(b.get("fingerprint_enabled")))
        _set_combo(self.f_fp_platform, b.get("fingerprint_platform") or "windows")
        _set_combo(self.f_fp_brand, b.get("fingerprint_brand") or "Chrome")
        self.f_browser_exe.setText(b.get("executable_path") or "")

        self.f_tm_enabled.setChecked(bool(t.get("enabled")))
        _set_combo(self.f_tm_type, t.get("type") or "cloud_mail")
        self.f_tm_url.setText(t.get("base_url") or "")
        self.f_tm_admin.setText(t.get("admin_email") or "")
        self.f_tm_pass.setText(t.get("admin_password") or "")
        self.f_tm_domain.setText(t.get("domain") or "")
        self.f_tm_prefix.setText(t.get("name_prefix") or "")
        self.f_tm_timeout.setValue(int(t.get("code_timeout") or 120))
        self.f_tm_poll.setValue(int(t.get("poll_interval") or 3))

        self.f_resin_enabled.setChecked(bool(r.get("enabled")))
        self.f_resin_url.setText(r.get("url") or "")
        self.f_resin_platform.setText(r.get("platform") or "Default")

        self.f_om_enabled.setChecked(bool(om.get("enabled")))
        self.f_om_url.setText(om.get("api_url") or "")
        self.f_om_key.setText(om.get("api_key") or "")

        self.f_upd_use_proxy.setChecked(bool(u.get("use_register_proxy", True)))
        self.f_upd_proxy.setText(u.get("proxy") or "")
        self.f_upd_token.setText(u.get("github_token") or "")

        self.f_pp_enabled.setChecked(bool(pp.get("enabled")))
        self.f_pp_exe.setText(pp.get("exe_path") or "")
        self.f_pp_config.setText(pp.get("config_path") or "")
        self.f_pp_port.setValue(int(pp.get("manage_port") or 9091))

    def _collect(self) -> Dict[str, Any]:
        prefix = self.f_tm_prefix.text().strip()
        return {
            "email_suffix": self.f_suffix.text().strip() or "@outlook.com",
            "headless": self.f_headless.isChecked(),
            "bot_protection_wait": self.f_wait.value(),
            "page_open_timeout": self.f_page_timeout.value(),
            "max_captcha_retries": self.f_captcha_retry.value(),
            "captcha_strategy": self.f_captcha_strategy.currentData(),
            "batch_success_limit": self.f_batch.value(),
            "proxy": {
                "mode": self.f_proxy_mode.currentData(),
                "type": self.f_proxy_type.currentData(),
                "host": self.f_proxy_host.text().strip(),
                "single_port": self.f_single_port.value(),
                "port_start": self.f_port_start.value(),
                "port_end": self.f_port_end.value(),
                "max_per_proxy": self.f_max_per.value(),
            },
            "oauth2": {
                "enable_oauth2": self.f_oauth_enabled.isChecked(),
                "client_id": self.f_client_id.text().strip(),
                "redirect_url": self.f_redirect.text().strip() or "http://localhost",
                "Scopes": [s.strip() for s in self.f_scopes.text().split(",") if s.strip()],
            },
            "browser": {
                "fingerprint_enabled": self.f_fp_enabled.isChecked(),
                "fingerprint_platform": self.f_fp_platform.currentData(),
                "fingerprint_brand": self.f_fp_brand.currentData(),
                "executable_path": self.f_browser_exe.text().strip(),
            },
            "temp_mail": {
                "enabled": self.f_tm_enabled.isChecked(),
                "type": self.f_tm_type.currentData(),
                "base_url": self.f_tm_url.text().strip(),
                "admin_email": self.f_tm_admin.text().strip(),
                "admin_password": self.f_tm_pass.text(),
                "domain": self.f_tm_domain.text().strip(),
                "name_prefix": prefix,
                "enable_prefix": bool(prefix),
                "code_timeout": self.f_tm_timeout.value(),
                "poll_interval": self.f_tm_poll.value(),
            },
            "resin": {
                "enabled": self.f_resin_enabled.isChecked(),
                "url": self.f_resin_url.text().strip(),
                "platform": self.f_resin_platform.text().strip() or "Default",
            },
            "outlook_manager": {
                "enabled": self.f_om_enabled.isChecked(),
                "api_url": self.f_om_url.text().strip(),
                "api_key": self.f_om_key.text().strip(),
            },
            "update": {
                "use_register_proxy": self.f_upd_use_proxy.isChecked(),
                "proxy": self.f_upd_proxy.text().strip(),
                "github_token": self.f_upd_token.text().strip(),
            },
            "proxy_pool": {
                "enabled": self.f_pp_enabled.isChecked(),
                "exe_path": self.f_pp_exe.text().strip(),
                "config_path": self.f_pp_config.text().strip(),
                "manage_port": self.f_pp_port.value(),
            },
        }

    def _on_save(self) -> None:
        patch = self._collect()
        proxy = patch["proxy"]
        if proxy["mode"] == "multiple" and proxy["port_end"] < proxy["port_start"]:
            self.status.show_result(
                {"ok": False, "detail": "结束端口不能小于起始端口"})
            return
        try:
            core.merge_config(patch)
        except Exception as exc:
            self.status.show_result({"ok": False, "detail": f"保存失败: {exc}"})
            return
        self.status.show_result(
            {"ok": True, "detail": "配置已保存（下次启动注册生效）"})
        if self._on_saved:
            self._on_saved()

    # ---------- 测试 ----------
    def _on_check_proxy(self) -> None:
        self.btn_check_proxy.setEnabled(False)
        self.proxy_status.show_message("检查中…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_check_proxy.setEnabled(True)
            self.proxy_status.show_result(
                result if isinstance(result, dict) else {"ok": False})

        run_async(core.check_connectivity, done, owner=self)

    def _on_test_resin(self) -> None:
        self.btn_test_resin.setEnabled(False)
        self.resin_status.show_message("测试中（两次请求，约需数秒）…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_test_resin.setEnabled(True)
            self.resin_status.show_result(
                result if isinstance(result, dict) else {"ok": False})

        run_async(core.check_resin, done, owner=self)

    def _on_test_manager(self) -> None:
        self.btn_test_om.setEnabled(False)
        self.om_status.show_message("测试中…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_test_om.setEnabled(True)
            self.om_status.show_result(
                result if isinstance(result, dict) else {"ok": False})

        run_async(core.test_manager_connection, done, owner=self)

    def _on_push_manager(self) -> None:
        self.btn_push_om.setEnabled(False)
        self.om_status.show_message("推送中…", TEXT_DIM)

        def done(result: Any) -> None:
            self.btn_push_om.setEnabled(True)
            self.om_status.show_result(
                result if isinstance(result, dict) else {"ok": False})

        run_async(core.push_to_manager, done, owner=self)

    def update_state(self, snapshot) -> None:
        """运行中禁用保存 —— worker 已读走配置，此时改会让人误以为立即生效。"""
        running = bool((snapshot.get("register") or {}).get("running"))
        self.btn_save.setEnabled(not running)
        self.btn_save.setToolTip("注册运行中，停止后才能保存" if running else "")
