#添加图纸上传页面
import streamlit as st
import requests
from PIL import Image
import io
import pymupdf
import json
import pandas as pd
from typing import List, Optional, Dict

# ============================ 页面配置 ============================
st.set_page_config(page_title="工程数字图纸智能管理系统", layout="centered")
col1, col2, col3 = st.columns([1, 15, 1])
with col2:
    st.title("工程数字图纸智能管理系统")
st.markdown("基于大模型的图纸解析与批注")

# ================== 后端 API 地址配置 ==================
if "api_url" not in st.session_state:
    st.session_state["api_url"] = "http://127.0.0.1:5000"  # Flask 默认地址

def update_api_url():
    st.session_state["api_url"] = st.session_state["api_url_input"]

st.sidebar.text_input(
    "后端 API 基础地址",
    value=st.session_state["api_url"],
    key="api_url_input",
    on_change=update_api_url,
    help="输入 Flask 后端地址，例如 http://127.0.0.1:5000"
)
st.sidebar.markdown("💡 确保 Flask 后端已启动，接口为 `/conversation/new` 等")

# ========================= 文件上传与初始化 =========================
uploaded_file = st.file_uploader(
    "上传图纸", 
    type=["pdf", "jpg", "jpeg", "png"], 
    help="支持 PDF 及常见图片格式"
)

if uploaded_file is not None:
    st.success(f"已上传: {uploaded_file.name}")
    st.session_state['file_bytes'] = uploaded_file.getvalue()
    st.session_state['file_name'] = uploaded_file.name
    st.session_state['file_type'] = uploaded_file.type
else:
    for key in ['file_bytes', 'file_name', 'file_type', 'drawing_data', 'images']:
        if key in st.session_state:
            del st.session_state[key]

# ========================= 图像预处理（多页支持） =========================
def pdf_to_images(file_bytes: bytes, dpi: int = 150) -> List[Image.Image]:
    """将 PDF 文件字节流转换为 PIL Image 列表（每页一张）"""
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        images = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
        doc.close()
        return images
    except Exception as e:
        st.error(f"PDF 解析失败: {e}")
        return []

def image_to_base64(img: Image.Image, format: str = "JPEG") -> str:
    """将 PIL Image 编码为 Base64 字符串（备用）"""
    buffered = io.BytesIO()
    img.save(buffered, format=format)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

# ========================= 调用 Flask 后端的函数 =========================
def upload_and_parse_first_page(images: List[Image.Image], base_url: str) -> Optional[Dict]:
    """
    将图像列表的第一页上传到 Flask 后端 /conversation/new，
    获取 conv_uuid，再调用 /conversation/<uuid>/info 获取 PartDrawing 数据。
    返回完整的图纸结构化字典，失败返回 None。
    """
    if not images:
        st.error("没有可解析的图像")
        return None

    first_img = images[0]
    # 将 PIL Image 转为 JPEG 字节流
    img_bytes = io.BytesIO()
    first_img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {"image": ("page_1.jpg", img_bytes, "image/jpeg")}
    try:
        # 1. 上传图片，创建对话
        resp = requests.post(f"{base_url}/conversation/new", files=files, timeout=60)
        if resp.status_code != 200:
            st.error(f"上传失败 (HTTP {resp.status_code}): {resp.text}")
            return None

        conv_uuid = resp.json().get("conv_uuid")
        if not conv_uuid:
            st.error("后端未返回 conv_uuid")
            return None

        # 2. 获取图纸结构化信息
        info_resp = requests.get(f"{base_url}/conversation/{conv_uuid}/info", timeout=30)
        if info_resp.status_code != 200:
            st.error(f"获取图纸信息失败 (HTTP {info_resp.status_code}): {info_resp.text}")
            return None

        return info_resp.json()

    except requests.exceptions.ConnectionError:
        st.error("无法连接到后端，请检查地址和服务状态")
    except requests.exceptions.Timeout:
        st.error("请求超时，请稍后重试")
    except Exception as e:
        st.error(f"未知错误: {e}")

    return None

# ========================= 批注功能 =========================
def export_annotations():
    """导出所有批注为 JSON 文件"""
    if "annotations" in st.session_state and st.session_state["annotations"]:
        json_str = json.dumps(st.session_state["annotations"], ensure_ascii=False, indent=2)
        st.download_button(
            label="⬇️ 导出批注 (JSON)",
            data=json_str,
            file_name="annotations.json",
            mime="application/json"
        )
    else:
        st.info("暂无批注内容可导出")

