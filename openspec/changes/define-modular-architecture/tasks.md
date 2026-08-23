## 1. Decision Gates And Contract Authority

- [x] 1.1 建立 ADR 索引，记录每个 Open Question 的负责人、截止阶段、证据链接和“未决即阻塞”的依赖里程碑。
- [x] 1.2 决定 HTML、Draw.io 和目标描述发生冲突时的权威顺序，修正 Draw.io 路径，并确定是否将两份图纳入仓库版本控制。
- [x] 1.3 决定实际统一搜索路由与 README 旧 `/start`、`/refine`、`/recover` 路由的兼容权威和弃用策略。
- [x] 1.4 决定搜索、history、favorites、FAQ 响应包络和分页字段中前端与后端哪一侧是权威，并为每个裁决生成 JSON Schema fixture。
- [x] 1.5 决定 SSE 步骤 ID、`message/detail/error` 字段、终态和版本协商；重放固定为窗口内按 event ID 排他续传、窗口外返回 `replay_expired/resync` 与权威任务快照/终态，并生成两类 wire-level fixture。
- [x] 1.6 决定 Food DTO 的 camelCase/snake_case、Restaurant 身份语义、ID 稳定性、Python public exports 和结果等价容差。
- [x] 1.7 定义 Canonical Query 字段枚举、规范化版本、语言/地域/租户隔离、`audience` 语义、公共/个人约束分类、相似算法和 Family 合并/拆分规则。
- [x] 1.8 定义 freshness、最大陈旧时间、最低覆盖度、来源水位、热门度和刷新优先级的领域配置合同。
- [x] 1.9 定义 Evidence、Bundle、SourceLocator、MediaRef、DerivedArtifact 的正式 schema、可见性、许可、保留和删除策略。
- [x] 1.10 定义 Domain Contract 方法、发现与版本协商、allowed tools、输出模式，并裁决 Fixed Workflow、Scoring Policy、Domain Sources 和 Refresh Coordinator 是否是公开扩展点。
- [x] 1.11 定义四层记忆 schema、用户/匿名身份迁移、同意、过期、纠正、导出、删除和反馈聚合隐私阈值。
- [x] 1.12 将已批准的数据权威写入 ADR：PostgreSQL 16 保存业务事实与 `task_progress_projection`，Temporal history 是唯一 executable checkpoint，Redis 只保存可重建热状态；目标多 worker 模式禁止进程内静默 fallback、Redis lock/Redlock 和 Redis durable task state。
- [ ] 1.13 将已批准的基础设施绑定写入 ADR：Temporal 承载 Research/Refresh/Media 三类 Task Queue，S3-compatible `ObjectStore` 使用 boto3 adapter、本地使用 MinIO；另行定义加密、保留、清理、重试耗尽和人工恢复策略。
- [x] 1.14 将 Pydantic AI V2 固化为唯一 Agent runtime，保留 SiliconFlow/OpenAI/DeepSeek 的 provider adapters，官方 MCP SDK 只进入外部 interop adapter；Node signer/Playwright 缺失合同仍单独裁决。
- [x] 1.15 将 Python 3.12 固化为主运行时和 blocking gate，并决定支持的 OS、CPU、浏览器、容器及其他 Python 版本的 blocking/probe 范围。
- [x] 1.16 调查现有部署的 `turn_id` migration、缺失 internal docs、CORS/Vite/env/容器差异和已知搜索状态缺陷，逐项标记“先修复”“characterize 保留”或“独立 change”。
- [ ] 1.17 定义显式刷新 use-case/API 版本、普通/强制模式授权、in-flight 合并和稳定 SSE 映射；明确它是新行为而非既有兼容合同。
- [x] 1.18 审批 ADR 索引，确认基础设施基线均标记为 accepted，剩余 Open Questions 只包含业务、兼容性和运维参数；未决项只阻塞其实际影响的里程碑。
- [x] 1.19 复核 `dependency-research.md` 已批准裁决并在 ADR 索引引用：adopt Pydantic AI V2、Temporal、SQLAlchemy 2 Async、asyncpg、Alembic、PostgreSQL 16/pgvector/pg_trgm、Redis、S3/boto3/MinIO、OpenTelemetry/Prometheus；为许可证、升级和安全响应指定 owner。
- [ ] 1.20 对 Temporal Python SDK 及 Pydantic AI 官方 Temporal durable execution integration 运行 workflow determinism、模型/工具 Activity replay、worker crash、取消竞争、重试耗尽和部署升级 qualification suite；记录 ARQ、Celery、LangGraph、OpenAI Agents SDK 及 Redis job facade 不作为第二套核心 runtime 的架构禁令。
- [x] 1.21 固化数据库和检索方案：SQLAlchemy 2 Async 通过 asyncpg 访问 PostgreSQL 16，Alembic 是唯一 schema authority，检索使用确定性键、`pg_trgm` 与 pgvector；定义 BGE-M3 `profile_v1`（1024 维、cosine）的新增 profile/table、回填、切换和回滚边界。
- [x] 1.22 固化 S3-compatible ObjectStore/boto3、本地 MinIO、OpenTelemetry SDK、Prometheus client、import-linter、Schemathesis/Hypothesis 和前端 OpenAPI client 的 adapter/tooling 边界及脱敏要求。
- [ ] 1.23 将官方资料 URL、核验日期、精确版本、维护状态和 spike 结果写入 ADR 索引；用 Python 3.12 生成并提交 `uv.lock`，依赖状态变化必须显式评审并更新锁文件。

