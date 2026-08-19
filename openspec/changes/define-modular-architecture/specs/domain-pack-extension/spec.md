## Purpose

建立领域语义与来源访问相分离的扩展合同，使 Food、Travel 和后续领域在复用共享研究核心的同时，可以独立定义有效证据、决策规则和输出结构。

## ADDED Requirements

### Requirement: 完整的 Domain Contract
每个 Domain Pack MUST 通过版本化 Domain Contract 声明领域标识、实体类型、证据类型、证据有效性规则、特征、公共评分规则、个性化策略槽位、最终输出模式、允许工具及其输入输出模式、新鲜度/覆盖度策略和错误映射。缺少必需声明、模式无法验证或引用未注册工具的 Pack MUST 无法激活。

#### Scenario: 注册 Food Pack
- **WHEN** Food Pack 注册餐厅、菜品、口味、价格、本地性、广告嫌疑、评论可信度和餐厅推荐输出模式
- **THEN** 系统 MUST 在合同验证成功后激活该版本，并仅向它暴露声明允许的工具

#### Scenario: 不完整 Pack 注册
- **WHEN** 新 Domain Pack 未声明证据有效性、工具输入输出模式或最终输出模式
- **THEN** 注册 MUST 失败并列出缺失合同项，不得让部分 Pack 接收生产任务

#### Scenario: 工具或最终输出不符合活动模式
- **WHEN** 工具参数、工具结果或 Agent 最终输出不符合当前任务固定的版本化模式
- **THEN** Gateway MUST 拒绝该值并产生稳定模式验证错误，不得将未验证值传给下游模块或发布为成功结果

### Requirement: Domain Pack 与 Source Connector 分离
Source Connector MUST 只负责“去哪取数据”及将来源响应交给标准化边界；Domain Pack MUST 负责“如何理解数据”、有效证据定义、特征、评价和输出。任一 Connector MUST NOT 内嵌最终领域评分，任一 Domain Pack MUST NOT 直接使用平台内部 API 或认证实现。

#### Scenario: Travel Pack 使用多个来源
- **WHEN** Travel Pack 需要景点、路线、季节、门票和拥挤度证据
- **THEN** 它 MUST 声明所需来源能力，由 Research Orchestrator 经 Evidence Intelligence/Source Gateway 请求已注册 Connector，再由 Travel Pack 使用自身合同解释返回的标准 Evidence

#### Scenario: 平台 Connector 被多个领域使用
- **WHEN** 同一来源提供 Food 和 Travel 都可使用的 POI 数据
- **THEN** Connector MUST 输出来源级标准数据，而各 Domain Pack MUST 独立解释其领域含义

### Requirement: 共享核心不得被领域复制
新增领域 MUST 复用现有 Agent Runtime、任务状态、Query Family、Evidence Library、Refresh Coordinator、Personalization、持久任务执行、可重建热状态、权威存储、对象存储和可观测设施。Domain Pack 只能增加领域语义、领域策略、输出适配和确有需要的 Connector 能力。

#### Scenario: 增加 Travel Pack
- **WHEN** 团队增加旅游推荐能力
- **THEN** 交付物 MUST 不包含 Travel 专属的 Agent Runtime、公共证据库、用户记忆库、刷新协调器或基础设施副本

#### Scenario: 架构检查发现核心副本
- **WHEN** 新领域模块声明独立 Agent loop、持久任务运行时、热状态后端、记忆系统、对象存储或 Query Family 实现
- **THEN** 架构验证 MUST 失败并要求通过共享合同接入

### Requirement: 受控注册与禁止依赖
Domain Pack、Agent Tool、Source Connector、Media Processor、Evidence Extractor 和 Refresh Job MUST 通过各自注册表和版本化 Gateway 接入。扩展实例 MUST NOT 直接访问 Agent 内部状态、数据库驱动、持久任务实现、热状态客户端、对象存储客户端、其他平台内部或其他扩展实例的私有状态。所有基础能力访问 MUST 通过显式端口或 Gateway。

#### Scenario: 注册新的 Agent Tool
- **WHEN** New Agent Tool 声明能力、输入输出模式、权限、超时和错误合同并注册到 Tool Gateway
- **THEN** Research Orchestrator MUST 只能经由 Tool Gateway 调用它

