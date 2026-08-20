## Purpose

为所有研究领域提供同一套任务生命周期、模块职责和依赖合同，并在架构迁移期间保持既有 API、事件、数据与运行方式兼容。

## ADDED Requirements

### Requirement: 统一研究任务生命周期
系统 MUST 让 Food、Travel 及后续领域的研究请求共享同一套任务创建、规划、执行、刷新、恢复、完成和失败状态模型。体验层 MUST 只暴露稳定任务状态，不得包含来源平台逻辑或领域评分权重。

#### Scenario: 不同领域使用同一任务状态合同
- **WHEN** 客户端分别提交 Food 和 Travel 研究请求
- **THEN** 系统 MUST 通过同一任务状态集合与同一恢复语义报告两项任务的进度和终态

#### Scenario: 任务断线后恢复
- **WHEN** 客户端在研究任务执行期间断开，并在事件保留窗口内携带已确认位置重新连接
- **THEN** 系统 MUST 从已确认位置继续交付任务事件，不得创建语义重复的研究任务

#### Scenario: 断线游标已超出保留窗口
- **WHEN** 客户端携带的已确认位置已因时间或流长上限不再可重放
- **THEN** 系统 MUST 返回稳定的重放过期标识及当前权威任务快照或终态，不得伪造连续事件或创建新任务

### Requirement: 显式刷新使用共享任务和版本流程
体验与任务层 MUST 接收针对既有研究语义的显式刷新请求，并将其解析到同一 Domain、Canonical Query 和 Query Family。显式刷新 MUST 通过 Research Orchestrator 和 Freshness Gate 选择已批准的普通或强制刷新策略，MUST 合并兼容的活动刷新，并 MUST 通过稳定任务事件报告状态；它不得直接调用 Connector、原地修改当前 Evidence Bundle 或隐式创建用户专属公共证据。

#### Scenario: 用户刷新既有 Query Family
- **WHEN** 用户对已有研究结果发起显式刷新且没有兼容的活动刷新任务
- **THEN** 系统 MUST 为同一 Query Family 创建版本化刷新任务，并仅在新 Bundle 完整验证后切换当前版本

#### Scenario: 显式刷新命中活动任务
- **WHEN** 多个兼容刷新请求同时指向同一 Query Family 和刷新范围
- **THEN** 系统 MUST 让请求复用同一活动刷新标识和事件流，而不得重复请求相同来源

#### Scenario: 未获授权的强制刷新
- **WHEN** 请求要求绕过正常新鲜度策略但不满足已批准的授权或策略合同
- **THEN** 系统 MUST 返回稳定的策略拒绝结果，且不得直接启动 Connector 调用

### Requirement: 明确且互斥的模块职责
目标架构 MUST 采用以下唯一职责划分，并 MUST 通过自动化架构检查验证归属：

- 体验与任务：接收查询、追问、刷新和恢复请求，并输出稳定任务状态；不得拥有平台采集逻辑或推荐权重。
- Research Orchestrator：负责 Agent 规划、复用与刷新决策、并发调度和停止条件；不得直接访问来源 Connector。
- Evidence Intelligence：负责查询族、相似查询、新鲜度、来源采集、规范化、来源链和公共证据；不得保存用户私有偏好。
- Knowledge & Decision：负责实体消歧、特征计算、质量判断、公共评分、排序输入和解释数据；不得抓取来源数据。
- Personalization：负责会话记忆、显式与推断偏好、策略反馈和个性化重排；不得修改公共证据或公共评分事实。
- Domain Pack：负责领域实体、证据类型、特征、评分策略、输出结构和允许工具；不得复制 Agent Runtime、队列、记忆或证据库。
- Foundation：负责权威业务事实与稳定读模型的持久化适配、持久任务执行历史、可重建热状态、对象资产存储及可观测设施；不得承载领域业务语义。

#### Scenario: 职责归属检查
- **WHEN** 架构测试扫描一个模块对外声明的职责和依赖
- **THEN** 每项职责 MUST 归属于且仅归属于一个目标模块，违反“不得负责”边界的依赖 MUST 使检查失败

