# Windows 服务器部署指南（DD 成 Windows 后）

> 在一台 Windows 服务器上安装 **easy_proxies（代理池）** + **OutlookRegister（注册机 + Web 控制台）**。

---

## 一、前置（一次性）

1. **Python 3.10+**：https://www.python.org/downloads/ 安装时**勾选 "Add python.exe to PATH"**
2. **Git for Windows**：https://git-scm.com/download/win 一路默认

## 二、一键安装

在服务器上（PowerShell 或 CMD）：

```bat
curl -L -o install_windows.bat https://raw.githubusercontent.com/zhonggy/OutlookRegister/main/install_windows.bat
install_windows.bat
```

脚本自动完成：
- 下载 **easy_proxies v2.2.1 Windows 版** → `D:\easy_proxies\`
- clone **OutlookRegister** → `D:\OutlookRegister\`
- 建 venv + pip 装依赖 + `patchright install chromium`（浏览器）
- 生成 `config.yaml` / `config.json` 模板

## 三、改配置

| 文件 | 要改什么 |
|---|---|
| `D:\easy_proxies\config.yaml` | `subscriptions:` 填你的订阅地址；`management.password:` 设 9091 登录密码 |
| `D:\OutlookRegister\config.json` | `temp_mail`（cloud_mail 的 URL/管理员/密码）、端口范围按实际节点数 |

## 四、启动

```bat
start_all.bat
```

- **9090** → 注册机控制台（首次访问创建管理员账号）
- **9091** → 代理池 WebUI（密码 = config.yaml 的 management.password）

> `install_windows.bat` / `start_all.bat` 在仓库根目录，也可单独下载。

## 五、开机自启（可选）

任务计划程序建两个任务（登录时运行 / 系统启动时运行）：
- `D:\easy_proxies\easy_proxies.exe --config D:\easy_proxies\config.yaml`（工作目录 D:\easy_proxies）
- `D:\OutlookRegister\.venv\Scripts\python web_console.py --host 0.0.0.0 --port 9090`（工作目录 D:\OutlookRegister）

## 六、防火墙

Windows 防火墙放行 **9090、9091**（入站 TCP）：

```powershell
New-NetFirewallRule -DisplayName "Registrar 9090" -Direction Inbound -Protocol TCP -LocalPort 9090 -Action Allow
New-NetFirewallRule -DisplayName "Registrar 9091" -Direction Inbound -Protocol TCP -LocalPort 9091 -Action Allow
```

## 七、使用流程

1. `http://服务器IP:9091` → 密码登录 → 添加订阅 → 等节点测试 → **连通性检查选 outlook** 筛能过微软的节点
2. `http://服务器IP:9090` → 创建管理员 → 系统设置（代理端口池 24000 起、浏览器指纹开启）→ 启动注册

## 常见问题

| 现象 | 处理 |
|---|---|
| 节点全 `[Fail:IP]` 秒失败 | 端口池范围和 easy-proxies 实际端口不匹配；或节点连不上 |
| 节点 35s 超时 `[Fail:IP]` | 节点渲染不出页面，用 9091 的 outlook 连通性检查筛节点 |
| 验证码全失败 `b2=click:0%` | 微软验证码形态变化，纯自动点击过不去——考虑接打码平台或半自动 |
| 日志中文乱码 | 已修复（子进程强制 UTF-8），更新到最新代码即可 |
