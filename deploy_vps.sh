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
#   MGMT_LISTEN="0.0.0.0:9091"       WebUI 监听地址（默认允许 VPS 外部访问）
#   EP_REBUILD=1                     强制重新编译 easy_proxies（旧版升级时用）
#   PORT_END=24024                   端口池上限（默认 24024）
#   TEMP_MAIL="1"                    写 cloud_mail 临时邮箱配置到 config.json（配合下面4个必填）
#   TEMP_MAIL_URL / TEMP_MAIL_ADMIN / TEMP_MAIL_PASS / TEMP_MAIL_DOMAIN
#   TASKS=100                        OutlookRegister 任务数（默认 100）
#   HEADLESS=1                       无头模式（默认 1）
# ============================================================
set -euo pipefail

GO_VERSION="1.26.5"
EP_REPO="https://github.com/zhonggy/easy-proxies.git"
EP_BUILD_DIR="/opt/easy_proxies/src"
OR_REPO="https://github.com/zhonggy/OutlookRegister.git"
EP_DIR="/opt/easy_proxies"
OR_DIR="/opt/OutlookRegister"
GO_DIR="/opt/go"

SUBS="${SUBSCRIPTIONS:-}"
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

# ---------- 1. easy_proxies（源码编译，含 WebUI 首次访问创建管理员） ----------
log "部署 easy_proxies（源码编译）"
mkdir -p "${EP_DIR}/logs"

# 决定是否需要编译/重编译：
#   - 二进制不存在（首次部署）
#   - EP_REBUILD=1（强制，旧版部署升级时用）
#   - 源码 pull 后 commit 与上次编译的不同（日常更新）
NEED_BUILD=0
if [ ! -x "${EP_DIR}/easy_proxies" ]; then
    NEED_BUILD=1
elif [ "${EP_REBUILD:-0}" = "1" ]; then
    NEED_BUILD=1
    log "EP_REBUILD=1 → 强制重新编译"
elif [ -d "${EP_BUILD_DIR}/.git" ]; then
    git -C "${EP_BUILD_DIR}" pull -q || true
    CUR=$(git -C "${EP_BUILD_DIR}" rev-parse HEAD 2>/dev/null || echo "")
    BUILT=$(cat "${EP_DIR}/.built_commit" 2>/dev/null || echo "")
    if [ -n "${CUR}" ] && [ "${CUR}" != "${BUILT}" ]; then
        NEED_BUILD=1
        log "检测到 easy_proxies 源码更新（${BUILT} → ${CUR}）"
    else
        log "easy_proxies 已是最新（${CUR}），跳过编译"
    fi
else
    warn "easy_proxies 二进制已存在但无源码目录（旧版部署？）。如需升级请用 EP_REBUILD=1"
fi

if [ "${NEED_BUILD}" = "1" ]; then
    # 安装 Go（项目要求 Go 1.24+）
    if [ ! -x "${GO_DIR}/go/bin/go" ]; then
        log "安装 Go ${GO_VERSION}"
        mkdir -p "${GO_DIR}"
        wget -q "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz
        tar -C "${GO_DIR}" -xzf /tmp/go.tar.gz
        rm -f /tmp/go.tar.gz
    fi
    export PATH="${GO_DIR}/go/bin:$PATH"
    export GOPROXY="https://goproxy.cn,direct"

    if [ ! -d "${EP_BUILD_DIR}/.git" ]; then
        git clone -q "${EP_REPO}" "${EP_BUILD_DIR}"
    else
        git -C "${EP_BUILD_DIR}" pull -q || true
    fi
    log "编译 easy_proxies（sing-box 依赖较多，首次约 5-10 分钟）"
    (cd "${EP_BUILD_DIR}" && CGO_ENABLED=0 go build -tags "with_utls with_quic with_grpc with_clash_api" -o "${EP_DIR}/easy_proxies" .)
    chmod +x "${EP_DIR}/easy_proxies"
    CUR=$(git -C "${EP_BUILD_DIR}" rev-parse HEAD 2>/dev/null || echo "")
    [ -n "${CUR}" ] && echo "${CUR}" > "${EP_DIR}/.built_commit"
    log "easy_proxies 编译完成"
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
        echo "    password: """
        echo "    pprof_enabled: false"
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
    # 仅更新管理端监听地址；账号密码由首次访问 WebUI 时创建（不写回本文件）
    if grep -qE '^management:' "${EP_DIR}/config.yaml"; then
        sed -i -E "/^management:/,/^[^[:space:]]/ s|^([[:space:]]+)listen:.*|\\1listen: ${MGMT_LISTEN}|" "${EP_DIR}/config.yaml" || true
        log "已更新 management.listen=${MGMT_LISTEN}"
    else
        warn "config.yaml 没有 management 配置，请手动设置 management.listen=${MGMT_LISTEN}"
    fi
fi

warn "WebUI 监听 ${MGMT_LISTEN}（公网可访问）。首次访问 http://VPS_IP:9091 时请在网页上创建管理员账号和密码。"

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

log "配置 systemd 服务 outlook_register_web（Web 控制台，端口 9090）"
cat > /etc/systemd/system/outlook_register_web.service <<EOF
[Unit]
Description=OutlookRegister Web Console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${OR_DIR}
ExecStart=${OR_DIR}/.venv/bin/python web_console.py --host 0.0.0.0 --port 9090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------- 3. 启动 ----------
systemctl daemon-reload
systemctl enable -q easy_proxies outlook_register outlook_register_web 2>/dev/null || true
systemctl restart easy_proxies
log "easy_proxies 已启动（节点测试需要几分钟，之后 24000+ 端口才会监听）"
systemctl restart outlook_register_web
log "Web 控制台已启动: http://VPS_IP:9090"
systemctl status easy_proxies --no-pager | head -6 || true

echo
echo "======================================================"
echo " 部署完成！接下来："
echo " 0) 打开浏览器访问 http://VPS_IP:9090 （OutlookRegister Web 控制台，首次访问创建管理员）"
echo "    在此配置 config.json、启动注册、查看日志、下载成果"
echo " 1) 打开浏览器访问 http://VPS_IP:9091 （easy_proxies 代理池，首次访问创建管理员）"
echo "    在 WebUI 里粘贴订阅、等节点测试、确认多端口就绪"
echo " 2) 等节点测试：  tail -f ${EP_DIR}/logs/easy_proxies.log"
echo "    ss -tlnp | grep 24000    （看端口池就绪）"
echo " 3) 确认通过节点数 N，若实际端口 > ${PORT_END}，改 Web 控制台系统设置里的 port_end"
echo " 4) 检查 Web 控制台系统设置（temp_mail 密码等）"
echo " 5) 在 Web 控制台点开始注册，或 systemctl start outlook_register"
echo "    看日志：     journalctl -u outlook_register -f"
echo " 6) 结果：       ${OR_DIR}/Results/oauth2.txt（Web 控制台可下载）"
echo "======================================================"
