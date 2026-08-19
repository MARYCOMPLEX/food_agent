## Purpose

通过公共语义查询族、新鲜度判断和不可变证据版本，在相似请求之间安全复用来源证据，并对过期或缺失部分执行可追溯的增量刷新。

## ADDED Requirements

### Requirement: 公共 Canonical Query 签名
系统 MUST 将研究请求规范化为只包含 `domain`、`geo`、`intent`、`audience`、`constraints`、`time_range` 和 `freshness_policy` 的公共 Canonical Query 签名。签名中的 `constraints` MUST 只包含经版本化 Domain Contract 规则分类为公共语义的约束投影；签名字段 MUST 使用稳定规范化规则和显式模式版本。

用户 ID、会话 ID、显式偏好、推断偏好、收藏、点击和个人策略反馈 MUST NOT 进入共享 Query Family 的身份主键。

#### Scenario: 个人口味不同但公共语义相同
- **WHEN** 两个用户提交相同地点、意图、受众、公共约束、时间范围和新鲜度策略，但个人口味不同的查询
- **THEN** 系统 MUST 将两者解析到同一公共 Query Family，并在最终个性化阶段处理口味差异

#### Scenario: 公共约束改变
- **WHEN** 两个查询的领域或地理范围等公共签名字段不同
- **THEN** 系统 MUST 生成不同签名，除非版本化的 Query Family 归并规则明确证明它们等价

### Requirement: 公共约束与个人约束必须先分类
系统 MUST 在生成共享签名前，把输入约束分类为公共语义约束或当前用户/会话的个人约束。口味、忌口、个人预算和个人出行偏好等被 Domain Contract 分类为个人的约束 MUST 只进入 Personalization 策略，不得进入公共 `constraints`、Family identity 或 Evidence。未能按活动规则分类的约束 MUST NOT 被静默写入共享签名；系统只能请求澄清或按已批准策略执行不共享的研究。

#### Scenario: 两用户个人约束不同
- **WHEN** 两个用户的公共语义相同，但分别声明不同口味、忌口或个人预算
- **THEN** 系统 MUST 生成相同公共 Canonical Query，并把差异放入各自隔离的 Personalization 输入

#### Scenario: Domain Contract 声明公共约束
- **WHEN** 活动 Domain Contract 将某个约束明确分类为会改变公共研究语义
- **THEN** 系统 MUST 将其规范化到公共 `constraints`，并用规则版本记录分类依据

#### Scenario: 约束无法分类
- **WHEN** 输入约束不匹配活动 Domain Contract 的任何公共或个人分类规则
- **THEN** 系统 MUST NOT 用该约束命中或创建共享 Query Family，并 MUST 采用已批准的澄清或不共享路径

### Requirement: 可解释的 Query Family 匹配
系统 MUST 根据版本化规则将 Canonical Query 解析到 Query Family，并 MUST 保存匹配依据、规范化版本和置信度。低于已配置置信阈值的相似查询 MUST 创建候选或新 Family，不得静默合并公共语义不同的证据。

#### Scenario: 自贡地方美食相似查询
- **WHEN** “自贡哪些本地人吃的美食”与“刚到自贡旅游应该吃什么”被规范化为相同的 `自贡 / 地方美食 / 餐饮推荐` 公共语义
- **THEN** 两个查询 MUST 可共享笔记、评论、餐厅实体、POI、可信度、时效和媒体派生证据，同时保留各自的排序策略输入

#### Scenario: 匹配置信度不足
- **WHEN** Family 匹配结果低于策略阈值
- **THEN** 系统 MUST 避免直接复用并记录新建或人工复核所需的匹配理由

### Requirement: 版本化相似性索引配置
确定性键、词法相似索引和语义向量索引 MUST 被视为 Query Family 匹配规则下的可重建派生数据。每个语义索引配置 MUST 记录模型标识、向量维度、距离度量、归一化规则和配置版本。系统 MUST NOT 跨不兼容配置比较向量或原地改变已发布索引的向量维度。新配置 MUST 通过独立索引、可重放回填、质量验证和原子激活切换，并 MUST 保留前一配置以供回滚。

#### Scenario: 切换到不同维度的语义配置
- **WHEN** 新语义索引配置的模型、维度、距离或归一化规则与当前配置不同
- **THEN** 系统 MUST 建立并回填独立索引，在质量和完整性门禁通过后原子切换，不得对旧向量列或索引做原地维度变更

#### Scenario: 派生相似性索引不可用
- **WHEN** 语义或词法派生索引缺失、过期或查询失败
- **THEN** 系统 MUST 仅使用仍可验证的确定性键或其他已批准匹配阶段，低于置信阈值时 MUST 避免复用而不是猜测合并 Family

### Requirement: 三态 Freshness Gate
系统 MUST 使用 Evidence Bundle 的最近验证时间、新鲜度窗口、覆盖度、来源更新时间水位和活动刷新状态，对每次查询选择且仅选择以下路径之一：

- 证据仍在新鲜窗口且覆盖度合格：直接复用。
- 证据过期或覆盖度部分下降但已有大部分有效覆盖：仅刷新缺失、过期或水位变化的证据。
- 没有合格 Query Family 或现有证据不可用：创建全新研究任务。

#### Scenario: 新鲜证据直接复用
- **WHEN** 当前 Evidence Bundle 在新鲜度窗口内且满足领域覆盖阈值
- **THEN** 系统 MUST 返回该版本并不得重复请求已覆盖来源

