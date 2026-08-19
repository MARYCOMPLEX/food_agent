## Context

动机见 [proposal.md](./proposal.md)。本设计把目标描述、交互式 HTML、Draw.io 对照图和当前仓库实现转换为可实施的架构边界；四份 delta spec 是目标行为的规范来源。

### 设计输入

| 输入 | 用途 | 状态 |
|---|---|---|
| 目标描述 | 七个模块、Query Family、持续刷新、四层记忆、Domain Pack 和六个绿色扩展点的规范来源 | 本 change 的主要输入 |
| [food-agent-unified-architecture.html](./references/food-agent-unified-architecture.html) | 总览与各模块内部交互的详细模型 | 已复制到 change 并纳入版本控制 |
| [food-agent-extensible-evidence-architecture.drawio](./references/food-agent-extensible-evidence-architecture.drawio) | 可编辑对照图、端口和媒体管线细节 | 已复制到 change 并纳入版本控制 |
| 当前代码与测试 | 迁移前 characterization 和兼容性事实来源 | 不是目标边界的模板 |
| README 和前端类型 | 已声明或被客户端假定的合同来源 | 与当前后端存在多处不一致，需先判定权威性 |

规范、设计、代码事实和图示之间的权威顺序，以及两份引用文件的 SHA-256，记录在 [ADR-0001](./decisions/ADR-0001-specification-authority.md)。外部 visualization 路径不再是评审依赖。

依赖复用调研和最终裁决记录在 [dependency-research.md](./dependency-research.md) 与 [ADR-0002](./decisions/ADR-0002-infrastructure-baseline.md)。本文 `Decisions` 是实现选型的规范权威；调研文件负责保存候选比较、官方资料和被拒方案，不得覆盖本文裁决。

### 当前状态与约束

- 当前主链为 `FastAPI -> search state/tasks -> XHSFoodOrchestrator -> SearchExecutor/FollowUpHandler -> MCP registry -> XHS providers -> spider`。
- 分析链为 `Orchestrator -> Analyzer -> preprocessing/scoring`；POI 链仍可越过公开仓储端口访问 Amap 和存储内部状态。
- 后台研究任务由进程内 `asyncio.create_task` 启动；Redis EventBus 可重放事件，但不存在持久刷新队列、Query Family、Freshness Gate、Evidence Bundle、来源链或 Domain Contract。
- Food 语义分散在意图、提示词、四阶段关键词、分析、评分、DTO、SSE 步骤和前端组件中，无法只通过切换 Connector 增加 Travel。
- `ConversationContext`、会话存储、用户设置、收藏和历史提供了记忆原料，但长期偏好尚未形成隔离的研究策略和最终重排能力。
- Redis、PostgreSQL、EventBus 和状态存储存在当前降级语义；目标生产模式已确定 PostgreSQL 为业务事实权威、Temporal 为任务执行历史权威、Redis 为可重建热状态，并通过版本化行为里程碑退出生产内存 fallback。
- 当前 API、README 和前端类型不是完全一致的合同。结构迁移不得顺便选择或修复任一侧；先用双侧 characterization 记录，再由独立决策确定目标合同。
- 本 change 只建立规范、设计和验证基线，不修改生产代码、数据或部署。

## Goals / Non-Goals

**Goals:**

- 给每项当前职责指定唯一目标所有者，并为七个模块定义可自动检查的依赖方向和禁止依赖。
- 用端口、Gateway、注册表和 Composition Root 隔离共享核心、领域语义、平台访问和基础设施。
- 定义公共 Query Family、版本化 Evidence Bundle、用户记忆和 Domain Pack 的关键合同及数据所有权。
- 明确所有现有兼容面，以及存在冲突时的“先 characterization、后选择”规则。
- 把纯结构迁移与行为启用拆成独立阶段；每个里程碑均可独立测试、提交、部署观察和回退。
- 提供 characterization、contract、failure-injection 和跨平台测试矩阵作为实施准入门槛。

**Non-Goals:**

- 本阶段不创建目标包、不迁移数据库、不引入队列或对象存储、不修复前后端合同差异，也不启用 Query Family、个性化或 Travel。
- 不在本设计中选定相似度业务阈值、具体表字段、内容保留期限或个性化权重；基础设施产品、运行时边界和迁移权威已经确定。
- 不重新设计 UI，不改变既有推荐文案或排名业务阈值，不删除当前 Python 导出、环境变量或兼容入口。
- 不把交互图中未被本文确认的产品名升级为承诺；当图与本文冲突时，本文已接受的技术决策优先，图需随后同步。

## Current Responsibility Mapping

| 当前职责或组件 | 当前代码位置 | 目标模块 | 迁移边界与已知缺口 |
|---|---|---|---|
| 浏览器页面、路由、HTTP 客户端 | `frontend/src/App.tsx`、`frontend/src/api/*`、`frontend/src/components/views/*` | 体验与任务（客户端适配器） | 只消费版本化任务/结果 DTO；Food 卡片与建议迁入 Food 展示适配器。当前前端响应假设与后端不一致，必须先快照。 |
| 浏览器搜索状态与 SSE 状态机 | `frontend/src/stores/searchStore.ts` | 体验与任务 | 映射稳定任务事件；不得写死 `xhs_search`、评论和 POI 等平台步骤。当前 step ID、重放参数和 payload 字段与后端不一致。 |
| FastAPI 生命周期、中间件和路由装配 | `src/api/main.py`、`src/api/deps.py` | 体验与任务 + Composition Root | FastAPI 只做传输、身份、DTO 和用例调用；具体实例装配移至组合根。 |
| 搜索入口、状态、后台任务和恢复 | `src/api/search/routes.py`、`state.py`、`tasks.py` | 体验与任务 / ResearchTaskService | 先由兼容 facade 包住现有实现；不得保留对 `orchestrator._context` 的私有访问。 |
| SSE 类型、总线和 emitter | `src/xhs_food/events/*` | 体验与任务的 Stable Event Mapper + Foundation EventBus adapter | 稳定事件模式与总线实现分离；事件 ID、重放和终态必须保持已批准合同。 |
| 主编排与追问 | `src/xhs_food/orchestrator/core.py`、`follow_up.py` | Research Orchestrator | 抽取 ResearchCoordinator、计划、预算、停止条件与业务进度投影；领域提示词和 Food 决策移出。 |
| 四阶段搜索、采集、合并、过滤和排序 | `src/xhs_food/orchestrator/search_executor.py` | Research Orchestrator + Evidence Intelligence + Knowledge & Decision + Food Pack | 先 characterization，再按职责逐段委派；不能一次性重写。 |
| 意图解析 | `src/xhs_food/agents/intent_parser.py`、相关 prompts | Research Orchestrator 的 Canonical Query 输入 + Food Pack | 通用语义归一与 Food 字段定义分离；保持当前 `FoodSearchIntent` facade。 |
| MCP 工具注册与结果信封 | `src/xhs_food/protocols/mcp.py`、`di/factories.py` | Tool Gateway / Composition Root | 保留 `MCPToolProvider`、`ToolResult` 和现有注册名的兼容适配器；核心不直接解析具体工具内部数据。 |
| XHS provider、service 和 API | `src/xhs_food/providers/xhs_providers.py`、`spider/**` | Evidence Intelligence 的 XHS SourceConnector + Foundation 平台适配器 | 平台字段在 Connector 内终止；失败必须与“真实空结果”区分。 |
| 评论预处理、分析和评分 | `agents/analyzer.py`、`services/preprocessing.py`、`services/scoring.py` | Knowledge & Decision + Food Pack | 通用 Evidence/Feature 管线与 Food 有效性、网红识别和评分策略分离。 |
| POI 搜索与补充 | `agents/poi_enricher.py`、`poi_search.py`、`spider/apis/amap_api.py` | Evidence Intelligence 的 Place Connector + Food Pack tool/feature | 通过 Source/Tool Gateway；禁止访问 `UserStorage._pool` 等内部实现。 |
| 会话上下文 | `schemas/ConversationContext`、`SessionManager` | Personalization 的 Session Memory + Research Orchestrator 业务进度投影 | 当前公开方法和多轮语义由 facade 保持；公共证据不得包含会话结果对象。 |
| Redis/PostgreSQL 会话实现 | `services/redis_memory.py`、`postgres_storage.py` | Foundation repository/cache adapters | 通过 Repository/Cache ports；PostgreSQL 迁为权威，Redis 只保留最近 20 条/24 小时热窗口，旧降级只作 characterization。 |
| 用户、收藏、历史和搜索结果 | `api/user.py`、`favorites.py`、`history.py`、`services/user_storage/**` | Personalization/Profile + 体验与任务查询服务 + Foundation repositories | 用户私有数据与公共 Evidence 拆库/拆表语义隔离；保留现有 ID 和读兼容。 |
| Food 实体、输出和领域提示词 | `schemas/*`、`prompts/*`、四阶段关键词及前端餐厅类型 | Food Pack | 注册 `Domain Contract`；通过旧 DTO/renderer adapter 保持兼容。 |
| 配置、LLM、认证、指标 | `config.py`、`services/llm_service.py`、`auth/**`、`observability/**` | Foundation + Composition Root | 保留配置 facade、多 LLM 和认证资料格式；业务模块只依赖端口。 |
| Redis EventBus、状态缓存、PostgreSQL、pgvector、容器 | `events/bus.py`、`api/search/state.py`、存储服务、Docker/Compose | Foundation | Redis 仅可重建运行态，PostgreSQL 为目标权威事实，对象存储只存二进制；现有可选降级冲突在行为切换前解决。 |

