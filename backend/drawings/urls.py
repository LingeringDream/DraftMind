"""URL declarations for DraftMind-compatible API endpoints."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.health_check, name="health_check"),
    path("uploads/<path:filename>", views.uploaded_file, name="uploaded_file"),
    path("conversation/new", views.conversation_new, name="conversation_new"),
    path("conversation/list", views.conversation_list, name="conversation_list"),
    path("conversation/<uuid:conv_uuid>/info", views.conversation_info, name="conversation_info"),
    path("conversation/<uuid:conv_uuid>/review", views.conversation_review, name="conversation_review"),
    path("conversation/<uuid:conv_uuid>/ask", views.conversation_ask, name="conversation_ask"),
    path("job/<uuid:job_id>/status", views.job_status, name="job_status"),
    path("job/<uuid:job_id>/prioritize", views.job_prioritize, name="job_prioritize"),
    path("knowledge/similar/<uuid:conv_uuid>", views.knowledge_similar, name="knowledge_similar"),
    path("knowledge/search", views.knowledge_search, name="knowledge_search"),
]
