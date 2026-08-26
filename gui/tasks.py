"""把阻塞调用丢到后台线程执行。

core 层里所有涉及网络和等待子进程的函数都会阻塞几秒到几十秒
（连通性测试、Resin 双请求、停止注册最长 35s）。在主线程直接调
会冻住界面，Windows 还会给窗口标题挂上「未响应」。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals):
        super().__init__()
        self._fn = fn
        self._signals = signals

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            self._signals.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        self._signals.done.emit(result)


def run_async(fn: Callable[[], Any],
              on_done: Optional[Callable[[Any], None]] = None,
              on_failed: Optional[Callable[[str], None]] = None,
              owner: Optional[QObject] = None) -> None:
    """在线程池里跑 fn，完成后在主线程回调。

    owner 用于给信号对象挂父级 —— 否则 _Signals 在函数返回后被 GC，
    回调永远不会触发（这类 bug 表现为"点了没反应"，极难查）。
    """
    signals = _Signals(owner)
    if on_done is not None:
        signals.done.connect(on_done)
    if on_failed is not None:
        signals.failed.connect(on_failed)
    elif on_done is not None:
        # 没给失败回调时，把异常也走成功通道，让 UI 至少能显示出错
        signals.failed.connect(lambda msg: on_done({"ok": False, "detail": msg}))
    QThreadPool.globalInstance().start(_Task(fn, signals))
