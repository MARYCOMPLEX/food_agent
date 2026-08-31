<div align="center">

# 🍜 XHS Food Agent

**小红书美食智能推荐 Agent** — 让"找吃的"变得更聪明

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic AI](https://img.shields.io/badge/Pydantic%20AI-V2-E92063?style=for-the-badge)](https://ai.pydantic.dev/)
[![Temporal](https://img.shields.io/badge/Temporal-durable%20workflows-000000?style=for-the-badge)](https://temporal.io/)
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

下方先展示兼容模式的总体链路；平台账号、Temporal、ObjectStore 与 provider
边界以本页“平台连接器集成”和 SVG/HTML 图为准。

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

## 🔌 平台连接器集成（当前开发线）

本次平台接入位于 **`codex/integrate-platform-source-connectors`**，基于已确定的
模块化基线实现；`master` 仍是稳定基线，`codex/define-modular-architecture-s0`
保存架构基线，`codex/agentic-runtime-v2` 是独立的历史 Agent Runtime 实验线，
不是本次平台接入分支。

### 外部项目与边界

| 平台 | 外部项目 | 固定快照（示例） | 接入范围 |
|------|----------|------------------|----------|
| 大众点评 | [`dazhongdianping`](https://github.com/MARYCOMPLEX/dazhongdianping) | `ffbc1d413ed1c83602212bc1fec12b57cd2b423d` | 搜索、店铺详情、评价、媒体引用；复用其 Playwright 协议模块，不启动其 FastAPI/SQLite/worker |
| 小红书 PC | [`Spider_XHS`](https://github.com/cv-cat/Spider_XHS) | `e1888d712519040f5fcc294baeac4b9505b25c98` | 笔记搜索、详情、评论、媒体引用；每个账号独立客户端和 signer |
| 小红书 Creator | [`Spider_XHS`](https://github.com/cv-cat/Spider_XHS) | 同上 | 仅本人笔记读取与健康检查；发布、上传、排程保持未注册 |

外部 checkout 只作为依赖输入，放在仓库之外，并由 Composition Root 注入。不要
把上游仓库根目录加入主应用包路径，也不要提交上游 `.env`、Cookie、SQLite 文件、
浏览器 profile、二维码或 signer 状态。需要同时运行多个不同版本时使用已审批的
sidecar；同一进程内的 in-process importer 会按顶层包（`apis`、`xhs_utils`、
`dz_engine`）锁定首个 checkout，发现串包会 fail-closed。

### 模块、技术栈与交互

| 项目模块 | 技术栈 | 运行/交互职责 |
|----------|--------|---------------|
| `src/api` | FastAPI + SSE | REST、账号登录控制面、状态/QR 展示；不接触明文凭据 |
| `src/xhs_food/contracts` | Pydantic V2 | `PlatformAccount`、`SourceInvocation`、Canonical 文档/评论/媒体及稳定错误合同 |
| `src/xhs_food/experience/platform_login.py` | Pydantic 用例服务 | 账号注册、授权、QR/手机/Cookie 流程；只接收不透明 `CREDENTIAL_REF` |
| `src/xhs_food/foundation/platform_accounts.py` | AES-GCM（Crypto）+ 本地 qualification authority | 本地测试账号/session/grant/lease/health 实现；生产替换为注入的 vault/key provider |
| `src/xhs_food/foundation/platform_account_repository.py` / `platform_account_schema.py` | SQLAlchemy 2 Async + asyncpg；Alembic | PostgreSQL 账号、加密 session 版本、grant、lease、health、login flow 权威 |
| `src/xhs_food/foundation/platform_login_temporal.py` | Temporal Python SDK | 可选 `account-auth` 队列；QR 创建/轮询/取消具备心跳、超时和重启恢复 |
| `src/xhs_food/composition/adapters/platforms.py` | Playwright（大众点评）+ Spider_XHS Python/Node 协议桥 | 每次 Activity 创建一个账号本地 provider；只导出 allow-list 协议方法 |
| `src/xhs_food/gateways/platform_sources.py` | 异步端口 + `asyncio.to_thread` | 将 tuple/envelope 转为 CanonicalSourceBatch，去除签名 URL 参数并分类错误 |
| `src/xhs_food/gateways/platform_gateway.py` | 账号绑定 SourceGateway | 先校验 tenant/platform/grant/health/session/lease，再调用 provider，最后释放并清理明文 |
| Redis | Redis 热状态 | 可重建 SSE/status、短期幂等、限流；不保存业务事实、锁、lease 或 durable task state |
| ObjectStore | S3-compatible（生产 boto3，开发 MinIO） | QR/媒体二进制及短期引用；PostgreSQL 保存元数据和权限 |

运行链路为：`FastAPI → Experience/Temporal → AccountGateway → Provider Adapter →
Canonical contracts → PostgreSQL/Evidence`；QR/媒体字节走 `ObjectStore`，Redis
只做可重建投影。大众点评与小红书的账号标识分别按
`(tenant_id, platform_channel, account_ref)` 隔离，`dianping`、`xhs_pc`、
`xhs_creator` 永不共享 Cookie、设备/signer、session version、lease 或 health。

完整 SVG/HTML 图（含模块技术栈、进程边界、队列及交互）见：
[`platform-integration-architecture.svg`](openspec/changes/integrate-platform-source-connectors/references/platform-integration-architecture.svg) ·
[`platform-integration-architecture.html`](openspec/changes/integrate-platform-source-connectors/references/platform-integration-architecture.html)。

### 启用步骤（默认保持关闭）

```powershell
git switch codex/integrate-platform-source-connectors
git clone https://github.com/MARYCOMPLEX/dazhongdianping.git CHECKOUT_PATH_DIANPING
git -C CHECKOUT_PATH_DIANPING checkout ffbc1d413ed1c83602212bc1fec12b57cd2b423d
git clone https://github.com/cv-cat/Spider_XHS.git CHECKOUT_PATH_XHS
git -C CHECKOUT_PATH_XHS checkout e1888d712519040f5fcc294baeac4b9505b25c98
```

将 `.env.example` 复制为 `.env`，只填写本地路径、基础设施地址和由部署系统
注入的密钥引用：

```dotenv
MODULAR_PLATFORM_CONNECTORS_ENABLED=true
MODULAR_PLATFORM_DIANPING_ENABLED=true
MODULAR_PLATFORM_XHS_ENABLED=true
MODULAR_PLATFORM_PROVIDER_MODE=sidecar
MODULAR_PLATFORM_DIANPING_CHECKOUT=CHECKOUT_PATH_DIANPING
MODULAR_PLATFORM_XHS_CHECKOUT=CHECKOUT_PATH_XHS
MODULAR_PLATFORM_PROVENANCE_REF=PROVENANCE_REF
MODULAR_PLATFORM_LICENSE_APPROVAL_REF=OWNER_LEGAL_REF
MODULAR_OBJECT_STORE_ENVIRONMENT=local
MODULAR_OBJECT_STORE_ENDPOINT_URL=http://HOST:PORT
MODULAR_OBJECT_STORE_BUCKET=food-agent
MODULAR_TEMPORAL_ACCOUNT_AUTH_QUEUE=account-auth
MODULAR_TEMPORAL_ACCOUNT_AUTH_ENABLED=true
```

应用启动时必须通过 `app.state.platform_runtime_factory` 注入 PostgreSQL
authority、AES-GCM session codec、provider factory、Temporal workflow 和
ObjectStore；仅设置环境变量不会自动构造 provider。先执行 `alembic upgrade head`，
再启动 API 与单独的 Temporal `account-auth` worker。`GET /v1/platform/readiness`
应显示每个平台和登录队列的脱敏状态。

### 账号登录与 re-auth

1. `POST /v1/platform/accounts` 注册一个 `(tenant_id, platform, account_ref)`，
   账号初始为 `pending_login`。
2. `xhs_pc`/`xhs_creator` 使用仓库内置的 Spider_XHS split-phase bridge：
   `POST /v1/platform/accounts/{platform}/{account_ref}/login/qr` 创建短期 QR 流程，
   `GET /v1/platform/login/{flow_id}/qr` 只返回限时展示引用，`POST .../poll` 推进状态。
3. 也可通过 `/login` 使用 `CREDENTIAL_REF` 做手机/Cookie 导入；API 和 Temporal
   历史中只出现不透明引用，不出现 Cookie、二维码内容、storage-state 或 signer 输入。
4. `dianping` 首版通过 vault handle 导入其 QR 登录生成的 Playwright storage state，
   或由部署侧注入实现同一 `PlatformLoginProvider` 端口的 account-auth sidecar；应用
   不启动上游 FastAPI、SQLite worker 或长驻 CLI。
5. 成功后由 PostgreSQL CAS 写入一个新的加密 session version；过期、取消、风控、
   worker 重启和重复完成都不会激活错误账号。Creator 发布接口保持 `CAPABILITY_UNREGISTERED`。

生产/商业启用还需要 owner/legal/security 的审批、真实 disposable-account canary
和 aggregate evidence；本地 fixture/合约测试不等同于生产批准。

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

默认启动的是兼容模式（平台连接器开关为 `false`）。兼容模式仍可读取
`XHS_COOKIES`；启用新的账号绑定平台连接器后，不再读取进程级 Cookie，而是通过
账号控制面和 `CREDENTIAL_REF` 完成登录。

| 变量 | 必需 | 说明 |
|------|:----:|------|
| `XHS_COOKIES` | 兼容模式 | 旧版 `xhs.compat` 的 Cookie（平台连接器启用后不用此变量） |
| `OPENAI_API_KEY` | ✅ | LLM API 密钥 |
| `OPENAI_API_BASE` | ✅ | API 基础地址 |
| `REDIS_HOST` | ❌ | Redis 地址（可选，fallback 到内存） |
| `POSTGRES_HOST` | ❌ | PostgreSQL 地址（可选，长期存储） |
| `EMBEDDING_API_KEY` | ❌ | Embedding API 密钥（可选，向量搜索） |

### 3️⃣ 安装依赖

**前置要求：**
- **Python 3.10+**
- **Node.js** (用于 XHS 签名加密，请确保 `node` 在 PATH 中)

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

平台接入新增的目标模块（与旧版目录并行，默认开关关闭）如下：

```
src/
├── api/platform.py                         # 账号/登录/readiness REST
└── xhs_food/
    ├── contracts/account.py                # 账号、session、grant、lease 合同
    ├── experience/platform_login.py        # 登录用例与脱敏投影
    ├── foundation/platform_accounts.py     # 本地 authority/codec
    ├── foundation/platform_account_repository.py  # PostgreSQL adapter
    ├── foundation/platform_account_schema.py      # Alembic metadata
    ├── foundation/platform_login.py        # 登录端口与结果
    ├── foundation/platform_login_temporal.py # account-auth Temporal workflow
    ├── composition/platform_bindings.py   # feature/readiness/capability binding
    ├── composition/adapters/platforms.py   # DP/Spider_XHS provider bridge
    └── gateways/
        ├── platform_sources.py             # canonical source normalizers
        └── platform_gateway.py              # account-bound SourceGateway
```

---

## � 文档

| 文档 | 说明 |
|------|------|
| [agents/README.md](src/xhs_food/agents/README.md) | Agent 模块架构与扩展 |
| [services/README.md](src/xhs_food/services/README.md) | 服务层配置与使用 |
| [spider/README.md](src/xhs_food/spider/README.md) | 爬虫模块与注意事项 |
| [api/README.md](src/api/README.md) | API 端点与 SSE 规范 |
| [平台连接器架构图](openspec/changes/integrate-platform-source-connectors/references/platform-integration-architecture.html) | 模块技术栈、进程边界、队列与交互 |
| [平台接入运行手册](openspec/changes/integrate-platform-source-connectors/verification/platform-rollout-runbook.md) | checkout、账号登录、ObjectStore、灰度与回滚 |
| [上游 provenance/兼容性记录](openspec/changes/integrate-platform-source-connectors/verification/upstream-provenance.md) | 固定 commit、依赖和 license gate |

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

平台连接器和 ObjectStore 的完整变量模板以仓库根目录
`.env.example` 为准，尤其是 `MODULAR_PLATFORM_*`、
`MODULAR_TEMPORAL_ACCOUNT_AUTH_*` 与 `MODULAR_OBJECT_STORE_*`。其中
`MODULAR_PLATFORM_PROVENANCE_REF`、`MODULAR_PLATFORM_LICENSE_APPROVAL_REF`、
`MODULAR_OBJECT_STORE_ENCRYPTION_KEY_REF` 只填写审批单/密钥系统引用，不填写
Cookie、访问令牌或明文密钥。

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

兼容模式下小红书 Cookie 有效期约 7-30 天，需要定期更新。平台连接器模式使用
账号隔离的 QR/手机/Cookie 导入流程，不把 Cookie 写入 `.env`：

1. 调用 `POST /v1/platform/accounts` 注册 `xhs_pc` 或 `xhs_creator` 账号
2. 使用 `.../login/qr` 扫码，或提交由 vault 解析的 `CREDENTIAL_REF`
3. 过期后对同一账号调用 `.../login/re-auth`；系统以 CAS 写入新的加密 session version

若仍使用旧版兼容模式，再打开浏览器登录小红书并更新 `.env` 中的 `XHS_COOKIES`。

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
- **兼容模式 Redis**: 不配置会降级为内存存储（重启丢失）
- **平台连接器 Redis**: 只承载可重建的 SSE/status、短期幂等和限流，不是业务事实或锁的权威
- **PostgreSQL**: 平台账号、加密 session、grant、lease、health 和业务历史的权威；启用平台连接器时需先执行 Alembic migration
- **ObjectStore**: 平台 QR/媒体字节的存储（本地 MinIO，生产 S3-compatible）

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
