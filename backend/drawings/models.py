"""Database models for the DraftMind drawing intelligence backend."""

import uuid

from django.db import models


class DrawingConversation(models.Model):
    """A parsed drawing conversation compatible with the original conv_uuid API."""

    conv_uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, blank=True, default="")
    info = models.JSONField(default=dict, blank=True)
    image_urls = models.JSONField(default=list, blank=True)
    image_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "图纸会话"
        verbose_name_plural = "图纸会话"

    def __str__(self) -> str:
        return self.title or str(self.conv_uuid)


class ParseJob(models.Model):
    """Background parsing job status compatible with the original job API."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    job_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        DrawingConversation,
        related_name="jobs",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    progress = models.CharField(max_length=255, blank=True, default="等待处理...")
    progress_pct = models.FloatField(default=0.0)
    priority = models.IntegerField(default=10)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "解析任务"
        verbose_name_plural = "解析任务"

    def __str__(self) -> str:
        return f"{self.job_id} ({self.status})"


class DrawingFile(models.Model):
    """Stored drawing page or rendered CAD image metadata."""

    STORAGE_LOCAL = "local"
    STORAGE_OSS = "oss"

    STORAGE_CHOICES = [
        (STORAGE_LOCAL, "Local"),
        (STORAGE_OSS, "OSS"),
    ]

    conversation = models.ForeignKey(
        DrawingConversation,
        related_name="files",
        on_delete=models.CASCADE,
    )
    page_index = models.PositiveIntegerField(default=1)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    stored_url = models.CharField(max_length=1024)
    storage_backend = models.CharField(max_length=20, choices=STORAGE_CHOICES, default=STORAGE_LOCAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["conversation_id", "page_index"]
        unique_together = ("conversation", "page_index")
        verbose_name = "图纸文件"
        verbose_name_plural = "图纸文件"

    def __str__(self) -> str:
        return f"{self.conversation_id} page {self.page_index}"


class KnowledgeEntry(models.Model):
    """Search and recommendation index associated with one parsed drawing."""

    conversation = models.OneToOneField(
        DrawingConversation,
        related_name="knowledge_entry",
        on_delete=models.CASCADE,
    )
    embedding = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "知识库条目"
        verbose_name_plural = "知识库条目"

    def __str__(self) -> str:
        return str(self.conversation_id)