## 2. S0 Characterization Baseline

- [x] 2.1 修复测试基础设施的独立 tooling 基线，使 Python 3.12 下的 `uv sync --frozen` 与 `uv lock --check`、frontend lockfile/tsconfig、pytest marker 选择和 CI 命令可重复执行且不改变生产行为。
- [x] 2.2 生成当前 FastAPI OpenAPI snapshot，并为搜索 new/refine/recover、status/results 和错误分支添加 HTTP golden tests。
- [x] 2.3 为 favorites、history、user、help、health 和 metrics 的路径、header、状态码、分页、包络和软删除添加 characterization tests。
- [x] 2.4 为 `X-User-Id > X-Device-Id > anonymous`、匿名隔离和浏览器 device ID 添加身份 characterization tests。
- [x] 2.5 为完整 SSE 字节流、六步顺序、payload、event ID、心跳、终态和 `Last-Event-ID` 排他重放添加 tests。
- [x] 2.6 为同 session refine、断线恢复、旧 terminal event、重复订阅和多 worker 模拟添加 SSE/state characterization tests。
- [x] 2.7 为四阶段关键词、fast/deep 停止、note 去重、合并、过滤、排序和追问添加冻结来源/LLM fixture tests。
- [x] 2.8 为 `FoodSearchIntent`、`RestaurantRecommendation`、`XHSFoodResponse`、Enriched DTO 和持久化 JSON 添加全字段/空值/Unicode golden tests，并锁定 restaurant hash 在空电话与 `trim(name):trim(tel)` 两个分支的精确公式。
- [x] 2.9 为顶层 `__all__`、Orchestrator public methods、构造注入、MCP 注册名和 ToolResult 添加 Python/import contract snapshots。
- [x] 2.10 为 Memory/Redis 状态、EventBus、session window、TTL、warm-up、PostgreSQL/pgvector 禁用和启动 fallback 添加固定时钟 tests。
- [x] 2.11 为 clean DB、迁移前 `search_results` 和已执行 `turn_id` migration 的 schema/repository 组合建立可重放 fixtures。
- [x] 2.12 为环境变量名称/默认值/优先级、多 LLM、Node signer、容器入口/端口/UID/卷/healthcheck 添加 configuration/deployment characterization。
- [x] 2.13 建立前端和服务端双方的 consumer fixture，记录 search/history/favorites/FAQ/SSE/CORS 当前不一致，测试不得通过隐式改一侧来消除差异。
- [x] 2.14 运行 S0 在无外部网络的 CI 基线，归档测试数量、未覆盖项和 fixture 更新规则。
- [x] 2.15 演练 revert S0 提交并确认仅移除测试/tooling 资产；将 S0 作为不含生产行为变化的独立提交。

## 3. S1 Contract SDK And Architecture Rules

- [x] 3.1 创建领域中立 contract package 和 schema-version 基础类型，不导入 FastAPI、平台 SDK、数据库或 Food/Travel 实现。
- [x] 3.2 定义版本化 `ResearchRequest`（含 query/refine/refresh/recover operation）、`ResearchPlan`、`ResearchTask`、`TaskEvent`、非执行型 `task_progress_projection` 和稳定错误分类。
- [x] 3.3 定义 `CanonicalQuery`、`CollectRequest`、`CanonicalSourceBatch`、`SourceLocator`、`EvidenceItem` 和 `EvidenceBundle` 合同。
- [x] 3.4 定义 SourceConnector、Tool Gateway、Repository、Workflow、Cache/EventBus、ObjectStore 和 LLM provider ports。
- [x] 3.5 定义 Domain Contract SDK、Pack manifest、allowed-tools 及每个 tool input/output schema、Agent final output schema 和注册验证结果；schema 缺失或非法的 Pack 不得激活。
- [x] 3.6 定义 `MemoryRecord`、`PreferenceSnapshot`、`PersonalizationPolicy` 和用户隔离键合同。
- [x] 3.7 定义 RefreshJob、MediaAsset、DerivedArtifact、Processor 和 Evidence Extractor 合同。
- [x] 3.8 建立 Composition Root 骨架和 registry 生命周期；所有 registry 初始只装配 legacy adapters。
- [x] 3.9 添加允许依赖边的静态架构测试，默认拒绝跨层具体实现导入和新增下划线私有属性访问。
- [x] 3.10 添加合同序列化、向后兼容可选字段和破坏性枚举/字段变化检测。
- [x] 3.11 运行 S0+S1 tests，证明旧 imports、HTTP/SSE 和结果 golden 不变，并归档架构图生成结果。
- [x] 3.12 演练移除 contract/registry 绑定的 revert；将 S1 作为不依赖 S2 的独立提交。

