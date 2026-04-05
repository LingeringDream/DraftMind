#添加图纸上传页面
import streamlit as st
st.set_page_config(page_title="工程数字图纸智能管理系统",layout="centered")
#使用列布局实现标题居中
col1,col2,col3=st.columns([1,10,1])
with col2:
    st.title("工程数字图纸智能管理系统")
st.markdown("基于大模型")

uploaded_file=st.file_uploader("上传图纸",type=["pdf","jpg"])

if uploaded_file is not None:
    st.success(f"已上传:{uploaded_file.name}")
else:
    st.info("请先上传工程图纸文件")

#图像预处理
from PIL import Image
import io #处理字节流
import pymupdf #解析pdf文件，提取页面图像
def load_and_preprocess(uploaded_file,target_size=(512,512)):
    '''支持pdf和常见图片格式,返回预处理后的图像'''
    file_type=uploaded_file.type
    file_bytes=uploaded_file.read()

    #处理pdf文件
    if "pdf" in file_type:
        doc=pymupdf.open(stream=file_bytes,filetype="pdf")
        if len(doc)==0:
            raise ValueError("PDF文件没有页面")
        page=doc[0]  #只处理第一页
        pix=page.get_pixmap(dpi=150)#高分辨率渲染
        img=Image.open(io.BytesIO(pix.tobytes("png")))
        doc.close()
    #图片处理
    else:
        img=Image.open(io.BytesIO(file_bytes))
    #统一转换成rgb
    if img.mode!="RGB":
        img=img.convert("RGB")

    #统一预处理
    img=img.resize(target_size)
    return img
    

