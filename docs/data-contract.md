# 数据契约与建模规则

> Phase 1A–1E 已实现 SQLite/SQLAlchemy/Alembic、合成账户/卡片/交易/订阅/转账/分账/理财数据，以及支持续跑的持久化 Agent Workflow、通用确认挑战和追加审计。以下规则适用于当前实现和后续扩展。

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

Phase 3 已接入的本地模拟强验证：`strong_verifications` 通过唯一 `confirmation_id` 绑定确认、actor 与参数/策略摘要。只保存带盐验证码摘要、尝试次数、有效期和生命周期状态；不保存明文 OTP。适用的高风险写操作在同一 SQLite 写事务中复核风险、消费验证并执行。该机制仅用于本地演示，不是生产认证。

首批已实现实体及字段以 ORM 模型和 Alembic 迁移为准：

- `demo_users`：固定合成用户及 `dataset_version`，不含真实登录资料。
- `accounts`：所属 DemoUser、标签、币种、`opening_balance_minor` 和由服务端事务维护的 `balance_minor` 投影；金额变化与对应交易记录在同一事务提交。
- `cards`：所属 Account、展示标签、假卡号后四位、`active`/`frozen`/`lost`/`replaced` 状态、乐观并发 `version`。`lost` 不能通过解冻恢复；经确认及本地模拟验证码可补发新合成卡，旧卡标记为 `replaced` 并通过 `replaced_by_card_id` 关联新卡。
- `card_applications`：当前模拟用户对已有账户提交的借记卡申请；`pending_confirmation` 仅为未提交提案，用户确认后变为 `submitted`；本地模拟审核给出 `approved`/`rejected`，批准时创建新合成卡并记录 `issued_card_id`。不得将其解释为真实银行信用审核或授信。
- `birthday_plans`：当前 actor 的生日日期、提前两天的到期提醒日期、所属合成账户、整数预算和固定商品参考总价。确认后从 `pending_confirmation` 变为 `scheduled`，但这仅是预算意向；`funds_held=false`、`order_placed=false`，不扣款也不锁定余额。到期时再次核对资金、卡片限制和交付方式，实际购买仍须新的用户授权及服务端确认；当前没有自动订单调度。
- `cards` 的模拟消费控制（Implemented）：单笔、同一 UTC+8 业务日累计上限和线上支付开关；限额仅约束明确选择该卡的固定目录模拟消费，不等于信用额度，也不直接限制独立的账户转账。服务端在确认事务中复核限制与余额，同事务写账户扣款、`transactions` 流水、卡版本和审计；不连接真实支付网络。
- `agent_tasks`：actor、conversation、幂等作用域、Provider 模式、受限长度的用户请求和 Workflow 状态。仅用于合成 Demo；不保存凭据或完整拼装后的系统 Prompt。
- `task_steps`：任务内按 sequence 排列的规划、工具和用户输入/取消步骤，带状态与安全摘要。
- `tool_executions`：注册工具名/版本、幂等键摘要、输入摘要、实际执行状态和受 Schema 限制的结果。
- `payees`、`transfers`、`split_bills`、`split_participants`：仅合成收款人、模拟转账及 AA 分账；`payees.phone_number` 可空且每 actor 唯一，仅精确匹配当前用户的模拟收款人，对外只返回掩码；`transfers.remark` 可空，作为不可信用户数据存储并参与确认参数摘要。转账/收款执行由 Application 用例在事务内更新余额与关联流水。
- `investment_products`、`investment_holdings`、`investment_orders`：确定性模拟产品和价格、风险等级、用户持仓及申购/赎回订单；不代表真实理财产品或收益。
- `risk_assessments`：用户主动提交的四项模拟风险问卷答案、问卷版本、确定性得分和风险等级；按时间追加保存，`demo_users.risk_level` 是最新测评等级的受控投影。提交由服务端按答案评分并写审计，Agent 只能读取问卷，不能代填或直接提高等级。重复 Seed 不覆盖已有用户等级；显式 Reset 清除测评并恢复合成初始值。
- `subscriptions` 的 `reminder_days_before`（0–30，默认 3）和 `last_reminded_charge_at` 记录应用内续费提醒设置与已生成提醒的扣款周期；仅有效订阅可生成提醒，同一周期不会重复生成。提醒审计以 `subscription.renewal_reminder_created` 追加记录，不代表真实商户扣款或外部通知送达。
- `confirmation_challenges`：一次性绑定 actor、单一目标资源（含银行卡、借记卡申请、生日计划、订阅、转账、AA 分账或理财订单）、tool/version、目标状态、参数摘要、对应资源版本、策略版本、幂等键、有效期和消费状态的服务端挑战；数据库约束保证只关联一种资源。
- `transactions`：模拟账单明细也记录内部资金操作；`entry_kind` 用于区分 `bill`、`transfer` 和 `investment`，账单统计只汇总 `bill`。可选 `card_id` 将来源卡与交易关联，以支持可解释的重复扣费证据。
- `audit_events`：通用 actor、event type、resource、request/task/tool execution ID、outcome、可选前后状态摘要和 UTC 时间；兼容既有卡片状态语义。正常业务路径只追加，不覆盖或删除历史。不得在审计事件中存密钥、原始敏感数据或完整 Prompt。

