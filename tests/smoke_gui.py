#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 冒烟测试：offscreen 下把界面完整构造一遍。

比等打包完再发现问题快得多 —— 能一次抓出漏收的模块、构造期的 Qt 报错、
以及中文文字被裁切这类布局缺陷。

用法：
    QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONUTF8", "1")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{label} {detail}".strip())


def main() -> int:
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QLabel, QLineEdit,
        QProgressBar, QPushButton, QSpinBox, QWidget, QAbstractSpinBox,
    )

    app = QApplication([])

    from gui.theme import apply_theme
    apply_theme(app)
    print("== 构造 ==")
    check("apply_theme", True)

    from gui.main_window import MainWindow
    window = MainWindow()
    window.resize(1180, 820)
    window.show()
    for _ in range(12):
        app.processEvents()
    check("MainWindow", True)

    import core
    snapshot = core.stats_snapshot()
    for name, page in window._pages.items():
        try:
            page.update_state(snapshot)
            check(f"page {name}", True)
        except Exception as exc:
            check(f"page {name}", False, f"{exc.__class__.__name__}: {exc}")

    print("== 设置页往返 ==")
    window.settings.reload()
    collected = window.settings._collect()
    for key in ("proxy", "oauth2", "browser", "temp_mail", "resin",
                "outlook_manager", "update", "proxy_pool"):
        check(f"config section {key}", key in collected)

    print("== 日志着色 ==")
    reg = window.register
    reg._append_line("[REGISTER][FAIL] fail line")
    reg._append_line("[OAUTH][OK] ok line")
    reg._append_line("[Batch] plain line")
    check("append log lines", reg.log.blockCount() >= 3)

    print("== 更新页状态机 ==")
    window.about._sync_update_state()
    check("about sync", True)

    print("== 布局几何（多分辨率）==")
    TYPES = (QLabel, QPushButton, QSpinBox, QCheckBox, QComboBox,
             QLineEdit, QProgressBar)
    #: QLineEdit 的 sizeHint 宽是"约 17 字符"的理想值，不是硬性下限。
    #: 只在明显过窄（长 URL 基本没法读）时才算缺陷。
    MIN_EDIT_W = 150

    for width, height in ((980, 660), (1180, 820), (1600, 1000)):
        window.resize(width, height)
        for _ in range(12):
            app.processEvents()
        clipped = []
        for row in range(window.nav.count()):
            window.nav.setCurrentRow(row)
            for _ in range(12):
                app.processEvents()
            page_name = window.nav.item(row).text()
            for widget in window.stack.currentWidget().findChildren(QWidget):
                if not isinstance(widget, TYPES) or not widget.isVisible():
                    continue
                # spinbox 内部编辑器由 spinbox 自身管理，不单独判
                if isinstance(widget, QLineEdit) and isinstance(
                        widget.parentWidget(), QAbstractSpinBox):
                    continue
                size = widget.size()
                text = widget.text()[:20] if hasattr(widget, "text") else ""
                if isinstance(widget, QLabel) and widget.wordWrap():
                    need_h = widget.heightForWidth(size.width()) if size.width() > 0 else 0
                else:
                    need_h = widget.sizeHint().height()
                if need_h > 0 and size.height() < need_h - 1:
                    clipped.append(f"[{page_name}] {type(widget).__name__} "
                                   f"H {size.height()}<{need_h} {text!r}")
                if isinstance(widget, (QLineEdit, QComboBox)):
                    if size.width() < MIN_EDIT_W:
                        clipped.append(f"[{page_name}] {type(widget).__name__} "
                                       f"W {size.width()}<{MIN_EDIT_W} {text!r}")
                elif isinstance(widget, QPushButton):
                    need_w = widget.sizeHint().width()
                    if size.width() < need_w - 2:
                        clipped.append(f"[{page_name}] Button "
                                       f"W {size.width()}<{need_w} {text!r}")
        check(f"{width}x{height} 无裁切", not clipped,
              f"({len(clipped)} 处)" if clipped else "")
        for line in clipped[:8]:
            print(f"       {line}")

    print("== 指标卡字号 ==")
    for key, card in window.dashboard.cards.items():
        label = card._value
        need = label.fontMetrics().boundingRect(label.text() or "0").height()
        check(f"metric {key}", label.height() >= need,
              f"h={label.height()} need={need}")

    window.close()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项")
        for line in FAILURES:
            print("  - " + line)
        return 1
    print("GUI 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
