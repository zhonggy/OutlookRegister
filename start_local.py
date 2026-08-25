#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地一键启动（源码模式开发用）。

打包版请直接运行 OutlookRegister.exe —— 它会自己起控制台。
本脚本保留用于源码调试，并支持可选拉起外部代理池。

代理池路径不再硬编码，改为读 config.json:

    "proxy_pool": {
      "enabled": false,
      "exe_path": "D:/out/easy_proxies/easy_proxies.exe",
      "config_path": "D:/out/easy_proxies/config.yaml",
      "manage_port": 9091
    }

enabled=false 或 exe_path 不存在则跳过，只起控制台。
"""
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser

import paths

CONSOLE_PORT = 9090


def load_cfg() -> dict:
    try:
        return json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def port_open(port, host="127.0.0.1", timeout=1.0):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def wait_port(port, secs, name):
    for _ in range(secs):
        if port_open(port):
            print(f"  [{name}] OK (port {port})")
            return True
        time.sleep(1)
    return False


def start_proxy_pool(cfg: dict):
    pp = cfg.get("proxy_pool") or {}
    if not pp.get("enabled"):
        print("[代理池] 未启用（config.json -> proxy_pool.enabled），跳过")
        return False

    exe = (pp.get("exe_path") or "").strip()
    if not exe or not os.path.isfile(exe):
        print(f"[代理池] 未找到可执行文件: {exe or '(未配置 exe_path)'}，跳过")
        return False

    port = int(pp.get("manage_port") or 9091)
    if port_open(port):
        print(f"[代理池] 已在运行 ({port})，跳过启动")
        return True

    ep_dir = os.path.dirname(exe)
    cmd = [exe]
    conf = (pp.get("config_path") or "").strip()
    if conf and os.path.isfile(conf):
        cmd += ["--config", conf]

    print("[代理池] 启动中 ...")
    run_log = paths.LOG_DIR / "proxy_pool.log"
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(run_log, "a", encoding="utf-8", errors="replace")
    subprocess.Popen(
        cmd,
        cwd=ep_dir or None,
        stdout=logf,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ok = wait_port(port, 30, "代理池")
    if not ok:
        print(f"  [代理池] 30s 内未就绪，请查看 {run_log}")
    return ok


def start_console():
    if port_open(CONSOLE_PORT):
        print(f"[控制台] 已在运行 ({CONSOLE_PORT})，跳过启动")
        return True

    app = paths.APP_DIR / "app.py"
    if not app.is_file():
        print(f"[控制台] 未找到 {app}")
        return False

    venv_py = paths.APP_DIR / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.exists() else sys.executable

    print("[控制台] 启动 app.py ...")
    subprocess.Popen(
        [py, str(app), "--console", "--port", str(CONSOLE_PORT)],
        cwd=str(paths.APP_DIR),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ok = wait_port(CONSOLE_PORT, 15, "控制台")
    if not ok:
        print("  [控制台] 15s 内未就绪，请检查是否有报错")
    return ok


def main():
    print("=" * 44)
    print("  OutlookRegister 本地一键启动（源码模式）")
    print("=" * 44)
    cfg = load_cfg()
    start_proxy_pool(cfg)
    start_console()
    print()
    print(f"控制台: http://127.0.0.1:{CONSOLE_PORT}")
    print()
    try:
        webbrowser.open(f"http://127.0.0.1:{CONSOLE_PORT}")
    except Exception:
        pass
    input("按回车退出本窗口（服务仍在后台运行）...")


if __name__ == "__main__":
    main()
