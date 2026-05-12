"""
DraftMind Django 项目配置
========================

本文件集中管理后端所有配置项，包括：
  - 基础 Django 设置（密钥、调试模式、时区等）
  - 数据库配置（默认 SQLite，可通过环境变量切换）
  - CORS 跨域配置（允许前端访问）
  - AI 模型 API 配置（通义千问 VLM + 文本嵌入）
  - 阿里云 OSS 存储配置（可选）
  - 本地文件存储路径
  - 图纸解析 System Prompt 路径

所有敏感配置均通过 .env 文件注入，不硬编码在代码中。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ================================================================
# 基础路径
# ================================================================
# BASE_DIR 指向项目根目录（即 manage.py 所在目录）
BASE_DIR = Path(__file__).resolve().parent.parent

# 从项目根目录加载 .env 环境变量文件
load_dotenv(BASE_DIR / ".env")

# ================================================================
# Django 核心设置
# ================================================================

# 安全密钥：生产环境务必通过 DJANGO_SECRET_KEY 环境变量设置强密钥
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-draftmind-local-development-key-change-in-production",
)

# 调试模式：默认开启，生产环境应设为 false
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"

# 允许访问的主机列表，生产环境需添加实际域名
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]

# ================================================================
# 已安装的应用
# ================================================================
INSTALLED_APPS = [
    # Django 内置应用
    "django.contrib.admin",           # 管理后台
    "django.contrib.auth",            # 认证系统
    "django.contrib.contenttypes",    # 内容类型框架
    "django.contrib.sessions",        # 会话管理
    "django.contrib.messages",        # 消息框架
    "django.contrib.staticfiles",     # 静态文件服务
    # 第三方应用
    "corsheaders",                    # CORS 跨域支持
    # 项目应用
    "drawings",                       # 图纸解析核心业务
]

# ================================================================
# 中间件
# ================================================================
# 注意：CorsMiddleware 必须放在最前面，才能正确处理 CORS 预检请求
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",           # CORS 跨域处理（必须在最前）
    "django.middleware.security.SecurityMiddleware",   # 安全相关 HTTP 头
    "django.contrib.sessions.middleware.SessionMiddleware",  # 会话处理
    "django.middleware.common.CommonMiddleware",       # 通用请求处理
    "django.middleware.csrf.CsrfViewMiddleware",      # CSRF 防护
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # 用户认证
    "django.contrib.messages.middleware.MessageMiddleware",    # 消息处理
    "django.middleware.clickjacking.XFrameOptionsMiddleware",  # 点击劫持防护
]

# ================================================================
# URL 与模板配置
# ================================================================

# 根 URL 配置模块
ROOT_URLCONF = "draftmind_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# WSGI/ASGI 应用入口
WSGI_APPLICATION = "draftmind_backend.wsgi.application"

# ================================================================
# 数据库配置
# ================================================================
# 默认使用 SQLite（适合本地开发），生产环境可通过环境变量切换为 PostgreSQL 等
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", str(BASE_DIR / "db.sqlite3")),
    }
}

# ================================================================
# 密码验证（管理后台用，API 无影响）
# ================================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ================================================================
# 国际化与时区
# ================================================================
LANGUAGE_CODE = "zh-hans"       # 简体中文
TIME_ZONE = "Asia/Shanghai"     # 中国时区
USE_I18N = True                 # 启用国际化
USE_TZ = True                   # 启用时区感知

# ================================================================
# 静态文件与媒体文件
# ================================================================

# 静态文件（CSS/JS/图片等，开发阶段由 Django 自动服务）
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # collectstatic 收集目标目录

# 媒体文件（用户上传的图纸图片）
MEDIA_URL = "/uploads/"                   # URL 访问前缀
MEDIA_ROOT = BASE_DIR / "uploads"         # 本地存储目录

# 数据持久化目录（JSON 格式的解析结果备份，当前由 ORM 接管）
DATA_DIR = BASE_DIR / "data"

# ================================================================
# Django 其他设置
# ================================================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ================================================================
# CORS 跨域配置
# ================================================================
# 开发阶段允许所有来源访问，生产环境应限制为实际前端域名
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "true").lower() == "true"

# 允许的前端来源列表（CORS_ALLOW_ALL_ORIGINS=false 时生效）
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if origin.strip()
]

# ================================================================
# AI 模型 API 配置（通义千问 OpenAI 兼容接口）
# ================================================================

# API 密钥：从阿里云 DashScope 控制台获取
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# API 基础地址：使用 OpenAI 兼容模式调用通义千问
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# 多模态视觉模型：用于图纸图像解析（需支持图片输入）
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "qwen3-vl-32b-thinking")

# 文本嵌入模型：用于生成向量嵌入（相似推荐/语义搜索）
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v3")

# 模型输出最大 token 数：过小会导致 JSON 截断，过大会浪费额度
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "8021"))

# ================================================================
# 阿里云 OSS 存储配置（可选）
# ================================================================
# 未配置时自动降级为本地 uploads/ 目录存储
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")          # 如 oss-cn-beijing.aliyuncs.com
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY", "")
OSS_ACCESS_SECRET = os.getenv("OSS_ACCESS_SECRET", "")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")

# ================================================================
# 图纸解析 System Prompt
# ================================================================
# 从项目根目录的 main_prompt.md 加载 VLM 解析指令
PROMPT_PATH = BASE_DIR / "main_prompt.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""

# ================================================================
# 后台解析任务配置
# ================================================================
# 线程池并发数：同时处理的图纸解析任务数量
# 生产环境建议替换为 Celery 等持久化任务队列
PARSE_WORKER_COUNT = int(os.getenv("PARSE_WORKER_COUNT", "4"))
