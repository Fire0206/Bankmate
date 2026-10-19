# Agent、Tool 与 Workflow 契约

> Phase 1B 已交付本地卡片切片：有界单 Agent、Typed Tool Registry、持久化 Task/Step/ToolExecution/ConfirmationChallenge、确认后卡片冻结/解冻及 REST 任务读取。Phase 1B.5 增加 Provider Mock 验证、actor 范围任务恢复与安全同键重试；真实模型服务仍未验证。其余银行工具与场景仍为 Planned。Banking Core 调用边界见[接口说明](development/banking-core.md)。

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
- Agent Loop 最多处理 4 轮工具调用，累计 `tool_calls` 不超过 4 次，并最多额外请求一轮无工具的最终响应；同一轮可有多个 `tool_calls`，每个工具结果都按原 `tool_call_id` 回送。重复的工具名与规范化参数组合会失败停止；未知工具、非法 JSON/Schema、无效/重复调用 ID、Provider 错误和步数上限都不会执行未验证的业务操作。
- 模型仅返回文本而没有提出已注册工具调用时，服务端不会把文本作为执行结果；会返回未执行操作/等待补充信息状态。完成只读工具后也由服务端生成“已查询、未改变卡片状态”的消息。
- Fake Provider 的流程由 pytest 验证；真实 Adapter 通过 Mock HTTP 验证 Chat Completions 请求、`tools`/`tool_choice`、多工具及多轮 `tool_call_id` 配对、无工具响应、错误响应、超时和连接中断。当前未对任何实际模型供应商进行网络连通性、模型行为或付费调用测试。

当前允许工具：

| Tool            | 输入/输出                      | 权限 / 风险 / 确认                       | 实际行为                                               |
| --------------- | ------------------------------ | ---------------------------------------- | ------------------------------------------------------ |
| `card.list`     | 空输入 / 当前用户卡片列表      | `read_only` / `low` / `never`            | Application 查询 actor 自己的合成卡片                  |
| `card.get`      | `card_suffix` / 一张卡的 DTO   | `read_only` / `low` / `never`            | actor 范围内按尾号查询，不存在或越权统一视为 not found |
| `card.freeze`   | `card_suffix` / 操作提案与挑战 | `reversible_write` / `medium` / `always` | 校验归属和状态并建 challenge；本步骤不改变卡片状态     |
| `card.unfreeze` | `card_suffix` / 操作提案与挑战 | `reversible_write` / `medium` / `always` | 校验归属和状态并建 challenge；本步骤不改变卡片状态     |

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
4. **Execution**：在幂等边界内调用领域用例。卡片确认路径在一个 SQLite 写事务中复核 challenge、消费确认、变更卡片并更新 Task/Step/ToolExecution。
5. **Audit**：记录请求、策略决定、确认、执行结果、actor 和时间。审计记录不应包含不必要的敏感字段。

Agent 不可跳过其中任一步骤。工具失败、超时和部分完成都必须返回实际服务端状态。

## Workflow 状态协议

顶层任务状态已在数据库约束和 Application 转换表实现：`pending`、`planning`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`cancelled`。

| 当前状态                             | 允许的下一状态                                                                |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| `pending`                            | `planning`、`cancelled`                                                       |
| `planning`                           | `awaiting_input`、`awaiting_confirmation`、`running`、`failed`、`cancelled`   |
| `awaiting_input`                     | `planning`、`cancelled`                                                       |
| `awaiting_confirmation`              | `running`、`planning`、`cancelled`、`failed`（过期/拒绝按产品策略终结）       |
| `running`                            | `awaiting_input`、`awaiting_confirmation`、`completed`、`failed`、`cancelled` |
| `completed` / `failed` / `cancelled` | 终态；重试应创建新尝试或任务                                                  |

服务端校验状态转换并记录版本/事件。前端只能展示状态，不能自行推动状态。

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
