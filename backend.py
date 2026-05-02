from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import oss2
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI, BadRequestError
from PIL import Image


# ================================================================
# 审图 Prompt 模板
# ================================================================

_REVIEW_PROMPT_TEMPLATE = """\
你是一名资深机械设计工程师，精通《机械设计手册》、GB/T 4458 系列制图国标及相关行业标准。
请对以下图纸结构化数据进行全面合规性审查，并以 JSON 格式输出审查报告。

## 审查维度
1. 尺寸标注完整性：长/宽/高是否缺失（数值为 0 视为缺失）；关键配合尺寸是否标注公差
2. 公差合理性：是否符合 GB/T 1800 标准等级；上下偏差符号是否正确；尺寸链是否闭合
3. 材料选型合理性：材料牌号与零件功能、载荷、使用环境的匹配度
4. 表面处理适配性：工艺与材料兼容性；粗糙度值与配合面功能需求的对应关系
5. 形位公差规范性：基准选取合理性；公差值松紧是否适当
6. 技术要求完整性：关键加工要求、热处理要求、检验要求是否遗漏
{CUSTOM_RULES_SECTION}
## 待审图纸结构化数据
{DRAWING_JSON}

## 输出要求
只输出以下结构的 JSON 对象，不添加任何其他文字或代码块标记。
字段说明：
- overall_pass: boolean，无 ERROR 级问题时为 true，有 ERROR 时为 false
- risk_level: "LOW"（无ERROR）/"MEDIUM"（有WARNING无ERROR）/"HIGH"（有ERROR）
- issues: 数组，每项含 category/severity/description/suggestion/reference
  - category 可选值: 尺寸标注、公差、材料、表面处理、形位公差、技术要求
  - severity 可选值: ERROR（必须修改）、WARNING（建议修改）、INFO（参考建议）
  - description: 具体问题描述
  - suggestion: 具体修改建议
  - reference: 参考标准，如 GB/T 4458.4-2003，无则填空字符串
- summary: 总体评价字符串，100 字以内
"""


# ================================================================
# 加载主 Prompt
# ================================================================

def _load_main_prompt() -> str:
    with open("main_prompt.md", "r", encoding="utf-8") as f:
        return f.read()

_MAIN_PROMPT: str = _load_main_prompt()


# ================================================================
# Logger
# ================================================================

class Logger:
    @staticmethod
    def _log(level: str, message: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] [{level}] {message}")

    @classmethod
    def info(cls, message: str) -> None:
        cls._log("INFO", message)

    @classmethod
    def warning(cls, message: str) -> None:
        cls._log("WARNING", message)

    @classmethod
    def error(cls, message: str) -> None:
        cls._log("ERROR", message)


# ================================================================
# 后端配置
# ================================================================

class BackendConfig:
    _REQUIRED: List[str] = [
        "OSS_ENDPOINT", "OSS_ACCESS_KEY", "OSS_ACCESS_SECRET", "OSS_BUCKET_NAME",
        "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_MODEL", "OPENAI_MAX_TOKENS",
    ]
    _OPTIONAL: Dict[str, str] = {
        # DashScope OpenAI-compatible mode supports text embedding models like:
        # - text-embedding-v3 / text-embedding-v4
        # While OpenAI official endpoints use text-embedding-3-*
        "OPENAI_EMBEDDING_MODEL": "text-embedding-v3",
    }

    def __init__(self) -> None:
        for key in self._REQUIRED:
            setattr(self, key, "")
        for key, default in self._OPTIONAL.items():
            setattr(self, key, default)

    @staticmethod
    def _normalize_api_base(url: str) -> str:
        normalized = url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/responses", "/completions"):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]
        return normalized

    def load(self) -> None:
        Logger.info("从 .env 文件加载环境变量...")
        load_dotenv()
        missing = 0
        for key in self._REQUIRED:
            if key in os.environ:
                value = os.environ[key]
                if key == "OPENAI_API_BASE":
                    value = self._normalize_api_base(value)
                setattr(self, key, value)
                Logger.info(f"  [OK] {key} = {value}")
            else:
                Logger.error(f"  [MISSING] 必需变量 {key} 未设置!")
                missing += 1
        for key, default in self._OPTIONAL.items():
            if key in os.environ:
                setattr(self, key, os.environ[key])
                Logger.info(f"  [OK] {key} = {os.environ[key]}")
            else:
                Logger.info(f"  [DEFAULT] {key} = {default}")
        if missing:
            Logger.error(f"{missing} 个必需环境变量未设置，即将退出")
            exit(1)


