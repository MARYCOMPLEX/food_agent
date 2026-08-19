# 已批准基础设施裁决记录

> 状态：Approved
>
> 裁决日期：2026-08-19
>
> 适用 change：`define-modular-architecture`

本文记录架构基线已经批准的基础设施和框架选择，替代此前的候选依赖调研。后续 proposal、design、spec、task、ADR 和实现必须以本文为选型基线；依赖升级可以在兼容范围内进行，但引入另一套同职责核心运行时、事实存储或 Agent 框架必须新建 ADR，并证明迁移、回滚和所有权边界。

Query Family、Evidence Bundle、Domain Contract、公共评分、个性化策略、任务状态机和稳定 API/事件合同仍由本项目拥有。被批准的库只实现端口或基础设施能力，不取得业务语义所有权。

## 最终技术栈

| 能力 | 已批准选择 | 状态 | 强制边界 |
|---|---|---|---|
| Agent/LLM runtime | Pydantic AI V2 stable core | Adopt | 只位于 Research Orchestrator 内部；不得成为任务、证据、记忆或 Domain Pack 的事实所有者 |
| Durable workflow | Temporal Python SDK + Temporal Service | Adopt | Research、Refresh、Media 共用唯一 durable runtime；不得并行引入第二套任务引擎 |
| 权威数据库 | PostgreSQL 16 | Adopt | 业务任务读模型、Evidence、Query Family、用户记忆和 outbox 的唯一权威事实源；不复制 Temporal execution history |
| 数据访问 | SQLAlchemy 2 Async + `asyncpg` dialect/driver | Adopt | 一个 async engine/连接池；Repository 之外不得暴露 Session、engine、driver connection |
| Schema migration | Alembic | Adopt | DDL 和数据迁移的唯一版本权威；生产启动不得以 `CREATE TABLE IF NOT EXISTS` 代替 migration |
| 运行态与事件 | Redis 7.4 + redis-py `redis.asyncio` | Adopt | 会话热窗口最多 20 条/TTL 24h；SSE Streams TTL 1h/`MAXLEN 1000`；不得成为任务/锁/租约或业务事实权威 |
| Embedding/向量检索 | BAAI BGE-M3 `profile_v1` + pgvector | Adopt | 固定 1024 维、cosine、归一化；embedding 是可重建派生数据，模型 revision/profile 必须随向量记录 |
| 对象存储 | S3 API + boto3 adapter；本地 MinIO | Adopt | 核心只依赖 `ObjectStore` port；MinIO 是本地 S3 实现，不泄漏专属 SDK 类型 |
| 可观测性 | OpenTelemetry + Prometheus client | Adopt | OTel 负责 trace/context，Prometheus 负责稳定指标；禁止采集凭据和私有记忆值 |
| 外部工具协议 | 官方 MCP Python SDK | Adopt as external adapter | 仅用于外部 MCP transport/interop；内部继续使用版本化 `ToolGateway` 合同 |
| Python/toolchain | CPython 3.12 + uv + committed `uv.lock` | Adopt | CI/镜像使用 `uv sync --frozen`；依赖变化必须显式更新并评审 lockfile |

## 1. Agent 与多 Provider

### 1.1 Pydantic AI V2 是唯一 Agent runtime

采用 Pydantic AI V2 的稳定核心 API，承载 typed model request、structured output、typed tool、usage limit、stream 和 provider adapter。使用 `pydantic-ai>=2,<3` 的兼容范围，在 `uv.lock` 中锁定实际部署版本。

约束如下：