## 4. S2 Experience And Task Facades

- [x] 4.1 在现有 search routes 前实现 ResearchTask use-case facade，默认完整委派 legacy workflow。
- [x] 4.2 为 legacy orchestrator 增加公开的结果/context snapshot adapter，替代 API 对 `orchestrator._context` 的私有读取。
- [x] 4.3 实现 Stable Event Mapper，将内部 TaskEvent 映射为已批准的现有 SSE 事件与 payload。
- [x] 4.4 实现 Stable Result Mapper，将内部结果映射为当前 Food HTTP/SSE/持久化 DTO，保持字段和默认值。
- [x] 4.5 让 new/refine/recover/status/results 路由只依赖 ResearchTask port，保持现有路径、包络、状态码和后台启动次数。
- [x] 4.6 把 emitter 的任务步骤元数据与平台调用解耦，并定义尚未暴露的显式刷新 use-case port；legacy compatibility version 仍只输出相同六步且不新增 refresh route。
- [x] 4.7 为 task facade 添加 legacy-policy 代理测试，逐字保持当前终态、持久化顺序、错误、恢复和已知缺陷；目标 exactly-once/persist-before-success 断言留到 B0。
- [x] 4.8 运行完整 HTTP/SSE/browser characterization，对任何差异生成失败而不是更新 golden。
- [x] 4.9 增加 `modular_core` 逻辑绑定和回旧 facade 的 runbook，默认仍走 legacy。
- [x] 4.10 演练 binding 回退并确认无 schema/data 依赖；将 S2 作为独立提交。

## 5. S3 Gateways And Foundation Facades

- [x] 5.1 用 SourceConnector compatibility adapter 包装 XHS search/note/batch providers，保持 MCP 调用参数、顺序和注册名。
- [x] 5.2 用 Place Source/Tool adapter 包装 Amap/POI，并移除对 UserStorage pool/internal flags 的直接访问。
- [x] 5.3 实现 Tool Gateway allow-list、schema、budget、health 和 ToolResult compatibility adapter。
- [x] 5.4 用 Pydantic AI V2 provider port 包装旧 `LLMService` 和 SiliconFlow/OpenAI/DeepSeek 配置；旧服务仅作为迁移期 adapter，结构阶段不改变模型选择、请求参数或错误语义。
- [x] 5.5 为 session、user、history、favorites、search results 和 public evidence 定义独立 Repository ports；新增 SQLAlchemy 2 Async + asyncpg adapter 骨架，明确每个 unit of work 的 `AsyncSession` 所有权，结构阶段仍绑定旧实现且不双写。
- [x] 5.6 用 StateStore/EventBus ports 包装现有 Memory/Redis backends 并冻结 legacy key、TTL、replay 和 fallback；另定义目标 Redis contract：最近 20 条会话窗口 TTL 24 小时、SSE Stream TTL 1 小时且 `MAXLEN 1000`、热点缓存、短期幂等和限流，所有内容均可重建。
- [x] 5.7 定义 Temporal workflow/activity/Task Queue adapter 与 Composition Root 绑定点；Research/Refresh/Media 使用独立 Task Queue，结构阶段只注册禁用的目标 adapter，不以 Redis、ARQ、Celery 或 LangGraph 补充第二套 durable runtime。
- [x] 5.8 定义 S3-compatible ObjectStore adapter，使用 boto3 实现受控并发的 async 边界并提供本地 MinIO binding；Domain Pack 和核心合同不得导入 boto3/MinIO 类型。
- [x] 5.9 接入 OpenTelemetry 的 FastAPI/httpx/Redis/PostgreSQL/Temporal instrumentation 和既有 Prometheus `/metrics` adapter，统一脱敏 correlation attributes，结构阶段不改变既有指标名称和语义。
- [x] 5.10 集中配置 facade，按 owner 暴露只读配置，同时保留所有旧 env 名称、默认值和 import 路径；新增配置必须由 Pydantic Settings 解析且不得在模块导入时创建客户端。
- [x] 5.11 统一 Source/Provider/Foundation failure taxonomy adapter：区分 `success_empty`、source/provider `failure` 和聚合 `partial`，映射 `ErrorCategory`/`ErrorScope`/retryability，并使结构阶段继续映射到当前 XHS empty/error、analyzer partial 和 Amap/POI basic-result 行为而不改变 wire 行为；按 ADR-0010 保留 XHS hanging/loading characterization，不得在本阶段新增 timeout。
- [x] 5.12 为每个 port 运行同一 consumer-driven suite，覆盖 true-empty、timeout、429/rate-limit、malformed、dependency unavailable、exception、partial item、all-empty/all-failed、hanging/cancel、可选 POI fallback、客户端生命周期和 legacy fallback；断言 `CanonicalSourceBatch.errors`/coverage 与 ADR-0010 的 SSE、direct Python、status/results/recover 投影逐项一致。
- [x] 5.13 添加目标 adapter 合同测试：SQLAlchemy transaction rollback、Redis TTL/MAXLEN、Temporal deterministic payload、S3 multipart/内容哈希、OTel 脱敏和 Prometheus label cardinality。
- [x] 5.14 更新架构检查，禁止 Orchestrator 导入 spider/Amap/数据库/Redis/Temporal/boto3，禁止 Foundation 导入 Food 类型，并禁止 Agent、Pack 或 repository 绕过 owner port。
- [x] 5.15 扫描依赖图并拒绝核心路径出现 ARQ、Celery、LangGraph、OpenAI Agents SDK、LiteLLM、Mem0、Zep 或第二套数据库连接池。
- [x] 5.16 验证目标 Redis contract 不暴露分布式锁/Redlock、租约或 durable task-state API；single-flight 必须由 Temporal Workflow ID 表达，事实提交竞争由 PostgreSQL CAS 处理。
- [x] 5.17 演练 Composition Root 逐 adapter 回绑旧实现；将 S3 作为独立提交且不迁移 schema、不启用目标 runtime。

