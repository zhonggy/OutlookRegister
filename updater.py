"""手动更新：查 GitHub Release → 下载 patch 包 → 校验 → 拉起新版 exe 落地。

不自动更新。用户在「关于与更新」里点检查才发起。

落地不能由本进程完成：运行中的 exe 无法覆盖自己，也无法覆盖被自己
加载的 _internal/*.dll。旧版用 apply.bat，但它在 DETACHED_PROCESS
（无控制台）下彻底失效 —— tasklist 无输出、timeout 返回 125，
等待循环直接跳出，2 秒就去覆盖正在运行的程序文件。

现在改由解压出来的**新版 exe** 以 --apply-update 模式执行落地（见
​apply_update.py）：它跑在 update_staging 里，锁的是那份 _internal，
因此可以自由覆盖安装目录；等待用 WaitForSingleObject，不依赖控制台。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import requests

import paths
import version as appver

# 更新时必须保留的用户数据。真正的排除逻辑在 apply_update.py 里，
# 这里只用于提示文案，两处定义保持一致。
from apply_update import PRESERVE_DIRS, PRESERVE_FILES  # noqa: E402

_state = {
    "phase": "idle",      # idle|checking|available|downloading|verifying|ready|error|uptodate
    "message": "",
    "local": appver.VERSION,
    "remote": "",
    "notes": "",
    "asset": "",
    "size": 0,
    "downloaded": 0,
    "requires_full": False,
    "lock": threading.Lock(),
}


def snapshot() -> dict:
    # 下划线开头的是内部状态（下载 URL、新 exe 路径等），不往 UI 送
    d = {k: v for k, v in _state.items()
         if k != "lock" and not k.startswith("_")}
    if d["size"]:
        d["percent"] = round(d["downloaded"] * 100.0 / d["size"], 1)
    else:
        d["percent"] = 0.0
    d["release_page"] = appver.RELEASE_PAGE
    return d


def _set(**kw):
    with _state["lock"]:
        _state.update(kw)


def _proxies_from_config() -> dict:
    """GitHub API 在部分网络下不通，复用 config.json 里的代理。"""
    try:
        cfg = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    up = cfg.get("update") or {}
    explicit = (up.get("proxy") or "").strip()
    if explicit:
        return {"http": explicit, "https": explicit}
    if up.get("use_register_proxy") is False:
        return {}
    p = cfg.get("proxy") or {}
    host = (p.get("host") or "").strip()
    if not host:
        return {}
    ptype = (p.get("type") or "http").strip() or "http"
    if (p.get("mode") or "single") == "single":
        port = p.get("single_port")
    else:
        port = p.get("port_start")
    try:
        port = int(port)
    except Exception:
        return {}
    if not port:
        return {}
    url = f"{ptype}://{host}:{port}"
    return {"http": url, "https": url}


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json",
         "User-Agent": f"{appver.APP_NAME}/{appver.VERSION}"}
    try:
        cfg = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
        tok = ((cfg.get("update") or {}).get("github_token") or "").strip()
        if tok:
            h["Authorization"] = f"Bearer {tok}"
    except Exception:
        pass
    return h


def _pick_asset(assets: list, prefer_patch=True):
    """prefer_patch=True 选 patch 包（不含 Chromium，约 40MB）；否则选 full 包。

    requires_full 的版本（换了内置 Chromium）必须走 full，patch 包缺 browsers/。
    """
    def _named(kw):
        return [a for a in assets
                if kw in (a.get("name") or "").lower()
                and (a.get("name") or "").lower().endswith(".zip")]

    patch, full = _named("patch"), _named("full")
    order = (patch, full) if prefer_patch else (full, patch)
    for group in order:
        if group:
            return group[0]
    zips = [a for a in assets if (a.get("name") or "").lower().endswith(".zip")]
    return zips[0] if zips else None


def _sha256_from_notes(notes: str, asset_name: str) -> str:
    """从 release body 里找该 asset 的 SHA256（形如 `name  <64hex>` 或 `name: <64hex>`）。"""
    if not notes:
        return ""
    for line in notes.splitlines():
        if asset_name.lower() in line.lower():
            m = re.search(r"\b([a-fA-F0-9]{64})\b", line)
            if m:
                return m.group(1).lower()
    return ""


def check() -> dict:
    _set(phase="checking", message="正在查询最新版本…", downloaded=0, size=0)
    try:
        r = requests.get(appver.RELEASE_API, headers=_headers(),
                         proxies=_proxies_from_config(), timeout=15)
    except Exception as exc:
        _set(phase="error", message=f"无法连接 GitHub（可在系统设置里配置代理）: {exc}")
        return snapshot()
    if r.status_code == 404:
        _set(phase="error", message="仓库暂无 Release，或仓库为私有需要在配置里填 update.github_token")
        return snapshot()
    if r.status_code != 200:
        _set(phase="error", message=f"GitHub 返回 {r.status_code}: {r.text[:200]}")
        return snapshot()
    try:
        rel = r.json()
    except Exception as exc:
        _set(phase="error", message=f"响应解析失败: {exc}")
        return snapshot()

    tag = (rel.get("tag_name") or "").strip()
    notes = rel.get("body") or ""
    requires_full = "REQUIRES_FULL" in notes.upper()
    if not appver.is_newer(tag):
        _set(phase="uptodate", remote=tag, notes=notes,
             message=f"已是最新版本 v{appver.VERSION}")
        return snapshot()

    asset = _pick_asset(rel.get("assets") or [], prefer_patch=not requires_full)
    if not asset:
        _set(phase="error", remote=tag, notes=notes,
             message="Release 里没有可用的安装包资源")
        return snapshot()

    _set(phase="available", remote=tag, notes=notes, requires_full=requires_full,
         asset=asset.get("name", ""), size=int(asset.get("size") or 0),
         message=f"发现新版本 {tag}")
    with _state["lock"]:
        _state["_download_url"] = asset.get("browser_download_url", "")
    return snapshot()


def _download(url: str, dest: Path, expect_size: int) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    got = 0
    try:
        with requests.get(url, headers=_headers(), proxies=_proxies_from_config(),
                          stream=True, timeout=(15, 120)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or expect_size or 0)
            _set(size=total or expect_size)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    _set(downloaded=got)
    except Exception as exc:
        _set(phase="error", message=f"下载失败: {exc}")
        return False
    if expect_size and got != expect_size:
        _set(phase="error", message=f"下载不完整: {got}/{expect_size} 字节")
        return False
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


def _find_new_exe(src: Path) -> Path | None:
    """在解压出的更新包里找可执行的新版 exe。"""
    for name in ("OutlookRegister.exe",):
        cand = src / name
        if cand.is_file():
            return cand
    exes = [p for p in src.glob("*.exe")]
    return exes[0] if exes else None


def download_and_stage() -> dict:
    with _state["lock"]:
        url = _state.get("_download_url", "")
        name = _state.get("asset", "")
        size = int(_state.get("size") or 0)
        notes = _state.get("notes", "")
        remote = _state.get("remote", "")
    if not url:
        _set(phase="error", message="请先检查更新")
        return snapshot()
    if _state.get("requires_full"):
        _set(phase="error",
             message=f"该版本更换了内置 Chromium，需手动下载完整包: {appver.RELEASE_PAGE}")
        return snapshot()
    if not getattr(sys, "frozen", False):
        _set(phase="error", message="源码模式不支持自动更新，请用 git pull")
        return snapshot()

    stage = paths.UPDATE_DIR
    try:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _set(phase="error", message=f"无法创建暂存目录: {exc}")
        return snapshot()

    pkg = stage / name
    _set(phase="downloading", message=f"正在下载 {name}", downloaded=0)
    if not _download(url, pkg, size):
        return snapshot()

    _set(phase="verifying", message="正在校验完整性…")
    want = _sha256_from_notes(notes, name)
    if want:
        got = _sha256(pkg)
        if got != want:
            shutil.rmtree(stage, ignore_errors=True)
            _set(phase="error", message=f"SHA256 校验失败\n期望 {want}\n实际 {got}")
            return snapshot()
    extracted = stage / "extracted"
    try:
        with zipfile.ZipFile(pkg) as z:
            z.extractall(extracted)
    except Exception as exc:
        _set(phase="error", message=f"解压失败: {exc}")
        return snapshot()

    # zip 里可能多套一层同名目录
    entries = list(extracted.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        extracted = entries[0]

    # 落地靠的就是这份新版 exe 自己跑 --apply-update，因此它必须存在
    # 且带完整 _internal（能脉离安装目录独立运行）
    new_exe = _find_new_exe(extracted)
    if new_exe is None:
        _set(phase="error", message="更新包里没有 exe，无法落地")
        return snapshot()
    if not (extracted / "_internal").is_dir():
        _set(phase="error", message="更新包缺少 _internal 目录，结构异常")
        return snapshot()

    with _state["lock"]:
        _state["_new_exe"] = str(new_exe)
        _state["_payload"] = str(extracted)

    _set(phase="ready",
         message=f"{remote} 已就绪，点「立即重启并更新」完成安装"
                 + ("（校验通过）" if want else "（release 未提供 SHA256，已跳过校验）"))
    return snapshot()


def apply_and_restart() -> dict:
    """拉起新版 exe 的 --apply-update 模式，然后让本进程退出。

    调用方需先停掉注册任务 —— worker 占着 _internal/*.dll 会让覆盖失败。
    """
    stage = paths.UPDATE_DIR
    with _state["lock"]:
        new_exe_str = _state.get("_new_exe", "")
        payload_str = _state.get("_payload", "")

    src = Path(payload_str) if payload_str else (stage / "extracted")
    if not src.is_dir():
        _set(phase="error", message="更新未就绪，请先下载")
        return snapshot()

    new_exe = Path(new_exe_str) if new_exe_str else _find_new_exe(src)
    if new_exe is None or not new_exe.is_file():
        _set(phase="error", message="未找到新版 exe，请重新下载")
        return snapshot()

    target_exe = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        _set(phase="error", message="源码模式不支持自动更新，请用 git pull")
        return snapshot()

    try:
        subprocess.Popen(
            [str(new_exe), "--apply-update", str(os.getpid()),
             str(src), str(paths.APP_DIR), str(target_exe)],
            cwd=str(src),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
    except Exception as exc:
        _set(phase="error", message=f"启动更新程序失败: {exc}")
        return snapshot()

    _set(phase="restarting",
         message="更新程序已启动，本程序即将退出并自动重启")
    # 给 UI 一点时间把提示画出来，再硬退 —— 落地进程正在等我们死
    threading.Thread(
        target=lambda: (time.sleep(1.2), os._exit(0)), daemon=True,
    ).start()
    return snapshot()