- `ResearchCoordinator` 是 `ResearchTask`、`TaskEvent`、研究阶段、预算、停止条件和 `task_progress_projection` 的唯一业务状态写入者；该投影不是 executable checkpoint。
- Pydantic AI 通过官方 Temporal durable execution integration 在 Coordinator/Workflow 边界执行受控 model/tool loop，每次模型请求和工具调用映射为 Activity；普通 Pydantic AI loop 不得直接运行在 Workflow sandbox 中。确定性采集、证据验证、评分、刷新 workflow identity 和条件发布仍由普通服务或 Temporal Activity 完成。
- Domain Pack 提供 schema、policy、prompt fragment 和 allow-list，不创建 Agent、Runner、graph 或 provider client。
- 内部合同使用项目自有的 Pydantic DTO。不得把 Pydantic AI message、result、tool 或 provider 类型持久化为长期 wire/schema 合同。
- 首个实现阶段不采用 `pydantic_graph`、beta module 或 0.x `pydantic-ai-harness`；需要图控制流时先证明普通 Python/Temporal Workflow 无法清晰表达，再单独裁决。
- 多 Provider 直接通过 Pydantic AI model/provider adapters 实现。模型按逻辑角色配置，例如 `intent_extractor`、`evidence_analyzer`、`research_planner`、`summarizer` 和 `embedding`，不得在领域代码写死供应商。
- SiliconFlow 等 OpenAI-compatible endpoint 通过 provider adapter 接入；每个可上线组合必须通过 structured output、tool call、stream、timeout、usage 和 error taxonomy contract tests。
- fallback 只可发生在相同 capability profile 内。缺少 structured output、tool calling 或数据驻留要求的候选不得被静默选中。

### 1.2 非核心 Agent/路由依赖

以下方案不进入目标核心依赖：

| 方案 | 裁决 | 允许范围 |
|---|---|---|
| LangChain Agent | Not adopted | 不新增 `create_agent` 或 Agent runtime 使用 |
| LangGraph | Not adopted | 不承担任务状态、checkpoint、记忆或 durable execution |
| OpenAI Agents SDK | Not adopted as core | 仅在未来确需 OpenAI 专属能力时通过隔离 adapter 评估 |
| LiteLLM SDK | Not adopted | 不在进程内导入；未来可把独立 LiteLLM Proxy 当作透明上游，但不得改变 `ModelGateway` 合同 |
| 现有 LangChain/`langchain-openai` | Migration adapter only | 只允许在 legacy `LLMService` 兼容适配器中存在；新核心代码不得新增导入 |

Pydantic AI V2 的 provider 能力已经覆盖当前多 Provider 目标，首阶段额外叠加 LiteLLM SDK 只会产生第二套路由、重试、错误映射和 usage 语义。

## 2. Durable Workflow 与任务所有权

Temporal 是 Research、Refresh 和 Media 的唯一 durable workflow/worker 主引擎。

- Workflow 只包含确定性控制流、timer、retry policy、signal、query、cancel 和版本迁移逻辑。
- 网络、LLM、Connector、数据库外部副作用和对象存储访问必须位于 Activity。
- Temporal history 是唯一 executable checkpoint。PostgreSQL 的 `task_progress_projection` 只供业务查询，不能驱动 replay；两者按 `workflow_id/run_id` 对账，terminal 只能在 PostgreSQL 业务结果提交后发布。
- `workflow_id`、业务幂等键、`ResearchTask.id` 和外部请求幂等键分别建模，不以随机 UUID 掩盖重复提交。
- Activity retry 与 Connector 内部 retry 必须有单一总预算；禁止无界嵌套重试。
- Worker 崩溃、Activity timeout、取消竞争、重复 delivery、重试耗尽和 workflow version upgrade 必须进入 failure-injection suite。
- Temporal history 是执行恢复依据，不替代 PostgreSQL 业务事实、Evidence 版本或用户记忆。
- 本地开发使用官方 Temporal dev server/Test Server；生产使用明确版本的 Temporal Service 和独立 worker 进程。

ARQ 和 Celery 不作为 fallback 或“轻量任务”旁路。短时任务也通过普通请求内协程或 Temporal Activity 表达，避免两套投递、重试和运维语义。

## 3. PostgreSQL、Repository 与迁移

### 3.1 PostgreSQL 16 是唯一事实源

PostgreSQL 16 持有：

- ResearchTask 稳定业务读模型、幂等请求和 transactional outbox；Temporal 单独拥有 execution history、timer、retry、cancel 和恢复位置。
- Canonical Query、Query Family、Evidence、不可变 Bundle、current pointer、特征和公共评分。
- 会话记录、四层用户记忆、偏好快照、来源事件、同意/过期/纠正/导出/删除状态。
- Connector/refresh 水位、对象元数据、审计引用和 schema/version metadata。

Redis、Temporal history、对象存储、向量索引和模型 provider 均不得成为上述事实的唯一副本。

### 3.2 SQLAlchemy 2 Async + asyncpg

