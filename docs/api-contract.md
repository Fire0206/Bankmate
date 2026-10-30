# API 契约

## 单一事实来源

REST API 使用 FastAPI/Pydantic 定义。FastAPI 生成的 OpenAPI Schema 是**单一事实来源**；仓库中的 `apps/web/openapi.json` 是生成快照，`apps/web/src/generated/api.d.ts` 是从该快照生成的前端类型，均不得手工编辑。

修改路由或 Schema 后运行 `pnpm run api:types`，提交生成物、测试和相关文档。CI 再生成并检查是否有未提交差异。

## 路径、字段和方法

- API 根路径版本化为 `/api/v1`。兼容性破坏变更使用新的路径主版本；废弃路径应提前公告。
- 使用 REST 名词资源和标准 HTTP 方法；读取通常不改变业务状态，唯一例外是读取任务时服务端可能惰性结算已过期的确认挑战（只更新 Workflow/审计，不改变卡片）。写入使用 `POST`/`PUT`/`PATCH`/`DELETE` 的明确语义。
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

## 分页和筛选

新列表优先采用 cursor pagination：`limit`（默认 20，最大 100）和不透明 `cursor`。卡片列表已采用该方式；Phase 1C 的交易流水为兼容本地有限合成数据，使用 `offset`（默认 0，最大 10,000）/`limit`（默认 50，最大 100），响应包含 `total` 和 `next_offset`。后续如需统一分页，必须评估兼容性并通过接口变更流程处理。筛选项作为有类型、文档化的 query 参数；排序需显式限定稳定字段和方向。

## 时间、金额和货币

- 时间戳使用 ISO 8601/RFC 3339 并带时区偏移；服务端存 UTC，序列化建议 `Z`。日期（不含时刻）使用 `YYYY-MM-DD`。
- 金额不得使用 IEEE-754 浮点。用整数 `amount_minor` 表示货币最小单位，并同时传 ISO 4217 `currency`，例如 `1250` + `USD` 表示 12.50 USD。货币小数位遵循 ISO 4217 配置，不硬编码所有货币为两位。超出 JSON 安全整数的金额拒绝或改用契约明确的字符串表示。
- 精度、舍入、汇率和舍入方向必须由后端规则定义并测试；不可由模型或前端计算后作为可信结果。

## 幂等与兼容

- 未来新建的有副作用请求必须使用 `Idempotency-Key`。当前任务创建、补充输入、确认和取消接口已实现持久化幂等；收款人增删和本地 `/simulate-due` 端点目前没有该机制，调用方应在响应不确定时先重新读取服务端状态。相同 actor/操作作用域内，同键同请求返回已保存结果，同键不同请求返回 `idempotency_conflict`。
- Phase 1B–1D 的任务创建、补充/修订输入、卡片、订阅、转账、分账或理财确认和取消 API 已实现持久化幂等检查；键在 actor/任务/操作作用域内绑定规范化输入。并发确认由 SQLite 写事务串行化，确认键与 challenge 绑定。当前没有通用幂等中间件。
- 增加可选响应字段通常向后兼容；删除/重命名字段、收窄输入或改变既有含义属于破坏性变更。先弃用并沟通，再在新主版本移除。
- PR 必须更新 Schema、类型生成物、兼容说明、消费者和测试。Breaking change 需 ADR 或版本变更评审。

## 已实现端点

`GET /api/v1/health` 返回 `HealthResponse`：

```json
{ "status": "ok", "service": "finorch-api", "version": "0.1.0" }
```

它只报告 API 进程状态，不检查数据库、模型或外部依赖。

卡片只读端点：

| 方法与路径                              | 说明                                                                                         |
| --------------------------------------- | -------------------------------------------------------------------------------------------- |
| `GET /api/v1/cards?limit=20&cursor=...` | 读取当前服务端 Demo actor 自己的卡片；`limit` 为 1–100，使用不透明游标并返回 `next_cursor`。 |
| `GET /api/v1/cards/{card_id}`           | 读取当前 actor 所属卡片；资源不存在或不属于 actor 时统一返回 404。                           |

Demo actor 由服务端 `FINORCH_DEMO_USER_ID` 选择，仅在 `development`/`test` 可用；客户端提供的 `user_id` 或角色字段不参与身份判定。两端点的响应 DTO 与 SQLAlchemy 模型分离，Schema 仍以 OpenAPI 和自动生成的 TypeScript 类型为准。

账单和订阅查询端点（所有查询均限定为当前服务端 Demo actor 的合成数据）：