# ========================= 主解析流程 =========================
if st.button("🔍 解析图纸", type="primary", disabled=('file_bytes' not in st.session_state)):
    base_url = st.session_state["api_url"].rstrip("/")
    file_type = st.session_state['file_type']
    file_bytes = st.session_state['file_bytes']

    with st.status("正在处理图纸...", expanded=True) as status:
        # 1. 获取图像列表（PDF多页，图片单页）
        images: List[Image.Image] = []
        if "pdf" in file_type:
            st.write("检测到 PDF 文件，正在转换为图像...")
            images = pdf_to_images(file_bytes)
            if not images:
                status.update(label="PDF 转换失败", state="error")
                st.stop()
            st.write(f"共 {len(images)} 页")
        else:  # 图片格式
            try:
                img = Image.open(io.BytesIO(file_bytes))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                images = [img]
                st.write("图片加载成功")
            except Exception as e:
                st.error(f"图片加载失败: {e}")
                status.update(label="图片处理失败", state="error")
                st.stop()

        # 2. 调用后端解析第一页
        status.update(label="正在调用 AI 解析第一页图纸...")
        drawing_data = upload_and_parse_first_page(images, base_url)

        if drawing_data:
            # 保存解析结果和所有图像供后续展示
            st.session_state['drawing_data'] = drawing_data
            st.session_state['images'] = images
            status.update(label="解析完成！", state="complete")
        else:
            status.update(label="解析失败，请查看上方错误信息", state="error")

# ========================= 展示解析结果与批注 =========================
if 'drawing_data' in st.session_state and 'images' in st.session_state:
    drawing_data = st.session_state['drawing_data']
    images = st.session_state['images']

    st.subheader("📋 AI 解析结果（基于第一页图纸）")

    # --- 展示 PartDrawing 结构化数据 ---
    basic = drawing_data.get('basic_info', {})
    dims = drawing_data.get('dimensions', {})
    tolerances = drawing_data.get('tolerances', [])
    geo_tolerances = drawing_data.get('geometric_tolerances', [])
    roughness = drawing_data.get('surface_roughness', [])
    tech_reqs = drawing_data.get('technical_requirements', [])

    # 基本信息卡片
    with st.container():
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**零件名称**: {basic.get('part_name', '—')}")
            st.markdown(f"**图号**: {basic.get('drawing_number', '—')}")
        with col2:
            st.markdown(f"**材料**: {basic.get('material', '—')}")
            st.markdown(f"**表面处理**: {basic.get('surface_treatment', '—')}")

    # 尺寸信息
    st.markdown("---")
    st.markdown("#### 📏 主要尺寸")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("长度", f"{dims.get('length', '—')} mm")
    with col2:
        st.metric("宽度", f"{dims.get('width', '—')} mm")
    with col3:
        st.metric("高度/厚度", f"{dims.get('height_thickness', '—')} mm")
    if dims.get('other_dimensions'):
        st.caption(f"其他尺寸备注: {dims['other_dimensions']}")

    # 公差信息（可折叠）
    if tolerances:
        with st.expander("🔧 尺寸公差"):
            df_tol = pd.DataFrame(tolerances)
            st.dataframe(df_tol, use_container_width=True)

    if geo_tolerances:
        with st.expander("📐 形位公差"):
            df_geo = pd.DataFrame(geo_tolerances)
            st.dataframe(df_geo, use_container_width=True)

    if roughness:
        with st.expander("✨ 表面粗糙度"):
            df_rough = pd.DataFrame(roughness)
            st.dataframe(df_rough, use_container_width=True)

    if tech_reqs:
        with st.expander("📝 技术要求"):
            for req in tech_reqs:
                st.markdown(f"- {req}")

    st.divider()
    st.subheader("📄 图纸页面浏览与批注")

    # 初始化批注字典（如果之前没有）
    if "annotations" not in st.session_state:
        st.session_state["annotations"] = {}

    # 逐页展示图片缩略图 + 批注输入框
    for idx, img in enumerate(images):
        page_num = idx + 1
        with st.expander(f"📑 第 {page_num} 页", expanded=(page_num == 1)):
            # 显示图片预览
            st.image(img, caption=f"第 {page_num} 页预览", use_container_width=True)
            # 批注功能
            key = f"annotation_page_{page_num}"
            current_val = st.session_state["annotations"].get(page_num, "")
            new_val = st.text_area(
                f"📝 第 {page_num} 页批注",
                value=current_val,
                key=key,
                height=100
            )
            if new_val != current_val:
                st.session_state["annotations"][page_num] = new_val

    # 导出批注按钮
    col1, col2 = st.columns([1, 3])
    with col1:
        export_annotations()
    with col2:
        if st.button("🗑️ 清除所有批注"):
            st.session_state["annotations"] = {}
            st.rerun()

# ========================= 底部提示 =========================
st.caption("💡 点击「解析图纸」将上传第一页至 Flask 后端,AI 将提取零件工程信息，其余页面可浏览并添加批注。")