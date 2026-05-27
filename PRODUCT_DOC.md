# 视频总结工具 — 产品文档

## 1. 产品概述

一个本地运行的 Web 工具，用户输入视频 URL，选择"原文"或"总结"模式，系统自动完成字幕提取/音频转写，调用 DeepSeek 大模型总结，生成排版整齐的中文 HTML 结果页，并支持历史记录浏览。

**使用场景：** 个人使用，快速获取视频的文字版/摘要，省去观看时间。

**用户量：** 1 人，本地运行。

---

## 2. 功能需求

### 2.1 核心流程

```
输入URL → 选择模式(原文/总结) → 选择总结粒度(若选总结) → 提交
  → [进度实时反馈] 下载字幕/音频 → Whisper转写 → LLM总结(可选) → 生成HTML → 保存历史
  → 展示结果页
```

### 2.2 选项说明

用户提交任务前需选择：

| 选项 | 可选值 | 说明 |
|------|--------|------|
| **模式** | 原文 / 总结 | 原文=完整转录文本；总结=AI提炼 |
| **总结粒度** | 简洁 / 标准 / 详细 | 仅总结模式生效 |
| **LLM 来源** | 本地 / API | 仅总结模式生效 |

**LLM 来源说明：**

| 来源 | 模型 | 调用方式 |
|------|------|----------|
| **本地** | `deepseek-r1:8b` | 通过 Ollama 本地推理（默认） |
| **API** | DeepSeek API | 通过 OpenAI 兼容接口调用 |

### 2.3 总结粒度（仅总结模式）

- **简洁（约200字）：** 核心要点一句话 + 3-5 个关键信息点
- **标准（约800字）：** 分段总结，包含背景、核心内容、结论
- **详细（约2000字）：** 完整摘要 + 分章节要点 + 关键引用

### 2.4 平台支持

通过 yt-dlp 覆盖主流视频平台：

| 平台 | 字幕 | 兜底方案 |
|------|------|----------|
| YouTube | 优先使用官方字幕（自动生成字幕标记提示） | yt-dlp 下载音频 |
| Bilibili | 优先使用 CC 字幕 | 下载音频 → Whisper |
| 其他（yt-dlp 支持的所有平台） | 有字幕则用 | 同上 |

### 2.5 历史记录

- 输出 HTML 文件保存至 `D:\video-summary-output\`
- 目录结构：

```
D:\video-summary-output\
├── index.json              # 历史索引
├── 2026-05-27_<title1>.html
├── 2026-05-27_<title2>.html
└── ...
```

- `index.json` 结构：

```json
[
  {
    "id": "uuid",
    "title": "视频标题",
    "url": "原始URL",
    "platform": "youtube",
    "mode": "summary",
    "granularity": "standard",
    "created_at": "2026-05-27T10:30:00",
    "filename": "2026-05-27_xxx.html"
  }
]
```

- 前端历史列表页：按时间倒序排列，点击可查看已生成的 HTML

### 2.6 进度反馈

通过 **SSE (Server-Sent Events)** 向前端实时推送进度：

```
等待处理 → 正在获取视频信息 → 正在下载字幕 → 字幕下载完成
                                   → 无字幕，正在下载音频 → 正在本地转写(Whisper)...
                                   → 转写完成，正在调用DeepSeek总结...
                                   → 正在生成HTML → 完成 ✓
```

每个阶段有对应状态文本和百分比。

---

## 3. 技术方案

### 3.1 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端框架 | **FastAPI** (Python 3.10+) | 轻量、异步、自带 SSE 支持 |
| 视频下载 | **yt-dlp** | 多平台视频/字幕/音频下载 |
| 语音转写 | **Whisper** (本地 base 模型) | 离线转写，无 API 成本 |
| 大模型（本地）| **Ollama** (`deepseek-r1:8b`) | 默认选项，本地推理 |
| 大模型（API）| **DeepSeek API** (OpenAI 兼容) | 备选，通过 API Key 调用 |
| 前端 | **纯 HTML + JS + CSS** | 单文件，本地打开，简洁风格 |
| 配置管理 | `.env` 环境变量 | DEEPSEEK_API_KEY, OLLAMA_BASE_URL |

### 3.2 架构图

```
┌─────────────────────────────────────────────────────┐
│  浏览器 (前端单页面)                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ 输入页       │  │ 进度展示      │  │ 历史列表     │ │
│  │ URL + 选项   │  │ SSE 实时更新  │  │ 查看结果     │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
└─────────┼────────────────┼─────────────────┼────────┘
          │ HTTP POST      │ SSE             │ HTTP GET
          ▼                ▼                 ▼
