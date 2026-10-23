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

在智能助手输入“我想做风险测评”可打开四题模拟问卷。用户本人选择答案并提交后，服务端更新当前演示用户风险等级并追加审计；“查询最新结果”可核对网络中断后的真实结果。重复 Seed 保留已测评等级，显式 Reset 清除测评并恢复初始画像。问卷不是生产适当性审核；后续申购仍由服务端重新检查产品匹配。

输入“我有哪些即将续费的提醒”可通过只读 Agent Tool 查看未来 30 天的合成订阅。展开自动扣费查询结果可设置每项提前 0–30 天的应用内提醒偏好；“检查到期提醒”按服务端当前时间生成本地提醒，同一扣款周期只生成一次。当前没有后台定时调度或短信/商户通知；需要本地演示到期生成时，可在临时测试数据库中调用 `generate_due_subscription_reminders(..., now=...)` 注入模拟时间，不能将客户端时间当作服务端执行依据。

Phase 3 本地模拟二次验证：单笔或当日累计转账超过 ¥1,000，以及 R4/R5 模拟产品申购，需要在普通确认外输入随机六位验证码。保持同一仓库根目录和同一个本地开发数据库，在**另一个本机终端**运行 `uv run --project apps/api python -m finorch_api.demo_verification --latest`；该终端显示的验证码只在本地使用，最多有效三分钟，不能复制进聊天、Issue 或日志。`--latest` 只选当前配置的演示用户最新待确认操作；并行演示多个任务时使用 `--confirmation-id <ID>` 指定挑战。错误尝试最多五次。没有本地终端就不能完成红色操作；此机制不是短信、人脸或生产级多因素认证。定时转账到期时再次按当日累计金额评估；若升为红色则失败并留下审计，必须重新发起授权，不会静默扣款。

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

### Phase 2F 工作流收尾与演示验证（2026-10-20）

本轮根据 Phase 2E 本地留出集的离线复核结果修复通用意图判断和续跑问题。Phase 2E 原报告记录 63/80；从原始执行状态用当前评分器重算为 65/80，其中允许相互独立的只读步骤换序，但写操作顺序和写操作所需读取仍受约束。原始报告、案例和预算文件没有修改；评分口径变化不是模型表现提升，旧报告也不是对当前分支的重新实测。

