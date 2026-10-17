# 数据契约与建模规则

> 当前没有数据库、SQLAlchemy 模型、迁移或业务数据。以下是 Phase 1 起实施前应遵循的设计规则。

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
- SQLAlchemy 模型未来放入 Infrastructure/Data 模块，Domain 规则不依赖 ORM 实体。
- DDL 变更通过 Alembic 迁移管理，迁移可审阅、有上下行策略说明；不得在运行时静默创建或改表。当前尚未安装 SQLAlchemy/Alembic。

## 逻辑实体与关系（Planned）

下表是首批模拟数据的关系草图，不是已实现模型或完整字段清单。

| 实体                  | 主要关系                                                      | 说明                                                                  |
| --------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------- |
| `demo_users`          | 1 对多 `accounts`                                             | 仅演示身份；不存真实登录资料                                          |
| `accounts`            | 多对 1 `demo_users`；1 对多 `ledger_entries`                  | 记录合成账户及币种，不存真实银行账号                                  |
| `transactions`        | 多对 1 `accounts`；可选映射 `subscriptions`                   | 账单分析使用的合成交易明细/导入记录；不直接作为余额事实               |
| `ledger_entries`      | 多对 1 `accounts`；可选关联 `transfer_id`、`transaction_id`   | 不可变的模拟账务条目；金额符号和借贷方向由领域契约确定                |
| `transfers`           | 多对 1 source/destination `accounts`；1 对多 `ledger_entries` | 一次模拟转账的业务聚合，不能由模型直接写表                            |
| `cards`               | 多对 1 `accounts`                                             | 使用假卡号或稳定合成引用；展示值脱敏                                  |
| `subscriptions`       | 多对 1 `accounts`；可选关联多条 `ledger_entries`              | 订阅识别候选及用户确认后的模拟管理状态                                |
| `investment_products` | 1 对多 `investment_holdings`                                  | 使用明确标记的演示产品信息，不暗示真实投资建议                        |
| `investment_holdings` | 多对 1 `accounts` 和 `investment_products`                    | 持仓快照与币种；未来操作记录需审计                                    |
| `agent_tasks`         | 1 对多 `task_steps`                                           | 记录用户目标引用和 Workflow 当前状态；对话全文按需最小化保存          |
| `task_steps`          | 多对 1 `agent_tasks`；1 对多 `tool_executions`                | 有序计划步骤、状态与安全错误摘要                                      |
| `tool_executions`     | 多对 1 `task_steps`；可关联领域业务记录                       | 受控工具调用状态、幂等引用、确认引用和结果摘要                        |
| `audit_events`        | 引用 actor、task/tool execution 和业务资源                    | 追加式安全事件；通过资源类型 + ID 关联，避免 audit 表承担业务外键体系 |

余额的权威值由服务端对已提交账务条目计算或维护受控投影，永不由前端或模型提供。关系采用最小必要字段；财务流水、任务状态和审计状态不得通过覆盖历史来隐藏既有结果。具体表结构、索引、删除保留策略和事务边界需各场景实现前另行评审。

## 敏感字段与日志

- 分类并最小化：内部 synthetic IDs、账户/卡展示标识、用户输入、确认挑战、认证秘密分别管理。
- 不保存完整支付卡号、真实账号、真实身份证号码、访问令牌或不必要的原始提示词。演示卡号应为假数据并明确标注。
- 日志和错误响应不复制原始敏感 payload；账户/手机号只以不可逆或截断形式呈现。日志脱敏规则与审计记录字段使用一致的数据分类。
- 若后续引入加密、保留期或删除能力，须写明密钥管理、备份和审计边界；不要把“模拟数据”当作不需保护的理由。
