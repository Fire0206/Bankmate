# FinOrch 前端能力交接

本文按当前 FastAPI 路由、Pydantic Schema、受控 Tool 输出和生成的 OpenAPI 核对。它说明前端现在能读取什么，以及哪些后续产品能力值得设计；不表示候选能力已经交付。

状态标记：

- **Implemented**：有当前 API/Task 字段和真实合成数据，可直接展示。
- **Extendable**：主要数据已存在，仍需少量服务端计算、规则或字段扩展。
- **Planned**：当前缺少明显的数据、规则、接口或事件机制，不能直接调用。
- **Proposed**：未来接口/字段建议，不是当前 API。

所有用户、账户、交易、产品、卡片、订阅及执行结果都是本地合成演示数据。Demo Identity 只在 development/test 使用，不能当作用户认证，也不能用于远程多用户环境。

## A. 当前数据与接口

### 通用约定

- REST 前缀为 `/api/v1`。当前 API 不接受客户端传入 `user_id` 或角色；服务端从 `FINORCH_DEMO_USER_ID` 选择模拟 actor。
- 所有金额字段以整数最小货币单位表示，和 `currency` 一起使用。当前种子数据使用 CNY，`amount_minor: 1250` 表示 ¥12.50；禁止前端把金额转成浮点数参与累计。展示时可以将整数换算成元字符串。
- `units_micros` 是百万分之一单位；`annual_yield_bps` 是基点，100 bps = 1%；两者都不是金额元数。
- 时间戳为带时区的 ISO 8601/RFC 3339 字符串，服务端存 UTC。`month` 使用 `YYYY-MM`，不带时刻。
- ID 在 JSON 中是 UUID 字符串。卡片尾号是四位字符串，不能转为数字。
- 标准错误体为 `{ "error": { "code", "message", "details", "request_id" } }`，并带 `X-Request-ID` 响应头。界面逻辑根据稳定 `error.code` 分支；可把 `message` 展示为简短错误说明，不要解析消息文本决定业务状态。
- `apps/web/openapi.json` 是 OpenAPI 快照，`apps/web/src/generated/api.d.ts` 是生成类型。两者均不得手工编辑；运行 `pnpm run api:types` 更新。

### 会话、卡片和账单

