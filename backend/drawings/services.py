"""Service functions used by the DraftMind-compatible Django API."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import oss2
import requests
from django.conf import settings
from PIL import Image

try:
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    CAD_SUPPORT = True
except ImportError:
    CAD_SUPPORT = False


def json_response_params() -> dict:
    """Return JSON dump parameters for Chinese-compatible responses."""

    return {"ensure_ascii": False}


def get_oss_bucket():
    """Initialize an Aliyun OSS bucket when all required variables exist."""

    if not all([
        settings.OSS_ENDPOINT,
        settings.OSS_ACCESS_KEY,
        settings.OSS_ACCESS_SECRET,
        settings.OSS_BUCKET_NAME,
    ]):
        return None
    try:
        auth = oss2.Auth(settings.OSS_ACCESS_KEY, settings.OSS_ACCESS_SECRET)
        return oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)
    except Exception as exc:  # pragma: no cover - network/config dependent
        print(f"[OSS] 初始化失败: {exc}")
        return None


def upload_image_to_oss(image_bytes: bytes, filename: str) -> Optional[str]:
    """Upload an image to OSS and return a public URL if successful."""

    bucket = get_oss_bucket()
    if not bucket:
        return None
    try:
        key = f"draftmind/uploads/{filename}"
        bucket.put_object(key, image_bytes)
        return f"https://{settings.OSS_BUCKET_NAME}.{settings.OSS_ENDPOINT}/{key}"
    except Exception as exc:  # pragma: no cover - network/config dependent
        print(f"[OSS] 上传失败: {exc}")
        return None


def save_image_locally(image_bytes: bytes, filename: str) -> Optional[str]:
    """Save an image under MEDIA_ROOT and return the original compatible URL."""

    try:
        settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        filepath = settings.MEDIA_ROOT / filename
        filepath.write_bytes(image_bytes)
        return f"uploads/{filename}"
    except Exception as exc:
        print(f"[Local] 本地存储失败: {exc}")
        return None


def call_vlm_api(image_base64_list: List[str], user_prompt: str = "") -> Optional[dict]:
    """Call an OpenAI-compatible multimodal model to parse drawing images."""

    if not settings.OPENAI_API_KEY:
        print("[VLM] 未配置 OPENAI_API_KEY，跳过模型调用")
        return None

    content: List[Dict[str, Any]] = []
    for img_b64 in image_base64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
        })
    if user_prompt:
        content.append({"type": "text", "text": user_prompt})

    messages = [
        {"role": "system", "content": settings.SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    content_text = ""
    try:
        resp = requests.post(
            f"{settings.OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.OPENAI_MODEL,
                "messages": messages,
                "max_tokens": settings.OPENAI_MAX_TOKENS,
                "temperature": 0.1,
                "enable_thinking": False,
            },
            timeout=180,
        )
        print(f"[VLM] API 响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[VLM] API 错误响应: {resp.text[:500]}")
        resp.raise_for_status()
        result = resp.json()
        content_text = result["choices"][0]["message"]["content"]
        print(f"[VLM] 模型原始响应长度: {len(content_text)} 字符")

        content_text = re.sub(r"<think>[\s\S]*?</think>", "", content_text).strip()
        content_text = re.sub(r"^```(?:json)?\s*\n?", "", content_text.strip())
        content_text = re.sub(r"\n?```\s*$", "", content_text.strip())
        json_match = re.search(r"\{[\s\S]*\}", content_text)
        if json_match:
            content_text = json_match.group(0)

        parsed = json.loads(content_text)
        if not isinstance(parsed, dict):
            print(f"[VLM] 模型返回了非字典类型: {type(parsed)}")
            return None
        print(f"[VLM] JSON 解析成功，字段: {list(parsed.keys())}")
        return parsed
    except json.JSONDecodeError as exc:
        print(f"[VLM] JSON 解析失败: {exc}")
        print(f"[VLM] 清理后内容(前800字符): {content_text[:800]}")
        return None
    except requests.exceptions.Timeout:
        print("[VLM] API 调用超时（180秒），图片可能过大")
        return None
    except Exception as exc:
        print(f"[VLM] API 调用失败: {exc}")
        return None


def call_embedding_api(text: str) -> Optional[List[float]]:
    """Call an OpenAI-compatible embedding API."""

    if not settings.OPENAI_API_KEY:
        return None
    try:
        resp = requests.post(
            f"{settings.OPENAI_API_BASE}/embeddings",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": settings.OPENAI_EMBEDDING_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as exc:
        print(f"[Embedding] API 调用失败: {exc}")
        return None


def image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes as base64 text."""

    return base64.b64encode(image_bytes).decode("utf-8")