- 将卡片、订阅、转账、理财和 AA 分账的显式意图识别集中到共享模块，修复冻结/解冻反向、暂停/恢复/取消混淆、分账金额和参与人抽取及查询被误判成写入等问题。读操作的参数补充会结合任务原始请求解析。
- 当服务端任务状态要求下一工具时，OpenAI-compatible Provider 使用命名工具选择，避免模型在已确认步骤后直接结束；注册表过滤、工具参数验证、授权和确认仍由服务端执行。DeepSeek 的 Chat Completions 文档说明命名工具选择会强制调用指定函数，thinking 模式不支持该选择，因此适配器对此类请求显式关闭 thinking。[DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。
- 用 DeepSeek `deepseek-flash` 在隔离 SQLite 和随机本地端口运行 20 个单轮案例，51 次 Provider 请求、估算 ¥0.9605。初始自动评分为 17/20；复核发现风险不匹配用例错误地要求调用 `investment.buy`。产品工具返回不适当后，运行时以 `risk_mismatch` 结束且未提申购、未产生副作用，这是预期安全结果。按正确预期离线重算为 **18/20**：必需工具覆盖 18/19，工具路径 19/20，确认提案/执行 7/9；已执行操作的审计与业务状态对账各 8/8，未确认副作用 0，未授权写提案 0。该安全用例没有调用 `investment.buy`。
- 首轮跨场景失败为确认冻结银行卡后没有继续暂停订阅，返回 `agent_required_tool_not_called`。加上命名工具选择后，一次定向 DeepSeek 复测 **1/1** 完成；账单异常、订阅、冻结卡和暂停订阅都来自实际工具结果，两项写操作分别确认，审计与最终状态对账通过。
- AA 分账案例仍有一个模型参数未通过 Schema 校验，Task 安全停在 `awaiting_input`，没有产生分账或副作用。补充清晰字段名后的一次定向复测仍为 **0/1**；具体无效参数值未被保存，不能据此断定是哪一个字段。保留为待解决的真实模型限制，不继续消耗额度反复调样例。
- 20 例和两次定向复测合计 58 次 Provider 请求，348,045 输入 tokens、5,667 输出 tokens，估算费用 **¥1.1121**，低于本轮 ¥20 软上限与 ¥50 硬上限。原始提示词、模型文本和确认值不写入评测报告，也未提交任何 `.data/` 报告或用例。
- 使用 Fake Provider 和隔离演示数据库在浏览器完成两条跨场景主线：可疑扣款流程分别确认冻结尾号 1042 的卡、暂停腾讯视频会员；发薪日流程确认转账 ¥200 和申购 ¥9,300，最终日常账户余额 ¥3,000。直接核验了 SQLite 的账户、卡片、订阅、转账、订单、持仓和审计记录。刷新后切回智能助手，页面重新读取并显示服务端已完成的最近任务，没有重放写操作。
- 在 1440×900 和 390×844 视口检查页面；390px 下 `documentElement.scrollWidth` 与 viewport 同为 390px。浏览器截图保存在本地忽略目录 `output/playwright/`。

20 例结果是一次小样本、单轮执行；18/20 不能代表自然语言总体成功率或稳定性，也不是独立安全审查。Phase 2E 的 65/80 是旧执行数据的评分器离线重算，不应与这次 20 例混为一谈。CI 仍不调用真实模型。

### Phase 2E 失败驱动可靠性评测（2026-10-20）

本轮先离线复核 Phase 2D 已保存报告，再完成开发集调优，最后冻结新留出集；没有把旧 Holdout 报告称作独立验证集。旧报告以 v2 评分器重算，开发集可观察的必需工具覆盖为 **203/207**、工具路径为 **296/300**；旧 Holdout 为 **74/81**、**128/135**。旧报告缺少足以单独验证审计、注入文本是否送入模型及完整工具参数的数据，这些维度标为不可观察。旧报告原文件未改写，v2 评分副本留在本地忽略目录 `.data/phase2e-rescored/`。

修复后使用 `deepseek-flash` 在隔离临时 SQLite 上跑 32 个开发案例一轮：端到端 **32/32**，工具路径 **32/32**，必要写确认 **9/9**，确认执行、审计和业务状态对账各 **9/9**，未确认副作用 **0/10**。另对首轮发现的 4 个失败案例做定向复核，**4/4** 通过。开发集结果用于调优，不代表自然语言请求总体成功率。

实现提交 `60c647a4b6315e2beaa25081f51ffe6fd2fe262b` 冻结一组新的本地 Holdout（40 个案例、两轮、80 次试验）。端到端通过 **63/80（78.8%）**，必需工具覆盖 **68/72**，工具路径 **74/80**；无写决策 **32/32**，确认提案和执行各 **22/26**，已执行操作的审计及业务状态对账各 **22/22**，未确认副作用 **0/36**，未授权写提案 **0**。失败主要集中在目标措辞/订阅动作判断、分账参数校验、少数任务结束状态与预期工具路径不一致；完整工具名与状态统计保存在本地报告，不含原始提示词、模型回复或确认值。留出集结果显示未见表达仍有可靠性缺口，不能用开发集 32/32 替代。

Phase 2E 共 348 次模型请求，估算费用 **¥6.6326**；此前 Phase 2D 支出不计入本轮 ¥30 软上限与 ¥80 硬上限。留出报告和输入案例保存在被 Git 忽略的 `.data/` 中，未提交仓库；评测使用临时测试数据库和随机本地端口。报告仅保留案例编号、工具名、状态、结构化字段校验和计量数据，不包含提示词、模型回答、账户数据或密钥。评测结果不是独立人工安全审查，也不构成对未覆盖输入的保证；CI 不调用真实模型。

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

## 本地模拟人工处理

任务详情中的“申请模拟人工处理”会为当前用户的任务创建一张工单。`GET/POST /api/v1/agent/tasks/{task_id}/handoff` 只允许任务所属的 Demo actor 查询或提交；重复提交返回同一工单。工单仅保存原因、状态、简短处理结果和已成功工具名称，不保存完整模型对话，也不执行金融业务或绕过已有确认。

本地开发环境的模拟处理员可依次执行：

```powershell
uv run --project apps/api python apps/api/scripts/handoff_operator.py <ticket-uuid> in_progress
uv run --project apps/api python apps/api/scripts/handoff_operator.py <ticket-uuid> resolved --outcome "已核对模拟处理结果"
```

请先通过任务详情或 API 获取工单 ID。脚本仅允许 `FINORCH_ENVIRONMENT=development/test`，处理过程追加审计；它不代表已接入真实银行客服。

## 本地模拟借记卡申请

助手中输入“为我的日常账户申请一张模拟借记卡”，确认后可通过 `GET /api/v1/cards/applications` 查询提交状态。确认只提交申请，不立即发卡；未确认的提案不会列入申请列表。本地演示处理员可从申请列表取得 ID 后运行：

```powershell
uv run --project apps/api python apps/api/scripts/card_application_operator.py <application-uuid> approve
```

也可将 `approve` 换成 `reject`。脚本仅允许 development/test 环境、当前模拟用户的申请，批准时创建新的合成借记卡并追加审计。它不代表真实审核、发卡或授信。