| 场景 / API                                                                                                     | 请求                                        | 响应与关键字段                                                                                                                                                       |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/v1/demo/session`                                                                                     | 无参数                                      | `user_id` UUID、`display_name`、`environment` (`development`/`test`)、`dataset_version`、`agent_provider` (`fake`/`openai-compatible`)。用于环境说明，不是登录凭证。 |
| `GET /api/v1/health`                                                                                           | 无参数                                      | `status: "ok"`、`service`、`version`。只表示 API 进程可响应，不表示数据库或模型在线。                                                                                |
| `GET /api/v1/cards?limit=20&cursor=...`                                                                        | `limit` 1–100；可选不透明 `cursor`          | `{items, next_cursor}`。卡片字段见下表。                                                                                                                             |
| `GET /api/v1/cards/{card_id}`                                                                                  | UUID 路径参数                               | 单张当前 actor 所属卡片；不存在或越权均为 404。                                                                                                                      |
| `GET /api/v1/transactions?month=YYYY-MM&category=...&merchant=...&direction=income\|expense&offset=0&limit=50` | 筛选项可选；`offset` 0–10000，`limit` 1–100 | `{items, total, offset, limit, next_offset}`；`next_offset` 为空表示结束。                                                                                           |
| `GET /api/v1/bills/summary?month=YYYY-MM&category=...`                                                         | `month`、`category` 可选                    | 月度收支、类别、近六个月趋势和规则提示；字段见下表。                                                                                                                 |

**CardResponse**（`items[]` 与单卡响应相同）：

| 字段                       | 含义 / 类型         | 可空 / 枚举            |
| -------------------------- | ------------------- | ---------------------- |
| `id`, `account_id`         | 卡片、所属账户 UUID | 否                     |
| `label`                    | 卡片名称            | 否                     |
| `card_suffix`              | 卡号尾四位字符串    | 否                     |
| `status`                   | 卡状态              | 否；`active`、`frozen` |
| `version`                  | 服务端资源版本      | 否；正整数             |
| `created_at`, `updated_at` | 创建、更新时间      | 否；UTC date-time      |
| `next_cursor`              | 列表下一页游标      | 是                     |

**BillTransactionResponse**：

| 字段                                  | 含义 / 类型          | 可空 / 枚举             |
| ------------------------------------- | -------------------- | ----------------------- |
| `id`, `account_id`                    | 流水、账户 UUID      | 否                      |
| `direction`                           | 收支方向             | 否；`income`、`expense` |
| `amount_minor`, `currency`            | 整数分和货币代码     | 否                      |
| `merchant`, `category`, `description` | 商户、分类、合成描述 | 否                      |
| `occurred_at`                         | 流水发生时间         | 否；UTC date-time       |
| `anomaly_reason`                      | 命中规则的解释文本   | 是；不是欺诈结论        |
| `source_card_suffix`                  | 来源卡尾号           | 是                      |

`BillSummaryResponse` 还含 `month`、`currency`、`income_minor`、`expense_minor`、`net_minor`、`selected_category`、`selected_category_expense_minor`、`categories[]`、`trends[]`、`anomalies[]`。类别项为 `{category, amount_minor, transaction_count}`；趋势项为 `{month, income_minor, expense_minor}`。无类别筛选时 `selected_category` 和 `selected_category_expense_minor` 为空。筛选结果、汇总、类别统计和趋势均由服务端从 `entry_kind="bill"` 的模拟流水计算。

当前异常规则是可解释的演示提示：非住房单笔支出达到 ¥1,000，以及同一账户、商户、金额、币种在同一 UTC 日期出现多笔扣款。它不是风控评分或欺诈检测。演示种子中 2026-10 有工资、餐饮、交通、住房、大额数码消费，以及腾讯视频相同金额的重复扣费样例；全部为合成流水。

### 订阅与代扣

| API                         | 请求   | 响应                                                                         |
| --------------------------- | ------ | ---------------------------------------------------------------------------- |
| `GET /api/v1/subscriptions` | 无参数 | `{items, monthly_total_minor, currency}`；订阅通过周期合成流水识别并持久化。 |

订阅项字段：`id`、`account_id`（UUID），`merchant`，`amount_minor`（整数分/月），`currency`，`billing_cycle`（当前仅 `monthly`），`status`（`active`/`paused`/`cancelled`），`next_charge_at`（UTC date-time），`version`，`detected_charge_count`。`monthly_total_minor` 只合计 active 订阅。当前没有独立订阅写 API；暂停、恢复和取消需通过 Agent 任务提出并确认。

### 账户、收款人、转账和 AA 分账

| API                                   | 请求                                                          | 响应 / 用途                                                                               |
| ------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `GET /api/v1/accounts`                | 无参数                                                        | `{items:[{id,label,currency,balance_minor}]}`；仅当前 actor 自己的账户和余额。            |
| `GET /api/v1/payees`                  | 无参数                                                        | `{items:[{id,display_name,destination_account_id,destination_account_label,currency}]}`。 |
| `POST /api/v1/payees`                 | JSON `{display_name, destination_account_id}`；名称 1–80 字符 | 创建模拟收款人，返回 PayeeResponse，HTTP 201。                                            |
| `DELETE /api/v1/payees/{payee_id}`    | UUID 路径参数                                                 | 删除未被转账引用的当前 actor 收款人，HTTP 204。                                           |
| `GET /api/v1/transfers?limit=50`      | `limit` 1–100                                                 | `{items: TransferResponse[]}`。                                                           |
| `GET /api/v1/transfers/{transfer_id}` | UUID 路径参数                                                 | 单笔当前 actor 转账；越权/不存在返回 404。                                                |
| `GET /api/v1/splits?limit=50`         | `limit` 1–100                                                 | `{items: SplitBillResponse[]}`。                                                          |
| `POST /api/v1/simulate-due`           | 无 body；仅 development/test                                  | 显式模拟已确认且到期的定时转账，返回 `{executed_count, items}`。不是后台定时任务。        |

`TransferResponse` 字段：`id`、`source_account_id`、`destination_account_id`、`source_account_label`、`payee_name`、`amount_minor`、`currency`、`transfer_type` (`immediate`/`scheduled`)、`status` (`awaiting_confirmation`/`scheduled`/`executed`/`cancelled`/`failed`)、可空 `scheduled_at`、可空 `executed_at`、`version`。

`SplitBillResponse` 字段：`id`、`title`、`total_amount_minor`、`currency`、`participant_count`、`status` (`awaiting_confirmation`/`open`/`settled`/`cancelled`/`failed`)、`version`、`participants[]`。参与人含 `id`、`display_name`、`amount_minor`、`status` (`organizer_paid`/`pending`/`paid`)。已确认普通转账会同步改变两侧模拟账户余额和两条流水；AA 分账确认时写入模拟消费，收款确认时把待收金额计入组织者账户并更新参与人状态。

收款人 CRUD 和 `/simulate-due` 是 Agent Task 之外的直接接口，目前没有 `Idempotency-Key`。收款人同名冲突会返回业务错误；若创建/删除响应丢失，先重新读取 `/payees` 确认当前状态。到期模拟器按 scheduled 状态筛选，成功项执行后会退出待执行集合；重复调用不会再次扣款。

### 理财

| API                                                                     | 请求     | 响应 / 用途                                           |
| ----------------------------------------------------------------------- | -------- | ----------------------------------------------------- |
| `GET /api/v1/investments/profile`                                       | 无参数   | `{risk_level, risk_label}`，服务端模拟风险档案。      |
| `GET /api/v1/investments/products?category=...&maximum_risk_level=1..5` | 可选筛选 | `{items, risk_level, risk_label}`；每项含适当性结果。 |
| `GET /api/v1/investments/portfolio`                                     | 无参数   | 现金、持仓市值、估算收益和资产合计。                  |
| `GET /api/v1/investments/orders`                                        | 无参数   | `{items: InvestmentOrderResponse[]}`。                |

产品字段：`id`、`code`、`name`、`category`、`risk_level`（1–5）、`minimum_amount_minor`、`unit_price_minor`、`annual_yield_bps`、`term_days`、`currency`、`description`、`suitable`。`suitable` 是服务端权威适当性结果；产品价格和收益为模拟值，收益不保证。

持仓字段：`id`、`product_id`、`product_name`、`units_micros`、`purchase_price_minor`、`current_price_minor`、`current_value_minor`、`estimated_gain_minor`、`currency`、`version`。Portfolio 还含 `cash_balance_minor`、`invested_value_minor`、`estimated_gain_minor`、`total_assets_minor`、`risk_level`、`risk_label`、`holdings[]`。订单字段为 `id`、`order_type` (`buy`/`redeem`)、`product_id`、`product_name`、`amount_minor`、`currency`、`status` (`awaiting_confirmation`/`executed`/`cancelled`/`failed`)、可空 `executed_at` 和 `holding_id`。

申购/赎回只能由 Agent Tool 提案、确认后更新账户、订单、持仓、流水和审计；没有绕过确认的理财写 API。

### Agent Task、确认和审计

| API                                                                                                                         | 请求 / 参数                                                            | 说明                                                                                                      |
| --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `POST /api/v1/agent/tasks`                                                                                                  | JSON `{request_text, conversation_id?}`；必需 Header `Idempotency-Key` | 创建任务并同步运行有界 Agent/工具循环。客户端应生成并保存 `conversation_id`，以便响应丢失后查询。         |
| `GET /api/v1/agent/tasks/{task_id}`                                                                                         | Task UUID                                                              | 读取任务快照、步骤、工具结果和当前待确认项。读取时服务端会结算已过期挑战。                                |
| `GET /api/v1/agent/tasks/recent?conversation_id=...`                                                                        | 必需会话 UUID                                                          | 优先返回该会话最近的活动任务，没有活动任务时返回最近终态任务；没有记录返回 `null`。actor 仍由服务端决定。 |
| `GET /api/v1/agent/tasks/by-idempotency-key/{key}?conversation_id=...&operation=create\|input\|confirm\|cancel&task_id=...` | `task_id` 对非 create 操作必需                                         | 响应丢失后的按操作查找；未找到返回 `null`。                                                               |
| `POST /api/v1/agent/tasks/{task_id}/input`                                                                                  | JSON `{request_text}`；必需 `Idempotency-Key`                          | 补充 `awaiting_input`，或对部分失败任务继续输入；修改待确认请求会使旧 challenge 失效。                    |
| `POST /api/v1/agent/tasks/{task_id}/confirm`                                                                                | JSON `{challenge_id, parameters_hash}`；必需 `Idempotency-Key`         | Header 必须使用 Challenge 返回的同一 `idempotency_key`；只确认所显示的已绑定参数。                        |
| `POST /api/v1/agent/tasks/{task_id}/cancel`                                                                                 | 无 body；必需 `Idempotency-Key`                                        | 取消尚未完成的 Task 和未执行操作，不撤销已经成功的步骤。                                                  |
| `GET /api/v1/agent/tasks/{task_id}/audit`                                                                                   | Task UUID                                                              | 返回该 Task 关联的审计摘要。                                                                              |

**AgentTaskResponse**：

| 字段                       | 含义 / 类型                                | 可空 / 枚举                                                                                                         |
| -------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `id`                       | Task UUID（接口没有单独的 `task_id` 字段） | 否                                                                                                                  |
| `conversation_id`          | 会话关联 UUID，不是身份凭证                | 否                                                                                                                  |
| `request_text`             | 当前累积的用户任务文本；仅合成内容         | 否                                                                                                                  |
| `provider_mode`            | Provider 模式                              | 否；`fake`、`openai-compatible`                                                                                     |
| `status`                   | 服务端任务状态                             | 否；`pending`、`planning`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`cancelled` |
| `message`                  | 面向用户的当前说明；可能来自模型自然语言   | 否；不是业务事实来源                                                                                                |
| `error_code`               | 稳定错误标识                               | 是                                                                                                                  |
| `version`                  | Task 资源版本                              | 否；正整数                                                                                                          |
| `created_at`, `updated_at` | 创建、更新时间                             | 否；UTC date-time                                                                                                   |
| `steps`                    | 有序 `AgentTaskStepResponse[]`             | 否；可能为空                                                                                                        |
| `confirmation`             | 当前待确认项                               | 是；已过期/已消费后为 `null`                                                                                        |

步骤字段为 `id`、`sequence`、`step_type`、`status`、`summary`、可空 `tool_name`、`error_code`、`result_summary`、`result_data`。当前 `step_type` 实际包括 `planner`、`tool`、`user_input`、`cancellation`；工具步骤状态包括 `pending`、`running`、`awaiting_confirmation`、`succeeded`、`failed`、`cancelled`。Planner/user-input 记录通常没有 `result_data`。只有 `tool_name` 对应的 Tool Step 才有工具结果；其中的结构按工具而异。

当前 Tool 结果的主要结构：

| 场景 / 工具                                                               | `result_data` 中的服务端数据                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 卡片：`card.list`、`card.get`                                             | 列表 `{items:[{id,account_id,label,card_suffix,status,version}],next_cursor}`；单卡字段同一项。                                                                                                                                                                                      |
| 卡片：`card.freeze`、`card.unfreeze`                                      | 提案 `{status:"awaiting_confirmation",confirmation_required,challenge_id,card_id,card_suffix,card_label,current_status,target_status,card_version,parameters_hash,idempotency_key,expires_at,...}`；此时卡片状态尚未改变。确认后结果含 `card`、`card_suffix`、`status:"succeeded"`。 |
| 账单：`bill.monthly_summary`                                              | 月份、币种、收入/支出/结余、`categories[]`、`trends[]`、`anomalies[]`。金额来自服务端流水汇总。                                                                                                                                                                                      |
| 账单：`bill.transactions`、`bill.anomalies`                               | `{month,items,total}` 或 `{month,items}`；工具流水项含方向、金额、币种、商户、分类、发生时间、提示原因、来源卡尾号。                                                                                                                                                                 |
| 订阅：`subscription.list`                                                 | `{items:[{id,merchant,amount_minor,currency,billing_cycle,status,next_charge_at,version,detected_charge_count}],monthly_total_minor,currency}`。                                                                                                                                     |
| 订阅：`subscription.pause`、`subscription.resume`、`subscription.cancel`  | 先返回绑定订阅 ID、当前/目标状态、版本、challenge、摘要、幂等键和有效期的提案；确认结果含 `subscription` 和 `status:"succeeded"`。                                                                                                                                                   |
| 转账：`transfer.accounts`、`transfer.payees`、`transfer.history`          | 对应账户余额、收款人列表或 `TransferResponse` 形状的 `items`。                                                                                                                                                                                                                       |
| 转账：`transfer.create`、`transfer.schedule`、`transfer.cancel_scheduled` | 先返回 `transfer_id`、收款人、来源账户、金额/币种、转账类型、计划时间和确认信息；确认后含实际 Transfer 结果。                                                                                                                                                                        |
| 分账：`transfer.splits`                                                   | 分账与参与人列表；分账项含总额、币种、参与人数、状态、版本和逐人金额/收付状态。                                                                                                                                                                                                      |
| 分账：`transfer.split_create`、`transfer.split_collect`                   | 先返回总额、参与人/份额和 challenge；确认后返回分账及状态结果。                                                                                                                                                                                                                      |
| 资金计划：`finance.payday_plan`                                           | 账户余额、当月收入/支出、转账金额、预留金额、转账后余额、服务端计算的 `investment_budget_minor` 和 `reserve_shortfall_minor`。只读计划，不改余额。                                                                                                                                   |
| 理财：`investment.products`、`investment.compare`                         | 产品列表、当前风险等级，以及 `suitable` 适当性结果。                                                                                                                                                                                                                                 |
| 理财：`investment.profile`、`investment.portfolio`、`investment.orders`   | 风险档案、真实模拟持仓/估值/现金，或模拟订单列表。                                                                                                                                                                                                                                   |
| 理财：`investment.buy`、`investment.redeem`                               | 提案含订单、产品、账户、金额、份额、风险等级及确认字段；确认后含实际订单结果。                                                                                                                                                                                                       |

这里列的是当前实现的主要字段，不建立第二套前端 DTO。详细 Schema 仍以生成的 OpenAPI 为准。`ToolExecution` 没有单独查询 API；前端通过 Task Step 的 `result_summary` / `result_data` 展示。未注册工具、输入参数错误或执行失败时，步骤包含错误码和服务端失败结果；不得把失败的模型文本当成成功结果。

**ConfirmationResponse** 的稳定公共字段为 `id`（challenge UUID）、`resource_type` (`card`/`subscription`/`transfer`/`split`/`investment_order`)、`resource_id`、`resource_label`、`resource_version`、`current_status`、`target_status`、`parameters_hash`、`idempotency_key`、`expires_at`、`policy_version`、`tool_name`、`tool_version`。卡片可能另含 `card_id`、`card_suffix`、`card_label`、`card_version`；订阅可能另含 `subscription_id`、`merchant`、`subscription_version`；其他操作通过 `resource_id` 和可空 `details` 承载特定信息。`details` 目前对转账含金额/币种/类型/计划时间/来源账户/收款人，对分账含金额/币种/参与人，对理财含买入或赎回、金额/币种/份额/风险/账户。前端应根据 `resource_type` 分支，不假设每种资源字段都存在。

Audit Event 字段：`id`、`event_type`、`resource_type`、`resource_id`、可空 `tool_execution_id`、`outcome`、可空 `before_state` / `after_state`、`occurred_at`。`AgentAuditResponse` 为 `{task_id,events[]}`。这是任务范围摘要，不是全部账户历史审计查询 API。

任务执行期间可能出现多个确认节点。部分成功时，已提交步骤和审计保留，后续步骤可以失败或等待补充信息；取消只阻止尚未执行的步骤。`failed` 任务在已有至少一个成功工具执行时可通过 `/input` 带用户补充继续；否则应创建新任务。刷新后只能恢复服务器记录的 Task、步骤和当前 Challenge，不存在可恢复的完整聊天记录。

### 推荐交互和重试顺序

1. 首次加载读取 `/demo/session`、`/health`、需要展示的业务 GET；会话 ID 由前端保存用于任务关联，不能当作授权信息。
2. 创建任务时前端先生成 `conversation_id` 和 `Idempotency-Key`，并在请求发出前保存这两项；提交 `POST /agent/tasks`。成功后以响应中的 Task 快照、步骤和状态为准。
3. 若写响应超时/连接断开，先用相同 conversation、operation、task_id 和原幂等键查询 `/by-idempotency-key/{key}`；查到后读取该 Task。只有确认服务端不存在该操作时，才用原请求和原键重试。不要在结果未知时生成新键。
4. `awaiting_input` 时提交 `/input` 并使用一个新的输入操作键。修改一个仍待确认任务的目标会取消旧挑战；刷新 Task 后再展示新的确认信息。
5. 只有顶层 `task.confirmation != null` 且 Task/步骤状态仍待确认时才显示可执行确认卡。确认前展示该对象当前状态、目标状态、金额/币种或份额、收款人/订阅/卡片、有效期。确认请求 Header 使用 `confirmation.idempotency_key`，body 原样传 `id` 和 `parameters_hash`。按钮提交后禁用，等待服务端返回；不要自行改参数或倒计时后仍允许提交。
6. Task 读取可能惰性处理过期挑战；因此从 `GET /tasks/{id}` 返回的 `task.confirmation` 是当前待确认状态的来源。过期后读取失败 Task 及步骤状态，不要仅看历史 `step.result_data` 中保留的旧 proposal。
7. 取消和输入/确认同样需要保存并复用幂等键。确认状态变为成功后重新读取相关余额、卡片、订阅、交易、持仓或订单，再展示最终状态。不要由前端乐观更新资金或状态。
8. `message` 是解释文字；`status`、`confirmation`、成功工具的 `result_data`、业务 GET 和 Audit Event 才是服务端结果。Fake Provider 为确定性本地规则模式，不调用外部模型；`openai-compatible` 表示已选择兼容 Provider，不保证模型响应必然成功。

## B. 值得规划的产品扩展

以下均不是当前可调用的新功能。优先复用可验证的账户、账单、订阅、投资、Task、Confirmation 和 Audit 数据；评分、预测、风险解释等判断应放在后端，前端负责可视化而不复制业务规则。

### 1. 跨场景计划预览与执行回放 — **Extendable**

- **用户价值 / 展示**：执行前看到目标、资金来源、逐步操作和每步影响；执行中用有序时间线呈现读取、待确认、已完成、失败与部分成功。支持展开工具结果和审计依据。
- **可复用**：`AgentTaskResponse`、`steps[].sequence/status/tool_name/result_data`、Confirmation、Task Audit、账户/账单/订阅/组合 GET 已提供。
- **可计算**：前端可以把步骤显示为时间线、分组和前后快照对比；金额格式化可在安全整数范围内完成。
- **需要补充**：若要正式计划摘要和风险影响，建议后端返回 `plan_summary`、`expected_effects[]`、`completed_effects[]`、`pending_effects[]`。示例均为 **Proposed**，不是当前字段。成功工具执行结果可支撑基线回放，但没有通用撤销接口。
- **复杂度 / 依赖 / 优先级**：低至中；依赖稳定 Task Schema 和明确的服务端结果；比赛价值高，优先做。

### 2. 可疑扣款证据链 — 当前规则 **Implemented**，增强分析 **Extendable**

- **用户价值 / 展示**：展示命中的是“大额”还是“同日同商户同额重复扣费”，并把交易、来源卡、活动订阅、Agent 建议与确认结果连成证据时间线。使用“重复扣费提示”等措辞，不显示“欺诈已确认”。
- **可复用**：交易 API/Tool 的 `anomaly_reason`、`merchant`、`amount_minor`、`occurred_at`、`source_card_suffix`，`subscription.list`，卡片状态，Task steps 和 Audit。
- **可计算**：前端可按同一 Task 的 sequence 展示服务端返回证据；现有规则原因可直接展示。不要在前端自行扩展重复扣款规则。
- **需要补充**：更完整的因果关联、规则 ID/版本、关联 `transaction_ids`、`evidence[]`、`confidence` 或 `risk_level` 都需要服务端规则与 schema。任何分数/概率均为 **Proposed**，不可当成现有欺诈能力。
- **复杂度 / 依赖 / 优先级**：基础时间线低；跨资源证据关联中；演示价值很高，优先做可解释规则版。

### 3. 发薪日资金调度情景模拟 — **Extendable**

- **用户价值 / 展示**：资金流向图或步骤预览显示当前余额、账单收支、转账额、预留金额、转后余额和可投资上限；可在确认前调整参数并重新计算。
- **可复用**：`/accounts`、`/bills/summary`、`finance.payday_plan` 返回的 `investment_budget_minor`、转账和投资产品/组合 API。
- **可计算**：图表和场景数值直接用服务端 `finance.payday_plan` 结果；前端可按返回值绘制 Sankey 或资金分配条，不负责最终资金约束。
- **需要补充**：多个方案同时比较、固定支出/目标金额、账户选择等可扩展为 `POST /api/v1/plans/payday/preview`，这是 **Proposed**。当前只有 Agent 工具内的单方案只读计算。
- **复杂度 / 依赖 / 优先级**：低至中；依赖服务端计划结果和现有模拟资金，比赛展示价值很高。

### 4. 订阅续费与可节省金额 — **Extendable**

- **用户价值 / 展示**：按月费用、下次扣款时间和状态排序，提供“暂停/取消后每月/每年可少支出多少”的影响预览，仍由用户逐项确认。
- **可复用**：订阅状态、月费、下次扣款、活动订阅月费合计和合成重复扣款提示；暂停/恢复/取消工具已存在。
- **可计算**：按 `amount_minor × 12` 估算当前月费对应的年化支出或节省额，明确标“按当前月费估算”，不把它解释为历史实付或确定未来扣费。
- **需要补充**：真实订阅使用频率、试用/优惠、合同结束日或续费提醒触发记录都不存在；“闲置订阅”判断需新增用户使用数据/偏好和后端规则。建议的 `estimated_annual_saving_minor`、`reason_codes[]` 为 **Proposed**。
- **复杂度 / 依赖 / 优先级**：金额估算低；识别浪费和提醒中至高；数据准备度高但缺使用情况。

### 5. 理财适当性解释与配置对比 — **Extendable**

- **用户价值 / 展示**：同时展示用户模拟风险等级、产品风险等级、起购金额、模拟期限和收益估值，并说明适合/不适合依据；区分模拟收益和保证收益。
- **可复用**：`/investments/profile`、`/products` 的 `risk_level`、`suitable`、`minimum_amount_minor`、`annual_yield_bps`，以及投资组合/订单。
- **可计算**：可由前端格式化风险等级、比较产品差异和显示 basis point；适当性最终结果仍只信服务端 `suitable`。
- **需要补充**：当前没有适当性理由、波动/期限风险说明、投资目标或资产配置建议。建议返回 `suitability_reason_codes[]`、`risk_explanation` 或场景化估值结构；这些都是 **Proposed**，不能由模型编造成投资结论。
- **复杂度 / 依赖 / 优先级**：低至中；依赖后端理由码和明确模拟免责声明；展示价值中高。

### 6. 月末余额与现金流预测 — **Extendable**

- **用户价值 / 展示**：估算月底可用余额区间并展示固定订阅、近期账单和历史趋势对预测的影响。
- **可复用**：月度及近六个月收入/支出、当前账户余额、订阅月费、已保存定时转账。
- **可计算**：现有数据足够做明确标注的简单基线；不应将模型生成的数字作为预测结果。
- **需要补充**：对定时转账以外的已知未来义务、置信区间、模型版本和预测评估当前没有统一查询/API。建议 `GET /api/v1/cashflow/forecast?month=YYYY-MM`、`forecast_balance_minor`、`assumptions[]`、`range_low_minor`、`range_high_minor`，全部为 **Proposed**。
- **复杂度 / 依赖 / 优先级**：中；依赖统一预测口径和可解释假设；比赛价值中等。

### 7. 个人财务健康评分 — **Planned**

- **用户价值 / 展示**：展示分数之外，还要显示储蓄、必要支出占比、订阅负担、现金缓冲等分项与数据时间范围，避免只有一个不可解释数字。
- **可复用**：余额、月度收支/类别、趋势、订阅月费和持仓数据。
- **可计算**：这些数据可形成候选特征，但评分权重、阈值、缺失数据和货币口径尚未定义；不可由前端自行给出正式评分。
- **需要补充**：后端定义并测试评分规则、依据、数据完整度和版本。建议 `GET /api/v1/financial-health` 返回 `score`、`grade`、`components[]`、`as_of`、`rule_version`；均为 **Proposed**。
- **复杂度 / 依赖 / 优先级**：中；依赖产品定义和解释规则；视觉展示吸引力较强，但需谨慎定义评分。

### 8. 事件触发提醒与用户授权自动化 — **Planned**

- **用户价值 / 展示**：续费/余额/异常发生时呈现原因、建议动作、影响和授权范围；用户可批准一次性任务或撤销未来授权。
- **可复用**：当前账单异常、`next_charge_at`、账户余额、Task 和确认数据可用于原型建议卡。
- **可计算**：前端可以设计静态信息层级；当前服务端没有推送、通知、事件订阅或后台计划执行，不能显示为已启用提醒。
- **需要补充**：服务端事件产生与投递、通知偏好、用户授权、自动化策略、执行窗口、撤销和审计。建议的 `AutomationRule`、`triggered_at` 和 `authorization_scope` 均为 **Proposed**。
- **复杂度 / 依赖 / 优先级**：高；依赖真实身份/授权与可靠事件机制；长期差异化高，当前不宜伪装成已有功能。

### 9. 可撤销操作与补偿 — **Planned**

- **用户价值 / 展示**：对可逆操作展示撤销入口、可撤销时限及撤销后状态。
- **可复用**：Task、确认挑战、资源版本、Audit 和卡片/订阅状态转换记录。
- **可计算**：前端不能靠发送相反操作宣称“撤销原操作”；目前反向操作需要新请求和新确认，也不等于恢复历史账本。
- **需要补充**：每种业务定义补偿语义、有效窗口、并发冲突和专用 API。例如 `POST /api/v1/agent/tasks/{task_id}/compensate` 为 **Proposed**，不是现存路由。
- **复杂度 / 依赖 / 优先级**：高；资金操作需严格后端定义；比赛演示价值高但应晚于稳定的回放和确认展示。

### 候选能力推荐顺序

排序综合考虑比赛演示价值、实现工作量和现有数据准备度。高数据准备度表示已有接口/字段可直接支撑原型，不等于该扩展功能已经实现。

| 顺序 | 能力                     | 比赛展示价值 | 实现工作量 | 数据准备度 | 建议                                                                        |
| ---: | ------------------------ | ------------ | ---------- | ---------- | --------------------------------------------------------------------------- |
|    1 | 跨场景计划预览与执行回放 | 高           | 低至中     | 高         | 优先把现有 Task、步骤、确认、审计和业务结果组织成清晰的前后对照。           |
|    2 | 可疑扣款证据链           | 高           | 低至中     | 高         | 先呈现现有金额/重复扣费规则及关联记录；风险判断保持可解释，不宣称欺诈结论。 |
|    3 | 发薪日资金调度情景模拟   | 高           | 低至中     | 高         | 复用现有确定性资金计划，重点展示资金流向和确认前后的真实余额。              |
|    4 | 订阅费用与节省估算       | 中高         | 低         | 高         | 可先展示月费、年化估算和下一扣款日期；识别“闲置”需要更多使用数据。          |
|    5 | 理财适当性解释           | 中高         | 低至中     | 中高       | 现有风险匹配可用；新增服务端理由码后再展示配置解释和模拟情景。              |
|    6 | 现金流与月底余额预测     | 中高         | 中         | 中         | 先统一预测假设及数据口径，再提供明确标注的区间预测。                        |
|    7 | 个人财务健康评分         | 中高         | 中         | 中         | 有可用输入数据，但需先定义并验证评分因子、权重、缺失数据规则和版本。        |
|    8 | 可撤销操作与补偿         | 高           | 高         | 低         | 逐项定义资金业务的补偿语义、并发边界和确认要求后再设计界面入口。            |
|    9 | 事件触发提醒与授权自动化 | 高           | 高         | 低         | 依赖通知投递、用户授权、后台触发与审计能力，适合作为后续差异化方向。        |

## C. 前后端协作

- **单一事实来源**：后端 Pydantic Schema 和 FastAPI 路由生成 OpenAPI；执行 `pnpm run api:types` 更新 `apps/web/openapi.json` 与 `apps/web/src/generated/api.d.ts`。前端组件直接引用生成类型，不另建相同 DTO。
- **稳定依赖**：Task/Step/Confirmation 状态、资源枚举、业务 API Schema 和标准错误码。`status` 与 Tool result 字段以生成类型和服务端响应为准；展示代码应对 nullable 字段、空列表和未来新增可选字段做好处理。
- **解释与结果**：`task.message`、`step.summary`、`result_summary` 是说明文本，可能受模型措辞影响；任务状态、待确认 Challenge、成功 Tool 的 `result_data`、业务 GET 和 Audit 是服务端记录。模型文字不能作为余额、风险、适当性或操作成功的证据。
- **前端可做**：金额格式化、状态文案映射、列表筛选交互、图表、布局、时间线和已有 API 数据的展示性比较。前端不要重新判断余额充足、用户权限、风险适当性、重复收费规则或操作是否成功。
- **新增接口需求**：提交字段英文名/含义、类型/单位/可空性、数据来源、空/错误/并发行为、是否写操作、确认/幂等与审计需求、兼容影响及示例。先由前后端共同确认，再改 Pydantic Schema、测试、OpenAPI 和生成类型。
- **Demo 与银行能力边界**：收款人、账户、余额、交易、订阅、产品、价格、收益和两条跨场景流程都是确定性合成数据；没有真实银行、支付网络、商户通知或生产认证。`Fake Provider` 不调用外部模型；`openai-compatible` 才会将合成上下文发送到配置的模型服务，仍须由受控工具和服务端确认执行业务写入。
