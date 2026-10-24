# Agent、Tool 与 Workflow 契约

> Phase 1E 覆盖银行卡、账单、订阅、转账、理财及跨场景任务。跨场景主线为可疑扣款处置与发薪日资金调度；真实模型评测范围和结果以[开发指南](development.md)记录为准。Banking Core 调用边界见[接口说明](development/banking-core.md)。

## Agent 边界

- Agent 可分析意图、提出澄清问题、生成计划并请求调用获准的工具。
- Agent 和模型输出是不可信输入，不能直接访问数据库、调整余额、修改权限或宣称工具成功。
- 所有写操作进入服务端验证、授权、风险策略、确认和审计流程。
- Tool Provider 与模型 Provider 应可替换；模型响应仅作为建议，服务端 Tool Schema 和业务规则为准。
- Provider 接口支持 OpenAI-compatible API，配置不绑定特定供应商。

## 当前 Provider 和运行时

- `FakeProvider` 是明确标注的确定性本地演示实现：它按小范围请求文本和可信会话上下文产生预设工具调用，不做模型推理、不访问网络。它不是“假装的 LLM”。
- `OpenAICompatibleProvider` 实现 Chat Completions Tool Calling Adapter。只有显式配置 `FINORCH_AGENT_PROVIDER=openai-compatible`、Base URL、API Key 和模型名后才启用。凭据仅由服务端配置读取；错误消息不回显凭据或模型响应正文。
- Provider 接口只接收受控消息与注册工具定义，并返回文本/工具调用提议；Provider 不接收 ORM Session，不决定 actor、权限、风险等级或确认结果。
- Agent Loop 每次规划最多执行 8 次工具调用；确认后在同一持久化 Task 中继续规划，最多追加 6 个续跑阶段。若完成态门禁发现明确请求仍缺少成功的写工具记录，服务端最多再请求两次有界重规划，并把缺失工具放入可信上下文；仍未完成则以失败状态返回。同一轮可有多个 `tool_calls`，每个工具结果都按原 `tool_call_id` 回送。已成功的写操作不会重放；未知工具、非法 JSON/Schema、无效/重复调用 ID、Provider 错误和步数上限都不会执行未验证的业务操作。
- 模型仅返回文本而没有提出已注册工具调用时，服务端不会把文本作为执行结果；会返回未执行操作/等待补充信息状态。只读结果和写入结果摘要均基于服务端工具数据生成，不将模型文本当作业务执行事实。
- Fake Provider 的流程由 pytest 验证；真实 Adapter 通过 Mock HTTP 验证 Chat Completions 请求、低温度设置、`tools`/`tool_choice`、多工具及多轮 `tool_call_id` 配对、无工具响应、错误响应、超时和连接中断。理财申购还要求同一任务已返回该产品的服务端适当性结果；DeepSeek 端到端评测使用隔离测试库和合成数据，覆盖范围及结果见[开发指南](development.md)。该评测不等同于独立安全或 Prompt Injection 认证。

当前允许工具：

