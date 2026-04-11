#添加图纸上传页面
import streamlit as st
import requests
from PIL import Image
import io #处理字节流
import pymupdf #解析pdf文件，提取页面图像
import base64
from dashscope import MultiModalConversation


#============================页面配置============================
st.set_page_config(page_title="工程数字图纸智能管理系统",layout="centered")
#主页标题居中
col1,col2,col3=st.columns([1,10,1])
with col2:
    st.title("工程数字图纸智能管理系统")
st.markdown("基于大模型")


#=================后端api地址配置=================
API_URL = st.sidebar.text_input("后端 API 地址", value="http://localhost:8000/api/parse")
#根据实际后端api地址改变默认值，提示用户输入正确地址    
st.sidebar.markdown("💡 确保 FastAPI 后端已启动且接口地址正确")


#========================文件上传与保存========================
uploaded_file=st.file_uploader("上传图纸",type=["pdf","jpg"],help="支持PDF和常见图片格式")

if uploaded_file is not None:
    st.success(f"已上传:{uploaded_file.name}")
    #保存原始字节流、文件名、类型到session_state，供后续处理使用
    st.session_state['file_bytes'] = uploaded_file.getvalue()
    st.session_state['file_name'] = uploaded_file.name
    st.session_state['file_type'] = uploaded_file.type
    #=======补全按钮和请求代码========
    if st.button("开始解析图纸"):
        files = {
            "file": (
                st.session_state['file_name'],
                st.session_state['file_bytes'],
                st.session_state['file_type']
            )
        }
        try:
            import requests
            response = requests.post(API_URL, files=files)
            if response.status_code == 200:
                st.success("图纸解析成功！")
                st.json(response.json())    
            else:
                st.error(f"后端返回错误: {response.status_code}\n{response.text}")
        except Exception as e:
            st.error(f"请求后端接口时发生错误: {str(e)}") 
    
else:
   for key in ['file_bytes', 'file_name', 'file_type']:
        if key in st.session_state:
            del st.session_state[key]       
#========================图像预处理=========================

def load_and_preprocess(file_bytes,file_type,file_name,target_size=(512,512)):

    #处理pdf文件
    if "pdf" in file_type:
        doc=pymupdf.open(stream=file_bytes,filetype="pdf")
        if len(doc)==0:
            raise ValueError("PDF文件没有页面")
        else:
            page_num=st.slider("选择要查看的页面",1,len(doc),1)
            page=doc[page_num-1]  
            pix=page.get_pixmap(dpi=150)#高分辨率渲染
            img=Image.open(io.BytesIO(pix.tobytes("png")))
            st.image(img,caption=f"PDF页面{page_num}",use_column_width=True)
            doc.close()
    #图片处理
    elif "jpg" in file_type:
        img=Image.open(uploaded_file)
        st.image(img,caption="上传的图纸",use_column_width=True)
    else:
        st.warning(f"不支持的文件类型: {file_type}")
        return None
    #统一转换成rgb并resize
    if img.mode!="RGB":
        img=img.convert("RGB")
    img=img.resize(target_size)
    return img
 

 #================调用后端接口进行图像分析========================
if st.button("🔍 解析图纸", type="primary", disabled=('file_bytes' not in st.session_state)):
    with st.spinner("正在调用后端模型解析，请稍候..."):
        try:
            # 构造 multipart/form-data 请求
            files = {
                "file": (
                    st.session_state['file_name'],
                    st.session_state['file_bytes'],
                    st.session_state['file_type']
                )
            }
            response = requests.post(API_URL, files=files, timeout=30)
            response.raise_for_status()  # 抛出 HTTP 错误
            result = response.json()

            # 根据后端实际返回结构调整提取字段（常见为 "result" 或 "text"）
            output_text = result.get("result") or result.get("text") or str(result)
            st.success("图纸解析完成！")
            st.subheader("识别结果")
            st.text_area("模型输出", value=output_text, height=300)
        except requests.exceptions.ConnectionError:
            st.error(f" 无法连接到后端服务，请确保 FastAPI 已启动且地址正确：{API_URL}")
        except requests.exceptions.Timeout:
            st.error("请求超时，请检查后端处理时间或网络")
        except requests.exceptions.HTTPError as e:
            st.error(f" 后端返回错误：{e.response.status_code} - {e.response.text}")
        except Exception as e:
            st.error(f" 未知错误：{e}")

# 底部提示
st.caption(" 点击「解析图纸」将调用后端 /api/parse 接口，后端需返回包含 'result' 或 'text' 字段的 JSON")
