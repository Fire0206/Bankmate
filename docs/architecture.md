# 系统架构

## 当前实现与计划边界

已实现：私有优先的 Monorepo、React/Vite/Tailwind Agent 工作界面、FastAPI 健康/卡片/交易/账单/订阅/Agent Task API、OpenAPI 导出和生成的 TypeScript 类型、SQLAlchemy/SQLite/Alembic、DemoUser/Account/Card/Transaction/Subscription 与持久化 Workflow 表、合成 seed/reset、卡片和订阅状态规则、受控 Tool Registry、Fake Provider、OpenAI-compatible Provider Adapter、服务端确认和通用追加式审计。

**Planned**：智能转账、理财、跨场景联动、真实用户认证、账本/资金变更、SSE/WebSocket 事件推送和生产部署。当前 Agent 覆盖本地模拟卡片查询及确认后冻结/解冻、基于合成交易的账单分析，以及基于周期流水识别的订阅读取和确认后暂停/恢复/取消。异常提示是确定性金额规则，不是欺诈检测；Fake Provider 是确定性演示逻辑，不代表模型推理。OpenAI-compatible Adapter 通过 Mock HTTP 验证，未对真实模型服务做连通性测试。Demo Identity 不具备生产级安全性。数据库与调用边界见[数据契约](data-contract.md)和[Banking Core 接口说明](development/banking-core.md)。

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
- `apps/api/src/finorch_api/application/`：确定性用例、事务边界和持久化任务编排；卡片变更仅由确认流程调用。
- `apps/api/src/finorch_api/agent/`：单 Agent Loop、Typed Tool Registry、Fake Provider 和 OpenAI-compatible Provider Adapter；Provider 不获得数据库写权限。
- `apps/api/src/finorch_api/domain/`：框架无关的卡片/订阅状态规则和账单提示规则。
- `apps/api/src/finorch_api/infrastructure/`：共享 SQLAlchemy Base、engine/session、ORM 模型和持久化查询。
- `apps/api/src/finorch_api/security/`：development/test 专用 DemoActor 上下文。
- `docs/`：跨模块产品、架构、安全、协作和比赛事实；契约变更同 PR 更新。
- `.github/`：面向私有仓库的 PR、Issue 和 CI 配置。
- `tests/`：当前测试与 API 同域，故保留在 `apps/api/tests`；跨模块集成需要真实出现时再增加顶层测试。

## 依赖决策

- React + TypeScript + Vite：建立轻量 SPA 开发和构建链路。
- Tailwind CSS：用于当前 Agent 工作界面。
- FastAPI + Pydantic：HTTP 路由和可生成 OpenAPI 的数据模型。
- uv + pytest + Ruff：Python 依赖锁定、测试和静态检查。
- shadcn/ui：后续可选的组件集成方法，未安装、未建立组件复制流程。
- SQLAlchemy 2.x、SQLite、Alembic：Phase 1A–1C 使用；一个共享 Session provider，API 依赖创建并关闭 Session；Application `write_transaction` 拥有或加入明确写事务。读取自动事务不会造成不兼容嵌套，待处理写入要求先处于显式写事务；迁移由 Alembic 管理，不在启动时自动建表。
- LangGraph、MCP：当前不预先引入；如后续需要，先比较状态持久化、恢复、可观测性、工具边界与复杂度并记录 ADR。
- 不引入 Redis、Kafka、Kubernetes 或真实银行/支付 API。

## 运行时关系

Web 开发服务器将 `/api` 请求代理到本地 FastAPI。前端通过 `/api/v1/cards`、`/api/v1/transactions`、`/api/v1/bills/summary`、`/api/v1/subscriptions` 和 Agent Task API 查询并完成当前三类场景；卡片和订阅写入均经 Agent 服务端确认流程。健康检查只返回 API 进程状态，不代表数据库或 Agent 可用。