def compress_image(image_bytes: bytes, max_size: int = 1024, quality: int = 85) -> bytes:
    """Resize and JPEG-compress an uploaded image."""

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as exc:
        print(f"[Image] 图片压缩失败: {exc}")
        return image_bytes


def dxf_to_images(dxf_bytes: bytes, dpi: int = 150) -> List[Image.Image]:
    """Render a DXF document into one or more PIL images."""

    if not CAD_SUPPORT:
        print("[CAD] ezdxf 或 matplotlib 未安装，无法解析 DXF 文件")
        return []
    try:
        text = dxf_bytes.decode("utf-8", errors="ignore")
        doc = ezdxf.read(io.StringIO(text))
        images: List[Image.Image] = []
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        for layout in doc.layouts:
            fig, ax = plt.subplots(figsize=(16, 12), dpi=dpi)
            ax.set_facecolor("white")
            ax.set_aspect("equal")
            ax.axis("off")
            ctx = RenderContext(doc)
            out = MatplotlibBackend(ax)
            Frontend(ctx, out).draw_layout(layout, finalize=True)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white", edgecolor="none")
            plt.close(fig)
            buf.seek(0)
            images.append(Image.open(buf).convert("RGB"))
        return images
    except Exception as exc:
        print(f"[CAD] DXF 渲染失败: {exc}")
        return []


def dwg_to_images(dwg_bytes: bytes) -> List[Image.Image]:
    """Placeholder DWG rendering implementation, matching the original behavior."""

    print("[CAD] DWG 格式暂不支持直接解析，请将文件转换为 DXF 格式后重新上传")
    return []


