"""业务后端：配置读写、注册进程管理、日志读取、连通性测试、推送。

不依赖 Qt，也不含任何 HTTP —— 桌面 GUI 与 CLI 共用这一层。
原先这些逻辑内嵌在 web_console.py 里，与 HTTP handler 缠在一起；
拆出来后 GUI 直接调函数，不用再自己起个 HTTP 服务绕一圈。

线程约定：
- `_runtime` 的读写都过锁，GUI 主线程与轮询定时器可安全并发访问
- 涉及网络的函数（连通性测试、推送、Resin 测试）会阻塞，
  GUI 必须丢到 QThread 里调，不能在主线程直接调
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import requests

import paths

# ---------------------------------------------------------------- 路径

BASE_DIR = str(paths.APP_DIR)
CONFIG_PATH = str(paths.CONFIG_PATH)
RESULTS_DIR = str(paths.RESULTS_DIR)
OAUTH_FILE = str(paths.OAUTH_FILE)
RECOVERY_FILE = str(paths.RECOVERY_FILE)
LOG_DIR = str(paths.LOG_DIR)
RUN_LOG = str(paths.RUN_LOG)
PUSH_STATE_FILE = str(paths.PUSH_STATE_FILE)


# ---------------------------------------------------------------- 运行时状态

_runtime: Dict[str, Any] = {
    "proc": None,
    "proc_lock": threading.Lock(),
    "task_total": 0,
    "base_oauth_lines": 0,
    "started_at": None,
    "stopping": False,
    "log_pos": 0,
    "log_lock": threading.Lock(),
}


# ---------------------------------------------------------------- 配置

def load_config() -> dict:
    """读 config.json。main.py 允许 // 注释行，这里保持一致。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        lines = [ln for ln in raw.split("\n") if not ln.strip().startswith("//")]
        return json.loads("\n".join(lines))
    except Exception as exc:
        return {"_error": str(exc)}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def merge_config(patch: dict) -> dict:
    """把 patch 合并进现有配置并保存。返回合并后的完整配置。"""
    cfg = load_config()
    cfg.pop("_error", None)
    cfg.update(patch)
    save_config(cfg)
    return cfg


# ---------------------------------------------------------------- 文件

def read_lines(path: str, tail: int = 0) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-tail:] if tail else lines
    except Exception:
        return []


