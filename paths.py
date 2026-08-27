"""路径解析：区分「可写数据目录」与「只读资源目录」。

冻结（PyInstaller）后 __file__ 指向解压临时目录（sys._MEIPASS），
不能再用它定位 config.json / Results / log —— 那些必须落在 exe 同级。

    app_dir()      可写数据根：frozen = exe 所在目录，开发 = 项目根
    resource_dir() 只读资源根：frozen = sys._MEIPASS，开发 = 项目根

开发模式下两者相同，因此源码方式运行时行为与改造前完全一致。
"""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

# 本文件位于项目根，开发模式下即项目根目录
_SRC_ROOT = Path(__file__).resolve().parent


def app_dir() -> Path:
    """可写数据根目录（config.json / Results / log / browser_profiles）。"""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return _SRC_ROOT


def resource_dir() -> Path:
    """只读资源根目录（打包进 exe 的静态文件）。"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return _SRC_ROOT


APP_DIR = app_dir()
RESOURCE_DIR = resource_dir()

# ---- 可写数据 ----
CONFIG_PATH = APP_DIR / "config.json"
ADMIN_FILE = APP_DIR / "admin.json"
RESULTS_DIR = APP_DIR / "Results"
OAUTH_FILE = RESULTS_DIR / "oauth2.txt"
RECOVERY_FILE = RESULTS_DIR / "recovery_emails.txt"
LOG_DIR = APP_DIR / "log"
RUN_LOG = LOG_DIR / "web_console_run.log"
#: worker 实时进度快照（JSON）。worker 原子写，GUI 只读。
#: 计数与日志里的 [进度]/[Cumulative] 同源，避免 GUI 用日志文本二次推断。
PROGRESS_FILE = LOG_DIR / "progress.json"
PUSH_STATE_FILE = APP_DIR / ".push_state"
PROFILES_ROOT = APP_DIR / "browser_profiles"
UPDATE_DIR = APP_DIR / "update_staging"
#: 停止请求标志。GUI 创建，worker 轮询到后自行删除并走中断流程。
#: 用文件而不用信号：worker 由 windowed GUI 以 CREATE_NO_WINDOW 启动，
#: 两边不共享控制台，CTRL_BREAK_EVENT 根本送不到。
STOP_FLAG = APP_DIR / ".stop_request"

# ---- 只读资源 ----
# 冻结时打进 _internal/app_data/，开发时就在项目根
NAMES_FILE = RESOURCE_DIR / ("app_data/english_name_generator.txt" if FROZEN
                             else "english_name_generator.txt")
CONFIG_EXAMPLE = RESOURCE_DIR / "config.example.json"
# 内置 Chromium：目录名必须匹配 patchright browsers.json 的 revision
BROWSERS_DIR = RESOURCE_DIR / "browsers"


def ensure_dirs():
    """创建运行时目录（幂等）。"""
    for d in (RESULTS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def check_writable() -> tuple:
    """探测 app_dir 是否可写。返回 (ok, detail)。

    装到 C:\\Program Files 这类受保护目录时，写入会静默失败或抛
    PermissionError，导致「注册成功但结果文件不存在」。启动时先探明。
    """
    probe = APP_DIR / ".write_probe"
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(APP_DIR)
    except Exception as exc:
        return False, f"{APP_DIR} 不可写: {exc}"


def setup_browsers_env():
    """声明内置 Chromium 位置。必须在任何 patchright 导入之前调用。"""
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return os.environ["PLAYWRIGHT_BROWSERS_PATH"]
    if BROWSERS_DIR.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
        return str(BROWSERS_DIR)
    return ""


def browsers_root() -> Path:
    """实际生效的浏览器根目录（环境变量 → 内置目录 → 系统默认）。"""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if env:
        return Path(env)
    if BROWSERS_DIR.is_dir():
        return BROWSERS_DIR
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "ms-playwright" if local else Path.home() / ".cache" / "ms-playwright"


def headless_shell_available() -> bool:
    """是否存在 chromium_headless_shell。

    Playwright ≥1.49 在 headless=True 时默认启动这个独立二进制（~197MB）。
    打包版不带它，需要回退到 channel='chromium' 用完整 Chromium 跑无头。
    """
    root = browsers_root()
    try:
        if not root.is_dir():
            return False
        return any(p.name.startswith("chromium_headless_shell") for p in root.iterdir())
    except Exception:
        return False
