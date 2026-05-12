#!/usr/bin/env bash
# ============================================
# DraftMind Docker 构建脚本
# 自动检测 Docker / Podman，国内镜像优先
# ============================================

set -euo pipefail

# ---------- 颜色 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------- 检测容器运行时 ----------
detect_runtime() {
    if command -v docker &>/dev/null; then
        echo "docker"
    elif command -v podman &>/dev/null; then
        echo "podman"
    else
        error "未找到 docker 或 podman，请先安装其中之一"
        exit 1
    fi
}

RUNTIME=$(detect_runtime)
info "使用容器运行时: $RUNTIME"

# ---------- Docker Hub 镜像源（自动配置） ----------
configure_mirrors() {
    [ "$RUNTIME" != "docker" ] && return

    MIRRORS='["https://docker.1ms.run","https://docker.xuanyuan.me","https://docker.m.daocloud.io","https://huecker.io","https://dockerhub.timeweb.cloud"]'

    # 判断平台，确定 daemon.json 路径
    if [[ "$OSTYPE" == msys* ]] || [[ "$OSTYPE" == cygwin* ]] || [[ -n "${WINDIR-}" ]]; then
        # Windows (Git Bash / MSYS2)
        DAEMON_JSON="${USERPROFILE:-$HOME}/.docker/daemon.json"
        IS_WINDOWS=1
    elif [[ "$OSTYPE" == darwin* ]]; then
        # macOS — Docker Desktop 通过 Settings 管理，不自动写入
        DAEMON_JSON="$HOME/.docker/daemon.json"
        IS_WINDOWS=0
    else
        # Linux
        DAEMON_JSON="/etc/docker/daemon.json"
        IS_WINDOWS=0
    fi

    # 检查是否已配置
    if [ -f "$DAEMON_JSON" ] && grep -q "registry-mirrors" "$DAEMON_JSON" 2>/dev/null; then
        info "Docker 镜像加速器已配置"
        return
    fi

    info "自动配置 Docker 镜像加速器..."

    # 备份已有配置
    if [ -f "$DAEMON_JSON" ]; then
        cp "$DAEMON_JSON" "${DAEMON_JSON}.bak.$(date +%Y%m%d%H%M%S)"
        info "已备份原有配置"
    fi

    # 确保目录存在
    mkdir -p "$(dirname "$DAEMON_JSON")"

    # 写入镜像配置
    if [ -f "$DAEMON_JSON" ]; then
        # 已有 daemon.json 但没有 registry-mirrors，合并进去
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, sys
with open('$DAEMON_JSON') as f:
    cfg = json.load(f) if f.read().strip() else {}
cfg['registry-mirrors'] = $MIRRORS
with open('$DAEMON_JSON', 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>/dev/null || echo "{\"registry-mirrors\": $MIRRORS}" > "$DAEMON_JSON"
        else
            echo "{\"registry-mirrors\": $MIRRORS}" > "$DAEMON_JSON"
        fi
    else
        echo "{\"registry-mirrors\": $MIRRORS}" > "$DAEMON_JSON"
    fi

    info "已写入 $DAEMON_JSON"

    # 重启 Docker 使配置生效
    if [ "$IS_WINDOWS" = "1" ]; then
        # Windows Docker Desktop
        local docker_cli="/c/Program Files/Docker/Docker/DockerCli.exe"
        if [ -f "$docker_cli" ]; then
            info "正在重启 Docker Desktop..."
            "$docker_cli" -SwitchDaemon 2>/dev/null &
            sleep 8
        else
            warn "请手动重启 Docker Desktop 使配置生效"
        fi
    elif [[ "$OSTYPE" == darwin* ]]; then
        # macOS — 无法自动重启 Docker Desktop
        warn "请手动重启 Docker Desktop 使配置生效"
    else
        # Linux
        if command -v systemctl &>/dev/null; then
            info "正在重启 Docker 服务..."
            sudo systemctl restart docker 2>/dev/null || warn "重启 Docker 失败，请手动执行: sudo systemctl restart docker"
            sleep 3
        fi
    fi

    # 验证
    if $RUNTIME info 2>/dev/null | grep -q "registry-mirrors"; then
        info "镜像加速器配置成功"
    else
        warn "配置已写入，但可能需要手动重启 Docker 后生效"
    fi
}

# ---------- 拉取基础镜像（带重试） ----------
pull_base_images() {
    local images=("node:20-alpine" "nginx:stable-alpine")

    for img in "${images[@]}"; do
        info "拉取基础镜像: $img"
        if ! $RUNTIME pull "$img" 2>/dev/null; then
            warn "拉取 $img 失败，等待 5 秒后重试..."
            sleep 5
            if ! $RUNTIME pull "$img" 2>/dev/null; then
                error "无法拉取 $img，请检查网络连接或配置镜像加速器"
                exit 1
            fi
        fi
    done
}

# ---------- 构建 ----------
build() {
    local api_url="${1:-/api}"

    info "开始构建 DraftMind 前端镜像..."
    info "VITE_API_BASE_URL=$api_url"

    $RUNTIME build \
        --build-arg "VITE_API_BASE_URL=$api_url" \
        -t draftmind-frontend:latest \
        -t draftmind-frontend:$(date +%Y%m%d) \
        .

    info "构建完成！"
    echo ""
    info "运行方式:"
    echo "  $RUNTIME run -d -p 3000:80 --name draftmind draftmind-frontend:latest"
    echo ""
    info "或使用 docker-compose:"
    echo "  docker compose up -d"
}

# ---------- 主流程 ----------
main() {
    cd "$(dirname "$0")"
    configure_mirrors
    pull_base_images
    build "$@"
}

main "$@"