- 新 Repository 使用 SQLAlchemy 2 的 async API，通过 `postgresql+asyncpg://` dialect 建立唯一 async engine 和 pool。
- 一个 use case 的事务由调用方拥有的 unit-of-work/`AsyncSession` 明确控制；Repository 不得自行提交跨仓储事务。
- Core/ORM 可按模型复杂度选择，但 schema、事务和查询必须位于 Foundation adapter；业务模块只依赖 Repository port。
- 现有 raw asyncpg 代码先包入 legacy adapter，再按里程碑迁移。迁移期间不得为同一写模型同时维护 SQLAlchemy pool 与第二个裸 asyncpg pool。
- 不采用 `psycopg2-binary` 作为异步生产路径。
- PostgreSQL 不可用时不得发布新 Bundle、持久记忆或成功终态；只读陈旧 Bundle 是否开放由 use-case 合同明确决定。

### 3.3 Alembic 是唯一迁移机制

- 所有新表、列、约束、索引和 extension 通过 Alembic revision 交付。
- 使用 expand/migrate/contract 顺序，确保 N-1 读兼容、失败可重跑、部署可回退。
- 应用启动只检查 revision 和依赖 extension，不隐式修改 schema。
- `scripts/init_db.sql` 最终只负责数据库/extension bootstrap；业务 DDL 迁入 Alembic。

## 4. Redis 7.4 运行态基线

Redis 固定以 7.4 作为兼容基线，Python 统一使用 redis-py 的 `redis.asyncio` API。

允许用途：

- 短期会话上下文和热点 Query Family 的 cache-aside 缓存。
- 每个会话最多最近 20 条、TTL 24 小时的热上下文；淘汰不删除 PostgreSQL 会话事实。
- TTL 1 小时且 `MAXLEN 1000` 的 SSE/EventBus Redis Streams、游标和短期 replay；窗口外返回 `replay_expired/resync` 与权威任务快照/终态。
- 速率限制、短生命周期幂等窗口和可丢失的 worker 协调信号。
- 可从 PostgreSQL、Temporal 或确定性计算重建的运行态投影。

禁止用途：

- 用户偏好、Evidence、Bundle current pointer、任务成功状态或 checkpoint 的唯一权威副本。
- 在 async request/worker 路径调用同步 redis client。
- 生产环境 Redis 故障时静默切换到进程内 dict；进程内实现仅用于 unit test 和显式单进程本地 profile。
- 把 Redis Streams 当成 Temporal 的第二套 durable job queue。
- 使用 Redis lock、lease 或 Redlock 承担 Research/Refresh/Media 的 single-flight；这些语义由 Temporal Workflow ID 承担。

Redis 不可用时，已启动 Workflow 继续且已提交结果仍可读；新的实时研究或 SSE 请求固定返回稳定 `dependency-unavailable`。Redis 恢复后从 PostgreSQL/Temporal 权威状态重建热投影。

持久事实先在 PostgreSQL 事务中写入事实记录与 outbox，再异步失效或填充 Redis。现有“先写 Redis，再 `asyncio.create_task` 写 PostgreSQL”的行为仅作为迁移期 characterization，不是目标写入语义。

## 5. Embedding 与检索

BGE-M3 `profile_v1` 是批准的默认 embedding profile，固定为 1024 维、cosine 距离和归一化向量；pgvector 是唯一向量索引实现。第一阶段不引入独立向量数据库或 Redis Vector。

- BGE-M3 用于中文/多语言 Query Family 候选召回、Evidence/实体检索和经批准的长期记忆语义召回。
- 每条 embedding 必须记录 `model_id`、精确 revision、profile version、1024 维、cosine、归一化方式、输入规范版本和生成时间；模型升级写入新 profile/物理索引，不原地混用向量空间。
- embedding 是可重建派生物。原始文本、来源、权限和业务事实仍在 PostgreSQL 规范表中。
- Query Family 匹配顺序固定为：确定性 canonical key -> PostgreSQL `pg_trgm`/结构过滤 -> 当前两级无法达到已批准置信度时使用 BGE-M3 + pgvector 候选召回 -> 领域阈值/必要时 rerank。
- 在召回率、误合并率、P95 延迟和索引规模基准通过前，使用精确向量扫描或保守索引；HNSW/IVFFlat 参数由数据基准决定。
- 公共 Evidence 与用户私有记忆必须使用独立表/namespace 和强制用户过滤，不能依靠向量相似度实现访问隔离。

