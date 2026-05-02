
import base64
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import pandas as pd
import pymupdf
import requests
import streamlit as st
from PIL import Image


# ================================================================
# 页面配置
# ================================================================

st.set_page_config(
    page_title="DraftMind 工程图纸智能管理",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ================================================================
# Session State 初始化
# ================================================================

_DEFAULTS: Dict[str, Any] = {
    "api_url": "http://127.0.0.1:5000",
    "conv_uuid": None,
    "drawing_data": None,
    "images": None,
    "annotations": {},
    "chat_history": [],
    "review_report": None,
    # 异步任务状态
    "_jobs": {},           # key: drawing_key, value: job_id
    "_job_images": {},     # key: drawing_key, value: images（用于解析中预览）
    # 批量上传管理
    "drawings": {},        # key: 图纸标识（文件名或conv_uuid），value: 图纸数据字典
    "current_drawing_key": None,  # 当前选中的图纸标识
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ================================================================
# 后端通信工具函数
# ================================================================

def base_url() -> str:
    return st.session_state["api_url"].rstrip("/")


def check_health(url: str) -> tuple[bool, str]:
    try:
        r = requests.get(url.rstrip("/") + "/", timeout=5)
        return (True, "后端已连接") if r.status_code == 200 else (False, f"HTTP {r.status_code}")
    except requests.exceptions.ConnectionError:
        return False, "无法连接后端"
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except Exception as exc:
        return False, str(exc)


def api_get(path: str, params: Optional[dict] = None, timeout: int = 15) -> Optional[dict]:
    try:
        r = requests.get(f"{base_url()}{path}", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        st.error(f"GET {path} 失败 (HTTP {r.status_code}): {r.text}")
    except Exception as exc:
        st.error(f"请求失败: {exc}")
    return None


def api_post(
    path: str,
    json_body: Optional[dict] = None,
    files: Optional[list] = None,
    data_body: Optional[dict] = None,
    timeout: int = 60,
) -> Optional[dict]:
    try:
        r = requests.post(
            f"{base_url()}{path}",
            json=json_body if files is None else None,
            files=files,
            data=data_body if files is not None else None,
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"POST {path} 失败 (HTTP {r.status_code}): {r.text}")
    except requests.exceptions.Timeout:
        st.error("请求超时，请稍后重试")
    except Exception as exc:
        st.error(f"请求失败: {exc}")
    return None


def get_job_status(job_id: str, timeout: int = 5) -> Optional[dict]:
    """查询后台解析任务状态（用于侧边栏/主界面展示）。"""
    if not job_id:
        return None
    return api_get(f"/job/{job_id}/status", timeout=timeout)


def load_drawing_to_top(drawing_key: str) -> bool:
    """将图纸库中的指定图纸数据加载到顶层 session state 变量（用于展示）"""
    drawings = st.session_state["drawings"]
    if drawing_key not in drawings:
        return False
    d = drawings[drawing_key]
    st.session_state["conv_uuid"] = d.get("conv_uuid")
    st.session_state["drawing_data"] = d.get("drawing_data")
    st.session_state["images"] = d.get("images")
    st.session_state["annotations"] = d.get("annotations", {})
    st.session_state["chat_history"] = d.get("chat_history", [])
    st.session_state["review_report"] = d.get("review_report")
    st.session_state["current_drawing_key"] = drawing_key
    return True


def save_current_to_drawing():
    """将当前顶层数据保存回当前图纸的仓库中"""
    key = st.session_state.get("current_drawing_key")
    if key and key in st.session_state["drawings"]:
        st.session_state["drawings"][key].update({
            "conv_uuid": st.session_state["conv_uuid"],
            "drawing_data": st.session_state["drawing_data"],
            "images": st.session_state["images"],
            "annotations": st.session_state["annotations"],
            "chat_history": st.session_state["chat_history"],
            "review_report": st.session_state["review_report"],
        })


def load_drawing_from_backend(conv_uuid: str) -> bool:
    """从后端加载图纸并存入图纸库，同时切换到该图纸"""
    data = api_get(f"/conversation/{conv_uuid}/info")
    if not data:
        return False
    report = api_get(f"/conversation/{conv_uuid}/review")
    # 以 conv_uuid 作为图纸标识
    drawing_key = conv_uuid
    st.session_state["drawings"][drawing_key] = {
        "conv_uuid": conv_uuid,
        "drawing_data": data,
        "images": None,          # 历史图纸通常不存储图像，避免内存过大
        "annotations": {},
        "chat_history": [],
        "review_report": report,
        "file_name": data.get("basic_info", {}).get("drawing_number", conv_uuid[:8]),
        "file_bytes": None,
        "file_type": None,
    }
    load_drawing_to_top(drawing_key)
    return True


# ================================================================
# 图像处理工具函数
# ================================================================

def pdf_to_images(file_bytes: bytes, dpi: int = 150) -> List[Image.Image]:
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        imgs = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        doc.close()
        return imgs
    except Exception as exc:
        st.error(f"PDF 解析失败: {exc}")
        return []


def pil_to_jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def preprocess_uploaded_file(file_bytes: bytes, file_type: str) -> Optional[List[Image.Image]]:
    """预处理上传的文件，返回图像列表(PDF多页,图片单页)"""
    if "pdf" in file_type:
        images = pdf_to_images(file_bytes)
    else:
        try:
            images = [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
        except Exception as exc:
            st.error(f"图片加载失败: {exc}")
            return None
    return images if images else None


# ================================================================
# 侧边栏
# ================================================================

with st.sidebar:
    st.title("系统设置")
    # ---------- 固定项目标识（自动适配图片格式） ----------
    st.subheader(" 项目标识")

    logo_base64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAcFBQYFBAcGBgYIBwcICxILCwoKCxYPEA0SGhYbGhkWGRgcICgiHB4mHhgZIzAkJiorLS4tGyIyNTEsNSgsLSz/2wBDAQcICAsJCxULCxUsHRkdLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCz/wAARCAL+AvADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD6RooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiuD+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5rEO9WR2017otFFFc5YUUUUwCiiimISsbxD4es/EmkS6ffR7o5R94dVPYj3FbNGKItp3E0fIN/4K1eDxHNpdtazTkSGONiuAfQ88Cu+8N/Ai8lkEviC6WKLr5Nvgs31J4Fe8mztzL5n2eLf13bBn86nruljqklZaGfs0znPDngnQvDFv5WnWEaE9ZHG5z9WPNdCqKvRQKfRXHKTk7s0UUhMUuKKKkYUUUUDCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKhms7edg0sMbsOhZc4qaigBFUKAAMAUtFFABRRRQAUUUUAFFFFABRRRQB49+0FpH2jQNO1NF+e1lZGI/uNj+oFfP8AX2nqul22r2ElneRLLDIMFWGa8in+AVtJcySJfbEY5C+gr1MJiY048sjmqQcndHhNFe5/8KAj/wCgg35Uf8KAj/6CDV2/XKXcj2UjwyivoLSfgTpMEzHUpZLmMjgbiv6g1s6V8GPCul6it6kNxcMh3Is8m9FPbjHOPesZ46GyKVJnQfD/AEttH8C6VZMu10t1Lj0ZvmI/WulpiqFX5Rin140pc0nI6YqysLRRRUDCiiimAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAH/9kNiDYKAAAAACpERm3wanord/iohqpMvEI="  # 粘贴您的完整字符串
    st.markdown(
        f'<div style="text-align: center;"><img src="{logo_base64}" width="120"></div>',
        unsafe_allow_html=True,
    )
    st.caption("DraftMind 智能图纸管理")
    st.divider()
    st.title("系统设置")

    new_url = st.text_input(
        "后端 API 地址",
        value=st.session_state["api_url"],
        help="Flask 后端地址，例如 http://127.0.0.1:5000",
        key="_api_url_input",
    )
    if new_url != st.session_state["api_url"]:
        st.session_state["api_url"] = new_url

    healthy, health_msg = check_health(st.session_state["api_url"])
    if healthy:
        st.success(health_msg)
    else:
        st.error(health_msg)

    st.divider()
    st.subheader("图纸库")

    # 图纸选择器（整合上传的图纸和历史图纸）
    drawing_keys = list(st.session_state["drawings"].keys())
    if drawing_keys:
        # 构建显示名称
        display_names = []
        for key in drawing_keys:
            d = st.session_state["drawings"][key]
            name = d.get("file_name") or d.get("drawing_data", {}).get("basic_info", {}).get("part_name") or key[:8]
            # 追加解析进度标识（如果该图纸正在解析）
            job_id = (st.session_state.get("_jobs") or {}).get(key)
            if job_id:
                status_data = get_job_status(job_id, timeout=2) or {}
                s = status_data.get("status", "pending")
                pct = status_data.get("progress_pct", None)
                msg = status_data.get("progress", "")
                if s in ("pending", "processing"):
                    try:
                        pct_i = int(float(pct) * 100) if pct is not None else None
                    except Exception:
                        pct_i = None
                    tag = f"解析中 {pct_i}%" if pct_i is not None else "解析中"
                    if msg:
                        tag = f"{tag} · {msg}"
                    display_names.append(f"{name} [{key[:8]}]  ({tag})")
                elif s == "failed":
                    display_names.append(f"{name} [{key[:8]}]  (解析失败)")
                else:
                    display_names.append(f"{name} [{key[:8]}]")
            else:
                display_names.append(f"{name} [{key[:8]}]")
        default_idx = 0
        if st.session_state["current_drawing_key"] in drawing_keys:
            default_idx = drawing_keys.index(st.session_state["current_drawing_key"])
        selected_display = st.selectbox(
            "选择图纸",
            display_names,
            index=default_idx,
            key="_drawing_selector",
        )
        selected_key = drawing_keys[display_names.index(selected_display)]
        if selected_key != st.session_state["current_drawing_key"]:
            # 保存当前图纸数据，再切换
            save_current_to_drawing()
            load_drawing_to_top(selected_key)
            # 如果该图纸正在解析中，提升优先级（优先解析正在观看的图纸）
            job_id = st.session_state.get("_jobs", {}).get(selected_key)
            if job_id:
                api_post(f"/job/{job_id}/prioritize", json_body={"priority": 0}, timeout=5)
            st.rerun()
    else:
        st.info("暂无图纸，请上传或从历史加载")
        st.session_state["current_drawing_key"] = None

    st.divider()
    st.subheader("历史图纸")

    if healthy:
        conv_list: Dict[str, str] = api_get("/conversation/list") or {}
        if conv_list:
            options = {
                f"{title or '（无标题）'}  [{uid[:8]}]": uid
                for uid, title in conv_list.items()
            }
            selected = st.selectbox(
                "选择历史图纸",
                ["-- 请选择 --"] + list(options.keys()),
                key="_hist_select",
            )
            if selected != "-- 请选择 --":
                if st.button("加载此图纸", use_container_width=True):
                    uid = options[selected]
                    with st.spinner("加载中..."):
                        if load_drawing_from_backend(uid):
                            st.success("加载成功")
                            st.rerun()
        else:
            st.info("暂无历史图纸")
    else:
        st.warning("后端未连接，无法获取历史图纸")

    st.divider()
    st.caption("DraftMind v2.0")


# ================================================================
# 主界面标题
# ================================================================

st.title("DraftMind 工程图纸智能管理系统")
st.caption("图纸解析 / 智能审图 / 相似推荐 / 图纸问答")
st.divider()


# ================================================================
# 异步任务轮询（优化核心）
# ================================================================

# 注意：轮询期间可能会切换图纸，但任务完成后会保存到正确的图纸
jobs_map: Dict[str, str] = st.session_state.get("_jobs") or {}
# 让“解析进度”在任何页面都可见（即使当前选中的是已解析图纸）
with st.expander(
    "后台解析任务进度",
    expanded=(st.session_state["drawing_data"] is None and bool(jobs_map)),
):
    if not jobs_map:
        st.info("暂无后台解析任务。点击下方「解析当前图纸」后，这里会显示进度条并自动刷新。")
    else:
        auto_refresh = st.checkbox(
            "自动刷新进度（3 秒）",
            value=True,
            key="_auto_refresh_jobs",
        )

        any_running = False
        # 优先展示当前正在观看的图纸
        current_key = st.session_state.get("current_drawing_key")
        ordered_keys = []
        if current_key and current_key in jobs_map:
            ordered_keys.append(current_key)
        ordered_keys.extend([k for k in jobs_map.keys() if k not in ordered_keys])

        for target_key in ordered_keys:
            job_id: str = jobs_map[target_key]
            status_data = get_job_status(job_id, timeout=10)

            if status_data is None:
                st.error(f"无法获取任务状态：{job_id}（请检查后端）")
                continue

            status = status_data.get("status", "pending")
            progress_msg = status_data.get("progress", "处理中...")
            progress_pct = status_data.get("progress_pct", None)

            # 进度步骤映射（后端若未给 progress_pct 时兜底）
            step_map = {
                "等待处理...": 0.05,
                "正在压缩图像...": 0.15,
                "AI 正在解析图纸，请稍候...": 0.55,
                "正在解析返回结果...": 0.80,
                "正在保存解析结果...": 0.92,
                "解析完成": 1.00,
            }
            try:
                progress_val = float(progress_pct) if progress_pct is not None else None
            except Exception:
                progress_val = None
            if progress_val is None:
                progress_val = step_map.get(progress_msg, 0.3)
            progress_val = max(0.0, min(1.0, float(progress_val)))

            title = st.session_state["drawings"].get(target_key, {}).get("file_name") or str(target_key)
            st.markdown(f"**{title}**  \n任务 ID：`{job_id}`")

            if status == "done":
                conv_uuid = status_data.get("conv_uuid")
                drawing_data = api_get(f"/conversation/{conv_uuid}/info") if conv_uuid else None
                if drawing_data and target_key in st.session_state["drawings"]:
                    st.session_state["drawings"][target_key].update({
                        "conv_uuid": conv_uuid,
                        "drawing_data": drawing_data,
                        "images": st.session_state.get("_job_images", {}).pop(target_key, None),
                        "annotations": st.session_state["drawings"][target_key].get("annotations", {}) or {},
                        "chat_history": st.session_state["drawings"][target_key].get("chat_history", []) or [],
                        "review_report": st.session_state["drawings"][target_key].get("review_report"),
                    })
                    if st.session_state["current_drawing_key"] == target_key:
                        load_drawing_to_top(target_key)
                st.session_state["_jobs"].pop(target_key, None)
                st.success("解析完成")

            elif status == "failed":
                error_msg = status_data.get("error", "未知错误")
                st.error(f"解析失败：{error_msg}")
                st.session_state["_jobs"].pop(target_key, None)
                st.session_state.get("_job_images", {}).pop(target_key, None)

            else:
                any_running = True
                st.progress(progress_val, text=f"{progress_msg}（{int(progress_val * 100)}%）")

                # 仅对当前正在观看的图纸展示预览（避免占用太大）
                if target_key == current_key:
                    job_images = st.session_state.get("_job_images", {}).get(target_key)
                    if job_images:
                        with st.expander("已上传图纸预览（当前图纸）", expanded=False):
                            for idx, img in enumerate(job_images):
                                st.image(img, caption=f"第 {idx + 1} 页", use_container_width=True)

            st.divider()

        # 统一自动刷新：仅当存在进行中的任务时触发
        if (st.session_state.get("_auto_refresh_jobs") is True) and any_running:
            time.sleep(3)
            st.rerun()


# ================================================================
# 上传与解析区域（无图纸且无进行中任务时显示）
# ================================================================

if st.session_state["drawing_data"] is None and not (st.session_state.get("_jobs") or {}):
    st.subheader("批量上传图纸")
    uploaded_files = st.file_uploader(
        "支持 PDF 及常见图片格式（JPG / PNG），可多选",
        type=["pdf", "jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="_batch_uploader",
    )

    if uploaded_files:
        first_file_name = None
        new_file_added = False
        for uploaded in uploaded_files:
            file_name = uploaded.name
            if first_file_name is None:
                first_file_name = file_name
            if file_name not in st.session_state["drawings"]:
                # 预处理图像...
                images = preprocess_uploaded_file(uploaded.getvalue(), uploaded.type)
                if images is None:
                    continue
                st.session_state["drawings"][file_name] = {
                    "file_name": file_name,
                    "file_bytes": uploaded.getvalue(),
                    "file_type": uploaded.type,
                    "images": images,
                    "drawing_data": None,
                    "conv_uuid": None,
                    "annotations": {},
                    "chat_history": [],
                    "review_report": None,
                }
                new_file_added = True
        # 强制选中第一个上传的文件
        if first_file_name and (st.session_state.get("current_drawing_key") is None):
            load_drawing_to_top(first_file_name)
            st.session_state["drawings"][first_file_name]["drawing_data"] = None

        if new_file_added:
            st.success(f"已添加 {len(uploaded_files)} 个图纸，当前选中：{first_file_name}")
            # 只有在“新增文件”时才触发 rerun，避免按钮点击被无限 rerun 吞掉
            st.rerun()
        else:
            st.info("文件已在图纸库中，可直接点击下方「解析当前图纸」。")

    # 如果有图纸但当前没有选中，显示提示
    if st.session_state["drawings"] and st.session_state["current_drawing_key"] is None:
        first_key = list(st.session_state["drawings"].keys())[0]
        
        load_drawing_to_top(first_key)
        st.rerun()

    # 解析按钮（仅当有当前图纸且未解析时显示）
    current_key = st.session_state.get("current_drawing_key")
    # ---- 调试信息 ----
    # 调试信息（测试后可删除）
    # ------------------
    def submit_parse_job(drawing_key: str, priority: int) -> bool:
        d = st.session_state["drawings"].get(drawing_key) or {}
        images = d.get("images")
        if not images:
            images = preprocess_uploaded_file(d.get("file_bytes") or b"", d.get("file_type") or "")
            if not images:
                return False
            d["images"] = images

        # 构建多页文件上传
        def _encode_one(args):
            idx, img = args
            return idx, pil_to_jpeg_bytes(img)

        files_list = []
        with ThreadPoolExecutor(max_workers=min(8, len(images))) as ex:
            encoded = list(ex.map(_encode_one, list(enumerate(images))))
        for idx, img_bytes in sorted(encoded, key=lambda x: x[0]):
            files_list.append(("image", (f"page_{idx+1}.jpg", img_bytes, "image/jpeg")))

        result = api_post(
            "/conversation/new",
            files=files_list,
            data_body={"priority": str(int(priority))},
            timeout=60,
        )
        if result and "job_id" in result:
            st.session_state["_jobs"][drawing_key] = result["job_id"]
            st.session_state["_job_images"][drawing_key] = images
            return True
        return False

    if current_key and st.session_state["drawings"][current_key].get("drawing_data") is None:
        current = st.session_state["drawings"][current_key]
        st.info(f"当前图纸：{current.get('file_name', current_key)}")
        col_a, col_b = st.columns([1, 2])
        with col_a:
            if st.button("解析当前图纸", type="primary"):
                with st.spinner("正在提交解析任务（压缩/上传图纸）..."):
                    ok = submit_parse_job(current_key, priority=0)
                if ok:
                    st.rerun()
                else:
                    st.error("提交解析任务失败：未能生成任务 ID（请检查后端是否在线、或查看后端控制台日志）。")
        with col_b:
            if st.button("并行解析全部未解析图纸"):
                pending_keys = [
                    k for k, d in st.session_state["drawings"].items()
                    if d.get("drawing_data") is None and k not in st.session_state["_jobs"]
                ]
                # 优先提交正在观看的图纸（priority=0），其它默认 priority=10
                if current_key in pending_keys:
                    submit_parse_job(current_key, priority=0)
                    pending_keys = [k for k in pending_keys if k != current_key]
                # Streamlit 的 st.session_state / st.error 不能在 worker 线程中安全访问；
                # 这里改为主线程顺序提交，避免 session_state 在子线程里缺失导致 KeyError。
                for k in pending_keys:
                    submit_parse_job(k, priority=10)
                st.rerun()

    if not healthy:
        st.warning("后端未连接，请先确认 Flask 服务已启动。")


# ================================================================
# 结果展示区域（图纸已加载时显示）
# ================================================================

if st.session_state["drawing_data"] is not None:
    drawing_data: Dict = st.session_state["drawing_data"]
    conv_uuid: str = st.session_state["conv_uuid"]
    images: Optional[List] = st.session_state["images"]

    col_name, col_id, col_btn = st.columns([4, 3, 1])
    with col_name:
        part_name = drawing_data.get("basic_info", {}).get("part_name") or "未知零件"
        st.subheader(part_name)
    with col_id:
        st.caption(f"对话 ID：{conv_uuid}")
    with col_btn:
        if st.button("换图纸"):
            # 保存当前图纸数据
            save_current_to_drawing()
            # 切换到下一个未解析或任意图纸
            drawings = st.session_state["drawings"]
            keys = list(drawings.keys())
            if keys:
                current_idx = keys.index(st.session_state["current_drawing_key"]) if st.session_state["current_drawing_key"] in keys else 0
                next_idx = (current_idx + 1) % len(keys)
                load_drawing_to_top(keys[next_idx])
            else:
                # 清空顶层
                for k in ["drawing_data", "conv_uuid", "images", "annotations", "chat_history", "review_report"]:
                    st.session_state[k] = None
                st.session_state["current_drawing_key"] = None
            st.rerun()

    tab_info, tab_review, tab_similar, tab_chat = st.tabs([
        "图纸信息", "智能审图", "相似推荐", "图纸问答",
    ])

    # ==============================================================
    # Tab 1：图纸信息
    # ==============================================================
    with tab_info:
        basic = drawing_data.get("basic_info", {})
        dims  = drawing_data.get("dimensions", {})
        tols  = drawing_data.get("tolerances", [])
        geos  = drawing_data.get("geometric_tolerances", [])
        rough = drawing_data.get("surface_roughness", [])
        reqs  = drawing_data.get("technical_requirements", [])

        st.markdown("## 基本信息")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("零件名称", basic.get("part_name") or "—")
        c2.metric("图号",     basic.get("drawing_number") or "—")
        c3.metric("材料",     basic.get("material") or "—")
        c4.metric("表面处理", basic.get("surface_treatment") or "—")

        st.markdown("---")
        st.markdown("## 主要尺寸")
        c1, c2, c3 = st.columns(3)
        c1.metric("长度",      f"{dims.get('length', 0)} mm")
        c2.metric("宽度",      f"{dims.get('width', 0)} mm")
        c3.metric("高度/厚度", f"{dims.get('height_thickness', 0)} mm")
        if dims.get("other_dimensions"):
            st.caption(f"备注：{dims['other_dimensions']}")

        if tols:
            with st.expander(f"尺寸公差（{len(tols)} 项）"):
                st.dataframe(pd.DataFrame(tols), use_container_width=True)
        if geos:
            with st.expander(f"形位公差（{len(geos)} 项）"):
                st.dataframe(pd.DataFrame(geos), use_container_width=True)
        if rough:
            with st.expander(f"表面粗糙度（{len(rough)} 项）"):
                st.dataframe(pd.DataFrame(rough), use_container_width=True)
        if reqs:
            with st.expander(f"技术要求（{len(reqs)} 项）", expanded=True):
                for i, r in enumerate(reqs, 1):
                    st.markdown(f"**{i}.** {r}")

        with st.expander("原始 JSON", expanded=False):
            st.json(drawing_data)

        st.divider()
        if images:
            st.markdown("## 图纸页面浏览与批注")
            for idx, img in enumerate(images):
                pn = idx + 1
                with st.expander(f"第 {pn} 页", expanded=(pn == 1)):
                    st.image(img, caption=f"第 {pn} 页预览", use_container_width=True)
                    cur = st.session_state["annotations"].get(pn, "")
                    new = st.text_area(
                        f"第 {pn} 页批注",
                        value=cur,
                        key=f"_ann_{pn}",
                        height=90,
                        placeholder="在此输入对本页图纸的批注...",
                    )
                    if new != cur:
                        st.session_state["annotations"][pn] = new
                        save_current_to_drawing()  # 实时保存

            ann = st.session_state["annotations"]
            if any(v.strip() for v in ann.values()):
                col1, col2 = st.columns([1, 5])
                with col1:
                    st.download_button(
                        "导出批注 (JSON)",
                        data=json.dumps(
                            {str(k): v for k, v in ann.items()},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        file_name=f"{conv_uuid[:8]}_annotations.json",
                        mime="application/json",
                    )
                with col2:
                    if st.button("清除所有批注"):
                        st.session_state["annotations"] = {}
                        save_current_to_drawing()
                        st.rerun()
        else:
            st.info("从历史记录加载的图纸不支持图像预览，重新上传该图纸可查看原图及批注。")

    # ==============================================================
    # Tab 2：智能审图
    # ==============================================================
    with tab_review:
        st.markdown("## AI 智能审图")
        st.caption("依据 GB/T 4458 系列标准、《机械设计手册》进行合规性检查，可叠加企业自定义规则。")

        custom_rules = st.text_area(
            "企业自定义审核规则（可选）",
            placeholder=(
                "示例：\n"
                "- 禁止使用 Q235 材料制作受力结构件\n"
                "- 所有配合面表面粗糙度不得高于 Ra 1.6\n"
                "- 板材厚度不得低于 3 mm"
            ),
            height=110,
            key="_custom_rules",
        )

        col1, col2 = st.columns([1, 4])
        with col1:
            run_review = st.button("开始审图", type="primary", use_container_width=True)
        with col2:
            if st.session_state["review_report"]:
                st.info("已有审图报告，点击「开始审图」可重新审查。")

        if run_review:
            with st.spinner("AI 正在审查图纸，约 15~30 秒..."):
                result = api_post(
                    f"/conversation/{conv_uuid}/review",
                    json_body={"custom_rules": custom_rules},
                    timeout=90,
                )
            if result:
                st.session_state["review_report"] = result
                save_current_to_drawing()
                st.rerun()

        report = st.session_state.get("review_report")
        if report:
            passed  = report.get("overall_pass", False)
            risk    = report.get("risk_level", "—")
            issues  = report.get("issues", [])
            summary = report.get("summary", "")

            risk_label  = {"LOW": "[低风险]", "MEDIUM": "[中风险]", "HIGH": "[高风险]"}.get(risk, risk)
            result_label = "通过" if passed else "未通过"
            errors   = sum(1 for i in issues if i.get("severity") == "ERROR")
            warnings = sum(1 for i in issues if i.get("severity") == "WARNING")

            c1, c2, c3 = st.columns(3)
            c1.metric("审图结论", result_label)
            c2.metric("风险等级", risk_label)
            c3.metric("问题统计", f"ERROR: {errors}  WARNING: {warnings}")
            st.info(f"综合评价：{summary}")

            if issues:
                st.markdown("---")
                st.markdown("## 问题详情")
                sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
                sev_label = {"ERROR": "[ERROR]", "WARNING": "[WARNING]", "INFO": "[INFO]"}
                for iss in sorted(
                    issues,
                    key=lambda x: sev_order.get(x.get("severity", "INFO"), 9),
                ):
                    sev  = iss.get("severity", "INFO")
                    desc = iss.get("description", "")
                    title = (
                        f"{sev_label.get(sev, sev)} "
                        f"{iss.get('category', '—')} - "
                        f"{desc[:50]}{'...' if len(desc) > 50 else ''}"
                    )
                    with st.expander(title):
                        st.markdown(f"**问题描述**：{desc}")
                        st.markdown(f"**修改建议**：{iss.get('suggestion', '—')}")
                        if iss.get("reference"):
                            st.caption(f"参考标准：{iss['reference']}")
            else:
                st.success("未发现任何合规性问题。")

            st.download_button(
                "导出审图报告 (JSON)",
                data=json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"{conv_uuid[:8]}_review.json",
                mime="application/json",
            )

    # ==============================================================
    # Tab 3：相似推荐 & 知识库搜索
    # ==============================================================
    with tab_similar:
        st.markdown("## 相似图纸推荐")
        st.caption(
            "综合相似度 = alpha x 语义相似度 + beta x 尺寸相似度，"
            "基于 OpenAI Embeddings 与欧氏距离融合计算。"
        )

        col1, col2, col3 = st.columns(3)
        top_k = col1.slider("推荐数量", 1, 10, 5, key="_sim_topk")
        alpha = col2.slider(
            "语义权重 alpha", 0.0, 1.0, 0.7, step=0.1, key="_sim_alpha",
            help="越高越注重名称、材料等文本特征",
        )
        beta = col3.slider(
            "尺寸权重 beta", 0.0, 1.0, 0.3, step=0.1, key="_sim_beta",
            help="越高越注重长宽高数值特征",
        )

        if st.button("查找相似图纸", type="primary", key="_btn_similar"):
            with st.spinner("正在检索知识库..."):
                sim_results = api_get(
                    f"/knowledge/similar/{conv_uuid}",
                    params={"top_k": top_k, "alpha": alpha, "beta": beta},
                    timeout=30,
                )
            if sim_results is not None:
                if sim_results:
                    df = pd.DataFrame(sim_results)[
                        ["part_name", "drawing_number", "material", "score"]
                    ]
                    df.columns = ["零件名称", "图号", "材料", "相似度"]
                    df["相似度"] = df["相似度"].map(lambda x: f"{float(x):.2%}")
                    st.dataframe(df, use_container_width=True)

                    st.markdown("---")
                    st.caption("点击以下按钮可加载对应图纸：")
                    for row in sim_results:
                        btn_label = (
                            f"{row['part_name']}  "
                            f"[{row['conv_uuid'][:8]}]  "
                            f"相似度 {float(row['score']):.2%}"
                        )
                        if st.button(btn_label, key=f"_load_{row['conv_uuid']}"):
                            with st.spinner("加载中..."):
                                if load_drawing_from_backend(row["conv_uuid"]):
                                    st.rerun()
                else:
                    st.info("知识库中暂无其他图纸，上传更多图纸后才能推荐。")

        st.divider()
        st.markdown("#### 关键词语义搜索")

        kw_col1, kw_col2 = st.columns([5, 1])
        with kw_col1:
            keyword = st.text_input(
                "关键词",
                placeholder="如：铝合金支架、45钢轴、冲压件",
                key="_kw_input",
                label_visibility="collapsed",
            )
        with kw_col2:
            kw_topk = st.number_input(
                "数量",
                min_value=1,
                max_value=20,
                value=5,
                key="_kw_topk",
                label_visibility="collapsed",
            )

        if st.button("搜索", key="_kw_btn"):
            if not keyword.strip():
                st.warning("请输入关键词后再搜索。")
            else:
                with st.spinner("语义检索中..."):
                    kw_results = api_post(
                        "/knowledge/search",
                        json_body={"keyword": keyword.strip(), "top_k": int(kw_topk)},
                        timeout=30,
                    )
                if kw_results is not None:
                    if kw_results:
                        df_kw = pd.DataFrame(kw_results)[
                            ["part_name", "drawing_number", "score"]
                        ]
                        df_kw.columns = ["零件名称", "图号", "相似度"]
                        df_kw["相似度"] = df_kw["相似度"].map(
                            lambda x: f"{float(x):.2%}"
                        )
                        st.dataframe(df_kw, use_container_width=True)

                        st.markdown("---")
                        st.caption("点击以下按钮可加载对应图纸：")
                        for row in kw_results:
                            btn_label = (
                                f"{row['part_name']}  "
                                f"[{row['conv_uuid'][:8]}]  "
                                f"相似度 {float(row['score']):.2%}"
                            )
                            if st.button(btn_label, key=f"_kw_load_{row['conv_uuid']}"):
                                with st.spinner("加载中..."):
                                    if load_drawing_from_backend(row["conv_uuid"]):
                                        st.rerun()
                    else:
                        st.info("未找到相关图纸，请尝试其他关键词。")

    # ==============================================================
    # Tab 4：图纸问答
    # ==============================================================
    with tab_chat:
        st.markdown("# 图纸问答")
        st.caption("基于当前图纸的解析上下文与原始图像，向 AI 提问任何与图纸相关的问题。")

        chat_history: List[Dict] = st.session_state["chat_history"]
        if chat_history:
            for entry in chat_history:
                with st.chat_message("user"):
                    st.markdown(entry["question"])
                with st.chat_message("assistant"):
                    st.markdown(entry["answer"])
        else:
            st.info(
                "暂无对话记录。在下方输入框中提问,AI 将结合图纸信息回答。\n\n"
                "示例问题：\n"
                "- 这个零件的配合公差是多少？\n"
                "- 材料选用是否合理？\n"
                "- 技术要求中有哪些热处理要求？"
            )

        question = st.chat_input(
            "请输入您的问题，例如：这个零件的主要配合尺寸是什么？",
            key="_chat_input",
        )

        if question:
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                with st.spinner("AI 思考中..."):
                    result = api_post(
                        f"/conversation/{conv_uuid}/ask",
                        json_body={"question": question},
                        timeout=60,
                    )
                if result and "answer" in result:
                    answer = result["answer"]
                    st.markdown(answer)
                    st.session_state["chat_history"].append(
                        {"question": question, "answer": answer}
                    )
                    save_current_to_drawing()
                else:
                    st.error("AI 未返回有效回答，请稍后重试。")

        if chat_history:
            st.divider()
            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("清除对话", key="_clear_chat"):
                    st.session_state["chat_history"] = []
                    save_current_to_drawing()
                    st.rerun()
            with col2:
                chat_export = [
                    {
                        "round": i + 1,
                        "question": e["question"],
                        "answer": e["answer"],
                    }
                    for i, e in enumerate(chat_history)
                ]
                st.download_button(
                    "导出对话记录 (JSON)",
                    data=json.dumps(chat_export, ensure_ascii=False, indent=2),
                    file_name=f"{conv_uuid[:8]}_chat.json",
                    mime="application/json",
                    key="_export_chat",
                )


# ================================================================
# 底部说明
# ================================================================

st.divider()
st.caption(
    "使用说明：上传图纸后点击「解析当前图纸」，任务将在后台运行，页面自动刷新显示进度。"
    "解析完成后可在「智能审图」Tab 进行合规性检查，"
    "在「相似推荐」Tab 查找历史相似图纸，"
    "在「图纸问答」Tab 与 AI 自由对话。"
)