#### Scenario: 部分证据过期
- **WHEN** 当前 Bundle 的一个来源分区过期而其余分区仍满足复用条件
- **THEN** 系统 MUST 只计划过期或缺失分区的增量刷新

#### Scenario: 没有可复用 Family
- **WHEN** 请求无法匹配任何合格 Query Family
- **THEN** 系统 MUST 创建新的研究任务和初始 Evidence Bundle 流程

### Requirement: 刷新去重与并发一致性
同一 Query Family、相同刷新范围和兼容策略 MUST 生成稳定幂等标识，并在同一时间至多存在一个生效刷新任务。并发请求 MUST 复用持久任务所有者、读取已发布版本或等待新版本，不得对相同来源产生重复刷新风暴。任何新版本激活 MUST 使用权威存储中的条件更新，迟到执行者不得覆盖更新版本。

#### Scenario: 并发命中过期 Family
- **WHEN** 多个请求同时命中同一个已过期 Query Family
- **THEN** 系统 MUST 让所有兼容请求解析到同一稳定持久任务身份，并让其余请求复用活动刷新标识或已发布的陈旧版本

#### Scenario: 刷新 worker 失效
- **WHEN** 执行刷新的 worker 失效且没有提交新版本
- **THEN** 持久任务运行时 MUST 在同一任务身份下从已确认历史安全恢复或重新调度，且任何迟到提交不得通过条件更新覆盖更新的已发布版本

### Requirement: 不可变 Evidence Bundle 版本
新增、修正或重新验证的证据 MUST 形成新的不可变 Evidence Bundle 版本。系统 MUST 原子发布新的当前版本指针，并保留旧版本、来源链、采集时间、内容哈希、规范化版本和父版本关系用于追溯与回滚。

#### Scenario: 成功发布增量证据
- **WHEN** 增量刷新完成规范化、验证和派生计算
- **THEN** 系统 MUST 创建新 Bundle 版本并原子更新当前指针，旧版本保持可读且内容不变

#### Scenario: 新版本构建失败
- **WHEN** 增量证据在验证或派生计算期间失败
- **THEN** 当前版本指针 MUST 保持不变，失败草稿不得作为可复用证据发布

### Requirement: 来源链和证据标准化
每条标准 Evidence MUST 关联其原始来源、Connector、获取时间、来源更新时间水位、规范化器版本、许可/可见性范围及派生链。媒体或文本派生结果只有通过 Evidence Extractor 转换并验证后才能进入 Evidence Bundle。二进制资产 MUST 使用内容哈希和不透明对象引用与 Evidence 关联；资产元数据、来源链、权限和业务可见性 MUST 由权威事实控制。

#### Scenario: 媒体派生证据进入 Bundle
- **WHEN** 媒体处理器产出 OCR、转录或视觉标签
- **THEN** Evidence Extractor MUST 生成符合领域证据类型的标准 Evidence 并保留到原始媒体的派生链

#### Scenario: 缺失来源链
- **WHEN** 候选证据无法关联原始来源或规范化版本
- **THEN** 系统 MUST 拒绝将其发布到可复用的 Evidence Bundle

#### Scenario: 对象资产写入或完整性验证失败
- **WHEN** 候选 Evidence 引用的二进制资产未成功写入、内容哈希不匹配或无法读取
- **THEN** 系统 MUST 拒绝发布该 Evidence 及引用它的 Bundle，当前已发布版本 MUST 保持不变

#### Scenario: 资产写入后元数据事务失败
- **WHEN** 二进制资产已写入但其权威元数据或 Evidence 事务未提交
- **THEN** 该资产 MUST NOT 对业务读路径可见，并 MUST 能由幂等清理或后续重试处理

### Requirement: 公共派生计算与用户重排分离
发布新 Evidence Bundle 后，系统 MUST 基于该公共版本重算实体、特征、质量判断和公共评分索引。用户策略只能在读取公共计算结果后进行筛选或重排，不得产生用户专属 Bundle 或修改公共索引。

#### Scenario: 同一 Bundle 服务不同用户
- **WHEN** 本地口碑优先用户和首次到访便利优先用户读取同一 Query Family
- **THEN** 系统 MUST 复用同一 Evidence Bundle 和公共特征，并分别提高本地性权重或游客友好度与交通便利权重

### Requirement: 刷新调度优先级
后台刷新 MUST 使用可观测且可配置的优先级，至少考虑热门程度、距过期时间、覆盖度下降、新来源或新时间窗口，以及用户反馈所显示的公共事实变化频率。个人身份和私有偏好不得成为公共 Family 优先级键。

#### Scenario: 即将过期的热门 Family
- **WHEN** 队列容量有限且一个热门 Family 即将过期
- **THEN** 调度器 MUST 能将其排在低使用率且仍新鲜的 Family 之前，并记录优先级原因

### Requirement: 刷新失败时的可控陈旧读取
刷新失败时，只有仍满足领域最大陈旧时间和最低覆盖度的旧 Bundle 才能继续提供；结果 MUST 明确携带陈旧度和部分覆盖状态。超过限制的 Bundle MUST 不得伪装为新鲜结果。

#### Scenario: 可接受的陈旧版本
- **WHEN** 增量刷新失败但当前 Bundle 未超过最大陈旧时间且覆盖度仍合格
- **THEN** 系统 MUST 可返回当前版本，同时标记其验证时间、陈旧状态和刷新失败类别

#### Scenario: 陈旧版本超出边界
- **WHEN** 当前 Bundle 超过领域最大陈旧时间或低于最低覆盖度
- **THEN** 系统 MUST 返回明确的不可满足或研究失败状态，而不是完整成功结果
