#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新落地冒烟测试。

真实起进程、真实覆盖文件、真实在 DETACHED_PROCESS（无控制台）下运行 ——
这正是上一版失败的地方：apply.bat 里的 tasklist 无输出、timeout 返回 125，
等待循环直接跳出，2 秒就去覆盖还在运行的程序文件。

用法：
    python tests/smoke_update.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import apply_update  # noqa: E402

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def _kill_leftovers() -> None:
    if sys.platform != "win32":
        return
    for _ in range(2):
        try:
            subprocess.run(["taskkill", "/F", "/IM", "OutlookRegister.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        time.sleep(0.5)


def _make_layout(base: Path) -> tuple:
    """造一个 v1 安装目录 + v2 更新包。"""
    app = base / "app"
    stage = app / "update_staging" / "extracted"

    (app / "_internal" / "app_data").mkdir(parents=True)
    (app / "_internal" / "lib.dat").write_text("V1", encoding="utf-8")
    (app / "_internal" / "app_data" / "names.txt").write_text("NAMES_V1", encoding="utf-8")
    shutil.copy2(sys.executable, app / "OutlookRegister.exe")
    (app / "config.json").write_text('{"secret":"USER_V1"}', encoding="utf-8")
    (app / "admin.json").write_text('{"u":"a"}', encoding="utf-8")
    (app / ".push_state").write_text("42", encoding="utf-8")
    (app / "Results").mkdir()
    (app / "Results" / "oauth2.txt").write_text("acct1\n", encoding="utf-8")
    (app / "log").mkdir()
    (app / "log" / "old.txt").write_text("OLDLOG", encoding="utf-8")
    (app / "browsers" / "chromium-1169").mkdir(parents=True)
    (app / "browsers" / "chromium-1169" / "chrome.exe").write_text("BIG", encoding="utf-8")

    (stage / "_internal" / "app_data").mkdir(parents=True)
    (stage / "_internal" / "lib.dat").write_text("V2", encoding="utf-8")
    (stage / "_internal" / "app_data" / "names.txt").write_text("NAMES_V2", encoding="utf-8")
    shutil.copy2(sys.executable, stage / "OutlookRegister.exe")
    (stage / "manual.txt").write_text("MANUAL_V2", encoding="utf-8")
    # 打包失误模拟：包里混进用户数据，必须被白名单挡住
    (stage / "config.json").write_text('{"secret":"LEAK"}', encoding="utf-8")
    (stage / "Results").mkdir()
    (stage / "Results" / "oauth2.txt").write_text("LEAK\n", encoding="utf-8")
    return app, stage


def test_wait_semantics() -> None:
    print("== 等待语义 ==")
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    t0 = time.time()
    ok = apply_update.wait_for_pid_exit(p.pid, timeout_sec=30)
    check("已退出的进程立即返回", ok and (time.time() - t0) < 3,
          f"{time.time()-t0:.1f}s")

    check("pid=0 视为已退出", apply_update.wait_for_pid_exit(0))
    check("不存在的 pid 视为已退出", apply_update.wait_for_pid_exit(999999))

    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    t0 = time.time()
    ok = apply_update.wait_for_pid_exit(victim.pid, timeout_sec=30)
    dt = time.time() - t0
    # 关键断言：必须真的等了，不能秒退（旧 bat 版就是 2 秒跑完）
    check("存活进程会被等待到退出", ok and 3.0 < dt < 12.0, f"{dt:.1f}s")

    victim2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    t0 = time.time()
    ok = apply_update.wait_for_pid_exit(victim2.pid, timeout_sec=2)
    dt = time.time() - t0
    check("超时返回 False", (not ok) and dt < 5, f"{dt:.1f}s")
    victim2.kill()


def test_payload_whitelist() -> None:
    print("== 白名单 ==")
    base = Path(tempfile.mkdtemp(prefix="upd_wl_"))
    try:
        app, stage = _make_layout(base)
        rels = sorted(str(r) for _, r in apply_update._iter_payload(stage))
        leaked = [r for r in rels
                  if r.split("\\")[0] in apply_update.PRESERVE_DIRS
                  or r in apply_update.PRESERVE_FILES]
        check("包内用户数据被挡住", not leaked, f"待复制={rels}")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_full_apply() -> None:
    print("== 完整落地（DETACHED，旧进程存活）==")
    base = Path(tempfile.mkdtemp(prefix="upd_e2e_"))
    try:
        app, stage = _make_layout(base)

        old = subprocess.Popen(
            [str(app / "OutlookRegister.exe"), "-c", "import time; time.sleep(8)"])
        time.sleep(1.5)

        runner = base / "runner.py"
        runner.write_text(
            "import sys\n"
            f"sys.path.insert(0, r'{ROOT}')\n"
            "import apply_update\n"
            "sys.exit(apply_update.run(sys.argv[1:]))\n", encoding="utf-8")

        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        t0 = time.time()
        proc = subprocess.Popen(
            [sys.executable, str(runner), str(old.pid), str(stage), str(app),
             str(app / "OutlookRegister.exe")],
            cwd=str(stage), creationflags=flags, close_fds=True)
        proc.wait(timeout=180)
        dt = time.time() - t0

        check("落地进程成功退出", proc.returncode == 0, f"rc={proc.returncode}")
        # 必须等到旧进程真的退出才动手 —— 这是旧版最大的 bug
        check("等待了旧进程", dt > 6.0, f"{dt:.1f}s（旧进程存活 8s）")

        def rd(rel: str) -> str:
            f = app / rel
            return f.read_text(encoding="utf-8") if f.is_file() else "<MISSING>"

        check("_internal/lib.dat 已更新", rd("_internal/lib.dat") == "V2", rd("_internal/lib.dat"))
        check("嵌套文件已更新", rd("_internal/app_data/names.txt") == "NAMES_V2")
        check("新增文件已落地", rd("manual.txt") == "MANUAL_V2")

        check("config.json 保留", "USER_V1" in rd("config.json"), rd("config.json"))
        check("admin.json 保留", rd("admin.json") == '{"u":"a"}')
        check(".push_state 保留", rd(".push_state") == "42")
        check("Results 保留", "acct1" in rd("Results/oauth2.txt"))
        check("log 保留", rd("log/old.txt") == "OLDLOG")
        check("browsers 保留", rd("browsers/chromium-1169/chrome.exe") == "BIG")

        check("已生成 update.log", (app / "log" / "update.log").is_file())
        check("已生成备份", (app / "backup_prev" / "_internal" / "lib.dat").is_file())

        try:
            old.kill()
        except Exception:
            pass
    finally:
        _kill_leftovers()
        shutil.rmtree(base, ignore_errors=True)


def test_failure_paths() -> None:
    print("== 失败路径 ==")
    base = Path(tempfile.mkdtemp(prefix="upd_fail_"))
    try:
        app, _ = _make_layout(base)
        rc = apply_update.run(["0", str(base / "nope"), str(app),
                               str(app / "OutlookRegister.exe")])
        lib = (app / "_internal" / "lib.dat").read_text(encoding="utf-8")
        check("源目录不存在 → rc=1 且不动文件", rc == 1 and lib == "V1", f"rc={rc}")
        check("参数不足 → rc=2", apply_update.run(["1", "2"]) == 2)
    finally:
        _kill_leftovers()
        shutil.rmtree(base, ignore_errors=True)


def test_backup_restore() -> None:
    print("== 备份与回滚 ==")
    base = Path(tempfile.mkdtemp(prefix="upd_bak_"))
    try:
        app, _ = _make_layout(base)
        apply_update.backup_current(app)
        backed = (app / "backup_prev" / "_internal" / "lib.dat").read_text(encoding="utf-8")
        (app / "_internal" / "lib.dat").write_text("CORRUPT", encoding="utf-8")
        restored = apply_update.restore_backup(app)
        value = (app / "_internal" / "lib.dat").read_text(encoding="utf-8")
        check("备份内容正确", backed == "V1")
        check("回滚恢复原值", restored and value == "V1", value)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_cleanup() -> None:
    print("== 清理暂存 ==")
    base = Path(tempfile.mkdtemp(prefix="upd_cl_"))
    try:
        (base / "update_staging" / "extracted").mkdir(parents=True)
        (base / "update_staging" / "x.txt").write_text("x", encoding="utf-8")
        apply_update.cleanup_staging(base)
        check("update_staging 已删除", not (base / "update_staging").exists())
        apply_update.cleanup_staging(base)
        check("重复调用不报错", True)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    test_wait_semantics()
    test_payload_whitelist()
    test_full_apply()
    test_failure_paths()
    test_backup_restore()
    test_cleanup()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项")
        for line in FAILURES:
            print("  - " + line)
        return 1
    print("更新落地冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
