## Why

当前实现已具备搜索编排、来源采集、结果分析、会话与持久化等能力，但职责仍以美食场景和现有调用链组织，缺少可执行的模块边界、共享证据复用规则及跨领域扩展合同。现在需要先建立一个可验证、可分阶段迁移且保持现有接口兼容的架构基线，避免在增加旅游等领域时复制 Agent、证据、记忆和基础设施。

## What Changes

### 结构调整

- 定义唯一的通用研究骨架，并将现有职责映射到体验与任务、Research Orchestrator、Evidence Intelligence、Knowledge & Decision、Personalization、Domain Pack 和 Foundation 七个目标模块。
- 规定自上而下的依赖方向、Gateway/Contract 注册边界，以及 Agent、Connector、媒体处理器、Evidence Extractor、Domain Pack 和刷新任务的禁止依赖。
- 定义 PostgreSQL 业务事实、Temporal 持久执行历史、Redis 可重建热状态和 S3-compatible 对象存储四个互斥的基础设施权威边界。
- 给出可独立测试、提交和回退的分阶段迁移顺序，以及阶段级失败隔离和回滚条件。

### 目标行为

- 引入 `Canonical Query -> Query Family -> Freshness Gate` 流程，在公共语义相同的查询之间复用证据，并选择直接复用、增量刷新或全新研究。
- 增加显式刷新用例：刷新必须复用同一 Query Family、合并已有 in-flight 刷新，并通过稳定任务状态报告，不得绕过 Evidence 版本激活。
- 对 Evidence Bundle 采用追加版本而非原地覆盖；新版本触发特征与评分索引重算，同时保留旧版本用于追溯和回滚。
- 将会话记忆、显式偏好、稳定偏好/推断偏好和策略反馈用于当前用户的研究策略与最终重排，且不污染共享 Query Family 或公共证据。
- 通过 Domain Contract 接入 Food Pack、Travel Pack 和后续领域 Pack；新增领域只增加领域语义与所需 Connector，不复制共享运行时。
- 建立 characterization、contract、failure-injection 和跨平台测试基线，验证迁移前后兼容性及降级行为。

### 兼容性声明

- 不改变 authority gate 裁决并冻结后的 REST/SSE、会话、收藏、历史及用户资料合同；裁决前分别保持服务器事实、客户端假设和文档声明，不把当前互相矛盾的三侧描述为一个可同时满足的合同。
- 不改变现有美食查询的排序输出含义、来源认证配置和部署入口；现有 PostgreSQL/Redis/进程内降级语义先冻结为 characterization，再通过本 change 定义的独立行为里程碑迁移到已批准生产基线。
- 本 change 仅创建规范、设计和验证基线，不修改生产代码，也不在本阶段启用上述目标行为。

## Capabilities

### New Capabilities

- `modular-research-core`: 定义共享研究骨架的模块职责、依赖方向、禁止依赖、运行时端口和兼容性边界。
- `query-family-evidence-reuse`: 定义公共查询规范化、Query Family 复用、新鲜度判断、增量刷新及版本化证据生命周期。
- `personalization-memory`: 定义四层用户记忆、冲突优先级、用户隔离，以及只在策略和最终排序阶段生效的规则。
- `domain-pack-extension`: 定义 Food/Travel/后续领域的 Domain Contract、注册机制、来源与媒体扩展点及共享核心复用要求。

### Modified Capabilities

- 无。仓库当前没有既有 OpenSpec capability；现有可观察行为作为新架构的兼容性基线保留。

## Impact

- 规划涉及未来对 `src/api`、`src/xhs_food/orchestrator`、`agents`、`services`、`spider`、`schemas`、`events`、`providers`、`frontend`、数据库迁移、队列/缓存和测试目录的分阶段调整。
- 未来实现将新增模块端口、Domain Pack 注册、Query Family/Evidence Bundle 持久化与刷新协调能力，但应通过适配器保持现有 API、SSE、存储数据和配置合同。
- 本 proposal 不新增运行时依赖、不执行数据迁移、不修改部署拓扑或生产代码。