## Structure And Behavior Separation

### Structural changes

以下调整不得改变外部结果、事件、排序、持久化副作用或降级行为：

| 结构项 | 内容 | 证明方式 |
|---|---|---|
| 合同层 | 增加纯类型/协议、错误分类和版本标识 | 导入边界测试、旧接口适配器 contract test |
| Composition Root | 集中创建并注册 Orchestrator、Gateway、Pack 和 adapters | 相同依赖夹具下 characterization 全等 |
| 体验 facade | FastAPI/SSE 通过用例端口，仍委派旧工作流 | HTTP/SSE golden tests 全等 |
| Connector facade | 现有 MCP/XHS/Amap 包在 Source/Tool Gateway 后 | provider 调用序列、参数和结果全等 |
| Food Pack facade | 把既有 Food 类型、提示词、评分和输出放入领域边界，仍调用旧逻辑 | 固定夹具下关键词、候选、过滤、排序、DTO 全等 |
| Repository facade | 私有 pool/Redis 访问封装为端口，底层 schema 暂不变 | 读写、TTL、错误和 fallback characterization 全等 |
| 架构检查 | 禁止跨层导入和私有属性访问 | 静态测试阻断新增违规 |

### Behavioral changes

以下每项都必须在结构阶段完成后单独启用，并有独立开关、验收和回滚：

| 行为项 | 新行为 | 不得混入的顺手修改 |
|---|---|---|
| Query Family | 公共语义匹配、公共/个人约束分类、in-flight 合并、新鲜度三态选择 | 前后端 envelope/路由修复、评分调参 |
| Evidence 生命周期 | 标准 Evidence、不可变 Bundle、原子激活、派生重算 | 旧 DTO 字段重命名、旧数据删除 |
| 个性化 | 四层记忆、优先级、策略和最终重排 | 公共评分重写、Family 主键加入用户信息 |
| 持续刷新 | 后台优先级、增量刷新、失败后陈旧读取 | 改变同步搜索错误语义 |
| 显式刷新 | 用户请求复用同一 Family 和活动刷新，以稳定任务事件报告普通/强制刷新 | 把未实现的 refresh 当作既有兼容合同，或顺带增加未规范的外部 cancel API |
| 媒体派生 | 引用选择、对象存储、处理器和 Extractor | 将原始媒体放入 Redis/PostgreSQL JSON/SSE/提示词 |
| 新领域 | Travel Pack 和新输出模式 | 复制 runtime、队列、证据库或记忆系统 |
| 现有合同纠错 | 选择并统一 API/SSE/前端的一侧 | 任何模块移动或 Query Family 启用；需另立兼容 change |

行为开关关闭时，新结构 MUST 委派当前实现并通过 characterization；结构提交不得以“最终会改变”为理由接受当前差异。

## Decisions

### Decision 1: 一个共享核心加领域 Pack

采用 `通用研究骨架 + Food Pack + Travel Pack + 后续 Domain Pack`。任务、Agent Runtime、Query Family、Evidence Library、Refresh Coordinator、Personalization、队列和存储只有一套。

**Rationale:** 公共证据、并发控制、恢复和用户记忆跨领域具有相同生命周期；复制会造成事实、任务和策略分叉。

**Alternatives considered:**

- Food/Travel 各自建设整套系统：短期边界简单，但证据、刷新、身份、队列和运维重复，拒绝。
- 仅切换 Connector：只能解决“去哪取”，不能表达实体、有效证据、特征、评分和输出差异，拒绝。

### Decision 2: 端口与适配器，只有 Composition Root 见到具体实现

核心模块依赖调用方拥有的协议和领域中立值对象。Connector、Repository、EventBus、ObjectStore、LLM provider、Domain Pack 和工具实现通过注册表装配；只有 Composition Root 可同时导入合同和具体实现。

**Rationale:** 图中的运行时箭头不能成为源码直接依赖；集中装配使失败替换、测试和回滚可控。

**Alternatives considered:**

- 全局 service locator：隐藏依赖且容易跨越模块，拒绝。
- 让 Orchestrator 直接导入 XHS/Amap/数据库：延续当前耦合，阻止跨领域复用，拒绝。

### Decision 2a: Agent loop 与任务状态的唯一所有者

每个研究任务只允许由 Research Orchestrator 持有一个 Pydantic AI V2 runtime 实例。只使用 `pydantic-ai>=2,<3` 的稳定核心 API、typed dependencies、typed tools 和 typed outputs；精确版本由 `uv.lock` 固定。Agent 只能通过版本化 typed Tool Gateway 请求能力；它不得直接创建后台队列、访问 Connector/Repository，或把领域 Pack 当成第二个 Agent runtime。确定性采集、证据校验、特征计算、评分、刷新所有权和恢复状态由普通服务/Coordinator 负责。每个任务的 `ResearchCoordinator` 是 `ResearchTask`/`TaskEvent` 状态的唯一写入者；体验层只做请求和事件投影，Foundation 只持久化/投递，不拥有业务状态迁移。

**Rationale:** 图中“单一 Agent + typed tool calls”的语义需要一个明确边界，否则每个 Domain Pack 或 LangGraph 节点都可能隐式形成第二套编排器；任务状态若有多个写入者则无法保证恢复、终态和回滚的一致性。

**Implementation choice:** Pydantic AI V2 是唯一 Agent/LLM runtime，并通过其官方 Temporal durable execution integration 接入 Research Workflow；模型请求和工具调用由 integration 转换为可重试 Activity，普通 Pydantic AI loop 不得直接运行在 Workflow sandbox 中。现有 LangChain 只作为迁移期 `LLMService` adapter，完成 provider contract 后移除；OpenAI Agents SDK、LangGraph、LangChain Agent、Pydantic Graph/Harness 和多 Agent handoff 不进入首阶段运行时。将来替换框架只能实现内部 `AgentRuntime`/`ModelGateway` ports，并通过独立 OpenSpec change 和完整合同测试。

### Decision 3: 公共研究与私有个性化在数据和计算上分离

Canonical Query、Query Family、Evidence、实体、公共特征和公共评分不含用户身份或偏好。Domain Contract 的版本化分类器先把输入约束投影为公共 `constraints` 或私有 Personalization 输入；未分类约束不得进入共享 identity。用户记忆生成独立策略快照，只在规划参数、硬过滤和最终重排处生效。

**Rationale:** 这是复用相似查询且避免隐私泄漏的前提。

**Alternatives considered:**

- 把偏好写入 Query Family key：会切碎公共证据并造成重复平台请求，拒绝。
- 为每个用户复制 Evidence Bundle：成本高、来源事实分叉且难以纠错，拒绝。

### Decision 4: Query Family 是版本化匹配结果，不是裸文本或单一向量命中

入口先生成带 schema 版本的 Canonical Query；Family Index 同时支持确定性规范键和可解释的相似匹配。匹配需保存规则版本、置信度和理由，低置信度不自动合并。`audience` 等字段的精确身份/相似匹配权重尚待 Open Question 决定。

**Rationale:** 仅字符串 key 不能覆盖示例中的语义相近问法；仅向量阈值又不可审计且容易误合并。

**Alternatives considered:**

- 只使用所有字段的哈希：确定但无法归并近义查询，拒绝。
- 只使用 embedding 最近邻：不可稳定复现且边界不清，拒绝。

### Decision 5: Evidence Bundle 不可变并原子激活

刷新先创建候选 Bundle，完成证据验证、来源链校验、特征重算和索引构建后，再以单个权威事务更新 Family 的当前版本指针。旧版本保持只读，可用于追溯、比较和指针回滚。

**Rationale:** 原地覆盖会让并发读者看到证据和评分不一致，也无法安全回退。

**Alternatives considered:**

- 原地更新证据行：写放大较低，但无一致快照，拒绝。
- Redis 缓存结果作为权威：不可追溯且无法承载长期事实，拒绝。

### Decision 6: PostgreSQL、Temporal、Redis 和 ObjectStore 各有唯一权威边界

