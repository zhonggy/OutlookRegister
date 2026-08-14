#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OutlookRegister Web Console

单文件 Web 控制台：管理 OutlookRegister 注册机。
  - 首次访问网页时创建管理员账号 + 密码
  - 仪表盘：成功账号 / 总记录
  - 启动注册：任务参数（注册数量、并发数）、注册进度、实时日志、开始/停止/连通检查
  - 系统设置：可视化编辑 config.json

用法:
  python web_console.py            # 默认 127.0.0.1:9090
  python web_console.py --host 0.0.0.0 --port 9090
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
OAUTH_FILE = os.path.join(RESULTS_DIR, "oauth2.txt")
RECOVERY_FILE = os.path.join(RESULTS_DIR, "recovery_emails.txt")
ADMIN_FILE = os.path.join(BASE_DIR, "admin.json")
LOG_DIR = os.path.join(BASE_DIR, "log")
RUN_LOG = os.path.join(LOG_DIR, "web_console_run.log")

HOST = "127.0.0.1"
PORT = 9090

# ---------------------------------------------------------------- runtime

_runtime = {
    "proc": None,
    "proc_lock": threading.Lock(),
    "task_total": 0,
    "base_oauth_lines": 0,
    "started_at": None,
    "stopping": False,
    "log_offset": 0,
    "log_pos": 0,
    "log_lock": threading.Lock(),
}

_sessions = {}  # token -> expiry
_sessions_lock = threading.Lock()
SESSION_TTL = 30 * 24 * 3600


# ---------------------------------------------------------------- auth

def _hash_password(password: str, salt_hex: str = "") -> tuple:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex(), dk.hex()


def _load_admin():
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_admin(username: str, salt_hex: str, hash_hex: str):
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": username, "salt": salt_hex, "hash": hash_hex}, f, indent=2)
    try:
        os.chmod(ADMIN_FILE, 0o600)
    except Exception:
        pass


def _verify_admin(username: str, password: str) -> bool:
    a = _load_admin()
    if not a or not username or not password:
        return False
    if a.get("username") != username:
        return False
    salt, h = _hash_password(password, a.get("salt", ""))
    return hmac.compare_digest(h, a.get("hash", ""))


def _new_session() -> str:
    token = secrets.token_hex(32)
    with _sessions_lock:
        _sessions[token] = time.time() + SESSION_TTL
    return token


def _valid_session(token: str) -> bool:
    if not token:
        return False
    with _sessions_lock:
        exp = _sessions.get(token)
        if exp is None:
            return False
        if time.time() > exp:
            _sessions.pop(token, None)
            return False
        return True


# ---------------------------------------------------------------- helpers

def _read_lines(path: str, tail: int = 0):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-tail:] if tail else lines
    except Exception:
        return []


