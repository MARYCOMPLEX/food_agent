# 🌐 API 模块

**FastAPI 服务层** — RESTful + SSE 流式接口

---

## 📋 概述

API 模块基于 FastAPI 构建，提供 RESTful 接口和 SSE 流式推送，支持多用户会话管理。

---

## 🚀 快速启动

```bash
# 开发模式
uvicorn src.api.main:app --reload --port 8000

# 生产模式
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

访问 http://localhost:8000/docs 查看 Swagger 文档

---

## 📂 文件结构

| 文件 | 职责 |
|------|------|
| `main.py` | 应用入口，中间件配置 |
| `routes.py` | 通用路由 |
| `search.py` | 搜索相关端点 (SSE) |
| `favorites.py` | 收藏功能 |
| `history.py` | 历史记录 |
| `user.py` | 用户管理 |
| `help.py` | 帮助与反馈 |
| `schemas.py` | 请求/响应模型 |
| `deps.py` | 依赖注入 |

---

## 🔗 API 端点概览

### 搜索

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/v1/search/` | 新建或继续一轮研究 |
| `GET` | `/v1/search/stream/{sessionId}` | SSE 流式接收结果 |
| `GET` | `/v1/search/status/{sessionId}` | 查询状态 |
| `GET` | `/v1/search/results/{sessionId}` | 查询结果 |

### 收藏

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/v1/favorites` | 获取收藏列表 |
| `POST` | `/v1/favorites` | 添加收藏 |
| `DELETE` | `/v1/favorites/{id}` | 取消收藏 |
| `GET` | `/v1/favorites/{id}/check` | 检查收藏状态 |

### 历史记录

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/v1/history` | 获取搜索历史 |
| `POST` | `/v1/history` | 添加记录 |
| `DELETE` | `/v1/history/{id}` | 删除单条 |
| `DELETE` | `/v1/history` | 清空全部 |

### 用户

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/v1/user/profile` | 获取资料 |
| `PUT` | `/v1/user/profile` | 更新资料 |
| `GET` | `/v1/user/settings` | 获取设置 |
| `PUT` | `/v1/user/settings` | 更新设置 |

---

## 🔐 认证机制

通过 HTTP Header 识别用户：

```
X-Device-Id: <设备唯一标识>   # 推荐，自动创建用户
X-User-Id: <用户UUID>         # 可选，显式指定
```

### 依赖注入

```python
from src.api.deps import get_current_user

@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    return user
```

---

## 📡 SSE 流式响应

### 事件类型

| Event | 说明 |
|-------|------|
| `step_start` | 步骤开始 |
| `step_done` | 步骤完成 |
| `step_error` | 步骤失败 |
| `restaurant` | 单个餐厅数据 |
| `result` | 最终汇总 |
| `done` | 流结束 |
| `progress` | 心跳保活 |

### 流程示例

```
Client                          Server
  |                               |
  |-- POST /search/ -------------->|
  |<---- { sessionId } -----------|
  |                               |
  |-- GET /search/stream/{id} --->|
  |<---- step_start(step1) -------|
  |<---- step_done(step1) --------|
  |<---- step_start(step2) -------|
  |<---- ...                      |
  |<---- restaurant × N ----------|
  |<---- result ------------------|
  |<---- done --------------------|
  |                               |
```

### 继续研究与恢复

用于从历史记录恢复完整的多轮对话，返回所有轮次的搜索结果。

**请求示例**:
```bash
curl -X POST http://localhost:8000/v1/search/ \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"<sessionId>","query":"继续分析评论争议"}'
```

**响应示例** (status: completed):
```json
{
  "success": true,
  "data": {
    "sessionId": "abc-123-def",
    "status": "completed",
    "turnId": 2,
    "query": "便宜点的",
    "restaurants": [...],
    "summary": "根据您的要求...",
    "total": 3,
    "turns": [
      {
        "turnId": 1,
        "query": "成都火锅推荐",
        "restaurants": [...],
        "summary": "为您找到以下火锅店...",
        "total": 8,
        "createdAt": "2026-01-09T15:30:00"
      },
      {
        "turnId": 2,
        "query": "便宜点的",
        "restaurants": [...],
        "summary": "根据您的要求...",
        "total": 3,
        "createdAt": "2026-01-09T15:31:00"
      }
    ],
    "turnCount": 2,
    "fromDatabase": true
  }
}
```

**响应示例** (status: loading):
```json
{
  "success": true,
  "data": {
    "sessionId": "abc-123-def",
    "status": "loading",
    "streamUrl": "/v1/search/stream/abc-123-def?lastEventIndex=5",
    "lastEventIndex": 5,
    "message": "搜索进行中，请连接 SSE 流继续接收"
  }
}
```

**响应示例** (status: not_found):
```json
{
  "success": false,
  "data": {
    "sessionId": "abc-123-def",
    "status": "not_found",
    "message": "会话不存在或已过期"
  }
}
```

**状态说明**:

| status | 说明 | 处理方式 |
|--------|------|----------|
| `completed` | 搜索已完成 | 直接使用 `turns` 渲染历史 |
| `loading` | 搜索进行中 | 连接 `streamUrl` 继续接收 |
| `interrupted` | 搜索中断（服务重启） | 提示用户重新搜索 |
| `error` | 搜索失败 | 显示错误信息 |
| `not_found` | 会话不存在 | 返回首页 |

---

## ❌ 错误处理

### 统一响应格式

**成功**:
```json
{
  "success": true,
  "data": { ... }
}
```

**错误**:
```json
{
  "success": false,
  "error": "error_code",
  "message": "错误描述"
}
```

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 🧪 测试

```bash
# 健康检查
curl http://localhost:8000/health

# 新建搜索
curl -X POST http://localhost:8000/v1/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "成都火锅推荐"}'

# SSE 流式接收
curl -N "http://localhost:8000/v1/search/stream/{sessionId}"
```

---

## ⚙️ 配置

```bash
# 服务配置
API_HOST=0.0.0.0
API_PORT=8000

# CORS
CORS_ORIGINS=["http://localhost:3000"]
```

---

## 📚 相关文档

- [API 完整规范](../../internal-docs/API.md)
- [SSE 事件规范](../../internal-docs/SSE_SPEC.md)
- [前端集成指南](../../internal-docs/FRONTEND_SSE_GUIDE.md)