def line_count(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def parse_oauth_results(tail: int = 0) -> List[Dict[str, str]]:
    """解析 oauth2.txt。格式：邮箱----密码----client_id----refresh_token"""
    out = []
    for line in read_lines(OAUTH_FILE, tail):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("----")
        if len(parts) >= 4:
            out.append({
                "email": parts[0].strip(),
                "password": parts[1].strip(),
                "client_id": parts[2].strip(),
                "refresh_token": parts[3].strip(),
            })
    return out


# ---------------------------------------------------------------- 日志

def run_log_tail(max_bytes: int = 1_000_000) -> str:
    """读运行日志尾部，避免全量读取大文件拖慢统计。"""
    try:
        with open(RUN_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def read_log_incremental() -> List[str]:
    """从上次字节位置读新增行。文件被清空/截断时自动重置位置。"""
    with _runtime["log_lock"]:
        pos = _runtime["log_pos"]
        try:
            with open(RUN_LOG, "rb") as f:
                f.seek(pos)
                data = f.read()
                new_pos = f.tell()
        except Exception:
            data = b""
            new_pos = 0
        _runtime["log_pos"] = 0 if new_pos < pos else new_pos
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def reset_log_cursor() -> None:
    with _runtime["log_lock"]:
        _runtime["log_pos"] = 0


def clear_log_and_stats() -> dict:
    """清空运行日志，并把进度统计基准重置到当前结果行数。"""
    try:
        open(RUN_LOG, "w").close()
    except Exception:
        pass
    reset_log_cursor()
    _runtime["base_oauth_lines"] = line_count(OAUTH_FILE)
    return {"ok": True, "detail": "已清空日志与进度统计"}


# ---------------------------------------------------------------- 注册进程

def register_status() -> dict:
    with _runtime["proc_lock"]:
        proc = _runtime["proc"]
        task_total = _runtime["task_total"]
        base = _runtime["base_oauth_lines"]
        started = _runtime["started_at"]
        stopping = _runtime["stopping"]

    if proc is None:
        # 未启动会话：进度清零，不显示历史累计
        success = failed = completed = 0
        percent = 0
    else:
        success = max(0, line_count(OAUTH_FILE) - base)
        failed = run_log_tail().count("[REGISTER][FAIL]")
        completed = success + failed
        percent = min(100, int(completed / task_total * 100)) if task_total > 0 else 0

    if proc is None:
        state, state_text = "waiting", "等待启动"
    elif proc.poll() is None:
        state, state_text = "running", "运行中"
    elif stopping:
        state, state_text = "stopped", "已停止"
    elif proc.returncode == 0:
        state, state_text = "done", "已完成"
    else:
        state, state_text = "error", "异常退出"

    return {
        "state": state,
        "state_text": state_text,
        "task_total": task_total,
        "completed": completed,
        "success": success,
        "failed": failed,
        "percent": percent,
        "started_at": started,
        "running": proc is not None and proc.poll() is None,
        "pid": proc.pid if proc is not None else None,
    }


def register_running() -> bool:
    with _runtime["proc_lock"]:
        proc = _runtime["proc"]
    return proc is not None and proc.poll() is None


def _worker_command() -> List[str]:
    """构造注册子进程命令。

    打包后 sys.executable 就是 OutlookRegister.exe，用 --worker 重入自身；
    源码模式下走 python app.py --worker。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, "-u", os.path.join(BASE_DIR, "app.py"), "--worker"]


def start_register(tasks: int, concurrent: int) -> dict:
    with _runtime["proc_lock"]:
        if _runtime["proc"] is not None and _runtime["proc"].poll() is None:
            return {"ok": False, "detail": "已有注册任务正在运行，请先停止"}

        cfg = load_config()
        if cfg.get("_error"):
            return {"ok": False, "detail": f"配置文件读取失败: {cfg['_error']}"}
        cfg["tasks"] = tasks
        cfg["concurrent_flows"] = concurrent
        save_config(cfg)

        cmd = _worker_command()
        # 启动前清掉可能遗留的停止标志，否则 worker 刚起就自己停了
        try:
            paths.STOP_FLAG.unlink()
        except OSError:
            pass
        # 有头模式在 Linux 上需要 xvfb 虚拟显示器；Windows 有桌面直接跑
        if not cfg.get("headless", True) and os.name != "nt":
            if shutil.which("xvfb-run"):
                cmd = ["xvfb-run", "-a", *cmd]
            else:
                return {"ok": False,
                        "detail": "有头模式需要 xvfb：请先安装 (sudo apt install -y xvfb)，或改回无头模式"}

        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(RUN_LOG, "a", encoding="utf-8", buffering=1)
        logf.write(
            f"\n===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 启动注册 "
            f"tasks={tasks} concurrent={concurrent} "
            f"headless={cfg.get('headless', True)} =====\n"
        )
        # 强制子进程 UTF-8 输出（Windows 默认 GBK，日志会乱码）
        proc_env = dict(os.environ)
        proc_env["PYTHONIOENCODING"] = "utf-8"
        proc_env["PYTHONUTF8"] = "1"

        popen_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            # 独立进程组：停止时才能用 CTRL_BREAK_EVENT 触发 main.py 的 SIGBREAK
            # 处理器（先写汇总再清 profile）。terminate() 是硬杀，清理逻辑不执行。
            # CREATE_NO_WINDOW：GUI 版不能让 worker 弹出黑窗。
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=proc_env,
                **popen_kwargs,
            )
        except Exception as exc:
            return {"ok": False, "detail": f"启动失败: {exc}"}

        _runtime["proc"] = proc
        _runtime["task_total"] = tasks
        _runtime["base_oauth_lines"] = line_count(OAUTH_FILE)
        _runtime["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _runtime["stopping"] = False
        reset_log_cursor()
    return {"ok": True, "detail": "注册已启动"}

def _signal_graceful_stop(proc) -> str:
    """请求 worker 优雅退出。

    主路径是写停止标志文件：worker 有个守护线程在轮询它，发现后会
    interrupt_main() 触发与 Ctrl+C 相同的中断路径（先写汇总再清 profile）。

    为何不用信号：GUI 是 windowed 进程，而 worker 用 CREATE_NO_WINDOW 启动，
    两边不共享控制台，CTRL_BREAK_EVENT 送不到（已实测：os.kill 不报错但
    worker 无任何反应，最后只能超时硬杀，汇总与清理全部丢失）。
    信号仍作为后备手段保留，对命令行启动的 worker 有效。
    """
    try:
        paths.STOP_FLAG.write_text(str(int(time.time())), encoding="utf-8")
        return "stop_flag"
    except Exception:
        pass
    if os.name == "nt":
        try:
            import signal as _signal
            os.kill(proc.pid, _signal.CTRL_BREAK_EVENT)
            return "ctrl_break"
        except Exception:
            pass
    try:
        proc.terminate()
        return "terminate"
    except Exception:
        return "failed"


def stop_register(wait_sec: int = 40) -> dict:
    """请求停止并等待。会阻塞最多 wait_sec + 5 秒，GUI 必须在后台线程调。

    等得长是必要的：worker 退出前要写汇总、关掉所有浏览器、删清 profile
    目录，并发数高时本身就要十几秒。
    """
    with _runtime["proc_lock"]:
        proc = _runtime["proc"]
        if proc is None or proc.poll() is not None:
            return {"ok": False, "detail": "当前没有运行中的注册任务"}
        _runtime["stopping"] = True
        method = _signal_graceful_stop(proc)

    deadline = time.time() + wait_sec
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.5)
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        deadline2 = time.time() + 5
        while time.time() < deadline2 and proc.poll() is None:
            time.sleep(0.3)
    # 无论结果如何都清掉标志，否则下次启动会被旧标志立即中断
    try:
        paths.STOP_FLAG.unlink()
    except OSError:
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": True, "detail": "已强制结束（未能在限时内优雅退出）"}
    return {"ok": True, "detail": f"已停止（{method}，汇总与清理已完成）"}


# ---------------------------------------------------------------- 连通性

def check_connectivity() -> dict:
    cfg = load_config()
    proxy = cfg.get("proxy") or {}
    mode = proxy.get("mode", "single")
    host = (proxy.get("host") or "").strip()
    proxy_type = proxy.get("type", "http")

    # 直连模式：host 为空 → 测本机能否访问外网
    if not host:
        try:
            import urllib.request
            r = urllib.request.urlopen("https://www.gstatic.com/generate_204", timeout=6)
            return {"ok": r.status == 204, "mode": "direct",
                    "detail": "直连模式：本机可访问网络（generate_204）"}
        except Exception as exc:
            return {"ok": False, "mode": "direct",
                    "detail": f"直连模式：网络不通 ({exc.__class__.__name__})"}

    ports: List[int] = []
    if mode == "single":
        p = proxy.get("single_port")
        if p:
            ports = [int(p)]
    else:
        start = int(proxy.get("port_start", 24000) or 24000)
        end = int(proxy.get("port_end", start + 35) or start + 35)
        ports = list(range(start, min(end, start + 9) + 1))

    if not ports:
        return {"ok": False, "detail": "未配置代理端口"}

    def _tcp(h, port, timeout=2.0):
        try:
            with socket.create_connection((h, port), timeout=timeout):
                return True
        except Exception:
            return False

    reachable = [p for p in ports if _tcp(host, p)]
    sample = ", ".join(str(p) for p in ports[:5])
    if mode == "single":
        ok = len(reachable) == 1
        detail = f"端口 {ports[0]} {'可达' if ok else '不可达'}"
    else:
        ok = len(reachable) >= 1
        detail = f"抽查 {len(ports)} 个端口（{sample}...），可达 {len(reachable)} 个"
    return {"ok": ok, "detail": detail, "mode": mode, "host": host, "type": proxy_type}


def check_resin() -> dict:
    """Resin 连通性：同 Account 连续两次请求 ipinfo，验证连通 + 出口 IP 粘性。"""
    cfg = load_config()
    resin = cfg.get("resin") or {}
    if not resin.get("enabled"):
        return {"ok": False, "detail": "Resin 未启用（先勾选启用并保存）"}
    url = (resin.get("url") or "").strip()
    platform = (resin.get("platform") or "Default").strip() or "Default"
    if not url:
        return {"ok": False, "detail": "Resin URL 未配置"}
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        if not u.scheme or not u.netloc:
            return {"ok": False, "detail": f"Resin URL 格式错误: {url}"}
        token = (u.path or "").strip("/").rsplit("/", 1)[-1] if u.path else ""
    except Exception as exc:
        return {"ok": False, "detail": f"Resin URL 解析失败: {exc}"}
    if not token:
        return {"ok": False, "detail": "Resin URL 缺少 Token（格式: http://host:port/token）"}

    account = "test" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    proxy = f"{u.scheme}://{platform}.{account}:{token}@{u.netloc}"
    ips, parts = [], []
    for i in range(2):
        try:
            r = requests.get("https://ipinfo.io/json",
                             proxies={"http": proxy, "https": proxy},
                             timeout=8, headers={"Accept": "application/json"})
            if r.status_code != 200:
                return {"ok": False, "detail": f"Resin 返回 HTTP {r.status_code}"}
            d = r.json()
            ips.append(d.get("ip", "?"))
            parts.append(f"{d.get('ip', '?')} ({d.get('country', '')})")
        except Exception as exc:
            return {"ok": False,
                    "detail": f"第{i + 1}次请求失败: {exc.__class__.__name__}: {exc}"}
    sticky = len(ips) == 2 and ips[0] == ips[1]
    return {
        "ok": True, "sticky": sticky, "account": account, "ip": ips[0],
        "detail": (f"同 Account({account}) 两次出口: {parts[0]} → {parts[1]}；"
                   + ("粘性 OK" if sticky else "IP 变化，粘性异常")),
    }


# ---------------------------------------------------------------- Outlook Manager

def test_manager_connection() -> dict:
    cfg = load_config()
    om = cfg.get("outlook_manager") or {}
    if not om.get("api_url"):
        return {"ok": False, "detail": "请先配置 Outlook Manager 地址"}
    try:
        base = om["api_url"].rsplit("/api/", 1)[0]
        resp = requests.get(f"{base}/api/v1/healthz", timeout=10)
        if resp.status_code == 200:
            return {"ok": True, "detail": "连接成功"}
        return {"ok": False, "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def push_to_manager() -> dict:
    """把 oauth2.txt 中尚未推送的账号推给 outlook-manager。"""
    cfg = load_config()
    om = cfg.get("outlook_manager") or {}
    if not om.get("api_url") or not om.get("api_key"):
        return {"ok": False, "detail": "请先在设置里配置 Outlook Manager 地址和 API Key"}

    lines = read_lines(OAUTH_FILE)
    if not lines:
        return {"ok": True, "pushed": 0, "detail": "没有可推送的账号"}

    last_pushed = 0
    try:
        with open(PUSH_STATE_FILE, "r") as f:
            last_pushed = int(f.read().strip())
    except Exception:
        pass

    if last_pushed >= len(lines):
        return {"ok": True, "pushed": 0, "detail": "没有新账号需要推送"}

    new_accounts = []
    for line in lines[last_pushed:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("----")
        if len(parts) >= 4:
            new_accounts.append({
                "email": parts[0].strip(),
                "password": parts[1].strip(),
                "client_id": parts[2].strip(),
                "refresh_token": parts[3].strip(),
            })

    if not new_accounts:
        return {"ok": True, "pushed": 0, "detail": "没有新账号需要推送"}

    try:
        resp = requests.post(
            om["api_url"], json=new_accounts,
            headers={"X-API-Key": om["api_key"], "Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:
        return {"ok": False, "detail": f"推送失败: {exc}"}

    with open(PUSH_STATE_FILE, "w") as f:
        f.write(str(len(lines)))

    result["ok"] = True
    result["pushed"] = len(new_accounts)
    result.setdefault("detail", f"已推送 {len(new_accounts)} 个账号")
    return result


# ---------------------------------------------------------------- 统计快照

_SKIP_RE = re.compile(r"放弃 (\d+) 个")


def stats_snapshot() -> dict:
    """仪表盘数据。SQLite 那套本项目没有，真相源就是结果文件 + 运行日志。"""
    log_text = run_log_tail()
    success_total = line_count(OAUTH_FILE)
    return {
        "success_total": success_total,
        "recovery_total": line_count(RECOVERY_FILE),
        "record_total": success_total + line_count(RECOVERY_FILE),
        "failed_total": log_text.count("[REGISTER][FAIL]"),
        "skipped_total": sum(int(m.group(1)) for m in _SKIP_RE.finditer(log_text)),
        "register": register_status(),
        "recent": parse_oauth_results(tail=10)[::-1],
    }


def export_file(src: str, dest: str) -> dict:
    """导出结果文件到用户选定路径。"""
    try:
        if not os.path.isfile(src):
            return {"ok": False, "detail": "源文件不存在（还没有注册结果）"}
        shutil.copy2(src, dest)
        return {"ok": True, "detail": f"已导出到 {dest}"}
    except Exception as exc:
        return {"ok": False, "detail": f"导出失败: {exc}"}
