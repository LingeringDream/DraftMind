#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DraftMind Flask 后端服务
========================

本文件是 DraftMind 工程图纸智能管理系统的后端 API 服务。
基于 Flask 框架提供 RESTful API，供 Vue.js 前端调用。

主要功能：
  - 图纸上传与异步解析（调用通义千问多模态大模型）
  - 合规性审查（基于国标 + 自定义规则）
  - 相似图纸推荐（向量嵌入 + 混合相似度）
  - 语义搜索（关键词匹配知识库）
  - 图纸知识问答（基于解析上下文的 RAG）

技术栈：
  - Flask + flask-cors 提供 HTTP API
  - 阿里云 OSS 存储图纸原图
  - 通义千问 (qwen3-vl-32b-thinking) 进行图纸解析
  - text-embedding-v3 生成向量嵌入
  - ThreadPoolExecutor 管理异步任务队列
"""

import base64
import io
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import oss2
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from PIL import Image

# [CAD] CAD 文件解析依赖（延迟导入，未安装时不影响图片/PDF 功能）
try:
    import ezdxf
    import matplotlib
    matplotlib.use("Agg")  # 无 GUI 后端，服务器环境适用
    import matplotlib.pyplot as plt
    CAD_SUPPORT = True
except ImportError:
    CAD_SUPPORT = False

# ================================================================
# 环境变量加载
# ================================================================
# 从 .env 文件读取配置（API 密钥、OSS 配置等）
load_dotenv()

# ================================================================
# Flask 应用初始化
# ================================================================
app = Flask(__name__)
# 允许跨域请求（Vue.js 前端运行在 localhost:5173，后端在 localhost:5000）
CORS(app)

# ================================================================
# 全局配置
# ================================================================

# --- 通义千问 API 配置 ---
# 使用 OpenAI 兼容接口调用阿里云通义千问模型
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "qwen3-vl-32b-thinking")            # 多模态视觉模型，用于图纸解析
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v3")  # 文本嵌入模型
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "8021"))

# --- [OSS] 本地存储配置（默认存储位置） ---
# 图片默认保存在项目根目录的 uploads/ 文件夹下
LOCAL_STORAGE_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)

# --- 阿里云 OSS 配置（可选，用户主动开启时使用） ---
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY", "")
OSS_ACCESS_SECRET = os.getenv("OSS_ACCESS_SECRET", "")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")

# --- 解析提示词 ---
# 从 main_prompt.md 加载图纸解析的 system prompt
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "main_prompt.md")
SYSTEM_PROMPT = ""
if os.path.exists(PROMPT_PATH):
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

# ================================================================
# 数据持久化目录
# ================================================================
# 解析结果保存为本地 JSON 文件，重启后自动加载
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def save_conversation_to_disk(conv_uuid: str, data: dict):
    """将单条图纸解析结果持久化到 data/ 目录"""
    try:
        filepath = os.path.join(DATA_DIR, f"{conv_uuid}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Data] 保存失败: {e}")


def load_conversations_from_disk() -> Dict[str, dict]:
    """启动时从 data/ 目录加载所有历史解析结果"""
    loaded = {}
    if not os.path.isdir(DATA_DIR):
        return loaded
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            filepath = os.path.join(DATA_DIR, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            conv_uuid = fname.replace(".json", "")
            loaded[conv_uuid] = data
        except Exception as e:
            print(f"[Data] 加载 {fname} 失败: {e}")
    print(f"[Data] 已加载 {len(loaded)} 条历史记录")
    return loaded


# ================================================================
# 内存数据存储
# ================================================================

# 图纸会话数据: conv_uuid -> 图纸完整信息（启动时从磁盘加载）
conversations: Dict[str, dict] = load_conversations_from_disk()

# 异步任务数据: job_id -> 任务状态信息
jobs: Dict[str, dict] = {}

# 知识库条目: conv_uuid -> {info, embedding, image_urls}
knowledge_base: Dict[str, dict] = {}

# 启动时将已加载的历史数据同步到知识库（用于相似推荐/搜索）
for _cid, _cdata in conversations.items():
    knowledge_base[_cid] = {
        "info": _cdata.get("info", {}),
        "embedding": None,  # 历史数据的嵌入需重新生成
        "image_urls": _cdata.get("image_urls", []),
    }

# ================================================================
# 异步任务执行器
# ================================================================
# 使用线程池处理后台解析任务，max_workers 控制并发数
executor = ThreadPoolExecutor(max_workers=4)

# 任务优先级队列（用于 prioritize 功能）
# 结构: {job_id: priority_value}，值越小优先级越高
job_priorities: Dict[str, int] = {}
priority_lock = threading.Lock()


# ================================================================
# 工具函数
# ================================================================

def generate_uuid() -> str:
    """生成唯一标识符，用于会话 ID 和任务 ID"""
    return str(uuid.uuid4())


def get_oss_bucket():
    """
    初始化并返回阿里云 OSS Bucket 对象。

    Returns:
        oss2.Bucket: OSS 存储桶对象，配置失败时返回 None
    """
    if not all([OSS_ENDPOINT, OSS_ACCESS_KEY, OSS_ACCESS_SECRET, OSS_BUCKET_NAME]):
        return None
    try:
        auth = oss2.Auth(OSS_ACCESS_KEY, OSS_ACCESS_SECRET)
        return oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
    except Exception as e:
        print(f"[OSS] 初始化失败: {e}")
        return None


def upload_image_to_oss(image_bytes: bytes, filename: str) -> Optional[str]:
    """
    将图片上传到阿里云 OSS 并返回访问 URL。

    Args:
        image_bytes: 图片的二进制数据
        filename: 存储在 OSS 上的文件名

    Returns:
        str: 图片的公开访问 URL，上传失败时返回 None
    """
    bucket = get_oss_bucket()
    if not bucket:
        return None
    try:
        key = f"draftmind/uploads/{filename}"
        bucket.put_object(key, image_bytes)
        return f"https://{OSS_BUCKET_NAME}.{OSS_ENDPOINT}/{key}"
    except Exception as e:
        print(f"[OSS] 上传失败: {e}")
        return None


# [OSS] 本地存储函数 — 图片保存到项目 uploads/ 目录
def save_image_locally(image_bytes: bytes, filename: str) -> Optional[str]:
    """
    将图片保存到本地 uploads/ 目录并返回可访问的相对路径。

    作为 OSS 上传的替代方案，图片默认存储在本地磁盘。

    Args:
        image_bytes: 图片的二进制数据
        filename: 保存的文件名

    Returns:
        str: 本地文件的相对路径（如 "uploads/xxx.jpg"），保存失败时返回 None
    """
    try:
        filepath = os.path.join(LOCAL_STORAGE_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        # 返回相对路径，供前端通过 /uploads/ 路由访问
        return f"uploads/{filename}"
    except Exception as e:
        print(f"[Local] 本地存储失败: {e}")
        return None


def call_vlm_api(image_base64_list: List[str], user_prompt: str = "") -> Optional[dict]:
    """
    调用通义千问多模态视觉大模型解析工程图纸。

    将图片编码为 base64 后发送给 VLM，由模型提取结构化信息。

    Args:
        image_base64_list: 图片 base64 编码列表（支持多页图纸）
        user_prompt: 用户附加的提示词（可选）

    Returns:
        dict: 模型返回的结构化 JSON 数据，调用失败时返回 None
    """
    if not OPENAI_API_KEY:
        print("[VLM] 未配置 OPENAI_API_KEY，跳过模型调用")
        return None

    # 构建多模态消息：将所有图片页合并为一条消息
    content = []
    for img_b64 in image_base64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
        })

    # 如果有附加提示词，追加到消息末尾
    if user_prompt:
        content.append({"type": "text", "text": user_prompt})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content}
    ]

    try:
        # 使用 OpenAI 兼容接口调用通义千问
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": OPENAI_MAX_TOKENS,
                "temperature": 0.1,  # 低温度确保输出稳定性
                # 关闭 thinking 模式，避免思考过程消耗 max_tokens 导致 JSON 截断
                "enable_thinking": False,
            },
            timeout=180,  # 大图解析耗时较长，放宽超时
        )
        # 打印 HTTP 状态码，方便排查
        print(f"[VLM] API 响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[VLM] API 错误响应: {resp.text[:500]}")
        resp.raise_for_status()
        result = resp.json()

        # 从模型响应中提取 JSON 内容
        content_text = result["choices"][0]["message"]["content"]
        print(f"[VLM] 模型原始响应长度: {len(content_text)} 字符")

        # --- 多层清理策略，处理模型返回的各种非纯 JSON 格式 ---

        # 1. 去除 qwen3-thinking 模型生成的 <think>...</think> 思考过程
        import re
        content_text = re.sub(r"<think>[\s\S]*?</think>", "", content_text).strip()

        # 2. 去除 Markdown 代码块标记（```json ... ``` 或 ``` ... ```）
        content_text = re.sub(r"^```(?:json)?\s*\n?", "", content_text.strip())
        content_text = re.sub(r"\n?```\s*$", "", content_text.strip())

        # 3. 用正则提取第一个完整的 JSON 对象 {...}
        #    处理模型在 JSON 前后附加说明文字的情况
        json_match = re.search(r"\{[\s\S]*\}", content_text)
        if json_match:
            content_text = json_match.group(0)

        # 4. 尝试解析 JSON
        parsed = json.loads(content_text)

        # 5. 校验返回的是 dict 而非 list 或其他类型
        if not isinstance(parsed, dict):
            print(f"[VLM] 模型返回了非字典类型: {type(parsed)}")
            return None

        print(f"[VLM] JSON 解析成功，字段: {list(parsed.keys())}")
        return parsed

    except json.JSONDecodeError as e:
        print(f"[VLM] JSON 解析失败: {e}")
        print(f"[VLM] 清理后内容(前800字符): {content_text[:800]}")
        return None
    except requests.exceptions.Timeout:
        print(f"[VLM] API 调用超时（180秒），图片可能过大")
        return None
    except Exception as e:
        print(f"[VLM] API 调用失败: {e}")
        return None


def call_embedding_api(text: str) -> Optional[List[float]]:
    """
    调用通义千问文本嵌入模型，将文本转换为向量表示。

    用于相似图纸推荐和语义搜索的向量计算。

    Args:
        text: 待嵌入的文本内容

    Returns:
        list[float]: 文本的向量嵌入，调用失败时返回 None
    """
    if not OPENAI_API_KEY:
        return None
    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/embeddings",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": OPENAI_EMBEDDING_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"[Embedding] API 调用失败: {e}")
        return None


def image_to_base64(image_bytes: bytes) -> str:
    """
    将图片二进制数据编码为 base64 字符串。

    Args:
        image_bytes: 图片的原始二进制数据

    Returns:
        str: base64 编码的字符串
    """
    return base64.b64encode(image_bytes).decode("utf-8")


def compress_image(image_bytes: bytes, max_size: int = 1024, quality: int = 85) -> bytes:
    """
    压缩图片以减少上传到 VLM 的数据量。

    对大尺寸图片进行缩放和 JPEG 压缩，在保持可读性的前提下减小体积。

    Args:
        image_bytes: 原始图片二进制数据
        max_size: 图片最大边长（像素），超过则等比缩放
        quality: JPEG 压缩质量 (1-100)

    Returns:
        bytes: 压缩后的图片二进制数据
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # 等比缩放，保持最大边不超过 max_size
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as e:
        print(f"[Image] 图片压缩失败: {e}")
        return image_bytes