PostgreSQL 16 保存 Query Family、Evidence、Provenance、Bundle 版本指针、会话消息、用户记忆、稳定任务读模型和 outbox；Temporal 保存 workflow history、timer、retry、cancel、Task Queue、Workflow ID 幂等和执行恢复；Redis 7.4 只保存最近 20 条/24 小时会话窗口、1 小时且 `MAXLEN 1000` 的 SSE replay、热点缓存、短期幂等窗口和限流；S3-compatible ObjectStore 只保存原始媒体与派生二进制，通过 PostgreSQL MediaAsset 元数据引用。Temporal history 是唯一 executable checkpoint；PostgreSQL 的 `task_progress_projection` 只用于业务查询，不得驱动 Workflow replay。PG/Temporal 不一致时，reconciler 按 `workflow_id/run_id` 对账，且只有 PostgreSQL 业务结果提交成功后才能发布 terminal。记忆和消息的写入顺序固定为 `PostgreSQL transaction + outbox -> commit -> Redis invalidate/warm`。

生产研究模式要求 PostgreSQL、Temporal 和 Redis 可用。PostgreSQL 不可用时不得确认新事实或成功终态；Redis 不可用时已运行 Temporal workflow 和已提交结果保持有效，但新实时研究或 SSE 请求必须返回稳定 `dependency-unavailable`；进程内 fallback 仅限单进程开发和测试。Redis 不承载 durable task state、任务队列、事实权威或 Redlock；刷新 single-flight 使用稳定 Temporal Workflow ID，Bundle 激活使用 PostgreSQL 条件更新。

**Rationale:** 业务事实、执行历史、热状态和二进制各有一个权威，既避免双写恢复冲突，也允许在端口后独立替换实现。

**Alternatives considered:**

- PostgreSQL/Redis 双权威：恢复冲突不可控，拒绝。
- 把二进制存入 PostgreSQL JSON 或 Redis：容量、传输和安全边界不合适，拒绝。
- 用 Redis 锁、ARQ 或进程内任务替代 durable workflow：无法提供统一历史和确定恢复，拒绝。
- 生产无 PostgreSQL/Redis 的静默降级：会虚假承诺持久与跨 worker 恢复，拒绝；只保留为 legacy characterization 和 test fixture。

### Decision 6a: SQLAlchemy/Alembic 是新持久层与迁移基线

新 repository 使用 SQLAlchemy 2 Async + asyncpg；Alembic 是唯一 schema migration authority。旧 raw asyncpg 代码只在 legacy adapter 中保留并逐仓储迁移，新代码不得同时维护运行时 `CREATE TABLE IF NOT EXISTS`、手写迁移脚本和 ORM metadata 三套 schema。事务由 use case/repository boundary 显式拥有，不能让 Redis 写入先于权威提交。

PostgreSQL 16 的 `pg_trgm` 与 pgvector 覆盖首阶段确定性 key、文本相似候选和向量候选检索，不引入独立向量数据库。Embedding profile v1 固定为 `BAAI/bge-m3`、1024 维、cosine、归一化向量，并记录 provider、model revision、profile version 和生成时间。当前 `VECTOR(4096)` 不再延续；更换维度必须新增 profile/物理索引，经双写、回填和读指针切换迁移，禁止原地改变既有向量含义。

**Rationale:** SQLAlchemy/Alembic 消除 schema 多权威；版本化 embedding profile 允许以后换模型而不破坏旧索引或把 provider 类型泄漏到领域层。

**Alternatives considered:**

- 继续以运行时自动建表为生产迁移：无法审计和可靠回退，拒绝。
- 立即引入独立向量数据库：当前规模没有证明额外运维与双权威成本，拒绝。
- 使用无版本的可变维度 embedding：无法稳定索引、比较和回填，拒绝。

### Decision 7: Domain Contract 同时约束语义、策略和能力

每个 Pack 至少声明领域标识和版本、Entity/Relation/EvidenceType、FeatureSet、ScoringPolicy、Domain Sources、allowed tools 及其 input/output schema、Agent final output schema、freshness/coverage 和停止条件。Pack 只消费标准 Evidence 和共享端口；任务启动时固定这些 schema 版本，worker 恢复不得切换到新注册版本。

**Rationale:** 只声明实体或数据源不足以保证跨领域执行和输出一致。

**Alternatives considered:**

- 继承一个包含基础设施方法的基类：让 Pack 知道数据库/队列实现，拒绝。
- 用自由格式配置表示整个 Pack：缺少静态合同和测试边界，拒绝。

### Decision 8: 兼容性由边界 mapper 和 facade 保持

内部可采用领域中立命令、事件和结果信封；FastAPI、SSE、Python public API、旧 DTO、MCP tools 和前端 renderer 前保留版本化 mapper。已存在的两侧冲突不由 mapper 随机选边，必须经过 authority gate。

**Rationale:** 内部模块化不应强迫所有客户端同步迁移。

**Alternatives considered:**

- 直接把内部模型暴露为新 API：把结构调整变成破坏性行为变化，拒绝。
- 永久维护两套核心模型：重复业务规则，拒绝；只在边界维护薄适配器。

### Decision 9: 刷新与前台研究使用独立工作负载边界

Temporal 是唯一 durable runtime。Research Job、Refresh Job 和 Media Job 使用三个独立 Temporal Task Queue、worker 配额和 activity retry policy，但共享 Workflow ID、取消、超时、版本和观测合同。刷新只能生成候选 Evidence 版本，不能绕过验证或直接修改当前指针。重试耗尽的 workflow 保留为可查询失败执行并进入人工恢复/终止流程，不再另造 broker DLQ 语义。Provider 和 Connector 的内部重试必须关闭或严格有界，避免与 Temporal activity retry 相乘。

**Rationale:** 媒体或热门刷新不能耗尽交互查询容量；独立边界便于故障注入和停用。

**Alternatives considered:**

- 全部任务共用一个无优先级队列：容易优先级反转和级联失败，拒绝。
- 定时任务直接写当前证据：绕过版本激活，拒绝。
- 同时引入 Celery、ARQ、LangGraph checkpoint 或 Redis queue：产生第二任务状态权威，拒绝。

### Decision 10: 媒体先形成资产和派生物，再提取 Evidence

Connector 只返回 MediaRef，不下载或永久保存二进制。被策略选中的引用进入幂等 Media Job，经流式验证、内容哈希去重、ObjectStore、Processor Registry 和 Evidence Extractor 后形成标准 Evidence 与完整 provenance。

ObjectStore 合同固定为 S3-compatible API，Python adapter 使用 boto3；本地 Compose 使用 MinIO，生产使用满足同一 contract suite 的 S3-compatible 服务。领域层不得依赖 MinIO/AWS 专用类型。对象键使用内容哈希与租户/可见性前缀，签名 URL、加密、保留和孤儿清理按后续运维策略配置，但不得改变端口合同。

**Rationale:** 平台访问、二进制处理和证据语义需要独立限额与失败边界。

**Alternatives considered:**

- Connector 内同步下载/分析媒体：扩大平台适配器职责并阻塞研究，拒绝。
- 将原始媒体直接交给 Agent：不可追溯且预算不可控，拒绝。

### Decision 11: Provider、协议、观测和工具链使用稳定 adapter

- Pydantic AI V2 通过内部 `ModelGateway` 按 `intent_extractor/evidence_analyzer/research_planner/summarizer/embedding` 逻辑角色选择 provider；SiliconFlow、OpenAI 和 DeepSeek 使用经过能力探测的原生或 OpenAI-compatible adapter。Domain code 不出现 provider SDK 类型，不做未记录的运行中模型切换。
- 不引入 LiteLLM SDK。只有未来出现集中网关、跨团队配额或统一计费需求时，LiteLLM Proxy 才可作为 `ModelGateway` 后的部署 adapter，由独立 change 审批。
- 官方 MCP Python SDK 只用于外部 MCP transport/interop；内部 `ToolGateway`、`ToolResult`、权限、预算和错误合同保持领域中立。
- OpenTelemetry 是 trace/correlation 标准，现有 Prometheus client 继续提供指标；不采用 Logfire 作为必需后端。task、family、bundle、pack、workflow 和 model role 使用脱敏关联标识。
- import-linter + pytest 检查依赖边界，Schemathesis/Hypothesis + OpenAPI snapshot 检查 API，Playwright 检查 SSE/browser；Python 3.12 是主运行时，`uv.lock` 固定精确依赖版本。

**Rationale:** adapter 保留 provider、协议、存储和观测后端的可替换性；单一稳定实现避免同时维护多个框架运行时。

**Alternatives considered:**

- OpenAI Agents SDK：与图示接近，但多 provider 和 Temporal 组合不如选定栈直接，拒绝作为核心。
- LangGraph/LangChain Agent：会形成第二状态机，拒绝；旧 LangChain 仅作迁移 adapter。
- ARQ：上游 maintenance-only 且无完整 workflow history，拒绝。
- Celery：成熟但不是 workflow history 引擎，且会增加第二任务运行时，拒绝。

