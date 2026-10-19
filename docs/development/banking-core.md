# Banking Core 与 Card Agent 接口说明（Phase 1B）

本文是 Banking Core 的共享调用入口。所有场景模块都通过 Application 用例操作数据；API、Agent 和前端不得直接写 ORM 表、拼 SQL 或自行提交业务事务。

## 模块边界

- `domain/`：纯业务状态和转换规则；不依赖 SQLAlchemy、FastAPI 或模型服务。
- `application/`：确定性用例、DTO、资源授权查询和写事务边界。
- `infrastructure/`：共享 SQLAlchemy Base、engine/session factory、ORM 模型和持久化查询。
- `api/`：HTTP Schema、身份依赖、参数校验和响应；只调用 Application。
- `security/`：当前提供 development/test 专用的服务端 DemoActor；真实身份认证仍未实现，卡片确认策略由 `application.agent` 的服务端用例执行。

## Session 与 Unit of Work

`infrastructure.database.get_db_session()` 是 API 请求使用的唯一 Session provider：按配置选择共享 session factory，为请求创建并关闭 Session。迁移和 CLI 使用同一 `build_engine`/`get_session_factory` 配置入口。模块不得私建连接或第二套 Session 管理。

`get_db_session` 只负责 Session 生命周期，不自动提交业务事务。SQLAlchemy 查询会触发 autobegin；`application.transactions.write_transaction()` 是统一写事务入口：如果当前只有读取产生的干净事务，它先关闭该只读事务，再开始业务写事务；如果已有待提交写入但不在该 helper 管理的 Unit of Work 中，则拒绝继续；在显式 `write_transaction` 内的嵌套 Application 调用加入当前事务，不再启动不兼容的嵌套事务。顶层写用例负责提交或回滚，API 依赖在请求结束关闭 Session。SQLite 确认流程使用 `BEGIN IMMEDIATE` 串行化确认竞争。

卡片状态、确认消费、ToolExecution、Task/Step 状态与对应 AuditEvent 由同一显式事务提交或回滚。卡片 ORM 使用乐观版本字段；确认时还会在写锁内复核 challenge 绑定的卡片版本。不要在事务中调用外部模型服务；模型规划在业务写事务以外完成。

## Card Application API

入口：`finorch_api.application.cards`

```python
from uuid import UUID

from finorch_api.application.cards import get_card, list_cards
from finorch_api.infrastructure.database import get_session_factory

actor_id: UUID  # 必须来自服务端授权上下文，不来自请求体/查询参数
card_id: UUID
session_factory = get_session_factory(database_url)

with session_factory() as session:
    cards = list_cards(session, actor_id=actor_id, limit=20)

```

- `list_cards(session, actor_id, limit, after_id=None) -> CardPage`：只返回该 actor 所属账户的卡片。
- `get_card(session, actor_id, card_id) -> CardView`：资源不存在或不属于 actor 时抛出 `CardNotFoundError`。
- `freeze_card(...)` / `unfreeze_card(...) -> CardView`：仅允许 `active → frozen` 和 `frozen → active`；无效转换抛出 `InvalidCardTransition`。仅由 Application 确认用例 `confirm_card_change` 在验证一次性 challenge 后调用；路由、Agent Provider 和 Web 不得直接调用或写 ORM。成功改变状态时在同一事务追加通用 `card.status_changed` 审计事件；失败时状态和审计一并回滚。
- 并发版本冲突抛出 `CardWriteConflictError`。调用方应返回可识别冲突或按上层幂等策略处理，不可假报成功。

## Agent / Workflow 调用边界

- `application.agent.create_agent_task` 建立 Task，再把用户文本、可信服务端上下文和已注册工具交给有界 `AgentRuntime`；Provider 只返回建议的工具调用，不持有 Session。
- 工具实现使用允许列表并通过 Pydantic Input/Output Schema 校验。只读卡片工具调用 `list_cards` / `get_card`；冻结/解冻工具只验证资源归属并创建 challenge，不改卡状态。
- `application.agent.confirm_card_change` 是唯一的卡片确认写路径。它在单一 Unit of Work 内复核 actor、card、tool/version、参数摘要、策略版本、卡片版本、有效期和幂等键，消费 challenge，调用 `freeze_card` / `unfreeze_card` 并写执行/审计状态。
- Web 只消费 API DTO 和 OpenAPI 生成类型，不读取数据库，不根据模型文本推断执行结果。

`/api/v1/agent/tasks` 及其 `/recent`、`/by-idempotency-key/{key}`、`/{task_id}`、`/input`、`/confirm`、`/cancel`、`/audit` 路径的 DTO 与行为以 [API 契约](../api-contract.md)和 FastAPI OpenAPI 为准。任务恢复查询按服务端 actor、会话和操作类型过滤；读取过期确认时会惰性结算 Workflow 与审计，但不改变卡片。当前 Demo actor 仅用于 development/test，不构成真实认证。

## Seed 与 Reset

- `python -m finorch_api.seed`：仅 development/test 可运行；幂等插入固定 UUID 的 `phase1a-v1` 合成数据，不覆盖现有业务变更。
- `python -m finorch_api.reset --confirm`：仅 development 的仓库 `.data/finorch.db` 或 test 下临时 `finorch-test*.sqlite3` 可执行；清空业务、Agent Workflow、确认和审计记录后恢复 seed。必须显式 `--confirm`，拒绝其他环境、路径和数据库文件。
- 不将 seed 账户余额解释为账本事实或可转账资金；它只是演示初始值。

## 开发协作约定

新增或修改实体由 Banking Core 负责人维护 ORM、迁移和数据契约；Application 边界由相关业务负责人共同审查；API Schema 变更同步 OpenAPI、生成类型和接口文档。测试应使用 `apps/api/tests` 提供的临时 SQLite fixture，不共享本地 `.data` 数据库。