## 6. S4 Food Pack And Decision Extraction

- [x] 6.1 根据已批准 Domain Contract 创建 Food Pack manifest，并声明实体、关系、证据、特征、评分、Agent final output、来源、allowed tools 及其 input/output schema、覆盖度和停止条件。
- [x] 6.2 把 Food intent schema、领域词汇和相关 prompts 放到 Food Pack 后，同时保留 `FoodSearchIntent` compatibility facade。
- [x] 6.3 把四阶段关键词和 Food 停止规则放到 Pack/workflow adapter 后，保持调用序列和 fast/deep 结果。
- [x] 6.4 把评论有效性、网红识别、本地性特征和评分策略从通用 Orchestrator 分离到 Food Pack/Decision ports。
- [x] 6.5 将 POI 网络采集保持在 Place SourceConnector/Evidence 边界，只把 POI Evidence 的店名匹配、实体消歧和公共 Food feature 投影放到 Knowledge & Decision facade，不改变当前排序。
- [x] 6.6 实现 Food OutputSchema adapter 到旧 Restaurant/XHSFoodResponse DTO 和前端 renderer contract。
- [x] 6.7 注册 Food Pack allowed tools，验证 malformed tool input/output/final-output schema 会阻止激活或执行，并验证 Pack 无 Agent、queue、storage driver 或平台内部依赖。
- [x] 6.8 对旧 workflow 与 Food Pack facade 运行固定 fixture differential tests，要求批准的关键词、Top-K、评分和 DTO 等价。
- [x] 6.9 增加按 Pack version 回绑 legacy Food adapter 的开关和 runbook。
- [x] 6.10 演练 Food Pack 注销/回绑且其他 facade 不变；将 S4 作为独立提交。

## 7. S5 Shared Research Skeleton

- [x] 7.1 实现 typed DAG ResearchPlan、step dependencies/status/budget/evidence refs 和 plan schema version。
- [x] 7.2 实现 ResearchCoordinator 生命周期 facade；legacy policy 继续委派当前调度、取消、重试和终态行为，目标可靠策略只注册接口且保持未启用。
- [x] 7.3 在 Coordinator 内注册唯一的 Pydantic AI V2 Agent runtime adapter，定义 typed dependencies、typed tools 和 typed output，并预留官方 Temporal durable execution integration binding；开关关闭时不调用该 runtime，Domain Pack 不得创建第二个 Agent。
- [x] 7.4 实现 Step Scheduler 和 Tool Gateway 调用，默认计划仍代理现有 Food workflow；Pydantic AI tool 只能调用 Gateway，不能直接访问 Connector、Repository、Redis、Temporal 或对象存储。
- [x] 7.5 实现 Evidence Review/replan shell 和停止条件端口，在所有新行为开关关闭时不改变 legacy 决策。
- [x] 7.6 实现非执行型 `task_progress_projection` 与 recover-view 端口，保持现有 session/turn/event identity 和 SSE mapper；该投影只供查询，B0 的 Workflow 恢复不得依赖它。
- [x] 7.7 将 Experience facade 路由到共享 Coordinator 的 legacy plan，并保持旧 `XHSFoodOrchestrator` public API adapter。
- [x] 7.8 添加 Pydantic AI model/provider fake、tool schema、output validation、budget 和 provider failure contracts，不访问实时模型。
- [x] 7.9 添加并发、重复启动、终态和业务进度投影的 legacy differential tests，证明 S5 保持当前成功与失败行为；目标 executable checkpoint/replay tests 留到 B0。
- [x] 7.10 运行 S0 differential suite 和架构依赖检查，确认 Food 结果与 wire 行为零差异。
- [x] 7.11 演练 `modular_core` 路由回旧 Orchestrator；将 S5 作为最后一个纯结构独立提交。

## 8. B0 Reliable Task Semantics

