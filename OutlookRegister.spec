# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

在 GitHub Actions 的 windows-latest 上构建，不在本地编译。

关键点：
  - 内置 Chromium 从 %LOCALAPPDATA%\\ms-playwright 复制到 browsers/，
    目录名必须匹配 patchright browsers.json 的 revision（如 chromium-1169）
  - upx=False：UPX 压缩 node.exe / Chromium DLL 会导致启动崩溃且提高杀软误报
  - 排除 playwright：项目只用 patchright，playwright 从未被 import（省 ~97MB）
"""
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

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

excludes = [
    "playwright",          # 项目只用 patchright，从未 import playwright
    "tkinter", "unittest", "pydoc", "doctest", "pdb",
    "setuptools", "pip", "wheel",
    "PIL", "numpy", "pandas", "matplotlib",
    "IPython", "pytest",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=True,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OutlookRegister",
)