def _line_count(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        # main.py 允许 // 注释行
        lines = [ln for ln in raw.split("\n") if not ln.strip().startswith("//")]
        return json.loads("\n".join(lines))
    except Exception as e:
        return {"_error": str(e)}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _run_log_tail(max_bytes: int = 1_000_000) -> str:
    """读运行日志尾部（默认最多 1MB），避免全量读取大文件拖慢统计。"""
    try:
        with open(RUN_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _read_log_incremental() -> list:
    """从上次字节位置读日志新增行（增量，避免每次读全文件）。"""
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
        # 文件被清空/截断时重置位置
        if new_pos < pos:
            _runtime["log_pos"] = 0
        else:
            _runtime["log_pos"] = new_pos
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _clear_log_and_stats() -> dict:
    """清空运行日志文件，并重置进度统计基准（失败/成功从 0 重新计数）。"""
    try:
        open(RUN_LOG, "w").close()
    except Exception:
        pass
    with _runtime["log_lock"]:
        _runtime["log_offset"] = 0
        _runtime["log_pos"] = 0
    _runtime["base_oauth_lines"] = _line_count(OAUTH_FILE)
    return {"message": "已清空日志与进度统计"}


def _register_status() -> dict:
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
        success = max(0, _line_count(OAUTH_FILE) - base)
        log_text = _run_log_tail()
        failed = log_text.count("[REGISTER][FAIL]")
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
    }


def _check_connectivity() -> dict:
    cfg = _load_config()
    proxy = cfg.get("proxy") or {}
    mode = proxy.get("mode", "single")
    host = (proxy.get("host") or "").strip()
    proxy_type = proxy.get("type", "http")

    # 直连模式：host 为空 → 直接测本机能否访问目标站
    if not host:
        try:
            import urllib.request
            r = urllib.request.urlopen(
                "https://www.gstatic.com/generate_204", timeout=6)
            return {"ok": r.status == 204, "detail": "直连模式：本机可访问网络（generate_204）", "mode": "direct"}
        except Exception as e:
            return {"ok": False, "detail": f"直连模式：网络不通 ({e.__class__.__name__})", "mode": "direct"}

    ports = []
    if mode == "single":
        p = proxy.get("single_port")
        if p:
            ports = [int(p)]
    else:
        start = int(proxy.get("port_start", 24000))
        end = int(proxy.get("port_end", start + 35))
        ports = list(range(start, min(end, start + 9) + 1))

    def _tcp(host, port, timeout=2.0):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    if not ports:
        return {"ok": False, "detail": "config.json 未配置代理端口"}
    reachable = [p for p in ports if _tcp(host, p)]
    sample = ", ".join(str(p) for p in ports[:5])
    if mode == "single":
        ok = len(reachable) == 1
        detail = f"端口 {ports[0]} {'可达' if ok else '不可达'}"
    else:
        ok = len(reachable) >= 1
        detail = f"抽查 {len(ports)} 个端口（{sample}...），可达 {len(reachable)} 个"
    return {"ok": ok, "detail": detail, "mode": mode, "host": host, "type": proxy_type}


# ---------------------------------------------------------------- actions

def _start_register(tasks: int, concurrent: int) -> str:
    with _runtime["proc_lock"]:
        if _runtime["proc"] is not None and _runtime["proc"].poll() is None:
            return "已有注册任务正在运行，请先停止"

        cfg = _load_config()
        cfg["tasks"] = tasks
        cfg["concurrent_flows"] = concurrent
        _save_config(cfg)

        # 有头模式（headless=false）在 Linux 上需要 xvfb 虚拟显示器
        # 本地 Windows 有桌面则直接跑
        cmd = [sys.executable, "-u", "main.py"]
        if not cfg.get("headless", True) and os.name != "nt":
            if shutil.which("xvfb-run"):
                cmd = ["xvfb-run", "-a", *cmd]
            else:
                return "有头模式需要 xvfb：请先安装 (sudo apt install -y xvfb)，或改回无头模式"

        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(RUN_LOG, "a", encoding="utf-8", buffering=1)
        logf.write(f"\n===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] 启动注册 tasks={tasks} concurrent={concurrent} headless={cfg.get('headless', True)} =====\n")
        # 强制子进程以 UTF-8 输出（Windows 默认 GBK，会导致日志乱码）
        proc_env = dict(os.environ)
        proc_env["PYTHONIOENCODING"] = "utf-8"
        proc_env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=proc_env,
        )
        _runtime["proc"] = proc
        _runtime["task_total"] = tasks
        _runtime["base_oauth_lines"] = _line_count(OAUTH_FILE)
        _runtime["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _runtime["stopping"] = False
        with _runtime["log_lock"]:
            _runtime["log_offset"] = 0
            _runtime["log_pos"] = 0
    return "ok"


def _stop_register() -> str:
    with _runtime["proc_lock"]:
        proc = _runtime["proc"]
        if proc is None or proc.poll() is not None:
            return "当前没有运行中的注册任务"
        _runtime["stopping"] = True
        try:
            proc.terminate()
        except Exception:
            pass
    # 等待优雅退出（main.py 有 SIGTERM 处理），最多 15s 后强杀
    deadline = time.time() + 15
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.5)
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    return "ok"


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "ORConsole/1.0"

    # ---- helpers ----
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, filename):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            return self._send_json({"error": "文件不存在或暂无数据"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _token(self):
        # 优先 Authorization: Bearer <token>
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):].strip()
        # 兼容 Cookie
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("or_token="):
                return part[len("or_token="):]
        return ""

    def _authed(self) -> bool:
        return _valid_session(self._token())

    # ---- routes ----
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            return self._send_page(PAGE)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/state":
            return self._send_json({
                "configured": _load_admin() is not None,
                "authed": self._authed(),
                "username": (_load_admin() or {}).get("username", "") if self._authed() else "",
            })
        if path == "/api/dashboard":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            recent = []
            for line in _read_lines(OAUTH_FILE, 10):
                parts = line.strip().split("----")
                if len(parts) >= 4:
                    recent.append({"email": parts[0], "token": parts[3][:24] + "..."})
            # 失败 / 跳过：从运行日志累计统计
            log_text = _run_log_tail()
            failed = log_text.count("[REGISTER][FAIL]")
            skipped = sum(int(m.group(1)) for m in re.finditer(r"放弃 (\d+) 个", log_text))
            return self._send_json({
                "success": _line_count(OAUTH_FILE),
                "total": _line_count(OAUTH_FILE) + _line_count(RECOVERY_FILE),
                "recovery": _line_count(RECOVERY_FILE),
                "failed": failed,
                "skipped": skipped,
                "recent": recent,
            })
        if path == "/api/config":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_json(_load_config())
        if path == "/api/export/oauth2":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_file(OAUTH_FILE, "oauth2.txt")
        if path == "/api/export/recovery":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_file(RECOVERY_FILE, "recovery_emails.txt")
        if path == "/api/register/status":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_json(_register_status())
        if path == "/api/logs":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            # 增量读取（服务端维护字节位置，前端无需传 offset）
            new_lines = _read_log_incremental()
            return self._send_json({"lines": new_lines, "offset": 0})
        if path == "/api/logs/full":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_json({"text": _run_log_tail()})
        if path == "/api/logs/clear":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_json(self._clear_log_and_stats())
        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._read_json()

        if path == "/api/setup":
            if _load_admin() is not None:
                return self._send_json({"error": "管理员已创建，禁止重复初始化"}, 403)
            username = (data.get("username") or "").strip()
            password = data.get("password") or ""
            if not username or len(username) < 3 or len(username) > 32:
                return self._send_json({"error": "账号需为 3-32 位"}, 400)
            if len(password) < 6:
                return self._send_json({"error": "密码至少 6 位"}, 400)
            salt, h = _hash_password(password)
            _save_admin(username, salt, h)
            return self._send_json({"message": "管理员已创建", "token": _new_session()})

        if path == "/api/login":
            username = (data.get("username") or "").strip()
            password = data.get("password") or ""
            if not _verify_admin(username, password):
                time.sleep(0.3)
                return self._send_json({"error": "账号或密码错误"}, 401)
            return self._send_json({"message": "登录成功", "token": _new_session()})

        if path == "/api/logout":
            with _sessions_lock:
                _sessions.pop(self._token(), None)
            return self._send_json({"message": "已退出"})

        if not self._authed():
            return self._send_json({"error": "未登录"}, 401)

        if path == "/api/config":
            cfg = _load_config()
            cfg.update(data)
            _save_config(cfg)
            return self._send_json({"message": "配置已保存"})

        if path == "/api/register/start":
            try:
                tasks = max(1, int(data.get("tasks", 1)))
                concurrent = max(1, int(data.get("concurrent_flows", 1)))
            except Exception:
                return self._send_json({"error": "参数格式错误"}, 400)
            msg = _start_register(tasks, concurrent)
            if msg != "ok":
                return self._send_json({"error": msg}, 400)
            return self._send_json({"message": "注册已启动"})

        if path == "/api/register/stop":
            msg = _stop_register()
            if msg != "ok":
                return self._send_json({"error": msg}, 400)
            return self._send_json({"message": "已请求停止"})

        if path == "/api/register/check":
            return self._send_json(_check_connectivity())

        if path == "/api/logs/clear":
            if not self._authed():
                return self._send_json({"error": "未登录"}, 401)
            return self._send_json(_clear_log_and_stats())

        return self._send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


