#!/usr/bin/env bash
# ============================================================
# VPS 一键部署：easy_proxies (代理池) + OutlookRegister
# 适用：Ubuntu 22.04 / 24.04
#
# 用法：
#   sudo bash deploy_vps.sh
#
# 可选环境变量（不传则生成模板后手动编辑）：
#   SUBSCRIPTIONS="url1,url2,url3"   订阅地址（逗号分隔）
#   MGMT_PASSWORD="xxx"              easy_proxies 管理端密码（公网监听时强烈建议填写）
#   MGMT_LISTEN="0.0.0.0:9091"       WebUI 监听地址（默认允许 VPS 外部访问）
#   PORT_END=24024                   端口池上限（默认 24024）
#   TEMP_MAIL="1"                    写 cloud_mail 临时邮箱配置到 config.json（配合下面4个必填）
#   TEMP_MAIL_URL / TEMP_MAIL_ADMIN / TEMP_MAIL_PASS / TEMP_MAIL_DOMAIN
#   TASKS=100                        OutlookRegister 任务数（默认 100）
#   HEADLESS=1                       无头模式（默认 1）
# ============================================================
set -euo pipefail

EP_VERSION="v2.2.1"
EP_ASSET="easy_proxies-v2.2.1-linux-amd64"
EP_RELEASE_URL="https://github.com/daimon3332/easy-proxies/releases/download/${EP_VERSION}/${EP_ASSET}"
OR_REPO="https://github.com/zhonggy/OutlookRegister.git"
EP_DIR="/opt/easy_proxies"
OR_DIR="/opt/OutlookRegister"

SUBS="${SUBSCRIPTIONS:-}"
MGMT_PASS="${MGMT_PASSWORD:-}"
MGMT_LISTEN="${MGMT_LISTEN:-0.0.0.0:9091}"
PORT_END="${PORT_END:-24024}"
TASKS="${TASKS:-100}"
HEADLESS="${HEADLESS:-1}"

log()  { echo -e "\033[1;32m[+] $*\033[0m"; }
warn() { echo -e "\033[1;33m[!] $*\033[0m"; }
die()  { echo -e "\033[1;31m[x] $*\033[0m" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 或 sudo 运行"

# ---------- 0. 系统依赖 ----------
log "安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl wget python3 python3-venv python3-pip >/dev/null

# ---------- 1. easy_proxies ----------
log "部署 easy_proxies ${EP_VERSION}"
mkdir -p "${EP_DIR}/logs"
if [ ! -x "${EP_DIR}/easy_proxies" ]; then
    wget -q "${EP_RELEASE_URL}" -O "${EP_DIR}/easy_proxies"
    chmod +x "${EP_DIR}/easy_proxies"
    log "已下载 easy_proxies 二进制"
else
    log "easy_proxies 已存在，跳过下载"
fi

if [ ! -f "${EP_DIR}/config.yaml" ]; then
    log "生成 easy_proxies config.yaml"
    {
        echo "mode: multi-port"
        echo "listener:"
        echo "    address: 127.0.0.1"
        echo "    port: 2323"
        echo "    username: \"\""
        echo "    password: \"\""
        echo "multi_port:"
        echo "    address: 127.0.0.1"
        echo "    base_port: 24000"
        echo "    username: \"\""
        echo "    password: \"\""
        echo "pool:"
        echo "    mode: rotate"
        echo "    failure_threshold: 2"
        echo "    blacklist_duration: 10m0s"
        echo "    rotation_interval: 2m0s"
        echo "management:"
        echo "    enabled: true"
        echo "    listen: ${MGMT_LISTEN}"
        echo "    probe_target: https://www.gstatic.com/generate_204"
        echo "    password: \"${MGMT_PASS}\""
        echo "subscription_refresh:"
        echo "    enabled: true"
        echo "    interval: 1h0m0s"
        echo "    timeout: 30s"
        echo "    health_check_timeout: 5s"
        echo "    drain_timeout: 30s"
        echo "    min_available_nodes: 1"
        echo "log:"
        echo "    output: stdout"
        echo "    file: logs/easy_proxies.log"
        echo "    max_size: 50"
        echo "    max_backups: 3"
        echo "    max_age: 7"
        echo "    compress: false"
        echo "nodes: []"
        echo "nodes_file: \"\""
        if [ -n "${SUBS}" ]; then
            echo "subscriptions:"
            IFS=',' read -ra _subs <<< "${SUBS}"
            for s in "${_subs[@]}"; do
                echo "    - ${s}"
            done
        else
            echo "subscriptions: []"
        fi
        echo "external_ip: \"\""
        echo "log_level: \"\""
        echo "skip_cert_verify: false"
    } > "${EP_DIR}/config.yaml"
    if [ -z "${SUBS}" ]; then
        warn "未提供 SUBSCRIPTIONS → 请编辑 ${EP_DIR}/config.yaml 填入订阅地址（subscriptions: 段）"
    fi
else
    log "config.yaml 已存在，保留订阅配置"
    # 更新管理端监听地址；不会修改订阅、节点池等其他配置。
    if grep -qE '^management:' "${EP_DIR}/config.yaml"; then
        sed -i -E "/^management:/,/^[^[:space:]]/ s|^([[:space:]]+)listen:.*|\\1listen: ${MGMT_LISTEN}|" "${EP_DIR}/config.yaml" || true
        if [ -n "${MGMT_PASS}" ]; then
            sed -i -E "/^management:/,/^[^[:space:]]/ s|^([[:space:]]+)password:.*|\\1password: \"${MGMT_PASS}\"|" "${EP_DIR}/config.yaml" || true
        fi
        log "已更新 management.listen=${MGMT_LISTEN}"
    else
        warn "config.yaml 没有 management 配置，请手动设置 management.listen=${MGMT_LISTEN}"
    fi
fi

if [[ "${MGMT_LISTEN}" == "0.0.0.0:"* && -z "${MGMT_PASS}" ]]; then
    warn "管理端已公网监听但未设置 MGMT_PASSWORD，建议立即设置密码并限制防火墙来源 IP"
fi

log "配置 systemd 服务 easy_proxies"
cat > /etc/systemd/system/easy_proxies.service <<EOF
[Unit]
Description=Easy Proxies
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${EP_DIR}
ExecStart=${EP_DIR}/easy_proxies --config ${EP_DIR}/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------- 2. OutlookRegister ----------
log "部署 OutlookRegister"
if [ ! -d "${OR_DIR}/.git" ]; then
    git clone -q "${OR_REPO}" "${OR_DIR}"
    log "已 clone OutlookRegister"
else
    log "OutlookRegister 已存在，执行 git pull"
    git -C "${OR_DIR}" pull -q || warn "git pull 失败（忽略，继续）"
fi

cd "${OR_DIR}"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
log "安装 patchright 浏览器（含系统库，耗时较长）"
patchright install --with-deps chromium || patchright install chromium

if [ ! -f "${OR_DIR}/config.json" ]; then
    log "生成 OutlookRegister config.json"
    python3 - "${PORT_END}" "${TASKS}" "${HEADLESS}" "${TEMP_MAIL:-0}" <<'PY'
import json, os, sys
port_end, tasks, headless, use_tm = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4] == "1"