| 方法与路径                                                                                                      | 说明                                                                                            |
| --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `GET /api/v1/transactions?month=YYYY-MM&category=...&merchant=...&direction=income%7Cexpense&offset=0&limit=50` | 按月份、类别、商户、收支方向筛选流水；返回 `items/total/offset/limit/next_offset`。             |
| `GET /api/v1/bills/summary?month=YYYY-MM&category=...`                                                          | 返回月度收入、支出、结余、类别汇总、近六个月趋势及规则提示；可选类别筛选。                      |
| `GET /api/v1/subscriptions`                                                                                     | 返回从周期模拟交易识别并持久化的订阅、月费合计、状态、检测扣款数及下次模拟扣款时间。            |
| `GET /api/v1/subscriptions/reminders`                                                                           | 返回当前 actor 未来 30 天有效订阅的应用内提醒计划与是否已生成。                                 |
| `POST /api/v1/subscriptions/reminders/refresh`                                                                  | 用服务端当前时间为已到提醒日的周期追加一次本地提醒审计；重复调用不重复生成。                    |
| `PUT /api/v1/subscriptions/{subscription_id}/reminder-preference`                                               | 以 `days_before`（0–30）和 `expected_version` 设置当前 actor 订阅的提前提醒天数，冲突返回 409。 |

账单 API 的金额均为整数 `amount_minor` 和 ISO 4217 `currency`；异常仅表示匹配确定性演示规则，不代表欺诈结论。提醒设置仅改变应用内通知偏好，不修改商户代扣状态；暂停、恢复和取消仍只能经 Agent Tool 提案与下述任务确认端点执行。

Phase 1D 查询 API 也仅返回当前 Demo actor 的合成数据：

| 方法与路径                                                             | 说明                                                                                                          |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `GET /api/v1/accounts`                                                 | 当前 actor 的模拟账户及服务端余额投影。                                                                       |
| `GET /api/v1/payees`                                                   | 当前 actor 已保存的模拟收款人。                                                                               |
| `GET /api/v1/transfer-destinations`                                    | 新增收款人可选的合成目标账户；只返回账户 ID、展示名称和币种，不返回账户持有人或余额。                         |
| `GET /api/v1/transfers?limit=50`                                       | 普通/定时转账历史及模拟状态。                                                                                 |
| `GET /api/v1/transfers/{transfer_id}`                                  | actor 范围内的单笔转账；越权按 not found 处理。                                                               |
| `GET /api/v1/splits?limit=50`                                          | AA 分账、参与人及模拟收付状态。                                                                               |
| `GET /api/v1/investments/profile`                                      | 服务端模拟风险等级。                                                                                          |
| `GET /api/v1/investments/risk-assessment/questionnaire`                | 四项固定版本模拟问卷和五档选项；只读。                                                                        |
| `GET /api/v1/investments/risk-assessment/latest`                       | 当前 actor 最近一次测评；未测评返回 `null`。                                                                  |
| `POST /api/v1/investments/risk-assessment`                             | 用户本人提交四项 1–5 答案和问卷版本；须提供 `Idempotency-Key`，服务端评分、写画像及审计。同键异答案返回 409。 |
| `GET /api/v1/investments/products?category=...&maximum_risk_level=...` | 模拟产品筛选及风险匹配结果。                                                                                  |
| `GET /api/v1/investments/portfolio`                                    | 模拟现金、持仓、资产及估算盈亏。                                                                              |
| `GET /api/v1/investments/orders`                                       | 当前 actor 的模拟申购/赎回历史。                                                                              |

普通转账、定时转账、AA 分账收付、理财申购和赎回没有绕过确认的独立写 API；只能经 Agent Task proposal 和确认 API 执行。定时任务仅支持开发/测试环境的显式本地模拟执行，不是后台自动调度。
`POST /api/v1/payees` 可选填写合成 `phone_number`，每位 actor 的手机号唯一；`GET /api/v1/payees` 仅返回掩码。转账 Tool 传精确 `recipient_phone` 或 `recipient_name`，不能两者兼传。转账查询返回可空 `remark`；备注不被执行为指令，确认时须保持一致。
Demo Session 与 Agent Task 端点：

