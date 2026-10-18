# ADR-0004：采用 SQLite 与 SQLAlchemy 建立 Banking Core 底座

- 状态：Accepted
- 日期：2026-10-18
- 决策人：FinOrch 项目团队（待团队成员确认）

## 背景

Phase 1A 需要一个低依赖、可在开发机与 CI 重复运行的合成银行数据底座，同时支持清楚的事务、迁移和五条工作流共享边界。当前不需要生产级并发能力、真实用户认证或远程数据库。

## 决策

1. 初期采用 SQLite 文件数据库，SQLAlchemy 2.x 同步 Session 管理访问；Alembic 是唯一 DDL 迁移机制。应用启动不自动建表。
2. 使用单一 `build_engine`、`get_engine`、`get_session_factory` 和 API `get_db_session`，各模块不创建自己的连接池或 Session 方案。
3. API 请求依赖负责 Session 创建与关闭；只读 Application 用例不提交。写 Application 用例拥有完整事务，确保业务状态和审计事件同成同败。
4. Domain 规则与 ORM/API DTO 分离。API、Agent 和 Web 只能通过受控 Application/API 契约访问业务，不直接操作表。
5. 当前 Demo Identity 仅在 development/test 使用服务端配置的合成用户 ID。它不是认证系统，生产环境禁用；客户端不能指定 actor。
6. 合成 Seed 使用固定数据集版本和稳定 ID。Reset 必须显示 `--confirm`，仅接受仓库 development 数据库或测试临时文件白名单。

## 考虑过的备选方案

- PostgreSQL：提供更强并发能力，但当前本地/CI 演示规模不需要额外服务；出现经测量的 SQLite 限制后可另行 ADR。
- SQLAlchemy Async：当前 API 和 SQLite 工作负载无需额外异步 Session/事务复杂度；若将来出现明确 I/O 或数据库需求，再评估。
- 各业务模块自建 Session/SQL：短期方便但会导致事务、连接和数据访问行为分裂，拒绝。
- 登录用户通过客户端 ID 模拟身份：无法保护资源归属，拒绝。

## 影响与限制

- SQLite 只有有限的并发写能力；`busy_timeout` 不是高并发保证。生产部署、横向扩展和真实金融数据不在本 ADR 范围。
- 首批模型为 `demo_users`、`accounts`、`cards`、`audit_events`；后续场景只能在需求明确后增加表和迁移。
- 账户 `opening_balance_minor` 只是合成期初演示值，不是账本或可用余额；没有资金移动能力。
- 显式 Reset 会删除允许目标文件中的全部合成数据，包括审计历史；普通业务路径仅追加审计事件。
- Demo Identity 不具备生产级安全性；不得绑定公网或用于真实用户。

## 验证方式

Alembic migration 和临时 SQLite 集成测试验证 schema、外键、Seed 幂等、资源归属、状态变更、事务回滚和审计一致性。若后续换数据库、Session 模式或 actor 来源，需新增 ADR 并迁移调用契约。