# ---------------------------------------------------------------- page

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Outlook 注册机控制台</title>
<style>
:root{
  --bg:#f4f6fa; --panel:#ffffff; --panel2:#eef1f6; --border:#e3e8f0;
  --text:#1f2430; --muted:#6b7280; --accent:#3b82f6; --accent2:#2f6fe0;
  --green:#16a34a; --red:#dc2626; --amber:#d97706;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;font-size:14px}
button{font-family:inherit}
input,select{background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px 12px;font-size:14px;outline:none;width:100%}
input:focus,select:focus{border-color:var(--accent)}
input[type=checkbox]{width:auto}
label{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}
.btn{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:14px;cursor:pointer;transition:.15s}
.btn:hover{background:var(--accent2)}
.btn.ghost{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn.ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn.danger{background:var(--red)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn.sm{padding:6px 12px;font-size:13px}

/* 登录/首次设置 */
.auth-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center}
.auth-card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:38px 36px;width:380px}
.auth-card h1{font-size:20px;margin-bottom:6px}
.auth-card .sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.auth-card .field{margin-bottom:16px}
.status{min-height:20px;font-size:13px;margin:10px 0}
.status.err{color:var(--red)} .status.ok{color:var(--green)}
.auth-switch{margin-top:16px;text-align:center;color:var(--muted);font-size:13px}

/* 主界面 */
.layout{display:flex;min-height:100vh}
aside{width:210px;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;position:fixed;top:0;bottom:0}
.logo{padding:22px 20px;border-bottom:1px solid var(--border)}
.logo h1{font-size:16px}
.logo p{color:var(--muted);font-size:12px;margin-top:4px}
nav{flex:1;padding:14px 10px}
nav .item{display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:10px;cursor:pointer;color:var(--muted);margin-bottom:4px;transition:.15s}
nav .item:hover{background:var(--panel2);color:var(--text)}
nav .item.active{background:var(--accent);color:#fff}
nav .item .ico{width:18px;height:18px;flex-shrink:0}
aside .foot{padding:16px 20px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
aside .foot .user{font-size:13px;color:var(--muted)}
main{flex:1;margin-left:210px;padding:28px 32px}
.page-title{font-size:20px;font-weight:600;margin-bottom:4px}
.page-desc{color:var(--muted);font-size:13px;margin-bottom:24px}

/* 卡片 */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px;align-items:stretch}
.grid2 .card{min-height:232px;display:flex;flex-direction:column}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:18px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:20px}
.card h3{font-size:15px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.metric{display:flex;flex-direction:column;justify-content:center}
.metric .lab{color:var(--muted);font-size:45px;font-weight:600;margin-bottom:6px}
.metric .num{font-size:34px;font-weight:700}
.metric .sub{color:var(--muted);font-size:13px;margin-top:10px}
.metric.green .num{color:var(--green)}
.metric.blue .num{color:var(--accent)}

/* 表格 */
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);text-align:left;padding:9px 10px;border-bottom:1px solid var(--border);font-weight:500}
td{padding:9px 10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.mono{font-family:Consolas,monospace;font-size:12px}

/* 任务参数 */
.row{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}
.row .field{flex:1;min-width:150px}
.actions{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}

/* 进度 */
.progress-state{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.pill{background:var(--panel2);border:1px solid var(--border);border-radius:20px;padding:5px 14px;font-size:13px}
.pill.running{color:var(--green);border-color:var(--green)}
.bar{height:12px;background:var(--panel2);border-radius:8px;overflow:hidden;margin-bottom:12px}
.bar>div{height:100%;background:linear-gradient(90deg,var(--accent),#7ab3ff);border-radius:8px;transition:width .4s;width:0%}
.progress-meta{display:flex;gap:24px;color:var(--muted);font-size:13px}
.progress-meta b{color:var(--text);font-size:16px;margin-left:4px}
.progress-meta .ok b{color:var(--green)} .progress-meta .fail b{color:var(--red)}

/* 日志 */
.log-box{background:#ffffff;border:1px solid var(--border);border-radius:10px;height:380px;overflow-y:auto;padding:14px;font-family:Consolas,monospace;font-size:12px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#1f2430}
.log-box .dim{color:#9ca3af}
.log-box .ok{color:var(--green)} .log-box .fail{color:var(--red)} .log-box .warn{color:var(--amber)}

/* 设置表单 */
.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.settings-grid .card{grid-column:auto}
.settings-grid .full{grid-column:1/-1}
.field{margin-bottom:14px}
.hint{color:var(--muted);font-size:12px;margin-top:4px}
.hidden{display:none}
.chk-row{display:flex;align-items:center;gap:8px}
.chk-row input{width:auto}
</style>
</head>
<body>

<!-- ============ 登录 / 首次设置 ============ -->
<div id="authView" class="auth-wrap hidden">
  <div class="auth-card">
    <h1 id="authTitle">登录</h1>
    <p class="sub" id="authSub">输入管理员账号和密码</p>
    <div class="field"><label>管理员账号</label><input id="auUser" type="text" autocomplete="username" placeholder="请输入账号"></div>
    <div class="field"><label>管理密码</label><input id="auPass" type="password" autocomplete="current-password" placeholder="请输入密码"></div>
    <div id="auPass2Wrap" class="field hidden"><label>确认密码</label><input id="auPass2" type="password" autocomplete="new-password" placeholder="再次输入密码"></div>
    <p class="status" id="auStatus"></p>
    <button class="btn" id="auBtn" style="width:100%" onclick="authSubmit()">登录</button>
  </div>
</div>

<!-- ============ 主界面 ============ -->
<div id="appView" class="layout hidden">
  <aside>
    <div class="logo"><h1>🎯 Outlook 注册机</h1><p>Web 控制台</p></div>
    <nav>
      <div class="item active" data-page="dashboard" onclick="go('dashboard')">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        仪表盘
      </div>
      <div class="item" data-page="register" onclick="go('register')">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>
        启动注册
      </div>
      <div class="item" data-page="settings" onclick="go('settings')">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        系统设置
      </div>
    </nav>
    <div class="foot">
      <span class="user" id="curUser"></span>
      <button class="btn ghost sm" onclick="logout()">退出</button>
    </div>
  </aside>
  <main id="main"></main>
</div>

<script>
const $=id=>document.getElementById(id);
let TOKEN='', PAGE='dashboard', logOffset=0, pollTimer=null, statusTimer=null;

async function api(path,opt={}){
  const headers={...(opt.headers||{})};
  if(opt.body!==undefined)headers['Content-Type']='application/json';
  if(TOKEN)headers['Authorization']='Bearer '+TOKEN;
  const res=await fetch(path,{...opt,headers});
  let data={};
  try{data=await res.json()}catch(e){}
  if(!res.ok){const err=new Error(data.error||res.statusText);err.status=res.status;throw err}
  return data;
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function setStatus(el,msg,type){el.textContent=msg||'';el.className='status '+(type||'')}

/* ---------- 认证 ---------- */
async function checkAuth(){
  try{
    const st=await api('/api/state');
    if(!st.authed){showAuth(st.configured?'login':'setup');return false}
    TOKEN=localStorage.getItem('or_token')||'';
    $('appView').classList.remove('hidden');
    $('authView').classList.add('hidden');
    $('curUser').textContent=st.username||'';
    initApp();
    return true;
  }catch(e){showAuth('login');return false}
}
function showAuth(mode){
  $('appView').classList.add('hidden');
  $('authView').classList.remove('hidden');
  const setup=mode==='setup';
  $('authTitle').textContent=setup?'首次部署配置':'登录';
  $('authSub').textContent=setup?'创建管理员账号和密码以保护控制台':(TOKEN?'登录已过期，请重新登录':'输入管理员账号和密码');
  $('auPass2Wrap').classList.toggle('hidden',!setup);
  $('auBtn').textContent=setup?'创建并进入':'登录';
  setStatus($('auStatus'),'');
}
async function authSubmit(){
  const user=$('auUser').value.trim(),pass=$('auPass').value,pass2=$('auPass2').value;
  const setup=!$('auPass2Wrap').classList.contains('hidden');
  if(!user){setStatus($('auStatus'),'请输入账号','err');return}
  if(!pass){setStatus($('auStatus'),'请输入密码','err');return}
  if(setup&&pass!==pass2){setStatus($('auStatus'),'两次输入的密码不一致','err');return}
  try{
    const r=setup?await api('/api/setup',{method:'POST',body:JSON.stringify({username:user,password:pass})})
                 :await api('/api/login',{method:'POST',body:JSON.stringify({username:user,password:pass})});
    TOKEN=r.token;localStorage.setItem('or_token',TOKEN);
    $('auUser').value='';$('auPass').value='';$('auPass2').value='';
    await checkAuth();
  }catch(e){setStatus($('auStatus'),e.message,'err')}
}
async function logout(){
  try{await api('/api/logout',{method:'POST'})}catch(e){}
  TOKEN='';localStorage.removeItem('or_token');
  showAuth('login');
}

/* ---------- 导航 ---------- */
function go(page){
  PAGE=page;
  document.querySelectorAll('nav .item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  renderPage();
}
function initApp(){
  go('dashboard');
  statusTimer=setInterval(async()=>{
    if(PAGE==='register')await refreshProgress();
  },2000);
}

/* ---------- 仪表盘 ---------- */
async function renderPage(){
  const main=$('main');
  if(PAGE==='dashboard')return renderDashboard(main);
  if(PAGE==='register')return renderRegister(main);
  if(PAGE==='settings')return renderSettings(main);
}
async function renderDashboard(main){
  let d={success:0,total:0,recent:[],failed:0,skipped:0};
  try{d=await api('/api/dashboard')}catch(e){}
  main.innerHTML=`
    <div class="page-title">仪表盘</div>
    <div class="page-desc">注册成果总览</div>
    <div class="grid3">
      <div class="card metric green">
        <div class="lab">成功账号</div>
        <div class="num">${d.success}</div>
        <div class="sub">成功记录 ${d.success} 条</div>
      </div>
      <div class="card metric blue">
        <div class="lab">总记录</div>
        <div class="num">${d.total}</div>
        <div class="sub">失败 ${d.failed} · 跳过 ${d.skipped}</div>
      </div>
    </div>
    <div class="card">
      <h3>最近成功记录</h3>
      <table>
        <tr><th>邮箱</th><th>Refresh Token</th></tr>
        ${d.recent.length?d.recent.map(r=>`<tr><td>${esc(r.email)}</td><td class="mono">${esc(r.token)}</td></tr>`).join(''):'<tr><td colspan="2" style="color:var(--muted)">暂无记录</td></tr>'}
      </table>
    </div>
    <div class="card" style="margin-top:18px">
      <h3>下载成果</h3>
      <div class="actions">
        <button class="btn" onclick="downloadExport('/api/export/oauth2','oauth2.txt')">下载 oauth2.txt</button>
        <button class="btn ghost" onclick="downloadExport('/api/export/recovery','recovery_emails.txt')">下载 recovery_emails.txt</button>
        <span class="status" id="dlStatus" style="display:inline-flex;align-items:center"></span>
      </div>
    </div>`;
}
async function downloadExport(path,filename){
  const st=$('dlStatus');
  if(st){st.textContent='下载中...';st.className='status'}
  try{
    const res=await fetch(path,{headers:{'Authorization':'Bearer '+TOKEN}});
    if(!res.ok){const d=await res.json().catch(()=>({}));throw new Error(d.error||'下载失败')}
    const blob=await res.blob();
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},500);
    if(st){st.textContent='已下载 ✓';st.className='status ok'}
  }catch(e){
    if(st){st.textContent=e.message;st.className='status err'}
  }
}

/* ---------- 启动注册 ---------- */
async function renderRegister(main){
  let st={state:'waiting',state_text:'等待启动',task_total:0,completed:0,success:0,failed:0,percent:0};
  try{st=await api('/api/register/status')}catch(e){}
  main.innerHTML=`
    <div class="page-title">启动注册</div>
    <div class="page-desc">配置任务参数并启动注册，实时查看进度与日志</div>
    <div class="grid2" style="margin-bottom:18px">
      <div class="card">
        <h3>任务参数</h3>
      <div class="row">
        <div class="field"><label>注册数量</label><input id="inTasks" type="number" min="1" value="${st.task_total||5}"></div>
        <div class="field"><label>并发数</label><input id="inConc" type="number" min="1" value="1"></div>
      </div>
      <div class="actions">
        <button class="btn" id="btnStart" onclick="startReg()">开始注册</button>
        <button class="btn danger" id="btnStop" onclick="stopReg()">停止</button>
        <button class="btn ghost" id="btnCheck" onclick="checkConn()">连通检查</button>
        <span class="status" id="actStatus" style="display:inline-flex;align-items:center"></span>
      </div>
    </div>
    <div class="card" style="margin-bottom:18px">
      <h3>注册进度</h3>
      <div class="progress-state">
        <span class="pill" id="progPill">${esc(st.state_text)}</span>
        <span class="mono" id="progFrac">0/${st.task_total||1}</span>
      </div>
      <div class="bar"><div id="progBar" style="width:${st.percent}%"></div></div>
      <div class="progress-meta">
        <span class="ok">已完成 <b id="progDone">${st.completed}</b></span>
        <span class="ok">成功 <b id="progOk">${st.success}</b></span>
        <span class="fail">失败 <b id="progFail">${st.failed}</b></span>
      </div>
    </div>
    </div>
    <div class="card">
      <h3>实时日志 <button class="btn ghost sm" onclick="clearLogView()">清空日志与进度</button></h3>
      <div class="log-box" id="logBox"><span class="dim">等待日志输出...</span></div>
    </div>`;
  logOffset=0;
  logLines=[];
  if(pollTimer)clearInterval(pollTimer);
  pollTimer=setInterval(async()=>{
    try{
      const r=await api('/api/logs');
      if(r.lines&&r.lines.length){
        appendLog(r.lines.join('\n'));
      }
    }catch(e){}
  },1000);
  await refreshProgress();
}
let logLines=[]; // 日志行缓存，最多保留 100 行，防止页面卡顿
function appendLog(text){
  const box=$('logBox');
  if(!box)return;
  const first=box.querySelector('.dim');
  if(first)first.remove();
  const rows=String(text).split(/\r?\n/);
  for(const raw of rows){
    if(raw==='')continue;
    const div=document.createElement('div');
    div.innerHTML=colorize(raw);
    box.appendChild(div);
    logLines.push(div);
  }
  // 只保留最近 100 行
  while(logLines.length>100){
    const old=logLines.shift();
    if(old&&old.parentNode)old.parentNode.removeChild(old);
  }
  box.scrollTop=box.scrollHeight;
}
function colorize(raw){
  let s=esc(raw);
  s=s.replace(/\[OK\]/g,'<span class="ok">[OK]</span>');
  s=s.replace(/(\[FAIL\]|失败)/g,'<span class="fail">$1</span>');
  s=s.replace(/(\[WARN\]|警告)/g,'<span class="warn">$1</span>');
  return s;
}
async function clearLogView(){
  // 清空日志文件 + 重置统计基准（后端）
  try{await api('/api/logs/clear',{method:'POST'})}catch(e){}
  // 清空日志显示
  const box=$('logBox');
  if(box)box.innerHTML='<span class="dim">等待日志输出...</span>';
  logLines=[];
  // 重置进度 UI
  const pill=$('progPill'); if(pill){pill.textContent='等待启动';pill.className='pill'}
  const bar=$('progBar'); if(bar)bar.style.width='0%';
  if($('progFrac'))$('progFrac').textContent='0/0';
  if($('progDone'))$('progDone').textContent='0';
  if($('progOk'))$('progOk').textContent='0';
  if($('progFail'))$('progFail').textContent='0';
}
async function refreshProgress(){
  try{
    const st=await api('/api/register/status');
    const pill=$('progPill'),bar=$('progBar');
    if(!pill)return;
    pill.textContent=st.state_text;
    pill.className='pill'+(st.state==='running'?' running':'');
    bar.style.width=st.percent+'%';
    $('progFrac').textContent=st.completed+'/'+(st.task_total||1);
    $('progDone').textContent=st.completed;
    $('progOk').textContent=st.success;
    $('progFail').textContent=st.failed;
    const running=st.running;
    const bs=$('btnStart'),bt=$('btnStop');
    if(bs)bs.disabled=running;
    if(bt)bt.disabled=!running;
  }catch(e){}
}
async function startReg(){
  const tasks=parseInt($('inTasks').value)||1;
  const conc=parseInt($('inConc').value)||1;
  try{
    await api('/api/register/start',{method:'POST',body:JSON.stringify({tasks,concurrent_flows:conc})});
    setStatus($('actStatus'),'注册已启动','ok');
    await refreshProgress();
  }catch(e){setStatus($('actStatus'),e.message,'err')}
}
async function stopReg(){
  try{
    await api('/api/register/stop',{method:'POST'});
    setStatus($('actStatus'),'已请求停止','ok');
    await refreshProgress();
  }catch(e){setStatus($('actStatus'),e.message,'err')}
}
async function checkConn(){
  setStatus($('actStatus'),'正在检查连通性...');
  try{
    const r=await api('/api/register/check',{method:'POST'});
    setStatus($('actStatus'),(r.ok?'✅ ':'❌ ')+r.detail,r.ok?'ok':'err');
  }catch(e){setStatus($('actStatus'),'检查失败: '+e.message,'err')}
}

/* ---------- 系统设置 ---------- */
async function renderSettings(main){
  let cfg={};
  try{cfg=await api('/api/config')}catch(e){}
  const p=cfg.proxy||{},o=cfg.oauth2||{},t=cfg.temp_mail||{},b=cfg.browser||{};
  main.innerHTML=`
    <div class="page-title">系统设置</div>
    <div class="page-desc">可视化编辑 config.json，保存后下次启动注册生效</div>
    <div class="settings-grid">
      <div class="card">
        <h3>基础</h3>
        <div class="field"><label>邮箱后缀</label><input id="cfSuffix" value="${esc(cfg.email_suffix||'@outlook.com')}"></div>
        <label class="chk-row"><input id="cfHeadless" type="checkbox" ${cfg.headless?'checked':''}><div><strong>无头模式</strong><div class="hint">勾选=无头（推荐）；取消勾选=有头，Linux 上自动用 xvfb 虚拟显示（需已装 xvfb）</div></div></label>
        <div class="field"><label>机器人防护等待（秒）</label><input id="cfWait" type="number" value="${cfg.bot_protection_wait??15}"></div>
        <div class="field"><label>页面打开超时（秒）</label><input id="cfPageTimeout" type="number" value="${cfg.page_open_timeout??30}" placeholder="默认 30"></div>
        <div class="field"><label>最大验证码重试</label><input id="cfCapRetry" type="number" value="${cfg.max_captcha_retries??3}"></div>
        <div class="field"><label>验证码策略</label><select id="cfCapStrategy">
          <option value="0" ${cfg.captcha_strategy===0?'selected':''}>策略 0</option>
          <option value="1" ${cfg.captcha_strategy===1?'selected':''}>策略 1</option>
        </select></div>
        <div class="field"><label>批成功上限</label><input id="cfBatch" type="number" value="${cfg.batch_success_limit??300}"></div>
      </div>
      <div class="card">
        <h3>代理</h3>
        <div class="field"><label>模式</label><select id="cfProxyMode">
          <option value="single" ${p.mode==='single'?'selected':''}>single（单端口）</option>
          <option value="multiple" ${p.mode==='multiple'?'selected':''}>multiple（端口池）</option>
        </select></div>
        <div class="field"><label>类型</label><select id="cfProxyType">
          <option value="http" ${(p.type||'http')==='http'?'selected':''}>HTTP</option>
          <option value="socks5" ${p.type==='socks5'?'selected':''}>SOCKS5</option>
        </select></div>
        <div class="field"><label>主机（留空 = 直连不走代理）</label><input id="cfProxyHost" value="${esc(p.host||'')}" placeholder="留空则 VPS 直连"></div>
        <div class="field"><label>单端口（single 模式）</label><input id="cfSinglePort" type="number" value="${p.single_port??0}"></div>
        <div class="field"><label>起始端口（multiple 模式）</label><input id="cfPortStart" type="number" value="${p.port_start??24000}"></div>
        <div class="field"><label>结束端口（multiple 模式）</label><input id="cfPortEnd" type="number" value="${p.port_end??24035}"></div>
        <div class="field"><label>每端口最大并发</label><input id="cfMaxPer" type="number" value="${p.max_per_proxy??5}"></div>
      </div>
      <div class="card">
        <h3>OAuth2</h3>
        <label class="chk-row"><input id="cfOauthEn" type="checkbox" ${o.enable_oauth2?'checked':''}><div><strong>启用 OAuth2</strong></div></label>
        <div class="field"><label>Client ID</label><input id="cfClientId" value="${esc(o.client_id||'')}"></div>
        <div class="field"><label>Redirect URL</label><input id="cfRedirect" value="${esc(o.redirect_url||'http://localhost')}"></div>
        <div class="field"><label>Scopes（逗号分隔）</label><input id="cfScopes" value="${esc((o.Scopes||[]).join(', '))}"></div>
      </div>
      <div class="card">
        <h3>浏览器</h3>
        <label class="chk-row"><input id="cfFpEn" type="checkbox" ${b.fingerprint_enabled?'checked':''}><div><strong>启用浏览器指纹</strong><span class="hint" style="display:block">patchright 指纹伪装 Canvas/WebGL/UA 等，降低自动化识别</span></div></label>
        <div class="field"><label>指纹平台</label><select id="cfFpPlatform">
          <option value="windows" ${(b.fingerprint_platform||'windows')==='windows'?'selected':''}>Windows</option>
          <option value="macos" ${b.fingerprint_platform==='macos'?'selected':''}>macOS</option>
          <option value="linux" ${b.fingerprint_platform==='linux'?'selected':''}>Linux</option>
          <option value="android" ${b.fingerprint_platform==='android'?'selected':''}>Android</option>
          <option value="ios" ${b.fingerprint_platform==='ios'?'selected':''}>iOS</option>
        </select></div>
        <div class="field"><label>指纹品牌</label><select id="cfFpBrand">
          <option value="Chrome" ${(b.fingerprint_brand||'Chrome')==='Chrome'?'selected':''}>Chrome</option>
          <option value="Edge" ${b.fingerprint_brand==='Edge'?'selected':''}>Edge</option>
          <option value="Firefox" ${b.fingerprint_brand==='Firefox'?'selected':''}>Firefox</option>
          <option value="Safari" ${b.fingerprint_brand==='Safari'?'selected':''}>Safari</option>
        </select></div>
      </div>
      <div class="card">
        <h3>临时邮箱</h3>
        <label class="chk-row"><input id="cfTmEn" type="checkbox" ${t.enabled?'checked':''}><div><strong>启用临时邮箱</strong></div></label>
        <div class="field"><label>类型</label><select id="cfTmType">
          <option value="cloud_mail" ${(t.type||'cloud_mail')==='cloud_mail'?'selected':''}>cloud_mail</option>
          <option value="cf_temp_mail" ${t.type==='cf_temp_mail'?'selected':''}>CF Temp Mail</option>
        </select></div>
        <div class="field"><label>API 地址</label><input id="cfTmUrl" value="${esc(t.base_url||'')}"></div>
        <div class="field"><label>管理员邮箱</label><input id="cfTmAdmin" value="${esc(t.admin_email||'')}"></div>
        <div class="field"><label>管理员密码</label><input id="cfTmPass" type="password" value="${esc(t.admin_password||'')}"></div>
        <div class="field"><label>域名</label><input id="cfTmDomain" value="${esc(t.domain||'')}"></div>
        <div class="field"><label>前缀（跟随 Outlook 前缀，这里备用）</label><input id="cfTmPrefix" value="${esc(t.name_prefix||'')}"></div>
        <div class="field"><label>验证码超时（秒）</label><input id="cfTmTimeout" type="number" value="${t.code_timeout??120}"></div>
        <div class="field"><label>轮询间隔（秒）</label><input id="cfTmPoll" type="number" value="${t.poll_interval??3}"></div>
      </div>
    </div>
    <div class="actions" style="margin-top:18px">
      <button class="btn" onclick="saveSettings()">保存配置</button>
      <span class="status" id="cfgStatus" style="display:inline-flex;align-items:center"></span>
    </div>`;
}
async function saveSettings(){
  const q=v=>$('cfgStatus')&&v;
  const payload={
    email_suffix:$('cfSuffix').value.trim(),
    headless:$('cfHeadless').checked,
    bot_protection_wait:parseInt($('cfWait').value)||15,
    page_open_timeout:parseInt($('cfPageTimeout').value)||30,
    max_captcha_retries:parseInt($('cfCapRetry').value)||3,
    captcha_strategy:parseInt($('cfCapStrategy').value)||0,
    batch_success_limit:parseInt($('cfBatch').value)||300,
    proxy:{
      mode:$('cfProxyMode').value,
      type:$('cfProxyType').value,
      host:$('cfProxyHost').value.trim(),
      single_port:parseInt($('cfSinglePort').value)||0,
      port_start:parseInt($('cfPortStart').value)||24000,
      port_end:parseInt($('cfPortEnd').value)||24035,
      max_per_proxy:parseInt($('cfMaxPer').value)||5,
    },
    oauth2:{
      enable_oauth2:$('cfOauthEn').checked,
      client_id:$('cfClientId').value.trim(),
      redirect_url:$('cfRedirect').value.trim(),
      Scopes:$('cfScopes').value.split(',').map(s=>s.trim()).filter(Boolean),
    },
    temp_mail:{
      enabled:$('cfTmEn').checked,
      type:$('cfTmType').value,
      base_url:$('cfTmUrl').value.trim(),
      admin_email:$('cfTmAdmin').value.trim(),
      admin_password:$('cfTmPass').value,
      domain:$('cfTmDomain').value.trim(),
      name_prefix:$('cfTmPrefix').value.trim(),
      enable_prefix:true,
      code_timeout:parseInt($('cfTmTimeout').value)||120,
      poll_interval:parseInt($('cfTmPoll').value)||3,
    },
    browser:{
      fingerprint_enabled:$('cfFpEn').checked,
      fingerprint_platform:$('cfFpPlatform').value,
      fingerprint_brand:$('cfFpBrand').value,
    },
  };
  try{
    await api('/api/config',{method:'POST',body:JSON.stringify(payload)});
    setStatus($('cfgStatus'),'配置已保存 ✓','ok');
  }catch(e){setStatus($('cfgStatus'),e.message,'err')}
}

/* ---------- 启动 ---------- */
(async function boot(){
  if(localStorage.getItem('or_token'))TOKEN=localStorage.getItem('or_token');
  await checkAuth();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- main

def main():
    global HOST, PORT
    ap = argparse.ArgumentParser(description="OutlookRegister Web Console")
    ap.add_argument("--host", default=HOST, help="监听地址 (默认 127.0.0.1)")
    ap.add_argument("--port", type=int, default=PORT, help="监听端口 (默认 9090)")
    args = ap.parse_args()
    HOST, PORT = args.host, args.port

    os.makedirs(LOG_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"OutlookRegister Web Console: http://{HOST}:{PORT}")
    print(f"配置文件: {CONFIG_PATH}")
    print("首次访问请在网页上创建管理员账号和密码。Ctrl+C 退出。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