### Requirement: 单向依赖与端口访问
业务依赖 MUST 从体验与任务流向 Research Orchestrator，再通过显式端口流向 Evidence Intelligence、Knowledge & Decision、Personalization 和 Domain Pack，最终由 Foundation 适配器实现权威持久化、持久任务、热状态、对象资产及外部 I/O。跨模块调用 MUST 依赖调用方拥有的合同或 Gateway，不得依赖被调用方的内部实现。

以下依赖 MUST 被禁止：

- 体验与任务直接访问来源 Connector、数据库、持久任务实现、热状态客户端或领域内部实现。
- Research Orchestrator 直接调用平台 SDK、Spider、数据库驱动、对象存储客户端或具体 Connector。
- Evidence Intelligence 读取或写入用户私有记忆。
- Knowledge & Decision 直接执行网络采集。
- Personalization 修改公共 Evidence Bundle、公共特征或公共评分记录。
- Domain Pack 直接访问 Agent Runtime、数据库、持久任务、热状态、对象存储、其他平台内部实现或另一个 Domain Pack 的内部实现。
- Foundation 依赖领域实体或领域评分规则。

#### Scenario: 允许的跨模块调用
- **WHEN** Research Orchestrator 需要收集某个来源的证据
- **THEN** 它 MUST 调用 Evidence Intelligence 暴露的证据端口，并由 Source Gateway 选择已注册 Connector

#### Scenario: 禁止的跨模块调用
- **WHEN** 静态架构检查发现 Domain Pack 导入数据库适配器或 Orchestrator 导入具体平台 Connector
- **THEN** 检查 MUST 失败并报告依赖两端及违反的规则

### Requirement: 单一 Agent Runtime 与任务状态所有权
每个 `ResearchTask` MUST 由 Research Orchestrator 持有至多一个 Agent runtime；Agent 只能通过版本化 typed Tool Gateway 请求能力。Domain Pack MUST NOT 创建自己的 Agent loop、后台调度器或并发任务运行时。确定性采集、证据验证、特征/评分计算、刷新幂等身份和恢复协调 MUST 由普通服务或 `ResearchCoordinator` 负责，而不是由模型自由决定。`ResearchCoordinator` MUST 是 `ResearchTask` 和 `TaskEvent` 状态迁移的唯一业务写入者；体验层只能投影请求和事件，Foundation 只能持久化/投递。

#### Scenario: Domain Pack 请求工具
- **WHEN** Food 或 Travel Pack 需要来源能力
- **THEN** Pack MUST 声明所需 capability，由 Orchestrator 经 Tool/Source Gateway 调用，且 Pack 不得启动第二个 Agent loop

#### Scenario: Agent 产出无效步骤或结构
- **WHEN** Agent 返回未注册工具、非法 DAG、超出预算的步骤，或不符合活动输入输出模式的工具参数、工具结果或最终输出
- **THEN** Gateway 或 Coordinator MUST 依据合同拒绝或截断该步骤并记录稳定错误，不能让模型直接写任务状态或绕过 Gateway

#### Scenario: 任务状态并发写入
- **WHEN** Experience、Foundation worker 和 Coordinator 同时处理同一任务事件
- **THEN** 只有 Coordinator 计算并提交状态迁移；其他组件 MUST 使用命令/持久化端口，不能直接改写任务状态

### Requirement: 持久任务执行与工作负载隔离
研究、刷新和媒体任务 MUST 共享同一个可持久恢复的任务运行时，并使用隔离的工作负载队列、并发配额和重试策略。运行时 MUST 保存足以在进程或 worker 崩溃后重建任务进度的执行历史，并 MUST 使用稳定任务标识实现重复启动合并、取消、超时和至多一次成功终态。进程内后台任务和进程内队列 MUST NOT 作为目标生产模式的任务执行权威。

#### Scenario: Worker 在工具调用后崩溃
- **WHEN** worker 在一个可重试步骤完成后、任务终态发布前崩溃
- **THEN** 系统 MUST 使用同一任务标识恢复执行，并不得创建重复研究任务、重复提交成功终态或丢失已确认进度

#### Scenario: 可重试活动被重复投递
- **WHEN** 持久任务运行时因 worker 崩溃或确认丢失而重复投递同一活动
- **THEN** 活动 MUST 使用稳定幂等键抑制重复业务副作用，系统只能确认一个成功业务终态，不得把可能重试的底层调用声称为仅执行一次