- [ ] 8.1 为 legacy task policy 与 Temporal-backed reliable policy 分配独立合同版本，明确 completed/error、旧终态重放、取消、持久化顺序和稳定 HTTP/SSE 映射。
- [ ] 8.2 在独立 `reliable_task_lifecycle` 开关后实现 Research Temporal Workflow；以稳定 Workflow ID 表达 task 幂等和同任务 single-flight，重复启动必须返回同一 task/workflow 而非获取 Redis 锁。
- [ ] 8.3 保持 `ResearchCoordinator` 为语义状态迁移的唯一 owner；Temporal history 是唯一 executable checkpoint，PostgreSQL 只保存业务进度/结果投影。实现按 `workflow_id/run_id` 的固定 reconciliation、权威结果提交屏障与 PG commit 后唯一 terminal 投影。
- [x] 8.4 使用 Pydantic AI 官方 Temporal durable execution integration 将每次模型与工具调用映射为有界 Activity，并将 Connector、Repository 和结果提交放入普通 Activities；定义版本化 timeout、retry、non-retryable failure、heartbeat 和 cancellation policy，禁止普通 Pydantic AI loop 或任何非确定性 I/O 直接运行在 Workflow sandbox 中。
- [ ] 8.5 将 Research 任务绑定到独立 Temporal Task Queue 和 worker 配额，禁止与 Refresh/Media 共用无优先级队列；B4 启用另外两类 Task Queue。
- [ ] 8.6 协调 Temporal executable checkpoint、PostgreSQL `task_progress_projection` 与 Redis EventBus/SSE；SSE Stream 固定 TTL 1 小时和 `MAXLEN 1000`，窗口内按 event ID 排他续传，窗口外或 Redis 重启后返回稳定 `replay_expired/resync` 与权威任务快照/终态，并保持同一 task/turn、不创建重复研究。
- [ ] 8.7 添加 Pydantic AI 模型/工具 Activity history replay、Workflow 代码版本升级、worker crash/restart、Activity 重复、PG/Temporal projection reconciliation、SSE 保留窗口内/外重连、并发启动、持久化失败、取消竞争、重试耗尽和旧 policy differential tests。
- [ ] 8.8 验证 Redis 不可用时已启动 Temporal workflow 可继续且持久结果可读；需要创建实时会话/SSE热状态的新请求返回明确 dependency-unavailable，不静默退化到进程内状态。
- [ ] 8.9 运行 HTTP/SSE compatibility mapper tests，证明 reliable policy 的 wire 差异只出现在已批准 authority contract 允许的位置，且 terminal event 只在 PostgreSQL 提交成功后发出。
- [x] 8.10 添加依赖和运行时 gate，证明核心路径没有 Redis lock/lease、ARQ、Celery、LangGraph checkpoint 或第二个 durable scheduler。
- [ ] 8.11 关闭 reliable policy 并回 legacy task adapter，确认 Temporal history 可保留但不再接收新任务，Evidence/数据库无不可逆依赖；将 B0 作为独立行为提交。

## 9. B1 Canonical Evidence Shadow

- [ ] 9.1 只通过 Alembic 编写只增不删的 Query/Evidence/Provenance/Bundle migration；移除新 schema 的运行时 `CREATE TABLE IF NOT EXISTS` 和旁路迁移脚本，并验证 clean、N-1、pre-turn 和 current PostgreSQL 16 的幂等升级与 expand-phase 回退兼容。
- [x] 9.2 使用 SQLAlchemy 2 Async declarative/Core metadata 与 asyncpg driver 实现新 repositories；每个 use case 只持有一个 `AsyncSession`/transaction，禁止与 legacy asyncpg pool 隐式双写或维护第二套 schema 定义。
- [x] 9.3 新增版本化 embedding profile 和独立向量存储结构，将 `bge-m3/profile_v1/1024/cosine` 固化为首个 profile；不得把现有 `VECTOR(4096)` 原地改维，也不得让不同 profile 在同一索引中混写。
- [ ] 9.4 实现 profile-aware dual-write/backfill/shadow-read 工具及可重放 backfill cursor，验证中断可恢复、行数/内容哈希可核对、旧 chat embedding 继续可读，并在切换前保持新 profile 不参与响应。
- [x] 9.5 根据已批准合同实现 Canonical Query normalizer、公共/个人约束分类器和 schema/classifier version，拒绝 user/session/preference 进入公共 identity。
- [x] 9.6 为 shadow 写生成稳定的确定性 Family identity 和匹配依据；本阶段不启用相似匹配、Family read reuse 或响应切换。
- [ ] 9.7 实现 CanonicalSourceBatch normalizers，确保 source/external ID、canonical URL、captured time、watermark 和无二进制约束。
- [ ] 9.8 实现 SourceLocator、EvidenceItem 和 provenance 验证，缺来源链或 schema 不符的 item 进入隔离区。
- [ ] 9.9 实现绑定 shadow Family identity 的不可变 candidate Bundle repository、parent version 和内容哈希去重，但不切换当前读路径。
- [ ] 9.10 让 XHS/Place adapters 在保持 legacy 输出的同时 shadow 生成标准来源 batch 和 Evidence。
- [ ] 9.11 实现 `evidence_shadow` 开关、抽样率、写预算，以及包含 task/family/bundle/profile version 的 OTel spans 和 Prometheus 指标；默认关闭且不得改变 HTTP/SSE。
- [ ] 9.12 添加公共 Canonical Query/Evidence 不含 user/session/personal constraints 的信息流测试、OTel/日志脱敏测试和 Prometheus label-cardinality gate。
- [ ] 9.13 注入 Alembic interruption、transaction abort、profile/dimension mismatch、constraint 未分类、connector timeout、malformed item 和重复 shadow 写，验证无 current pointer 与 legacy 行为变化。
- [ ] 9.14 对 shadow Query/Evidence/embedding 与 legacy source/result 建立差异报告和人工审批 fixture 更新流程。
- [ ] 9.15 停用 shadow/profile dual-write、回旧 adapters 并确认附加表和 Alembic revision 可安全保留；将 B1 作为独立提交。