| Tool                   | 输入/输出                              | 权限 / 风险 / 确认                       | 实际行为                                                                         |
| ---------------------- | -------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------- |
| `card.list`            | 空输入 / 当前用户卡片列表              | `read_only` / `low` / `never`            | Application 查询 actor 自己的合成卡片                                            |
| `card.get`             | `card_suffix` / 一张卡的 DTO           | `read_only` / `low` / `never`            | actor 范围内按尾号查询，不存在或越权统一视为 not found                           |
| `card.freeze`          | `card_suffix` / 操作提案与挑战         | `reversible_write` / `medium` / `always` | 校验归属和状态并建 challenge；本步骤不改变卡片状态                               |
| `card.unfreeze`        | `card_suffix` / 操作提案与挑战         | `reversible_write` / `medium` / `always` | 校验归属和状态并建 challenge；本步骤不改变卡片状态                               |
| `card.report_lost`     | `card_suffix` / 操作提案与挑战         | `high_risk_write` / `high` / `always`    | 独立 lost 状态；确认后仍需模拟强验证，不能通过解冻恢复                           |
| `card.replace`         | `card_suffix` / 操作提案与挑战         | `high_risk_write` / `high` / `always`    | 挂失卡经确认及本地模拟验证码后停用旧卡、生成新合成卡                             |
| `card.apply`           | 账户标签/卡片标签 / 申请提案与挑战     | `reversible_write` / `medium` / `always` | 确认后仅提交模拟借记卡申请；本地审核独立进行                                     |
| `card.applications`    | 空输入 / 当前用户已提交申请列表        | `read_only` / `low` / `never`            | 查询提交、批准或驳回状态，未确认提案不显示                                       |
| `card.catalog`         | 空输入 / 固定合成商品与价格            | `read_only` / `low` / `never`            | 只列出模拟鲜花和蛋糕，不接真实商户                                               |
| `card.controls`        | 卡尾号与一项设置 / 确认提案            | `reversible_write` / `medium` / `always` | 更改单笔、单日限额或线上开关；重大额度上调需本地模拟 OTP                         |
| `card.purchase`        | 卡尾号、商品、数量、渠道 / 确认提案    | `high_risk_write` / `medium` / `always`  | 服务端定价并在确认后复核限制、扣减模拟余额、写交易和审计；无真实支付             |
| `bill.monthly_summary` | 月份/可选类别 / 收支、类别、趋势、提示 | `read_only` / `low` / `never`            | 从当前 actor 的真实合成交易记录计算，不由模型计算金额                            |
| `bill.transactions`    | 月份/类别/商户 / 合成流水              | `read_only` / `low` / `never`            | 返回匹配流水和总数；服务端限制最多 100 条                                        |
| `bill.anomalies`       | 月份 / 规则匹配流水                    | `read_only` / `low` / `never`            | 标记非住房大额支出及同账户/商户/金额/币种/UTC 日重复收费；仅为提示，不是欺诈检测 |
| `subscription.list`    | 空输入 / 订阅、周期费用及下次模拟扣款  | `read_only` / `low` / `never`            | 返回基于周期合成交易识别并入库的订阅                                             |
| `subscription.pause`   | 商户名 / 操作提案与挑战                | `reversible_write` / `medium` / `always` | 仅创建服务端确认挑战；不调用真实商户或扣款网络                                   |
| `subscription.resume`  | 商户名 / 操作提案与挑战                | `reversible_write` / `medium` / `always` | 仅创建服务端确认挑战；目标状态为 active                                          |
| `subscription.cancel`  | 商户名 / 操作提案与挑战                | `reversible_write` / `medium` / `always` | 仅创建服务端确认挑战；目标状态为 cancelled                                       |

转账和理财受控工具包括 `transfer.accounts`、`transfer.payees`、`transfer.history`、`transfer.create`、`transfer.schedule`、`transfer.cancel_scheduled`、`transfer.simulate_due`、`transfer.splits`、`transfer.split_create`、`transfer.split_collect`；`investment.products`、`investment.compare`、`investment.profile`、`investment.portfolio`、`investment.orders`、`investment.buy`、`investment.redeem`。`finance.payday_plan` 是只读确定性 Application 用例，按账户余额、月度收支、用户指令和预留金额计算可用资金，不由模型计算余额或资金额度。所有读取按 actor 限定；资金变更工具只创建服务端 challenge，确认时再次校验账户归属、余额/持仓、参数摘要、资源版本、策略版本、有效期及幂等键。定时转账只由开发/测试环境里的显式模拟器执行。
`transfer.create` 与 `transfer.schedule` 可用已保存姓名或用户明确给出的完整模拟手机号定位收款人，服务端精确匹配，找不到即拒绝；可选备注视为不可信数据，写入记录并绑定确认摘要。Agent 不能根据掩码猜出完整号码，也不能把用户给出的号码替换为其他号码。
`investment.assessment_questions` 只读返回固定版本问卷。Agent 可以引导用户测评，但不能代填答案或直接设置风险等级；用户在应用内自行提交，服务端确定性评分并持久化。申购确认会重新读取最新画像核对适当性。

