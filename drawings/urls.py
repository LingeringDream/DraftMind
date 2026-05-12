"""DraftMind API 路由声明。

所有路由与原 Flask 后端完全兼容，前端无需任何改动。

路由一览：
  GET  /                                  → 健康检查
  GET  /uploads/<filename>                → 本地图片访问
  POST /conversation/new                  → 上传图纸并创建解析任务
  GET  /conversation/list                 → 获取历史图纸列表
  GET  /conversation/<uuid>/info          → 获取解析结果
  POST /conversation/<uuid>/review        → 合规性审查
  POST /conversation/<uuid>/ask           → 图纸问答
  GET  /job/<uuid>/status                 → 查询任务状态
  POST /job/<uuid>/prioritize             → 提升任务优先级
  GET  /knowledge/similar/<uuid>          → 相似图纸推荐
  POST /knowledge/search                  → 语义搜索
"""

from django.urls import path

from . import views

urlpatterns = [
    # 健康检查：前端用于确认后端是否在线
    path("", views.health_check, name="health_check"),
    # 本地上传图片访问（开发环境由 Django 直接服务）
    path("uploads/<path:filename>", views.uploaded_file, name="uploaded_file"),
    # 图纸会话管理
    path("conversation/new", views.conversation_new, name="conversation_new"),
    path("conversation/list", views.conversation_list, name="conversation_list"),
    path("conversation/<uuid:conv_uuid>/info", views.conversation_info, name="conversation_info"),
    path("conversation/<uuid:conv_uuid>/review", views.conversation_review, name="conversation_review"),
    path("conversation/<uuid:conv_uuid>/ask", views.conversation_ask, name="conversation_ask"),
    # 异步任务管理
    path("job/<uuid:job_id>/status", views.job_status, name="job_status"),
    path("job/<uuid:job_id>/prioritize", views.job_prioritize, name="job_prioritize"),
    # 知识库（相似推荐 & 语义搜索）
    path("knowledge/similar/<uuid:conv_uuid>", views.knowledge_similar, name="knowledge_similar"),
    path("knowledge/search", views.knowledge_search, name="knowledge_search"),
]