## 10. B2 Query Family, Explicit Refresh And Versioned Reuse

- [ ] 10.1 基于 B1 Canonical Query 实现“确定性规范键 -> PostgreSQL `pg_trgm` -> 前两级未达到批准置信度时进入 pgvector BGE-M3 `profile_v1`”三级检索，记录命中层级、规则/profile 版本、置信度、alias 和 Family merge/split 审计依据。
- [ ] 10.2 实现 Freshness Gate 的 fresh/incremental/new 三态及 verified time、coverage、watermark、active refresh 输入。
- [ ] 10.3 以稳定 Temporal Workflow ID 实现同 Family/范围/策略 single-flight，并由持久 history replay/reschedule 处理 worker 失效，以 PostgreSQL idempotency constraint/current-pointer CAS 阻止 late writer；不得使用 Redis lease、Redlock 或缓存值裁决权威提交。
- [ ] 10.4 实现 delta collection、candidate Bundle 验证、公共 feature/score 重算和 profile-aware 索引构建；分别以权威条件事务激活 embedding profile read pointer 与 Bundle current pointer，禁止跨 profile 查询，并保留旧 profile/Bundle 原子回滚路径。
- [ ] 10.5 实现按最大陈旧时间/最低覆盖度返回旧 Bundle 的明确 stale/partial 状态。
- [ ] 10.6 按 ADR 实现显式普通/强制刷新 use-case 和 API mapper，复用同一 Family/活动 task、执行授权并发出稳定任务事件。
- [ ] 10.7 实现 `query_reuse_read` shadow compare 和小流量 canary，不同时启用 personalization 或 background refresh scheduler。
- [ ] 10.8 添加示例自贡两问、公共/个人约束分类、确定性键/trigram/vector 各级命中、低置信度、显式刷新、并发命中、Temporal worker failure replay/reschedule 和 pointer rollback tests。
- [ ] 10.9 添加固定 BGE-M3 embedding fixture，验证 1024 维、cosine operator/index、profile 回填质量门禁、read pointer 原子切换/回滚、跨 profile 查询拒绝、模型版本变化拒绝静默复用，以及禁用 embedding 时确定性键/`pg_trgm` 路径可用。
- [ ] 10.10 注入 Evidence 写入、feature recompute、vector/trigram index update 和 activation transaction failure，证明旧 Bundle 连续可用。
- [ ] 10.11 验证未授权强制刷新不调用 Connector，兼容刷新请求合并到同一 Temporal workflow/task/event stream。
- [ ] 10.12 运行结果等价/相关性、各检索层召回/延迟、来源请求减少率和错误分类 gate，记录 canary 审批。
- [ ] 10.13 关闭 explicit refresh/read reuse、恢复 legacy realtime research 或上一 Bundle pointer；将 B2 作为独立提交。

## 11. B3 Personalization Memory