完整证据、版本状态和比较矩阵见 [dependency-research.md](./dependency-research.md)。

## Module Dependency Direction

### Compile-time direction

```text
frontend/client adapters
        |
FastAPI + Stable Event/Result Mappers        (Experience & Tasks)
        |
Research Use-Case Ports
        |
Research Coordinator + Plan/Task Contracts  (Research Orchestrator)
       /                |                 \
Evidence Ports     Decision Ports     Personalization Ports
       |                |                 |
Domain Contract <-------+-----------------+
       |
Domain-neutral Repository / Workflow / Cache / Object / Provider Ports
       |
Composition Root wires concrete Foundation adapters and registered extensions
```

Domain Pack implementation与 Foundation adapter 是核心端口的平级插件；两者不得互相依赖。运行时的数据流可以从 Foundation 返回核心，但源码依赖始终指向合同。

### Allowed dependencies

| 模块 | 可直接依赖 | 对外提供 |
|---|---|---|
| 体验与任务 | 公共 API DTO、Research Use-Case Ports、身份端口 | HTTP/SSE/UI 适配、稳定任务状态 |
| Research Orchestrator | 通用合同、Evidence/Decision/Personalization/Domain ports | ResearchPlan、调度、预算、停止、业务进度投影 |
| Evidence Intelligence | 通用证据模型、Domain Contract 的证据声明、Source/Repository ports | Canonical Query、Family、Freshness、Evidence Bundle |
| Knowledge & Decision | 标准 Evidence、Domain Contract 的特征/评分声明、实体仓储端口 | 公共实体、特征、质量、评分和解释 |
| Personalization | 用户记忆端口、公共候选/特征只读视图、Domain 策略槽位 | Preference Snapshot、Research Strategy、最终重排 |
| Domain Pack | Domain Contract SDK、领域中立值对象 | 领域模式、验证器、策略和输出 adapter |
| Foundation | 领域中立端口与外部库 | Repository、Workflow、Cache/EventBus、ObjectStore、Provider、监控 adapters |
| Composition Root | 所有公开合同和具体实现 | 注册、生命周期和配置装配；不承载业务行为 |

### Forbidden dependencies

- 体验与任务 -> Connector、Spider、平台 SDK、数据库驱动、领域评分内部。
- Research Orchestrator -> XHS/Amap/具体 Connector、Redis/PostgreSQL/ObjectStore 客户端、Pack 私有类。
- Evidence Intelligence -> 用户私有记忆、用户结果或个性化排序。
- Knowledge & Decision -> 网络采集、平台认证、媒体下载。
- Personalization -> 公共 Evidence/公共评分写端、Connector 或其他用户记忆。
- Domain Pack -> Agent Runtime、任务队列实现、数据库驱动、平台内部、另一个 Pack 内部。
- Foundation -> Food/Travel 实体、评分规则、提示词或输出模式。
- Connector -> Agent、Domain Pack、数据库驱动、永久媒体存储或另一个 Connector 私有状态。
- Processor/Extractor -> Agent、API、任务数据库私有实现或未声明的外部网络。
- 任意模块 -> 另一个模块的下划线私有属性；当前 `orchestrator._context`、`storage._pool` 等访问必须先经 facade 消除。

架构测试必须维护允许边集合；默认拒绝未列出的跨模块依赖，并报告导入链。

## Target Contracts And Data Ownership

### Core contracts

| 合同 | 最小语义 | 所有者 |
|---|---|---|
| `ResearchRequest` | query/refine/refresh/recover operation、公共查询输入、独立身份上下文、刷新/请求策略、兼容 API 版本 | 体验与任务 |
| `CanonicalQuery` | `domain`、`geo`、`intent`、`audience`、公共 `constraints` 投影、`time_range`、`freshness_policy`、schema/classifier version；无用户偏好 | Evidence Intelligence |
| `ResearchPlan` | typed DAG；goal、steps、dependencies、status、budget、evidence refs、contract versions | Research Orchestrator |
| `ResearchTask` / `TaskEvent` | 稳定状态、`task_progress_projection`、turn、progress、terminal error；该投影不作为可执行 checkpoint，由边界 mapper 转现有 SSE | Research Orchestrator / 体验与任务 |
| `CollectRequest` | query、source scope、depth、cursor、media policy (`refs_only`/`selected`) | Evidence Intelligence |
| `SourceConnector` | `search(request)`、`fetch_document(ref)`、`fetch_comments(document_ref,cursor)`、`list_media_refs(owner_ref)`；稳定错误分类 | Evidence Intelligence port |
| `CanonicalSourceBatch` | documents、comments、authors、media refs；无二进制；每项有 source/external id、canonical URL、captured time | Evidence Intelligence |
| `SourceLocator` | source/document，optional comment/media-ref/asset，canonical URL、capture time | Evidence Intelligence |
| `EvidenceItem` | id、claim type/value/confidence、SourceLocator、optional asset、extractor/schema version、visibility | Evidence Intelligence / Domain Contract |
| `EvidenceBundle` | family/version/parent、evidence refs、coverage、watermarks、verified time、freshness、provenance、activation state | Evidence Intelligence |
| `DomainContract` | Entity、Relation、EvidenceType、FeatureSet、ScoringPolicy、ToolInputSchema、ToolOutputSchema、AgentFinalOutputSchema、sources、allowed tools、coverage、freshness、stopping | Domain Pack SDK |
| `MemoryRecord` / `PreferenceSnapshot` | layer、scope、source event、confidence、effective time、user subject、version | Personalization |
| `PersonalizationPolicy` | hard constraints、research depth/source policy、weights、explanation refs；不含公共事实副本 | Personalization |
| `RefreshJob` | family、base version、delta scope、watermarks、priority reason、stable workflow identity、idempotency key | Evidence Intelligence port |
| `MediaAsset` / `DerivedArtifact` | content hash、object ref、mime、owner/source locator、processor version、resource limits | Foundation / Evidence pipeline |
| `RecommendationView` | public score refs、personalization version、Evidence refs、Domain output payload | Knowledge & Decision + output mapper |

所有字段的精确 schema、枚举和版本协商在实现前通过合同 ADR 固化；本表只规定不可省略的语义边界。

### Data ownership

| 数据 | 权威所有者 | 允许的副本 | 禁止项 |
|---|---|---|---|
| Query Family 和签名别名 | PostgreSQL / Evidence Intelligence repository | Redis lookup cache | 用户 ID/偏好进入身份键 |
| Evidence/Provenance/Bundle 版本 | PostgreSQL | 只读索引、缓存 | 原地覆盖已发布版本 |
| 原始媒体和派生二进制 | ObjectStore | 流式临时缓冲 | Redis、关系 JSON、SSE、prompt 内嵌二进制 |
| 实体、公共特征和公共评分 | PostgreSQL / Knowledge repositories | 可重建向量或搜索索引 | 用户专属值回写公共行 |
| Workflow execution history、timer、retry、cancel | Temporal | PostgreSQL 稳定任务读模型；Redis 短期 SSE 投影 | Redis 锁/租约或第二 durable queue 成为执行权威 |
| 稳定任务状态与业务结果 | PostgreSQL / ResearchTask repository | Redis 可重建热投影 | Temporal search attributes 或 Redis 成为业务事实权威 |
| 用户记忆和策略版本 | PostgreSQL / Personalization repository | 用户隔离的短期缓存 | 跨用户 cache key、写入公共 Evidence |
| 最终用户结果 | 结果/历史 repository，引用公共版本 | 客户端/会话缓存 | 把个性化结果当公共 Bundle |

### Bundle activation protocol

1. 读取活动 Bundle 版本和来源水位，创建带幂等键的 candidate version。
2. 采集仅缺失/过期 delta，标准化并建立 provenance；单个来源失败保持独立错误状态。
3. 完成 Evidence 验证、实体消歧、公共特征/评分索引和覆盖度计算。
4. 在一个权威事务中验证 base version 未变化，标记 candidate 为 published，并切换 Family 当前指针。
5. 事务后发布版本事件；缓存和派生读模型按版本幂等更新。
6. 任一步失败均不切指针；candidate 可诊断/清理，旧 published version 保持可读。

## Compatibility Contracts

在 S0 基线完成前，“兼容”表示同时记录服务器实际行为、客户端实际假设和公开文档声明。只有 authority decision 才能把其中一项指定为迁移后的规范；结构阶段必须保持它实际代理的那一侧。