# [CAD] DXF 文件渲染函数 — 将 CAD 图纸转换为图片供 VLM 解析
def dxf_to_images(dxf_bytes: bytes, dpi: int = 150) -> List[Image.Image]:
    """
    将 DXF 文件渲染为 PIL 图片列表。

    使用 ezdxf 读取 DXF 结构，matplotlib 将其渲染为黑白工程图风格的图片。
    每个 DXF 布局（Layout）渲染为一张图片，模型空间（Model）始终渲染。

    Args:
        dxf_bytes: DXF 文件的二进制数据
        dpi: 渲染分辨率

    Returns:
        list[Image.Image]: 渲染后的图片列表；失败时返回空列表
    """
    if not CAD_SUPPORT:
        print("[CAD] ezdxf 或 matplotlib 未安装，无法解析 DXF 文件")
        return []

    try:
        # 从字节流加载 DXF 文档
        doc = ezdxf.readfile(io.BytesIO(dxf_bytes))
        msp = doc.modelspace()  # 模型空间（主绘图区域）

        images = []
        # 遍历所有布局（Model + 用户创建的布局如 Layout1）
        for layout in doc.layouts:
            fig, ax = plt.subplots(figsize=(16, 12), dpi=dpi)
            ax.set_facecolor("white")
            ax.set_aspect("equal")
            ax.axis("off")

            # 使用 ezdxf 内置的 matplotlib 绘制后端渲染所有图元
            # 包括 LINE, ARC, CIRCLE, LWPOLYLINE, INSERT(块引用) 等
            from ezdxf.addons.drawing import RenderContext, Frontend
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

            ctx = RenderContext(doc)
            out = MatplotlibBackend(ax)
            Frontend(ctx, out).draw_layout(layout, finalize=True)

            # 将 matplotlib 图形转换为 PIL Image
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                        facecolor="white", edgecolor="none")
            plt.close(fig)
            buf.seek(0)
            images.append(Image.open(buf).convert("RGB"))

        return images if images else []

    except Exception as e:
        print(f"[CAD] DXF 渲染失败: {e}")
        return []


