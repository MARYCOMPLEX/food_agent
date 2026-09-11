# 后端 API 指南

本文是 `food-agent` 主应用后端的统一接入文档。内容以当前 FastAPI 路由、
Pydantic 模型、稳定映射器和合同测试为准，不把 OpenSpec 中的目标设计写成已上线能力。

## 1. 文档边界与权威来源

| 内容 | 权威来源 |
|---|---|
| 当前 HTTP 路由和请求模型 | 运行时 `GET /openapi.json` |
| 可提交的 OpenAPI 文件 | `contracts/openapi.yaml` |
| 测试快照 | `tests/fixtures/http/openapi.json` |
| 搜索与 SSE 运行时行为 | `src/api/search/routes.py` 及 HTTP/SSE 合同测试 |
| 上游账号服务合同 | `src/food_agent/contracts/account_service.py` |
| 未来研究体验事件合同 | `src/food_agent/contracts/research_experience.py` |

三份 OpenAPI 表达必须保持语义一致。生成与校验方法见[第 12 节](#12-openapi-生成与验证)。

这里的“主应用 API”与独立部署的 XHS、Dianping Account Service API 不是同一个服务：

- 本文记录浏览器和业务客户端访问的主应用路由。
- [Account Service 接入合同](account-services.md)记录主应用如何连接上游 HTTP/MCP 服务。
- `/v1/platform/*` 是主应用暴露的脱敏控制面和调试边界，不是上游服务原始 URL。

## 2. 启动与交互式文档

项目要求 Python 3.12。仓库根目录执行：

```bash
uv sync
cp .env.example .env
uv run uvicorn api.main:app --reload --port 8000
```

默认地址：

| 资源 | 地址 |
|---|---|
| API 基址 | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| 运行时 OpenAPI | `http://localhost:8000/openapi.json` |
| 健康检查 | `http://localhost:8000/health` |
| Prometheus 指标 | `http://localhost:8000/metrics` |

搜索依赖 LLM、经过策略放行的 MCP 工具，以及请求中选定的平台账号引用。只启动 HTTP
服务并不代表搜索链路已具备真实平台数据能力；先检查 `/v1/platform/readiness` 和
`/v1/platform/agent-tools/catalog`。

## 3. 通用约定

### 3.1 身份解析，不是认证

用户相关路由和平台控制面按以下优先级解析调用方：

1. `X-User-Id`：直接使用调用方给出的 ID。
2. `X-Device-Id`：查找或创建稳定的设备用户。
3. 两者都没有：使用共享的 legacy 匿名用户。

对需要完整 `User` 对象的依赖还有一个例外：若 `X-User-Id` 在数据库中不存在，
`get_current_user` 会回退到设备用户或匿名用户，而同一请求里的 `get_current_user_id`
仍返回原始 header。`GET /v1/user/profile` 等同时使用两者的端点可能因此组合出匿名资料和
另一个 ID 的统计。调用方应只发送后端已注册的用户 ID；这仍不能代替真正认证。

搜索路由接受同名的两个头，但当前实现的值转换**并不相同**：它优先使用原始
`X-User-Id`，其次直接使用原始 `X-Device-Id` 字符串，没有头时使用字面值
`anonymous`。它不会先经用户存储把设备 ID 转换成用户 UUID。

因此，当前要让平台账号注册所得 tenant 与搜索 MCP 工具上下文稳定一致，调用方必须在
两条链路都发送同一个 `X-User-Id`。只发送 `X-Device-Id` 会导致平台控制面使用解析后的
用户 UUID，而搜索使用原始设备字符串；这是现有实现限制，不是可依赖的隔离策略。

这些头目前**没有签名校验、登录态校验或授权证明**，因此只是身份选择机制。面向不可信
网络部署时，必须由认证网关校验主体并覆盖这些头，不能允许客户端任意声明
`X-User-Id`。

更重要的是，当前 `sessionId` 没有 ownership 校验：refine、recover、status、results 和
两种 SSE stream 都不会验证该会话是否属于身份头中的主体，部分读路由甚至完全不读取
这些头。知道一个 `sessionId` 的调用方即可读取或修改对应会话。认证网关除了覆盖身份头，
还必须在外层实施会话级授权；在后端补齐 ownership 约束前，不能把 session ID 本身当作
授权凭据。

示例：

```http
X-User-Id: 11111111-1111-1111-1111-111111111111
Content-Type: application/json
```

### 3.2 命名与时间

- 公共搜索 API 保留 camelCase，例如 `sessionId`、`accountRefs`。
- 平台控制面沿用上游合同的 snake_case，例如 `account_ref`、`flow_id`。
- 时间格式不是全局统一的：平台合同通常是 ISO 8601；收藏和历史的部分时间是 Unix 秒。
- 路径参数中的 `sessionId`、`restaurantId`、`flow_id` 都是不透明引用，不应由客户端解析。

### 3.3 响应没有单一全局外壳

最常见的成功形式是：

```json
{
  "success": true,
  "data": {}
}
```

但以下例外必须按端点处理：

- 收藏写操作返回顶层 `success`、`message`、`isFavorite`。
- 历史删除、用户业务校验和反馈接口可能返回顶层 `message` 或 `error`。
- `/health` 返回原始健康对象；`/metrics` 返回 Prometheus 文本。
- FastAPI 的常规 4xx 错误使用 `{"detail": ...}`。
- 平台控制面的校验和上游错误使用脱敏的
  `{"success": false, "error": "...", "message": "..."}`。
- 少数业务未命中仍返回 HTTP 200，例如搜索恢复未命中、收藏目标不存在、无效历史 ID。

客户端不能只根据 HTTP 2xx 判断业务成功，也不能假定每个响应都有 `data`。

### 3.4 JSON 校验

- 未特别说明的请求体使用 `application/json`。
- 平台控制面请求模型禁止未知字段，并拒绝 cookie、token、password、signature、QR
  payload、storage state、browser profile 等疑似凭据字段或二进制内容。
- 普通 FastAPI 模型的校验失败通常是 HTTP 422；平台控制面会返回不回显原请求体的
  `PLATFORM_REQUEST_INVALID`。

## 4. 完整端点清单

下面的清单由测试与运行时 OpenAPI 对照，当前共有 33 个路径、38 个 operation。

<!-- BEGIN API ENDPOINT INVENTORY -->
| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 进程存活检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET` | `/v1/favorites` | 当前用户收藏列表 |
| `POST` | `/v1/favorites` | 添加餐厅收藏 |
| `DELETE` | `/v1/favorites/{restaurantId}` | 删除餐厅收藏 |
| `GET` | `/v1/favorites/{restaurantId}/check` | 检查收藏状态 |
| `GET` | `/v1/help/faqs` | 静态 FAQ 列表 |
| `POST` | `/v1/help/feedback` | 接收反馈，当前不持久化 |
| `GET` | `/v1/history` | 分页读取搜索历史 |
| `POST` | `/v1/history` | 新增搜索历史 |
| `DELETE` | `/v1/history` | 清空搜索历史 |
| `DELETE` | `/v1/history/{historyId}` | 删除单条搜索历史 |
| `POST` | `/v1/platform/account-services/{platform}/invoke` | 调用账号绑定的上游能力 |
| `GET` | `/v1/platform/account-services/{platform}/tools` | 查看上游 MCP 工具描述 |
| `POST` | `/v1/platform/account-services/{platform}/tools/{tool_name}` | 调用上游 MCP 工具 |
| `POST` | `/v1/platform/accounts` | 注册平台账号引用 |
| `GET` | `/v1/platform/accounts/{platform}/{account_ref}` | 查询平台账号投影 |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login` | 启动平台登录 |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login/qr` | 启动 QR 登录 |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login/re-auth` | 启动重新认证 |
| `GET` | `/v1/platform/agent-tools/catalog` | 查看 Agent 可见工具投影 |
| `GET` | `/v1/platform/login/{flow_id}` | 查询登录流程状态 |
| `POST` | `/v1/platform/login/{flow_id}/cancel` | 取消登录流程 |
| `POST` | `/v1/platform/login/{flow_id}/poll` | 推进登录流程 |
| `GET` | `/v1/platform/login/{flow_id}/qr` | 获取限时 QR 展示引用 |
| `GET` | `/v1/platform/login/{flow_id}/status` | 查询登录流程状态的显式别名 |
| `GET` | `/v1/platform/readiness` | 查询账号服务和 MCP 就绪度 |
| `POST` | `/v1/search/` | 新建、追问或恢复研究会话 |
| `GET` | `/v1/search/results/{sessionId}` | 获取当前结果快照 |
| `GET` | `/v1/search/status/{sessionId}` | 获取当前进度快照 |
| `GET` | `/v1/search/stream/{sessionId}` | 订阅搜索 SSE |
| `PUT` | `/v1/user/notifications` | 合并更新通知设置 |
| `PUT` | `/v1/user/preferences` | 合并更新偏好设置 |
| `GET` | `/v1/user/profile` | 获取用户资料和统计 |
| `PUT` | `/v1/user/profile` | 更新用户资料 |
| `GET` | `/v1/user/settings` | 获取用户资料和完整设置 |
| `PUT` | `/v1/user/settings` | 批量合并设置 |
| `GET` | `/v1/user/stats/{type}` | 获取收藏、评论或访问明细 |
<!-- END API ENDPOINT INVENTORY -->

## 5. 搜索 API

### 5.1 统一命令入口

`POST /v1/search/` 根据 `sessionId` 和 `query` 的组合决定操作，不存在独立的
`/start`、`/refine` 或 `/recover` 路由。

| `sessionId` | `query` | 行为 | 未命中/无效结果 |
|---|---|---|---|
| 无 | 有 | 新建研究会话 | 受理后返回会话和 SSE URL |
| 有 | 有 | 在已有会话中继续研究 | 会话不存在返回 HTTP 404 |
| 有 | 无 | 恢复持久化会话 | 不存在时 HTTP 200 且 `success=false` |
| 无 | 无 | 无效新查询 | HTTP 400 |

规范路径包含末尾 `/`。FastAPI 当前可能把 `/v1/search` 重定向到 `/v1/search/`，客户端
不应依赖这个重定向。

分支判断使用字符串 truthiness，而不是“字段是否出现在 JSON 中”。当前模型也没有
`min_length`：空 `sessionId` 会被当作未提供；空 `query` 在没有有效 session 时触发
HTTP 400，在有 session 时进入 recover；只包含空格的 query 则是 truthy，会作为查询
继续受理。客户端应先 trim 并拒绝空输入，不能依赖这些偶然语义。

请求模型：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `string \| null` | `null` | 新建和追问时需要 |
| `sessionId` | `string \| null` | `null` | 追问或恢复的会话引用 |
| `location` | `object<string, number> \| null` | `null` | 约定使用 `{lat, lng}`；当前模型未限制键名 |
| `platforms` | `string[]` | `["xhs_pc", "dianping"]` | 非空、不可重复；可用值见下文 |
| `accountRefs` | `object<string, string>` | `{}` | 平台到不透明账号引用的映射 |
| `expectedSessionVersions` | `object<string, integer>` | `{}` | 平台账号会话版本固定值 |

有效平台是 `xhs_pc`、`xhs_creator`、`dianping`。生产研究通常先用 XHS 笔记和评论
发现证据、争议和店铺线索，再用大众点评补充店铺名称、地址、坐标、图片、评分、
菜品、活动等结构化档案。请求的平台还必须同时被部署配置和 Agent 工具策略放行。

新建请求：

```bash
curl -X POST http://localhost:8000/v1/search/ \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: 11111111-1111-1111-1111-111111111111' \
  -d '{
    "query": "成都玉林本地人常吃、评论有争议但值得去的馆子",
    "platforms": ["xhs_pc", "dianping"],
    "accountRefs": {
      "xhs_pc": "xhs-main",
      "dianping": "dianping-main"
    }
  }'
```

默认 legacy 受理结果：

```json
{
  "success": true,
  "data": {
    "sessionId": "session-example",
    "streamUrl": "/v1/search/stream/session-example",
    "action": "new_search"
  }
}
```

追问使用相同入口：

```json
{
  "sessionId": "session-example",
  "query": "只保留评论里提到具体必点菜的店",
  "platforms": ["xhs_pc", "dianping"],
  "accountRefs": {
    "xhs_pc": "xhs-main",
    "dianping": "dianping-main"
  }
}
```

追问成功会多返回 `turnId`，`action` 为 `refine`。恢复只发送
`{"sessionId":"session-example"}`；完成态恢复包含最新轮的 `query`、`restaurants`、
`summary`、`total`，以及 `turns`、`turnCount`、`fromDatabase`。

开启可靠任务生命周期后，新建受理结果改为：

```json
{
  "success": true,
  "data": {
    "sessionId": "session-example",
    "taskId": "task-example",
    "turnId": 1,
    "streamUrl": "/v1/search/stream/session-example?sseVersion=v1",
    "action": "new_search"
  }
}
```

可靠开关不是整个搜索 API 的存储切换。当前端点归属如下：

| 操作 | Legacy 会话 | Reliable 新建会话 |
|---|---|---|
| `POST /v1/search/` 新建 | 可靠开关关闭时受理 | 可靠开关开启时受理并返回 `taskId` |
| `POST /v1/search/` 追问 | 使用 legacy refine | **未接入 reliable refine** |
| `POST /v1/search/` 恢复 | 使用 legacy PostgreSQL/history/state | **未查询 reliable task store** |
| `GET .../status` | 使用 legacy state/emitter | **未查询 reliable projection store** |
| `GET .../results` | 使用 legacy result snapshot | **未查询 reliable result store** |
| `GET .../stream`（legacy） | 支持 | 不代表可靠任务事件 |
| `GET .../stream?sseVersion=v1` | 不适用 | 支持可靠生命周期事件 |

因此，当前可靠会话的对外闭环只有“新建受理 + reliable SSE v1”。拿它的 `sessionId`
调用追问、恢复、status 或 results 不能获得可靠任务的同一份状态；常见结果是 404 或
业务 `not_found`。内部 reliable policy 虽有 recover task 能力，但当前 HTTP recover
分支没有调用它。客户端在后端补齐统一 reliable session API 前，不应为可靠会话展示
这些操作。

### 5.2 状态与结果快照

`GET /v1/search/status/{sessionId}` 返回：

```json
{
  "success": true,
  "data": {
    "sessionId": "session-example",
    "status": "loading",
    "loadingSteps": []
  }
}
```

`loadingSteps` 是 legacy 六步显示投影，元素包含 `id`、`label`、`status`。具体状态快照
可能随任务阶段补充字段，当前 OpenAPI 将 `data` 保留为开放对象。

`GET /v1/search/results/{sessionId}` 的稳定最小形态是：

```json
{
  "success": true,
  "data": {
    "sessionId": "session-example",
    "restaurants": [],
    "summary": ""
  }
}
```

餐厅对象兼容字段包括 `id`、`name`、`chnName`、`address`、`city`、`district`、
`businessArea`、`tel`、`rating`、`cost`、`openTime`、`trustScore`、`oneLiner`、
`tags`、`pros`、`cons`、`warning`、`mustTry`、`blackList`、`photos`、
`providerRefs`、`profileUrl`、`sourceUrl`、`imageUrl`、`category`、`reviewCount`、
`averagePrice`、`latitude`、`longitude`、`coordinateSystem`、`geo`、
`recommendedDishes`、`promotions`、`profileMetadata`、`reviewCompleteness`、
`profileGaps` 和档案刷新时间/状态。字段可为空，客户端应按能力渐进渲染。

状态或结果会话不存在时返回 HTTP 404：`{"detail":"Session not found"}`。

## 6. 搜索 SSE

### 6.1 连接与恢复

端点：`GET /v1/search/stream/{sessionId}`。

```bash
curl -N \
  -H 'Last-Event-ID: mem-12' \
  'http://localhost:8000/v1/search/stream/session-example'
```

每一帧遵循标准 SSE：

```text
id: mem-13
event: step_start
data: {"step":"step2","message":"搜索小红书笔记","progress":16}

```

客户端应保存服务端 `id`，重连时发送标准 `Last-Event-ID` 请求头。服务端从该游标之后
继续读取，即语义是 exclusive。不存在 `lastEventIndex` 查询参数。

`sseVersion` 只接受：

| 值 | 行为 |
|---|---|
| 省略 | legacy SSE，当前默认 |
| `legacy` | 显式选择 legacy SSE |
| `v1` | 选择可靠任务 SSE v1 |
| 其他 | HTTP 406，并返回支持列表 |

### 6.2 Legacy SSE

事件类型：

| Event | 含义 |
|---|---|
| `step_start` | 一个显示步骤开始 |
| `step_done` | 一个显示步骤完成 |
| `step_error` | 一个显示步骤失败 |
| `progress` | 进度或心跳；心跳 payload 为 `{"heartbeat":true}` |
| `intent_parsed` | 意图解析中间结果 |
| `notes_found` | 笔记发现中间结果 |
| `analysis_done` | 评论分析中间结果 |
| `restaurant` | 单个餐厅增量，payload 形如 `{"restaurant": {...}}` |
| `result` | 汇总信息，包含 summary、total、filtered、steps |
| `error` | 终止失败 |
| `done` | 成功结束 |

`done` 和 `error` 是终止事件。六步显示投影是：解析用户意图、搜索小红书笔记、分析
评论内容、交叉验证筛选、补充店铺结构化档案、生成推荐结果。它只是前端进度投影，
不表示 Agent 内部必须按固定六次工具调用执行。

legacy 后端可使用内存或 Redis。内存重启会丢失事件；超出 Redis 保留窗口时，legacy
协议没有可靠的 `replay_expired` 通知，因此客户端不能在缺少事件时自行断言“完整恢复”。

### 6.3 可靠任务 SSE v1

可靠模式必须同时显式设置 `MODULAR_TARGET_ADAPTERS_ENABLED=true` 和
`MODULAR_RELIABLE_TASK_LIFECYCLE=true`，配置 `MODULAR_DATABASE_URL`、可解析的 Redis
连接、Temporal 地址/namespace/独立 task queue，并为 research queue 运行通过同一合同
注册的业务 worker。依赖不完整时启动或请求 fail-closed，不会静默退回内存模式。仓库
提供 worker builder 和 release qualification/smoke 脚本，但没有可直接宣称为生产
daemon 的统一 worker CLI；部署前应按
[可靠任务回滚手册](../openspec/changes/define-modular-architecture/runbooks/b0-reliable-task-rollback.md)
完成队列和持久化资格检查。

连接 `?sseVersion=v1` 后，响应包含 `X-SSE-Version: v1`。当前路由实际映射的事件只有：

| Event | 来源 | 关键字段 |
|---|---|---|
| `progress` | `task.accepted` | `schemaVersion`、`sessionId`、`taskId`、`turnId`、`progress` |
| `done` | `task.completed` | 公共标识和 `message` |
| `error` | `task.failed` / `task.cancelled` | 公共标识和 `{code,message,retryable}` |
| `replay_expired` | 游标已不在保留区间 | `reason`、`action=resync`、`snapshot`；随后关闭连接 |

可靠游标同样是 exclusive。`replay_expired` 没有事件 ID，客户端必须按 `snapshot`
重建当前状态，而不是继续拼接旧投影。snapshot 的当前形态为：

```json
{
  "snapshotVersion": 1734567890000,
  "status": "running",
  "resumeFromEventId": "1734567889000-1"
}
```

完成态把 `resumeFromEventId` 替换为
`{"terminal":{"event":"done","message":"搜索完成"}}`；失败或取消态的 terminal 为
`error`，并包含 `{code,message,retryable}`。`snapshotVersion` 来自 projection 的
`updated_at` 毫秒时间戳，不是可递增写入的客户端版本号。

### 6.4 三个容易混淆的“v1”

以下合同不是同一个东西：

| 名称 | 当前是否通过搜索 SSE 提供 | 说明 |
|---|---|---|
| Reliable SSE v1 | 条件提供 | `?sseVersion=v1`；当前只有 progress/done/error/replay_expired |
| `ResearchEvent v1` | **否** | 已冻结的未来增量研究体验事件合同 |
| `UserResearchProjection v1` | **否** | 已冻结的用户可见聚合投影合同 |

`ResearchEvent v1` 和 `UserResearchProjection v1` 已有模型、schema 和 projector 设计，
但当前 FastAPI 未挂载事件追加、snapshot、replay 或对应 transport adapter。前端目前
消费的是 legacy SSE 适配结果。不能因为可靠事件的 `schemaVersion` 为 `v1`，就把它
解释成 `research-event/v1`。

## 7. 平台账号服务与 MCP 控制面

### 7.1 就绪度和工具目录

`GET /v1/platform/readiness` 在未配置 registry 时仍返回 HTTP 200：

```json
{
  "success": true,
  "data": {"enabled": false, "ready": false, "services": []}
}
```

启用后，`services` 提供脱敏的服务 ID、协议、频道、状态、descriptor 版本、能力、MCP
工具状态和诊断信息。这里的 `ready` 才表示组合根看到的依赖就绪情况。

`GET /v1/platform/account-services/{platform}/tools` 返回远端刷新后的原始 MCP 描述：

```json
{
  "success": true,
  "data": [{
    "name": "notes.search",
    "description": "...",
    "input_schema": {},
    "output_schema": {},
    "capability": "notes.search",
    "capability_version": "account-service/v1",
    "side_effect": "read_only"
  }]
}
```

`GET /v1/platform/agent-tools/catalog` 返回经过应用策略二次过滤、提供给模型的稳定投影：

```json
{
  "success": true,
  "data": {
    "enabled": true,
    "snapshot_ref": "...",
    "generation": 3,
    "tools": [{
      "public_name": "xhs_pc__notes_search",
      "service_id": "xhs-account",
      "platform": "xhs_pc",
      "capability": "notes.search",
      "capability_version": "account-service/v1",
      "side_effect": "read_only",
      "policy_state": "allowed"
    }],
    "rejections": []
  }
}
```

未配置 catalog 时也是 HTTP 200，但 `enabled=false`、工具列表为空。Agent 实际可调用
集合以此投影为准，不以远端 `tools/list` 的全部结果为准。

### 7.2 直接工具调用与能力调用

原始 MCP 工具调用：

```http
POST /v1/platform/account-services/xhs_pc/tools/notes.search
Content-Type: application/json

{"arguments":{"query":"成都玉林苍蝇馆子"}}
```

主应用会覆盖注入 `tenant_ref`。成功 `data` 包含 `tool_name`、`is_error`、`content`。
此端点主要用于控制面验证；Agent 运行时使用固定 catalog 快照和 executor，不应由前端
自行复制编排逻辑。

账号绑定能力调用：

```json
{
  "account_ref": "xhs-main",
  "capability": "notes.search",
  "correlation_id": "request-01",
  "query": {"keyword": "成都玉林"},
  "expected_session_version": 4,
  "timeout_seconds": 30
}
```

`expected_session_version` 可选且至少为 1；`timeout_seconds` 大于 0.1 且不超过 300。
主应用从身份头注入 tenant，不接收客户端传入 tenant。

### 7.3 账号注册与查询

`POST /v1/platform/accounts`：

```json
{
  "platform": "dianping",
  "account_ref": "dianping-main",
  "alias": "点评测试账号",
  "permissions": ["places.search", "places.detail", "reviews.search"]
}
```

`account_ref` 也接受输入别名 `accountRef`、`account_id`。成功投影字段为：
`tenant_id`、`service_id`、`platform`、`account_ref`、`alias`、`status`、`health`、
`session_version`、`provider_subject_id`、`created_at`、`updated_at`。

`GET /v1/platform/accounts/{platform}/{account_ref}` 返回同一脱敏投影。账号由身份解析
出的 tenant 隔离；URL 中没有 tenant 参数。

`permissions` 当前只通过请求校验，`RemoteAccountServiceFacade` 调用 registry 时没有
转发该值。不能把它视为已经在上游生效的账号权限合同；真正的 Agent 工具授权仍由
服务 capabilities 和 `MODULAR_AGENT_MCP_TOOL_POLICY_JSON` 决定。

### 7.4 登录、二维码和 re-auth

推荐流程：

1. 注册账号引用。
2. `POST .../login/qr` 启动 QR 流程；请求体可省略。
3. `GET /v1/platform/login/{flow_id}/qr` 取得限时展示引用。
4. 客户端展示上游受控资源，并调用 `POST .../poll` 推进状态。
5. 使用 `GET .../status` 或 `GET /login/{flow_id}` 查看最终状态。

通用 `/login` 和 `/login/re-auth` 请求体：

```json
{
  "mode": "qr",
  "credential_ref": "vault-reference-only",
  "idempotency_key": "login-attempt-01"
}
```

`Idempotency-Key` 请求头优先于 body 的 `idempotency_key`。`credential_ref` 只能是不透明
引用，不能传手机号、Cookie 或 token。`/login/qr` 会强制 `mode=qr`。

启动、poll、cancel 的成功结果是 `data.flow` 包装；状态 GET 则直接把流程投影放在
`data`。流程投影包含 `flow_id`、`service_id`、`platform`、`account_ref`、`state`、
创建/过期/更新时间、QR 过期时间、provider subject 引用，以及可选错误码和错误消息。

QR 端点只返回 `flow_id`、`presentation_ref`、`expires_at`、`content_type`。其中
`presentation_ref` 是上游 `object_ref` 的不透明转写，可能是 fixture 引用或对象存储
引用；它**不是保证可放进 `<img src>` 的 URL**。主应用目前没有公开的
`presentation_ref` 解引用/下载端点，实际 UI 必须由部署侧提供受控的短期展示解析器，
不能把对象存储密钥或签名参数放进该字段。它也不返回 Cookie、二维码原始字节或可持久化
的 provider 登录材料。

流程 `state` 当前是上游提供的开放字符串，不是后端强制 enum。当前前端类型使用
`success`，本地 Account Service fixture 则以 `succeeded` 表示成功；在上游合同冻结
统一枚举前，两者都不能被宣称为唯一成功值。客户端必须对未知值容错。轮询没有服务端
规定的固定频率，应有上限地轮询并以 `expires_at`/`qr_expires_at` 为截止依据。

主应用只在进程内保存 `flow_id -> platform` 路由。主应用重启后，既有 flow 即使仍在
上游有效，当前无 platform 参数的 status/poll/QR 路由也会返回
`LOGIN_FLOW_NOT_FOUND`；客户端需要重新启动登录流程。

当前仓库内置的登录 modal 仍按旧响应类型读取：它期望 start/poll 直接得到 flow，并
期望 QR 数据含 `qr_code_url` 等字段；后端实际返回的是 `data.flow` 和上述
`presentation_ref` 合同。因此内置 UI 目前不能被视为这套登录 API 的端到端参考实现。

取消请求体可省略，也可发送 `{"reason":"user_cancelled"}`，原因最多 128 字符。

### 7.5 平台错误映射

下表只适用于 raw MCP tools 和 `/account-services/{platform}/invoke` 使用的 registry
错误映射：

| 上游分类 | HTTP 状态 |
|---|---:|
| `authentication` | 401 |
| `authorization` | 403 |
| `conflict` | 409 |
| `rate-limited` | 429 |
| `invalid` | 422 |
| `timeout` | 504 |
| 其他依赖失败 | 503 |

未启用控制面通常是 `PLATFORM_DISABLED`/503；未知平台为
`PLATFORM_INVALID`/422；未分类内部异常只返回 `PLATFORM_INTERNAL_ERROR`，不会泄漏上游
异常内容。

账号注册/查询/登录 facade 使用另一组当前映射：上游 authorization 变为
`PLATFORM_ACCOUNT_NOT_FOUND`/404，rate limit 变为 `LOGIN_RATE_LIMITED`/429，
authentication、conflict、timeout 和其余上游失败当前都折叠成对应错误码或
`PLATFORM_SERVICE_UNAVAILABLE`，HTTP 状态为 503。接入方应按具体 endpoint family
处理，不能把上表套到登录接口。

## 8. 收藏、历史、用户与帮助

### 8.1 收藏

- `GET /v1/favorites`：`data.items` 和 `data.total`。每项包含餐厅 ID、`addedAt`
  Unix 秒和关联餐厅对象。
- `POST /v1/favorites`：body 为 `{"restaurantId":"<32-char hash>"}`。餐厅必须已在
  restaurants 表；不存在时当前仍返回 HTTP 200、`success=false`。
- `DELETE /v1/favorites/{restaurantId}`：幂等删除并返回 `isFavorite=false`。
- `GET /v1/favorites/{restaurantId}/check`：返回 `data.isFavorite`。

### 8.2 历史

- `GET /v1/history?limit=20&offset=0`：`limit` 为 1 到 100，`offset` 不小于 0。
- `POST /v1/history`：body 字段为 `query`、可选 `resultsCount`（默认 0）和
  `location` 字符串。
- 历史项字段：`id`（如 `hist_12`）、`sessionId`、`query`、`status`、`timestamp`
  Unix 秒、`resultsCount`、`location`。
- `DELETE /v1/history/{historyId}`：格式无效时当前返回 HTTP 200、`success=false`。
- `DELETE /v1/history`：清空当前用户历史。

### 8.3 用户

- `GET /v1/user/profile` 返回用户字段和 `stats`。
- `PUT /v1/user/profile` 可更新 `name`、`username`、`email`、`location`。
- `GET /v1/user/settings` 返回资料以及合并默认值后的 `preferences`、`notifications`、
  `subscription`。
- `PUT /v1/user/settings` 以一层 merge 更新 `notifications`、`privacy`、`preferences`。
- `PUT /v1/user/preferences` 和 `/notifications` 接受开放 JSON 对象并分别 merge。
- `GET /v1/user/stats/{type}` 的 type 只能是 `saved`、`reviews`、`visited`。当前
  `reviews` 尚未实现，总是空列表；`visited` 最多读取 50 条历史且 total 是当前列表长度。

### 8.4 帮助

- `GET /v1/help/faqs` 返回进程内静态 FAQ。
- `POST /v1/help/feedback` 需要 `type`、`content`，可带 `contact`。当前端点只确认接收，
  **没有写入数据库或工单系统**。

## 9. 健康与观测

`GET /health` 是进程存活检查，不是依赖完整就绪检查。它不能替代平台 readiness、
数据库、Redis、Temporal 或真实账号 canary。

`GET /metrics` 暴露 Prometheus 文本，包括 HTTP 请求计数和耗时。OpenTelemetry/Phoenix
导出器从 Composition Root 注入；启动或 flush 失败会降级记录日志，不阻断业务服务。
相关配置使用 `MODULAR_OTEL_*` 和 `MODULAR_PHOENIX_*`，具体字段以
`TargetSettings` 为准。

## 10. 错误处理建议

客户端按以下顺序处理：

1. 先检查 HTTP 状态。
2. JSON 响应再检查 `success`，因为部分业务失败使用 HTTP 200。
3. SSE 以 `done` 或 `error` 结束；网络断开不是成功或失败结论。
4. 可靠 SSE 收到 `replay_expired` 时以 snapshot 重建；legacy SSE 缺少等价保证。
5. 平台 `authentication`、`provider-risk`、`conflict` 通常需要登录或 re-auth，而不是
   无限重试同一个采集调用。
6. `rate-limited` 和 `timeout` 应采用有上限的退避；不得为了成功而缩减合同要求的数据。

不要把上游错误 `message` 当稳定程序码；使用 `error`/category 和 HTTP 状态做分支。

## 11. 关键配置

### 11.1 LLM 与搜索

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI-compatible API key；不要提交到仓库 |
| `OPENAI_API_BASE` | OpenAI-compatible `/v1` 基址 |
| `DEFAULT_LLM_MODEL` | 默认模型 |
| `LLM_REASONING_EFFORT` | 推理力度 |
| `LLM_TEMPERATURE` | 温度；并非所有上游模型都接受 |
| `LLM_MAX_TOKENS` | 最大输出 token |
| `SEARCH_NOTE_LIMIT` | 笔记候选上限 |
| `SEARCH_MAX_RESTAURANTS` | 输出餐厅上限 |
| `ANALYZE_CONCURRENCY` | 评论分析并发度 |
| `PROFILE_CONCURRENCY` | 店铺档案补全并发度 |

### 11.2 会话与事件

| 变量 | 说明 |
|---|---|
| `EVENT_BUS_BACKEND` | `memory` 或 `redis` |
| `EVENT_STREAM_TTL_SECONDS` | Redis 事件保留时间 |
| `EVENT_STREAM_MAXLEN` | 单流近似最大事件数 |
| `SSE_HEARTBEAT_SECONDS` | legacy 心跳间隔 |
| `SSE_TIMEOUT_SECONDS` | 设置模型中的 SSE 超时名称；不要使用无效旧名 `SSE_TIMEOUT` |
| `MODULAR_RELIABLE_TASK_LIFECYCLE` | 可靠任务/SSE v1 开关，默认 false |
| `MODULAR_TARGET_ADAPTERS_ENABLED` | target adapter 总开关；可靠任务还要求它为 true |

当前路由没有把 `SSE_TIMEOUT_SECONDS` 实现成整个连接的硬截止时间；它是已声明的配置，
不是客户端可以依赖的断流 SLA。

### 11.3 平台与 Agent 工具

| 变量 | 说明 |
|---|---|
| `MODULAR_ACCOUNT_SERVICES_JSON` | 上游服务元数据 JSON |
| `MODULAR_ACCOUNT_SERVICES_FILE` | 上游服务元数据文件；与 JSON 互斥 |
| `MODULAR_ACCOUNT_SERVICE_REFRESH_SECONDS` | descriptor/tools 刷新间隔 |
| `MODULAR_AGENT_MCP_TOOL_POLICY_JSON` | Agent 工具 allow-list 策略 |

`auth_ref`、`credential_ref` 都是不透明引用，不能替换为真实凭据。当前默认
`AccountServiceRegistry` 构造 HTTP/MCP client 时没有把 `auth_ref` 解析成
`AuthHeaderProvider`，所以 stock Composition Root 无法直接连接要求认证 header 的上游
服务。代码支持由自定义 client factory 注入 `auth_headers`，但仓库尚无默认 secret
resolver 装配；在补齐前，只能连接不要求该 header 的可信内网服务或提供部署侧自定义
装配，不能把 token 直接写进 JSON。

### 11.4 CORS 与限流现状

- `CORS_ORIGINS` 是列表设置，环境变量应使用 JSON 数组，例如
  `CORS_ORIGINS='["http://localhost:5173"]'`；逗号分隔字符串当前会被
  pydantic-settings 在自定义 validator 之前拒绝。
- 当前 CORS allow-methods 只列出 GET、POST、DELETE、OPTIONS，跨域浏览器对 PUT 用户
  设置接口的预检可能失败；同源请求不受影响。
- `RATE_LIMIT_SEARCH` 有配置项，应用也安装了 slowapi 中间件，但当前搜索路由没有挂载
  limit decorator，不能把该值视为已生效的搜索限流合同。

## 12. OpenAPI 生成与验证

修改路由、请求模型、状态码或 OpenAPI 描述后执行：

```bash
uv run python scripts/export_openapi.py
```

该命令从 `api.main:app.openapi()` 确定性生成：

- `contracts/openapi.yaml`
- `tests/fixtures/http/openapi.json`

CI/本地只检查漂移而不写文件：

```bash
uv run python scripts/export_openapi.py --check
uv run --extra dev pytest -q tests/test_backend_api_documentation.py
```

不要手工维护两个生成文件。人类说明若与运行时 OpenAPI 冲突，以运行时和合同测试为
当前事实，并在同一变更中修正文档。

## 13. 当前明确限制

- `ResearchEvent v1` / `UserResearchProjection v1` 尚未接入 HTTP/SSE transport。
- reliable SSE v1 当前只投影任务生命周期，不包含评论证据、争议和店铺档案增量。
- legacy SSE 在游标过期时没有确定性缺口通知。
- 搜索的 status/results 使用开放 `data` schema，字段级兼容主要由映射器和 fixture 保证。
- 身份头不是认证；主应用自身没有面向公网的授权层。
- 搜索 refine/recover/status/results/SSE 没有 session ownership 校验；session ID 泄漏会
  形成跨用户读写风险。
- `X-Device-Id` 在平台控制面和搜索工具上下文中的转换不一致；跨链路绑定应使用同一个
  `X-User-Id`。
- `/health` 不是完整 readiness。
- QR `presentation_ref` 没有主应用公开解引用端点，登录 flow 路由映射也不能跨主应用
  重启恢复。
- 当前内置前端的登录响应类型仍与 `data.flow` / `presentation_ref` 后端合同不一致。
- 账号注册的 `permissions` 尚未转发，`auth_ref` 也尚未由默认 Composition Root 解析。
- 仓库有可靠 research worker builder 和资格脚本，但尚无统一生产 worker CLI。
- 多数平台和动态搜索响应仍缺少字段级 OpenAPI response model，生成客户端只能得到开放
  object；本指南和合同 fixture 暂时承担字段说明。
- 默认 `Dockerfile` 使用 Python 3.11，但 `pyproject.toml` 要求 Python 3.12；引用该文件的
  默认 compose 目前不是可复现的受支持部署路径。
- 反馈不持久化，用户 reviews 统计未实现。
- 跨域 PUT 预检和声明但未挂载的搜索限流仍是待处理的实现问题。

这些限制是当前代码事实，不是推荐的最终产品状态。
