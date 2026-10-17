# ADR-0001：采用 TypeScript Web 与 Python API 的模块化 Monorepo

- 状态：Accepted
- 日期：2026-10-17
- 决策人：FinOrch 项目团队（待团队成员确认）

## 背景

FinOrch 需要让前端、后端、Agent 和安全工作可并行推进，同时在 Phase 0 控制依赖和抽象规模。

## 决策

将 React/TypeScript Web 与 FastAPI/Python API 放在一个 Monorepo 的独立应用目录中。API 作为模块化单体起步，逻辑上区分 API、Application、Domain、Infrastructure、Agent 和 Security 职责；只有出现真实实现需要时才新增模块。初期数据目标为模拟数据和 SQLite；SQLAlchemy 尚不引入。shadcn/ui 留作后续选项；LangGraph、MCP、Redis、Kafka、Kubernetes 均不预先引入。

## 备选方案

- 分离仓库：本阶段增加跨仓库版本协调成本，故暂不选。
- 预先搭建 Agent 或微服务框架：目前没有已验证的需求，故暂不选。

## 影响

前后端可在单个私有仓库内协同并共享 API Schema 生成流程。需要在 CI 分别检查 Python 与 TypeScript 工具链。后续若应用边界或团队权限需求变化，应通过新 ADR 重新评估。