┌─────────────────────────────────────────────────────┐
│  FastAPI 后端 (localhost:8000)                       │
│                                                      │
│  POST /api/process  ──→  Pipeline ──→  生成HTML      │
│                                                      │
│  Pipeline:                                           │
│  ① VideoService  (yt-dlp: 获取信息/字幕/音频)        │
│  ② WhisperService (本地Whisper base模型转写)          │
│  ③ LlmService ┬─ Ollama (本地 deepseek-r1:8b)        │
│               └─ DeepSeek API (远程)                  │
│  ④ HtmlRenderer  (渲染HTML模板)                      │
│  ⑤ HistoryService (保存文件 + 更新索引)              │
│                                                      │
│  GET  /api/history     ←── 获取历史列表               │
│  GET  /api/output/{id} ←── 获取已生成的HTML           │
│  GET  /api/progress/{task_id}  ←── SSE进度推送        │
└─────────────────────────────────────────────────────┘
```

### 3.3 API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/process` | 提交处理任务，返回 task_id |
| `GET` | `/api/progress/{task_id}` | SSE 连接，推送实时进度 |
| `GET` | `/api/history` | 历史记录列表 |
| `GET` | `/api/output/{id}` | 获取指定历史 HTML 内容 |
| `DELETE` | `/api/output/{id}` | 删除指定历史记录 |

**POST /api/process 请求体：**

```json
{
  "url": "https://www.youtube.com/watch?v=xxx",
  "mode": "summary",
  "granularity": "standard",
  "llm_source": "local"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | 视频链接 |
| `mode` | string | 是 | `"original"` / `"summary"` |
| `granularity` | string | 否 | `"brief"` / `"standard"` / `"detailed"`，默认 `"standard"` |
| `llm_source` | string | 否 | `"local"` / `"api"`，默认 `"local"` |

**响应：**

```json
{
  "task_id": "uuid",
  "status": "queued"
}
```

**SSE 事件格式：**

```
data: {"stage":"downloading","progress":20,"message":"正在下载音频..."}
data: {"stage":"transcribing","progress":40,"message":"正在本地转写..."}
data: {"stage":"summarizing","progress":70,"message":"正在调用DeepSeek总结..."}
data: {"stage":"done","progress":100,"message":"完成","result_id":"uuid"}
data: {"stage":"error","progress":0,"message":"错误信息"}
```

### 3.4 Pipeline 详细逻辑

```
1. 验证URL → 提取平台类型
2. yt-dlp --list-subs 检查是否有字幕
3. 有字幕 → yt-dlp --write-subs 下载字幕文件(.vtt/.srt)
4. 无字幕 → yt-dlp -f bestaudio 下载音频 → whisper 转写
5. 原文模式 → 直接渲染HTML
6. 总结模式 → 根据 llm_source 选择：
   - local → 调用 Ollama (deepseek-r1:8b)
   - api   → 调用 DeepSeek API
   → 解析结果 → 渲染HTML
7. 保存HTML到D:\video-summary-output\ → 更新index.json
8. SSE通知前端完成
```

### 3.5 LLM 服务设计

提供统一的 `LlmService` 抽象，根据 `llm_source` 参数切换实现：

**本地 (Ollama)：**
- 模型：`deepseek-r1:8b`
- 接口：`POST http://localhost:11434/api/generate`
- JSON Schema 格式的 structured output

**API (DeepSeek)：**
- 接口：OpenAI 兼容 SDK，base_url 指向 DeepSeek
- 模型：`deepseek-v4-flash`
- API Key 从 `.env` 读取

**Prompt 设计（两种 LLM 共用）**

根据粒度调整 system prompt：

**简洁：**
```
你是一个专业的视频内容总结助手。请用中文对以下视频文本进行简洁总结。
要求：
1. 一句话概括核心内容（不超过50字）
2. 列出3-5个关键信息点
3. 总字数控制在200字以内
```

**标准：**
```
你是一个专业的视频内容总结助手。请用中文对以下视频文本进行分段总结。
要求：
1. 主题概述（1-2句话）
2. 核心内容分点总结（3-5个大点，每点2-3句话）
3. 关键结论或要点
4. 总字数控制在800字以内
```

