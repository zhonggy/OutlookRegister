<h1 align="center">OutlookRegister</h1>

<p align="center">
  Outlook / Hotmail 自动注册，并获取 Microsoft Graph OAuth2 <code>refresh_token</code>（基于 patchright 浏览器自动化）。<br>
  自带桌面界面，Windows 绿色便携版解压即用。
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./README.zh-CN.md"><b>简体中文</b></a> ·
  <a href="./README.zh-TW.md">繁體中文</a>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-green.svg">
  <img alt="patchright" src="https://img.shields.io/badge/Browser-patchright-4B5563">
  <img alt="GUI PySide6" src="https://img.shields.io/badge/GUI-PySide6-41CD52?logo=qt&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-blue">
</p>

## 配套项目

- **[Easy Proxies](https://github.com/daimon3332/easy-proxies)（强烈推荐搭配使用！！！！！！）— 多端口模式必需。** 当 `proxy.mode` 设为 `multiple` 时，为 OutlookRegister 提供本地代理池；使用该模式前请先启动并配置 Easy Proxies。
- **[OutlookManage](https://github.com/daimon3332/OutlookManage) — 账号管理。** 用于导入和管理已注册的 Outlook 账号及其 OAuth2 凭据。
- **[Outlook OAuth GetToken](https://github.com/daimon3332/Outlook-Oauth-GetToken) — 单独获取令牌。** 无需运行注册流程，即可为已有微软邮箱获取 OAuth2 `refresh_token`。

> 本项目基于 **[LainsNL/OutlookRegister](https://github.com/LainsNL/OutlookRegister)** 二开。  
> 增强点包括：可选辅助邮箱绑定、更完整的 OAuth 中间页处理、cookie 优先授权、分批调度，以及 Ctrl+C 中断后的汇总与清理。

---

## 使用教程

### 1. 环境要求

- 打包版：无（Windows 解压即用，内置 Chromium）
- 源码模式：建议 Python 3.10+
- 可用的 HTTP/SOCKS 代理（强烈建议）
- 若开启辅助邮箱绑定：兼容的临时邮箱 / CF Temp Mail 类 API

### 2. 安装

```bash
git clone <本仓库地址>
cd OutlookRegister
pip install -r requirements.txt
patchright install chromium
```

### 3. 配置

```bash
# Windows
copy config.example.json config.json

# Linux / macOS
cp config.example.json config.json
```

编辑 `config.json`：至少填好 **proxy**。对外分享时不要带上真实密钥。

### 4. 运行

**打包版（推荐）** —— 从 [Releases](https://github.com/zhonggy/OutlookRegister/releases) 下载，
解压后双击 `OutlookRegister.exe`。自带桌面界面与内置 Chromium，无需 Python。

**源码模式**

```bash
python app.py              # 启动桌面 GUI
python app.py --worker     # 直接跑注册（无界面，适合服务器）
python app.py --version    # 看版本号
```

成功账号会**追加**写入 `Results/oauth2.txt`：

```text
邮箱----密码----client_id----refresh_token
```

日志在 `log/`。GUI 里点「停止」或命令行按 **Ctrl+C** 可中断：
先写汇总，再关浏览器并清理 profile。

---

## 自己构建 exe

构建在 GitHub Actions（windows-latest）上进行，也可本地跑：

```bash
pip install -r requirements-build.txt
patchright install chromium
python build.py
```

产物在 `artifacts/`：`-full.zip`（含内置 Chromium）与 `-patch.zip`（仅程序文件，用于更新）。

发版：改 `version.py` 的 `VERSION` → 提交 → `git tag v1.1 && git push origin v1.1`。
CI 会校验 tag 与 `version.py` 一致，不一致直接失败。

---

## `config.json` 字段说明

模板见 `config.example.json`（与空的 `config.json` 结构一致）。

### 顶层字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `email_suffix` | string | 注册邮箱后缀，如 `@outlook.com` 或 `@hotmail.com`。 |
| `headless` | bool | `false` 显示浏览器窗口；`true` 无头。 |
| `bot_protection_wait` | number | 填表节奏基准（秒）。代码内会 ×1000 作为等待。 |
| `max_captcha_retries` | number | 验证码按压额外重试次数（约 `max_captcha_retries + 1` 轮 Hold）。 |
| `captcha_strategy` | number | 验证码/交接策略，见下表。 |
| `concurrent_flows` | number | 并发线程数（同时打开的浏览器任务数）。 |
| `tasks` | number | 全局提交任务上限；与 `success_tasks` **任一达标**即结束。 |
| `success_tasks` | number \| null | 全局成功上限。`null` = 不按成功数截断（仍受 `tasks` 限制）。 |
| `batch_success_limit` | number | 单批成功数上限；达到后重置程序内代理权重/统计并开下一批。累计成功/耗时保留。**不会**更换固定代理的真实出口 IP。 |
| `proxy` | object | 代理配置（正式使用必填）。 |
| `oauth2` | object | Graph OAuth2 配置。 |
| `temp_mail` | object | 可选：保护帐户页自动绑定辅助邮箱。 |
| `page_open_timeout` | number | 注册页打开超时（秒），默认 30。 |
| `browser` | object | 浏览器指纹与自定义内核。 |
| `resin` | object | 可选：Resin 外部粘性代理池。 |
| `outlook_manager` | object | 可选：注册成功后自动推送到 OutlookManage。 |
| `proxy_pool` | object | 可选：源码模式下一键启动脚本拉起外部代理池。 |
| `update` | object | 可选：检查更新时的代理与 GitHub Token。 |

### `captcha_strategy`

| 值 | 行为 |
| --- | --- |
| `0` | 全自动（验证码 + 进邮箱 + OAuth）。 |
| `1` | 半自动：你手动过验证码，其余自动。 |
| `2` | 验证码界面出现后交给人工；该任务程序不跑 OAuth。 |

### `proxy`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `mode` | string | `single` 使用 `single_port`；`multiple` 使用 `port_start`～`port_end` 端口池。 |
| `type` | string | 代理协议，如 `http`、`socks5`。 |
| `host` | string | 代理主机，如 `127.0.0.1`。**运行前请填写。** |
| `single_port` | number | `mode=single` 时的端口。 |
| `port_start` | number | `mode=multiple` 时起始端口。 |
| `port_end` | number | `mode=multiple` 时结束端口（含）。 |
| `max_per_proxy` | number | 单个端口在进程内最多被选中次数；用满后暂不选，全满或批次重置后计数清零。 |

### `oauth2`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `enable_oauth2` | bool | `false` 时注册成功即可计成功，不拉 token。 |
| `client_id` | string | 授权与换 token 使用的客户端 ID。 |
| `redirect_url` | string | 重定向 URI（默认 `http://localhost`）。 |
| `Scopes` | string[] | 授权范围，一般为 `offline_access` + Graph 默认范围。 |

### `temp_mail`

仅在微软弹出 **「让我们来保护你的帐户」** 且开启绑定时使用。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `enabled` | bool | `false` = 不自动绑定（出现保护页时走跳过等逻辑）。 |
| `base_url` | string | 临时邮箱 API 根地址。不用则留空。 |
| `admin_password` | string | 创建地址用的管理员密码。**勿公开。** |
| `domain` | string | 新建邮箱域名。 |
| `name_prefix` | string | 本地部分前缀（可选）。 |
| `enable_prefix` | bool | 是否启用 `name_prefix`。 |
| `code_timeout` | number | 等待验证码邮件的超时（秒）。 |
| `poll_interval` | number | 轮询收件箱间隔（秒）。 |

### `browser`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `fingerprint_enabled` | bool | 启用 patchright 指纹伪装（Canvas/WebGL/UA 等）。 |
| `fingerprint_platform` | string | `windows` / `macos` / `linux` / `android` / `ios`。 |
| `fingerprint_brand` | string | `Chrome` / `Edge` / `Firefox` / `Safari`。 |
| `executable_path` | string | 自定义内核路径（如 fingerprint-chromium 的 chrome.exe）。留空用内置 Chromium。 |
| `user_data_root` | string | profile 目录根。留空为程序目录下的 `browser_profiles/`。 |

### `outlook_manager`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `enabled` | bool | 注册成功后自动推送（异步，失败不阻塞注册）。 |
| `api_url` | string | 如 `http://IP:18327/api/v1/ingest/accounts`。 |
| `api_key` | string | OutlookManage 后台创建的密钥（`omk_` 开头）。**勿公开。** |

### `update`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `use_register_proxy` | bool | 检查更新时复用 `proxy` 里的代理。 |
| `proxy` | string | 更新专用代理，优先于上面的选项。 |
| `github_token` | string | 仅仓库为私有时需要。 |

### `proxy_pool`

仅源码模式的 `start_local.py` 使用，打包版不会拉起外部程序。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `enabled` | bool | 启动时先拉起代理池。 |
| `exe_path` | string | 代理池可执行文件完整路径。不存在则跳过。 |
| `config_path` | string | 代理池配置文件路径（可选）。 |
| `manage_port` | number | 管理端端口，用于就绪探测。 |

---

## 项目用途

```text
生成邮箱/密码
  -> 打开注册页并填表
  -> 按压验证码
  ->（可选）绑定辅助邮箱
  -> 进入 Outlook 邮箱
  -> OAuth2（优先 cookie，失败再新浏览器并可注入 cookie）
  -> 将 refresh_token 追加写入 Results/oauth2.txt
```

OAuth 可处理：个人/工作帐户选择、保护帐户、验证电子邮件、保持登录「否」、同意授权与 code 捕获等。

---

## 主要功能

- **桌面 GUI**（PySide6）：仪表盘 / 启动注册 / 系统设置 / 关于与更新四页
- **双进程模型**：界面与注册进程隔离，注册崩溃不影响界面
- 多代理并发注册
- 按批成功上限重置程序内权重
- Cookie 优先 OAuth + 冷启动/新环境兜底
- 可选 temp_mail 辅助邮箱绑定
- 停止/Ctrl+C：先汇总再关浏览器、清 profile
- `log/` 进度与失败分类
- 程序内手动检查更新（从 GitHub Releases 下载，不自动更新）

---

## 项目结构

```text
app.py                  统一入口（无参 = GUI，--worker = 注册进程）
core.py                 业务后端：配置/进程管理/日志/连通测试（不依赖 Qt）
main.py                 注册主流程：并发调度、批次控制、中断汇总
paths.py                路径解析（区分可写数据目录与只读资源目录）
updater.py              手动更新：检查/下载/校验/落地
version.py              版本号与版本比较
gui/                    桌面界面
  theme.py              配色、字体度量、全局样式表
  widgets.py            通用组件（指标卡、键值行、状态行）
  tasks.py              阻塞调用丢后台线程
  views/                四个页面
controllers/            浏览器自动化与 OAuth 流程
```

---

## 上游与致谢

- [LainsNL/OutlookRegister](https://github.com/LainsNL/OutlookRegister) — 本项目二开来源  
- [Microsoft identity platform / Graph](https://learn.microsoft.com/en-us/graph/auth-v2-user) — OAuth2 与 Graph  
- [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) — 浏览器自动化  

---

## 开源协议

本项目采用 [MIT License](./LICENSE)。  
保留对上游 OutlookRegister 及所依赖 MIT 组件的署名说明。

---

## 友情链接

- <a href="https://linux.do"><img src="./linuxdo.webp" width="22" height="22" alt="LINUX DO" align="center"></a> [linux.do](https://linux.do)：**学AI，上L站！！！**
- [Nodeseek.com](https://www.nodeseek.com)：**Nodeseek是一个为热爱web开发、托管、vps /服务器和其他极客事物的人提供的地方。**
