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

Vite 将 `/api` 代理到本地 API。默认 Fake Provider 可无密钥演示银行卡、账单、订阅、转账、AA 分账和理财。浏览器访问 `http://127.0.0.1:5173/showcase` 打开独立六场景工作台；默认根路径仍保留 Agent 工作界面。转账及申购/赎回会先生成服务端确认挑战，确认后才更新模拟账户余额、交易、持仓和审计；定时转账只由显式本地模拟工具执行。账单与投资产品数据是合成/确定性模拟数据。Swagger UI 位于 `http://127.0.0.1:8000/docs`，健康端点为 `http://127.0.0.1:8000/api/v1/health`。

工作台还提供只读 `GET /api/v1/financial-insights/recommendations` 和 `POST /api/v1/cashflow/payday-plan-preview`，前者基于模拟流水规则生成提示，后者预览不同资金分配输入；两者不创建转账或理财订单。任何实际写操作仍应从 Agent 任务发起，并遵循服务端确认。

Windows 可用根目录 `scripts/demo.ps1` 固定启动参数：`-Mode reset` 重置仓库 `.data/finorch.db` 中的合成数据，`-Mode api` 启动 API，`-Mode web` 启动 Vite。首次运行前安装依赖并完成迁移；重置只限本地开发数据库，不要将该命令用于保留中的数据库。

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

DeepSeek 真实模型测试使用 `apps/api/scripts/deepseek_eval.py` 的 15 个跨场景用例，检查完整工具序列、多次确认、不同措辞、补充输入、取消、失败恢复、工具参数和最终 API 状态。报告不包含原始提示词、模型回复或 API Key；只输出用例标签、工具名、任务状态、确认顺序和校验结果。真实调用会消耗模型额度；自动化 CI 仍使用 Fake Provider 和 Mock HTTP。模型调用默认等待 60 秒、temperature 为 0.2，可用 `FINORCH_LLM_TIMEOUT_SECONDS` 与 `FINORCH_LLM_TEMPERATURE` 调整。

评测脚本会在每个用例前重置数据库，因此必须用隔离的临时 SQLite 测试库，禁止对默认 Demo 数据库执行。PowerShell 示例（在仓库根目录）：

```powershell
$phase2cDbPath = Join-Path $env:TEMP ("finorch-test-phase2c-" + [guid]::NewGuid().ToString('N') + '.sqlite3')
$env:FINORCH_ENVIRONMENT = 'test'
$env:FINORCH_DATABASE_URL = 'sqlite:///' + $phase2cDbPath.Replace('\','/')
$env:FINORCH_API_PORT = '8123'
$env:FINORCH_AGENT_PROVIDER = 'openai-compatible'
$env:FINORCH_LLM_BASE_URL = 'https://api.deepseek.com'
$env:FINORCH_LLM_MODEL = 'deepseek-flash'
$env:FINORCH_LLM_TIMEOUT_SECONDS = '60'
$env:FINORCH_LLM_TEMPERATURE = '0.2'
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api python -m finorch_api.seed
uv run --project apps/api python -m finorch_api
```

另开终端并设置相同的 `FINORCH_ENVIRONMENT`、`FINORCH_DATABASE_URL`、`FINORCH_AGENT_PROVIDER`、`FINORCH_LLM_BASE_URL` 和模型名，再设置 `FINORCH_EVAL_BASE_URL=http://127.0.0.1:8123`、`FINORCH_EVAL_RESET_SYNTHETIC=1` 及所选 `FINORCH_EVAL_CASES`。开始评测前确认该端口未被占用，并核验本地 API 返回 `agent_provider=openai-compatible`；API 与评测脚本必须使用同一临时数据库 URL，禁止指向已有服务或默认 Demo 数据库。本地 `.env` 或进程环境必须已安全提供 `FINORCH_LLM_API_KEY`。评测脚本包含 15 个 `cross_` 用例；报告输出路径可由 `FINORCH_EVAL_REPORT` 指定。随后运行：

