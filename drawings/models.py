"""DraftMind 数据库模型。

定义四张核心表：
  - DrawingConversation: 图纸会话（一次上传对应一条记录）
  - ParseJob:            解析任务（异步任务状态追踪）
  - DrawingFile:         图纸文件（存储图片/OSS 地址）
  - KnowledgeEntry:      知识库条目（向量嵌入，用于相似推荐/搜索）

所有模型均使用 UUID 主键，与原 Flask 后端的 conv_uuid / job_id 完全兼容。
"""

import uuid

from django.db import models


class DrawingConversation(models.Model):
    """图纸会话：一次图纸上传的完整生命周期记录。

    字段说明：
      - conv_uuid:   会话唯一标识（UUID 主键，前端用此 ID 查询结果）
      - title:       图纸标题（通常取自 VLM 解析的零件名称）
      - info:        VLM 解析的结构化 JSON（含 basic_info / dimensions / tolerances 等）
      - image_urls:  图片访问地址列表（本地路径或 OSS URL）
      - image_count: 上传的图片/页数
    """

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
    """解析任务：后台异步图纸解析的状态追踪。

    状态流转：pending → processing → done / failed
    前端通过轮询 /job/<job_id>/status 获取实时进度。
    """

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
    """图纸文件：记录每页图片的存储信息。

    一次上传可能包含多页图纸（多张图片或 DXF 多布局），
    每页对应一条 DrawingFile 记录。
    """

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
    """知识库条目：为每张已解析图纸存储向量嵌入。

    用于相似图纸推荐（余弦相似度）和语义搜索（关键词向量匹配）。
    嵌入向量由通义千问 text-embedding-v3 模型生成。
    """

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
