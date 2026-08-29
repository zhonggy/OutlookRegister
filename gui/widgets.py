"""页面通用组件。

抽出来是为了各页视觉一致，也免得每页重复写 layout 样板。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    TEXT,
    TEXT_DIM,
    enable_wrap_growth,
    fit_spinbox,
    metric_height,
    text_height,
)


# ---------------------------------------------------------------- 文本

def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "title")
    # 19px 中文标题：布局若按默认 13px 算高度会裁掉底部
    label.setMinimumHeight(text_height(label, 19) + 8)
    return label


def subtitle_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    label.setMinimumHeight(text_height(label, 14) + 4)
    return label


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    # 提示文字常换行；wordWrap 单独不够 —— 还要开 heightForWidth，
    # 否则布局按单行高分配，多行文字只看得见第一行
    enable_wrap_growth(label)
    return label


def mono_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "mono")
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


# ---------------------------------------------------------------- 容器

def card() -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    return frame


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("role", "separator")
    line.setFixedHeight(1)
    return line


def toolbar(*widgets: QWidget, stretch_at: Optional[int] = None) -> QWidget:
    """一行工具栏。stretch_at 指定在第几个控件之后插入弹簧。"""
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget)
        if stretch_at is not None and index == stretch_at:
            layout.addStretch(1)
    if stretch_at is None:
        layout.addStretch(1)
    return host


# ---------------------------------------------------------------- 控件

def button(text: str, role: str = "") -> QPushButton:
    btn = QPushButton(text)
    if role:
        btn.setProperty("role", role)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class PlainSpinBox(QSpinBox):
    """纯手输的数字框：没有箭头按钮，滚轮和上下键也不改值。

    只留键盘直接输入这一条改值路径 —— 滚轮误触和方向键误碰都不会
    偷偷改掉参数。范围校验还是交给 QSpinBox 自己做。
    """

    _BLOCKED_KEYS = (
        Qt.Key_Up,
        Qt.Key_Down,
        Qt.Key_PageUp,
        Qt.Key_PageDown,
    )

    def __init__(self) -> None:
        super().__init__()
        self.setButtonSymbols(QSpinBox.NoButtons)
        # 默认是 WheelFocus：鼠标滚轮经过就能抢焦点，改成 StrongFocus
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.key() in self._BLOCKED_KEYS:
            event.ignore()
            return
        super().keyPressEvent(event)

    def stepBy(self, steps: int) -> None:  # noqa: N802 - Qt 命名
        # stepUp()/stepDown() 以及其它内部步进入口一并封掉
        return


def spinbox(minimum: int, maximum: int, value: int, digits: int = 6) -> QSpinBox:
    box = PlainSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    fit_spinbox(box, digits)
    return box


class MetricCard(QFrame):
    """指标卡：大数字 + 说明。

    大数字 28px，中文/数字实际占高约 36-40px（还受 DPI 缩放影响），
    所以显式设最小高度 —— 否则布局按默认字号算，数字被裁掉下半截。
    """

    def __init__(self, caption: str, value: str = "-", color: str = TEXT):
        super().__init__()
        self.setProperty("role", "card")
        self.setMinimumWidth(130)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self._value = QLabel(str(value))
        self._value.setProperty("role", "metric")
        self._value.setStyleSheet(f"color: {color};")
        self._value.setMinimumHeight(metric_height(self._value))

        self._caption = QLabel(caption)
        self._caption.setProperty("role", "hint")
        self._caption.setMinimumHeight(text_height(self._caption) + 4)
        self._caption.setWordWrap(True)

        layout.addWidget(self._value)
        layout.addWidget(self._caption)

    def set_value(self, value, color: Optional[str] = None) -> None:
        self._value.setText(str(value))
        if color:
            self._value.setStyleSheet(f"color: {color};")


class KeyValueRow(QWidget):
    """左键右值一行。

    elide=True 用于长路径：超宽时中间省略并挂 tooltip，比换行成三行整齐。
    默认换行，适合错误信息这类需要读全的内容。
    """

    def __init__(self, key: str, value: str = "-", elide: bool = False,
                 key_width: int = 108):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(8)

        self._elide = elide
        self._full_text = str(value)
        line = text_height(self) + 4

        self._key = QLabel(key)
        self._key.setStyleSheet(f"color: {TEXT_DIM};")
        self._key.setMinimumWidth(key_width)
        self._key.setMinimumHeight(line)
        self._key.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._value = QLabel(str(value))
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._value.setMinimumHeight(line)
        if elide:
            self._value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        else:
            self._value.setWordWrap(True)
            enable_wrap_growth(self._value)

        layout.addWidget(self._key)
        layout.addWidget(self._value, 1)

    def set_value(self, value, color: Optional[str] = None) -> None:
        self._full_text = str(value)
        if self._elide:
            self._apply_elide()
        else:
            self._value.setText(self._full_text)
        self._value.setToolTip(self._full_text if self._elide else "")
        if color:
            self._value.setStyleSheet(f"color: {color};")

    def _apply_elide(self) -> None:
        from PySide6.QtGui import QFontMetrics
        width = max(60, self._value.width())
        metrics = QFontMetrics(self._value.font())
        self._value.setText(
            metrics.elidedText(self._full_text, Qt.ElideMiddle, width)
        )

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._elide:
            self._apply_elide()


class StatusLine(QLabel):
    """操作反馈行。几秒后自动清空，避免旧消息一直留着让人误判。"""

    def __init__(self, timeout_ms: int = 6000):
        super().__init__("")
        self.setWordWrap(True)
        enable_wrap_growth(self)
        self.setMinimumHeight(text_height(self) + 4)
        self._timeout_ms = timeout_ms
        self._timer = None

    def show_message(self, text: str, color: str = TEXT_DIM) -> None:
        from PySide6.QtCore import QTimer
        self.setText(text)
        self.setStyleSheet(f"color: {color};")
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(lambda: self.setText(""))
        self._timer.start(self._timeout_ms)

    def show_result(self, result: dict) -> None:
        """直接吃 core 层的 {ok, detail} 返回。"""
        from .theme import COLOR_FAIL, COLOR_OK
        ok = bool(result.get("ok"))
        self.show_message(
            str(result.get("detail") or ("成功" if ok else "失败")),
            COLOR_OK if ok else COLOR_FAIL,
        )


# ---------------------------------------------------------------- 对话

def confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    yes = box.button(QMessageBox.Yes)
    no = box.button(QMessageBox.No)
    yes.setText("确定")
    no.setText("取消")
    return box.exec() == QMessageBox.Yes


def warn(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)
