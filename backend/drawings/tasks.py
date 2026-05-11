"""Lightweight background parsing tasks for DraftMind."""

from __future__ import annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List

from django.conf import settings
from django.db import close_old_connections, transaction
from PIL import Image

from .models import DrawingConversation, DrawingFile, KnowledgeEntry, ParseJob
from .services import (
    call_embedding_api,
    call_vlm_api,
    compress_image,
    dwg_to_images,
    dxf_to_images,
    extract_text_for_embedding,
    image_to_base64,
    save_image_locally,
    upload_image_to_oss,
)

executor = ThreadPoolExecutor(max_workers=settings.PARSE_WORKER_COUNT)


def submit_parse_job(job_id: str, conv_uuid: str, image_bytes_list: List[bytes], filename: str = "", upload_oss: bool = False) -> None:
    """Submit a parsing task to the process-local thread pool."""

    executor.submit(run_parse_job, job_id, conv_uuid, image_bytes_list, filename, upload_oss)


def _update_job(job_id: str, **fields) -> None:
    """Persist selected job fields safely from a worker thread."""

    ParseJob.objects.filter(job_id=job_id).update(**fields)


def _pil_image_to_jpeg_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def run_parse_job(job_id: str, conv_uuid: str, image_bytes_list: List[bytes], filename: str = "", upload_oss: bool = False) -> None:
    """Run the original parsing workflow while persisting status in the database."""

    close_old_connections()
    try:
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        if ext in (".dxf", ".dwg"):
            _update_job(
                job_id,
                status=ParseJob.STATUS_PROCESSING,
                progress="正在解析 CAD 图纸...",
                progress_pct=0.05,
            )
            rendered = dxf_to_images(image_bytes_list[0]) if ext == ".dxf" else dwg_to_images(image_bytes_list[0])
            if not rendered:
                _update_job(
                    job_id,
                    status=ParseJob.STATUS_FAILED,
                    error=(
                        f"无法解析 {ext} 文件。"
                        + ("请安装 ezdxf 和 matplotlib: pip install ezdxf matplotlib" if ext == ".dxf" else "文件可能已损坏或格式不受支持")
                    ),
                )
                return
            image_bytes_list = [_pil_image_to_jpeg_bytes(img) for img in rendered]

        _update_job(
            job_id,
            status=ParseJob.STATUS_PROCESSING,
            progress="正在压缩图像...",
            progress_pct=0.1,
        )
        compressed_images = [compress_image(img) for img in image_bytes_list]

        _update_job(job_id, progress="正在保存图像...", progress_pct=0.2)
        image_urls = []
        storage_backend = DrawingFile.STORAGE_OSS if upload_oss else DrawingFile.STORAGE_LOCAL
        for idx, img_bytes in enumerate(compressed_images):
            stored_filename = f"{conv_uuid}_page_{idx + 1}.jpg"
            url = upload_image_to_oss(img_bytes, stored_filename) if upload_oss else save_image_locally(img_bytes, stored_filename)
            if url:
                image_urls.append(url)
            elif upload_oss:
                # Match the original resilience: if OSS upload fails, continue without URL.
                print(f"[OSS] 第 {idx + 1} 页上传失败")

        _update_job(job_id, progress="AI 正在解析图纸，请稍候...", progress_pct=0.4)
        image_b64_list = [image_to_base64(img) for img in compressed_images]
        parsed_info = call_vlm_api(image_b64_list)
        if parsed_info is None:
            _update_job(
                job_id,
                status=ParseJob.STATUS_FAILED,
                error=(
                    "AI 解析失败，请检查："
                    "1) .env 中 OPENAI_MODEL 是否为多模态视觉模型（如 qwen-vl-max-latest）；"
                    "2) OPENAI_API_KEY 是否有效；"
                    "3) 图片是否清晰可读。"
                    "详见后端控制台日志。"
                ),
            )
            return

        _update_job(job_id, progress="正在生成向量嵌入...", progress_pct=0.8)
        text_summary = extract_text_for_embedding(parsed_info)
        embedding = call_embedding_api(text_summary)

        _update_job(job_id, progress="正在保存解析结果...", progress_pct=0.95)
        title = parsed_info.get("basic_info", {}).get("part_name", "") if isinstance(parsed_info, dict) else ""
        with transaction.atomic():
            conversation = DrawingConversation.objects.select_for_update().get(conv_uuid=conv_uuid)
            conversation.info = parsed_info
            conversation.image_urls = image_urls
            conversation.image_count = len(image_bytes_list)
            conversation.title = title
            conversation.save(update_fields=["info", "image_urls", "image_count", "title", "updated_at"])

            DrawingFile.objects.filter(conversation=conversation).delete()
            DrawingFile.objects.bulk_create([
                DrawingFile(
                    conversation=conversation,
                    page_index=idx + 1,
                    original_filename=filename,
                    stored_url=url,
                    storage_backend=storage_backend,
                )
                for idx, url in enumerate(image_urls)
            ])

            KnowledgeEntry.objects.update_or_create(
                conversation=conversation,
                defaults={"embedding": embedding},
            )

            ParseJob.objects.filter(job_id=job_id).update(
                status=ParseJob.STATUS_DONE,
                progress="解析完成",
                progress_pct=1.0,
                conversation=conversation,
                error="",
            )
    except Exception as exc:
        print(f"[Job] 任务 {job_id} 执行失败: {exc}")
        _update_job(job_id, status=ParseJob.STATUS_FAILED, error=str(exc))
    finally:
        close_old_connections()
