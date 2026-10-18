# Banking Core 接口说明（Phase 1A）

本文是 Banking Core 的共享调用入口。所有场景模块都通过 Application 用例操作数据；API、Agent 和前端不得直接写 ORM 表、拼 SQL 或自行提交业务事务。

## 模块边界

- `domain/`：纯业务状态和转换规则；不依赖 SQLAlchemy、FastAPI 或模型服务。
- `application/`：确定性用例、DTO、资源授权查询和写事务边界。
- `infrastructure/`：共享 SQLAlchemy Base、engine/session factory、ORM 模型和持久化查询。
- `api/`：HTTP Schema、身份依赖、参数校验和响应；只调用 Application。
- `security/`：当前提供 development/test 专用的服务端 DemoActor；后续真实身份和确认策略尚未实现。

## Session 与事务归属

`infrastructure.database.get_db_session()` 是 API 请求使用的唯一 Session provider：按配置选择共享 session factory，为请求创建并关闭 Session。迁移和 CLI 使用同一 `build_engine`/`get_session_factory` 配置入口。模块不得私建连接或第二套 Session 管理。

读用例只读传入 Session，不拥有提交。业务写 Application 用例负责完整的 `begin`、`commit`、`rollback`；卡片状态和 `AuditEvent` 在同一事务中写入。调用方不能在调用写用例前用这个 Session 开启未结束的事务；需要先读取时，在用例内完成检查，或使用独立 Session。SQLAlchemy 乐观版本字段用于检测并发状态变更。

## Card Application API

入口：`finorch_api.application.cards`

```python
from uuid import UUID

from finorch_api.application.cards import freeze_card, get_card, list_cards, unfreeze_card
from finorch_api.infrastructure.database import get_session_factory

actor_id: UUID  # 必须来自服务端授权上下文，不来自请求体/查询参数
card_id: UUID
session_factory = get_session_factory(database_url)

with session_factory() as session:
    cards = list_cards(session, actor_id=actor_id, limit=20)

with session_factory() as session:
    updated = freeze_card(
        session, actor_id=actor_id, card_id=card_id, request_id="request-id"
    )
```

- `list_cards(session, actor_id, limit, after_id=None) -> CardPage`：只返回该 actor 所属账户的卡片。
- `get_card(session, actor_id, card_id) -> CardView`：资源不存在或不属于 actor 时抛出 `CardNotFoundError`。
- `freeze_card(...)` / `unfreeze_card(...) -> CardView`：仅允许 `active → frozen` 和 `frozen → active`；无效转换抛出 `InvalidCardTransition`。成功改变状态时在同一事务追加一条审计事件；失败或异常时状态和审计一并回滚。
- 并发版本冲突抛出 `CardWriteConflictError`。调用方应返回可识别冲突或按上层幂等策略处理，不可假报成功。

当前 API 只暴露两个 GET 端点。冻结/解冻没有 HTTP 入口；Agent 也尚未实现。未来要暴露写操作，必须先设计服务端授权、确认和幂等边界，再把受控调用接到相同 Application 用例，不复制状态规则。

## Seed 与 Reset

- `python -m finorch_api.seed`：仅 development/test 可运行；幂等插入固定 UUID 的 `phase1a-v1` 合成数据，不覆盖现有业务变更。
- `python -m finorch_api.reset --confirm`：仅 development 的仓库 `.data/finorch.db` 或 test 下临时 `finorch-test*.sqlite3` 可执行；清空当前 Demo 表并恢复 seed。必须显式 `--confirm`，拒绝其他环境、路径和数据库文件。
- 不将 seed 账户余额解释为账本事实或可转账资金；它只是演示初始值。

## 开发协作约定

新增或修改实体由 Banking Core 负责人维护 ORM、迁移和数据契约；Application 边界由相关业务负责人共同审查；API Schema 变更同步 OpenAPI、生成类型和接口文档。测试应使用 `apps/api/tests` 提供的临时 SQLite fixture，不共享本地 `.data` 数据库。
