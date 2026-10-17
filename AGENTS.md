# FinOrch AI Coding 规则

本文件是 Codex 等 AI Coding Agent 在本仓库工作的统一规则；其他工具应引用本文件，避免复制成互相冲突的规则。

## 项目与目录

- FinOrch 目标是模拟银行场景的 AI Banking Agent。当前为 Phase 0：只有基础工程、健康检查和占位首页；不得把规划功能描述成已实现。
- 技术栈：`apps/web` 使用 React、TypeScript、Vite、Tailwind CSS、pnpm；`apps/api` 使用 Python、FastAPI、Pydantic、uv、pytest。SQLAlchemy/SQLite、LLM Provider、Agent Runtime 和业务层均为 Planned。
- `docs/` 是架构、产品、API、Agent、Workflow、安全、开发和协作契约入口；`docs/decisions/` 保存 ADR。
- 逻辑分层：Web UI；API 验证和响应；Application 流程；Domain 规则；Infrastructure 存储/外部适配；Agent 意图/规划/工具编排；Security 授权/确认/策略/审计。按需落地，不为逻辑分层制造空模块。

## 开始修改前

1. 阅读本文件、相关模块文档和适用 ADR；先查看当前 Git diff 和已有实现。
2. 复用现有模块，不重复实现相同能力。
3. 未经团队明确确认，不更改核心架构、核心契约、数据归属或仓库可见性；需要调整时先提交 ADR 和兼容方案。

## 编码与命名

- Python 使用 4 空格、类型注解、Ruff；前端使用 TypeScript strict、2 空格、ESLint/Prettier。
- API 路径小写、版本前缀 `/api/v1`、JSON 字段 `snake_case`。金额不用浮点数；传金额时使用货币代码和整数最小货币单位。
- SQLAlchemy 类用 PascalCase、表和列用 `snake_case`；迁移集中管理。实现前须更新数据契约。
- 面向用户的功能文案保持简洁；代码、API 标识和日志使用稳定英文标识符。

## 契约和单一事实来源

- API Schema 以 FastAPI/Pydantic 生成的 OpenAPI 为单一事实来源。变更模型或路由后运行 `pnpm run api:types`，提交 OpenAPI 与生成的 TypeScript 类型。
- Agent Tool、Workflow 和 Data 契约分别遵循 `docs/agent-contract.md`、`docs/data-contract.md`、`docs/security.md` 与 `docs/api-contract.md` 的约定。
- 跨模块接口变更必须先更新契约、版本兼容说明和相关文档，再改调用方与提供方。
- 不假设 Agent 可绕过后端工具直接修改业务状态；金额、权限、策略和确认都由服务端确定。

## 安全与数据

- 默认只使用明确标为合成/模拟的数据。不得提交真实账户数据、个人信息、API Key、令牌或 `.env`。
- Agent 只能通过受控业务工具触发变更。高风险操作必须服务端授权和确认；执行结果必须来自真实工具返回，不得由模型虚构。
- 不得以赶业务功能为由跳过授权、确认、幂等、审计或安全测试。
- 日志不得包含认证凭证、完整支付卡号、账户号、个人身份号码、完整提示词上下文或原始敏感业务载荷。

## 验证、Git 与文档

- 对变更运行相关 lint、类型检查、测试和构建；只报告实际运行的命令及结果，不伪造测试、接口或业务执行结果。
- 使用 `feat/*`、`fix/*`、`docs/*`、`refactor/*`、`chore/*` 分支和 Conventional Commits；通过 PR 合并到 `main`。普通 PR 至少一名其他成员 Review；资金、权限或安全契约变更还需安全 Review。
- 功能状态、命令、架构和 API 有变化时同步更新 README 或对应文档；重要设计决策写 ADR。
- 保持 PR 聚焦，避免多人无协调地同时编辑相同契约或入口文件。
