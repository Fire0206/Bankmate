# API 契约

## 单一事实来源

REST API 使用 FastAPI/Pydantic 定义。FastAPI 生成的 OpenAPI Schema 是**单一事实来源**；仓库中的 `apps/web/openapi.json` 是生成快照，`apps/web/src/generated/api.d.ts` 是从该快照生成的前端类型，均不得手工编辑。

修改路由或 Schema 后运行 `pnpm run api:types`，提交生成物、测试和相关文档。CI 再生成并检查是否有未提交差异。

## 路径、字段和方法

- API 根路径版本化为 `/api/v1`。兼容性破坏变更使用新的路径主版本；废弃路径应提前公告。
- 使用 REST 名词资源和标准 HTTP 方法；读取不改变状态，写入使用 `POST`/`PUT`/`PATCH`/`DELETE` 的明确语义。
- JSON 属性采用 `snake_case`，枚举值使用稳定小写字符串；URL 路径小写连字符或资源名。
- 请求/响应 Schema 标注必填、可空、范围、格式和示例；不要通过非正式约定复用字段。

## 响应和错误

成功响应使用端点定义的 JSON Schema。错误统一为以下项目约定：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      { "code": "missing", "message": "Field is required.", "field": "name" }
    ],
    "request_id": "01J..."
  }
}
```

客户端应依赖稳定的 `code`，不可解析人类可读的 `message` 来控制逻辑。`details` 可以为空；不得回显请求中的敏感值。建议代码包括 `validation_error`、`unauthorized`、`forbidden`、`not_found`、`conflict`、`confirmation_required`、`idempotency_conflict`、`rate_limited`、`internal_error`。具体业务错误码在对应功能设计中登记，避免重复定义。

响应携带 `X-Request-ID`。接受合法的调用方 request ID 或生成新 ID，并在错误体中回传。Trace ID 用于跨服务观测时采用独立 `traceparent` 或已批准的追踪规范；Phase 0 不实现分布式 tracing。

## 分页和筛选（Planned）

列表端点统一使用 cursor pagination：`limit`（默认 20，最大 100）和不透明 `cursor`。响应为 `{ "items": [], "next_cursor": null }`。筛选项作为有类型、文档化的 query 参数；排序需显式限定稳定字段和方向。不得在不同列表随意混用 offset 与 cursor。

## 时间、金额和货币

- 时间戳使用 ISO 8601/RFC 3339 并带时区偏移；服务端存 UTC，序列化建议 `Z`。日期（不含时刻）使用 `YYYY-MM-DD`。
- 金额不得使用 IEEE-754 浮点。用整数 `amount_minor` 表示货币最小单位，并同时传 ISO 4217 `currency`，例如 `1250` + `USD` 表示 12.50 USD。货币小数位遵循 ISO 4217 配置，不硬编码所有货币为两位。超出 JSON 安全整数的金额拒绝或改用契约明确的字符串表示。
- 精度、舍入、汇率和舍入方向必须由后端规则定义并测试；不可由模型或前端计算后作为可信结果。

## 幂等与兼容

- 创建或有副作用的请求应使用 `Idempotency-Key`。服务端按用户/作用域和键保存请求摘要及最终结果；相同键、相同请求返回原结果，相同键、不同请求返回 `idempotency_conflict`。
- 幂等记录保留时间、并发行为、失败可否重试需由具体 API 明确；该能力当前未实现。
- 增加可选响应字段通常向后兼容；删除/重命名字段、收窄输入或改变既有含义属于破坏性变更。先弃用并沟通，再在新主版本移除。
- PR 必须更新 Schema、类型生成物、兼容说明、消费者和测试。Breaking change 需 ADR 或版本变更评审。

## 已实现端点

`GET /api/v1/health` 返回 `HealthResponse`：

```json
{ "status": "ok", "service": "finorch-api", "version": "0.1.0" }
```

它只报告 API 进程状态，不检查数据库、模型或外部依赖。
