<div align="center">

# 🍜 XHS Food Agent

**小红书美食智能推荐 Agent** — 让"找吃的"变得更聪明

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-🦜-2C3E50?style=for-the-badge)](https://www.langchain.com/)
[![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

<p align="center">
  <strong>🔍 智能搜索 · 🎯 本地推荐 · ❌ 过滤网红 · 💬 多轮对话 · 🧠 长期记忆</strong>
</p>

---

*一个基于 LLM 的智能美食推荐系统，通过分析小红书社区真实用户评论，*  
*识别本地人推荐的隐藏美食，过滤网红流量店，帮你找到真正值得打卡的美食。*

<br/>

**[🚀 快速开始](#-快速开始) · [📖 文档](#-文档) · [💡 特性](#-核心特性) · [🤝 贡献](#-贡献)**

</div>

---

## 🎯 为什么选择 XHS Food Agent？

<table>
<tr>
<td width="50%">

### 😤 传统方式的痛点

- ❌ 搜"成都火锅"返回千篇一律的网红店
- ❌ 分不清哪些是真实推荐，哪些是广告软文
- ❌ 本地人私藏的宝藏店铺难以发现
- ❌ 需要翻阅大量笔记和评论

</td>
<td width="50%">

### 😊 我们的解决方案

- ✅ AI 智能分析评论，识别本地人口碑店
- ✅ 多维度信任评分，自动过滤营销内容
- ✅ 4 阶段搜索策略，挖掘隐藏美食
- ✅ 一句话搜索，秒出靠谱推荐

</td>
</tr>
</table>

---

## ✨ 核心特性

<table>
<tr>
<td width="50%">

### 🧠 智能分析引擎
- **4阶段搜索策略** — 广撒网、挖隐藏、定向验证、细分搜索
- **评论权重系统** — 识别本地人 vs 游客的真实评价
- **网红店过滤** — 自动识别并过滤过度营销内容

</td>
<td width="50%">

### 💾 混合记忆系统
- **Redis (L1)** — 短期上下文，滑动窗口
- **PostgreSQL (L2)** — 长期持久化 + pgvector 向量检索
- **智能缓存预热** — 自动恢复历史对话

</td>
</tr>
<tr>
<td width="50%">

### 🚀 生产就绪
- **SSE 流式输出** — 实时获取搜索进度
- **断线恢复** — 无感重连，数据不丢失
- **多用户支持** — 完整的会话管理 API

</td>
<td width="50%">

### 🔧 灵活配置
- **多 LLM 支持** — SiliconFlow / OpenAI / DeepSeek
- **独立 Embedding** — 可配置专用向量模型
- **优雅降级** — 组件缺失时自动 fallback

</td>
</tr>
</table>

---

## 🎬 Demo 演示

<details>
<summary>📱 <strong>点击展开使用示例</strong></summary>

### 示例查询

```bash
# 1. 基础搜索
"成都本地人常去的老火锅"

# 2. 带偏好的搜索
"上海浦东机场附近，适合商务宴请的餐厅，预算 500 以内"

# 3. 追问对话
"还有便宜点的吗？" / "有没有排队少的？"
```

### 返回结果示例

```json
{
  "name": "蜀大侠火锅",
  "trustScore": 8.5,
  "oneLiner": "本地人推荐的老火锅，锅底正宗不踩雷",
  "pros": ["锅底正宗", "服务热情", "性价比高"],
  "cons": ["高峰期需排队"],
  "mustTry": [{"name": "毛肚", "reason": "招牌必点"}],
  "stats": {
    "flavor": "A",
    "cost": "$$",
    "wait": "15min"
  }
}
```

</details>

---

## 🛠️ 技术架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         XHS Food Agent                                │
├──────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌─────────────────┐   ┌────────────────────────┐ │
│  │   FastAPI    │───│  SessionManager │───│   Multi-Agent System   │ │
│  │ (SSE + REST) │   │  (会话编排器)    │   │  Intent │ Analyzer    │ │
│  └──────────────┘   └─────────────────┘   └────────────────────────┘ │
│         │                  │    │                     │              │
│         ▼                  ▼    ▼                     ▼              │
│  ┌─────────────┐   ┌───────────────────────────┐  ┌───────────────┐ │
│  │   Redis     │   │      PostgreSQL           │  │  LLM Service  │ │
│  │ (L1 Cache)  │   │  + pgvector (L2 Storage)  │  │ (SiliconFlow) │ │
│  └─────────────┘   └───────────────────────────┘  └───────────────┘ │
│                              │                            │          │
│                              ▼                            ▼          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      XHS Spider                                │  │
│  │          (Search · Note Content · Comments Scraping)           │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 多 Agent 协作流程

```mermaid
flowchart LR
    A[用户查询] --> B[IntentParser<br/>意图解析]
    B --> C[XHS Spider<br/>数据采集]
    C --> D[Analyzer<br/>评论分析]
    D --> E[POIEnricher<br/>信息补充]
    E --> F[推荐结果]
```

---

## 🚀 快速开始

### 1️⃣ 克隆项目

```bash
git clone https://github.com/your-username/xhs-food-agent.git
cd xhs-food-agent
```

### 2️⃣ 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下项目：

| 变量 | 必需 | 说明 |
|------|:----:|------|
| `XHS_COOKIES` | ✅ | 小红书登录 Cookie |
| `OPENAI_API_KEY` | ✅ | LLM API 密钥 |
| `OPENAI_API_BASE` | ✅ | API 基础地址 |
| `REDIS_HOST` | ❌ | Redis 地址（可选，fallback 到内存） |
| `POSTGRES_HOST` | ❌ | PostgreSQL 地址（可选，长期存储） |
| `EMBEDDING_API_KEY` | ❌ | Embedding API 密钥（可选，向量搜索） |

### 3️⃣ 安装依赖

```bash
# 安装 uv (如果尚未安装)
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
# Linux/Mac
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依赖 (自动创建虚拟环境)
uv sync
```

### 4️⃣ 启动服务

```bash
uvicorn src.api.main:app --reload --port 8000
```

🎉 **服务已启动!** 访问 http://localhost:8000/docs 查看 API 文档

---

## 🧪 本地测试（无需前端）

如果你只想快速体验核心功能，**无需启动服务器**，可以直接使用测试脚本：

### 交互式对话（推荐）

```bash
# 深度搜索模式（默认，更全面）
uv run python tests/test_dialogue.py

# 快速模式（搜索更快，笔记数量较少）
uv run python tests/test_dialogue.py --fast
```

启动后进入交互式对话，支持多轮追问：
```
你: 成都本地人常去的老火锅
[状态: success]
推荐店铺 (5 家):
  1. 蜀大侠火锅
     判定: authentic (置信度: 85%)
     特点: 锅底正宗, 服务热情, 性价比高
     ...

你: 排除蜀大侠，还有其他推荐吗？
你: 有没有不用排队的？
你: reset   # 重置对话
你: quit    # 退出
```

### 单次查询

```bash
uv run python tests/test_dialogue.py --mode single --query "上海浦东机场附近的川菜"
```

### 预设对话流程

```bash
uv run python tests/test_dialogue.py --mode preset
```

> 💡 **提示**: 本地测试脚本直接调用 `XHSFoodOrchestrator` 核心模块，非常适合开发调试和快速验证功能。

---

## 📡 API 接口

### 搜索接口

```bash
# 普通搜索
curl -X POST http://localhost:8000/v1/search/start \
  -H "Content-Type: application/json" \
  -d '{"query": "成都本地人常去的老火锅"}'

# SSE 流式搜索 (推荐)
curl -N "http://localhost:8000/v1/search/stream/{sessionId}"
```

### 会话管理

```bash
# 创建新会话
curl -X POST http://localhost:8000/api/v1/session/create

# 断线恢复
curl http://localhost:8000/v1/search/recover/{sessionId}
```

<details>
<summary>📋 <strong>完整 API 端点列表</strong></summary>

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/v1/search/start` | 启动搜索 |
| `GET` | `/v1/search/stream/{id}` | SSE 流式搜索 |
| `GET` | `/v1/search/recover/{id}` | 断线恢复 |
| `POST` | `/v1/search/refine` | 多轮追问 |
| `GET` | `/v1/favorites` | 收藏列表 |
| `POST` | `/v1/favorites` | 添加收藏 |
| `GET` | `/v1/history` | 搜索历史 |
| `GET` | `/v1/user/profile` | 用户资料 |

</details>

---

## 📂 项目结构

```
xhs_food_agent/
├── 📁 src/
│   ├── 📁 api/                    # FastAPI 服务层
│   │   ├── main.py               # 应用入口
│   │   ├── search.py             # 搜索 API (SSE)
│   │   ├── favorites.py          # 收藏功能
│   │   └── README.md             # 📖 模块文档
│   │
│   └── 📁 xhs_food/              # 核心 Agent 模块
│       ├── orchestrator.py       # 🎯 主编排器
│       ├── schemas.py            # 数据模型
│       │
│       ├── 📁 agents/            # 子 Agent
│       │   ├── intent_parser.py  # 意图解析
│       │   ├── analyzer.py       # 结果分析
│       │   ├── poi_enricher.py   # POI 补充
│       │   └── README.md         # 📖 模块文档
│       │
│       ├── 📁 services/          # 💾 核心服务
│       │   ├── llm_service.py    # LLM 封装
│       │   ├── redis_memory.py   # Redis L1
│       │   ├── postgres_storage.py # PostgreSQL L2
│       │   ├── session_manager.py  # 会话管理
│       │   └── README.md         # 📖 模块文档
│       │
│       └── 📁 spider/            # XHS 爬虫
│           └── README.md         # 📖 模块文档
│
├── 📁 tests/                     # 测试用例
├── .env.example                  # 环境变量模板
├── pyproject.toml                # 项目配置
└── README.md                     # 项目说明
```

---

## � 文档

| 文档 | 说明 |
|------|------|
| [agents/README.md](src/xhs_food/agents/README.md) | Agent 模块架构与扩展 |
| [services/README.md](src/xhs_food/services/README.md) | 服务层配置与使用 |
| [spider/README.md](src/xhs_food/spider/README.md) | 爬虫模块与注意事项 |
| [api/README.md](src/api/README.md) | API 端点与 SSE 规范 |

---

## 🔧 高级配置

### 完整环境变量

```bash
# ========== LLM API ==========
OPENAI_API_KEY="sk-xxx"
OPENAI_API_BASE="https://api.siliconflow.cn/v1/"
DEFAULT_LLM_MODEL="Qwen/Qwen3-8B"

# ========== Redis (可选) ==========
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DATABASE=0
REDIS_PASSWORD=

# ========== PostgreSQL (可选) ==========
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=xhs_food_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD=

# ========== Embedding API (可选) ==========
EMBEDDING_API_KEY="sk-xxx"
EMBEDDING_API_BASE="https://api.openai.com/v1/"
EMBEDDING_MODEL="text-embedding-3-small"
```

### 支持的 LLM 提供商

| 提供商 | API Base | 推荐模型 |
|--------|----------|----------|
| SiliconFlow | `https://api.siliconflow.cn/v1/` | `Qwen/Qwen3-8B` |
| OpenAI | `https://api.openai.com/v1/` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1/` | `deepseek-chat` |

---

## 📋 开发计划

- [x] 基础多轮对话支持
- [x] SSE 流式输出
- [x] 评论权重分析系统
- [x] Redis 会话缓存
- [x] PostgreSQL 持久化存储
- [x] pgvector 向量搜索
- [x] 断线恢复机制
- [ ] 🚧 地理位置感知 (GPS 推荐)
- [ ] 🚧 用户偏好学习
- [ ] 📱 移动端 App
- [ ] 🐳 Docker 部署支持

---

## ❓ 常见问题

<details>
<summary><strong>Q: Cookie 过期了怎么办？</strong></summary>

小红书 Cookie 有效期约 7-30 天，需要定期更新：

1. 打开浏览器登录小红书
2. F12 → Network → 复制 Cookie
3. 更新 `.env` 中的 `XHS_COOKIES`

</details>

<details>
<summary><strong>Q: 为什么搜索结果不准确？</strong></summary>

可能原因：
1. 搜索关键词过于宽泛 → 尝试添加地点/菜系限定
2. 该地区笔记较少 → 热门城市效果更好
3. LLM 模型能力 → 尝试切换更强的模型

</details>

<details>
<summary><strong>Q: Redis/PostgreSQL 必须配置吗？</strong></summary>

不是必须的：
- **Redis**: 不配置会降级为内存存储（重启丢失）
- **PostgreSQL**: 不配置则仅有短期记忆，无法持久化

推荐生产环境完整配置。

</details>

---

## 🤝 贡献

欢迎贡献代码、提交 Issue 或建议！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开一个 Pull Request

---

## ⚠️ 免责声明

本项目仅供学习和研究使用。使用本项目获取小红书数据时，请遵守：

- 小红书服务条款和使用规范
- 相关法律法规
- 合理的请求频率限制

**请勿将本项目用于商业用途或任何可能损害小红书平台利益的行为。**

---

## 🙏 致谢

本项目的小红书数据采集能力基于以下优秀开源项目：

<table>
<tr>
<td align="center">
<a href="https://github.com/cv-cat/Spider_XHS">
<img src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" width="60" alt="Spider_XHS"/><br/>
<strong>Spider_XHS</strong>
</a>
<br/>
<sub>小红书逆向爬虫 · 为本项目提供核心数据采集能力</sub>
<br/>
<sub>感谢 <a href="https://github.com/cv-cat">@cv-cat</a> 的辛勤付出 ❤️</sub>
</td>
</tr>
</table>

---

## 📄 License

本项目采用 [MIT License](LICENSE) 开源协议。

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐ Star 支持一下！**

Made with ❤️ by <a href="https://github.com/MARYCOMPLEX">@MARYCOMPLEX</a>

</div>