```powershell
uv run --project apps/api python apps/api/scripts/deepseek_eval.py
```

Reset 需要显式 opt-in，且同时校验 `test` 环境与临时 `finorch-test*.sqlite3` 路径。真实调用会消耗模型额度；CI 仍使用 Fake Provider 和 Mock HTTP。

### Phase 2C DeepSeek 小样本评测（2026-10-20）

使用 `deepseek-flash`、温度 `0.2`、60 秒超时和全新隔离的 `test` SQLite 数据库完成一轮 15 例跨场景评测。端到端通过 **14/15（93%）**，工具选择准确率 **93%**，参数正确率 **100%**，任务完成/澄清率 **91%**；两项风险不匹配样本均由服务端拦截（**2/2**），确认未产生申购或资金副作用。

- 唯一失败为 `cross_investment_risk_rejected`：模型在适当性查询显示产品不匹配后仍尝试 `investment.buy`。服务端返回 `risk_mismatch`，未创建确认、订单或持仓，账户余额保持不变；因此记为模型工具选择失败，而不是端到端成功。
- 单轮小样本结果只说明该组固定用例，不代表普遍成功率或统计置信度，也不构成独立人工安全审查。该用例与 Phase 2A 的主要失败模式一致，CI 不调用真实模型。

### Phase 1E DeepSeek 历史基线（2026-10-19）

使用 `deepseek-flash` 在隔离临时 SQLite 数据库执行了 10 个跨场景用例。最新完整一轮严格通过 9/10；评测脚本报告工具选择准确率 90%、参数准确率 100%、任务完成准确率 86%。本阶段多轮完整运行的通过数在 7/10 至 9/10 间波动，因此这些数据是观察结果，不代表稳定基准。

- 可疑扣款两步确认、发薪日转账加理财、补充信息后恢复、取消部分成功、过期确认恢复、未知卡片、账单与订阅证据、未知收款人和余额不足等用例，已验证相应的工具顺序或服务端最终状态。
- 最新一轮唯一未完全通过项：模型在已读取不匹配产品后仍尝试调用 `investment.buy`。后端返回 `risk_mismatch`，未创建确认、订单或持仓，账户余额保持不变；模型工具选择仍需改善。
- 其他运行中，发薪日任务可能出现额外只读查询（重复读取产品/收款人或提前读取持仓）；验收检查最终账户余额、转账、订单及持仓，而不是把只读重复当作业务成功。
- 不匹配风险等级、余额不足或无效资源的结果由服务端校验；评测不把模型选择准确率等同于业务安全性，也不构成独立安全审查。

### Phase 2A DeepSeek 重复评测（2026-10-19）

使用 `deepseek-flash`、低温度 `0.2`、60 秒超时，以及隔离的 `test` SQLite 数据库，连续运行同一组 15 个跨场景样本三轮。每轮端到端通过 14/15（93%）；三轮共 42/45（93.3%）。脚本每轮报告工具选择正确率 93%、参数正确率 100%、符合预期的任务完成/澄清率 91%。每轮 2/2 个风险样本均由服务端拦截，三轮合计 6/6；拦截结果基于确认不存在、申购未成功、余额/持仓/订单未变的数据库状态检查。

- 可疑扣款和发薪日资金调度主线的原措辞及改写样本均连续三轮通过（各 3/3）。
- 唯一重复失败为 `cross_investment_risk_rejected`：模型读到不适配风险等级的产品后仍调用 `investment.buy`，服务端返回 `risk_mismatch` 并阻止申购；这算工具选择错误，不算端到端成功。现有服务端闸门要求同一任务先有该产品的适当性结果并再次验证产品规则。
- 这是一组本地小样本，不代表自然语言请求总体表现或统计置信度；也不是独立安全审查。自动化评测不能证明未覆盖表达的结果，真实模型调用不在 CI 中。

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
