# Agent、Tool 与 Workflow 契约

> 下述为设计约定。Phase 1A 仍不包含 Agent Runtime、工具执行器或任务调度器；未来调用 Banking Core 的边界见[接口说明](development/banking-core.md)。

## Agent 边界

- Agent 可分析意图、提出澄清问题、生成计划并请求调用获准的工具。
- Agent 和模型输出是不可信输入，不能直接访问数据库、调整余额、修改权限或宣称工具成功。
- 所有写操作进入服务端验证、授权、风险策略、确认和审计流程。
- Tool Provider 与模型 Provider 应可替换；模型响应仅作为建议，服务端 Tool Schema 和业务规则为准。
- Provider 接口应允许 OpenAI-compatible API，配置不得要求特定供应商。当前不持有模型密钥，也不发起 LLM 请求。

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

真实工具的权限、Schema、返回结果和确认阈值必须由服务端定义。示例不代表支持真实转账或当前可运行。

## 标准执行生命周期

```text
Validation -> Authorization -> Confirmation -> Execution -> Audit
```

1. **Validation**：验证 schema、当前资源状态、范围、幂等键和业务约束。
2. **Authorization**：服务端验证身份、资源归属、权限级别和策略；模型提供的角色声明不可信。
3. **Confirmation**：服务端按风险策略决定是否需要确认；高风险写操作由用户明确确认，并绑定将执行的输入摘要、操作、有效期和挑战 ID。确认后若输入改变，重新确认。
4. **Execution**：在幂等边界内调用领域用例。重试必须能区分“未执行”和“结果未知”，不得造成重复副作用。
5. **Audit**：记录请求、策略决定、确认、执行结果、actor 和时间。审计记录不应包含不必要的敏感字段。

Agent 不可跳过其中任一步骤。工具失败、超时和部分完成都必须返回实际服务端状态。

## Workflow 状态协议

顶层任务状态：`pending`、`planning`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`cancelled`。

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
- 取消阻止尚未启动的步骤，并向运行中的工具发送可取消请求；取消不是自动回滚。回滚或补偿只能由显式的领域流程实现并审计。
- 失败恢复仅重试幂等、可证明尚未生效或可查询的步骤；未知结果先查询执行状态，不直接重放。
- 多步任务部分成功时保留已完成事实，标记后续失败/取消步骤，向用户披露已发生和未发生的变化；不宣称原子事务。

## 前端进度订阅（Planned）

未来优先考虑认证保护的 Server-Sent Events（SSE）订阅任务事件；断线后用事件 ID 或当前任务快照恢复，必要时提供轮询快照端点。事件应有 schema、单调序号和 request/task IDs，不发送敏感载荷。具体传输方式需在实现前 ADR 评估。当前只显示 API 健康状态。
