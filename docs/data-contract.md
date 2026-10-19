# 数据契约与建模规则

> Phase 1A–1C 已实现 SQLite/SQLAlchemy/Alembic、合成卡片与交易数据、订阅记录，以及 `agent_tasks`、`task_steps`、`tool_executions`、卡片/订阅共用的 `confirmation_challenges` 和通用 `audit_events`。智能转账和理财实体仍为 Planned；以下规则同时约束当前实现和后续扩展。

## 数据边界

- 所有开发、测试和演示金融记录必须是合成数据，并明确标注数据集版本；不得导入真实用户、账户、交易、卡或银行数据。
- 业务数据、Agent 运行状态和安全审计事件按用途分离。Agent 状态不作为业务账本事实，审计记录也不代替领域记录。
- 模拟场景使用固定、可追溯的 fixture 版本和确定性 ID；开发/演示环境提供重置与重放入口，并在重置前显示目标环境和数据集版本。重置不得影响非本地环境。

## 金额、货币与时间

- 金额使用整数 `amount_minor`，同时存储 ISO 4217 `currency`；不使用 IEEE-754 浮点。
- 小数位数从货币元数据/ISO 4217 规则读取，不假设所有币种都是两位。跨币种数据要显式保存汇率来源、汇率时间、精度和舍入方式；Phase 0 不处理汇率。
- 数据库保存 UTC 时间戳；API 使用带时区偏移的 ISO 8601/RFC 3339 字符串。只有业务含义是日历日时才用无时区日期。

## 命名与迁移

- ORM 类名使用 PascalCase；表、列和索引名使用 `snake_case`。表采用复数名，如 `accounts`、`transactions`、`agent_tasks`、`audit_events`。
- 主键统一使用 UUID（以 SQLite 兼容的文本形式存储）；外键显式命名为 `<singular_entity>_id`。时间列使用 `created_at`、`updated_at`，软删除只在明确需要时添加。
- SQLAlchemy 模型放在 `apps/api/src/finorch_api/infrastructure/models.py`；Domain 规则不依赖 ORM 实体。API DTO 与 ORM 模型分离。
- DDL 变更通过 `apps/api/alembic/` 的 Alembic 迁移管理；迁移可审阅、有上下行策略说明；不得在运行时静默创建或改表。

## 当前实体与后续规划

首批已实现实体及字段以 ORM 模型和 Alembic 迁移为准：

- `demo_users`：固定合成用户及 `dataset_version`，不含真实登录资料。
- `accounts`：所属 DemoUser、标签、币种和 `opening_balance_minor`。这是演示初始余额，不是账本余额，也不能用于资金变更。
- `cards`：所属 Account、展示标签、假卡号后四位、`active`/`frozen` 状态、乐观并发 `version`。
- `agent_tasks`：actor、conversation、幂等作用域、Provider 模式、受限长度的用户请求和 Workflow 状态。仅用于合成 Demo；不保存凭据或完整拼装后的系统 Prompt。
- `task_steps`：任务内按 sequence 排列的规划、工具和用户输入/取消步骤，带状态与安全摘要。
- `tool_executions`：注册工具名/版本、幂等键摘要、输入摘要、实际执行状态和受 Schema 限制的结果。
- `confirmation_challenges`：一次性绑定 actor、单一目标资源（卡片或订阅）、tool/version、目标状态、参数摘要、对应资源版本、策略版本、幂等键、有效期和消费状态的服务端挑战；数据库约束保证只关联一种资源。
- `audit_events`：通用 actor、event type、resource、request/task/tool execution ID、outcome、可选前后状态摘要和 UTC 时间；兼容既有卡片状态语义。正常业务路径只追加，不覆盖或删除历史。不得在审计事件中存密钥、原始敏感数据或完整 Prompt。

`seed` 会按固定 UUID 插入缺失样例并将两位固定 Demo User 的 `dataset_version` 更新为当前值；不会重置既有卡片或订阅状态。当前数据集版本为 `phase1c-v1`，包含两位模拟用户、账户、卡片、2026 年合成交易流水及由重复月度扣款识别出的订阅。显式 `reset --confirm` 仅允许 development 环境的仓库 `.data/finorch.db` 或 test 环境中的临时 `finorch-test*.sqlite3` 文件，并清除业务、Agent Workflow、确认及审计记录后重建合成样例。禁止将重置指向其他 SQLite 文件。

下表为后续场景实体草图，不代表已实现：

| 实体                      | 主要关系                                                      | 说明                                                                      |
| ------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `demo_users`              | 1 对多 `accounts`                                             | 已实现；仅演示身份，不存真实登录资料                                      |
| `accounts`                | 多对 1 `demo_users`；1 对多 `ledger_entries`                  | 基础合成账户已实现；账本关系仍为 Planned                                  |
| `transactions`            | 多对 1 `accounts`；可作为订阅检测来源                         | 已实现合成收支流水及按月份、类别、商户筛选；不直接作为余额事实            |
| `ledger_entries`          | 多对 1 `accounts`；可选关联 `transfer_id`、`transaction_id`   | 不可变的模拟账务条目；金额符号和借贷方向由领域契约确定                    |
| `transfers`               | 多对 1 source/destination `accounts`；1 对多 `ledger_entries` | 一次模拟转账的业务聚合，不能由模型直接写表                                |
| `cards`                   | 多对 1 `accounts`                                             | 已实现 active/frozen 与假卡号后四位；扩展场景仍为 Planned                 |
| `subscriptions`           | 多对 1 `accounts`；记录来源交易 ID                            | 已实现周期候选持久化、月费/下次模拟扣款和经确认的状态管理；不操作真实商户 |
| `investment_products`     | 1 对多 `investment_holdings`                                  | 使用明确标记的演示产品信息，不暗示真实投资建议                            |
| `investment_holdings`     | 多对 1 `accounts` 和 `investment_products`                    | 持仓快照与币种；未来操作记录需审计                                        |
| `agent_tasks`             | 1 对多 `task_steps`                                           | 已实现；受限保存用户请求和 Workflow 当前状态                              |
| `task_steps`              | 多对 1 `agent_tasks`；1 对多 `tool_executions`                | 已实现；有序规划、输入、取消和工具步骤及安全错误摘要                      |
| `tool_executions`         | 多对 1 `task_steps`；可关联领域业务记录                       | 已实现；受控工具调用状态、幂等引用、结果和错误                            |
| `confirmation_challenges` | 多对 1 `agent_tasks` / `cards` / `tool_executions`            | 已实现；绑定 actor、目标、版本、摘要和有效期的一次性确认                  |
| `audit_events`            | 引用 actor、task/tool execution 和业务资源                    | 已实现通用追加事件；保存执行结果及可选前后状态摘要                        |

余额的权威值由服务端对已提交账务条目计算或维护受控投影，永不由前端或模型提供。关系采用最小必要字段；财务流水、任务状态和审计状态不得通过覆盖历史来隐藏既有结果。具体表结构、索引、删除保留策略和事务边界需各场景实现前另行评审。

## 敏感字段与日志

- 分类并最小化：内部 synthetic IDs、账户/卡展示标识、用户输入、确认挑战、认证秘密分别管理。
- 不保存完整支付卡号、真实账号、真实身份证号码、访问令牌或不必要的原始提示词。演示卡号应为假数据并明确标注。
- 日志和错误响应不复制原始敏感 payload；账户/手机号只以不可逆或截断形式呈现。日志脱敏规则与审计记录字段使用一致的数据分类。
- 若后续引入加密、保留期或删除能力，须写明密钥管理、备份和审计边界；不要把“模拟数据”当作不需保护的理由。
