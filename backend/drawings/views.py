"""HTTP views for DraftMind-compatible API endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
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


JSON_PARAMS = json_response_params()


def _json(data: Any, status: int = 200, safe: bool = True) -> JsonResponse:
    return JsonResponse(data, status=status, safe=safe, json_dumps_params=JSON_PARAMS)


def _load_json_body(request: HttpRequest) -> Dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _conversation_payload(conversation: DrawingConversation) -> dict:
    info = dict(conversation.info or {})
    info["image_urls"] = conversation.image_urls or []
    if "tolerances" in info:
        info["tolerances"] = format_tolerances_for_frontend(info.get("tolerances") or [])
    return info


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    return _json({"status": "ok"})


@require_GET
def uploaded_file(request: HttpRequest, filename: str) -> FileResponse:
    """Serve files under MEDIA_ROOT while preventing directory traversal."""

    media_root = Path(settings.MEDIA_ROOT).resolve()
    target = (media_root / filename).resolve()
    if not str(target).startswith(str(media_root)) or not target.is_file():
        raise Http404("File not found")
    return FileResponse(open(target, "rb"))


@csrf_exempt
@require_http_methods(["POST"])
def conversation_new(request: HttpRequest) -> JsonResponse:
    files = request.FILES.getlist("image")
    if not files:
        return _json({"error": "未上传图片"}, status=400)

    try:
        priority = int(request.POST.get("priority", 10))
    except (TypeError, ValueError):
        priority = 10
    upload_oss = str(request.POST.get("upload_oss", "false")).lower() == "true"

    image_bytes_list = [file.read() for file in files]
    first_filename = files[0].name if files else ""

    conversation = DrawingConversation.objects.create()
    job = ParseJob.objects.create(
        conversation=conversation,
        priority=priority,
        status=ParseJob.STATUS_PENDING,
        progress="等待处理...",
        progress_pct=0.0,
    )
    submit_parse_job(str(job.job_id), str(conversation.conv_uuid), image_bytes_list, first_filename, upload_oss)
    return _json({"job_id": str(job.job_id), "conv_uuid": str(conversation.conv_uuid)})


@require_GET
def conversation_list(request: HttpRequest) -> JsonResponse:
    conversations = DrawingConversation.objects.exclude(info={}).order_by("-created_at")
    payload = {str(conv.conv_uuid): (conv.title or "未命名图纸") for conv in conversations}
    return _json(payload)


@require_GET
def conversation_info(request: HttpRequest, conv_uuid: str) -> JsonResponse:
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


@require_GET
def job_status(request: HttpRequest, job_id: str) -> JsonResponse:
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


@require_GET
def knowledge_similar(request: HttpRequest, conv_uuid: str) -> JsonResponse:
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
    data = _load_json_body(request)
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return _json({"error": "请输入搜索关键词"}, status=400)
    try:
        top_k = int(data.get("top_k", 5))
    except (TypeError, ValueError):
        top_k = 5

    query_embedding = call_embedding_api(keyword)
    results = []
    keyword_lower = keyword.lower()
    for entry in KnowledgeEntry.objects.select_related("conversation"):
        conv = entry.conversation
        info = conv.info or {}
        if query_embedding and entry.embedding:
            score = cosine_similarity(query_embedding, entry.embedding)
        else:
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
