# FinOrch

**FinOrch** 是一个面向 2026 深圳国际金融科技大赛国内人工智能赛道的 AI Banking Agent 项目。目标是让用户用自然语言表达金融意图，由系统规划并执行模拟银行业务，同时提供可解释、可控、安全的操作体验。

> **项目状态：Phase 1B — Card Agent Vertical Slice。** 已交付本地可运行的单 Agent 卡片闭环：自然语言请求、Fake Provider、受控卡片工具、持久化任务、服务端确认、SQLite 卡片状态变更和通用审计，以及 React 操作界面。冻结/解冻必须确认。OpenAI-compatible Provider 已有可配置适配器和 Mock HTTP 测试，但未在真实模型服务上验证。其余五大场景、生产认证和真实金融服务均未实现。

## 产品规划

六大场景是 FinOrch 的产品规划，不代表都已有可演示的业务闭环：

1. 智能转账
2. 账单分析
3. 理财操作
4. 卡片管理（已实现模拟卡片查询、确认后冻结/解冻、任务进度和审计展示；真实认证、生产安全和其他扩展仍为 Planned）
5. 订阅与代扣管理
6. 跨场景联动

官方赛题强制场景、最低覆盖范围和提交要求仍需按本届官方工作台核实；六大场景目前仅作为 FinOrch 产品规划。详见[需求说明](docs/requirements.md)和[赛事要求核对记录](docs/competition-requirements.md)。

比赛演示与答辩设计资料（Planned，不代表已实现）：[docs/competition/README.md](docs/competition/README.md)。

## 技术架构

- **Web**：React、TypeScript、Vite、Tailwind CSS、pnpm。shadcn/ui 仅作为后续可选集成方案，当前未安装。
- **API**：Python、FastAPI、Pydantic、uv、pytest；包括健康检查、卡片查询、Demo Session，以及 Agent Task、输入补充、确认、取消和审计摘要 API。没有可绕过确认的卡片写入口。
- **Agent**：有界单 Agent Runtime、Typed Tool Registry 和模型无关 Provider 接口。默认 Fake Provider 仅做确定性的本地演示，不是 LLM 推理；可选 OpenAI-compatible Chat Completions Adapter 需要自行配置服务端密钥。
- **数据**：SQLAlchemy 2.x、SQLite、Alembic；包括 DemoUser、Account、Card、AgentTask、TaskStep、ToolExecution、ConfirmationChallenge 和追加式 AuditEvent。业务余额仍是 seed 中的模拟初始值，没有账本或资金变更功能。
- **API 类型**：FastAPI/Pydantic 生成的 OpenAPI Schema 是单一事实来源；Web 类型通过 `openapi-typescript` 生成。

系统逻辑分层、数据流和边界见[架构说明](docs/architecture.md)。

数据库实体关系、金额精度、模拟数据和迁移约定见[数据契约](docs/data-contract.md)。

## 仓库结构

```text
apps/
  api/                 FastAPI 服务、配置、API 测试和 Alembic 迁移
  web/                 React/Vite 占位前端及生成的 API 类型
docs/
  decisions/           架构决策记录（ADR）
  development/         开发和发布前检查说明
  research/            Phase 0.5 开源源码研究
.github/
  ISSUE_TEMPLATE/      Bug 与功能请求表单
  workflows/           GitHub Actions CI
```

各层职责和当前实现边界见[架构说明](docs/architecture.md)。

## 环境要求

- Node.js 24.x 和 pnpm 11.x
- Python 3.13.x 和 uv
- Git

详细的 Windows、macOS、Linux 安装与启动命令见[开发指南](docs/development.md)。

## 本地启动

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
pnpm install
uv sync --project apps/api
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api python -m finorch_api.seed
```

终端一，启动 API：

```powershell
uv run --project apps/api python -m finorch_api
```

终端二，启动 Web：

```powershell
pnpm --filter @finorch/web dev
```

打开 Vite 显示的本地地址即可在 Fake Provider 模式操作合成卡片。自然语言冻结/解冻先生成服务端确认卡片，确认后前端重新读取卡片状态。API 文档位于 `http://127.0.0.1:8000/docs`。

可选真实模型模式需要在本地 `.env` 配置 `FINORCH_AGENT_PROVIDER=openai-compatible`、`FINORCH_LLM_BASE_URL`、`FINORCH_LLM_API_KEY` 和 `FINORCH_LLM_MODEL`。该模式只支持 OpenAI-compatible Tool Calling Adapter；当前没有做真实供应商连通性或付费模型验证。不要将模型密钥提交到仓库。

## 测试与检查

```powershell
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api ruff check --config apps/api/pyproject.toml apps/api
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm run format:check
```

本地合成数据库重置（development 仅允许仓库 `.data/finorch.db`；test 仅允许临时 `finorch-test*.sqlite3`；必须显式确认）：

```powershell
uv run --project apps/api python -m finorch_api.reset --confirm
```

本地 Demo actor 由服务端 `.env` 的 `FINORCH_DEMO_USER_ID` 选择，默认是 Demo User One；也可改为 `.env.example` 中的第二个固定合成用户 ID。重启 API 后生效。该身份机制只用于 development/test，不具备生产级认证能力，API 不接受客户端传入的 `user_id` 或角色。

更新 FastAPI OpenAPI 快照及前端类型：

```powershell
pnpm run api:types
```

API Schema 或接口实现变更后，应重新生成并提交 `apps/web/openapi.json` 和 `apps/web/src/generated/api.d.ts`。不要手工编辑生成文件。

## 协作与开源

仓库遵循 **Private-first, Open-source-on-submission**：开发期间保持 GitHub 仓库私有，面向成员邀请、PR Review、CI 和分支保护设计。Phase 0 准备 Apache-2.0 文件不等于授权立即公开。比赛提交前由仓库管理员根据权属、官方规则、依赖许可证和安全审查结果手动决定是否公开；Codex 不修改仓库可见性。

分支、评审和 AI Coding 规则见[协作指南](docs/collaboration.md)、[CONTRIBUTING.md](CONTRIBUTING.md)和[AGENTS.md](AGENTS.md)。

许可证文件为 Apache License 2.0。版权主体及团队成员授权需在公开前由团队确认；第三方代码和 NOTICE 义务须逐项审查，见[许可与贡献权属说明](docs/development/licensing.md)和[开源与公开检查清单](docs/development/public-release-checklist.md)。

## 官方赛事链接

- [2026 深圳国际金融科技大赛官网](https://fintechathon.g-ican.com/)
- [人工智能赛道报名工作台](https://apply.g-ican.com/)

赛事要求及未确认事项按官方公开内容记录在[赛事核对文档](docs/competition-requirements.md)，核对日期为 2026-10-17。
