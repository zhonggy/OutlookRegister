"""视觉主题：配色、字体度量、全局样式表。

为什么要自己算控件高度：Qt 的布局按控件当前字体算 sizeHint，但样式表里
用 `font-size` 改过字号的控件，布局拿到的仍是旧字号的度量 —— 结果 28px
的大数字被裁掉下半截，19px 的中文标题缺一截。所以凡是样式表里放大过
字号的地方，都得显式 setMinimumHeight。

中文还有额外一层：同字号下中文字形比拉丁字母高，且 DPI 缩放会放大差异。
度量探针里刻意混了中文、西文、数字和下伸部字符，取最大包围盒。
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

#: 输入控件最小高度。与样式表里的 min-height + padding + border 对应；
#: 不显式设的话布局会按内容把 QSpinBox 挤到 19px，数字完全看不见。
INPUT_MIN_HEIGHT = 34

# ---------------------------------------------------------------- 配色
# 浅色底。状态色都压暗过 —— 深色主题惯用的亮绿 #3fb950 在白底上对比度
# 只有 2.3:1，远低于 WCAG AA 的 4.5:1，看着发飘。

COLOR_OK = "#166f2f"        # 绿：成功
COLOR_FAIL = "#c62828"      # 红：失败
COLOR_WARN = "#8a5c00"      # 深琥珀：需关注（纯橙在白底不达标）
COLOR_RUNNING = "#0a6e8a"   # 青蓝：进行中
                            # 刻意偏青，与交互蓝 ACCENT 拉开距离，
                            # 否则"运行中"文字和可点按钮同色，用户分不清
COLOR_IDLE = "#5f6b78"      # 灰：未开始

BG = "#f8fafc"              # 主区域背景：柔和浅灰（slate-50）
BG_ALT = "#ffffff"          # 卡片/输入框：纯白，浮在灰底上形成层次
BG_HOVER = "#f1f5f9"        # slate-100
BG_SUNKEN = "#e2e8f0"       # 日志区等内嵌区域（slate-200）

BORDER = "#e2e8f0"          # 卡片描边（slate-200）
BORDER_STRONG = "#cbd5e1"   # 输入框描边（slate-300）

TEXT = "#0f172a"            # slate-900
TEXT_DIM = "#64748b"        # slate-500
TEXT_FAINT = "#94a3b8"      # slate-400

ACCENT = "#2563eb"          # 科技蓝（blue-600）
ACCENT_HOVER = "#1d4ed8"    # blue-700
ACCENT_PRESSED = "#1e40af"  # blue-800
ACCENT_SOFT = "#dbeafe"     # blue-100
ACCENT_TINT = "#eff6ff"     # blue-50：outline 按钮悬停底色

DANGER = "#c62828"
DANGER_HOVER = "#ad1f1f"
DANGER_SOFT = "#fdeaea"

NAV_BG = "#0f172a"          # 侧栏深蓝黑（slate-900），与内容区形成主次
NAV_TEXT = "#94a3b8"
NAV_TEXT_ACTIVE = "#ffffff"
NAV_ACTIVE_BG = "#2563eb"
NAV_HOVER_BG = "#1e293b"    # slate-800

#: 卡片投影。QSS 不支持 box-shadow，用 QGraphicsDropShadowEffect 模拟
#: CSS `0 4px 6px -1px rgba(0,0,0,0.05)` 的效果（略加强以在白底可见）
CARD_SHADOW_BLUR = 14
CARD_SHADOW_OFFSET = (0, 3)
CARD_SHADOW_COLOR = QColor(15, 23, 42, 32)   # slate-900 @ ~12% alpha

#: 聚焦呼吸灯（Focus Ring）。QSS 无法发光，对获得焦点的输入控件
#: 挂一个动态模糊半径的蓝色投影，blur 4↔13px 循环，形成“呼吸”节奏
FOCUS_GLOW_COLOR = QColor(37, 99, 235, 85)   # blue-600
FOCUS_GLOW_MIN = 4.0
FOCUS_GLOW_MAX = 13.0
FOCUS_GLOW_PERIOD_MS = 1500

ROW_ALT = "#fafbfc"
HEADER_BG = "#f0f2f5"

SCROLL_HANDLE = "#c3cad3"
SCROLL_HANDLE_HOVER = "#a3adba"

DISABLED_TEXT = "#a0a8b3"
DISABLED_BG = "#f0f1f3"

MONO_FAMILY = "Consolas, 'Cascadia Mono', 'Courier New', monospace"

#: 注册状态 → 颜色
REGISTER_STATE_COLORS: Dict[str, str] = {
    "waiting": COLOR_IDLE,
    "running": COLOR_RUNNING,
    "stopped": COLOR_WARN,
    "done": COLOR_OK,
    "error": COLOR_FAIL,
}

#: 日志级别 → 颜色
LOG_LEVEL_COLORS: Dict[str, str] = {
    "DEBUG": TEXT_FAINT,
    "INFO": TEXT,
    "OK": COLOR_OK,
    "SUCCESS": COLOR_OK,
    "WARN": COLOR_WARN,
    "WARNING": COLOR_WARN,
    "ERROR": COLOR_FAIL,
    "FAIL": COLOR_FAIL,
}


def register_state_color(state: str) -> str:
    return REGISTER_STATE_COLORS.get((state or "").lower(), TEXT)


def log_level_color(level: str) -> str:
    return LOG_LEVEL_COLORS.get((level or "").upper(), TEXT)


# ---------------------------------------------------------------- 字体度量

#: 度量探针：混中文、西文、数字、下伸部（g/p/q/y），覆盖最大字形范围
_PROBE = "等待验证Ag账号 account@example.com 128.5MB gjpqy"

#: 拿不到 QFontMetrics 时的中文行高保守系数
_CJK_LINE_RATIO = 1.5


def text_height(widget: Optional[QWidget] = None,
                font_size: Optional[int] = None) -> int:
    """一行文字的实际占高（含上下伸部）。

    font_size 传了就按该字号算 —— 这是关键：样式表里放大字号后，
    widget 自身的 font() 还是默认值，直接量会偏小。
    """
    font = QFont(widget.font()) if widget is not None else QFont()
    if font_size:
        font.setPixelSize(font_size)
    try:
        metrics = QFontMetrics(font)
        rect = metrics.boundingRect(_PROBE)
        return max(metrics.height(), rect.height()) + 2
    except Exception:
        base = font_size or font.pixelSize() or 13
        return int(base * _CJK_LINE_RATIO) + 2


def metric_height(widget: Optional[QWidget] = None) -> int:
    """指标卡大数字（28px）的占高。"""
    return text_height(widget, 28) + 4


def fit_spinbox(widget: QWidget, digits: int = 6) -> None:
    """按位数给数字输入框留够宽度。

    右侧上下箭头已经去掉了，所以只留文字内边距的余量。
    """
    try:
        metrics = QFontMetrics(widget.font())
        char_w = metrics.horizontalAdvance("8")
        widget.setMinimumWidth(char_w * digits + 24)
    except Exception:
        widget.setMinimumWidth(90)
    widget.setMinimumHeight(INPUT_MIN_HEIGHT)


def enable_wrap_growth(label: QLabel) -> None:
    """让换行标签的高度真的跟着宽度长。

    Qt 的 QLabel 开了 wordWrap 也不会自动启用 heightForWidth，布局仍按
    单行高度分配 —— 于是两三行的提示文字只能看见第一行。必须把
    sizePolicy 的 heightForWidth 打开。
    """
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setVerticalPolicy(QSizePolicy.MinimumExpanding)
    label.setSizePolicy(policy)


def apply_card_shadow(widget: QWidget) -> None:
    """给卡片/分组框挂投影，模拟 CSS box-shadow。

    只对未挂过 effect 的控件生效，重复调用（例如 refit 被多处触发）不会叠层。
    """
    if widget.graphicsEffect() is not None:
        return
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(CARD_SHADOW_BLUR)
    effect.setOffset(*CARD_SHADOW_OFFSET)
    effect.setColor(CARD_SHADOW_COLOR)
    widget.setGraphicsEffect(effect)


class _FocusGlowFilter(QObject):
    """全局事件过滤器：输入控件获得焦点时挂蓝色呼吸灯投影。

    - QSS 只能改 border 颜色，发不了光；这里用 QGraphicsDropShadowEffect
      的动态 blurRadius 模拟 Focus Ring 呼吸效果
    - QSpinBox / 可编辑 QComboBox 内部的 QLineEdit 会收到 FocusIn，
      对内层编辑器挂光会被外框裁掉，需排除
    - FocusOut 时 setGraphicsEffect(None) 会连动画一起销毁，不需手动 stop
    """

    #: 参与呼吸灯的控件。QPlainTextEdit/QTextEdit 刻意不参与：日志区每追加
    #: 一行都触发重绘，挂上 effect 后每行都要过一遍 pixmap 重渲染，长跑时
    #: 纯属浪费。文本域用 QSS 的 border 变色作聚焦反馈。
    _GLOW_TYPES = (QLineEdit, QComboBox, QAbstractSpinBox)

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._current = None

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        if et == QEvent.Type.FocusIn:
            if isinstance(obj, self._GLOW_TYPES):
                inner = obj.parentWidget()
                if not isinstance(inner, (QAbstractSpinBox, QComboBox)):
                    self._attach(obj)
        elif et == QEvent.Type.FocusOut and obj is self._current:
            self._detach(obj)
        return False

    def _attach(self, widget: QWidget) -> None:
        self._detach(self._current)
        try:
            glow = QGraphicsDropShadowEffect(widget)
            glow.setBlurRadius(FOCUS_GLOW_MIN)
            glow.setOffset(0, 0)
            glow.setColor(FOCUS_GLOW_COLOR)
            widget.setGraphicsEffect(glow)

            anim = QPropertyAnimation(glow, b"blurRadius", glow)
            anim.setStartValue(FOCUS_GLOW_MIN)
            anim.setKeyValueAt(0.5, FOCUS_GLOW_MAX)
            anim.setEndValue(FOCUS_GLOW_MIN)
            anim.setDuration(FOCUS_GLOW_PERIOD_MS)
            anim.setLoopCount(-1)
            anim.start()
        except RuntimeError:
            # 控件正在销毁，放弃本次挂光
            return
        self._current = widget

    def _detach(self, widget) -> None:
        self._current = None
        if widget is None:
            return
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            # 控件已销毁，effect 作为子对象随之销毁，无需处理
            pass


_focus_glow_filter: Optional[_FocusGlowFilter] = None


def install_focus_glow(app: QApplication) -> None:
    global _focus_glow_filter
    if _focus_glow_filter is None:
        _focus_glow_filter = _FocusGlowFilter(app)
        app.installEventFilter(_focus_glow_filter)


def refit_widget_tree(root: QWidget) -> None:
    """样式表应用后重算整棵树的度量。

    样式表是控件构造完才 setStyleSheet 的，此时字号才真正生效；
    不重算，构造期按旧字号定下的 minimumHeight 就是错的。

    字体度量之外还要修两类裁切：
    - QLabel(wordWrap): Qt 默认不开 heightForWidth，换行后高度仍按一行算，
      多行文本只能看到第一行
    - QSpinBox/QLineEdit: 样式表里写 padding 后 Qt 不再用原生 sizeHint，
      内部编辑器会被挤成几像素高
    """
    for widget in root.findChildren(QWidget):
        role = widget.property("role")
        if role == "metric":
            widget.setMinimumHeight(metric_height(widget))
        elif role == "title":
            widget.setMinimumHeight(text_height(widget, 19) + 8)
        elif role in ("hint", "subtitle"):
            widget.setMinimumHeight(text_height(widget) + 4)

    for label in root.findChildren(QLabel):
        if label.wordWrap():
            enable_wrap_growth(label)

    for editor in root.findChildren(QAbstractSpinBox):
        editor.setMinimumHeight(INPUT_MIN_HEIGHT)
    for editor in root.findChildren(QLineEdit):
        # QSpinBox 内部也有个 QLineEdit，别给它设死高度，否则反而错位
        if isinstance(editor.parentWidget(), QAbstractSpinBox):
            continue
        editor.setMinimumHeight(INPUT_MIN_HEIGHT)
    for editor in root.findChildren(QComboBox):
        editor.setMinimumHeight(INPUT_MIN_HEIGHT)

    # 卡片投影：分组框与 role=card 的 QFrame。深色侧栏里的导航列表不需要
    for box in root.findChildren(QGroupBox):
        apply_card_shadow(box)
    for frame in root.findChildren(QFrame):
        if frame.property("role") == "card":
            apply_card_shadow(frame)


# ---------------------------------------------------------------- 样式表

_STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{ background: {BG}; }}

/* ---------- 侧栏导航 ---------- */
QListWidget[role="nav"] {{
    background: {NAV_BG};
    border: none;
    outline: none;
    padding: 8px 0;
}}
/* 全圆角胶囊选中态：item 高约 38px，radius 16px 接近满圆 */
QListWidget[role="nav"]::item {{
    color: {NAV_TEXT};
    padding: 10px 16px;
    border: none;
    margin: 2px 10px;
    border-radius: 16px;
}}
QListWidget[role="nav"]::item:hover {{
    background: {NAV_HOVER_BG};
    color: {NAV_TEXT_ACTIVE};
}}
QListWidget[role="nav"]::item:selected {{
    background: {NAV_ACTIVE_BG};
    color: {NAV_TEXT_ACTIVE};
    font-weight: 600;
}}

QLabel[role="brand"] {{
    color: {NAV_TEXT_ACTIVE};
    background: transparent;
    font-size: 16px;
    font-weight: 600;
}}
QLabel[role="version-pill"] {{
    color: #93c5fd;
    background: rgba(37, 99, 235, 0.18);
    border: 1px solid rgba(59, 130, 246, 0.35);
    border-radius: 9px;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
}}

/* ---------- 文本层级 ---------- */
QLabel[role="title"] {{ font-size: 19px; font-weight: 600; color: {TEXT}; }}
QLabel[role="subtitle"] {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
QLabel[role="hint"] {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel[role="metric"] {{ font-size: 28px; font-weight: 600; }}
QLabel[role="mono"] {{ font-family: {MONO_FAMILY}; }}

/* ---------- 卡片 ---------- */
QFrame[role="card"] {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame[role="separator"] {{ background: {BORDER}; border: none; }}

QGroupBox {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 10px;
    padding: 14px 14px 12px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {TEXT};
    background: {BG};
}}

/* ---------- 按钮 ---------- */
/* 默认按钮 = Outline 描边样式；主行动给 role=primary 实心蓝 */
QPushButton {{
    background: {BG_ALT};
    color: #334155;
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: {ACCENT_TINT};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QPushButton:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {BORDER};
}}

QPushButton[role="primary"] {{
    background: {ACCENT};
    color: #ffffff;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[role="primary"]:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {BORDER};
}}

QPushButton[role="danger"] {{
    background: {DANGER_SOFT};
    color: {DANGER};
    border: 1px solid #e5b3ae;
    font-weight: 600;
}}
QPushButton[role="danger"]:hover {{ background: {DANGER}; color: #ffffff; border-color: {DANGER}; }}
QPushButton[role="danger"]:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {BORDER};
}}

/* ---------- 输入控件 ----------
   文本框 / 数字框 / 下拉框统一形态：同底色、同描边、同圆角、同内边距。 */
QLineEdit, QSpinBox, QComboBox {{
    background: {BG_ALT};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px 9px;
    min-height: 20px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QPlainTextEdit, QTextEdit {{
    background: {BG_ALT};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
}}
QLineEdit[role="mono"] {{ font-family: {MONO_FAMILY}; }}

/* 数字框不要右侧的上下加减按钮，外观和普通文本框一致 */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0;
    height: 0;
    border: none;
    background: transparent;
    subcontrol-position: right;
}}

QComboBox::drop-down {{
    width: 22px;
    border-left: 1px solid {BORDER};
    background: {BG_HOVER};
}}
QComboBox QAbstractItemView {{
    background: {BG_ALT};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    outline: none;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    background: {BG_ALT};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    /* 无图标资源，用内嵌 SVG 画对勾，避免依赖外部文件 */
    image: url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'>\
<path d='M3.5 8.5l3 3 6-7' stroke='white' stroke-width='2' fill='none' \
stroke-linecap='round' stroke-linejoin='round'/></svg>");
}}

/* ---------- 表格 ---------- */
QTableWidget, QTableView {{
    background: {BG_ALT};
    alternate-background-color: {ROW_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {HEADER_BG};
    color: {TEXT};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 7px 9px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QTableCornerButton::section {{ background: {HEADER_BG}; border: none; }}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 20px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}

/* ---------- 日志区 ---------- */
QPlainTextEdit[role="log"] {{
    background: #1e232b;
    color: #d6dce5;
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    font-family: {MONO_FAMILY};
    font-size: 12px;
    padding: 8px;
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {SCROLL_HANDLE};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {SCROLL_HANDLE_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {SCROLL_HANDLE};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {SCROLL_HANDLE_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 状态栏 / 提示 ---------- */
QStatusBar {{
    background: {BG_ALT};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background: #2b3340;
    color: #f0f3f7;
    border: 1px solid {BORDER_STRONG};
    padding: 5px 8px;
}}

QScrollArea {{ border: none; background: {BG}; }}
QScrollArea > QWidget > QWidget {{ background: {BG}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", -1)
    font.setPixelSize(13)
    app.setFont(font)
    app.setStyleSheet(_STYLESHEET)
    # 聚焦呼吸灯：必须在全局样式表之后装，让 border 变色与光晕叠加生效
    install_focus_glow(app)