#### Scenario: 后台刷新与前台研究竞争容量
- **WHEN** 媒体处理或批量刷新积压且新的交互研究请求到达
- **THEN** 独立工作负载配额 MUST 防止后台任务耗尽前台研究容量，同时保持统一的取消、重试和观测语义

### Requirement: 权威事实、执行历史和热状态分离
目标生产模式 MUST 将长期业务事实、任务执行历史和可重建热状态分配给不同的单一权威边界。会话消息、用户记忆、Evidence、Bundle 和稳定任务读模型 MUST 在权威事务提交后才可被确认；执行恢复 MUST 依赖持久任务历史；最近会话窗口、短期事件重放、入站幂等窗口、限流和热点缓存 MUST 被视为可丢失、可重建状态，MUST NOT 承担跨 worker 锁、刷新 single-flight、持久任务身份或业务事实权威。对象存储只能成为二进制资产内容的权威，其资产元数据、所有权和业务可见性 MUST 仍以已提交的权威事实为准。进程内 fallback 只能用于单进程开发和测试，MUST NOT 在生产多 worker 模式下静默启用。

#### Scenario: 权威存储在成功终态前失败
- **WHEN** 任务结果或记忆变更未能提交到权威事实存储
- **THEN** 系统 MUST 不发布引用该数据的成功终态，并 MUST 让持久任务运行时按稳定失败或重试策略处理

#### Scenario: 生产热状态后端不可用
- **WHEN** 生产多 worker 部署失去短期事件或缓存后端
- **THEN** 系统 MUST 保持已提交事实和持久任务历史不变，让已有持久任务依合同继续执行，仍允许读取已提交结果，并对新建实时研究或事件流请求返回稳定的依赖不可用结果；它 MUST NOT 伪装成具有跨 worker 恢复能力的内存模式

### Requirement: 有界实时事件热状态
每任务的实时事件流 MUST 最多保留 1000 条事件且有效期为 1 小时。事件因容量或时间超出热窗口后，MUST NOT 删除已提交的稳定任务快照或持久任务历史。

#### Scenario: 任务事件流超出热窗口
- **WHEN** 任务事件超过 1000 条或事件流已超过 1 小时有效期
- **THEN** 系统 MUST 按保留策略截断热重放流，保留权威任务快照或终态，并对超出窗口的恢复游标使用稳定的重放过期语义

### Requirement: 版本化内部合同
模块端口 MUST 使用版本化、可序列化的命令、事件和数据合同。合同演进 MUST 默认向后兼容；删除字段、更改字段含义或改变既有枚举值 MUST 通过独立的破坏性变更审批和迁移方案。

#### Scenario: 向后兼容地增加合同字段
- **WHEN** 提供方在内部合同中增加一个可选字段
- **THEN** 旧消费者 MUST 能忽略该字段并继续处理消息

#### Scenario: 未声明的破坏性合同变化
- **WHEN** 合同测试检测到必填字段、字段语义或枚举值发生不兼容变化
- **THEN** 验证 MUST 失败，且该变化不得进入迁移里程碑

### Requirement: 单一数据模式迁移权威
目标模式下的表、列、索引和数据库扩展 MUST 只由一套可版本化、可审计的模式迁移链管理。应用运行时 MUST NOT 用机会性建表、并行建表脚本或第二套模式定义绕过该迁移链。迁移 MUST 支持新建部署、从已支持旧版本升级、混合版本发布和已批准的回滚边界。

#### Scenario: 新建库与旧版库升级
- **WHEN** 一个空数据库和一个由上一支持版本创建的数据库分别执行完整迁移链
- **THEN** 两者 MUST 收敛到同一已声明模式版本和等价结构，旧数据 MUST 保持既有含义

#### Scenario: 扩展回填收缩发布
- **WHEN** 新旧应用版本在滚动发布期间同时运行
- **THEN** 模式迁移 MUST 使用可兼容的扩展、回填和延后收缩步骤，且收缩前 MUST 通过混合版本验证与回滚门禁

