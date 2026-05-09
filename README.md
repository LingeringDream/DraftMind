# DraftMind v3.0

**基于多模态大模型的工程图纸智能管理系统**

一个结合大语言模型（LLM）与计算机视觉技术的智能平台，能够自动解析机械工程图纸、提取结构化信息、执行合规性审查，并提供知识管理与智能问答能力，大幅提升工程设计与审查效率。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Vue.js](https://img.shields.io/badge/Vue.js-3.5+-brightgreen.svg)
![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)

## 核心功能

- **智能图纸解析**：上传工程图纸图片/PDF/DXF，自动识别零件名称、图号、材料、尺寸公差、形位公差等信息，并输出结构化JSON数据。
- **AI合规性审查**：基于预设国标（GB/T 4458等）和自定义企业规则，对图纸进行全面审查，输出包含风险等级、问题描述及修改建议的详细报告。
- **相似图纸推荐**：基于图纸语义和尺寸特征，利用向量嵌入与混合相似度计算，在知识库中快速查找历史相似图纸。
- **图纸知识问答**：用户可基于已解析的图纸上下文，向AI提出任何相关问题，获得基于图纸内容的精准回答。
- **异步任务管理**：图纸解析在后台异步执行，前端通过进度条实时跟踪状态，支持批量上传与并行解析。
- **多图纸库管理**：支持同时处理多张图纸，维护独立的图纸数据、对话历史和批注，并可在不同图纸间快速切换。

## 系统架构

系统采用前后端分离架构，前端基于 Vue.js 3 构建，后端使用 Flask 提供 RESTful API。

```
┌─────────────────┐     HTTP/JSON      ┌─────────────────────┐
│   Vue.js 3      │ <---------------> │      Flask          │
│   前端 (Vite)    │                    │      后端 (API)       │
│   Element Plus   │                    │      Python          │
└─────────────────┘                    └─────────────────────┘
        │                                       │
        │ 用户交互                                │ 核心逻辑
        │                                       │
        ▼                                       ▼
 上传图纸/提问/查看报告                   图片压缩 & base64编码
 选择图纸/调整参数                         调用阿里云通义千问API
                                         本地存储 / 阿里云OSS存储
                                         管理向量知识库
```

## 快速开始

### 1. 环境准备

确保已安装：
- **Python 3.9+**
- **Node.js 20.19+ 或 22.12+**

```bash
# 克隆项目
git clone https://github.com/LingeringDream/DraftMind.git
cd DraftMind
```

### 2. 后端配置

```bash
# 创建并激活虚拟环境 (推荐)
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

复制示例配置文件，并填入您自己的密钥和配置信息。

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下关键项：
- `OPENAI_API_KEY`: 您的通义千问 API Key。
- `OPENAI_API_BASE`: 保持默认的 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
- `OPENAI_MODEL`: 使用的模型，默认 `qwen3-vl-32b-thinking`。
- `OPENAI_EMBEDDING_MODEL`: 嵌入模型，默认 `text-embedding-v3`。
- `OPENAI_MAX_TOKENS`: 模型最大输出 Token 数，默认 `8021`。
- `OSS_ENDPOINT`: 阿里云 OSS 端点（可选，不配置时使用本地存储）。
- `OSS_ACCESS_KEY` & `OSS_ACCESS_SECRET`: 您的阿里云 OSS 访问密钥。
- `OSS_BUCKET_NAME`: 您的 OSS 存储桶名称。

> **重要**：`.env` 文件已被添加到 `.gitignore`，不会上传至版本库，确保了敏感信息的安全。

### 3. 前端配置

```bash
# 安装前端依赖
npm install
```

如需自定义后端地址，可在项目根目录创建 `.env.local` 文件：

```
VITE_API_BASE_URL=http://127.0.0.1:5000
```

### 4. 启动系统

**方式一：统一启动脚本**

```bash
python start.py
```

**方式二：分别启动**

```bash
# 启动后端
python backend.py

# 新终端，启动前端
npm run dev
```

启动成功后，访问 `http://localhost:5173` 即可使用 DraftMind。

## 项目结构

```
DraftMind/
├── backend.py              # Flask 后端服务
├── start.py                # 统一启动脚本
├── main_prompt.md          # 图纸解析 System Prompt
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例
├── index.html              # 入口 HTML
├── package.json            # 前端依赖配置
├── vite.config.js          # Vite 构建配置
├── data/                   # 解析结果持久化目录（自动创建）
├── uploads/                # 本地图片存储目录（自动创建）
├── public/                 # 静态资源
│   ├── logo.png
│   └── pdf.worker.min.mjs  # PDF.js Worker
└── src/
    ├── api/                # API 请求封装
    │   ├── client.js       # Axios 实例
    │   ├── drawing.js      # 图纸相关接口
    │   ├── job.js          # 任务状态接口
    │   └── knowledge.js    # 知识库接口
    ├── components/         # Vue 组件
    │   ├── ChatPanel.vue   # 图纸问答面板
    │   ├── DrawingInfo.vue # 图纸信息展示
    │   ├── DrawingSidebar.vue # 图纸列表侧栏
    │   ├── ReviewPanel.vue # 审查报告面板
    │   ├── SimilarPanel.vue # 相似推荐面板
    │   └── TaskProgress.vue # 任务进度条
    ├── stores/             # Pinia 状态管理
    │   └── drawing.js
    ├── utils/
    │   └── image.js        # 图像/PDF 处理工具
    ├── views/
    │   └── HomeView.vue    # 主页面
    ├── App.vue
    ├── main.js
    └── router.js
```

## API 接口

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/` | 健康检查 |
| `POST` | `/conversation/new` | 上传图纸并创建解析任务 |
| `GET` | `/conversation/list` | 获取图纸列表 |
| `GET` | `/conversation/{uuid}/info` | 获取图纸解析信息 |
| `POST` | `/conversation/{uuid}/review` | 获取合规审查报告 |
| `POST` | `/conversation/{uuid}/ask` | 图纸知识问答 |
| `GET` | `/job/{jobId}/status` | 查询任务状态 |
| `POST` | `/job/{jobId}/prioritize` | 提升任务优先级 |
| `GET` | `/knowledge/similar/{uuid}` | 相似图纸推荐 |
| `POST` | `/knowledge/search` | 语义搜索 |

## 技术栈

| 层级 | 技术 | 说明 |
| :--- | :--- | :--- |
| **前端** | Vue.js 3 + Element Plus | 响应式 UI 框架，组件化开发 |
| **构建工具** | Vite | 快速开发服务器与构建 |
| **状态管理** | Pinia | Vue 3 官方状态管理方案 |
| **路由** | Vue Router | 单页应用路由管理 |
| **HTTP 客户端** | Axios | API 请求与拦截器 |
| **后端** | Flask + flask-cors | 轻量级 Python Web 框架，支持跨域请求 |
| **AI 模型** | 通义千问 (qwen3-vl-32b-thinking, text-embedding-v3) | 多模态理解与文本嵌入 |
| **存储** | 本地磁盘 / 阿里云 OSS | 图片默认本地存储，可选 OSS 云端存储 |
| **数据持久化** | JSON 文件 | 解析结果保存到 `data/` 目录，重启后自动加载 |
| **图像处理** | Pillow, pdfjs-dist | 图像压缩、PDF 解析（浏览器端） |
| **CAD 支持** | ezdxf, matplotlib | DXF 文件解析与渲染为图片 |
| **HTTP 请求** | requests | 调用通义千问 API |
| **向量计算** | numpy | 余弦相似度与尺寸相似度计算 |
| **环境管理** | python-dotenv | 加载 `.env` 配置文件 |

## 开发指南

### 开发命令

```bash
# 前端开发服务器（热重载）
npm run dev

# 前端构建
npm run build

# 前端代码检查
npm run lint

# 前端代码格式化
npm run format
```

### 分支策略
- `main`: 稳定发布分支，请勿直接提交。
- `dev`: 开发分支。
- `feature/*`: 新功能开发分支。
- `fix/*`: 问题修复分支。

### 贡献流程

1. **Fork** 本仓库。
2. 基于 `dev` 分支创建您的特性分支 (`git checkout -b feature/AmazingFeature`)。
3. 提交您的更改 (`git commit -m 'feat: add AmazingFeature'`)。
4. 推送到您的分支 (`git push origin feature/AmazingFeature`)。
5. 创建一个 **Pull Request**。

## 许可证

本项目采用 **MIT License** 开源。详情请见 [LICENSE](LICENSE) 文件。

---

**欢迎体验 DraftMind，让AI成为您的工程设计与审查助手！**
