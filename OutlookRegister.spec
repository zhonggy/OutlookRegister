# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

在 GitHub Actions 的 windows-latest 上构建，不在本地编译。

需要显式声明的隐式依赖：

  - Chromium 二进制（不在 site-packages 里，在 %LOCALAPPDATA%\\ms-playwright）
  - patchright/driver 整目录 —— 自动分析抓不到（运行时才按路径查找）
  - faker 的 provider —— 全靠字符串动态导入
  - gui.views 子模块 —— 由 __init__ 汇总导入

还需要 runtime hook（rthook_streams.py）：console=False 时 PyInstaller 把
标准流置为 None，而 main.py / controllers 大量用 print，不补会直接
在启动时 AttributeError。
"""
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Windows runner 控制台默认不是 UTF-8，spec 里 print 中文会直接抛
# UnicodeEncodeError 并让构建失败。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(os.path.abspath(SPECPATH))

# ---------------------------------------------------------------- browsers

INCLUDE_HEADLESS_SHELL = os.environ.get("INCLUDE_HEADLESS_SHELL", "0") == "1"


def _ms_playwright_root() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        return Path(local) / "ms-playwright"
    return Path.home() / "AppData" / "Local" / "ms-playwright"


def _patchright_revisions() -> dict:
    """从 patchright 的 browsers.json 读需要的 revision，避免硬编码版本号。"""
    import patchright
    bj = Path(patchright.__file__).parent / "driver" / "package" / "browsers.json"
    want = {}
    try:
        data = json.loads(bj.read_text(encoding="utf-8"))
        for b in data.get("browsers", []):
            if b.get("name") == "chromium":
                want["chromium"] = str(b.get("revision"))
            elif b.get("name") == "chromium-headless-shell":
                want["chromium_headless_shell"] = str(b.get("revision"))
    except Exception as exc:
        print(f"[spec][WARN] 无法读取 browsers.json: {exc}")
    return want


def _browser_datas():
    root = _ms_playwright_root()
    if not root.is_dir():
        raise SystemExit(
            f"[spec][FATAL] 未找到浏览器目录 {root}\n"
            f"              请先执行: patchright install chromium"
        )
    rev = _patchright_revisions()
    wanted = []
    if "chromium" in rev:
        wanted.append(f"chromium-{rev['chromium']}")
    if INCLUDE_HEADLESS_SHELL and "chromium_headless_shell" in rev:
        wanted.append(f"chromium_headless_shell-{rev['chromium_headless_shell']}")

    out = []
    found = []
    for name in wanted:
        src = root / name
        if not src.is_dir():
            raise SystemExit(
                f"[spec][FATAL] 缺少 {src}\n"
                f"              请执行: patchright install chromium"
            )
        out.append((str(src), f"browsers/{name}"))
        found.append(name)

    # winldd 是 Windows 上启动 Chromium 的依赖探测工具，必须一起带
    for p in root.iterdir():
        if p.is_dir() and p.name.startswith("winldd"):
            out.append((str(p), f"browsers/{p.name}"))
            found.append(p.name)

    print(f"[spec] 内置浏览器: {', '.join(found)}")
    return out


# ---------------------------------------------------------------- datas

# 注意：onedir 模式下 datas 的 "." 目标是 _internal/，不是 exe 同级目录。
# config.example.json 放 _internal/ 正合适（paths.CONFIG_EXAMPLE 指向 _MEIPASS）；
# 使用说明.txt 需要用户看得见，由 build.py 拷到 exe 同级。
datas = [
    (str(ROOT / "english_name_generator.txt"), "app_data"),
    (str(ROOT / "config.example.json"), "."),
]

# patchright 的 driver/ 含 node.exe + JS driver，必须完整收集
datas += collect_data_files("patchright", include_py_files=True)
datas += collect_data_files("faker")
datas += _browser_datas()

hiddenimports = []
hiddenimports += collect_submodules("faker")       # provider 全靠动态导入
hiddenimports += collect_submodules("patchright")
# GUI 页面由 gui/views/__init__.py 汇总导入，这里兜一层
hiddenimports += collect_submodules("gui")
hiddenimports += ["core", "paths", "updater", "version", "utils", "main"]
hiddenimports += ["controllers", "controllers.oauth2", "controllers.outlook_controller",
                  "controllers.recovery_bind", "controllers.temp_mail"]

excludes = [
    "playwright",          # 项目只用 patchright，从未 import playwright
    "tkinter", "unittest", "doctest", "pdb",
    "PIL", "numpy", "pandas", "matplotlib",
    "IPython", "pytest",
    # PySide6 里用不到的模块。QtWebEngine 单独就有 130MB+，
    # 不排掉分发包会白白肿一倍。
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtTest",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtHelp", "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtGraphs",
]
# 不排除 setuptools / pkg_resources：faker 等包可能在运行时间接依赖它们，
# 排掉省不了多少体积，却容易出 ModuleNotFoundError。
# 也不排 PySide6.QtSvg：样式表里的 checkbox 对勾用的是内嵌 SVG。

block_cipher = None

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "rthook_streams.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# PyInstaller 6.x: PYZ 不再接 cipher / zipped_data（cipher 会直接报
# RemovedCipherFeatureError）。Analysis 的 win_no_prefer_redirects /
# win_private_assemblies 也已废弃，一并去掉。
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OutlookRegister",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # 见文件头说明，务必保持 False
    console=False,                   # GUI 不弹黑窗；worker 用 CREATE_NO_WINDOW
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "app.ico") if (ROOT / "app.ico").is_file() else None,
    version=str(ROOT / "version_info.txt") if (ROOT / "version_info.txt").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OutlookRegister",
)