### Requirement: 保持既有外部兼容性
系统 MUST 在结构迁移前分别 characterize 服务器实际行为、客户端实际假设和文档声明，并由 authority gate 冻结可同时满足的兼容合同。结构里程碑 MUST 保持裁决后的合同；当前三侧矛盾、未证实入口或已记录缺陷不得被自动升级为永久合同，其修复 MUST 通过独立行为版本、测试和回滚审批。

- 既有 REST 路径、HTTP 方法、认证要求、状态码、请求字段、响应字段及序列化枚举值。
- SSE 连接方式、事件类型、事件字段、事件 ID、顺序、终态、心跳、断线恢复和重复事件处理语义。
- 当前已实现的搜索、追问、恢复、会话、收藏、历史和用户资料可观察行为；显式刷新由本 change 的新增目标行为合同定义而不属于迁移前兼容面，取消只有在后续合同明确规定时才构成外部能力。
- 现有美食结果结构、必填字段、排序含义、解释字段和空结果/错误表示。
- 现有会话 ID、用户 ID、任务 ID、turn ID 及其关联和幂等语义。
- 旧权威持久化记录的可读性、旧热状态键的迁移期兼容性、TTL/恢复语义，以及目标生产模式禁止静默内存 fallback 的版本化切换行为。
- 现有环境变量名称与默认值、应用入口、健康检查、容器端口和启动方式。
- 现有来源认证资料、Connector 输入输出、速率限制和超时/重试的对外可观察语义。

#### Scenario: 新旧路径的 characterization 对比
- **WHEN** 同一冻结输入、固定时钟、固定随机种子和相同来源夹具分别经过迁移前路径与新路径
- **THEN** 合同规范化后的 REST 响应、SSE 事件流、持久化副作用和错误分类 MUST 满足已批准的等价规则

#### Scenario: 显式来源查询投影在调用前验证
- **WHEN** 上游为某个 `source_scope` 成员提供 source-ready query projection
- **THEN** 投影 MUST 固定 source ID、language、renderer ID/version、查询文本和可选 locality，source/language 与请求隔离不匹配时 MUST 在调用 provider 前失败；Connector MUST NOT 把 Canonical Query 的枚举标识自行翻译为目标领域查询

#### Scenario: S3 旧 CollectRequest 未提供来源查询投影
- **WHEN** 兼容适配器接收一个在 S1 合同上创建且没有 `source_queries` 的旧请求
- **THEN** S3 MUST 仅使用已表征的 legacy fallback 并保持原输入行为；该 additive 字段的缺失不得成为新的 failure，后续目标行为启用前 MUST 由版本化 renderer 显式提供投影

#### Scenario: 读取迁移前数据
- **WHEN** 新版本读取由迁移前版本创建的会话、历史、收藏或搜索结果
- **THEN** 系统 MUST 在不要求用户重建数据的情况下恢复其既有含义

### Requirement: 模块级失败隔离
单一 Connector、Domain Pack、媒体处理器、Evidence Extractor、刷新任务、持久任务 worker、热状态后端、对象存储或非权威派生索引的失败 MUST 被限制在其所属边界内。系统 MUST 产生稳定错误分类和可关联的观测记录；如果兼容性合同允许降级，则 MUST 返回明确的降级状态而非伪装成完整结果。

#### Scenario: 有效来源返回真实空结果
- **WHEN** 一个 Source Connector 成功完成、返回通过 schema 验证的 payload，且其中没有任何 canonical item
- **THEN** 系统 MUST 将其记录为 `success_empty` 而不是 failure，MUST 保留成功尝试及 payload 已返回的来源水位，并 MUST 由声明的 coverage policy 评估该空尝试，而不得因空 item 列表生成伪造的 failure 或自动声称已满足覆盖度

#### Scenario: 来源失败与真实空结果保持可区分
- **WHEN** Source Connector 超时、被限流、依赖不可用、返回 malformed payload 或在边界抛出异常
- **THEN** 系统 MUST 产生带有稳定 `ErrorCategory` 和 `ErrorScope.SOURCE`（适配器在形成来源结果前失败时为 `PROVIDER`）的 `ContractError`，MUST 将该失败写入 `CanonicalSourceBatch.errors` 或等价来源错误端口，并 MUST NOT 将其编码为 `success_empty`

