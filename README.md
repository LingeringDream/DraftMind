# DraftMind v3.0

**基于多模态大模型的工程图纸智能管理系统**

一个结合大语言模型（LLM）与计算机视觉技术的智能平台，能够自动解析机械工程图纸、提取结构化信息、执行合规性审查，并提供知识管理与智能问答能力，大幅提升工程设计与审查效率。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red.svg)
![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)

## 核心功能

*   **智能图纸解析**：上传工程图纸图片/PDF，自动识别零件名称、图号、材料、尺寸公差、形位公差等信息，并输出结构化JSON数据。
*   **AI合规性审查**：基于预设国标（GB/T 4458等）和自定义企业规则，对图纸进行全面审查，输出包含风险等级、问题描述及修改建议的详细报告。
*   **相似图纸推荐**：基于图纸语义和尺寸特征，利用向量嵌入与混合相似度计算，在知识库中快速查找历史相似图纸。
*   **图纸知识问答**：用户可基于已解析的图纸上下文，向AI提出任何相关问题，获得基于图纸内容的精准回答。
*   **矢量SVG导出**：将图纸页转换为轻量级SVG矢量格式，便于浏览和下载，并支持在SVG上叠加交互式标注热区。
*   **异步任务管理**：图纸解析在后台异步执行，前端通过进度条实时跟踪状态，支持批量上传与并行解析。
*   **多图纸库管理**：支持同时处理多张图纸，维护独立的图纸数据、对话历史和批注，并可在不同图纸间快速切换。

## 系统架构

系统采用经典的前后端分离架构，设计清晰，易于维护和扩展。

```
┌─────────────────┐     HTTP/JSON      ┌─────────────────────┐
│   Streamlit     │ <---------------> │      Flask          │
│   前端 (UI)      │                    │      后端 (API)       │
└─────────────────┘                    └─────────────────────┘
        │                                       │
        │ 用户交互                                │ 核心逻辑
        │                                       │
        ▼                                       ▼
 上传图纸/提问/查看报告                   图片压缩 & base64编码
 选择图纸/调整参数                         调用阿里云通义千问API
                                         操作阿里云OSS存储
                                         管理向量知识库
                                         处理SVG转换
```

## 快速开始

### 1. 环境准备

确保已安装 Python 3.9 或更高版本。

```bash
# 克隆项目
git clone https://github.com/LingeringDream/DraftMind.git
cd DraftMind

# 创建并激活虚拟环境 (推荐)
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制示例配置文件，并填入您自己的密钥和配置信息。

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下关键项：
*   `OPENAI_API_KEY`: 您的通义千问API Key。
*   `OPENAI_API_BASE`: 保持默认的 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
*   `OSS_ACCESS_KEY` & `OSS_ACCESS_SECRET`: 您的阿里云OSS访问密钥。
*   `OSS_BUCKET_NAME`: 您的OSS存储桶名称。

> **重要**：`.env` 文件已被添加到 `.gitignore`，不会上传至版本库，确保了敏感信息的安全。

### 3. 启动系统

使用提供的统一启动脚本，一键启动后端和前端服务。

```bash
python start.py
```

启动脚本将自动：
1.  启动Flask后端服务 (`backend.py`)。
2.  等待后端就绪。
3.  启动Streamlit前端应用 (`frontend.py`)。

启动成功后，您的浏览器将自动打开 `http://localhost:8501`，即可开始使用DraftMind。

## 技术栈

| 层级 | 技术 | 说明 |
| :--- | :--- | :--- |
| **前端** | Streamlit | 快速构建交互式数据应用的Web框架 |
| **后端** | Flask | 轻量级Python Web框架，提供RESTful API |
| **AI模型** | 通义千问 (qwen3-vl-32b-thinking, text-embedding-v3) | 多模态理解与文本嵌入 |
| **存储** | 阿里云OSS | 对象存储，用于保存图纸原图 |
| **图像处理** | Pillow, PyMuPDF | 图像压缩、格式转换与PDF解析 |
| **向量计算** | NumPy | 用于计算嵌入向量的相似度 |
| **环境管理** | python-dotenv | 加载 `.env` 配置文件 |

## 开发指南

我们欢迎社区贡献！请遵循以下流程：

1.  **Fork** 本仓库。
2.  基于 `main` 分支创建您的特性分支 (`git checkout -b feature/AmazingFeature`)。
3.  提交您的更改 (`git commit -m ‘Add some AmazingFeature’`)。
4.  推送到您的分支 (`git push origin feature/AmazingFeature`)。
5.  创建一个 **Pull Request**。

### 分支策略
*   `main`: 稳定发布分支，请勿直接提交。
*   `feature/*`: 新功能开发分支。
*   `fix/*`: 问题修复分支。

### 代码规范
*   保持后端代码清晰，遵循模块化设计（参考 `backend.py` 中的类划分）。
*   前端代码使用 Streamlit 组件，注重用户体验和交互流畅性。
*   为新功能或重要逻辑添加适当的注释。

## 许可证

本项目采用 **MIT License** 开源。详情请见 [LICENSE](LICENSE) 文件。

---

**欢迎体验 DraftMind，让AI成为您的工程设计与审查助手！**
