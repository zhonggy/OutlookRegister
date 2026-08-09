# VPS 一键部署指南（deploy_vps.sh）

> 一条命令在 VPS 上部署 **easy_proxies（代理池）** + **OutlookRegister（注册机 + Web 控制台）**。
> 适用：Ubuntu 22.04 / 24.04

---

## 🚀 一键部署

```bash
curl -fsSL https://raw.githubusercontent.com/zhonggy/OutlookRegister/main/deploy_vps.sh | sudo bash
```

> ⚠️ 9091 代理池是官方版认证，**没有首次创建密码**：部署后必须设置 `management.password`，否则 9091 无密码开放。
> 方式一：部署时带密码 `curl ... | sudo MGMT_PASSWORD="你的密码" bash`
> 方式二：部署后 `sudo nano /opt/easy_proxies/config.yaml` 改 management.password

### 可选环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SUBSCRIPTIONS` | 空 | 代理订阅地址，逗号分隔（不传则部署后在 WebUI 添加） |
| `MGMT_PASSWORD` | 空 | easy_proxies 9091 密码（**建议必填**，否则无密码开放） |
| `PORT_END` | `24024` | 注册机端口池上限（按实际节点数调整） |
| `TASKS` | `100` | 注册任务数（可在控制台改） |
| `TEMP_MAIL=1` | 关 | 启用临时邮箱，配合 `TEMP_MAIL_URL / TEMP_MAIL_ADMIN / TEMP_MAIL_PASS / TEMP_MAIL_DOMAIN` |

---

## 📦 部署内容

| 组件 | 位置 | 端口 | 说明 |
|---|---|---|---|
| easy_proxies（官方 v2.2.1） | `/opt/easy_proxies` | **9091** | 代理池 WebUI：订阅导入、测速、多端口池（24000 起） |
| OutlookRegister | `/opt/OutlookRegister` | — | 注册机本体 |
| Web 控制台 | `/opt/OutlookRegister/web_console.py` | **9090** | 配置 config.json、启动注册、实时日志、下载成果 |

systemd 服务：
- `easy_proxies`（常驻）
- `outlook_register_web`（常驻，9090 控制台）
- `outlook_register`（单次批跑，控制台启动时无需手动开）

---

## 🖥️ 部署后使用

1. **9090 注册机控制台** → `http://VPS_IP:9090`
   - 首次访问：创建管理员账号 + 密码
   - 系统设置：填好代理（端口池 24000 起）、临时邮箱等
   - 启动注册：设注册数量/并发 → 开始注册 → 看进度和实时日志

2. **9091 代理池** → `http://VPS_IP:9091`
   - 用 `MGMT_PASSWORD` 登录（官方版认证）
   - 添加订阅 → 等节点测试 → 「连通性检查」选 outlook 筛能过微软的节点 → 入池

3. **成果文件**（Web 控制台仪表盘可直接下载）
   - `/opt/OutlookRegister/Results/oauth2.txt`（成功账号 + refresh_token）
   - `/opt/OutlookRegister/Results/recovery_emails.txt`（辅助邮箱）

---

## 🔄 更新

重新跑一遍脚本即可（幂等，不覆盖已有配置/账号/订阅）：

```bash
curl -fsSL https://raw.githubusercontent.com/zhonggy/OutlookRegister/main/deploy_vps.sh | sudo bash
```

---

## ⚠️ 防火墙（GCP 等云厂商）

控制台/安全组放行 TCP **9090、9091**（建议来源限自己 IP）：

```bash
gcloud compute firewall-rules create allow-or-9090 \
  --allow tcp:9090,tcp:9091 \
  --direction INGRESS --priority 1000
```

---

## 🔧 常见问题

| 现象 | 处理 |
|---|---|
| 节点全部秒失败 `[Fail:IP]` | 确认代理池节点能访问 Outlook（`curl -x http://127.0.0.1:24000 https://outlook.live.com` 应返回 4xx/2xx 而非 000）；用 WebUI「连通性检查」outlook 目标筛节点 |
| 9091 登录不了 | 官方版认证用 `management.password`（部署时 `MGMT_PASSWORD` 设置），不是网页创建管理员 |
| 代理池节点 000 | 已换官方 v2.2.1 release（fork 编译版有 DNS bug），若仍异常检查 VPS DNS |
| headless 被微软风控 | 备选 xvfb 有头模式：`apt install xvfb && xvfb-run -a python main.py` |