#### Scenario: 部分来源或条目失败时保留可用结果
- **WHEN** 同一研究聚合中至少一个来源尝试或条目分析/可选丰富步骤失败，但仍有一个或多个合格 canonical item 或可用餐厅结果
- **THEN** 系统 MUST 返回 surviving items，并以来源级错误与 coverage 元数据表达 `partial`；`partial` MUST NOT 成为新的 `TaskStatus`，且失败不得污染已验证的 Evidence 或阻止其他隔离来源继续

#### Scenario: 必需 XHS 来源耗尽时保持 legacy 投影
- **WHEN** 所有 XHS keyword attempts 都是 `success_empty` 或 failure，聚合中没有 notes
- **THEN** 内部 MUST 保留空与失败的区分并禁止把失败发布为成功 Evidence；S3 legacy streaming mapper MUST 输出 `step_error(step2)`、终端 `error` 和现有消息 `未找到相关笔记`，而不得新增 `partial` 字段，且已知 outer background projection 的 `completed` 行为 MUST 继续由 legacy policy 表征，直到 B0 版本化修复

#### Scenario: 直接 Python legacy 入口保留不同的无笔记投影
- **WHEN** 相同的无 notes 聚合通过 legacy `SearchExecutor.handle_new_search` 入口返回
- **THEN** compatibility mapper MUST 保留现有 `status="ok"`、空 recommendations 与既有 summary，不得在 S3 为统一 streaming 行为而把该 Python 合同改成 terminal error

#### Scenario: 可选 Amap/POI 失败降级为基础结果
- **WHEN** restaurant recommendations 已产生，但 Amap/POI 超时、限流、malformed、依赖不可用、空结果或单项丰富抛出异常
- **THEN** 系统 MUST 把通过验证的空 POI 结果记录为 `success_empty`，把其他条件记录为 optional-source failure/partial coverage，并保留基础餐厅 recommendation；S3 legacy mapper MUST 继续发送基本 restaurant、`result` 和 `done`，不得把可选丰富失败变成任务级 error

#### Scenario: 单一来源失败
- **WHEN** 一个可选 Source Connector 超时而其他合格来源仍可用
- **THEN** 研究任务 MUST 隔离该失败、记录来源级错误并依据覆盖度合同继续或明确标记部分结果

#### Scenario: 权威存储写入失败
- **WHEN** 新权威事实无法原子持久化
- **THEN** 系统 MUST 不发布引用该未提交事实的成功终态或新当前版本

#### Scenario: 对象资产写入失败
- **WHEN** 任务无法写入或验证某个 Evidence 必需的二进制资产
- **THEN** 系统 MUST 不发布引用该资产的 Evidence 或 Bundle，并 MUST 按稳定错误合同隔离、重试或标记覆盖缺失

### Requirement: 可追溯的架构决策
每个研究任务 MUST 能关联其领域、Query Family（如适用）、Evidence Bundle 版本、Domain Pack 合同版本、策略版本和用户重排版本，但观测数据 MUST 不泄漏用户私有偏好内容或来源认证资料。

#### Scenario: 调查一次推荐结果
- **WHEN** 运维人员使用任务关联标识调查结果来源
- **THEN** 系统 MUST 能定位所用公共证据版本和策略版本，同时对用户私有值和凭据执行脱敏

### Requirement: 端到端可观测与脱敏
系统 MUST 使用稳定关联标识连接体验请求、持久任务、Agent 步骤、Tool、Connector、Repository、Query Family、Evidence Bundle 和 Domain Pack 版本的观测记录。指标 MUST 至少区分接受、运行、重试、成功、失败、队列积压、外部调用延迟和基础依赖健康。观测属性 MUST 保持可控基数，MUST NOT 记录原始用户查询、用户标识、私有偏好值或认证资料。

#### Scenario: 跨 worker 调查任务失败
- **WHEN** 一项研究任务跨多个 worker 调用 Agent、Tool 和 Connector 后失败
- **THEN** 运维人员 MUST 能通过任务关联标识定位失败步骤、重试次数和依赖健康，且观测输出 MUST 已脱敏

#### Scenario: 观测属性包含私有或高基数值
- **WHEN** 候选日志、追踪或指标属性包含原始查询、用户标识、偏好内容、凭据或未受控高基数值
- **THEN** 观测边界 MUST 脱敏、丢弃或转换该属性，不得将其发布到共享观测后端