Mem0 和 Zep 不进入核心：四层记忆、冲突优先级、来源审计、用户隔离和删除语义由本项目的 Personalization 合同拥有。第三方记忆引擎会再引入一套抽取、写入、召回和数据权威，且 Zep Community Edition 已停止支持。未来仅可在 `MemoryRepository`/`MemoryRetriever` port 后进行非权威实验。

## 6. 对象存储

对象存储合同采用 S3 API，Python adapter 使用 boto3；本地和集成测试使用 MinIO。

- 领域和 Orchestrator 只接触版本化 `ObjectStore` port、`ObjectRef` 和受控 signed URL，不接触 boto3/MinIO 类型。
- boto3 的同步网络调用在 async 服务中必须放入有界线程池，或在 Temporal 的同步 Activity 中执行，不得阻塞 event loop。
- bucket、key、content hash、media type、size、encryption metadata、retention 和 provenance 保存在 PostgreSQL；二进制只在对象存储。
- 服务端加密、最小权限凭据、私有 bucket、signed URL、multipart 清理和 orphan reconciliation 由明确运维策略配置并纳入合同测试；具体保留期和 URL 时限不写入存储端口。
- MinIO 只验证 S3 合同；生产可替换任意满足已批准 S3 contract suite 的实现。

## 7. 可观测性

采用 OpenTelemetry 作为统一 trace/context 机制，保留 Prometheus client 和 `/metrics` 作为指标合同。

- trace correlation 至少包含脱敏后的 `task_id`、`family_id`、`bundle_version`、`workflow_id`、`pack_id/version`、provider/model 和 connector id。
- FastAPI、httpx、SQLAlchemy、redis-py、Temporal、Pydantic AI 与 boto3 instrumentation 在 Composition Root 配置，业务模块不直接初始化 exporter。
- Prometheus 指标名称、label 和 bucket 先做兼容快照；禁止把 user id、query 文本、URL、异常正文等高基数或敏感值作为 label。
- OTel exporter 不可用不得阻断业务；buffer、sampling 和 backpressure 必须有界。
- 日志、trace、metric 均不得记录 API key、cookie、原始私有偏好、完整 prompt 或未脱敏工具结果。

## 8. MCP 边界

官方 MCP Python SDK 只用于外部 MCP client/server transport 与协议互操作。

- 内部 Agent 和业务模块依赖项目自有 `ToolGateway`、版本化 tool schema、`ToolResult`、错误分类、预算和授权合同。
- MCP request/response/content block 在 adapter 边界转换，不泄漏到 Domain Pack、Evidence、Decision 或持久 schema。
- 外部 tool 必须经过 allow-list、主体授权、timeout、size limit、结果验证、审计和 provenance 包装。
- 现有内部 `MCPToolProvider` 名称可由 compatibility adapter 保留，但不把当前自研协议与外部 MCP transport 混为同一所有权层。

## 9. Python 与依赖供应链

CPython 3.12.x 是首个 blocking runtime。项目声明在首阶段约束为 `>=3.12,<3.13`；扩展到更新 Python 版本必须先通过全量 contract、native dependency 和容器矩阵。

- 使用 uv 管理项目环境和解析，提交根目录 `uv.lock`。
- CI、Docker 和发布构建执行 `uv sync --frozen`；禁止发布时重新求解依赖。
- `pyproject.toml` 表达直接依赖和兼容范围，`uv.lock` 表达审计过的完整传递依赖。
- Dependabot/Renovate 或人工升级 PR 必须包含 lockfile diff、release note 审查、许可证/安全检查和相关 contract suite。
- Pydantic AI、Temporal、SQLAlchemy、Alembic、redis-py、BGE-M3 runtime、pgvector、boto3、OTel、Prometheus 和 MCP SDK 各指定升级 owner；不得静默跨 major。

## 10. 明确不进入核心的依赖