cfg = {
    "email_suffix": "@outlook.com",
    "headless": headless,
    "bot_protection_wait": 15,
    "max_captcha_retries": 3,
    "captcha_strategy": 0,
    "concurrent_flows": 1,
    "tasks": tasks,
    "success_tasks": None,
    "batch_success_limit": 300,
    "proxy": {
        "mode": "multiple",
        "type": "http",
        "host": "127.0.0.1",
        "single_port": 0,
        "port_start": 24000,
        "port_end": port_end,
        "max_per_proxy": 5
    },
    "oauth2": {
        "enable_oauth2": True,
        "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
        "redirect_url": "http://localhost",
        "Scopes": ["offline_access", "https://graph.microsoft.com/.default"]
    },
    "temp_mail": {
        "enabled": use_tm,
        "type": "cloud_mail",
        "base_url": os.environ.get("TEMP_MAIL_URL", ""),
        "admin_email": os.environ.get("TEMP_MAIL_ADMIN", ""),
        "admin_password": os.environ.get("TEMP_MAIL_PASS", ""),
        "domain": os.environ.get("TEMP_MAIL_DOMAIN", ""),
        "name_prefix": os.environ.get("TEMP_MAIL_PREFIX", "orx"),
        "enable_prefix": True,
        "code_timeout": 120,
        "poll_interval": 3
    }
}
with open("config.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("config.json 已生成")
PY
    warn "请检查 ${OR_DIR}/config.json：temp_mail.admin_password 需手动填写"
else
    log "config.json 已存在，保留"
fi

log "配置 systemd 服务 outlook_register（单次批跑）"
cat > /etc/systemd/system/outlook_register.service <<EOF
[Unit]
Description=OutlookRegister batch
After=easy_proxies.service

[Service]
Type=simple
WorkingDirectory=${OR_DIR}
ExecStart=${OR_DIR}/.venv/bin/python main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# ---------- 3. 启动 ----------
systemctl daemon-reload
systemctl enable -q easy_proxies outlook_register 2>/dev/null || true
systemctl restart easy_proxies
log "easy_proxies 已启动（节点测试需要几分钟，之后 24000+ 端口才会监听）"
systemctl status easy_proxies --no-pager | head -6 || true

echo
echo "======================================================"
echo " 部署完成！接下来："
echo " 1) 等节点测试：  tail -f ${EP_DIR}/logs/easy_proxies.log"
echo "    ss -tlnp | grep 24000    （看端口池就绪）"
echo " 2) 确认通过节点数 N，若实际端口 > ${PORT_END}，改 ${OR_DIR}/config.json 的 port_end"
echo " 3) 检查 ${OR_DIR}/config.json（temp_mail 密码等）"
echo " 4) 跑一批：     systemctl start outlook_register"
echo "    看日志：     journalctl -u outlook_register -f"
echo " 5) 结果：       ${OR_DIR}/Results/oauth2.txt"
echo "======================================================"
