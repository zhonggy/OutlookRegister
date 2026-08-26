"""PyInstaller runtime hook：补齐 windowed 模式下缺失的标准流。

console=False 打包时 PyInstaller 把 sys.stdout / sys.stderr / sys.stdin 置为
None（没有控制台可写）。本项目有两处会因此在启动瞬间就崩：

- controllers/outlook_controller.py 的 write_log_line() 里 print(..., flush=True)
- main.py 的 run() 与各 controller 里大量 print

GUI 进程的输出重定向到 <数据目录>/log/gui.out，不静默丢弃 —— 真出问题时
用户能把这个文件发出来。worker 进程由 GUI 用 Popen 启动且已重定向到
log/web_console_run.log，句柄可用时保持不动，让日志照常落文件。

写文件失败（磁盘满、无权限）退回黑洞，保证程序不会因为写不了日志而起不来。
"""

import io
import os
import sys


class _NullStream(io.TextIOBase):
    """最后兜底：吞掉一切写入，但保持文件对象接口完整。"""

    def write(self, text):
        return len(text) if text else 0

    def flush(self):
        return None

    def isatty(self):
        return False

    def readable(self):
        return False

    def writable(self):
        return True

    def fileno(self):
        raise OSError("no fileno in windowed mode")


def _log_dir():
    """与 paths.py 的 LOG_DIR 保持一致。此处不能 import 业务模块 —— hook
    在任何业务代码之前执行，导入会引发循环。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "log")


def _open_fallback():
    try:
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        # 行缓冲：崩溃时已写内容不至于全丢
        return open(os.path.join(d, "gui.out"), "a", encoding="utf-8",
                    buffering=1, errors="replace")
    except OSError:
        return _NullStream()


_fallback = None


def _ensure(name):
    global _fallback
    if getattr(sys, name, None) is not None:
        return
    if _fallback is None:
        _fallback = _open_fallback()
    setattr(sys, name, _fallback)


_ensure("stdout")
_ensure("stderr")

if getattr(sys, "stdin", None) is None:
    # input() 在 GUI 下不该被调用；给个空流让它抛 EOFError 而非 AttributeError
    sys.stdin = io.StringIO("")