# [CAD] DWG 文件处理函数 — 占位实现，需配合外部转换工具
def dwg_to_images(dwg_bytes: bytes) -> List[Image.Image]:
    """
    将 DWG 文件渲染为图片（需要外部 ODA File Converter）。

    DWG 是 AutoCAD 私有格式，Python 无法直接解析。
    部署时需安装 ODA File Converter 并配置 DWG_CONVERTER_PATH 环境变量。
    下载地址: https://www.opendesign.com/guestfiles/oda_file_converter

    Args:
        dwg_bytes: DWG 文件的二进制数据

    Returns:
        list[Image.Image]: 渲染后的图片列表；不支持时返回空列表
    """
    # DWG 转换需要外部工具，当前返回空列表
    # 如需支持，请安装 ODA File Converter 并在此处实现转换逻辑
    print("[CAD] DWG 格式暂不支持直接解析，请将文件转换为 DXF 格式后重新上传")
    return []


def extract_text_for_embedding(info: dict) -> str:
    """
    从图纸结构化信息中提取文本摘要，用于生成向量嵌入。

    将零件名称、材料、尺寸、公差等关键信息组合为一段文本，
    以便后续进行向量相似度计算。

    Args:
        info: 图纸解析后的结构化 JSON 数据

    Returns:
        str: 用于嵌入的文本摘要
    """
    parts = []
    basic = info.get("basic_info", {})
    if basic.get("part_name"):
        parts.append(f"零件名称: {basic['part_name']}")
    if basic.get("material"):
        parts.append(f"材料: {basic['material']}")
    if basic.get("surface_treatment"):
        parts.append(f"表面处理: {basic['surface_treatment']}")

    dims = info.get("dimensions", {})
    if dims:
        dim_parts = []
        if dims.get("length"):
            dim_parts.append(f"长{dims['length']}mm")
        if dims.get("width"):
            dim_parts.append(f"宽{dims['width']}mm")
        if dims.get("height_thickness"):
            dim_parts.append(f"高{dims['height_thickness']}mm")
        if dim_parts:
            parts.append("尺寸: " + ", ".join(dim_parts))

    # 提取公差代号信息
    for tol in info.get("tolerances", []):
        if tol.get("tolerance_code"):
            parts.append(f"公差: {tol.get('dimension_name', '')} {tol['tolerance_code']}")

    return "; ".join(parts)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    计算两个向量的余弦相似度。

    Args:
        a: 向量 a
        b: 向量 b

    Returns:
        float: 余弦相似度 [-1, 1]
    """
    import numpy as np
    a_np = np.array(a)
    b_np = np.array(b)
    dot = np.dot(a_np, b_np)
    norm = np.linalg.norm(a_np) * np.linalg.norm(b_np)
    return float(dot / norm) if norm > 0 else 0.0


def compute_dimension_similarity(info_a: dict, info_b: dict) -> float:
    """
    计算两张图纸之间的尺寸相似度。

    基于长、宽、高三个维度的归一化差异进行评估。
    相似度范围 [0, 1]，1 表示完全相同。

    Args:
        info_a: 图纸 A 的结构化信息
        info_b: 图纸 B 的结构化信息

    Returns:
        float: 尺寸相似度分数
    """
    import numpy as np
    dims_a = info_a.get("dimensions", {})
    dims_b = info_b.get("dimensions", {})

    # 提取三维尺寸，缺失值用 0 替代
    vec_a = [dims_a.get("length", 0), dims_a.get("width", 0), dims_a.get("height_thickness", 0)]
    vec_b = [dims_b.get("length", 0), dims_b.get("width", 0), dims_b.get("height_thickness", 0)]

    a_np = np.array(vec_a, dtype=float)
    b_np = np.array(vec_b, dtype=float)

    max_dim = max(np.max(np.abs(a_np)), np.max(np.abs(b_np)), 1.0)
    diff = np.abs(a_np - b_np) / max_dim
    return float(1.0 - np.mean(diff))


def format_tolerances_for_frontend(raw_tolerances: list) -> list:
    """
    将 VLM 返回的原始公差数据转换为前端 DrawingInfo 组件期望的格式。

    前端 el-table 使用的列字段: feature（特征）、nominal（名义尺寸）、tolerance（公差）
    VLM 原始字段: dimension_name、basic_size、upper_deviation、lower_deviation、tolerance_code

    Args:
        raw_tolerances: VLM 返回的公差数组

    Returns:
        list: 格式化后的公差数组，适配前端表格展示
    """
    formatted = []
    for tol in raw_tolerances:
        # 构建公差描述字符串，例如 "+0.021 / -0.007" 或 "h7"
        upper = tol.get("upper_deviation", 0)
        lower = tol.get("lower_deviation", 0)
        code = tol.get("tolerance_code")

        if code:
            # 有公差代号时直接显示（如 h7、H8、f6）
            tol_str = code
        else:
            # 无代号时显示上下偏差
            upper_str = f"+{upper}" if upper >= 0 else str(upper)
            lower_str = f"+{lower}" if lower >= 0 else str(lower)
            tol_str = f"{upper_str} / {lower_str}"

        formatted.append({
            "feature": tol.get("dimension_name", ""),    # 特征名称（如"轴径 φ45"）
            "nominal": tol.get("basic_size", 0),         # 名义尺寸（如 45.0）
            "tolerance": tol_str,                         # 公差描述（如 "h7"）
            # 保留原始数据，供其他功能（如 SVG 标注）使用
            "_raw": tol,
        })
    return formatted


def run_parse_job(job_id: str, conv_uuid: str, image_bytes_list: List[bytes],
                  filename: str = "", upload_oss: bool = False):
    """
    后台异步执行图纸解析任务。

    流程：
      [CAD] 若为 CAD 文件 → 渲染为图片
      1. 压缩图片 → 2. 存储图片（本地或 OSS） → 3. 调用 VLM 解析 → 4. 生成嵌入 → 5. 保存结果

    Args:
        job_id: 任务唯一 ID
        conv_uuid: 关联的会话 UUID
        image_bytes_list: 文件二进制数据列表（图片/CAD）
        filename: [CAD] 原始文件名，用于判断文件类型
        upload_oss: [OSS] 是否上传到阿里云 OSS，默认 False（存储在本地）
    """
    try:
        # [CAD] CAD 文件预处理：将 DXF/DWG 渲染为图片再进入常规流程
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        if ext in (".dxf", ".dwg"):
            jobs[job_id]["status"] = "processing"
            jobs[job_id]["progress"] = "正在解析 CAD 图纸..."
            jobs[job_id]["progress_pct"] = 0.05

            if ext == ".dxf":
                rendered = dxf_to_images(image_bytes_list[0])
            else:
                rendered = dwg_to_images(image_bytes_list[0])

            if not rendered:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = (
                    f"无法解析 {ext} 文件。"
                    + ("请安装 ezdxf 和 matplotlib: pip install ezdxf matplotlib"
                       if not CAD_SUPPORT else "文件可能已损坏或格式不受支持")
                )
                return

            # 渲染成功，将 PIL Image 转为 JPEG 字节流，替换原始输入
            image_bytes_list = []
            for img in rendered:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                image_bytes_list.append(buf.getvalue())

        # ---------- 步骤 1: 压缩图片 ----------
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = "正在压缩图像..."
        jobs[job_id]["progress_pct"] = 0.1

        compressed_images = [compress_image(img) for img in image_bytes_list]

        # ---------- 步骤 2: 存储图片（本地 或 OSS） ----------
        jobs[job_id]["progress"] = "正在保存图像..."
        jobs[job_id]["progress_pct"] = 0.2

        # [OSS] 根据 upload_oss 标志决定存储位置
        image_urls = []
        for idx, img_bytes in enumerate(compressed_images):
            fname = f"{conv_uuid}_page_{idx+1}.jpg"
            if upload_oss:
                # 上传到阿里云 OSS
                url = upload_image_to_oss(img_bytes, fname)
            else:
                # 保存到本地 uploads/ 目录（默认行为）
                url = save_image_locally(img_bytes, fname)
            if url:
                image_urls.append(url)

        # ---------- 步骤 3: 调用 VLM 解析 ----------
        jobs[job_id]["progress"] = "AI 正在解析图纸，请稍候..."
        jobs[job_id]["progress_pct"] = 0.4

        image_b64_list = [image_to_base64(img) for img in compressed_images]
        parsed_info = call_vlm_api(image_b64_list)

        if parsed_info is None:
            # VLM 调用失败，标记任务失败并提示用户
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = (
                "AI 解析失败，请检查："
                "1) .env 中 OPENAI_MODEL 是否为多模态视觉模型（如 qwen-vl-max-latest）；"
                "2) OPENAI_API_KEY 是否有效；"
                "3) 图片是否清晰可读。"
                "详见后端控制台日志。"
            )
            return

        # ---------- 步骤 4: 生成向量嵌入 ----------
        jobs[job_id]["progress"] = "正在生成向量嵌入..."
        jobs[job_id]["progress_pct"] = 0.8

        text_summary = extract_text_for_embedding(parsed_info)
        embedding = call_embedding_api(text_summary)

        # ---------- 步骤 5: 保存解析结果 ----------
        jobs[job_id]["progress"] = "正在保存解析结果..."
        jobs[job_id]["progress_pct"] = 0.95

        conv_data = {
            "info": parsed_info,           # 结构化解析数据
            "image_urls": image_urls,      # [OSS] 图片存储地址（本地路径或 OSS URL）
            "image_count": len(image_bytes_list),
            "created_at": time.time(),
            "title": parsed_info.get("basic_info", {}).get("part_name", ""),
        }
        conversations[conv_uuid] = conv_data
        # 持久化到本地 JSON 文件，重启后可恢复
        save_conversation_to_disk(conv_uuid, conv_data)

        # 将解析结果加入知识库（用于相似推荐和搜索）
        knowledge_base[conv_uuid] = {
            "info": parsed_info,
            "embedding": embedding,
            "image_urls": image_urls,
        }

        # ---------- 任务完成 ----------
        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = "解析完成"
        jobs[job_id]["progress_pct"] = 1.0
        jobs[job_id]["conv_uuid"] = conv_uuid

    except Exception as e:
        # 任务异常处理
        print(f"[Job] 任务 {job_id} 执行失败: {e}")
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


# ================================================================
# API 路由 — 健康检查
# ================================================================

@app.route("/", methods=["GET"])
def health_check():
    """
    健康检查接口。

    前端通过此接口确认后端服务是否正常运行。
    对应前端: client.js → checkHealth()

    Returns:
        200: {"status": "ok"}
    """
    return jsonify({"status": "ok"})


# [OSS] 本地文件访问路由 — 供前端访问本地存储的图片
@app.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    """
    提供本地 uploads/ 目录下图片文件的 HTTP 访问。

    当用户选择本地存储时，前端通过此路由获取图片预览。

    Args:
        filename: 文件名（如 "xxx_page_1.jpg"）

    Returns:
        200: 图片文件二进制
        404: 文件不存在
    """
    from flask import send_from_directory
    return send_from_directory(LOCAL_STORAGE_DIR, filename)


# ================================================================
# API 路由 — 图纸会话管理
# ================================================================

@app.route("/conversation/new", methods=["POST"])
def create_conversation():
    """
    上传图纸并创建异步解析任务。

    接收 multipart/form-data 格式的图片/CAD 文件，创建后台解析任务。
    对应前端: drawing.js → createDrawingTask()

    请求格式:
        Content-Type: multipart/form-data
        字段:
          - image: 图片/CAD 文件（可多张，支持多页图纸；[CAD] 支持 .dxf/.dwg）
          - priority: 任务优先级（数字，值越小优先级越高）
          - upload_oss: [OSS] 是否上传到云端 OSS（"true"/"false"，默认 "false"）

    Returns:
        200: {"job_id": "xxx", "conv_uuid": "xxx"}
        400: {"error": "未上传图片"}
    """
    # 获取上传的文件列表（图片或 CAD 文件）
    files = request.files.getlist("image")
    if not files:
        return jsonify({"error": "未上传图片"}), 400

    # 读取优先级参数（默认为 10，数值越小优先级越高）
    priority = int(request.form.get("priority", 10))

    # [OSS] 读取是否上传到云端 OSS（默认 False，存储在本地）
    upload_oss = request.form.get("upload_oss", "false").lower() == "true"

    # 读取所有文件的二进制数据，并记录第一个文件名（用于 [CAD] 类型判断）
    image_bytes_list = []
    first_filename = ""
    for f in files:
        if not first_filename:
            first_filename = f.filename or ""
        image_bytes_list.append(f.read())

    # 生成唯一标识
    conv_uuid = generate_uuid()
    job_id = generate_uuid()

    # 初始化任务状态
    jobs[job_id] = {
        "status": "pending",        # 任务状态: pending / processing / done / failed
        "progress": "等待处理...",    # 当前进度描述
        "progress_pct": 0.0,        # 进度百分比 (0.0 ~ 1.0)
        "conv_uuid": conv_uuid,     # 关联的会话 ID
        "created_at": time.time(),  # 创建时间
    }

    # 记录任务优先级
    with priority_lock:
        job_priorities[job_id] = priority

    # 提交到线程池异步执行（[CAD] 传递文件名以支持 CAD 格式检测；[OSS] 传递存储选项）
    executor.submit(run_parse_job, job_id, conv_uuid, image_bytes_list, first_filename, upload_oss)

    return jsonify({"job_id": job_id, "conv_uuid": conv_uuid})


@app.route("/conversation/list", methods=["GET"])
def list_conversations():
    """
    获取所有已解析图纸的列表。

    返回 conv_uuid -> title 的映射字典，供前端侧边栏展示历史图纸。
    对应前端: drawing.js → getConversationList()

    Returns:
        200: {"uuid1": "零件名称1", "uuid2": "零件名称2", ...}
    """
    result = {}
    for conv_uuid, data in conversations.items():
        title = data.get("title", "")
        result[conv_uuid] = title
    return jsonify(result)


@app.route("/conversation/<conv_uuid>/info", methods=["GET"])
def get_conversation_info(conv_uuid):
    """
    获取指定图纸的解析结果。

    返回前端展示所需的结构化信息（基本尺寸、公差等）。
    对应前端: drawing.js → getDrawingInfo()
    前端组件: DrawingInfo.vue 使用此数据展示图纸详情

    Args:
        conv_uuid: 图纸会话 UUID

    Returns:
        200: 图纸结构化信息 JSON
        404: {"error": "图纸不存在"}
    """
    conv = conversations.get(conv_uuid)
    if not conv:
        return jsonify({"error": "图纸不存在"}), 404

    info = conv["info"]

    # 转换公差格式以适配前端 DrawingInfo 组件的 el-table 列定义
    # 前端期望: feature / nominal / tolerance
    # VLM 返回: dimension_name / basic_size / upper_deviation / lower_deviation
    frontend_info = dict(info)
    if "tolerances" in frontend_info:
        frontend_info["tolerances"] = format_tolerances_for_frontend(info.get("tolerances", []))

    return jsonify(frontend_info)


@app.route("/conversation/<conv_uuid>/review", methods=["POST"])
def review_conversation(conv_uuid):
    """
    对图纸进行合规性审查。

    基于预设国标规则和用户自定义规则，对图纸进行全面审查。
    对应前端: drawing.js → getReviewReport()
    前端组件: ReviewPanel.vue 展示审查结果

    Args:
        conv_uuid: 图纸会话 UUID

    请求体 (JSON):
        {
            "custom_rules": "企业自定义规则文本（可选）"
        }

    Returns:
        200: 审查报告 JSON，包含 overall_pass / risk_level / issues / summary
        404: {"error": "图纸不存在"}
    """
    conv = conversations.get(conv_uuid)
    if not conv:
        return jsonify({"error": "图纸不存在"}), 404

    # 获取用户自定义审查规则
    body = request.get_json(silent=True) or {}
    custom_rules = body.get("custom_rules", "")

    info = conv["info"]

    # ---------- 执行审查逻辑 ----------
    # 这里实现基于规则的自动化审查
    # 生产环境中可扩展为调用 LLM 进行更深入的审查
    issues = []
    basic = info.get("basic_info", {})
    dims = info.get("dimensions", {})
    tolerances = info.get("tolerances", [])

    # 规则 1: 检查必要字段是否完整
    if not basic.get("part_name"):
        issues.append({
            "severity": "WARNING",
            "description": "图纸缺少零件名称",
            "suggestion": "请在标题栏中明确标注零件名称",
            "reference": "GB/T 4458.1",
        })

    if not basic.get("drawing_number"):
        issues.append({
            "severity": "WARNING",
            "description": "图纸缺少图号",
            "suggestion": "请在标题栏中标注唯一图号",
            "reference": "GB/T 4458.1",
        })

    if not basic.get("material"):
        issues.append({
            "severity": "ERROR",
            "description": "图纸缺少材料标注",
            "suggestion": "请在标题栏中标注材料牌号及标准号",
            "reference": "GB/T 4458.1",
        })

    # 规则 2: 检查尺寸合理性
    if dims.get("length", 0) <= 0 or dims.get("width", 0) <= 0:
        issues.append({
            "severity": "WARNING",
            "description": "主要尺寸信息不完整或为零",
            "suggestion": "请确认图纸中是否标注了完整的外形尺寸",
            "reference": "GB/T 4458.4",
        })

    # 规则 3: 检查公差标注
    if not tolerances:
        issues.append({
            "severity": "WARNING",
            "description": "未检测到尺寸公差标注",
            "suggestion": "关键配合尺寸应标注公差",
            "reference": "GB/T 1800.1",
        })

    # 规则 4: 检查形位公差
    if not info.get("geometric_tolerances"):
        issues.append({
            "severity": "WARNING",
            "description": "未检测到形位公差标注",
            "suggestion": "关键特征应考虑标注形位公差",
            "reference": "GB/T 1182",
        })

    # 规则 5: 检查表面粗糙度
    if not info.get("surface_roughness"):
        issues.append({
            "severity": "WARNING",
            "description": "未检测到表面粗糙度标注",
            "suggestion": "配合面和重要表面应标注粗糙度",
            "reference": "GB/T 131",
        })

    # 规则 6: 应用自定义规则（如有）
    if custom_rules:
        # 简单的关键词匹配规则引擎
        # 生产环境可替换为 LLM 驱动的智能审查
        custom_lines = [line.strip() for line in custom_rules.split("\n") if line.strip()]
        material = basic.get("material", "")
        for rule in custom_lines:
            # 示例: "禁止使用 Q235 材料"
            if "禁止" in rule and "材料" in rule:
                forbidden = rule.replace("禁止使用", "").replace("材料", "").strip()
                if forbidden and forbidden in material:
                    issues.append({
                        "severity": "ERROR",
                        "description": f"违反自定义规则：使用了被禁止的材料 {forbidden}",
                        "suggestion": f"请更换材料，当前材料: {material}",
                        "reference": "企业自定义规则",
                    })

    # ---------- 综合评估 ----------
    error_count = sum(1 for i in issues if i["severity"] == "ERROR")
    warning_count = sum(1 for i in issues if i["severity"] == "WARNING")

    # 风险等级判定
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

    # 生成审查摘要
    if overall_pass:
        summary = f"图纸审查通过。发现 {warning_count} 个改进建议。"
    else:
        summary = f"图纸审查未通过。发现 {error_count} 个错误和 {warning_count} 个警告，请修正后重新提交。"

    report = {
        "overall_pass": overall_pass,    # 是否通过
        "risk_level": risk_level,         # 风险等级: NONE / LOW / MEDIUM / HIGH
        "issues": issues,                 # 问题列表
        "summary": summary,               # 审查摘要
        "error_count": error_count,
        "warning_count": warning_count,
    }

    return jsonify(report)


@app.route("/conversation/<conv_uuid>/ask", methods=["POST"])
def ask_question(conv_uuid):
    """
    基于图纸上下文的智能问答。

    用户输入问题，系统结合图纸解析结果调用 LLM 生成回答。
    对应前端: drawing.js → askDrawingQuestion()
    前端组件: ChatPanel.vue 展示对话

    Args:
        conv_uuid: 图纸会话 UUID

    请求体 (JSON):
        {
            "question": "用户的问题文本"
        }

    Returns:
        200: {"answer": "AI 的回答"}
        400: {"error": "请输入问题"}
        404: {"error": "图纸不存在"}
    """
    conv = conversations.get(conv_uuid)
    if not conv:
        return jsonify({"error": "图纸不存在"}), 404

    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    if not question:
        return jsonify({"error": "请输入问题"}), 400

    info = conv["info"]

    # ---------- 构建问答上下文 ----------
    # 将图纸结构化信息作为上下文提供给 LLM
    context = json.dumps(info, ensure_ascii=False, indent=2)

    if not OPENAI_API_KEY:
        # 未配置 API Key 时返回模拟回答（开发调试用）
        return jsonify({
            "answer": f"[模拟回答] 关于您的问题「{question}」，基于当前图纸信息："
                      f"零件名称为 {info.get('basic_info', {}).get('part_name', '未知')}，"
                      f"材料为 {info.get('basic_info', {}).get('material', '未知')}。"
                      f"（注：请配置 OPENAI_API_KEY 以获取真实 AI 回答）"
        })

    try:
        # 调用 LLM 进行问答
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一名专业的机械工程师助手。"
                            "根据用户提供的工程图纸信息回答问题。"
                            "回答应准确、专业、简洁。"
                            "如果图纸信息中没有相关内容，请如实说明。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"图纸信息:\n{context}\n\n问题: {question}",
                    },
                ],
                "max_tokens": 2048,
                "temperature": 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"[Ask] LLM 调用失败: {e}")
        return jsonify({"error": f"AI 回答生成失败: {str(e)}"}), 500


# ================================================================
# API 路由 — 异步任务管理
# ================================================================

@app.route("/job/<job_id>/status", methods=["GET"])
def get_job_status(job_id):
    """
    查询异步解析任务的执行状态。

    前端通过轮询此接口实时更新进度条。
    对应前端: job.js → getJobStatus()
    前端组件: TaskProgress.vue 每 3 秒轮询一次

    Args:
        job_id: 任务 ID

    Returns:
        200: {
            "status": "pending" | "processing" | "done" | "failed",
            "progress": "进度描述文本",
            "progress_pct": 0.0 ~ 1.0,
            "conv_uuid": "xxx",      // 仅 status=done 时返回
            "error": "xxx"           // 仅 status=failed 时返回
        }
        404: {"error": "任务不存在"}
    """
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404

    return jsonify({
        "status": job["status"],
        "progress": job.get("progress", ""),
        "progress_pct": job.get("progress_pct", 0),
        "conv_uuid": job.get("conv_uuid"),
        "error": job.get("error"),
    })


@app.route("/job/<job_id>/prioritize", methods=["POST"])
def prioritize_job(job_id):
    """
    提升异步任务的优先级。

    当用户切换到正在解析的图纸时，前端自动调用此接口
    以优先处理用户当前查看的图纸。
    对应前端: job.js → prioritizeJob()
    前端触发时机: DrawingSidebar.vue 切换图纸时

    Args:
        job_id: 任务 ID

    请求体 (JSON):
        {
            "priority": 0    // 优先级值，0 为最高
        }

    Returns:
        200: {"status": "ok", "job_id": "xxx"}
        404: {"error": "任务不存在"}
    """
    if job_id not in jobs:
        return jsonify({"error": "任务不存在"}), 404

    body = request.get_json(silent=True) or {}
    new_priority = body.get("priority", 0)

    # 更新优先级记录
    with priority_lock:
        job_priorities[job_id] = new_priority

    # 更新任务状态提示
    jobs[job_id]["progress"] = "优先级已提升，正在加速处理..."

    return jsonify({"status": "ok", "job_id": job_id})


# ================================================================
# API 路由 — 知识库（相似推荐 & 语义搜索）
# ================================================================

@app.route("/knowledge/similar/<conv_uuid>", methods=["GET"])
def get_similar_drawings(conv_uuid):
    """
    查找与指定图纸相似的历史图纸。

    使用语义向量相似度和尺寸相似度的加权组合进行排序。
    对应前端: knowledge.js → getSimilarDrawings()
    前端组件: SimilarPanel.vue 展示推荐结果

    Args:
        conv_uuid: 作为参考的图纸会话 UUID

    Query Parameters:
        top_k (int): 返回结果数量，默认 5
        alpha (float): 语义相似度权重，默认 0.7
        beta (float): 尺寸相似度权重，默认 0.3

    Returns:
        200: [
            {
                "conv_uuid": "xxx",
                "part_name": "零件名称",
                "drawing_number": "图号",
                "material": "材料",
                "score": 0.85
            },
            ...
        ]
        404: {"error": "图纸不存在"}
    """
    if conv_uuid not in knowledge_base:
        return jsonify({"error": "图纸不存在"}), 404

    # 读取查询参数
    top_k = int(request.args.get("top_k", 5))
    alpha = float(request.args.get("alpha", 0.7))   # 语义权重
    beta = float(request.args.get("beta", 0.3))      # 尺寸权重

    ref_entry = knowledge_base[conv_uuid]
    ref_info = ref_entry["info"]
    ref_embedding = ref_entry.get("embedding")

    results = []
    for other_uuid, entry in knowledge_base.items():
        if other_uuid == conv_uuid:
            continue  # 跳过自身

        # 计算语义相似度（基于向量余弦相似度）
        sem_score = 0.0
        if ref_embedding and entry.get("embedding"):
            sem_score = cosine_similarity(ref_embedding, entry["embedding"])
            sem_score = max(0.0, sem_score)  # 截断负值

        # 计算尺寸相似度
        dim_score = compute_dimension_similarity(ref_info, entry["info"])

        # 加权综合分数
        final_score = alpha * sem_score + beta * dim_score

        other_info = entry["info"]
        results.append({
            "conv_uuid": other_uuid,
            "part_name": other_info.get("basic_info", {}).get("part_name", ""),
            "drawing_number": other_info.get("basic_info", {}).get("drawing_number", ""),
            "material": other_info.get("basic_info", {}).get("material", ""),
            "score": round(final_score, 4),
        })

    # 按相似度降序排序，取 top_k
    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(results[:top_k])


@app.route("/knowledge/search", methods=["POST"])
def semantic_search():
    """
    基于关键词的语义搜索。

    将用户输入的关键词转换为向量，与知识库中的图纸进行匹配。
    对应前端: knowledge.js → semanticSearch()
    前端组件: SimilarPanel.vue 底部搜索区域

    请求体 (JSON):
        {
            "keyword": "搜索关键词",
            "top_k": 5       // 可选，默认 5
        }

    Returns:
        200: [
            {
                "conv_uuid": "xxx",
                "part_name": "零件名称",
                "drawing_number": "图号",
                "score": 0.85
            },
            ...
        ]
        400: {"error": "请输入搜索关键词"}
    """
    body = request.get_json(silent=True) or {}
    keyword = body.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入搜索关键词"}), 400

    top_k = int(body.get("top_k", 5))

    # 将搜索关键词转换为向量
    query_embedding = call_embedding_api(keyword)

    results = []
    for conv_uuid, entry in knowledge_base.items():
        if query_embedding and entry.get("embedding"):
            # 基于向量相似度匹配
            score = cosine_similarity(query_embedding, entry["embedding"])
            score = max(0.0, score)
        else:
            # 降级方案：简单的关键词匹配
            info_text = json.dumps(entry["info"], ensure_ascii=False)
            score = 1.0 if keyword.lower() in info_text.lower() else 0.0

        if score > 0:
            info = entry["info"]
            results.append({
                "conv_uuid": conv_uuid,
                "part_name": info.get("basic_info", {}).get("part_name", ""),
                "drawing_number": info.get("basic_info", {}).get("drawing_number", ""),
                "score": round(score, 4),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(results[:top_k])


# ================================================================
# 服务启动入口
# ================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  DraftMind 后端服务启动中...")
    print(f"  API 地址: http://127.0.0.1:5000")
    print(f"  VLM 模型: {OPENAI_MODEL}")
    print(f"  OSS 存储桶: {OSS_BUCKET_NAME or '(未配置)'}")
    print("=" * 50)

    # 启动 Flask 开发服务器
    # 生产环境应使用 gunicorn 或 uvicorn
    app.run(host="127.0.0.1", port=5000, debug=True)