- [ ] 11.1 只通过 Alembic 编写只增不删的 `conversation_turns`、`session_state`、`memory_records`、`memory_events`、`preference_snapshots`、版本化摘要和 outbox migration，并用 SQLAlchemy 2 Async repositories 保证 user scope 与 transaction boundary。
- [ ] 11.2 实现 Session、Explicit、Inferred 和 Strategy Feedback 四类权威写入及来源事件、置信度、作用域、有效时间和 schema/policy version 元数据；embedding 只作为可重建派生索引，不作为记忆事实。
- [ ] 11.3 固化权威写序：同一 PostgreSQL transaction 写 conversation/memory 与 outbox，commit 后再消费 outbox 做 Redis invalidate/warm；任何缓存失败不得回滚或取代已提交事实。
- [ ] 11.4 实现 Preference Resolver 的“显式硬约束 > 当前会话 > 稳定显式偏好 > 推断偏好”规则和策略反馈边界。
- [ ] 11.5 实现 `ContextAssembler`，按“当前请求约束 -> 最近消息 -> 版本化摘要 -> 相关记忆 -> 相关 Evidence”组装临时模型上下文，并记录每部分 token budget、版本和引用。
- [ ] 11.6 实现 Redis 会话投影：每 session 最多最近 20 条、TTL 24 小时、user-scoped key；缓存 miss/过期从 PostgreSQL 重建，生产多 worker 禁止退化到进程内跨请求记忆。
- [ ] 11.7 实现 user-scoped cache/repository authorization、匿名会话隔离和已批准的匿名转实名迁移。
- [ ] 11.8 实现 `Domain allow-list ∩ request authorization ∩ personalization subset` 能力计算，禁止个性化启用未声明或未授权来源/工具。
- [ ] 11.9 实现版本化 Research Strategy，只调整深度、已授权来源优先级/子集、停止条件和 hard filters，不改变 Query Family identity。
- [ ] 11.10 实现公共候选后的最终 reranker 和 explanation refs，禁止 Personalization 获取公共 Evidence/score 写端。
- [ ] 11.11 实现收藏/忽略/点击/反馈的幂等 ingestion，并按 ADR 执行 consent/expiry/correction/export/delete。
- [ ] 11.12 添加优先级、ContextAssembler 顺序/token budget、outbox 重放、缓存失效、能力越权、两用户同 Bundle 不同排序、匿名、跨用户攻击和 PostgreSQL/Redis memory outage tests。
- [ ] 11.13 添加架构 gate，禁止 Mem0、Zep、LangGraph Store、Pydantic AI session 或 Redis 成为长期记忆权威，禁止公共 Family/Bundle/feature/score 在个性化前后发生内容哈希变化。
- [ ] 11.14 启用独立 `personalization` canary，观察默认策略、排序差异、cache hit/outbox lag 和隐私指标，不改变公共 refresh priority。
- [ ] 11.15 关闭 personalization 并回公共/legacy 排名，保留 PostgreSQL 权威记录并停止 Redis projection warm-up；将 B3 作为独立提交。

## 12. B4 Continuous Refresh And Media Pipeline

- [ ] 12.1 使用 Temporal 实现 Research/Refresh/Media 三个独立 Task Queue、worker pool、配额和优先级；共享 Workflow ID、retry、timeout、heartbeat、cancel 和重试耗尽后的 failed-workflow 检索/人工恢复合同，不引入 broker 式伪 `dead-letter` 语义。
- [ ] 12.2 实现 Refresh Coordinator 优先级，记录热门、即将过期、覆盖下降、新来源/时间窗和隐私安全反馈聚合理由。
- [ ] 12.3 实现 Refresh Workflow 的 base version、delta scope、watermarks、稳定 Workflow ID/idempotency key 和 PostgreSQL CAS activation；Redis 不参与 lease 或权威并发裁决。
- [ ] 12.4 实现 SourceGateway 的 source cursor/rate-limit/circuit，并确保 refresh failure 与真实空结果分离。
- [ ] 12.5 实现 MediaRef 选择、幂等 fetch、流式验证、SHA-256 去重、S3-compatible ObjectStore 和 MediaAsset metadata；生产 adapter 使用 boto3，本地/CI 使用 MinIO，数据库只存 object ref 和 provenance。
- [ ] 12.6 实现 MediaProcessor registry 的 supports/process、资源/时间配额和 DerivedArtifact versioning。
- [ ] 12.7 实现 EvidenceExtractor registry，将文本/媒体派生物转成带 confidence/provenance 的领域 Evidence。
- [ ] 12.8 实现 Refresh/Media 开关，并以 OpenTelemetry spans/metrics 和 Prometheus counters/gauges/histograms 暴露独立 worker health、Task Queue lag、throughput、retry exhaustion、object I/O 和 extractor error；默认关闭调度。
- [ ] 12.9 为 boto3 adapter 添加 multipart threshold、streaming backpressure、content type/size allow-list、server-side encryption 配置、signed URL TTL 和 orphan cleanup contracts。
- [ ] 12.10 注入 Temporal worker crash/replay、Activity duplicate/out-of-order completion、rate limit、retry exhaustion、processor OOM、MinIO/S3 timeout、corrupt/missing object、对象上传成功后 PostgreSQL metadata transaction abort 和 extractor schema failure；断言孤儿对象不进入业务读路径、无 dangling Evidence、Bundle pointer 不变且幂等清理最终执行。
- [ ] 12.11 验证所有失败不切 current pointer，旧 Bundle 继续服务，失败 workflow 可定位/重试/终止，前台 Research Task Queue 容量不被 Refresh/Media 耗尽。
- [ ] 12.12 验证 OTel/Prometheus 不记录凭据、签名 URL、用户偏好值或高基数 object/task ID label，并能以 trace correlation 定位 workflow/activity/object failure。
- [ ] 12.13 分别停止 Refresh 和 Media workers、禁用媒体 policy、回同步/旧 Bundle 路径；保留 Temporal history 和 S3 对象供审计，将 B4 作为独立提交。

## 13. B5 Travel Pack Proof

