#!/usr/bin/env bash
# ============================================
# Docker 镜像加速器一键配置
# 用于解决国内无法拉取 Docker Hub 镜像的问题
# ============================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

MIRRORS='["https://mirror.ccs.tencentyun.com","https://docker.mirrors.ustc.edu.cn","https://hub-mirror.c.163.com"]'

# ---------- 判断平台 ----------
IS_WINDOWS=0
IS_MAC=0

if [[ "$OSTYPE" == msys* ]] || [[ "$OSTYPE" == cygwin* ]] || [[ -n "${WINDIR-}" ]]; then
    IS_WINDOWS=1
    DAEMON_JSON="${USERPROFILE:-$HOME}/.docker/daemon.json"
elif [[ "$OSTYPE" == darwin* ]]; then
    IS_MAC=1
    DAEMON_JSON="$HOME/.docker/daemon.json"
else
    DAEMON_JSON="/etc/docker/daemon.json"
fi

# ---------- 检查是否已配置 ----------
if [ -f "$DAEMON_JSON" ] && grep -q "registry-mirrors" "$DAEMON_JSON" 2>/dev/null; then
    info "Docker 镜像加速器已配置，无需重复操作"
    exit 0
fi

# ---------- 备份 ----------
if [ -f "$DAEMON_JSON" ]; then
    cp "$DAEMON_JSON" "${DAEMON_JSON}.bak.$(date +%Y%m%d%H%M%S)"
    info "已备份原有配置到 ${DAEMON_JSON}.bak.*"
fi

# ---------- 写入配置 ----------
mkdir -p "$(dirname "$DAEMON_JSON")"

if [ -f "$DAEMON_JSON" ] && command -v python3 &>/dev/null; then
    # 已有配置文件，合并 registry-mirrors 字段
    python3 -c "
import json
with open('$DAEMON_JSON') as f:
    raw = f.read().strip()
    cfg = json.loads(raw) if raw else {}
cfg['registry-mirrors'] = $MIRRORS
with open('$DAEMON_JSON', 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>/dev/null || echo "{\"registry-mirrors\": $MIRRORS}" > "$DAEMON_JSON"
else
    echo "{\"registry-mirrors\": $MIRRORS}" > "$DAEMON_JSON"
fi

info "已写入 $DAEMON_JSON"

# ---------- 重启 Docker ----------
if [ "$IS_WINDOWS" = "1" ]; then
    DOCKER_CLI="/c/Program Files/Docker/Docker/DockerCli.exe"
    if [ -f "$DOCKER_CLI" ]; then
        info "正在重启 Docker Desktop..."
        "$DOCKER_CLI" -SwitchDaemon 2>/dev/null &
        sleep 10
    else
        warn "请手动重启 Docker Desktop 使配置生效"
    fi
elif [ "$IS_MAC" = "1" ]; then
    if [ -d "/Applications/Docker.app" ]; then
        info "正在重启 Docker Desktop..."
        osascript -e 'quit app "Docker"' 2>/dev/null
        sleep 3
        open -a Docker 2>/dev/null
        sleep 10
    else
        warn "请手动重启 Docker Desktop 使配置生效"
    fi
else
    if command -v systemctl &>/dev/null; then
        info "正在重启 Docker 服务..."
        sudo systemctl restart docker
        sleep 3
    fi
fi

# ---------- 验证 ----------
if docker info 2>/dev/null | grep -q "registry-mirrors"; then
    info "配置完成，镜像加速器已生效"
else
    warn "配置已写入，请手动重启 Docker 后运行 docker info 验证"
fi
