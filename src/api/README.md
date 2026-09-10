# API 模块

`src/api` 是主应用的 FastAPI 传输层。完整的请求、响应、SSE、身份和错误合同见
[后端 API 指南](../../docs/backend-api.md)；本文件只说明代码归属和维护方式。

## 启动

从仓库根目录运行：

```bash
uv run uvicorn api.main:app --reload --port 8000
```

Swagger UI 位于 `http://localhost:8000/docs`，运行时 schema 位于
`http://localhost:8000/openapi.json`。

## 模块归属

| 路径 | 职责 |
|---|---|
| `main.py` | 应用生命周期、中间件、Composition Root 装配、router 注册 |
| `search/` | 统一搜索命令、状态/结果快照、legacy 与 reliable SSE 适配 |
| `platform.py` | 上游 Account Service 账号、登录、readiness 和 MCP 控制面 |
| `favorites.py` | 收藏读写 |
| `history.py` | 搜索历史读写 |
| `user.py` | 用户资料、统计和设置 |
| `help.py` | FAQ 和反馈接收 |
| `deps.py` | 身份解析和用户存储依赖 |
| `schemas.py` | 公共 FastAPI/Pydantic 模型 |

传输层只做协议适配：解析 HTTP 输入、调用 application port、映射稳定输出。Agent
规划、MCP 工具选择、研究状态、评论证据和店铺档案逻辑不应写入 route handler。

## 当前协议边界

- 搜索只有一个命令入口：`POST /v1/search/`。
- 默认 SSE 是 legacy；可靠任务流必须显式请求 `?sseVersion=v1` 并启用可靠运行时。
- `ResearchEvent v1` 和 `UserResearchProjection v1` 尚未挂载到当前 FastAPI transport。
- `X-User-Id` / `X-Device-Id` 只负责身份解析，不是认证或授权。
- 平台控制面禁止原始 Cookie、token、二维码字节和浏览器 profile 穿过主应用。

## OpenAPI 维护

不要手工编辑生成文件。路由或 schema 变化后执行：

```bash
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
uv run pytest -q tests/test_backend_api_documentation.py
```

生成结果：

- `contracts/openapi.yaml`：供外部接入和评审使用。
- `tests/fixtures/http/openapi.json`：运行时合同快照。

## 相关文档

- [完整后端 API 指南](../../docs/backend-api.md)
- [Account Service HTTP/MCP 接入](../../docs/account-services.md)
- [可靠任务回滚手册](../../openspec/changes/define-modular-architecture/runbooks/b0-reliable-task-rollback.md)
- [研究体验合同 schema](../../openspec/changes/freeze-research-experience-contracts/schema.md)
