# OutlookRegister → Windows EXE 打包规划

目标：把当前 Python 项目做成**绿色便携版 Windows 应用**，用户解压即用，零 Python / 零 pip / 零 `patchright install`。

## 已确认的技术决策

| 项 | 决策 |
| --- | --- |
| Chromium | 完全内置进分发包，同时保留 `browser.executable_path` 覆盖（高级用户可换 fingerprint-chromium） |
| exe 形态 | PyInstaller `onedir`：`OutlookRegister.exe` + `_internal/`，外层用 7z 自解压做单文件安装包 |
| 进程模型 | 单 exe 多模式：默认起 Web 控制台，内部用 `--worker` 重新调用自身跑注册（保持现有进程隔离） |
| 运行时数据 | exe 同级目录（绿色便携版） |
| 代理池 | 不打包，`start_local.py` 硬编码路径改为 config 可配，找不到就跳过 |
| 密钥 | 只分发 `config.example.json`，首次启动生成空配置 |
| 版本 | 从 `v1.0` 起，手动递增 `v1.1`、`v1.2`… |
| 更新 | 不自动更新。控制台里手动点「检查更新」→ 从 GitHub Releases 下载 |

---

## 一、现状盘点：冻结后会坏掉的地方

打包前必须先改代码，否则 PyInstaller 出来的 exe 一定跑不起来。逐条列出实际位置。

### 1.1 `__file__` 定位（冻结后指向解压临时目录，不是 exe 所在目录）

| 文件:行 | 常量 | 冻结后应指向 |
| --- | --- | --- |
| `main.py:19` | `RESULTS_DIR` | exe 同级（可写数据） |
| `main.py:22` | `DEFAULT_BROWSER_PROFILES` | exe 同级（可写数据） |
| `main.py:82` | `config_path`（自动推送读配置） | exe 同级（可写数据） |
| `web_console.py:39` | `BASE_DIR`（派生 config/Results/log/admin.json/.push_state） | exe 同级（可写数据） |
| `utils.py:8` | `_NAMES_FILE`（`english_name_generator.txt`） | **打包内资源**（只读） |
| `controllers/outlook_controller.py:69` | `browser_user_data_root` | exe 同级（可写数据） |
| `controllers/outlook_controller.py:101` | `log_dir` | exe 同级（可写数据） |
| `controllers/recovery_bind.py:21` | `RESULTS_DIR` | exe 同级（可写数据） |

### 1.2 依赖当前工作目录（cwd）

- `main.py:762` — `open('config.json', ...)` 用的是相对路径。现在能跑只因为 `web_console.py:455` 传了 `cwd=BASE_DIR`。冻结后必须改成绝对路径。

### 1.3 子进程拉起方式

- `web_console.py:439` — `cmd = [sys.executable, "-u", "main.py"]`。冻结后 `sys.executable` 是 `OutlookRegister.exe`，参数 `main.py` 会被当成脚本名传给应用自己，直接失效。
- `start_local.py:76` `_console_python()` 找 `.venv/Scripts/python.exe` — 冻结后整段无意义。

### 1.4 Chromium 二进制不在包里

- `controllers/outlook_controller.py:9` `from patchright.sync_api import sync_playwright`
- `outlook_controller.py:601` `launch_browser()`：`executable_path` 为空时走 patchright 自带 Chromium
- 实际二进制在 `%LOCALAPPDATA%\ms-playwright\chromium-1169`（对应 patchright `browsers.json` revision 1169 / Chrome 136.0.7103.25），**不在 site-packages 里**，PyInstaller 默认不会收集。

### 1.5 动态导入的库

- `faker`（`outlook_controller.py:858` `Faker()`）— provider 全靠动态导入，需要 `collect_all`。
- `patchright` — 需要连 `driver/`（`node.exe` + JS driver，91MB）一起收集。
- `requests` → `certifi` CA 包（PyInstaller 自带 hook，一般自动，需验证）。

### 1.6 顺手能省的体积

