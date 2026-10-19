# 开发指南

## 工具链

- Node.js 24.x（最低要求 `>=22.12.0`），pnpm 11.x
- Python 3.13.x，uv
- Git

Windows、macOS 和 Linux 使用相同的 pnpm、uv 项目配置；以下命令不依赖 Bash 脚本。首次开发无需模型密钥、数据库服务或外部银行账户。

## 安装依赖

在仓库根目录运行：

```powershell
Copy-Item .env.example .env
pnpm install
uv sync --project apps/api
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api python -m finorch_api.seed
```

macOS/Linux 复制环境文件用 `cp .env.example .env`。

`.env` 是本地开发设置并被 Git 忽略；当前不放任何 API Key 或个人/金融数据。

`pnpm-workspace.yaml` 对 npm 包启用严格的 24 小时最低发布年龄策略，避免新发布版本被自动加入例外。若新依赖被该策略拦截，先等待发布年龄满足策略再安装；不要为方便而扩大例外范围。

## 启动

API：

```powershell
uv run --project apps/api python -m finorch_api
```

首次启动前需先运行迁移并 Seed（见上方命令）。API 不会在启动时自动创建业务表。默认 SQLite 文件为仓库 `.data/finorch.db`，由 `.gitignore` 排除。

Web（另开终端）：

```powershell
pnpm --filter @finorch/web dev
```

Vite 将 `/api` 代理到本地 API。默认 Fake Provider 可无密钥演示银行卡、账单、订阅、转账、AA 分账和理财。转账及申购/赎回会先生成服务端确认挑战，确认后才更新模拟账户余额、交易、持仓和审计；定时转账只由显式本地模拟工具执行。账单与投资产品数据是合成/确定性模拟数据。Swagger UI 位于 `http://127.0.0.1:8000/docs`，健康端点为 `http://127.0.0.1:8000/api/v1/health`。

## 验证命令

```powershell
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api ruff check --config apps/api/pyproject.toml apps/api
uv run --project apps/api ruff format --check --config apps/api/pyproject.toml apps/api
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm run format:check
```

更新 API 类型：`pnpm run api:types`。CI 安装依赖时使用 `pnpm install --frozen-lockfile` 和 `uv sync --project apps/api --locked`。

## 配置说明

环境变量示例见根目录 `.env.example`。API 使用 `FINORCH_` 前缀，默认监听 `127.0.0.1:8000`。`FINORCH_AGENT_PROVIDER=fake` 是默认确定性演示模式；DeepSeek 可通过本地忽略文件 `.env` 配置 `FINORCH_AGENT_PROVIDER=openai-compatible`、`FINORCH_LLM_BASE_URL=https://api.deepseek.com`、`FINORCH_LLM_API_KEY` 和 `FINORCH_LLM_MODEL=deepseek-flash`。密钥只在服务端使用，不得提交到仓库。Demo Identity 只在 development/test 启用，不是用户认证系统。

DeepSeek 真实模型测试可在迁移并 Seed 后启动 API，再通过 `apps/api/scripts/deepseek_eval.py` 执行脱敏场景集。该脚本只输出测试编号、工具选择、任务状态和安全错误码，不保存原始请求或模型响应。真实调用需消耗模型额度；自动化 CI 仍使用 Fake Provider 和 Mock HTTP。

Provider Mock 验证范围、可选真实模型 Smoke Test 方法、任务刷新恢复与幂等重试说明见[Agent 可靠性指南](development/agent-reliability.md)。

## 分支与私有仓库

本地开发和 CI 按私有仓库流程运行。当前 GitHub 仓库为 Private，但 `main` 尚未启用分支保护或 Ruleset；计划限制、当前状态和人工协作替代流程见[协作流程](collaboration.md)。管理员邀请正式团队成员并分配最小权限。不得将工作复制到未经批准的公共 fork 或公开 CI Artifact。正式提交前依照[仓库公开检查清单](development/public-release-checklist.md)执行。

## 团队 Codex Skill

仓库内提供 `skills/finorch-banking-agent/`，用于让团队成员的 Codex 按统一的产品原则、Agent 契约、六场景后端手册、安全评测和 Demo 规范工作。安装步骤见[skills/INSTALL.md](../skills/INSTALL.md)。安装后重启 Codex 或新建对话；不要在未回写仓库的情况下只改本机 Skill 副本。

## 常见问题

- 若 `pnpm` 未找到，安装/启用 pnpm 11 并重新打开终端。
- 若 Python 版本不符，安装 Python 3.13 后运行 `uv sync --project apps/api`。
- 前端显示 API 未连接时，先确认 API 在 `127.0.0.1:8000` 正在运行，并已运行 Alembic migration 和 seed，再刷新页面。
- OpenAPI 类型有变化时运行 `pnpm run api:types` 并提交两项生成物。
- Banking Core 的卡片、账单、订阅 Application、Session 和事务调用边界见[接口说明](development/banking-core.md)。