| ID | 必须保持或显式裁决的合同 | 当前证据/内容 | 验证门槛 |
|---|---|---|---|
| C-HTTP-01 | 搜索 HTTP 路由与三分支 | 实际为 `POST /v1/search/`，按 `(sessionId, query)` 分派 new/refine/recover；另有 `/stream/{sessionId}`、`/status/{sessionId}`、`/results/{sessionId}` | OpenAPI snapshot + 三分支 wire golden |
| C-HTTP-02 | 收藏/历史/用户/帮助路由 | `/v1/favorites` GET/POST/DELETE/check；`/v1/history` GET/POST/DELETE；`/v1/user` profile/stats/settings/preferences/notifications；`/v1/help/faqs|feedback` | 每一路由请求、状态码、包络和错误 golden |
| C-HTTP-03 | 运维端点 | `GET /health` 内容和 200 行为；`/metrics` Prometheus 格式 | 无依赖、降级和完整栈 smoke |
| C-HTTP-04 | 文档中的旧搜索入口 | README/模块文档仍声明 `/start`、`/recover`、`/refine`，代码未实现对应 route | 先决定文档或历史部署是否构成支持合同；不得在结构提交中增删 |
| C-ENV-01 | HTTP 响应包络与字段大小写 | `{success,data}` / `{success,error,message}`，搜索含 `action/sessionId/streamUrl/turnId`；结果/用户 DTO 混用 camelCase 与 snake_case | JSON Schema + golden payload |
| C-SSE-01 | 事件集合 | `step_start`、`step_done`、`step_error`、`progress`、`intent_parsed`、`notes_found`、`analysis_done`、`restaurant`、`result`、`error`、`done` | 字节级 SSE fixture 与事件 schema |
| C-SSE-02 | 顺序与终态 | 当前六步、`steps/progress`、restaurant/result 流；`done|error` 为终态 | 正常、空结果、领域错误、异常状态机测试 |
| C-SSE-03 | 重放 | SSE `id`，服务器读取 `Last-Event-ID`；游标仍在窗口内时排他续传，游标已 trim/过期时返回稳定 `replay_expired/resync` 与 PostgreSQL 权威任务快照或终态，不创建新任务 | 断连、窗口内重连、游标过期/Redis restart、多订阅者、终态幂等测试 |
| C-ID-01 | 标识和幂等 | session ID、turn ID、event ID、task state ID、匿名用户 UUID；restaurant ID 在电话为空时为 `sha256(trim(name).utf8)[:32]`，否则为 `sha256((trim(name) + ":" + trim(tel)).utf8)[:32]` | 旧数据 golden + 空/非空电话、Unicode、重试/重复事件测试 |
| C-AUTH-01 | 用户识别 | `X-User-Id > X-Device-Id > anonymous`；浏览器持久化 `deviceId` | header 优先级、匿名隔离和迁移测试 |
| C-RESULT-01 | Food 请求和结果 DTO | `FoodSearchIntent.to_dict/from_dict`、`RestaurantRecommendation.to_dict`、`XHSFoodResponse.to_dict`、`EnrichedRestaurant.to_dict`；`mustTry/blackList` 与其他 snake_case 混合；live `search_results` writer 保存 recommendation mixed view + `id`，不同于构造的 `Restaurant.to_dict` camel-case fixture | 序列化 golden、writer-path side-effect、空值、Unicode、两类旧记录回读 |
| C-RANK-01 | 当前 Food 行为 | 四阶段关键词、快速模式停止、note 去重、店名合并、网红过滤、`confidence/source count` 排序、追问语义 | 冻结来源和 LLM fixture 的 characterization |
| C-PY-01 | Python 包与公开导出 | legacy current 为 Python `>=3.10`；目标 runtime 为 `>=3.12,<3.13`。wheel 包含 `xhs_food` 与 `api`；顶层及 `schemas/services/agents/events/protocols/di.__all__` | import smoke + signature snapshot；S0 只冻结旧声明，不把 3.10/3.11 延续为目标支持义务 |
| C-PY-02 | Orchestrator public API | `XHSFoodOrchestrator.search/process/search_stream/context/reset_context` 及测试覆盖的构造注入点 | compatibility facade contract suite |
| C-TOOL-01 | MCP Tool Gateway | `MCPToolProvider.name/execute/health_check`、`ToolResult` envelope、注册名 `xhs_search/xhs_note/xhs_batch` 和 `data["notes"]` | provider consumer-driven contracts |
| C-STATE-01 | 搜索状态 | `id/status/query/turn_id/summary/filtered_count/error/restaurants/timestamps`，Redis key `task:{sid}:state` | Memory/Redis 双实现等价测试 |
| C-SESSION-01 | 会话与事件保留 | Redis `session:{sid}:window`、当前 24h 会话声明、约 1h task/event TTL、PostgreSQL warm-up 与多轮恢复 | 固定时钟、TTL 边界、重启/多 worker 测试 |
| C-DATA-01 | PostgreSQL 旧数据 | users、favorites、search_history、search_results、restaurants、chat history/embeddings；旧记录不要求重建 | N-1 fixture migration + 双版本读写 |
| C-DATA-02 | 多轮 search_results | 运行 SQL 期待 `(session_id,turn_id)` 和 `query`，基础建表仍是单一 `session_id UNIQUE`，独立脚本补齐 | schema/repository contract；部署迁移清单调查 |
| C-CONFIG-01 | 环境变量和 provider | 当前 `.env.example`、Settings 名称/默认值、SiliconFlow/OpenAI/DeepSeek、XHS/Amap/Redis/Postgres 配置 | env precedence snapshot + unknown/legacy key tests |
| C-FALLBACK-01 | 当前降级 | Redis EventBus/state -> memory；PostgreSQL/pgvector 不可用时组件禁用或进程继续；Node signer/浏览器登录有独立路径 | 仅作 legacy characterization；B0/B3 必须验证退出生产内存 fallback 且不改变开发测试夹具 |
| C-DEPLOY-01 | 运行与容器 | `api.main:app`、端口 8000、healthcheck、UID/GID 1001、可写 logs/profile 卷、Compose service/volume 名和 pgvector init | Docker image/Compose smoke 与权限测试 |
| C-FRONT-01 | 浏览器路由和可见状态 | `/`、`/favorites`、`/history`、`/profile`；搜索状态 `idle/searching/completed/error` | Browser contract/e2e snapshot |
| C-OBS-01 | 指标与日志 | 既有指标名/label、HTTP metrics、关联 session/task 信息和凭据脱敏 | metrics golden + log redaction test |

### Known incompatible current expectations

| Surface | Client/document side | Server/code side | Required gate before behavior change |
|---|---|---|---|
| Search start response | 前端读取顶层 `sessionId/streamUrl` | 后端返回 `data.sessionId/data.streamUrl` | 双侧测试后指定 authority，另立兼容 change 或增加明确 adapter |
| Refine/recover | 前端调用 `/refine` 和 `/recover/{id}` | 后端统一 `POST /v1/search/` | 查明历史部署和公开使用量，再决定 alias/deprecation |
| History pagination/envelope | `page/pageSize`、`data.history` | `limit/offset`、`data.items` | consumer-driven contract 决策 |
| Favorites envelope | `data.favorites` | `data.items` | consumer-driven contract 决策 |
| FAQ envelope | `data.faqs` | `data` 直接数组 | consumer-driven contract 决策 |
| SSE replay | `lastEventIndex` query | `Last-Event-ID` header | 浏览器重连 wire test 后决定兼容桥接 |
| SSE steps | `intent_parsing/xhs_search/...`，读取 `detail` | `step1..step6`，发送 `message/error` | Stable Event Mapper 版本决策 |
| Frontend dev/CORS | Vite 端口 3000 | CORS 默认 5173，且方法清单不含 PUT | 环境合同决策，不能混入架构移动 |
| SSE timeout config | `.env.example` 使用 `SSE_TIMEOUT` | Settings 暴露的名称/消费关系不同 | 配置兼容测试与命名决策 |
| Search history side effect | 新搜索预期创建 `loading` history | route 调用不存在的 `create_search_history`，捕获异常后继续 | S2 按 characterization 保留；独立行为 change 定义用户身份、失败和幂等后修复 |
| Task terminal/state | Orchestrator 异常发出 terminal `error` | 外层因正常返回仍可写 `completed`，且持久化失败只记录 warning | S2 按 characterization 保留；B0 以提交屏障和单一终态修复 |
| Same-session refine replay | 新 turn 应继续接收新事件 | emitter reset 不清 EventBus，from-start replay 遇到旧 `done` 即停止 | S2 按 characterization 保留；B0/canonical v1 按 task+turn 修复 |
| Search-result persistence view | ADR-0005 的 `persistedRestaurant` 是构造的 `Restaurant.to_dict` camel-case view | live writer 从 `last_recommendations` 保存 `RestaurantRecommendation.to_dict` mixed view + `id` | S2 mapper 保持 live writer；规范化/回填另立数据与 API change |
| Container frontend delivery | 浏览器应用需要可交付静态资产 | 当前 image/Compose 仅交付 API:8000，没有 frontend service/bundle | 独立 release-topology change；结构里程碑保持 API-only image |
| Frontend CI | CI 执行 `npm ci`、`tsc -b` | 缺 lockfile 和 tsconfig，且根 `*.json` ignore 会屏蔽 lockfile | 先修复可执行基线的独立 tooling change |

