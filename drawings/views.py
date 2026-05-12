"""DraftMind API 视图层。

处理所有 HTTP 请求，职责：
  - 参数校验与类型转换
  - 调用 services 层执行业务逻辑
  - 返回 JSON 响应（格式与原 Flask 后端完全兼容）

所有 POST 接口均标记 @csrf_exempt（前后端分离架构无需 CSRF Token）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import DrawingConversation, KnowledgeEntry, ParseJob
from .services import (
    ask_with_llm,
    call_embedding_api,
    compute_dimension_similarity,
    cosine_similarity,
    format_tolerances_for_frontend,
    json_response_params,
    run_review,
)
from .tasks import submit_parse_job

# JSON 序列化参数：ensure_ascii=False 保证中文正常输出
JSON_PARAMS = json_response_params()


def _json(data: Any, status: int = 200, safe: bool = True) -> JsonResponse:
    """统一 JSON 响应构造器。"""
    return JsonResponse(data, status=status, safe=safe, json_dumps_params=JSON_PARAMS)


def _load_json_body(request: HttpRequest) -> Dict[str, Any]:
    """安全解析请求体中的 JSON 数据。"""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _conversation_payload(conversation: DrawingConversation) -> dict:
    """将数据库记录转换为前端期望的响应格式。"""
    info = dict(conversation.info or {})
    info["image_urls"] = conversation.image_urls or []
    if "tolerances" in info:
        info["tolerances"] = format_tolerances_for_frontend(info.get("tolerances") or [])
    return info


# ================================================================
# 健康检查
# ================================================================

@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """GET / — 健康检查，前端用于确认后端是否在线。"""
    return _json({"status": "ok"})


# ================================================================
# 本地文件服务
# ================================================================

@require_GET
def uploaded_file(request: HttpRequest, filename: str) -> FileResponse:
    """GET /uploads/<filename> — 提供本地上传图片的 HTTP 访问。

    安全措施：防止目录穿越攻击（../../etc/passwd）。
    """
    media_root = Path(settings.MEDIA_ROOT).resolve()
    target = (media_root / filename).resolve()
    if not str(target).startswith(str(media_root)) or not target.is_file():
        raise Http404("File not found")
    return FileResponse(open(target, "rb"))


# ================================================================
# 图纸会话管理
# ================================================================

@csrf_exempt
@require_http_methods(["POST"])
def conversation_new(request: HttpRequest) -> JsonResponse:
    """POST /conversation/new — 上传图纸并创建异步解析任务。

    请求格式: multipart/form-data
      - image:       图片/CAD 文件（可多张）
      - priority:    任务优先级（数字，值越小越优先，默认 10）
      - upload_oss:  是否上传到 OSS（"true"/"false"，默认 "false"）

    返回: {"job_id": "xxx", "conv_uuid": "xxx"}
    """
    files = request.FILES.getlist("image")
    if not files:
        return _json({"error": "未上传图片"}, status=400)

    try:
        priority = int(request.POST.get("priority", 10))
    except (TypeError, ValueError):
        priority = 10
    upload_oss = str(request.POST.get("upload_oss", "false")).lower() == "true"

    # 读取所有文件的二进制数据
    image_bytes_list = [file.read() for file in files]
    first_filename = files[0].name if files else ""

    # 创建数据库记录
    conversation = DrawingConversation.objects.create()
    job = ParseJob.objects.create(
        conversation=conversation,
        priority=priority,
        status=ParseJob.STATUS_PENDING,
        progress="等待处理...",
        progress_pct=0.0,
    )

    # 提交到线程池异步执行解析
    submit_parse_job(str(job.job_id), str(conversation.conv_uuid), image_bytes_list, first_filename, upload_oss)
    return _json({"job_id": str(job.job_id), "conv_uuid": str(conversation.conv_uuid)})


@require_GET
def conversation_list(request: HttpRequest) -> JsonResponse:
    """GET /conversation/list — 获取所有已解析图纸的列表。

    仅返回已完成解析的图纸（info 非空），供前端侧边栏展示。
    返回: {"uuid1": "零件名称1", "uuid2": "零件名称2", ...}
    """
    conversations = DrawingConversation.objects.exclude(info={}).order_by("-created_at")
    payload = {str(conv.conv_uuid): (conv.title or "未命名图纸") for conv in conversations}
    return _json(payload)


@require_GET
def conversation_info(request: HttpRequest, conv_uuid: str) -> JsonResponse:
    """GET /conversation/<uuid>/info — 获取指定图纸的解析结果。

    返回前端展示所需的结构化信息（基本尺寸、公差、图片地址等）。
    """
    try:
        conversation = DrawingConversation.objects.get(conv_uuid=conv_uuid)
    except DrawingConversation.DoesNotExist:
        return _json({"error": "图纸不存在"}, status=404)
    if not conversation.info:
        return _json({"error": "图纸不存在"}, status=404)
    return _json(_conversation_payload(conversation))


@csrf_exempt
@require_http_methods(["POST"])
def conversation_review(request: HttpRequest, conv_uuid: str) -> JsonResponse:
    """POST /conversation/<uuid>/review — 对图纸进行合规性审查。

    请求体: {"custom_rules": "企业自定义规则文本（可选）"}
    返回: 审查报告（overall_pass / risk_level / issues / summary）
    """
    try:
        conversation = DrawingConversation.objects.get(conv_uuid=conv_uuid)
    except DrawingConversation.DoesNotExist:
        return _json({"error": "图纸不存在"}, status=404)
    if not conversation.info:
        return _json({"error": "图纸不存在"}, status=404)
    data = _load_json_body(request)
    custom_rules = data.get("custom_rules", "") or ""
    return _json(run_review(conversation.info or {}, custom_rules))


@csrf_exempt
@require_http_methods(["POST"])
def conversation_ask(request: HttpRequest, conv_uuid: str) -> JsonResponse:
    """POST /conversation/<uuid>/ask — 基于图纸上下文的智能问答。

    请求体: {"question": "用户的问题文本"}
    返回: {"answer": "AI 的回答"}
    """
    try:
        conversation = DrawingConversation.objects.get(conv_uuid=conv_uuid)
    except DrawingConversation.DoesNotExist:
        return _json({"error": "图纸不存在"}, status=404)
    if not conversation.info:
        return _json({"error": "图纸不存在"}, status=404)
    data = _load_json_body(request)
    question = (data.get("question") or "").strip()
    if not question:
        return _json({"error": "请输入问题"}, status=400)
    try:
        return _json(ask_with_llm(conversation.info or {}, question))
    except Exception as exc:
        return _json({"error": f"AI 问答失败: {exc}"}, status=500)


# ================================================================
# 异步任务管理
# ================================================================

@require_GET
def job_status(request: HttpRequest, job_id: str) -> JsonResponse:
    """GET /job/<uuid>/status — 查询异步解析任务的执行状态。

    前端每 3 秒轮询此接口，实时更新进度条。
    返回: {status, progress, progress_pct, conv_uuid, error}
    """
    try:
        job = ParseJob.objects.get(job_id=job_id)
    except ParseJob.DoesNotExist:
        return _json({"error": "任务不存在"}, status=404)
    return _json({
        "status": job.status,
        "progress": job.progress,
        "progress_pct": job.progress_pct,
        "conv_uuid": str(job.conversation_id) if job.conversation_id else None,
        "error": job.error or None,
    })


@csrf_exempt
@require_http_methods(["POST"])
def job_prioritize(request: HttpRequest, job_id: str) -> JsonResponse:
    """POST /job/<uuid>/prioritize — 提升异步任务的优先级。

    当用户切换到正在解析的图纸时，前端自动调用此接口。
    请求体: {"priority": 0}
    """
    try:
        job = ParseJob.objects.get(job_id=job_id)
    except ParseJob.DoesNotExist:
        return _json({"error": "任务不存在"}, status=404)
    data = _load_json_body(request)
    try:
        priority = int(data.get("priority", 0))
    except (TypeError, ValueError):
        priority = 0
    job.priority = priority
    job.progress = "优先级已提升，正在加速处理..."
    job.save(update_fields=["priority", "progress", "updated_at"])
    return _json({"status": "ok", "job_id": str(job.job_id)})


# ================================================================
# 知识库（相似推荐 & 语义搜索）
# ================================================================

@require_GET
def knowledge_similar(request: HttpRequest, conv_uuid: str) -> JsonResponse:
    """GET /knowledge/similar/<uuid> — 查找与指定图纸相似的历史图纸。

    使用语义向量相似度（alpha）和尺寸相似度（beta）的加权组合排序。
    Query Params: top_k=5, alpha=0.7, beta=0.3
    """
    try:
        base_entry = KnowledgeEntry.objects.select_related("conversation").get(conversation_id=conv_uuid)
    except KnowledgeEntry.DoesNotExist:
        return _json({"error": "图纸不存在"}, status=404)

    try:
        top_k = int(request.GET.get("top_k", 5))
    except (TypeError, ValueError):
        top_k = 5
    try:
        alpha = float(request.GET.get("alpha", 0.7))
        beta = float(request.GET.get("beta", 0.3))
    except (TypeError, ValueError):
        alpha, beta = 0.7, 0.3

    base_info = base_entry.conversation.info or {}
    base_embedding = base_entry.embedding or []
    results = []
    for entry in KnowledgeEntry.objects.select_related("conversation").exclude(conversation_id=conv_uuid):
        conv = entry.conversation
        sem_score = cosine_similarity(base_embedding, entry.embedding or []) if base_embedding and entry.embedding else 0.0
        dim_score = compute_dimension_similarity(base_info, conv.info or {})
        final_score = alpha * sem_score + beta * dim_score
        basic = (conv.info or {}).get("basic_info", {}) or {}
        results.append({
            "conv_uuid": str(conv.conv_uuid),
            "part_name": basic.get("part_name", ""),
            "drawing_number": basic.get("drawing_number", ""),
            "material": basic.get("material", ""),
            "score": round(float(final_score), 4),
        })

    results.sort(key=lambda item: item["score"], reverse=True)
    return _json(results[:top_k], safe=False)


@csrf_exempt
@require_http_methods(["POST"])
def knowledge_search(request: HttpRequest) -> JsonResponse:
    """POST /knowledge/search — 基于关键词的语义搜索。

    将关键词转换为向量后与知识库匹配；无 API Key 时降级为关键词匹配。
    请求体: {"keyword": "搜索关键词", "top_k": 5}
    """
    data = _load_json_body(request)
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return _json({"error": "请输入搜索关键词"}, status=400)
    try:
        top_k = int(data.get("top_k", 5))
    except (TypeError, ValueError):
        top_k = 5

    # 将搜索关键词转换为向量
    query_embedding = call_embedding_api(keyword)
    results = []
    keyword_lower = keyword.lower()
    for entry in KnowledgeEntry.objects.select_related("conversation"):
        conv = entry.conversation
        info = conv.info or {}
        if query_embedding and entry.embedding:
            # 基于向量相似度匹配
            score = cosine_similarity(query_embedding, entry.embedding)
        else:
            # 降级方案：简单的关键词匹配
            info_text = json.dumps(info, ensure_ascii=False).lower()
            score = 1.0 if keyword_lower in info_text else 0.0
        if score > 0:
            basic = info.get("basic_info", {}) or {}
            results.append({
                "conv_uuid": str(conv.conv_uuid),
                "part_name": basic.get("part_name", ""),
                "drawing_number": basic.get("drawing_number", ""),
                "score": round(float(score), 4),
            })

    results.sort(key=lambda item: item["score"], reverse=True)
    return _json(results[:top_k], safe=False)
