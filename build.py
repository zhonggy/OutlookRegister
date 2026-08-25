#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建脚本：生成 version_info.txt → PyInstaller → 安全自检 → 打包分发包。

设计给 GitHub Actions 用（windows-latest），本地也能跑但不推荐。

用法:
    python build.py                      # 完整构建
    python build.py --skip-build         # 只重新打包 dist 里已有的产物
    python build.py --include-headless-shell   # 额外内置 197MB 的 headless shell
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import version as appver  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
OUT = DIST / "OutlookRegister"
ARTIFACTS = ROOT / "artifacts"

# 绝不允许出现在分发包里的运行时/私密文件
FORBIDDEN_IN_DIST = ["config.json", "admin.json", ".push_state"]
# 命中即视为泄露的敏感串前缀
SECRET_MARKERS = ["omk_", "admin_password\": \"z"]


def run(cmd, **kw):
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run(cmd, cwd=str(ROOT), **kw)
    if r.returncode != 0:
        sys.exit(f"[FATAL] 命令失败，退出码 {r.returncode}")


def check_env():
    print("== 环境检查 ==")
    print(f"Python: {sys.version.split()[0]}")
    try:
        import PyInstaller
        pv = PyInstaller.__version__
        print(f"PyInstaller: {pv}")
        major = int(pv.split(".")[0])
        minor = int(pv.split(".")[1]) if "." in pv else 0
        if sys.version_info >= (3, 13) and (major, minor) < (6, 11):
            sys.exit("[FATAL] Python 3.13 需要 PyInstaller >= 6.11")
    except ImportError:
        sys.exit("[FATAL] 缺少 PyInstaller: pip install pyinstaller")

    for mod in ("faker", "requests", "patchright"):
        try:
            __import__(mod)
            print(f"{mod}: OK")
        except ImportError:
            sys.exit(f"[FATAL] 缺少依赖 {mod}")

    try:
        import playwright  # noqa: F401
        print("[WARN] 环境里装了 playwright。项目并不使用它，spec 已排除，"
              "但为了减小体积建议在纯净环境构建。")
    except ImportError:
        print("playwright: 未安装（符合预期，省 ~97MB）")


def write_version_info():
    v = appver.VERSION
    parts = [int(x) for x in v.split(".")] + [0, 0, 0, 0]
    quad = ", ".join(str(x) for x in parts[:4])
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad}),
    prodvers=({quad}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'{appver.GITHUB_OWNER}'),
         StringStruct(u'FileDescription', u'Outlook \u81ea\u52a8\u6ce8\u518c\u5de5\u5177'),
         StringStruct(u'FileVersion', u'{v}'),
         StringStruct(u'InternalName', u'{appver.APP_NAME}'),
         StringStruct(u'OriginalFilename', u'{appver.APP_NAME}.exe'),
         StringStruct(u'ProductName', u'{appver.APP_NAME}'),
         StringStruct(u'ProductVersion', u'{v}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    p = ROOT / "version_info.txt"
    p.write_text(content, encoding="utf-8")
    print(f"[ok] 已生成 {p.name} (v{v})")


def clean():
    for d in (BUILD, DIST, ARTIFACTS):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    print("[ok] 已清理 build/ dist/ artifacts/")


def pyinstaller(include_headless_shell: bool):
    env = dict(os.environ)
    env["INCLUDE_HEADLESS_SHELL"] = "1" if include_headless_shell else "0"
    run([sys.executable, "-m", "PyInstaller", "--noconfirm",
         "OutlookRegister.spec"], env=env)


def stage_user_files():
    """拷需要用户直接看到的文件到 exe 同级目录。

    onedir 模式下 spec 里 datas 的 "." 实际落在 _internal/，用户看不到。
    """
    print("\n== 展开用户可见文件 ==")
    for name in ("使用说明.txt", "config.example.json"):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, OUT / name)
            print(f"[ok] {name}")
        else:
            print(f"[WARN] 缺少 {name}")