## Failure Isolation

| Failure | Isolation boundary | Required behavior | Rollback/repair |
|---|---|---|---|
| 单一 Source Connector 超时/限流 | Source Gateway circuit、source budget | 标记来源失败；满足覆盖度时部分继续，否则稳定失败；不得转成“真实空结果” | 停用该 Connector，保留旧 Bundle |
| LLM/provider 失败 | Provider adapter + step budget | 稳定错误分类；不得发布未经验证的 Evidence/结果 | 切回兼容 provider 或旧流程 |
| 单条文档/评论解析失败 | Evidence normalization item | 隔离单项并计入覆盖度，不中止无关来源 | 重放该 item；不改当前 Bundle |
| Media Processor/Extractor 超时或 OOM | 独立 Temporal Media Task Queue + process quota | 杀死单 Activity，隔离派生物；允许时返回媒体覆盖缺失 | 暂停 Media worker 或禁用处理器/Extractor 版本 |
| candidate Bundle 写入失败 | Evidence repository transaction | 不切 current pointer、不发 published 事件 | 清理/重试 candidate；继续旧版本 |
| 特征重算或索引失败 | version-scoped derived job | candidate 保持未发布；旧公共索引继续 | 重跑派生或放弃 candidate |
| Refresh worker 崩溃 | Temporal workflow history + activity retry | 由持久历史 replay/reschedule；外部副作用使用稳定幂等键，迟到 Activity 的发布 CAS 失败 | 暂停对应 Task Queue；旧 Bundle 继续 |
| 重复/乱序 Activity | Temporal Activity boundary + repository CAS | 允许底层调用至少一次执行；业务终态至多发布一次，旧 base/version 不得覆盖新版本 | 丢弃重复提交，记录冲突指标 |
| Redis/EventBus 不可用 | Foundation cache/event adapter | 已运行 workflow 继续，已提交结果仍可读；新实时研究/SSE 返回稳定 `dependency-unavailable`，生产多 worker 禁止切进程内存 | 恢复 Redis 后按 PostgreSQL/Temporal 权威状态重建热投影 |
| PostgreSQL 不可用 | Authority repository | 不发布新事实/Bundle；只在明确陈旧合同内读旧数据 | 回旧读路径或只读模式；禁止双权威修复 |
| Personalization 读取失败 | 用户策略边界 | 使用领域默认或明确失败；绝不读其他用户 cache | 关闭个性化开关，不影响公共证据 |
| Domain Pack 注册/执行失败 | Pack registry/version | 只禁用该领域/版本；其他领域继续 | 路由新任务回上一 Pack 版本 |
| SSE 客户端断线 | Stable Event Mapper/EventBus | 窗口内按 event ID 排他重放；窗口外返回 `replay_expired/resync` 和权威任务快照/终态；两者均不创建重复研究 | 客户端按 task/version 幂等应用 snapshot 或 terminal |
| 持久化晚于成功事件 | Task completion barrier | 权威结果提交前不得发布成功终态 | 保持 running/error，不产生假 completed |

Coordinator 负责总预算、超时、取消、重试和幂等；Gateway 负责来源速率、游标和 circuit；Repository 负责原子性；Domain Contract 负责最低覆盖度与可降级性。职责不得互相兜底到不可观测。

## Risks / Trade-offs

- **[误合并 Query Family 导致错误证据复用]** -> 版本化匹配、低置信度新建、shadow 对比、人工拆分与 Bundle 指针回退。
- **[Bundle 不可变增加存储成本]** -> 内容哈希去重、版本保留策略作为明确决策；在保留期未确定前不删除旧版本。
- **[双路径/双写窗口增加复杂度]** -> 幂等键、shadow-only 默认、单向 authority、阶段结束后另行收缩；不在同一里程碑删除旧路。
- **[当前隐式私有属性形成隐藏合同]** -> S0 characterization 后先增加 facade，再禁止新的私有跨层访问。
- **[现有无基础设施/Redis-only 降级退出生产支持时暴露历史部署差异]** -> S0 只做 legacy characterization；B0/B3 通过显式 capability/health gate 切换到 PostgreSQL + Temporal + Redis 目标模式，禁止静默 fallback，并保留开发测试 adapter。
- **[个性化泄漏或污染公共事实]** -> user-scoped repositories/cache keys、信息流测试、日志脱敏、公共写端不向 Personalization 暴露。
- **[领域 Pack 变成任意代码插件]** -> allow-list、版本化 schema、资源预算、注册时验证和禁止依赖检查。
- **[刷新抢占前台容量]** -> 独立队列/配额、优先级原因、全局预算和一键停用 Refresh Jobs。
- **[结构迁移被前后端现有不一致干扰]** -> 两侧分别冻结，合同纠错独立 change，不把测试“修绿”解释成架构工作。
- **[图、spec 和代码再次漂移]** -> 从合同生成依赖图/模式文档，并在 CI 校验注册表、spec 场景和架构边集合。

## Migration Plan

### Global rules

1. 一个里程碑对应一个可审查提交或 PR；不得把后续清理塞入同一提交。
2. 每个里程碑先提交失败的基线/合同测试，再提交最小实现；合并时测试必须通过。
3. 结构里程碑只做委派和边界，不启用新行为。行为里程碑必须有独立逻辑开关和 shadow/canary 路径。
4. 数据库使用 expand -> backfill/dual-read -> switch -> contract；`contract` 删除阶段不属于本 change 的首轮迁移。
5. 旧流程至少保留到新流程完成完整栈 canary 和回滚演练；回滚不依赖删除新数据。
6. 任何 authority/Open Question 未解决时，相关行为里程碑保持阻塞，不以默认假设继续。

### Phase A: structural milestones (no behavior change)

| Milestone | Independently committable deliverable | Independent test gate | Rollback |
|---|---|---|---|
| S0 - Characterization baseline | 冻结 HTTP/OpenAPI、SSE、DTO、Python exports、四阶段搜索、存储/TTL/fallback、容器和前端双方假设；建立 contract discrepancy ledger | 全部测试在当前实现通过；fixture 无实时平台依赖；覆盖率清单可审计 | 回退测试/fixture 提交，不触及生产状态 |
| S1 - Contract SDK and architecture rules | 新增领域中立合同、错误分类、版本字段、允许依赖图和 Composition Root 骨架；不迁移调用方 | import graph、协议结构、序列化、旧 imports 全通过 | 删除新增合同/规则提交；旧代码无引用 |
| S2 - Experience and task facades | FastAPI、SSE、state/tasks 通过 ResearchTask facade 委派旧 Orchestrator；增加 Stable Event/Result Mapper，但输出逐字节等价 | S0 HTTP/SSE golden、恢复和 header 测试全等 | 组合根切回直接旧调用；无数据迁移 |
| S3 - Gateway and repository facades | MCP/XHS/Amap、LLM、EventBus、Redis/Postgres 置于端口后；移除新增私有跨层依赖，底层行为不变 | consumer contracts、Memory/Redis 等价、SQL/schema contracts、失败分类 characterization | Composition Root 绑定旧 adapters；保留旧类和 schema |
| S4 - Food Pack and decision extraction | 把 Food intent、提示词、四阶段策略、Evidence 解释、评分和输出置于 Food Pack/Decision facade；旧 `XHSFoodOrchestrator` 和 DTO 继续可用 | 固定来源/LLM fixture 下关键词、候选、排序、输出和追问全等 | 注册旧 Food facade；撤销新 Pack 绑定 |
| S5 - Shared skeleton routing | 通用 ResearchCoordinator 通过 `AgentRuntime`/`ModelGateway` 端口注册 Pydantic AI V2 typed runtime adapter 并调度旧 Food workflow，建立业务进度投影/plan shell；旧 LangChain 只在兼容 adapter 内，所有行为开关默认关闭 | typed tool/output/provider contracts、端到端 characterization、依赖检查、同 session 并发基线 | 路由开关回旧 orchestrator/LLMService adapter；新计划数据为可忽略附加数据 |

### Phase B: behavioral milestones (each separately activated)