- `requirements.txt` 里 `playwright==1.53.0` **代码里从未 import**（全项目只用 patchright）。97MB 白搭，构建时排除。
- `ffmpeg-1011`（3.4MB）只用于录视频，项目没用到，不打包。
- `chromium_headless_shell-1169`（197MB）见 §2.2 讨论。

### 1.7 顺带发现的既有问题（非打包必需，建议一并修）

- `web_console.py:472` `_stop_register()` 用 `proc.terminate()`。在 Windows 上 `terminate()` = `TerminateProcess`，**硬杀进程**，`main.py:754` 注册的 `SIGTERM`/`SIGBREAK` 处理器根本不会执行 → Ctrl+C 那套「先写汇总再清 profile」的逻辑在 Web 控制台点「停止」时是失效的。
  正确做法：`CREATE_NEW_PROCESS_GROUP` 起子进程 + `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid)` 触发 `SIGBREAK`，超时再 `kill()`。打包时反正要重写这段 Popen，建议顺手修。
- `新建 文本文档.txt` 是垃圾文件，删掉。

---

## 二、方案设计

### 2.1 分发包结构

```
OutlookRegister-v1.0/
├─ OutlookRegister.exe          # 唯一入口（多模式）
├─ config.example.json          # 模板，首次启动复制成 config.json
├─ 使用说明.txt
├─ _internal/                   # PyInstaller onedir 运行时
│   ├─ python313.dll, base_library.zip, ...
│   ├─ patchright/              # 含 driver/node.exe + JS driver
│   ├─ faker/
│   └─ app_data/
│       └─ english_name_generator.txt
└─ browsers/                    # 内置 Chromium（PLAYWRIGHT_BROWSERS_PATH 指这里）
    ├─ chromium-1169/
    └─ winldd-1007/
```

首次运行后在 exe 同级生成：`config.json`、`admin.json`、`Results/`、`log/`、`browser_profiles/`、`.push_state`。

体积预估：解压后约 465MB（内置 headless_shell 则 660MB），7z LZMA2 压缩后约 220MB（含 headless_shell 约 300MB）。

### 2.2 Chromium 内置的关键细节

内置目录必须在**任何 patchright 导入之前**通过环境变量声明：

```python
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(resource_dir() / "browsers")
```

`browsers/` 目录里的名字必须与 patchright `browsers.json` 严格对应（`chromium-1169`），改名即失效。

**headless 支持的取舍**：Playwright ≥1.49 起，`headless=True` 默认启动 `chromium_headless_shell`（独立的 197MB 二进制）。三种处理：

- 只打包 `chromium-1169`，`launch()` 传 `channel="chromium"` → 强制用完整 Chromium 跑 headless，省 197MB。**推荐**，需实测确认 patchright 的 `--fingerprint` 参数在该 channel 下仍生效。
- 两个都打包，最省心，+197MB。
- 只打包 `chromium-1169` 且不支持 headless。当前 `config.json` 是 `headless: false`，但控制台里能勾选，不做处理会变成用户可触发的崩溃。

必须实测的点：`launch_persistent_context()`（`outlook_controller.py:698`，走自定义 exe 分支）与 `launch()`（第 733 行，走内置分支）在冻结环境下都要验证。

### 2.3 单 exe 多模式入口

新增 `app.py` 作为 PyInstaller 唯一入口：

```python
# app.py（伪码）
import os, sys
from paths import app_dir, resource_dir

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(resource_dir() / "browsers"))
os.environ.setdefault("PYTHONUTF8", "1")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--console"
    if mode == "--worker":       # 注册子进程
        import register_main; register_main.run()
    elif mode == "--apply-update":  # 更新落地（见 §2.6）
        import updater; updater.apply(sys.argv[2:])
    else:                        # 默认：Web 控制台 + 打开浏览器
        import console_main; console_main.run()
```

`web_console.py` 里的 Popen 相应改成：

```python
if getattr(sys, "frozen", False):
    cmd = [sys.executable, "--worker"]
else:
    cmd = [sys.executable, "-u", "app.py", "--worker"]
```

`main.py` 的 `if __name__ == "__main__":`（751-977 行）整段抽成 `def run():`，供 `--worker` 调用，逻辑不动。

