# Services 模块

`src/food_agent/services` 保存现有基础设施适配器和兼容服务。HTTP 接口、SSE 和外部接入
合同见[后端 API 指南](../../../docs/backend-api.md)；Agent 的新业务能力应优先依赖
`contracts` 中的 port，并由 Composition Root 注入实现，而不是直接绑定这些具体类。

## 模块清单

| 路径 | 当前职责 |
|---|---|
| `llm_service.py` | 使用 LangChain `ChatOpenAI` 调用 OpenAI-compatible Chat API |
| `session_manager.py` | 协调短期会话窗口和 PostgreSQL 聊天历史 |
| `redis_memory.py` | Redis 会话窗口；连接不可用时降级到进程内字典 |
| `postgres_storage.py` | 聊天历史和语义检索的 PostgreSQL 适配器 |
| `postgres_vector.py` | embedding 与 pgvector 辅助能力 |
| `user_storage/` | 用户、收藏、历史和餐厅持久化访问 |
| `preprocessing.py` | 文本预处理辅助函数 |
| `scoring.py` | legacy 推荐评分辅助函数 |

## LLMService

`LLMService` 不维护固定 provider 或模型白名单。模型和地址由部署配置决定：

| 参数/变量 | 优先级与作用 |
|---|---|
| 构造参数 `model_name` | 高于 `DEFAULT_LLM_MODEL` |
| `DEFAULT_LLM_MODEL` | 默认模型名 |
| `OPENAI_API_KEY` | 必需的模型凭据 |
| `OPENAI_API_BASE` | OpenAI-compatible API 基址 |
| `LLM_REASONING_EFFORT` | GPT-5/o 系列的 reasoning effort |
| `LLM_TEMPERATURE` | 非 GPT-5/o 系列的 temperature |
| `LLM_MAX_TOKENS` | GPT-5/o 系列映射到 `max_completion_tokens`，其他模型映射到 `max_tokens` |

最小示例：

```python
from langchain_core.messages import HumanMessage
from food_agent.services import LLMService

llm = LLMService(model_name="gpt-5.6-sol", reasoning_effort="medium")
response = await llm.call([HumanMessage(content="总结这些评论证据")])
```

具体模型是否接受某个参数仍由上游 OpenAI-compatible 服务决定。不要在应用文档中把
某个示例模型描述成代码强制的 allow-list；管理端模型放行是独立的产品/策略能力。

## 会话存储

`SessionManager` 的当前行为：

```text
写入: RedisMemory 同步写入 -> PostgreSQL 后台任务持久化
读取: RedisMemory -> 未命中时读取 PostgreSQL -> 回填短期窗口
```

- `RedisMemory` 默认窗口最多 20 条、TTL 24 小时；未配置或连接失败时使用进程内字典。
- `SessionManager` 暴露给 LLM 的默认上下文是最近 10 条消息。
- PostgreSQL 初始化失败时，SessionManager 继续运行 Redis-only 模式；这不等于长期历史
  已持久化。
- 进程退出时 `close()` 会等待已登记的后台保存任务。

`SessionManager` 是兼容会话服务。可靠任务、证据、店铺档案和事件流各自有独立 port 与
存储权威，不应把它当成所有 Agent 状态的唯一数据库。

## 用户与餐厅存储

`user_storage/` 使用 PostgreSQL，并通过 Alembic 已部署 schema 做启动检查；运行时不会
根据 README 中的 SQL 自动建表。未配置数据库、驱动不可用或 schema 不满足要求时，
服务标为未初始化：

- 身份读取可退化为匿名用户对象。
- 收藏、历史、资料更新和餐厅持久化不能因此被视为可靠成功。
- 表和字段的权威来源是 Alembic migrations 与 `user_storage/schema.py`，不是手写示例。

餐厅持久化模型包含点评补充的地址、坐标、评分、均价、营业时间、图片、推荐菜、活动、
provider refs、档案完整度、缺口和刷新状态；评论证据仍由证据生命周期和对应 repository
管理，不应塞进低频店铺档案字段。

## 配置边界

- 完整 legacy settings 定义：`src/food_agent/config.py`。
- target/modular settings 定义：`src/food_agent/foundation/config.py`。
- 可复制的示例：仓库根目录 `.env.example`。
- 环境变量中的 API key、数据库密码、对象存储密钥不得写进文档、fixture 或日志。

## 相关文档

- [后端 API 指南](../../../docs/backend-api.md)
- [Account Service HTTP/MCP 接入](../../../docs/account-services.md)
- [Agent 模块说明](../agents/README.md)
- [可靠任务回滚手册](../../../openspec/changes/define-modular-architecture/runbooks/b0-reliable-task-rollback.md)
