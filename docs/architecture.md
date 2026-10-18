# 系统架构

## 当前实现与计划边界

已实现：私有优先的 Monorepo、React/Vite/Tailwind 占位首页、FastAPI `/api/v1/health` 与只读卡片 API、OpenAPI 导出和生成的 TypeScript 类型、SQLAlchemy/SQLite/Alembic、DemoUser/Account/Card/AuditEvent、合成 seed/reset、卡片状态 Domain 规则及 Application 用例。

**Planned**：完整六大业务场景和前端、Agent/工具运行时、Workflow 调度、服务端确认挑战、真实认证、资金账本/转账、事件推送和生产部署。卡片冻结/解冻目前仅作为确定性 Application 用例存在，不提供写 API 或 Web 操作入口。数据库与调用边界见[数据契约](data-contract.md)和[Banking Core 接口说明](development/banking-core.md)。

## 逻辑层职责

| 层             | 职责                                     | 约束                                                |
| -------------- | ---------------------------------------- | --------------------------------------------------- |
| Web            | UI、交互、任务状态展示                   | 不决定余额、授权或业务结果；API 类型从 OpenAPI 生成 |
| API            | HTTP、输入验证、版本、权限入口、错误映射 | 不承载复杂业务流程；调用 Application 层             |
| Application    | 用例编排和事务边界                       | 组合领域规则与端口，不承载 Web 细节                 |
| Domain         | 银行业务规则与不变量                     | 确定性计算；不依赖 LLM 或具体数据库                 |
| Infrastructure | 数据存储、迁移、模型适配和外部系统适配   | 仅通过显式端口接入业务流程                          |
| Agent          | 意图理解、任务规划、受控工具选择/编排    | 不直接改业务存储；模型输出是非可信输入              |
| Security       | 身份/权限、风险策略、服务端确认、审计    | 关键校验不能由 Agent 或前端绕过                     |

这些是边界约定，不要求每层现在都有独立包或抽象基类。当前按需采用模块化单体。

## 计划数据流

```text
Web UI -> API v1 -> Application -> Domain -> Infrastructure
                     ^                  |
                     |                  v
                Security <- Agent -> Controlled Tools
                     |                  |
                     +---- Audit <------+
```

Agent 计划经 API/Application 校验后才能进入受控工具。对资金、权限和风险的确定性判断属于服务端。具体时序和确认生命周期见 [Agent、Tool 与 Workflow 契约](agent-contract.md)及[安全设计](security.md)。

## 仓库边界

- `apps/web/`：独立 Web 应用；前端不维护手工副本 API 类型。
- `apps/api/`：FastAPI 服务、配置、生成 OpenAPI 的脚本和后端测试。
- `apps/api/alembic/`：唯一数据库迁移历史；业务表不得在应用启动时自动创建。
- `apps/api/src/finorch_api/application/`：确定性用例和事务边界；Phase 1A 包含卡片状态变更用例。
- `apps/api/src/finorch_api/domain/`：框架无关的卡片状态规则。
- `apps/api/src/finorch_api/infrastructure/`：共享 SQLAlchemy Base、engine/session、ORM 模型和持久化查询。
- `apps/api/src/finorch_api/security/`：development/test 专用 DemoActor 上下文。
- `docs/`：跨模块产品、架构、安全、协作和比赛事实；契约变更同 PR 更新。
- `.github/`：面向私有仓库的 PR、Issue 和 CI 配置。
- `tests/`：当前测试与 API 同域，故保留在 `apps/api/tests`；跨模块集成需要真实出现时再增加顶层测试。

## 依赖决策

- React + TypeScript + Vite：建立轻量 SPA 开发和构建链路。
- Tailwind CSS：项目要求的基础样式工具；当前仅用于占位 UI。
- FastAPI + Pydantic：HTTP 路由和可生成 OpenAPI 的数据模型。
- uv + pytest + Ruff：Python 依赖锁定、测试和静态检查。
- shadcn/ui：后续可选的组件集成方法，未安装、未建立组件复制流程。
- SQLAlchemy 2.x、SQLite、Alembic：Phase 1A 已引入；一个共享 Session provider，读请求依赖负责创建/关闭 Session，Application 写用例负责 begin/commit/rollback；迁移由 Alembic 管理，不在启动时自动建表。
- LangGraph、MCP：当前不预先引入；如后续需要，先比较状态持久化、恢复、可观测性、工具边界与复杂度并记录 ADR。
- 不引入 Redis、Kafka、Kubernetes 或真实银行/支付 API。

## 运行时关系

Web 开发服务器将 `/api` 请求代理到本地 FastAPI。前端首页查询 `/api/v1/health`，API 返回服务名称、状态和版本；健康检查不代表业务依赖或 Agent 可用。
