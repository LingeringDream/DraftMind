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

# ---------- Docker Hub 镜像源 ----------
configure_mirrors() {
    MIRRORS=(
        "https://mirror.ccs.tencentyun.com"
        "https://hub-mirror.c.163.com"
        "https://docker.mirrors.ustc.edu.cn"
        "https://registry.docker-cn.com"
    )

    if [ "$RUNTIME" = "docker" ]; then
        DAEMON_JSON="/etc/docker/daemon.json"
        if [ -f "$DAEMON_JSON" ] && grep -q "registry-mirrors" "$DAEMON_JSON" 2>/dev/null; then
            info "Docker 已配置镜像加速器"
            return
        fi

        warn "建议配置 Docker 镜像加速器以提升拉取速度"
        echo "  执行以下命令（需 sudo）:"
        echo ""
        echo '  sudo mkdir -p /etc/docker'
        echo '  sudo tee /etc/docker/daemon.json <<EOF'
        echo '  {'
        echo '    "registry-mirrors": ['
        echo '      "https://mirror.ccs.tencentyun.com",'
        echo '      "https://docker.mirrors.ustc.edu.cn"'
        echo '    ]'
        echo '  }'
        echo 'EOF'
        echo '  sudo systemctl restart docker'
        echo ""
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
