"""Django admin registration for DraftMind models."""

from django.contrib import admin

from .models import DrawingConversation, DrawingFile, KnowledgeEntry, ParseJob


@admin.register(DrawingConversation)
class DrawingConversationAdmin(admin.ModelAdmin):
    list_display = ("conv_uuid", "title", "image_count", "created_at", "updated_at")
    search_fields = ("conv_uuid", "title")
    readonly_fields = ("conv_uuid", "created_at", "updated_at")


@admin.register(ParseJob)
class ParseJobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "conversation", "status", "progress_pct", "priority", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("job_id", "conversation__conv_uuid", "conversation__title")
    readonly_fields = ("job_id", "created_at", "updated_at")


@admin.register(DrawingFile)
class DrawingFileAdmin(admin.ModelAdmin):
    list_display = ("conversation", "page_index", "stored_url", "storage_backend", "created_at")
    list_filter = ("storage_backend",)
    search_fields = ("conversation__conv_uuid", "original_filename", "stored_url")


@admin.register(KnowledgeEntry)
class KnowledgeEntryAdmin(admin.ModelAdmin):
    list_display = ("conversation", "has_embedding", "created_at", "updated_at")
    search_fields = ("conversation__conv_uuid", "conversation__title")

    @admin.display(boolean=True, description="Has embedding")
    def has_embedding(self, obj: KnowledgeEntry) -> bool:
        return bool(obj.embedding)