**详细：**
```
你是一个专业的视频内容总结助手。请用中文对以下视频文本进行详细总结。
要求：
1. 视频基本信息概述
2. 按章节/主题分段总结
3. 每段包含核心观点和关键论据
4. 引用原文中的关键语句（标注时间戳如果可用）
5. 总结与延伸思考
6. 总字数控制在2000字左右
```

---

## 4. 前端设计

### 4.1 页面结构

单页面应用，3 个视图：

**视图1：输入页（默认）**
- 居中卡片布局
- URL 输入框（placeholder: "粘贴 B站 / YouTube 等视频链接..."）
- 模式切换：`○ 原文  ● 总结`
- 粒度选择（总结模式下显示）：`简洁 / 标准 / 详细` 下拉框
- LLM 来源选择（总结模式下显示）：`本地(Ollama) / API(DeepSeek)` 切换
- 提交按钮
- 底部：历史记录入口

**视图2：处理中（进度页）**
- 进度条 + 百分比
- 当前阶段图标动画（下载 → 转写 → 总结 → 生成）
- 阶段文字描述
- 取消按钮（可选）

**视图3：结果页 / 历史查看页**
- 左侧：历史列表（标题 + 日期）
- 右侧：HTML 内容渲染区（iframe 嵌入预览）
- 顶部工具栏：返回按钮 + "在新标签页打开"按钮 + "重新处理"按钮

### 4.2 样式风格

- 配色：黑白灰 + 单一强调色（如蓝色 #2563EB）
- 字体：系统默认中文字体（PingFang SC / Microsoft YaHei）
- 布局：响应式，最大宽度 960px 居中
- 不依赖任何前端框架，纯原生实现

### 4.3 交互细节

- 提交后自动切换到进度页
- 进度完成后自动跳转结果页
- 历史列表点击直接渲染 HTML 预览
- 加载态、空态、错误态都有对应 UI

---

## 5. 项目结构

```
video-summary/
├── backend/
│   ├── main.py              # FastAPI 入口 + 路由
│   ├── config.py             # 配置加载（.env）
│   ├── services/
│   │   ├── video_service.py  # yt-dlp 封装
│   │   ├── whisper_service.py # Whisper 转写
│   │   ├── llm_service.py      # LLM抽象（Ollama + DeepSeek API）
│   │   ├── html_renderer.py  # HTML 模板渲染
│   │   └── history_service.py # 历史记录管理
│   ├── models/
│   │   └── schemas.py        # Pydantic 数据模型
│   ├── templates/
│   │   ├── original.html     # 原文HTML模板
│   │   └── summary.html     # 总结HTML模板
│   └── utils/
│       └── sse_manager.py    # SSE 进度管理
├── frontend/
│   └── index.html            # 前端单页面
├── .env                       # 环境变量 (DEEPSEEK_API_KEY)
├── requirements.txt
└── PRODUCT_DOC.md
```

---

## 6. 关键依赖

```
fastapi==0.104+
uvicorn==0.24+
yt-dlp==2024+
openai-whisper==20231117+
openai==1.0+          # DeepSeek兼容OpenAI SDK
httpx==0.25+          # Ollama HTTP调用
python-dotenv==1.0+
sse-starlette==2.0+
```

## 7. 环境变量 (`.env`)

```env
# DeepSeek API (API模式使用)
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Ollama (本地模式使用，默认值无需修改)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:8b

# 输出目录
OUTPUT_DIR=D:\\video-summary-output
```

---

## 8. 确认事项（已确认 ✓）

| 事项 | 决定 |
|------|------|
| LLM 选项 | 本地 Ollama `deepseek-r1:8b`（默认）+ DeepSeek API 双选 |
| API Key | 已提供，存 `.env` |
| Whisper 模型 | 本地 base 模型（~140MB 自动下载） |
| 输出目录 | `D:\video-summary-output\` |
| 新标签页 | 结果页增加"在新标签页打开"按钮 |
| 语言 | 所有输出统一中文 |

---

## 9. 开发计划（建议顺序）

| 阶段 | 内容 | 预计 |
|------|------|------|
| 1 | 搭建 FastAPI 骨架 + 配置 + 数据模型 | 基础 |
| 2 | yt-dlp 视频/字幕下载服务 | 核心 |
| 3 | Whisper 转写服务 | 核心 |
| 4 | DeepSeek 总结服务 | 核心 |
| 5 | HTML 渲染器 + 历史存储 | 核心 |
| 6 | SSE 进度推送 | 体验 |
| 7 | 前端页面（3个视图） | 体验 |
| 8 | 联调测试 + 边界处理 | 收尾 |