def extract_text_for_embedding(info: dict) -> str:
    """Extract a compact text summary from parsed drawing information."""

    parts: List[str] = []
    basic = info.get("basic_info", {}) or {}
    if basic.get("part_name"):
        parts.append(f"零件名称: {basic['part_name']}")
    if basic.get("material"):
        parts.append(f"材料: {basic['material']}")
    if basic.get("surface_treatment"):
        parts.append(f"表面处理: {basic['surface_treatment']}")

    dims = info.get("dimensions", {}) or {}
    dim_parts: List[str] = []
    if dims.get("length"):
        dim_parts.append(f"长{dims['length']}mm")
    if dims.get("width"):
        dim_parts.append(f"宽{dims['width']}mm")
    if dims.get("height_thickness"):
        dim_parts.append(f"高{dims['height_thickness']}mm")
    if dim_parts:
        parts.append("尺寸: " + ", ".join(dim_parts))

    for tol in info.get("tolerances", []) or []:
        if isinstance(tol, dict) and tol.get("tolerance_code"):
            parts.append(f"公差: {tol.get('dimension_name', '')} {tol['tolerance_code']}")
    return "; ".join(parts)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity without requiring NumPy at runtime."""

    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    norm = norm_a * norm_b
    return float(dot / norm) if norm > 0 else 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_dimension_similarity(info_a: dict, info_b: dict) -> float:
    """Compute simple normalized dimension similarity."""

    dims_a = info_a.get("dimensions", {}) or {}
    dims_b = info_b.get("dimensions", {}) or {}
    vec_a = [
        _safe_float(dims_a.get("length")),
        _safe_float(dims_a.get("width")),
        _safe_float(dims_a.get("height_thickness")),
    ]
    vec_b = [
        _safe_float(dims_b.get("length")),
        _safe_float(dims_b.get("width")),
        _safe_float(dims_b.get("height_thickness")),
    ]
    max_dim = max([abs(v) for v in vec_a + vec_b] + [1.0])
    diffs = [abs(a - b) / max_dim for a, b in zip(vec_a, vec_b)]
    return float(1.0 - (sum(diffs) / len(diffs)))


def format_tolerances_for_frontend(raw_tolerances: list) -> list:
    """Format raw tolerances for the existing frontend table."""

    formatted = []
    for tol in raw_tolerances or []:
        if not isinstance(tol, dict):
            continue
        upper = _safe_float(tol.get("upper_deviation"), 0.0)
        lower = _safe_float(tol.get("lower_deviation"), 0.0)
        code = tol.get("tolerance_code")
        if code:
            tol_str = code
        else:
            upper_str = f"+{upper:g}" if upper >= 0 else f"{upper:g}"
            lower_str = f"+{lower:g}" if lower >= 0 else f"{lower:g}"
            tol_str = f"{upper_str} / {lower_str}"
        formatted.append({
            "feature": tol.get("dimension_name", ""),
            "nominal": tol.get("basic_size", 0),
            "tolerance": tol_str,
            "_raw": tol,
        })
    return formatted


def run_review(info: dict, custom_rules: str = "") -> dict:
    """Run the original rule-based compliance review."""

    issues = []
    basic = info.get("basic_info", {}) or {}
    dims = info.get("dimensions", {}) or {}
    tolerances = info.get("tolerances", []) or []

    if not basic.get("part_name"):
        issues.append({"severity": "WARNING", "description": "图纸缺少零件名称", "suggestion": "请在标题栏中明确标注零件名称", "reference": "GB/T 4458.1"})
    if not basic.get("drawing_number"):
        issues.append({"severity": "WARNING", "description": "图纸缺少图号", "suggestion": "请在标题栏中标注唯一图号", "reference": "GB/T 4458.1"})
    if not basic.get("material"):
        issues.append({"severity": "ERROR", "description": "图纸缺少材料标注", "suggestion": "请在标题栏中标注材料牌号及标准号", "reference": "GB/T 4458.1"})
    if _safe_float(dims.get("length")) <= 0 or _safe_float(dims.get("width")) <= 0:
        issues.append({"severity": "WARNING", "description": "主要尺寸信息不完整或为零", "suggestion": "请确认图纸中是否标注了完整的外形尺寸", "reference": "GB/T 4458.4"})
    if not tolerances:
        issues.append({"severity": "WARNING", "description": "未检测到尺寸公差标注", "suggestion": "关键配合尺寸应标注公差", "reference": "GB/T 1800.1"})
    if not info.get("geometric_tolerances"):
        issues.append({"severity": "WARNING", "description": "未检测到形位公差标注", "suggestion": "关键特征应考虑标注形位公差", "reference": "GB/T 1182"})
    if not info.get("surface_roughness"):
        issues.append({"severity": "WARNING", "description": "未检测到表面粗糙度标注", "suggestion": "配合面和重要表面应标注粗糙度", "reference": "GB/T 131"})

    if custom_rules:
        custom_lines = [line.strip() for line in custom_rules.split("\n") if line.strip()]
        material = basic.get("material", "")
        for rule in custom_lines:
            if "禁止" in rule and "材料" in rule:
                forbidden = rule.replace("禁止使用", "").replace("材料", "").strip()
                if forbidden and forbidden in material:
                    issues.append({
                        "severity": "ERROR",
                        "description": f"违反自定义规则：使用了被禁止的材料 {forbidden}",
                        "suggestion": f"请更换材料，当前材料: {material}",
                        "reference": "企业自定义规则",
                    })

    error_count = sum(1 for item in issues if item["severity"] == "ERROR")
    warning_count = sum(1 for item in issues if item["severity"] == "WARNING")
    if error_count > 0:
        risk_level = "HIGH"
        overall_pass = False
    elif warning_count > 2:
        risk_level = "MEDIUM"
        overall_pass = False
    elif warning_count > 0:
        risk_level = "LOW"
        overall_pass = True
    else:
        risk_level = "NONE"
        overall_pass = True

    summary = (
        f"图纸审查通过。发现 {warning_count} 个改进建议。"
        if overall_pass
        else f"图纸审查未通过。发现 {error_count} 个错误和 {warning_count} 个警告，请修正后重新提交。"
    )
    return {
        "overall_pass": overall_pass,
        "risk_level": risk_level,
        "issues": issues,
        "summary": summary,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def ask_with_llm(info: dict, question: str) -> dict:
    """Generate an answer from parsed drawing context."""

    if not settings.OPENAI_API_KEY:
        return {
            "answer": f"[模拟回答] 关于您的问题「{question}」，基于当前图纸信息："
            f"零件名称为 {info.get('basic_info', {}).get('part_name', '未知')}，"
            f"材料为 {info.get('basic_info', {}).get('material', '未知')}。"
            f"（注：请配置 OPENAI_API_KEY 以获取真实 AI 回答）"
        }

    context = json.dumps(info, ensure_ascii=False, indent=2)
    resp = requests.post(
        f"{settings.OPENAI_API_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.OPENAI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一名专业的机械工程师助手。根据用户提供的工程图纸信息回答问题。回答应准确、专业、简洁。如果图纸信息中没有相关内容，请如实说明。",
                },
                {"role": "user", "content": f"图纸信息:\n{context}\n\n问题: {question}"},
            ],
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        timeout=60,
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"]
    return {"answer": answer}