跨场景 Workflow 由受控工具序列组合，不新建业务旁路：可疑扣款主线先读 `bill.anomalies` 和 `subscription.list`，只在重复扣费规则命中且能关联来源卡与活动订阅时提出冻结/暂停操作；发薪日主线读取账户、账单并调用 `finance.payday_plan`，之后才可提出转账与理财操作。发薪日联动缺少转账额或预留额时保持 `awaiting_input`，后续输入会附加到原任务目标。每个写操作各自暂停等待服务端确认；确认后续跑原 Task。Application 在完成态校验明确请求的写操作是否存在成功 ToolExecution；若仍缺少明确操作，最多触发两轮有界重规划，之后模型仍不能只读数据后把未完成写目标标为成功。部分成功保留已提交的账本与审计记录，失败后可由用户重新输入继续；取消只阻止未执行步骤，不回滚已成功步骤。

订阅变更确认与卡片共用 Agent Task 确认 API、幂等机制和通用审计；challenge 绑定 `resource_type/resource_id`、资源版本、工具/参数/策略、actor、幂等键及有效期。订阅状态转换由后端领域规则限制为 `active→paused`、`paused→active`、`active|paused→cancelled`，已取消订阅不可恢复。

实际 Pydantic Schema 和版本定义在 `apps/api/src/finorch_api/agent/tools.py`、`application/agent.py`；新增工具必须有明确 handler、权限/风险/确认元数据、测试和审计，不允许模型自行注册工具。

## Tool 元数据

每项工具至少声明：

| 字段                       | 约定                                                                                          |
| -------------------------- | --------------------------------------------------------------------------------------------- |
| `tool_name`                | 稳定、命名空间化标识，如 `transfer.create`；弃用前不可复用                                    |
| `description`              | 适用意图、前置条件、影响和禁止边界；供模型阅读但不作为授权                                    |
| `input_schema`             | 版本化 JSON Schema；拒绝未声明字段和无效范围                                                  |
| `output_schema`            | 明确成功结果、失败、等待确认和执行状态                                                        |
| `permission_level`         | `read_only`、`reversible_write`、`high_risk_write`                                            |
| `risk_level`               | `low`、`medium`、`high`、`critical`；与权限分级关联但不互相替代                               |
| `confirmation_requirement` | `never`、`conditional`、`always`；最终由服务端策略计算                                        |
| `execution_status`         | `accepted`、`awaiting_confirmation`、`running`、`succeeded`、`failed`、`cancelled`            |
| `error`                    | 稳定 `code`、安全 `message`、可选字段/重试元信息；不得包含秘密                                |
| `audit_metadata`           | actor、task/tool execution ID、时间、风险级别、策略版本、幂等键摘要和结果引用；不复制敏感正文 |

## Tool 请求/响应草图（示例，非已实现接口）

```json
{
  "tool_name": "transfer.create",
  "input": {
    "recipient_id": "synthetic-recipient-001",
    "amount_minor": 1250,
    "currency": "USD",
    "idempotency_key": "demo-transfer-001"
  }
}
```

```json
{
  "tool_execution_id": "exec_01J...",
  "status": "awaiting_confirmation",
  "result": null,
  "error": null,
  "confirmation": { "required": true, "challenge_id": "confirm_01J..." },
  "audit_metadata": { "task_id": "task_01J...", "risk_level": "high" }
}
```

真实工具的权限、Schema、返回结果和确认阈值必须由服务端定义。上方 JSON 仅为通用契约示例，不代表支持转账。

## 标准执行生命周期

```text
Validation -> Authorization -> Confirmation -> Execution -> Audit
```

1. **Validation**：验证 schema、当前资源状态、范围、幂等键和业务约束。
2. **Authorization**：服务端验证身份、资源归属、权限级别和策略；模型提供的角色声明不可信。
3. **Confirmation**：服务端按风险策略决定是否需要确认；高风险写操作由用户明确确认，并绑定将执行的输入摘要、操作、有效期和挑战 ID。确认后若输入改变，重新确认。
4. **Execution**：在幂等边界内调用领域用例。卡片或订阅确认路径在一个 SQLite 写事务中复核 challenge、消费确认、变更对应资源并更新 Task/Step/ToolExecution。
5. **Audit**：记录请求、策略决定、确认、执行结果、actor 和时间。审计记录不应包含不必要的敏感字段。