def security_audit():
    print("\n== 安全自检 ==")
    if not OUT.is_dir():
        sys.exit(f"[FATAL] 未找到构建产物 {OUT}")

    bad = []
    for name in FORBIDDEN_IN_DIST:
        p = OUT / name
        if p.exists():
            bad.append(str(p))
    for d in ("Results", "log", "browser_profiles"):
        if (OUT / d).exists():
            bad.append(str(OUT / d))
    if bad:
        sys.exit("[FATAL] 分发包含运行时/私密文件:\n  " + "\n  ".join(bad))

    # 扫描文本类文件里的敏感串（Chromium 二进制体积大且不可能含配置，跳过）
    hits = []
    for p in OUT.rglob("*"):
        if not p.is_file():
            continue
        if "browsers" in p.parts:
            continue
        if p.suffix.lower() not in (".json", ".txt", ".py", ".cfg", ".ini", ".yaml", ".yml", ""):
            continue
        if p.stat().st_size > 4 * 1024 * 1024:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for marker in SECRET_MARKERS:
            if marker in text:
                hits.append(f"{p} 含 {marker!r}")
    if hits:
        sys.exit("[FATAL] 疑似密钥泄露:\n  " + "\n  ".join(hits))

    example = OUT / "config.example.json"
    if not example.is_file():
        sys.exit("[FATAL] 缺少 config.example.json，首次启动无法生成配置")
    inner_example = OUT / "_internal" / "config.example.json"
    if not inner_example.is_file():
        sys.exit("[FATAL] _internal 里缺少 config.example.json（paths.CONFIG_EXAMPLE 指向此处）")
    print("[ok] 未发现私密文件或密钥泄露")


def smoke_test():
    print("\n== 冒烟测试 ==")
    exe = OUT / "OutlookRegister.exe"
    if not exe.is_file():
        sys.exit(f"[FATAL] 未找到 {exe}")
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True,
                           text=True, timeout=120, cwd=str(OUT))
        print(f"--version -> {r.stdout.strip() or r.stderr.strip()}")
        if appver.VERSION not in (r.stdout + r.stderr):
            print("[WARN] --version 输出里没有版本号，请人工确认")
    except subprocess.TimeoutExpired:
        sys.exit("[FATAL] --version 超时（可能缺依赖或 bootloader 异常）")
    except Exception as exc:
        sys.exit(f"[FATAL] 无法执行 exe: {exc}")

    br = OUT / "_internal" / "browsers"
    chromium = [p.name for p in br.iterdir() if p.name.startswith("chromium")] if br.is_dir() else []
    if not chromium:
        sys.exit("[FATAL] _internal/browsers 里没有 chromium，内置浏览器收集失败")
    print(f"[ok] 内置浏览器: {', '.join(chromium)}")

    node = list((OUT / "_internal").rglob("driver/node.exe"))
    if not node:
        sys.exit("[FATAL] 未收集到 patchright driver/node.exe，浏览器将无法启动")
    print(f"[ok] patchright driver: {node[0].relative_to(OUT)}")

    # 生成的 config.json / log 是冒烟测试的副产物，不能留在分发包里
    for junk in ("config.json", "log", "Results", ".write_probe"):
        p = OUT / junk
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


def _zip_dir(zf: zipfile.ZipFile, base: Path, skip_browsers: bool):
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if skip_browsers and "browsers" in rel.parts:
            continue
        zf.write(p, str(rel))


def package():
    print("\n== 打包分发包 ==")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    v = appver.VERSION
    results = []

    full = ARTIFACTS / f"OutlookRegister-v{v}-full.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        _zip_dir(zf, OUT, skip_browsers=False)
    results.append(full)

    patch = ARTIFACTS / f"OutlookRegister-v{v}-patch.zip"
    with zipfile.ZipFile(patch, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        _zip_dir(zf, OUT, skip_browsers=True)
    results.append(patch)

    lines = []
    print()
    for p in results:
        mb = p.stat().st_size / 1048576
        digest = sha256(p)
        print(f"{p.name}  {mb:.1f} MB")
        print(f"  SHA256: {digest}")
        lines.append(f"{p.name}  {digest}")

    (ARTIFACTS / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[ok] 校验和已写入 {ARTIFACTS / 'SHA256SUMS.txt'}")
    print("     发版时请把这些行贴进 Release 说明，更新器会据此校验完整性。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true", help="跳过 PyInstaller，只重新打包")
    ap.add_argument("--include-headless-shell", action="store_true",
                    help="额外内置 chromium_headless_shell（+197MB）")
    args = ap.parse_args()

    print("=" * 60)
    print(f"  构建 {appver.DISPLAY_NAME}")
    print("=" * 60)

    check_env()
    if not args.skip_build:
        write_version_info()
        clean()
        pyinstaller(args.include_headless_shell)
    stage_user_files()
    security_audit()
    smoke_test()
    package()
    print("\n构建完成。")


if __name__ == "__main__":
    main()