# ================================================================
# 图像工具函数（优化核心）
# ================================================================

def compress_image(content: bytes, max_size: int = 1920, quality: int = 85) -> bytes:
    """
    压缩图像以减少上传大小和 LLM token 消耗。
    - 限制最长边不超过 max_size 像素
    - 使用 JPEG 格式，quality=85 在清晰度和体积间取得平衡
    """
    img = Image.open(BytesIO(content))
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        Logger.info(f"图像已缩放: {w}x{h} -> {new_w}x{new_h}")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    compressed = buf.getvalue()
    Logger.info(
        f"图像压缩完成: {len(content) / 1024:.1f}KB -> {len(compressed) / 1024:.1f}KB"
    )
    return compressed


def image_to_base64_url(content: bytes) -> str:
    """
    将图像字节转为 data URL，可直接传入 OpenAI vision API。
    跳过 OSS 上传等待，大幅减少 LLM 调用前的等待时间。
    """
    b64 = base64.b64encode(content).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


# ================================================================
# OSS 操作
# ================================================================

class OSSOperation:
    def __init__(self) -> None:
        self._bucket: Optional[oss2.Bucket] = None

    def init_bucket(self, config: BackendConfig) -> None:
        auth = oss2.Auth(config.OSS_ACCESS_KEY, config.OSS_ACCESS_SECRET)
        self._bucket = oss2.Bucket(
            auth, endpoint=config.OSS_ENDPOINT, bucket_name=config.OSS_BUCKET_NAME
        )

    def get_bucket(self) -> oss2.Bucket:
        if self._bucket is None:
            raise RuntimeError("存储桶尚未初始化，请先调用 init_bucket()")
        return self._bucket

    def test_bucket(self) -> None:
        try:
            self.get_bucket().get_bucket_info()
            Logger.info("成功连接到 OSS 存储桶")
        except Exception as exc:
            Logger.error("无法连接到 OSS 存储桶，请检查配置!")
            raise exc

    def upload(self, conv_id: str, content: bytes) -> str:
        """上传已压缩的 JPEG 字节到 OSS，返回永久 URL"""
        file_id = str(uuid.uuid4())
        path = f"{conv_id}/{file_id}.jpg"
        self.get_bucket().put_object(path, content)
        return f"https://draftmind.oss-cn-beijing.aliyuncs.com/{path}"


# ================================================================
# 图纸数据模型
# ================================================================