| 依赖 | 状态 | 原因与退出/重审条件 |
|---|---|---|
| ARQ | Not adopted | maintenance-only，且与 Temporal 重复任务投递和恢复语义 |
| Celery | Not adopted | 与 asyncio-first/Temporal 基线重复 broker、worker、retry 和运维模型 |
| LangGraph | Not adopted | 与 Coordinator/Temporal 重复状态机和 checkpoint 所有权 |
| LangChain Agent | Not adopted | 建立在 LangGraph runtime 上，超出 typed model/tool loop 所需能力 |
| OpenAI Agents SDK | Not adopted as core | OpenAI 能力优先且多 Provider 能力不对称；仅可在隔离 adapter 中重审 |
| Mem0 | Not adopted | 重复本项目记忆抽取、存储、召回和审计语义 |
| Zep | Not adopted | opinionated 外部记忆/知识图谱；Community Edition 已 deprecated |
| LiteLLM SDK | Not adopted | Pydantic AI 已提供 provider adapters；避免第二套路由、重试和 usage 语义 |
| 现有 LangChain | Migration adapter only | 保持旧行为用于 characterization；完成 Pydantic AI differential tests 后删除 |
| 独立向量数据库 | Not adopted | PostgreSQL 16 + pgvector 已满足首阶段，未出现独立扩容证据 |
| Redis 作为向量/事实库 | Not adopted | 避免与 PostgreSQL 形成第二数据权威 |

## 11. 实施顺序与验收门槛

1. 先把现有 LangChain、raw asyncpg、同步 Redis 和进程内任务包入 legacy ports，冻结当前行为。
2. 建立 Python 3.12/uv lock、Composition Root、Pydantic AI `ModelGateway` 和 provider contract tests。
3. 引入 SQLAlchemy async engine 与 Alembic，仅做 expand migration；迁移 Repository 时保持单写权威。
4. 将 Redis adapter 改为 `redis.asyncio`，建立 cache/outbox 和 EventBus contract，生产禁用进程内 fallback。
5. 以 Temporal 承接 Research lifecycle，再分别接入 Refresh/Media；每次迁移都做 crash/retry/cancel/replay 演练。
6. 以版本化 pipeline 生成 BGE-M3 embedding，并在 pgvector shadow index 上做召回/延迟基准后启用读取。
7. 接入 S3 `ObjectStore` adapter、本地 MinIO、OTel tracing 和 MCP external adapter。
8. 每个里程碑必须可独立提交、部署观察、关闭开关和回绑 legacy adapter；不得一次替换 Agent、数据库、任务和记忆全部路径。

基础设施实现的统一准入条件：contract suite 通过、failure injection 通过、旧 wire/DTO 无未批准变化、迁移可回滚、无双事实源、无第二套 durable runtime、无 provider/framework 类型越过 adapter。

## 官方一手资料

### 已采用

- [Pydantic AI](https://pydantic.dev/docs/ai/overview/)；[V2 version policy](https://pydantic.dev/docs/ai/project/version-policy/)；[model providers](https://pydantic.dev/docs/ai/models/overview/)；[Temporal durable execution integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/)
- [Temporal Python SDK](https://docs.temporal.io/develop/python)；[Event History](https://docs.temporal.io/encyclopedia/event-history)；[Temporal Python SDK source](https://github.com/temporalio/sdk-python)
- [PostgreSQL 16 documentation](https://www.postgresql.org/docs/16/)；[`pg_trgm`](https://www.postgresql.org/docs/16/pgtrgm.html)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)；[asyncpg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg)
- [Alembic](https://alembic.sqlalchemy.org/en/latest/)
- [Redis 7.4 release notes](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisce-7.4-release-notes/)；[redis-py asyncio examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)；[Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)
- [BAAI BGE-M3 model](https://huggingface.co/BAAI/bge-m3)；[BGE-M3 paper](https://arxiv.org/abs/2402.03216)
- [pgvector](https://github.com/pgvector/pgvector)；[pgvector-python](https://github.com/pgvector/pgvector-python)
- [Amazon S3 API reference](https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html)；[Boto3 S3 guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html)；[MinIO documentation](https://min.io/docs/minio/container/index.html)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/)；[Prometheus Python client](https://prometheus.github.io/client_python/)
- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)；[official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Python 3.12 documentation](https://docs.python.org/3.12/)；[uv projects](https://docs.astral.sh/uv/concepts/projects/)；[uv lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile)

### 未采用或仅迁移兼容

- [ARQ repository](https://github.com/python-arq/arq)
- [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [Mem0 OSS](https://docs.mem0.ai/open-source/overview)
- [Zep repository and Community Edition status](https://github.com/getzep/zep)
- [LiteLLM documentation](https://docs.litellm.ai/)
