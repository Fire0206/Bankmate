# Agent Provider 与任务恢复

> 本文记录 Phase 1B.5 的 Provider 和任务恢复验证。当前 Phase 1C 复用同一 Runtime/Registry/Workflow，新增账单只读工具和订阅确认工具；真实模型服务仍未验证。

## Provider 验证范围

`OpenAICompatibleProvider` 使用 Chat Completions `POST /chat/completions`，发送 `model`、`messages`、注册工具定义和 `tool_choice: auto`。适配层解析 `choices[0].message.tool_calls`；运行时会校验工具调用 ID、注册表、JSON 参数 Schema，并按每个原始 `tool_call_id` 回送工具结果。多个调用结果可以在下一轮一起返回。Provider 错误、无效响应、重复工具调用和步数上限均不会被当成业务成功。

pytest 使用 Mock HTTP 响应覆盖请求结构、多工具多轮、无工具响应、重复/无效调用 ID、未知工具、参数 JSON/Schema 错误、HTTP 错误、超时和连接失败。这些检查没有访问真实模型供应商，也没有证明不同兼容服务的具体行为一致。

## 可选真实模型 Smoke Test

只有在本机已安全获得可用的 OpenAI-compatible Tool Calling endpoint 时，才执行真实请求。不要把 Key 发到聊天、Issue、终端截图或仓库；只将 Key 放在被 `.gitignore` 忽略的根目录 `.env` 中，或者通过当前终端的私有环境变量提供。仓库默认 Fake Provider 不需要 Key。

根目录 `.env` 使用以下变量：

```dotenv
FINORCH_AGENT_PROVIDER=openai-compatible
FINORCH_LLM_BASE_URL=https://provider.example/v1
FINORCH_LLM_API_KEY=<local secret>
FINORCH_LLM_MODEL=<tool-calling model name>
FINORCH_LLM_TIMEOUT_SECONDS=20
```

Base URL 填到兼容 API 的版本根路径，适配器会追加 `/chat/completions`。准备并启动 API/Web 的命令见[开发指南](../development.md)。真实 Smoke Test 只用 seed 合成数据，按顺序验证：

1. 请求“查看我的银行卡”，确认任务结果来自 `card.list`。
2. 请求查询一个 seed 卡片的尾号状态，确认由 `card.get` 返回。
3. 请求冻结尾号 `1042` 的卡，确认 Task 进入 `awaiting_confirmation` 且卡片仍为 active。
4. 在 UI 核对卡片、目标状态、影响和有效期，手动确认；之后重新读取卡片并核对审计记录。

任何模型文本都不能直接改变卡片。真实测试报告只记供应商/model 名称、场景和成功/失败状态，不记录 Key、原始提示或敏感上下文。当前开发环境没有发现模型 Key 配置，因此本轮没有执行真实网络或付费模型 Smoke Test。

## 任务恢复与重试

- 页面刷新后用 `GET /api/v1/agent/tasks/recent` 优先恢复当前会话最近的活动服务端 Task；没有活动任务时恢复最近的终态任务，包括失败和已完成状态。不会重建缺失的完整对话历史。
- 待确认 Challenge 过期后，第一次读取任务由服务端在事务内结算 Task、Step、ToolExecution 和审计为 expired/failed，不修改卡片。此惰性处理不依赖浏览器时钟；若没有读取或确认请求，任务会保持等待状态，但过期挑战仍不能执行。
- 写响应状态未知时，先按服务端 actor、conversation、operation、task 和幂等键查询。查询后可单独刷新 Task；明确执行安全重试时沿用原参数与同一幂等键。若结果仍不确定，不生成新键或新任务。
- `sessionStorage` 只作当前标签页会话关联和同键恢复缓存，不是授权依据。服务端 Demo Actor 始终来自配置；缓存里的 task ID、conversation ID 或请求数据不能赋予访问权限。

## Phase 1B 确认路径自查记录

本记录来自代码审阅和自动化测试，只是作者自查，不是独立人工安全 Review。

- 已复核：确认时在 SQLite `BEGIN IMMEDIATE` 事务中重新校验 actor/资源归属、challenge 状态和有效期、参数摘要、卡片版本、工具/策略版本和幂等键；challenge 消费、卡片变更、Task/Step/ToolExecution 和审计同事务提交。测试覆盖重复/并发确认、过期、版本冲突、写入回滚和卡片/审计一致性。
- 修复：恢复前缺少 actor+conversation 最近任务读取，刷新会丢失活动 Task；新增服务端恢复查询。
- 修复：过期 challenge 读取时仍可能显示为待确认；现在服务端惰性落库为失败并审计，卡片不变。
- 修复：幂等结果查询若只按 key 搜索，可能混淆同一会话中不同操作范围；现在要求 operation，并对输入/确认/取消额外校验 task ID。
- 待 Review：以上权限、确认、幂等、过期处理和事务改动仍需另一名团队成员独立安全审查；测试通过不等同于该审查完成。

## 复核命令

```powershell
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api ruff check --config apps/api/pyproject.toml apps/api
uv run --project apps/api ruff format --check --config apps/api/pyproject.toml apps/api
pnpm run api:types
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm run format:check
```