### 2.4 路径抽象层（新增 `paths.py`）

```python
import os, sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

def app_dir() -> Path:
    """可写数据根目录：冻结时 = exe 所在目录，开发时 = 项目目录"""
    return Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent

def resource_dir() -> Path:
    """只读资源根目录：冻结时 = _MEIPASS，开发时 = 项目目录"""
    return Path(getattr(sys, "_MEIPASS", app_dir()))

CONFIG_PATH   = app_dir() / "config.json"
ADMIN_FILE    = app_dir() / "admin.json"
RESULTS_DIR   = app_dir() / "Results"
LOG_DIR       = app_dir() / "log"
PROFILES_ROOT = app_dir() / "browser_profiles"
NAMES_FILE    = resource_dir() / "app_data" / "english_name_generator.txt"
```

然后把 §1.1 表格里的 8 处全部换成从 `paths` 导入。这是个纯机械替换，但必须一处不漏 —— 漏一处的表现是「结果写进了临时目录，重启后消失」，很难查。

**写权限自检**：启动时往 `app_dir()` 试写一个探针文件。失败（比如用户放在 `C:\Program Files`）就明确报错提示换目录，而不是静默失败。

### 2.5 首次启动引导

1. `config.json` 不存在 → 从 `resource_dir()/config.example.json` 复制。
2. 建 `Results/`、`log/`、`browser_profiles/`。
3. 写权限探针。
4. 起 Web 控制台，`webbrowser.open("http://127.0.0.1:9090")`。
5. 控制台首次访问引导创建管理员账号（现有逻辑，`web_console.py:79-96`）。

**安全说明**：控制台默认绑 `127.0.0.1`，仅本机可访问。exe 版不暴露 `--host` 参数，避免用户误开 `0.0.0.0` —— 现有鉴权是 HTTP 明文，凭据和 session token 过公网会被嗅探。需要远程访问就走 SSH 隧道。

### 2.6 版本号与手动更新

**版本定义** —— 新增 `version.py`：

```python
VERSION = "1.0"                 # 手动递增：1.0 → 1.1 → 1.2
GITHUB_REPO = "zhonggy/OutlookRegister"
```

控制台标题栏显示 `OutlookRegister v1.0`，同时写进 PyInstaller 的 `version_info`（右键属性可见）。

**GitHub Release 约定** —— 每次发版打 tag `v1.1`，上传两个 asset：

| Asset | 内容 | 体积 | 用途 |
| --- | --- | --- | --- |
| `OutlookRegister-v1.1-full.7z` | 完整包（含 Chromium） | ~220MB | 全新安装 |
| `OutlookRegister-v1.1-patch.zip` | 只有 exe + `_internal/`（不含 `browsers/`） | ~40MB | 日常更新 |

Chromium 极少变，日常更新只推 patch 包。Chromium 需要换版本时在 release body 里标注 `REQUIRES_FULL`，更新器识别到就提示用户手动下完整包。

**更新流程**（控制台「系统设置」加一个面板）：

1. `GET https://api.github.com/repos/zhonggy/OutlookRegister/releases/latest`
   - 请求走 `config.json` 里配的代理（GitHub API 在国内经常不通），带 15s 超时。
   - 仓库若是私有，需要 PAT，在配置里加可选 `update.github_token`。**当前仓库可见性需要确认**。