| Milestone | Independently committable deliverable | Independent test and activation gate | Rollback |
|---|---|---|---|
| B0 - Reliable task semantics | 在独立 `reliable_task_lifecycle` 开关后，以 Temporal Research Task Queue 承载唯一 executable checkpoint、Workflow ID single-flight、timer/retry/cancel；Pydantic AI 官方 Temporal integration 将模型/工具调用转为 Activity，Coordinator 保持业务状态唯一写入者并 persist-before-success | legacy policy 继续逐字代理；Workflow sandbox determinism、模型/工具 Activity replay/versioning、worker crash、重复 Activity、PG/Temporal reconciliation、SSE 游标过期、持久化失败和取消 tests；Stable Mapper 维持 wire 合同 | 停止新 workflow 路由并回 legacy task adapter；已启动 workflow 按版本完成/终止，不更改 Evidence 读写 |
| B1 - Canonical Query and Evidence shadow | 通过 Alembic expand migration 增加 additive schema、Canonical Query、标准来源 batch、Evidence/Provenance 和 candidate Bundle；只 shadow 写，不参与响应 | clean install 与 N-1 upgrade 收敛到同一 schema、Source contracts、provenance 完整度、shadow 差异指标；零外部 payload 差异 | 停 shadow 写；旧读路径不变；保留附加表，不执行 contract migration |
| B2 - Query Family and versioned read canary | deterministic key -> `pg_trgm` -> 前两级置信不足时 pgvector/BGE-M3 profile v1 的 Family Index、Freshness Gate、Workflow ID in-flight 合并和 PostgreSQL Bundle activation CAS；小流量读复用 | fresh/incremental/new 三态、同一 durable task identity、profile 隔离/回填/切换、CAS、陈旧读取、固定输入结果容差 | 关闭 reuse read，读指针回上一 embedding profile/Bundle 或旧实时研究；不删版本 |
| B3 - Personalization | PostgreSQL conversation/memory/outbox、四层 Memory、ContextAssembler、Resolver、策略快照、用户隔离和最终重排；commit 后 Redis invalidate/warm，公共 Evidence 只读 | 优先级、20 条/24h 热窗口、缓存失效重放、用户隔离、匿名、幂等反馈、默认策略、公共数据不变 | 关闭 personalization，返回公共/旧排名；权威记忆附加数据保留，Redis 热投影可重建 |
| B4 - Refresh and media jobs | Temporal Refresh/Media Task Queue、优先级/配额、Processor/Extractor、S3-compatible ObjectStore、boto3 adapter 和派生证据候选版本；补齐 OTel traces 与 Prometheus 指标 | replay/duplicate/retry-exhaustion、资源配额、hash 去重、对象丢失、MinIO/S3 contract、跨队列 trace、旧 Bundle 连续服务 | 停止对应 Task Queue worker 和调度；禁用媒体 policy；旧 Bundle/同步路径继续 |
| B5 - Travel Pack proof | Travel Domain Contract、输出模式、必要 Connector 注册；完全复用共享 runtime/evidence/memory | Pack 合规、allowed tools、Travel 输出、Food 回归、Pack 故障隔离 | 注销 Travel 版本；Food 和共享核心不回滚 |
| B6 - Legacy contraction (later change) | 在使用量、回滚期和数据保留均满足后，删除旧实现/字段/开关 | 至少一个完整发布周期、回滚演练、无旧消费者证明 | 该阶段必须有单独备份/restore 计划；不纳入首次 apply |

### Rollback model

- 路由：Composition Root 的逻辑绑定按能力独立切换，至少分 `modular_core`、`reliable_task_lifecycle`、`evidence_shadow`、`query_reuse_read`、`personalization`、`background_refresh`、`travel_pack`；实际配置名在实现 ADR 决定。
- 数据：只增加表/列/索引；旧代码忽略新结构。新写入含 schema/version，回旧代码不需解释新表。
- 证据：回滚当前指针，不修改或删除旧 published Bundle；失败 candidate 永不升级为 current。
- 任务：Research、Refresh、Media 使用独立 Temporal Task Queue/配额，可单独停止；workflow 版本与 patch marker 保持 replay determinism，停止后台刷新不影响读取已发布 Bundle。
- Pack：任务创建时固定 Pack/合同版本；新任务可切回旧版本，进行中任务完成或按稳定错误合同终止。
- API：Stable Mapper 保留旧版本；内部合同回滚不改变 wire payload。现有前后端不一致只能通过另立 change 处理。
- 提交：每个里程碑的 revert 不依赖后续提交。后续里程碑开始前记录前一里程碑的开关状态、schema 版本和回滚演练结果。

## Verification Baseline

### Characterization matrix

| Area | Fixtures | Assertions | Existing gap to close in S0 |
|---|---|---|---|
| Unified search | new/refine/recover、missing query、unknown session | path/method/status、包络、action/turn、后台启动次数 | recover/status/results 成功路径不足 |
| SSE wire | 正常、空结果、领域错误、异常、窗口内重连、过期游标/Redis restart、同 session refine | 字节级 event/id/data、六步顺序、progress、terminal；窗口内排他重放，窗口外 `replay_expired/resync` + 权威 snapshot | HTTP wire、旧 terminal 回放、多轮未覆盖 |
| Four-stage Food search | 冻结 intent、notes、tool results、fast/deep mode | keyword 顺序、调用次数、去重、早停、合并、过滤、排序 | SearchExecutor 缺直接测试 |
| DTO/serialization | 全字段、空值、Unicode、旧持久化 JSON | 字段名、枚举、默认值、camel/snake 混合、round trip | StreamEvent 与实际事件模型不一致 |
| Session/state | Memory/Redis、固定时钟、重启、多 worker 模拟 | keys、TTL、turn、warm-up、恢复、幂等 | TTL 差异和多 worker fallback 风险 |
| User surfaces | header 组合、favorites/history/profile/settings/help | 身份优先级、隔离、分页、包络、软删除 | 当前 API 几乎无覆盖 |
| Python API | public imports、constructor overrides、methods | import path、signature、return type、exceptions | `__all__` 未做 golden |
| Tools/providers | success/failure/timeout/empty | ToolResult、注册名、调用参数、空与失败区分 | 测试 fake 与生产 ToolResult 不一致 |
| Config/fallback | env permutations、Redis/PG/pgvector/Node absent | default/precedence、启动、degraded status、日志脱敏 | 多数 fallback 未在 CI 验证 |
| Deployment/UI | image/Compose、frontend build、browser workflows | port/entry/user/volumes/health；路由和状态机 | frontend CI 当前不可执行，无 e2e |

### Contract test matrix

| Contract | Providers under test | Consumer assertions |
|---|---|---|
| ResearchTask | legacy workflow、new coordinator | state transitions、业务进度投影、显式 refresh 合并、内部 cancel、PG commit 后唯一 terminal；Temporal history 是唯一 executable checkpoint |
| Stable Event Mapper | old/new internal events | current SSE schemas and ordering, chosen compatibility version |
| SourceConnector | XHS、Amap/Place、fake failure connector | canonical batch、cursor、provenance、failure taxonomy、no binary |
| Tool Gateway | existing MCP providers、new tool fixture | allow-list、schema、budget、health、ToolResult compatibility |
| Canonical Query/Family | exact、near、low-confidence、two-user fixtures | deterministic version、private fields excluded、merge rationale |
| Evidence repositories | in-memory test double、PostgreSQL | immutable versions、atomic pointer、CAS、old-version reads |
| Domain Pack | Food、minimal fake、invalid pack、Travel | required declarations、allowed tools、tool input/output schema、Agent final output schema、恢复时版本固定、failure isolation |
| Personalization | session/explicit/inferred/strategy fixtures | precedence、user isolation、idempotency、public data unchanged |
| Runtime backends | Temporal test environment/完整服务、PostgreSQL read model、Redis EventBus/cache | ordering、TTL、workflow replay/versioning、Workflow ID single-flight、重复 Activity、业务终态唯一性 |
| Output adapters | Food legacy DTO、new domain-neutral result、frontend renderer | schema golden、null/default、unknown optional fields |
| Architecture | every target package/import | only allowed edges; no private cross-module access or concrete adapter import |
| Schema/repository | clean DB、pre-turn migration DB、current DB | DDL matches SQL, N-1 read, expand migration idempotent |

### Failure-injection matrix