`seed` 会按固定 UUID 幂等插入合成样例。当前数据集版本为 `phase3-v1`，包含两位模拟用户、账户、卡片、模拟收款手机号、理财产品、合成流水和订阅，并含一组同日重复收费记录用于验证规则提示。显式 `reset --confirm` 仅允许 development 环境的仓库 `.data/finorch.db` 或 test 环境中的临时 `finorch-test*.sqlite3` 文件，并清除业务、Agent Workflow、确认及审计记录后重建合成样例。禁止将重置指向其他 SQLite 文件。

下表为后续场景实体草图，不代表已实现：

| 实体                                 | 主要关系                                           | 说明                                                                      |
| ------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------------- |
| `demo_users`                         | 1 对多 `accounts`                                  | 已实现；仅演示身份，不存真实登录资料                                      |
| `accounts`                           | 多对 1 `demo_users`；关联 `cards`、`transactions`  | 已实现；服务端在单个事务内维护余额投影和资金流水                          |
| `transactions`                       | 多对 1 `accounts`；可作为订阅检测来源              | 已实现合成账单及 transfer/investment 记账条目；账单统计仅查询 `bill` 类型 |
| `transfers`                          | 多对 1 source/destination `accounts` 和 `payees`   | 已实现普通/定时模拟转账，需服务端确认后执行                               |
| `split_bills` / `split_participants` | 分账归属 account/actor；参与者按金额顺序关联       | 已实现模拟 AA 拆分及受控的模拟收款                                        |
| `cards`                              | 多对 1 `accounts`                                  | 已实现 active/frozen/lost/replaced 与假卡号后四位；不存完整卡号           |
| `subscriptions`                      | 多对 1 `accounts`；记录来源交易 ID                 | 已实现周期候选持久化、月费/下次模拟扣款和经确认的状态管理；不操作真实商户 |
| `investment_products`                | 1 对多 `investment_holdings` / `investment_orders` | 已实现确定性模拟价格、风险等级和参考收益                                  |
| `investment_holdings`                | 多对 1 `accounts` 和 `investment_products`         | 已实现模拟持仓及余额变化                                                  |
| `investment_orders`                  | 多对 1 actor/account/product，可选关联 holding     | 已实现确认后的模拟申购/赎回订单                                           |
| `birthday_plans`                     | 多对 1 actor/account；确认挑战可引用               | 已实现预算意向和到期提醒；不锁资金、不自动下单                            |
| `agent_tasks`                        | 1 对多 `task_steps`                                | 已实现；受限保存用户请求和 Workflow 当前状态                              |
| `human_handoffs`                     | 1 对 1 `agent_tasks`；归属 Demo actor              | 已实现本地模拟人工处理工单与状态；不代表金融授权                          |
| `task_steps`                         | 多对 1 `agent_tasks`；1 对多 `tool_executions`     | 已实现；有序规划、输入、取消和工具步骤及安全错误摘要                      |
| `tool_executions`                    | 多对 1 `task_steps`；可关联领域业务记录            | 已实现；受控工具调用状态、幂等引用、结果和错误                            |
| `confirmation_challenges`            | 多对 1 `agent_tasks` / `cards` / `tool_executions` | 已实现；绑定 actor、目标、版本、摘要和有效期的一次性确认                  |
| `audit_events`                       | 引用 actor、task/tool execution 和业务资源         | 已实现通用追加事件；保存执行结果及可选前后状态摘要                        |

余额的权威值由服务端对已提交账务条目计算或维护受控投影，永不由前端或模型提供。关系采用最小必要字段；财务流水、任务状态和审计状态不得通过覆盖历史来隐藏既有结果。具体表结构、索引、删除保留策略和事务边界需各场景实现前另行评审。

## 敏感字段与日志

- 分类并最小化：内部 synthetic IDs、账户/卡展示标识、用户输入、确认挑战、认证秘密分别管理。
- 不保存完整支付卡号、真实账号、真实身份证号码、访问令牌或不必要的原始提示词。演示卡号应为假数据并明确标注。
- 日志和错误响应不复制原始敏感 payload；账户/手机号只以不可逆或截断形式呈现。日志脱敏规则与审计记录字段使用一致的数据分类。
- 若后续引入加密、保留期或删除能力，须写明密钥管理、备份和审计边界；不要把“模拟数据”当作不需保护的理由。
