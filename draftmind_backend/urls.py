"""DraftMind 根 URL 配置。

将所有 API 路由委托给 drawings 应用处理，
并挂载 Django 管理后台和媒体文件服务（开发环境）。
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django 管理后台（可通过 /admin/ 访问）
    path("admin/", admin.site.urls),
    # 所有业务 API 由 drawings 应用处理
    path("", include("drawings.urls")),
]

# 开发环境下自动提供媒体文件服务（用户上传的图片）
# 生产环境应由 Nginx 等反向代理直接处理
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
