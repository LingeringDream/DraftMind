# ============================================
# DraftMind Frontend - Docker Production Build
# 优先使用国内镜像源，网络错误时自动换源
# ============================================

# ---------- 构建阶段 ----------
FROM node:20-alpine AS builder

# Alpine 国内源 (阿里云)
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories && \
    apk add --no-cache curl bash

WORKDIR /app

# 复制依赖清单
COPY package.json package-lock.json* ./

# npm 镜像源列表（按优先级排序）
ENV NPM_MIRRORS="https://registry.npmmirror.com https://mirrors.cloud.tencent.com/npm/ https://repo.huaweicloud.com/repository/npm/"

# 写入换源脚本并执行安装
RUN set -e; \
    INSTALL_OK=0; \
    for REGISTRY in $NPM_MIRRORS; do \
        echo ""; \
        echo "========================================"; \
        echo " 尝试 npm 源: $REGISTRY"; \
        echo "========================================"; \
        npm config set registry "$REGISTRY" && \
        npm install --legacy-peer-deps 2>/dev/null && \
        INSTALL_OK=1 && \
        echo " 使用源安装成功: $REGISTRY" && \
        break; \
        echo " 源 $REGISTRY 失败，尝试下一个..."; \
    done; \
    if [ "$INSTALL_OK" -ne 1 ]; then \
        echo "========================================"; \
        echo " 所有国内源失败，回退到官方源"; \
        echo "========================================"; \
        npm config set registry https://registry.npmjs.org/ && \
        npm install --legacy-peer-deps; \
    fi

# 复制源码
COPY . .

# 构建参数：可运行时覆盖 API 地址
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:stable-alpine AS production

# Alpine 国内源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