| 方法与路径                                                                                       | 说明                                                                                                                                              |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/v1/demo/session`                                                                       | 返回服务端选择的本地合成用户、环境、数据集版本和 Provider 模式                                                                                    |
| `GET /api/v1/birthday-plans`                                                                     | 返回当前 Demo actor 的生日计划、预留资金、到期状态及订单信息；预算确认会预留可用余额。到期只进入待再次确认状态，不会自动下单或扣款。              |
| `POST /api/v1/agent/tasks`                                                                       | 创建自然语言任务并运行有界 Provider/工具流程；必须带 `Idempotency-Key`                                                                            |
| `GET /api/v1/agent/tasks/{task_id}`                                                              | 读取当前 actor 可见的持久化任务、步骤、可选依赖计划和待确认详情                                                                                   |
| `GET /api/v1/agent/tasks/recent?conversation_id=...`                                             | 优先恢复最近活动任务；若无活动任务则返回最近终态任务；未找到时返回 `null`                                                                         |
| `GET /api/v1/agent/tasks/history?limit=20`                                                       | 当前 actor 最近任务列表，最多 50 项；可选 `conversation_id` 筛选。会话 ID 仅用于关联，不是授权凭证。                                              |
| `GET /api/v1/agent/tasks/by-idempotency-key/{key}?conversation_id=...&operation=...&task_id=...` | 在 actor、会话、操作类型及（非创建操作）任务范围内查询写请求结果；未找到时返回 `null`                                                             |
| `POST /api/v1/agent/tasks/{task_id}/input`                                                       | 为 `awaiting_input` 或修改待确认任务补充输入；修改会取消旧挑战；必须带 `Idempotency-Key`                                                          |
| `POST /api/v1/agent/tasks/{task_id}/confirm`                                                     | 消费服务端创建的卡片、生日计划、订阅、转账、分账或理财确认挑战；body 包含 `challenge_id` 与 `parameters_hash`，header 必须匹配 challenge 的幂等键 |
| `POST /api/v1/agent/tasks/{task_id}/cancel`                                                      | 取消尚未完成的本地任务；必须带 `Idempotency-Key`，相同键重试返回持久化结果                                                                        |
| `GET /api/v1/agent/tasks/{task_id}/audit`                                                        | 返回 actor 可见的任务审计摘要，不返回原始 prompt、API Key 或敏感上下文                                                                            |
| `GET /api/v1/agent/tasks/{task_id}/handoff`                                                      | 查询当前 actor 任务的本地模拟人工处理工单；没有工单返回 `null`。                                                                                  |
| `POST /api/v1/agent/tasks/{task_id}/handoff`                                                     | 为当前 actor 的任务申请本地模拟人工处理；重复提交返回同一工单，不授权金融写操作。                                                                 |

`card.freeze`、`card.unfreeze`、`card.report_lost`、`subscription.pause`、`subscription.resume`、`subscription.cancel`、转账、分账和理财写工具 不是独立 HTTP 写路由。Agent 工具提案只创建服务端确认挑战；确认路由复核 actor、资源所有权、工具/参数摘要、策略、资源版本、有效期和幂等键后，才通过 Application 用例变更状态。API Router、Agent Provider 和前端不得直接操作 ORM 表或 Session 事务。

`card.replace` 和 `card.apply` 同样走受控 Agent 确认。`GET /api/v1/cards/applications` 只返回当前 actor 已提交的模拟借记卡申请及本地审核状态；未确认提案不作为正式申请展示。审核脚本不通过 HTTP 或 Agent 暴露。

任务响应状态为 `pending`、`planning`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`cancelled`；实际任务、步骤和工具结果来自数据库。可选 `workflow_plan` 包含 `version`、`workflow_id` 和节点数组；节点字段为 `node_id`、`node_type`、`tool_name`、`depends_on`、`requires_confirmation`、`failure_policy`、`status`、`result_summary`、`error_code`。只对受支持的发薪日资金调度和可疑扣款复合任务生成计划，普通任务和迁移前任务为 `null`。依赖未满足的写工具调用会服务端拒绝并记录 `workflow_step_not_ready`。错误码还包括 `confirmation_not_pending`、`confirmation_invalidated`、`confirmation_expired`、`card_version_conflict`、`subscription_version_conflict`、`task_state_conflict`、`provider_not_configured`、`unknown_tool` 和 `tool_input_invalid`。具体 DTO 以 FastAPI 生成的 OpenAPI 和自动生成的 TypeScript 类型为准。

任务读取发现已过期的 pending confirmation 时，由服务端将挑战、ToolExecution、TaskStep 和 Task 状态在同一事务中结算为过期/失败并追加审计；业务状态保持不变。这个惰性过期处理保证刷新恢复显示服务端实际状态，不依赖前端时钟。

Agent Task 创建、输入补充、确认和取消操作必须提供 `Idempotency-Key`；当前收款人 `POST`/`DELETE` 及本地模拟到期转账 `POST /api/v1/simulate-due` 未实现幂等键处理。Agent 键按 actor/任务/操作作用域保存。任务创建或输入补充的相同键、相同请求返回既有任务；同键、不同请求返回 `idempotency_conflict`。确认参数摘要不匹配会令挑战失效；重复的同一确认返回已保存任务结果。重复取消使用同一键返回已保存取消结果。取消不会回滚任何已提交操作。客户端对没有幂等保护的直接接口应优先执行状态回读，避免盲目重发。

客户端在写响应丢失后，应先调用按 `operation` 与会话范围的幂等结果查询，并对已有 task 读取最新状态；只有查询确认没有该操作记录后，才可用原请求和原幂等键重试。不得因为超时新建幂等键。最近任务和幂等查询均由服务端 Demo actor 限定；`conversation_id` 是关联字段，不是身份凭证。