#### Scenario: 扩展绕过 Gateway
- **WHEN** 静态或运行时合同检查发现 Connector 直接调用 Agent，或 Domain Pack 直接写数据库、启动持久任务、读写热状态或访问对象存储客户端
- **THEN** 扩展 MUST 被拒绝加载或隔离停用，并产生可定位的合同违规记录

### Requirement: 标准 Evidence 派生管线
Media Processor MUST 只生成带来源链、内容哈希和不透明对象引用的派生资产；Evidence Extractor MUST 将文本或媒体派生结果转换为 Domain Contract 接受的标准 Evidence。二进制内容 MUST 经共享对象存储端口流式写入和读取，MUST NOT 内嵌到 Agent 上下文、Domain Contract 或 Evidence 结构中。未经模式、来源链、对象完整性和领域有效性验证的派生结果 MUST NOT 进入公共 Evidence Bundle。

#### Scenario: 新媒体处理器加入管线
- **WHEN** 新处理器从图片提取菜单、价格或地点文字
- **THEN** 它 MUST 输出带内容哈希和对象引用的标准派生资产，再由 Food Evidence Extractor 验证并转换为相应证据类型

#### Scenario: 派生资产与领域模式不匹配
- **WHEN** Evidence Extractor 产出的字段不符合活动 Domain Contract
- **THEN** 系统 MUST 隔离该证据并报告验证错误，而不得污染当前 Bundle

#### Scenario: 派生资产对象不可用
- **WHEN** 派生资产的对象写入、哈希验证或读取失败
- **THEN** 系统 MUST 隔离该派生资产，不得创建可发布 Evidence 引用，并 MUST 按扩展失败合同重试、降级或终止任务

### Requirement: 领域输出兼容适配
Food Pack 的激活不得改变现有美食客户端依赖的结果字段、字段含义、序列化形式和排序解释。共享核心可使用统一内部结果信封，但 MUST 在体验边界通过版本化输出适配器维持既有合同。新领域 MUST 使用明确的领域输出模式，不得把 Food 专属字段强加给其他领域。

#### Scenario: 现有 Food 客户端访问迁移后系统
- **WHEN** 客户端使用迁移前支持的美食请求和响应版本
- **THEN** 输出适配器 MUST 返回合同等价的餐厅结果和事件，不要求客户端了解 Domain Pack

#### Scenario: Travel 结果生成
- **WHEN** Travel Pack 返回景点或行程推荐
- **THEN** 系统 MUST 按 Travel 输出模式呈现路线、季节、门票、拥挤度、游玩时长和适合人群，而不伪装成餐厅结构

### Requirement: 扩展级失败隔离与能力降级
单个 Domain Pack 或扩展实例的加载、执行或超时失败 MUST 不影响其他已注册领域和扩展。系统 MUST 根据 Domain Contract 判断是否允许替代 Connector、跳过可选派生步骤、返回部分覆盖或终止任务，并 MUST 保留稳定错误分类。

#### Scenario: Travel Pack 初始化失败
- **WHEN** Travel Pack 在启动时未通过合同验证
- **THEN** Travel 领域 MUST 标记为不可用，Food Pack 和共享任务服务 MUST 继续工作

#### Scenario: 可选媒体处理器超时
- **WHEN** 可选媒体处理器超时但文本证据已满足领域最低覆盖度
- **THEN** 系统 MUST 隔离该处理器并按合同返回注明媒体覆盖缺失的结果

### Requirement: 合同版本选择和回退
运行时 MUST 为每个任务固定 Domain Contract 及扩展合同版本。部署新版本时 MUST 支持并行验证或按任务路由；回退不得让进行中的任务在没有显式迁移的情况下切换语义版本。

#### Scenario: 新旧 Domain Pack 并行验证
- **WHEN** 新 Food Pack 版本进入影子或小流量验证
- **THEN** 每个任务 MUST 固定到一个合同版本，比较结果 MUST 能关联相同输入和公共证据版本

#### Scenario: 回退活动 Pack 版本
- **WHEN** 新版本违反输出或评分兼容性阈值
- **THEN** 新任务 MUST 可切回上一个兼容版本，进行中任务按固定版本完成或按已定义的失败策略终止

#### Scenario: Worker 恢复进行中的领域任务
- **WHEN** 执行领域任务的 worker 重启并从持久执行历史恢复
- **THEN** 任务 MUST 继续使用启动时固定的 Domain Contract、Tool 输入输出模式、Processor 和 Extractor 版本，不得因重启切换到新注册版本