Agent 不可跳过其中任一步骤。工具失败、超时和部分完成都必须返回实际服务端状态。

## Workflow 状态协议

顶层任务状态已在数据库约束和 Application 转换表实现：`pending`、`planning`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`cancelled`。

| 当前状态                  | 允许的下一状态                                                                    |
| ------------------------- | --------------------------------------------------------------------------------- |
| `pending`                 | `planning`、`cancelled`                                                           |
| `planning`                | `awaiting_input`、`awaiting_confirmation`、`running`、`failed`、`cancelled`       |
| `awaiting_input`          | `planning`、`cancelled`                                                           |
| `awaiting_confirmation`   | `running`、`planning`、`cancelled`、`failed`（过期/拒绝按产品策略终结）           |
| `running`                 | `awaiting_input`、`awaiting_confirmation`、`completed`、`failed`、`cancelled`     |
| `completed` / `cancelled` | 终态；不能继续或重放                                                              |
| `failed`                  | 有至少一个成功工具执行时，可通过 `/input` 补充信息后转 `planning`；否则需新建任务 |

服务端校验状态转换并记录版本/事件。`failed` 不是无条件可恢复：只有保留了成功工具执行的部分成功任务，才接受补充输入继续运行。前端只能展示状态，不能自行推动状态。

## 任务、步骤和工具记录

- 一个 `task` 表示用户目标和当前顶层状态。
- 一个 `task_step` 属于一个 task，按顺序记录可解释计划步骤、状态、输入/输出摘要和失败信息。
- 一个 `tool_execution` 属于一个 step（必要时通过 task ID 追踪），记录 tool 名、版本、幂等键、执行状态、确认引用、结果摘要和错误。
- 一次工具执行不得仅以模型文本当作结果；结果必须来自服务端工具。

## 确认、恢复与取消

- 任何资金移动、不可逆操作、权限提升或高风险隐私变更必须服务端确认。确认展示实际收款对象、金额/币种、影响和有效期。
- 当前实现的取消仅允许尚未完成的本地任务；它取消待确认 challenge 和未完成 TaskStep，不会撤销已提交业务状态。取消请求使用 `Idempotency-Key`，相同键重试返回已保存任务结果。未来如增加可长时间运行工具，需另行设计运行中取消与补偿，不可假设当前支持。
- `GET /api/v1/agent/tasks/recent?conversation_id=...` 按服务端 actor 和会话关联 ID 优先返回最近的活动任务；没有活动任务时返回最近终态任务。`GET /api/v1/agent/tasks/by-idempotency-key/{key}` 还要求操作类型、会话 ID 和非创建操作的 task ID。二者不接受客户端身份或角色。
- 任务读取会由服务端惰性结算已过期的待确认挑战：将 Task/Step/ToolExecution 标记为失败、追加过期审计，并保持卡片不变。过期确认不会显示为仍可执行的挑战。
- 失败恢复仅重试幂等、可证明尚未生效或可查询的步骤；未知结果先按 actor、会话、操作类型和幂等键查询，再显示状态或使用原始参数/同一幂等键安全重试。不得直接生成新键重放写请求。
- 多步任务部分成功时保留已完成事实，标记后续失败/取消步骤，向用户披露已发生和未发生的变化；不宣称原子事务。

## 前端进度订阅

当前前端使用 REST 查询 Task 快照与 Task Audit；刷新时通过服务端恢复最近任务，不恢复未由服务端记录的聊天历史。`sessionStorage` 仅保存会话关联 ID 和待核实写请求的重试信息，绝不作为身份或授权凭证。没有实现 SSE 或 WebSocket。未来可以评估认证保护的 SSE；具体传输方式需在实现前 ADR 评估。Demo Identity 仅用于本机 development/test，不能用作远程部署的认证机制。
