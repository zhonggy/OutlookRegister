#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OutlookRegister 统一入口（PyInstaller 打包目标）。

模式：
    (无参数)      启动 Web 控制台并打开浏览器  —— 默认
    --worker      注册主流程子进程（由控制台拉起）
    --console     显式启动控制台
    --version     打印版本

打包后 sys.executable 就是 OutlookRegister.exe，控制台用 --worker 重入自身，
保持与源码模式相同的进程隔离（注册崩溃不影响控制台，停止=向进程发信号）。
"""
import os
import sys

# 环境准备必须早于任何 patchright / 业务模块导入
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import paths  # noqa: E402
import version as appver  # noqa: E402

paths.setup_browsers_env()


def _bootstrap_data_dir():
    """首次运行：探测写权限 → 建目录 → 从模板生成 config.json。"""
    ok, detail = paths.check_writable()
    if not ok:
        print("=" * 60)
        print("[FATAL] 程序目录不可写，无法保存配置和注册结果。")
        print(f"        {detail}")
        print("        请把整个文件夹移到有写权限的位置（如 D:\\OutlookRegister）")
        print("        后重新运行，不要放在 C:\\Program Files 下。")
        print("=" * 60)
        input("按回车退出...")
        sys.exit(1)

    paths.ensure_dirs()

    if not paths.CONFIG_PATH.exists():
        if paths.CONFIG_EXAMPLE.is_file():
            paths.CONFIG_PATH.write_bytes(paths.CONFIG_EXAMPLE.read_bytes())
            print(f"[init] 已生成配置文件: {paths.CONFIG_PATH}")
            print("[init] 请在网页控制台的「系统设置」里填写代理等参数。")
        else:
            print(f"[WARN] 缺少配置模板 {paths.CONFIG_EXAMPLE}，请手动创建 config.json")


def _run_worker():
    import main
    main.run()


def _run_console():
    import webbrowser
    import threading
    import web_console

    host, port = "127.0.0.1", 9090
    argv = sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1] == "--console" else sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                pass

    web_console.HOST, web_console.PORT = host, port

    print("=" * 60)
    print(f"  {appver.DISPLAY_NAME}")
    print("=" * 60)
    print(f"控制台   : http://{host}:{port}")
    print(f"数据目录 : {paths.APP_DIR}")
    print(f"配置文件 : {paths.CONFIG_PATH}")
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    print(f"浏览器   : {browsers or '使用系统安装的 patchright chromium'}")
    print()
    print("仅监听本机 127.0.0.1，其他设备无法访问。首次访问请在网页上创建管理员账号。")
    print("关闭此窗口即退出程序。")
    print()

    threading.Timer(1.2, lambda: _open_browser(f"http://{host}:{port}")).start()
    web_console.main_serve(host, port)


def _open_browser(url):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--console"

    if mode in ("--version", "-v"):
        print(appver.DISPLAY_NAME)
        return

    _bootstrap_data_dir()

    if mode == "--worker":
        _run_worker()
    else:
        _run_console()


if __name__ == "__main__":
    main()