- [ ] 13.1 根据 Domain Contract 创建 Travel Pack manifest，声明景点、路线、季节、门票、拥挤度、游玩时长和适合人群。
- [ ] 13.2 定义 Travel EvidenceType、FeatureSet、ScoringPolicy、freshness/coverage/stopping、allowed tool input/output schema 和 Agent final output schema fixtures。
- [ ] 13.3 声明 Travel 所需来源能力并注册相应 SourceConnector，不创建 Travel 专属 runtime、证据库、刷新、记忆、队列或存储。
- [ ] 13.4 实现 Travel allowed tools 和输出 adapter，确保客户端不接收伪装成 Restaurant 的结果。
- [ ] 13.5 让 Travel 查询复用共享 Canonical Query、Family、Bundle、Coordinator、Personalization 和 Refresh ports。
- [ ] 13.6 添加 invalid/incomplete Pack、malformed tool input/output/final output、恢复后 schema version 固定、unauthorized tool、Connector failure 和 Pack exception 隔离 tests。
- [ ] 13.7 运行 Food 全回归及 Travel contract/e2e，证明 Travel 注册或失败不改变 Food 行为。
- [ ] 13.8 注销 Travel version 并确认共享核心和 Food 无需回滚；将 B5 作为独立提交。

## 14. Verification And Release Gates

- [ ] 14.1 在 Ubuntu/Windows 的 Python 3.12 blocking runtime 上执行 `uv sync --frozen`、`uv lock --check`、backend characterization、contract、architecture 和 failure-injection suites；锁文件或 interpreter 漂移必须失败。
- [ ] 14.2 在 macOS/arm64 和其他已批准 Python 版本上运行 probe suites，记录与 Python 3.12 基线的差异；probe 结果不得静默扩大生产支持矩阵。
- [ ] 14.3 在目标完整栈 PostgreSQL 16+pgvector/pg_trgm、Redis、Temporal、S3-compatible ObjectStore 和 Pydantic AI provider fake 上运行同一 backend contract suite；no-infra、Redis-only、PostgreSQL-only 和 InMemory EventBus 仅运行 legacy characterization，不得标记为目标生产支持模式。
- [ ] 14.4 在 Chromium desktop/mobile 及已批准 Firefox/WebKit 组合运行 HTTP/SSE reconnect、search、favorites、history 和 profile e2e。
- [ ] 14.5 在 UTF-8 中文、UTC、Asia/Shanghai、固定时钟和已批准 locale 下验证 canonicalization、timestamps 和 freshness。
- [ ] 14.6 构建 Python 3.12 non-root Linux image，并对 PostgreSQL 16、Redis、Temporal server/workers 和 MinIO Compose 栈运行 health、端口、卷权限、restart、Alembic migration 和三类 Task Queue smoke tests。
- [ ] 14.7 从空库和 N-1 fixture 运行唯一 Alembic upgrade path，执行 downgrade/restore 演练并扫描新代码，确认没有旁路 migration、运行时建表或与 SQLAlchemy metadata 冲突的 schema authority。
- [ ] 14.8 验证 BGE-M3 `profile_v1` 的模型标识、1024 维、cosine 索引、dual-write/backfill cursor、质量门禁、profile read pointer 原子切换/回滚、跨 profile 查询拒绝和旧 `VECTOR(4096)` 非破坏兼容。
- [ ] 14.9 运行 Redis contract gate：20 条/24 小时会话窗口、SSE 1 小时/`MAXLEN 1000`、缓存可重建、限流和短幂等；注入 Redis outage，验证无锁/租约/durable state 且无生产 in-memory fallback。
- [ ] 14.10 运行 Temporal replay、determinism、Pydantic AI model/tool Activity 映射、Workflow ID single-flight、worker rollout、三 Task Queue 隔离、PG/Temporal reconciliation、取消、重试耗尽和 failed-workflow operator runbook gate。
- [ ] 14.11 运行 S3/boto3/MinIO 合同和故障矩阵，覆盖大对象流式传输、hash 去重、加密配置、签名 URL、缺失/损坏对象、上传成功后 metadata transaction abort、不可发现孤儿的幂等清理和数据库不内嵌二进制。
- [ ] 14.12 运行 OpenTelemetry trace continuity/脱敏和 Prometheus 指标语义/cardinality gates，覆盖 API -> Temporal workflow/activity -> PostgreSQL/Redis/S3 的 correlation。
- [ ] 14.13 扫描运行时依赖和 imports，确认核心仅有一个 Pydantic AI Agent runtime 和一个 Temporal durable runtime，不含 ARQ、Celery、LangGraph、OpenAI Agents SDK、LiteLLM、Mem0、Zep、Redis lock/Redlock 或第二套迁移权威。
- [ ] 14.14 对每个 S0-S5/B0-B5 里程碑分别归档测试结果、指标阈值、feature binding、schema/profile version 和独立 revert 演练。
- [ ] 14.15 运行 `openspec validate --strict`、全量 CI 和 dependency graph 检查，确认没有跳过的 requirement scenario。
- [ ] 14.16 更新架构图、合同目录、运行手册和兼容性 ledger，使其由实际注册表/schema 生成或 CI 校验。
- [ ] 14.17 创建后续 legacy-contraction change，只在完整发布周期、无旧消费者和 restore 演练证明后计划删除旧路径/字段；本 change 首轮实现不执行删除。
