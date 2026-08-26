"""更新落地：等旧进程退出 → 覆盖程序文件 → 重启。

为什么不用批处理：
    上一版用 apply.bat，实测在 DETACHED_PROCESS（无控制台）下彻底失效 ——
    `tasklist` 没有任何输出、`timeout` 返回 125 不等待。于是等待循环里
    `tasklist | find "PID"` 永远失败，`|| goto :gone` 立即跳出，
    2 秒就开始 robocopy，而旧 exe 还在运行、DLL 全被锁住，
    结果 _internal 被覆盖成半新半旧，新实例又撞上单实例锁直接退出。

现在的做法：由**新版 exe 自己**（解压在 update_staging/extracted 下，
带完整 _internal，可独立运行）以 --apply-update 模式执行落地。
它运行在 update_staging 里，锁的是那份 _internal，因此可以自由覆盖安装目录。
等待用 WaitForSingleObject，复制用 shutil —— 全是可测试的 Python 逻辑。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: 更新时必须保留的用户数据（相对安装根目录的顶层名字）
PRESERVE_DIRS = ("Results", "log", "browser_profiles", "browsers",
                 "update_staging", "backup_prev")
PRESERVE_FILES = ("config.json", "admin.json", ".push_state",
                  ".stop_request", ".write_probe")

_LOG_LINES: list = []


def _log(message: str, log_path: Path | None = None) -> None:
    line = f"{time.strftime('%H:%M:%S')} {message}"
    _LOG_LINES.append(line)
    print(line, flush=True)
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def wait_for_pid_exit(pid: int, timeout_sec: float = 90.0) -> bool:
    """等指定进程退出。返回 True 表示已退出（或本就不存在）。

    用 OpenProcess + WaitForSingleObject 而非轮询 tasklist：后者在无控制台
    环境下没有输出（已实测），而内核对象等待不受控制台影响。
    """
    if pid <= 0:
        return True
    if os.name != "nt":
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.3)
        return False

    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x0
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        # 打不开句柄：进程已经没了（或无权限，此时也只能当作已退出）
        return True
    try:
        rc = k32.WaitForSingleObject(handle, int(timeout_sec * 1000))
        return rc == WAIT_OBJECT_0
    finally:
        k32.CloseHandle(handle)


def _iter_payload(src: Path):
    """遍历更新包内容，跳过用户数据。产出 (源文件, 相对路径)。"""
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        parts = [] if rel_root == "." else rel_root.split(os.sep)
        top = parts[0] if parts else None

        # 更新包理论上不含用户数据目录，但打包失误时必须挡住
        if top in PRESERVE_DIRS:
            dirs[:] = []
            continue
        if not parts:
            dirs[:] = [d for d in dirs if d not in PRESERVE_DIRS]

        for name in files:
            if not parts and name in PRESERVE_FILES:
                continue
            rel = name if not parts else os.path.join(rel_root, name)
            yield Path(root) / name, Path(rel)


def copy_payload(src: Path, dst: Path, log_path: Path | None = None) -> tuple:
    """把更新包覆盖到安装目录。返回 (成功数, 失败列表)。"""
    copied = 0
    failures = []
    for source, rel in _iter_payload(src):
        target = dst / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        except Exception as exc:
            failures.append(f"{rel}: {exc.__class__.__name__}: {exc}")
    if failures:
        _log(f"[WARN] {len(failures)} 个文件复制失败", log_path)
        for line in failures[:10]:
            _log(f"       {line}", log_path)
    return copied, failures


def backup_current(app_dir: Path, log_path: Path | None = None) -> Path | None:
    """备份当前的 exe 与 _internal，便于覆盖失败时回滚。"""
    backup = app_dir / "backup_prev"
    try:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir(parents=True, exist_ok=True)
        internal = app_dir / "_internal"
        if internal.is_dir():
            shutil.copytree(internal, backup / "_internal", dirs_exist_ok=True)
        for exe in app_dir.glob("*.exe"):
            shutil.copy2(exe, backup / exe.name)
        _log(f"已备份到 {backup}", log_path)
        return backup
    except Exception as exc:
        _log(f"[WARN] 备份失败（继续更新）: {exc}", log_path)
        return None


def restore_backup(app_dir: Path, log_path: Path | None = None) -> bool:
    backup = app_dir / "backup_prev"
    if not backup.is_dir():
        return False
    try:
        internal_bak = backup / "_internal"
        if internal_bak.is_dir():
            shutil.copytree(internal_bak, app_dir / "_internal", dirs_exist_ok=True)
        for exe in backup.glob("*.exe"):
            shutil.copy2(exe, app_dir / exe.name)
        _log("已从备份回滚", log_path)
        return True
    except Exception as exc:
        _log(f"[FAIL] 回滚失败: {exc}", log_path)
        return False


def run(argv: list) -> int:
    """--apply-update <pid> <src> <dst> <exe>

    由旧进程在退出前拉起；此处运行的是解压出来的新版 exe。
    """
    if len(argv) < 4:
        print("[FATAL] --apply-update 参数不足", file=sys.stderr)
        return 2

    try:
        pid = int(argv[0])
    except ValueError:
        pid = 0
    src = Path(argv[1])
    dst = Path(argv[2])
    exe = Path(argv[3])
    log_path = dst / "log" / "update.log"

    _log("=" * 56, log_path)
    _log(f"开始落地更新 pid={pid}", log_path)
    _log(f"  来源: {src}", log_path)
    _log(f"  目标: {dst}", log_path)

    if not src.is_dir():
        _log(f"[FATAL] 更新包目录不存在: {src}", log_path)
        return 1

    _log("等待旧进程退出…", log_path)
    if not wait_for_pid_exit(pid, timeout_sec=90):
        _log("[FATAL] 90 秒内旧进程未退出，放弃更新（未改动任何文件）", log_path)
        _launch(exe, dst, log_path)
        return 1
    _log("旧进程已退出", log_path)
    # 句柄释放略滞后于进程退出，多等一会儿再动文件
    time.sleep(2.0)

    backup_current(dst, log_path)

    copied, failures = copy_payload(src, dst, log_path)
    _log(f"已复制 {copied} 个文件", log_path)

    if failures:
        _log("[FAIL] 存在复制失败，执行回滚", log_path)
        restore_backup(dst, log_path)
        _log("更新未完成，已恢复原版本", log_path)
        _launch(exe, dst, log_path)
        return 1

    _log("更新完成", log_path)
    _launch(exe, dst, log_path)
    return 0


def _launch(exe: Path, cwd: Path, log_path: Path | None = None) -> None:
    """启动安装目录里的 exe。"""
    if not exe.is_file():
        candidates = list(cwd.glob("*.exe"))
        if not candidates:
            _log(f"[FAIL] 找不到可启动的 exe: {exe}", log_path)
            return
        exe = candidates[0]
    try:
        subprocess.Popen(
            [str(exe)],
            cwd=str(cwd),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        _log(f"已启动 {exe}", log_path)
    except Exception as exc:
        _log(f"[FAIL] 启动失败: {exc}", log_path)


def cleanup_staging(app_dir: Path) -> None:
    """清理遗留的 update_staging。

    落地进程自己就跑在 update_staging 里，删不掉自己所在目录，
    因此改由更新后启动的新实例来清。
    """
    stage = app_dir / "update_staging"
    if not stage.is_dir():
        return
    for _ in range(6):
        try:
            shutil.rmtree(stage)
            return
        except OSError:
            # 落地进程可能还没完全退出，等一下重试
            time.sleep(1.0)
