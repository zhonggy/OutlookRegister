#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Registrar One-Click Start器

同时启动：
  1. 代理池 easy_proxies（9091 管理端 + 24000+ 端口池）
  2. 注册机 Web 控制台（9090）

already-running services are skipped (idempotent).
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))          # OutlookRegister 目录
EP_DIR = r"D:/out/easy_proxies"                            # 代理池目录
EP_EXE = os.path.join(EP_DIR, "easy_proxies.exe")
EP_CFG = os.path.join(EP_DIR, "config.yaml")
CONSOLE = os.path.join(BASE, "web_console.py")

RUN_LOG = os.path.join(EP_DIR, "run.log")


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


def start_proxy_pool():
    if port_open(9091):
        print("[代理池] [proxy-pool] already running (9091), skip")
        return True
    if not os.path.exists(EP_EXE):
        print(f"[代理池] 未找到 {EP_EXE}，跳过（如需代理池请先准备 easy_proxies）")
        return False
    print("[代理池] 启动 easy_proxies ...")
    logf = open(RUN_LOG, "a", encoding="utf-8", errors="replace")
    subprocess.Popen(
        [EP_EXE, "--config", EP_CFG],
        cwd=EP_DIR,
        stdout=logf,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ok = wait_port(9091, 30, "代理池")
    if not ok:
        print(f"  [代理池] 30s 内未就绪，请查看 {RUN_LOG}")
    # 等端口池（节点测试需要更久，不阻塞，控制台里可看进度）
    return ok


def start_console():
    if port_open(9090):
        print("[控制台] 已在运行 (9090)，跳过启动")
        return True
    if not os.path.exists(CONSOLE):
        print(f"[控制台] 未找到 {CONSOLE}")
        return False
    print("[控制台] 启动 web_console.py ...")
    subprocess.Popen(
        [sys.executable, CONSOLE, "--port", "9090"],
        cwd=BASE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ok = wait_port(9090, 15, "控制台")
    if not ok:
        print("  [控制台] 15s 内未就绪，请检查是否有报错")
    return ok


def main():
    print("=" * 40)
    print("  Local Registrar One-Click Start")
    print("=" * 40)
    start_proxy_pool()
    start_console()
    print()
    print("Console : http://127.0.0.1:9090")
    print("ProxyPool: http://127.0.0.1:9091")
    print("（提示：节点池测速需要几分钟，可在 9091 或控制台连通检查里查看）")
    print()
    try:
        webbrowser.open("http://127.0.0.1:9090")
    except Exception:
        pass
    input("按回车退出本窗口（服务仍在后台运行）...")


if __name__ == "__main__":
    main()