2. 比较 `tag_name`（去掉 `v`）与本地 `VERSION`，用元组数值比较而非字符串比较（否则 `1.10 < 1.9`）。
3. 有新版 → 展示版本号 + release body 作为更新日志 + 包大小，等用户点确认。
4. 下载 patch zip 到 `app_dir()/update_staging/`，显示进度。
5. 校验：`Content-Length` 对得上 + SHA256 与 release body 里公布的值一致。校验失败就删掉并报错。
6. 解压到 `update_staging/extracted/`。
7. **落地（关键）**：运行中的 exe 无法覆盖自己。生成 `update_staging/apply.bat`：
   - 轮询等当前 PID 退出（`tasklist` 或 `timeout` + 重试）
   - `robocopy extracted\ <app_dir>\ /E /IS /IT` 覆盖程序文件
   - **白名单排除**：`config.json`、`admin.json`、`Results\`、`log\`、`browser_profiles\`、`.push_state`、`browsers\`
   - 删 `update_staging/`
   - 重启 `OutlookRegister.exe`
8. `apply.bat` 以 `DETACHED_PROCESS` 启动后，主进程立即退出。

安全前提：**更新前先停掉正在运行的注册任务**，否则子进程还占着 `_internal/` 里的 DLL，robocopy 会失败。

**回滚**：覆盖前把旧的 `OutlookRegister.exe` + `_internal/` 移到 `backup_v1.0/`，覆盖成功后保留一份，下次更新时删掉上上一版。占额外 ~40MB，换来更新失败时能手动恢复。

### 2.7 密钥清理

- `.gitignore` 已正确排除 `config.json`/`admin.json`/`Results/`/`log/`（`git ls-files` 已确认未被追踪），这块无需改动。
- **构建脚本必须显式排除** `config.json`、`admin.json`、`.push_state`、`Results/`、`log/`、`browser_profiles/`。当前 `config.json` 里有 temp_mail 管理员密码和 OutlookManager 的 `api_key` 明文，误打包进 release 等于公开泄露。
- 构建后加一道自检：扫描 `dist/` 全部文件，grep 已知敏感串（api_key 前缀 `omk_`、`admin_password` 的值），命中就让构建失败。
- `config.example.json` 补上 `type`、`admin_email`、`browser.*`、`page_open_timeout`、`resin`、`outlook_manager`、新增的 `proxy_pool` / `update` 字段 —— 当前模板已经落后于实际 `config.json` 的结构。

### 2.8 代理池路径可配

`start_local.py:19-21` 硬编码 `D:/out/easy_proxies`。改为读 config：

```json
"proxy_pool": {
  "enabled": false,
  "exe_path": "",
  "config_path": "",
  "manage_port": 9091
}
```

`enabled=false` 或 `exe_path` 不存在 → 跳过，只起控制台。控制台的连通检查里显示「代理池未配置」而不是报错。

---

## 三、构建配置

### 3.1 环境

- 当前解释器是 **Python 3.13.5**（`D:\py`）。PyInstaller 对 3.13 支持要 ≥6.11，构建前确认版本。
- 用干净 venv 构建，只装实际需要的：`faker`、`requests`、`patchright`。**不装 `playwright`**（§1.6）。
- 打包必须在 Windows 上做，PyInstaller 不支持交叉编译。

### 3.2 `OutlookRegister.spec` 要点

```python
datas = [
    ("english_name_generator.txt", "app_data"),
    ("config.example.json", "."),
]
datas += collect_data_files("patchright")      # 含 driver/node.exe
datas += collect_data_files("faker")

# 内置 Chromium：从 %LOCALAPPDATA%\ms-playwright 复制
datas += [(chromium_src, "browsers/chromium-1169"),
          (winldd_src,   "browsers/winldd-1007")]

hiddenimports = collect_submodules("faker")

excludes = ["playwright", "tkinter", "unittest", "pydoc", "test",
            "email.test", "distutils", "setuptools", "pip"]

exe = EXE(..., console=True, icon="app.ico",
          version="version_info.txt", upx=False)