| Injection | Expected assertion | Data safety assertion |
|---|---|---|
| XHS/Amap timeout, 429, malformed payload | source-scoped error/circuit; coverage decides continue/fail | failure never becomes empty-success Evidence |
| LLM timeout, bad JSON, partial item failure | bounded retry/stable error; other eligible items continue | no unvalidated Evidence published |
| Redis unavailable/corrupt JSON/restart | 已运行 workflow 继续且已提交结果可读；新实时/SSE 请求返回稳定 `dependency-unavailable`；已有客户端若游标不可重放则获得 `replay_expired/resync` + 权威 snapshot；无跨会话数据 | PostgreSQL/Temporal 权威不变；生产多 worker 不切进程内 fallback，不作虚假恢复声明 |
| PostgreSQL unavailable/transaction abort | no success terminal/new current Bundle | current pointer and old records unchanged |
| EventBus disconnect/duplicate/out-of-order/trim | retained cursor 排他重放；expired cursor 返回 resync snapshot；terminal 业务投影唯一且客户端按 task/version 幂等应用 | task identity preserved, no duplicate research or fabricated event continuity |
| Worker crash before/after external fetch | Temporal 从持久 history replay/reschedule；Activity 可重复但外部副作用带稳定幂等键 | content hash/job key 和 PostgreSQL CAS 防止重复发布，迟到执行者不能覆盖新版本 |
| Concurrent refresh and late writer | all requests resolve to one Workflow ID or a visible PostgreSQL CAS conflict | older base cannot replace newer current version |
| Feature recompute/index failure | candidate remains non-current | old Bundle and index stay mutually consistent |
| ObjectStore missing/corrupt asset | asset-scoped quarantine and explicit coverage loss | no dangling Evidence without valid locator |
| Object upload succeeds but metadata transaction aborts | object remains undiscoverable; enqueue idempotent orphan reconciliation | no Evidence/Bundle references uncommitted metadata; current pointer unchanged |
| Processor OOM/timeout | process killed within quota; queue continues | raw asset retained per policy; no partial artifact publish |
| Memory service failure/cross-user cache collision | default/error behavior; isolation alarm | no other user's values returned or logged |
| Invalid/throwing Domain Pack | only that version/domain disabled | Food/shared runtime remain available |
| Frontend network/bad SSE JSON | stable error/retry UI, no infinite duplicate reconnect | no duplicate favorite/result or event counter authority |

### Cross-platform matrix

| Dimension | Blocking baseline | Extended probe | Notes |
|---|---|---|---|
| OS/CPU | Ubuntu current LTS x86_64、Windows current supported x86_64 | macOS current supported arm64 | probe 通过只记录兼容性，不扩大生产支持矩阵 |
| Python | 3.12 | 3.13 compatibility probe | 主运行时统一 3.12；`uv.lock` 精确锁定且 CI 执行 locked install/check |
| Node/signing | Node 20 present | Node absent、signer child exit、Playwright browser absent | 缺失时错误/降级需稳定 |
| Backend mode | PostgreSQL 16 + Redis 7.4 + Temporal + S3-compatible ObjectStore + pgvector/pg_trgm | 单依赖故障、恢复和滚动升级 | no-infra、Redis-only、PostgreSQL-only 只作 legacy characterization 或单进程 dev/test，不是生产支持矩阵 |
| Event backend | Redis Streams | Redis restart/cluster-like reconnect、InMemory dev/test adapter | 同一 contract suite；InMemory 不进入生产支持模式 |
| Database | PostgreSQL 16 + pgvector current schema、pre-turn schema | migration interruption/retry | N-1 fixtures 不依赖现网数据 |
| Browser | Chromium desktop/mobile | Firefox desktop、WebKit desktop/mobile | 搜索、SSE reconnect、favorites/history/profile；probe 非生产支持声明 |
| Container | Linux image/Compose smoke：PostgreSQL、Redis、Temporal、MinIO、Alembic upgrade | non-root volume ownership、restart/rolling worker | 端口 8000、health、profiles/logs；应用启动不自动建表 |
| Locale/time | UTF-8 中文、UTC、Asia/Shanghai | DST locale | canonicalization、JSON、timestamps、freshness |

现有 CI 仅 Ubuntu/Python 3.11，Pyright 非阻断，pytest marker 选择会遗漏约 32 个测试，前端缺 lockfile/tsconfig。S0 必须先让基线可执行；随后 Python 3.12、`uv sync --frozen`、`uv lock --check`、Alembic clean/N-1 upgrade 和完整 Compose smoke 成为阻断 gate，不能用当前无法执行的 CI 声称验证通过。

### Milestone exit criteria

每个 S/B 里程碑只有同时满足以下条件才算完成：

1. 对应 characterization 或 contract suite 在声明矩阵上通过。
2. 新增 failure-injection 场景已运行，且没有未分类失败或数据污染。
3. `openspec validate --strict` 和架构依赖检查通过。
4. 变更范围只包含该里程碑，提交可独立 revert。
5. 回滚命令/开关、数据影响和观察指标已演练并记录。
6. 未决 Open Question 要么不影响该阶段，要么已有明确 ADR；不得隐式采用默认值。

## Open Questions

以下只保留不会改变已批准基础设施基线的产品、兼容性和运维参数。相关 tasks 必须先产出 ADR/contract fixture，再解锁受影响的行为里程碑。

1. HTML 的领域中立命名与 Draw.io 中 `FoodResearchAgent`、`FoodSearchWorkflow`、`AuthenticityScorer`、Amap 等共享层命名冲突时，哪一份是目标命名权威？
2. 目标描述中的 Draw.io 链接遗漏 instance/visualizations 路径；是否需要把两份图复制到仓库并纳入版本控制？
3. HTML 引用 `details.experience`，但没有对应内部子图；体验层是否以 Draw.io 的 API/Task/Event 模块为正式细化？
4. `audience` 是精确 Canonical Query 身份字段、只参与相似匹配，还是只参与最终重排？示例两问可能 audience 不同但要求同 Family。
5. `domain/geo/intent/audience/constraints/time_range/freshness_policy` 的枚举、规范化、缺省值、语言/地域和 schema 版本规则是什么；每个 Domain Contract 如何把约束分类为公共投影或个人策略？
6. Family 相似阈值、低置信度策略、合并/拆分、别名和人工纠错流程是什么？
7. 新鲜度窗口、最大陈旧时间、最低覆盖度、来源水位、热门度和刷新优先级如何按领域配置？
8. Evidence、Evidence Bundle、SourceLocator、MediaRef、DerivedArtifact 的完整 schema、许可/可见性、保留期和删除规则是什么？
9. Domain Contract 的精确方法集、发现方式、版本协商、兼容策略、allowed-tools 和输出模式是什么？
10. 六个明确绿色扩展点之外，Draw.io 的 `New Fixed Workflow`、可替换 Scoring Policy、Domain Sources 和 HTML 的 Refresh Coordinator 是否也是公开扩展合同？
11. Refresh Job 的 retry budget、退避、优先级、超时、取消和重试耗尽后的人工处置参数如何按领域/来源配置？
12. 对象存储的服务端加密、内容保留、孤儿清理和签名 URL 策略是什么？
13. 用户显式约束、当前会话、稳定偏好、推断偏好的正式 schema、作用域、同意、过期、纠正、导出和删除语义是什么？
14. 哪类策略反馈可以影响公共刷新优先级，聚合到什么隐私阈值后才不再是个人信号？
15. Query Family 的租户、用户群、语言、地域和数据可见性隔离边界是什么？匿名身份升级为实名时记忆如何迁移？
16. 实际 `POST /v1/search/` 统一入口与文档 `/start`、`/refine`、`/recover` 中，哪套是兼容权威；历史部署是否有旧路由消费者？
17. 搜索响应包络、history/favorites/FAQ 字段、SSE replay、step IDs 和 message/detail 差异中，前端、服务端或公开文档哪一侧是权威？
18. 当前混合 camelCase/snake_case 的 Food/SSE/持久化 DTO 是否原样版本化，还是通过一个另立的迁移 API 统一？
19. **Resolved by ADR-0009:** 仓库不能证明历史 fleet 状态；B1 必须先探测并分类 clean/pre/post/divergent schema，再执行 Alembic baseline/stamp，禁止假定脚本已运行。
20. `Restaurant` 是公共实体、Evidence 派生视图还是用户结果？以 name/tel 生成的 ID 在补齐电话或实体合并后是否稳定？
21. **Resolved by ADR-0009:** S2-S5 对搜索历史缺写、error 后 completed、refine 旧终态和 live persistence view 做 characterization 保留；B0 或独立版本化行为/数据 change 修复。
22. 当前 source failure 被转换为空 notes；新的错误分类上线时，旧客户端应看到 error、partial 还是 empty success？
23. Python public exports、构造注入点和 README 示例是否属于长期支持 API，还是只保证 HTTP/UI？
24. **Disposition resolved by ADR-0009:** 当前 API-only image、CORS/Vite 和 timeout 名称差异仅作 characterization；目标交付、配置 alias 和前端托管由独立 release-topology change 决定，不混入结构里程碑。
25. 正式支持的 macOS/arm64 和浏览器集合是什么？
26. Food 新旧路径的结果等价采用精确顺序、Top-K 集合、评分容差还是人工相关性阈值？LLM 非确定性 fixture 如何审批更新？
27. **Resolved by ADR-0009:** reachable Git history 无被跟踪副本，外部副本未知；五个链接不具合同权威，独立文档 change 删除或替换，后续发现的副本只作为待评审证据。
28. 显式刷新通过哪个 use-case/API 版本暴露，普通与强制刷新如何授权、与同一 Temporal Workflow ID 合并并映射到现有 SSE？
