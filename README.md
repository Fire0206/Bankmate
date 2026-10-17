# FinOrch

**FinOrch** 是一个面向 2026 深圳国际金融科技大赛国内人工智能赛道的 AI Banking Agent 项目。目标是让用户用自然语言表达金融意图，由系统规划并执行模拟银行业务，同时提供可解释、可控、安全的操作体验。

> **项目状态：Phase 0 — Repository Foundation。** 当前只有工程基础、API 健康检查样例和占位首页。六大银行场景、Agent Runtime、工作流引擎、数据库业务模型和真实外部集成都尚未实现。

## 产品规划

六大场景均为 **Planned**：

1. 智能转账
2. 账单分析
3. 理财操作
4. 卡片管理
5. 订阅与代扣管理
6. 跨场景联动

官方公开赛题要求至少覆盖六类核心场景中的 3 类，并鼓励完整覆盖。该赛题要求与 FinOrch 的产品扩展规划分别维护，详见[需求说明](docs/requirements.md)和[赛事要求核对记录](docs/competition-requirements.md)。

## 技术架构

- **Web**：React、TypeScript、Vite、Tailwind CSS、pnpm。shadcn/ui 仅作为后续可选集成方案，当前未安装。
- **API**：Python、FastAPI、Pydantic、uv、pytest。当前只实现 `/api/v1/health`。
- **Agent**：未来采用模型无关的 OpenAI-compatible Provider 抽象和受控 Tool Calling；尚无 LLM 接入或 Agent 框架。
- **数据**：未来使用 SQLAlchemy、SQLite 和统一迁移管理；当前无业务数据库。
- **API 类型**：FastAPI/Pydantic 生成的 OpenAPI Schema 是单一事实来源；Web 类型通过 `openapi-typescript` 生成。

系统逻辑分层、数据流和边界见[架构说明](docs/architecture.md)。

数据库实体关系、金额精度、模拟数据和迁移约定见[数据契约](docs/data-contract.md)（当前全部为 Planned）。

## 仓库结构

```text
apps/
  api/                 FastAPI 服务、配置和 API 测试
  web/                 React/Vite 占位前端及生成的 API 类型
docs/
  decisions/           架构决策记录（ADR）
  development/         开发和发布前检查说明
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
```

终端一，启动 API：

```powershell
uv run --project apps/api python -m finorch_api
```

终端二，启动 Web：

```powershell
pnpm --filter @finorch/web dev
```

打开 Vite 显示的本地地址。前端通过 Vite 代理请求 `/api/v1/health`，并显示 API 连接状态。API 文档位于 `http://127.0.0.1:8000/docs`。

## 测试与检查

```powershell
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api ruff check --config apps/api/pyproject.toml apps/api
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm run format:check
```

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