```

- **`upx=False` 必须**。UPX 压缩 `node.exe` 和 Chromium 的 DLL 会导致启动崩溃，且大幅提高杀软误报率。
- `console=True` 起步（能看到报错）。稳定后可以考虑改 `False`，但那时必须给 `--worker` 子进程加 `CREATE_NO_WINDOW`，否则每个注册任务弹一个黑窗。
- `collect_data_files("patchright")` 要验证 `driver/node.exe` 真的进去了 —— PyInstaller 有时会漏掉 `.exe` 后缀的数据文件。

### 3.3 `build.py`（一键构建）

1. 校验 venv 依赖 + PyInstaller 版本
2. 定位 `%LOCALAPPDATA%\ms-playwright`，找不到 `chromium-1169` 就报错并提示跑 `patchright install chromium`
3. 清理 `build/`、`dist/`
4. `PyInstaller OutlookRegister.spec`
5. 敏感信息自检（§2.7）
6. 冒烟测试：起 exe → 探测 9090 端口 → 拉 `/api/status` → 关掉
7. 打 `dist/OutlookRegister-v{VERSION}-full.7z` 和 `-patch.zip`，输出各自 SHA256（贴到 release body）

---

## 四、实施步骤

分成 5 步，每步结束都可运行、可验证。

### Step 1 — 路径抽象（不改行为）

- 新增 `paths.py`
- 替换 §1.1 的 8 处 `__file__` 定位 + §1.2 的 cwd 依赖
- 新增 `version.py`
- 验证：源码方式跑 `python main.py` 和 `python web_console.py`，行为与现在完全一致，日志/结果写在项目目录

### Step 2 — 入口重构

- 新增 `app.py`（多模式分发）
- `main.py` 的 `__main__` 块抽成 `run()`
- `web_console.py` 的 Popen 改成 frozen 感知；顺手修 §1.7 的 `CTRL_BREAK_EVENT` 优雅停止
- `start_local.py` 的代理池路径改为可配
- 验证：`python app.py` 起控制台、点「开始注册」能正常起 worker、点「停止」能在日志里看到汇总行

### Step 3 — 首次打包

- 建干净 venv，写 `version_info.txt`、`app.ico`、`OutlookRegister.spec`、`build.py`
- 跑通构建
- 验证（**必须在一台没装过 Python 和 Chromium 的干净 Windows 上做**）：解压 → 双击 → 生成 config → 创建管理员 → 完整跑 1 个注册任务到写出 `refresh_token`
- 这一步是最容易卡住的，预期要反复调 Chromium 路径和 patchright driver 的收集

### Step 4 — 更新机制

- `updater.py`：检查 / 下载 / 校验 / 生成 `apply.bat` / 备份回滚
- 控制台加「关于与更新」面板
- 验证：手工造一个 v1.1 的 patch zip 传到 release，从 v1.0 完整走一遍更新 → 重启后版本号变 v1.1、`config.json` 和 `Results/` 完好无损

### Step 5 — 分发打磨

- 7z 自解压单文件安装包
- `使用说明.txt`
- 删 `新建 文本文档.txt`
- 打第一个正式 tag `v1.0`

---

## 五、风险清单

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| patchright driver 收集不全（`node.exe` 缺失/路径错） | exe 起不了浏览器 | Step 3 的首要验证项；必要时写自定义 PyInstaller hook 手动 `Tree()` 整个 `driver/` |
| headless 模式缺 `chromium_headless_shell` | 勾选无头就崩 | 实测 `channel="chromium"`；不行就多打 197MB |
| `channel="chromium"` 下 `--fingerprint` 失效 | 指纹伪装白瘸 | 实测；失效则退回打包两个二进制 |
| 杀软误报（PyInstaller + 未签名 + 自动化浏览器） | 用户直接被拦 | `upx=False` 已降低一部分；发布前过 VirusTotal；长期方案是买代码签名证书 |
| 用户装到 `C:\Program Files` | 无写权限，静默失败 | §2.4 写权限探针，明确报错 |
| 更新时 worker 进程占着 DLL | robocopy 失败，更新装到一半 | 更新前强制停任务；备份 + 回滚 |
| GitHub API 国内不通 | 检查更新超时 | 走 config 代理；超时给明确提示而非卡死 |
| 仓库私有导致 release 拉不到 | 更新功能不可用 | 确认仓库可见性；私有则加可选 PAT 配置 |
| 分发包 220MB+ | 下载体验差 | patch/full 双 asset，日常只更新 40MB |

---

## 六、合规提醒

批量自动注册 Microsoft 账号违反其服务条款，账号和出口 IP 都有被封禁的风险。打包成 exe 会显著降低使用门槛、扩大分发范围，相应地也放大了这个风险和你作为分发者的责任。这是既有项目的既有性质，本规划只涉及打包工程，不改变其行为。