def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class BasicInfo:
    part_name: str
    drawing_number: str
    material: str
    surface_treatment: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BasicInfo":
        return cls(
            part_name=str(data.get("part_name") or ""),
            drawing_number=str(data.get("drawing_number") or ""),
            material=str(data.get("material") or ""),
            surface_treatment=str(data.get("surface_treatment") or "无"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Dimensions:
    length: float
    width: float
    height_thickness: float
    other_dimensions: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Dimensions":
        return cls(
            length=_to_float(data.get("length")),
            width=_to_float(data.get("width")),
            height_thickness=_to_float(data.get("height_thickness")),
            other_dimensions=data.get("other_dimensions"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Tolerance:
    dimension_name: str
    basic_size: float
    upper_deviation: float
    lower_deviation: float
    tolerance_code: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Tolerance":
        return cls(
            dimension_name=str(data.get("dimension_name") or ""),
            basic_size=_to_float(data.get("basic_size")),
            upper_deviation=_to_float(data.get("upper_deviation")),
            lower_deviation=_to_float(data.get("lower_deviation")),
            tolerance_code=data.get("tolerance_code"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeometricTolerance:
    item: str
    value: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GeometricTolerance":
        return cls(
            item=str(data.get("item") or ""),
            value=_to_float(data.get("value")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SurfaceRoughness:
    surface_location: str
    value: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SurfaceRoughness":
        return cls(
            surface_location=str(data.get("surface_location") or ""),
            value=_to_float(data.get("value")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PartDrawing:
    basic_info: BasicInfo
    dimensions: Dimensions
    tolerances: List[Tolerance] = field(default_factory=list)
    geometric_tolerances: List[GeometricTolerance] = field(default_factory=list)
    surface_roughness: List[SurfaceRoughness] = field(default_factory=list)
    technical_requirements: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PartDrawing":
        return cls(
            basic_info=BasicInfo.from_dict(data.get("basic_info") or {}),
            dimensions=Dimensions.from_dict(data.get("dimensions") or {}),
            tolerances=[
                Tolerance.from_dict(t) for t in (data.get("tolerances") or [])
            ],
            geometric_tolerances=[
                GeometricTolerance.from_dict(gt)
                for gt in (data.get("geometric_tolerances") or [])
            ],
            surface_roughness=[
                SurfaceRoughness.from_dict(sr)
                for sr in (data.get("surface_roughness") or [])
            ],
            technical_requirements=data.get("technical_requirements") or [],
        )

    @classmethod
    def from_json(cls, json_str: str) -> "PartDrawing":
        return cls.from_dict(json.loads(json_str))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)


# ================================================================
# 对话管理
# ================================================================

@dataclass
class DraftInformation:
    title: str = ""
    draft_number: str = ""


class AIConversation:
    def __init__(self) -> None:
        self.main_contents: List[List[dict]] = []
        self.ask_contents: List[List[dict]] = []
        self.information: DraftInformation = DraftInformation()

    def get_full_context(self) -> List[dict]:
        result: List[dict] = []
        for turn in self.main_contents:
            result.extend(turn)
        for turn in self.ask_contents:
            result.extend(turn)
        return result

    def clear_questions(self) -> None:
        self.ask_contents = []

    def set_information(self, info: DraftInformation) -> None:
        self.information = info

    def get_information(self) -> DraftInformation:
        return self.information

    def to_dict(self) -> dict:
        return {
            "info": asdict(self.information),
            "main_contents": self.main_contents,
            "ask_contents": self.ask_contents,
        }

    @staticmethod
    def from_dict(data: dict) -> "AIConversation":
        conv = AIConversation()
        conv.main_contents = data.get("main_contents") or []
        conv.ask_contents = data.get("ask_contents") or []
        conv.information = DraftInformation(**(data.get("info") or {}))
        return conv


class ConvStore:
    def __init__(self) -> None:
        self.conversations: Dict[str, AIConversation] = {}
        self.uuid_to_title: Dict[str, str] = {}

    def get(self, conv_uuid: str) -> AIConversation:
        if conv_uuid not in self.conversations:
            raise KeyError(f"对话 {conv_uuid} 不存在")
        return self.conversations[conv_uuid]

    def new(self) -> str:
        conv_uuid = str(uuid.uuid4())
        self.conversations[conv_uuid] = AIConversation()
        return conv_uuid

    def save(self) -> None:
        os.makedirs("./conversations", exist_ok=True)
        for conv_uuid, conv in self.conversations.items():
            with open(f"./conversations/{conv_uuid}.json", "w", encoding="utf-8") as f:
                json.dump(conv.to_dict(), f, ensure_ascii=False, indent=4)
        with open("./conversations/index.json", "w", encoding="utf-8") as f:
            json.dump(self.uuid_to_title, f, ensure_ascii=False, indent=4)

    def load(self) -> None:
        os.makedirs("./conversations", exist_ok=True)
        for filename in os.listdir("./conversations"):
            if not filename.endswith(".json"):
                continue
            if filename == "index.json":
                continue
            conv_uuid = filename[:-5]
            path = f"./conversations/{filename}"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.conversations[conv_uuid] = AIConversation.from_dict(json.load(f))
                Logger.info(f"已加载对话: {conv_uuid}")
            except Exception as exc:
                Logger.warning(f"跳过损坏的对话文件 {filename}: {exc}")

        index_path = "./conversations/index.json"
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                self.uuid_to_title = json.load(f)
        else:
            self.uuid_to_title = {
                cid: conv.get_information().title
                for cid, conv in self.conversations.items()
            }


# ================================================================
# 异步任务管理（优化核心）
# ================================================================

@dataclass
class Job:
    job_id: str
    status: str = "pending"       # pending / processing / done / failed
    progress: str = "等待处理..."
    conv_uuid: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class JobStore:
    """
    线程安全的后台任务存储器。
    所有对 _jobs 的读写均通过 _lock 保护。
    """
    _JOB_TTL = 3600  # 已完成任务保留 1 小时后清理

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(job_id=str(uuid.uuid4()))
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)

    def cleanup(self) -> None:
        """清理超过 TTL 的已完成/失败任务，防止内存泄漏"""
        now = time.time()
        with self._lock:
            expired = [
                jid for jid, j in self._jobs.items()
                if j.status in ("done", "failed")
                and now - j.created_at > self._JOB_TTL
            ]
            for jid in expired:
                del self._jobs[jid]
            if expired:
                Logger.info(f"已清理 {len(expired)} 个过期任务")


# ================================================================
# 审图数据模型
# ================================================================

@dataclass
class ReviewIssue:
    category: str
    severity: str
    description: str
    suggestion: str
    reference: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewIssue":
        return cls(
            category=str(data.get("category") or ""),
            severity=str(data.get("severity") or "INFO"),
            description=str(data.get("description") or ""),
            suggestion=str(data.get("suggestion") or ""),
            reference=str(data.get("reference") or ""),
        )


@dataclass
class ReviewReport:
    overall_pass: bool
    risk_level: str
    issues: List[ReviewIssue] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_pass": self.overall_pass,
            "risk_level": self.risk_level,
            "issues": [i.to_dict() for i in self.issues],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewReport":
        return cls(
            overall_pass=bool(data.get("overall_pass", False)),
            risk_level=str(data.get("risk_level") or "HIGH"),
            issues=[ReviewIssue.from_dict(i) for i in (data.get("issues") or [])],
            summary=str(data.get("summary") or ""),
        )


# ================================================================
# 知识库
# ================================================================

@dataclass
class KnowledgeEntry:
    conv_uuid: str
    part_name: str
    drawing_number: str
    material: str
    surface_treatment: str
    length: float
    width: float
    height_thickness: float
    technical_requirements: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEntry":
        return cls(
            conv_uuid=str(data.get("conv_uuid") or ""),
            part_name=str(data.get("part_name") or ""),
            drawing_number=str(data.get("drawing_number") or ""),
            material=str(data.get("material") or ""),
            surface_treatment=str(data.get("surface_treatment") or ""),
            length=_to_float(data.get("length")),
            width=_to_float(data.get("width")),
            height_thickness=_to_float(data.get("height_thickness")),
            technical_requirements=data.get("technical_requirements") or [],
            embedding=data.get("embedding") or [],
        )


class DrawingKnowledgeBase:
    _DB_PATH = "./knowledge_base/entries.json"

    def __init__(self) -> None:
        self.entries: List[KnowledgeEntry] = []
        self._lock = threading.Lock()
        os.makedirs("./knowledge_base", exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._DB_PATH):
            return
        try:
            with open(self._DB_PATH, "r", encoding="utf-8") as f:
                self.entries = [KnowledgeEntry.from_dict(d) for d in json.load(f)]
            Logger.info(f"知识库加载完成，共 {len(self.entries)} 条记录")
        except Exception as exc:
            Logger.warning(f"知识库加载失败: {exc}")

    def _save(self) -> None:
        with open(self._DB_PATH, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f, ensure_ascii=False, indent=2)

    def upsert(self, entry: KnowledgeEntry) -> None:
        with self._lock:
            for i, e in enumerate(self.entries):
                if e.conv_uuid == entry.conv_uuid:
                    self.entries[i] = entry
                    self._save()
                    return
            self.entries.append(entry)
            self._save()

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        va = np.array(a, dtype=float)
        vb = np.array(b, dtype=float)
        denom = float(np.linalg.norm(va)) * float(np.linalg.norm(vb))
        return float(np.dot(va, vb) / denom) if denom > 1e-9 else 0.0

    @staticmethod
    def _dim_sim(e: KnowledgeEntry, q: KnowledgeEntry) -> float:
        de = np.array([e.length, e.width, e.height_thickness], dtype=float)
        dq = np.array([q.length, q.width, q.height_thickness], dtype=float)
        norm_q = max(float(np.linalg.norm(dq)), 1.0)
        return float(np.exp(-float(np.linalg.norm(de - dq)) / norm_q))

    def search(
        self,
        query: KnowledgeEntry,
        top_k: int = 5,
        alpha: float = 0.7,
        beta: float = 0.3,
    ) -> List[Tuple[KnowledgeEntry, float]]:
        scores: List[Tuple[KnowledgeEntry, float]] = []
        for e in self.entries:
            if e.conv_uuid == query.conv_uuid:
                continue
            sem = (
                self._cosine(e.embedding, query.embedding)
                if e.embedding and query.embedding
                else 0.0
            )
            dim = self._dim_sim(e, query)
            scores.append((e, round(alpha * sem + beta * dim, 4)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ================================================================
# OpenAI 实现
# ================================================================

class OpenAIImpl:
    def __init__(self, config: BackendConfig) -> None:
        self.model = config.OPENAI_MODEL
        self.max_tokens = int(config.OPENAI_MAX_TOKENS)
        self.embedding_model = config.OPENAI_EMBEDDING_MODEL
        self.client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )

    def get_response(
        self,
        prompt: str,
        conversation: AIConversation,
        direction: str,
        image_url: Optional[str] = None,
    ) -> str:
        if image_url:
            new_msg: dict = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        else:
            new_msg = {"role": "user", "content": prompt}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=conversation.get_full_context() + [new_msg],
            max_tokens=self.max_tokens,
        )
        reply = response.choices[0].message.content

        turn = [new_msg, {"role": "assistant", "content": reply}]
        if direction == "main":
            conversation.main_contents.append(turn)
        elif direction == "ask":
            conversation.ask_contents.append(turn)
        return reply

    def get_embedding(self, text: str) -> List[float]:
        normalized = (text or "").strip()
        if not normalized:
            return []

        # Try configured model first, then fall back across common providers.
        # This project may point base_url to a 3rd-party OpenAI-compatible gateway
        # (e.g. DashScope), where model names differ from OpenAI official endpoints.
        fallback_models = [
            self.embedding_model,
            "text-embedding-v4",
            "text-embedding-v3",
            "text-embedding-v2",
            "text-embedding-3-large",
            "text-embedding-3-small",
            "text-embedding-ada-002",
        ]
        tried: List[str] = []
        last_exc: Optional[Exception] = None

        for m in fallback_models:
            if not m or m in tried:
                continue
            tried.append(m)
            try:
                resp = self.client.embeddings.create(input=normalized, model=m)
                emb = resp.data[0].embedding
                # Cache the first working model for subsequent calls.
                if m != self.embedding_model:
                    Logger.warning(
                        f"Embedding 模型自动回退: {self.embedding_model} -> {m}"
                    )
                    self.embedding_model = m
                return emb
            except BadRequestError as exc:
                # Common failure: model not found / no access
                last_exc = exc
                msg = str(exc)
                if ("model" in msg and "does not exist" in msg) or ("model_not_found" in msg):
                    continue
                raise
            except Exception as exc:
                # For OpenAI-compatible gateways, model lookup failures may surface
                # as other exception types. Keep trying unless it's the last model.
                last_exc = exc
                msg = str(exc)
                if ("model" in msg and "not found" in msg) or ("model_not_found" in msg):
                    continue
                # Unknown error: don't mask it by falling back.
                raise

        raise RuntimeError(
            "Embedding 模型不可用。已尝试: "
            + ", ".join(tried)
            + (f"；最后错误: {last_exc}" if last_exc else "")
        )

    def config_summary(self) -> dict:
        return {
            "model": self.model,
            "embedding_model": self.embedding_model,
            "api_base": str(self.client.base_url),
        }


# ================================================================
# 工具函数
# ================================================================

def extract_json_payload(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].lstrip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end >= start:
        cleaned = cleaned[start: end + 1]
    return cleaned


def read_text_with_fallback(path: str) -> str:
    last_error: Optional[Exception] = None
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def make_embedding_text(pd: PartDrawing) -> str:
    bi = pd.basic_info
    reqs = "；".join(pd.technical_requirements)
    return (
        f"零件名称：{bi.part_name}；图号：{bi.drawing_number}；"
        f"材料：{bi.material}；表面处理：{bi.surface_treatment}；技术要求：{reqs}"
    )


def build_kb_entry(
    conv_uuid: str, pd: PartDrawing, embedding: List[float]
) -> KnowledgeEntry:
    return KnowledgeEntry(
        conv_uuid=conv_uuid,
        part_name=pd.basic_info.part_name,
        drawing_number=pd.basic_info.drawing_number,
        material=pd.basic_info.material,
        surface_treatment=pd.basic_info.surface_treatment,
        length=pd.dimensions.length,
        width=pd.dimensions.width,
        height_thickness=pd.dimensions.height_thickness,
        technical_requirements=pd.technical_requirements,
        embedding=embedding,
    )


# ================================================================
# 后台解析任务（优化核心）
# ================================================================

def _parse_worker(job_id: str, raw_content: bytes) -> None:
    """
    后台线程执行图纸解析全流程：
    1. 压缩图像（减少 token）
    2. 转 base64（跳过 OSS 等待，直接传 LLM）
    3. OSS 上传在独立线程并发执行
    4. LLM 解析
    5. 知识库索引在独立线程执行
    前端通过轮询 /job/<job_id>/status 获取进度。
    """
    try:
        # Step 1: 压缩图像
        jobs.update(job_id, status="processing", progress="正在压缩图像...")
        compressed = compress_image(raw_content)

        # Step 2: 创建对话上下文
        conv_uuid = store.new()
        conv = store.get(conv_uuid)

        # Step 3: 将 OSS 上传放入独立线程（与 LLM 调用并发）
        def _upload_oss():
            try:
                url = oss.upload(conv_uuid, compressed)
                Logger.info(f"OSS 后台上传完成: {url}")
            except Exception as exc:
                Logger.warning(f"OSS 后台上传失败（不影响主流程）: {exc}")

        threading.Thread(target=_upload_oss, daemon=True).start()

        # Step 4: 用 base64 直接调用 LLM（无需等待 OSS）
        jobs.update(job_id, progress="AI 正在解析图纸，请稍候...")
        b64_url = image_to_base64_url(compressed)
        try:
            raw_reply = ai.get_response(
                _MAIN_PROMPT, conv, "main", image_url=b64_url
            )
        except BadRequestError as exc:
            jobs.update(job_id, status="failed", error=f"OpenAI 请求被拒绝: {exc}")
            return
        except Exception as exc:
            jobs.update(job_id, status="failed", error=f"LLM 调用失败: {exc}")
            return

        # Step 5: 解析 JSON
        jobs.update(job_id, progress="正在解析返回结果...")
        normalized = extract_json_payload(raw_reply)
        try:
            parsed = json.loads(normalized)
        except ValueError:
            jobs.update(
                job_id, status="failed",
                error=f"模型回复无法解析为 JSON，原始回复: {raw_reply[:200]}"
            )
            return

        if "error" in parsed:
            jobs.update(
                job_id, status="failed",
                error=f"图纸解析失败: {parsed['error']}"
            )
            return

        try:
            part_drawing = PartDrawing.from_dict(parsed)
        except Exception as exc:
            jobs.update(job_id, status="failed", error=f"数据结构化失败: {exc}")
            return

        # Step 6: 持久化
        jobs.update(job_id, progress="正在保存解析结果...")
        conv.set_information(
            DraftInformation(
                title=part_drawing.basic_info.part_name,
                draft_number=part_drawing.basic_info.drawing_number,
            )
        )
        store.uuid_to_title[conv_uuid] = part_drawing.basic_info.part_name
        store.save()

        os.makedirs("./drawing_data", exist_ok=True)
        with open(f"./drawing_data/{conv_uuid}.json", "w", encoding="utf-8") as f:
            f.write(part_drawing.to_json())

        # Step 7: 知识库索引放入独立线程
        def _index_kb():
            try:
                emb = ai.get_embedding(make_embedding_text(part_drawing))
                kb.upsert(build_kb_entry(conv_uuid, part_drawing, emb))
                Logger.info(f"知识库索引完成: {conv_uuid}")
            except Exception as exc:
                Logger.warning(f"知识库索引失败（不影响主流程）: {exc}")

        threading.Thread(target=_index_kb, daemon=True).start()

        jobs.update(job_id, status="done", conv_uuid=conv_uuid, progress="解析完成")
        Logger.info(f"任务完成: job_id={job_id}, conv_uuid={conv_uuid}")

    except Exception as exc:
        Logger.error(f"解析任务异常: job_id={job_id}, error={exc}")
        jobs.update(job_id, status="failed", error=str(exc))


# ================================================================
# 初始化
# ================================================================

config = BackendConfig()
config.load()

oss = OSSOperation()
oss.init_bucket(config)
try:
    oss.test_bucket()
except Exception:
    Logger.error("无法连接到 OSS 存储桶，程序无法启动!")
    exit(1)

store = ConvStore()
store.load()

ai = OpenAIImpl(config)
kb = DrawingKnowledgeBase()
jobs = JobStore()

app = Flask(__name__)


# ================================================================
# Flask 路由
# ================================================================

@app.route("/")
def r_index():
    return "DraftMind Backend is running."


@app.route("/health", methods=["GET"])
def r_health():
    return jsonify({"status": "ok", "openai": ai.config_summary()})


@app.route("/conversation/list", methods=["GET"])
def r_list():
    return jsonify(store.uuid_to_title)


@app.route("/conversation/new", methods=["POST"])
def r_new():
    """
    接收图纸图片，立即返回 job_id，后台异步执行解析。
    前端通过 GET /job/<job_id>/status 轮询进度。
    响应: { "job_id": "..." }
    """
    if "image" not in request.files:
        return jsonify({"error": "缺少 image 字段，请使用 multipart/form-data 上传"}), 400

    raw_content = request.files["image"].read()
    if not raw_content:
        return jsonify({"error": "上传的图片内容为空"}), 400

    job = jobs.create()
    threading.Thread(
        target=_parse_worker,
        args=(job.job_id, raw_content),
        daemon=True,
    ).start()

    Logger.info(f"已创建解析任务: job_id={job.job_id}")
    return jsonify({"job_id": job.job_id})


@app.route("/job/<job_id>/status", methods=["GET"])
def r_job_status(job_id: str):
    """
    查询解析任务进度。
    响应:
    {
        "job_id": "...",
        "status": "pending|processing|done|failed",
        "progress": "当前步骤描述",
        "conv_uuid": "...（仅 status=done 时有值）",
        "error": "...（仅 status=failed 时有值）"
    }
    """
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在或已过期"}), 404

    resp = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
    }
    if job.conv_uuid:
        resp["conv_uuid"] = job.conv_uuid
    if job.error:
        resp["error"] = job.error
    return jsonify(resp)


@app.route("/conversation/<conv_uuid>/context", methods=["GET"])
def r_context(conv_uuid: str):
    try:
        return jsonify(store.get(conv_uuid).ask_contents)
    except KeyError:
        return jsonify({"error": "对话不存在"}), 404


@app.route("/conversation/<conv_uuid>/info", methods=["GET"])
def r_info(conv_uuid: str):
    path = f"./drawing_data/{conv_uuid}.json"
    if not os.path.exists(path):
        return jsonify({"error": "图纸信息不存在，请先上传并解析图纸"}), 404
    return jsonify(PartDrawing.from_json(read_text_with_fallback(path)).to_dict())


@app.route("/conversation/<conv_uuid>/ask", methods=["POST"])
def r_ask(conv_uuid: str):
    try:
        conv = store.get(conv_uuid)
    except KeyError:
        return jsonify({"error": "对话不存在"}), 404

    body = request.get_json(force=True, silent=True) or {}
    question = str(body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question 字段不能为空"}), 400

    try:
        answer = ai.get_response(question, conv, "ask")
    except Exception as exc:
        Logger.error(f"追问 LLM 失败: {exc}")
        return jsonify({"error": f"LLM 调用失败: {exc}"}), 500

    store.save()
    return jsonify({"answer": answer})


@app.route("/conversation/<conv_uuid>/review", methods=["POST"])
def r_review_create(conv_uuid: str):
    path = f"./drawing_data/{conv_uuid}.json"
    if not os.path.exists(path):
        return jsonify({"error": "图纸信息不存在，请先上传并解析图纸"}), 404

    body = request.get_json(force=True, silent=True) or {}
    custom_rules = str(body.get("custom_rules") or "").strip()

    part_drawing = PartDrawing.from_json(read_text_with_fallback(path))
    custom_section = (
        f"\n## 企业自定义审核规则\n{custom_rules}\n" if custom_rules else ""
    )
    prompt = (
        _REVIEW_PROMPT_TEMPLATE
        .replace("{CUSTOM_RULES_SECTION}", custom_section)
        .replace("{DRAWING_JSON}", part_drawing.to_json())
    )

    try:
        resp = ai.client.chat.completions.create(
            model=ai.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=ai.max_tokens,
        )
        raw = resp.choices[0].message.content
    except Exception as exc:
        Logger.error(f"审图 LLM 失败: {exc}")
        return jsonify({"error": f"LLM 调用失败: {exc}"}), 500

    try:
        report = ReviewReport.from_dict(json.loads(extract_json_payload(raw)))
    except Exception as exc:
        return jsonify({"error": "审图报告解析失败", "raw": raw, "detail": str(exc)}), 500

    os.makedirs("./review_reports", exist_ok=True)
    with open(f"./review_reports/{conv_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    return jsonify(report.to_dict())


@app.route("/conversation/<conv_uuid>/review", methods=["GET"])
def r_review_get(conv_uuid: str):
    report_path = f"./review_reports/{conv_uuid}.json"
    if not os.path.exists(report_path):
        # 前端会在加载历史图纸时尝试拉取 review；没有报告属于正常状态。
        # 返回 200 + 空对象，避免前端将其视为错误并弹出提示。
        return jsonify({}), 200
    with open(report_path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/knowledge/similar/<conv_uuid>", methods=["GET"])
def r_similar(conv_uuid: str):
    path = f"./drawing_data/{conv_uuid}.json"
    if not os.path.exists(path):
        return jsonify({"error": "图纸信息不存在"}), 404

    top_k = int(request.args.get("top_k", 5))
    alpha = float(request.args.get("alpha", 0.7))
    beta = float(request.args.get("beta", 0.3))

    part_drawing = PartDrawing.from_json(read_text_with_fallback(path))
    try:
        emb = ai.get_embedding(make_embedding_text(part_drawing))
    except Exception as exc:
        return jsonify({"error": f"嵌入向量获取失败: {exc}"}), 500

    results = kb.search(
        build_kb_entry(conv_uuid, part_drawing, emb),
        top_k=top_k, alpha=alpha, beta=beta,
    )
    return jsonify([
        {
            "conv_uuid": e.conv_uuid,
            "part_name": e.part_name,
            "drawing_number": e.drawing_number,
            "material": e.material,
            "score": score,
        }
        for e, score in results
    ])


@app.route("/knowledge/search", methods=["POST"])
def r_knowledge_search():
    body = request.get_json(force=True, silent=True) or {}
    keyword = str(body.get("keyword") or "").strip()
    top_k = int(body.get("top_k") or 5)

    if not keyword:
        return jsonify({"error": "keyword 不能为空"}), 400

    try:
        emb = ai.get_embedding(keyword)
    except Exception as exc:
        return jsonify({"error": f"嵌入向量获取失败: {exc}"}), 500

    dummy = KnowledgeEntry(
        conv_uuid="__query__", part_name=keyword, drawing_number="",
        material="", surface_treatment="", length=0, width=0,
        height_thickness=0, embedding=emb,
    )
    results = kb.search(dummy, top_k=top_k, alpha=1.0, beta=0.0)
    return jsonify([
        {
            "conv_uuid": e.conv_uuid,
            "part_name": e.part_name,
            "drawing_number": e.drawing_number,
            "score": score,
        }
        for e, score in results
    ])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)