# 开源项目源码审查

**检查日期：2026-10-18**

**审查方式：**固定 Git commit，读取 README、源码、测试和根目录许可证；未安装、未运行或复制被调研项目。

## 结论概览

| 项目                | 源码中可验证的实现                                                             | 主要限制                                                                                                         | 根许可证审查                                                                            |
| ------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| BankPilot           | ADK Agent、交易 MCP 服务、转账/余额检查/OTP 路径、BigQuery 账务操作和单测      | GCP 耦合；账务写入多次 BigQuery 调用；金额使用 float；幂等缓存为进程内字典；部分身份上下文代码不适合作安全范例   | 未发现根 LICENSE。个别文件有 Google Apache-2.0 头，不能据此推断整个仓库均获 Apache 授权 |
| SBI Dost            | React 多标签 UI、可视化执行轨迹、浏览器内存模拟状态和固定演示步骤              | 不是真实 ReAct/RAG；关键操作金额固定；审批由特殊文本触发；无服务端、持久化或测试                                 | 未发现根 LICENSE；README 声称 MIT 但仅有徽章/文字，未发现许可证全文                     |
| agentBANK           | Fastify API、Prisma/PostgreSQL 模型、支付服务、事务内余额/交易记录、请求审计   | auth 是 demo token 白名单 stub；金额 API schema 使用 Number；幂等查重先于事务；真实数据库集成测试依赖 PostgreSQL | 未发现根 LICENSE；README MIT 徽章不等于许可证授权                                       |
| Airwallex           | 18 个模拟 kit、请求 ID、结果查询、重复请求测试、纯函数审批/账本模型            | 模拟账务状态在进程内；关键金额路径使用 JS number；审批 gate 在无 TTY 时默认自动批准                              | 根 LICENSE 明确 MIT                                                                     |
| Kaching Copilot     | 确定性动作白名单、角色/risk/PIN 策略、服务端提案过期、并发锁、速率限制和审计   | Laravel/SME 领域与 FinOrch 不同；提案在 Cache 暂存；“exactly once”不可直接视为数据库级恰好一次                   | 自定义评审/研究许可，明确保留复制、修改、发布、分发等权利                               |
| Aegis Banking Agent | PII 正则脱敏、scope 检查、规则式协调器、HTTP mock 工具和对应单测               | 身份凭证与数据均为 mock；意图匹配是关键词规则而非通用 LLM planner；业务数据内存/静态                             | 未发现根 LICENSE                                                                        |
| Banko AI Assistant  | 真实 LangGraph 收据处理图、持久化 CockroachDBSaver、多 Provider 抽象及丰富测试 | 数据库和依赖栈明显超出 FinOrch 当前规模；Coach 子系统有手写规划循环，不能把所有模块都概括为 LangGraph            | 根 LICENSE 明确 MIT                                                                     |
| RBC Banking Chatbot | Python/SQLite 数据访问、SQL 事务中的同户转账示例、MCP 工具和 Gemini RAG        | 转账流程未验证金额为正、余额非负、更新行数或幂等；明文密码仅 demo；RAG Prompt 不是安全控制；未发现测试           | 根 LICENSE 明确 MIT                                                                     |

## 1. BankPilot

**仓库：** https://github.com/souravmighty/banking-agent

**检查 commit：** 6508bb7afbccbfcac80dc73665f41c8fc63ed0ba

**根许可证：** 根目录未发现 LICENSE/LICENCE/COPYING 文件；[README](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/README.md) 也未列出可直接用于 FinOrch 的通用仓库许可。ADK FastAPI 文件含 Google Apache-2.0 文件头，但这只覆盖该文件自身的声明，不能推断整仓许可。

### 实际实现

- [Agent 定义](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/app/agent.py#L29-L48) 使用 Google ADK 的 LlmAgent、BigQuery 子 Agent 和 MCP 工具；其根 Agent 中 sub_agents 配置仍被注释，AgentTool 通过工具函数单独调用。
- [工具适配](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/app/tools.py#L20-L33) 将 BigQuery 查询封装为 AgentTool；[交易 MCP Client](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/app/tools.py#L132-L179) 通过远程 HTTP MCP 工具集接入交易服务，并动态附带服务端/用户凭据。
- [MCP 转账工具](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/mcp-server/app/tools.py#L22-L152) 检查金额大于零、解析认证上下文、收款人和来源账户、可用余额，并按阈值创建 OTP challenge 或执行转账。
- [账本服务](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/mcp-server/app/ledger_service.py#L18-L64) 的幂等结果存在 Python Dict 和线程锁内；转账使用 float，并对 BigQuery 发出多次独立读取/更新/插入调用。[服务测试](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/mcp-server/tests/test_ledger_service.py#L43-L83) 使用 MagicMock 验证调用和结果，没有证明这些外部写操作处于一个原子数据库事务。
- [OTP 服务](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/mcp-server/app/otp_service.py#L1-L15) 使用 Python 进程内状态管理挑战。
- [FastAPI 集成测试](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/tests/integration/test_agent.py#L23-L57) 只断言对 “Why is the sky blue?” 有流式文本，不覆盖银行写操作或安全结果。
- [身份上下文代码](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/app/agent.py#L85-L118) 含全局 token 回退；[另一路径](https://github.com/souravmighty/banking-agent/blob/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba/ai-banking-assistant/app/agent.py#L551-L561) 使用 verify_signature=False 解码 JWT 读取用户上下文。该解码不能作为身份验证/授权依据。

### 可借鉴与不采用

可以借鉴把银行操作独立成 typed tools/MCP service、给工具单独编写业务测试的边界思路。其 Google ADK、Vertex AI、BigQuery、Firebase、GCP IAM 组合不符合 FinOrch 现有 OpenAI-compatible Provider 与 SQLite 规划；进程内幂等不能满足重启恢复。源码只作设计研究，未获清晰整仓许可，不复制。

## 2. SBI Dost

**仓库：** https://github.com/JatinGargz/sbi-dost

**检查 commit：** 61331ab73a3f2ff3c21961a9c4554523495757f4

**根许可证：** 根目录未发现 LICENSE 文件。README 的 MIT badge/文字不能替代许可证全文。

### 实际实现

- README 声称自主 ReAct、RAG、OTP 和后端模拟银行；[源码结构声明](https://github.com/JatinGargz/sbi-dost/blob/61331ab73a3f2ff3c21961a9c4554523495757f4/README.md#L12-L24) 应与代码区分看待。
- [mockAgent.js](https://github.com/JatinGargz/sbi-dost/blob/61331ab73a3f2ff3c21961a9c4554523495757f4/src/mockAgent.js#L1-L90) 在模块级 JS 对象中维护余额、订阅、预算和交易；所谓 policy search 是基于关键词返回固定字符串；取消订阅和转账直接改内存数组/数值。
- [执行轨迹](https://github.com/JatinGargz/sbi-dost/blob/61331ab73a3f2ff3c21961a9c4554523495757f4/src/mockAgent.js#L92-L149) 是按关键词进入固定场景、逐条显示预写步骤。其[租金转账确认路径](https://github.com/JatinGargz/sbi-dost/blob/61331ab73a3f2ff3c21961a9c4554523495757f4/src/mockAgent.js#L155-L205) 固定为 INR 12,000，并通过字符串 __approve_transfer:landlord 进入执行；UI 确认处理器也调用同一固定字符串。
- [前端页面](https://github.com/JatinGargz/sbi-dost/blob/61331ab73a3f2ff3c21961a9c4554523495757f4/src/App.jsx#L137-L163) 展示审批卡和状态日志，但没有服务器端确认、持久化或业务 API。仓库未发现自动化测试文件。

### 可借鉴与不采用

可以观察聊天与结构化数据卡、执行轨迹和显式确认 UI 的展示方式；需由 FinOrch 自行实现，确认必须绑定服务端真实计划和状态。不能将固定回复、虚构 policy、固定交易和显示动画等同真实 Agent/tool 执行，也不能复制没有明确许可的实现。

## 3. agentBANK

**仓库：** https://github.com/watsongm/agentbank

**检查 commit：** 400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a

**根许可证：** 未发现根 LICENSE；README 虽展示 MIT badge，但未提供许可证文本。

### 实际实现

- 后端按 domains 组织 Fastify routes/schema/service；[支付路由](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/domains/payments/routes.ts#L9-L36) 解析 schema 并交给 service；[输入 schema](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/domains/payments/schema.ts#L21-L34) 对 amount 使用 Number coercion。
- [支付 service](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/domains/payments/service.ts#L34-L67) 在写入前按 fapiInteractionId 查重、检查账户状态和可用余额并使用 Decimal；[事务内变更](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/domains/payments/service.ts#L67-L150) 更新账户、创建 Payment 和 DEBIT/CREDIT Transaction 记录。幂等查询位于事务前，源码没有在此处展示并发 duplicate request 的竞争处理。
- [Prisma 模型](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/prisma/schema.prisma#L72-L143) 将 Party、Account、Payment 及交易记录关联；Card/Portfolio/Holding/Order 也有模型，但本次列出的实际 domain route/service 只覆盖 Party、Accounts、Payments、Transactions，不能把存在模型当作完整场景 API。
- [认证插件](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/lib/auth.ts#L1-L51) 明确把 JWT signature 验证留给后续阶段，当前接受 demo-token 或配置 token，不应称为生产级 FAPI。
- [审计插件](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/src/lib/audit.ts#L30-L63) 在响应后保存请求路径、用户/请求 ID、请求体哈希、状态码和延迟，而不是原始 PII。
- [数据库烟测](https://github.com/watsongm/agentbank/blob/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a/backend/test/smoke.test.ts#L1-L24) 需要已配置 PostgreSQL；DATABASE_URL 缺失时整个 suite 会跳过。

### 可借鉴与不采用

最适合参考的是分域 route/schema/service 的职责拆分、API DTO 与数据模型分离，以及明确的支付和审计路径。若重做，FinOrch 应用 Pydantic/OpenAPI 单一事实来源，使用整数最小货币单位，并在同一 SQLite 事务内验证幂等和账本写入。其 MIT 声明没有许可证全文支持，代码保持不复用。

## 4. Airwallex Agentic Banking

**仓库：** https://github.com/everyai-com/airwallex-hackathon

**检查 commit：** 627a954ee78e4557c9b1574765950fc0778f18e6

**根许可证：** MIT，见[LICENSE](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/LICENSE#L1-L16)。

### 实际实现

- [18 个 kits](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/package.json#L9-L35) 覆盖模拟转账、支付、卡片、reconciliation、close 等情景；[MockTransport 状态](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/src/core/mock.ts#L168-L205) 在进程内对象中保存。
- [转账适配](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/src/api/transfers.ts#L46-L103) 在传输异常、重复 ID 或服务端错误时，按 request_id 查询转账结果再决定是否报告失败；[测试](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/tests/idempotency.test.ts#L45-L59) 验证重复请求返回同一个模拟 transfer。
- [纯规划函数](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/src/kits/kit1-treasury/planner.ts#L28-L39) 按余额、政策、预测确定 FUND/DEFER/ESCALATE 等计划，与实际执行分离。
- [账本示例](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/src/kits/kit12-close/ledger.ts#L1-L37) 对双分录是否平衡做纯函数校验，并配有[单元测试](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/tests/finance.test.ts#L224-L244)。这只是 demo 数值模型，使用 JS number 和四舍五入，不应照搬为金融精度实现。
- [审批 gate](https://github.com/everyai-com/airwallex-hackathon/blob/627a954ee78e4557c9b1574765950fc0778f18e6/src/core/approvals.ts#L19-L70) 声明绑定批准的金额/币种/收款方；但源码默认无 TTY 时自动批准。FinOrch 不应复制该默认值，服务端策略必须 fail-closed。

### 可借鉴与不采用

采用其“相同请求 ID重试后查询结果、不要盲目重复扣款”的思路，以及规划函数/状态演进测试。模拟状态非 SQLite 持久化；审批 gate 是命令行 demo，不代表用户身份验证。金额类型也需要按 FinOrch Data Contract 重新实现。

## 5. Kaching Copilot

**仓库：** https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026

**检查 commit：** 830acf47954b1685b10230d5c7899ce04e613864

**许可证：** 自定义 Kaching Copilot Evaluation & Research License，而非 Apache/MIT。其[许可第 1–3 条](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/LICENSE#L1-L13) 只给赛事评审/研究查看执行授权，明确保留一般复制、修改、分发、发布和商业化权利。未经书面许可不得复用代码。

### 实际实现与可借鉴点

- [ActionPolicyService](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/app/Services/Policy/ActionPolicyService.php#L10-L37) 表示 AI 是 proposer，并将 proposal 暂存在 TTL 15 分钟 Cache；[动作白名单](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/app/Services/Policy/ActionPolicyService.php#L68-L112) 为动作指定角色、风险、参数白名单和 PIN 要求。
- [批准控制器](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/app/Http/Controllers/Api/CopilotActionApprovalController.php#L69-L118) 对 proposal 加 cache lock 并校验 user/outlet；[审批检查](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/app/Http/Controllers/Api/CopilotActionApprovalController.php#L120-L204) 验证有效期、策略、员工角色和 PIN/限速，再执行固定映射。
- [执行、缓存失效和审计](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/app/Http/Controllers/Api/CopilotActionApprovalController.php#L208-L260) 由服务端执行白名单变更，再失效 proposal 并写 AuditLogger。相关[集成测试](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/blob/830acf47954b1685b10230d5c7899ce04e613864/tests/Feature/CopilotApprovalFirewallIntegrationTest.php#L21-L80) 准备多租户、多个角色和 PIN 场景；测试文件还覆盖过期 proposal、角色和限速用例。

### 限制

这是 SMB 商户管理系统，不是零售银行。缓存锁和 proposal 失效提供了防重思路，但不能单凭注释中的 “exactly-once” 推断数据库写、proposal 消费和 audit 之间具备跨进程原子性。这里只借鉴“服务端白名单策略、带时效 proposal、审批与执行分离”的设计思想，不引用或复制代码。

## 6. Aegis Banking Agent

**仓库：** https://github.com/vendra020-art/agentic-ai-system-banking-assistant

**检查 commit：** 7762c6f5fd8d08522011e93b6e280538b227be43

**根许可证：** 未发现根 LICENSE 文件。

### 实际实现

- [Security 模块](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/app/security.py#L11-L36) 使用正则脱敏卡号、SSN、邮箱，并由 require_scope 检查作用域；认证仅接受固定 mock-demo-token。
- [Coordinator](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/app/coordinator.py#L22-L65) 通过关键词形成确定性动作计划，再将工具结果加入 trace；[工具分派](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/app/coordinator.py#L88-L96) 通过受控 action map 调用读取/服务工具。
- [交易服务](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/services/transactions.py#L1-L37) 返回静态合成列表。它不是数据库账务写路径。
- [安全与编排测试](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/tests/test_security.py#L7-L23) 和 [Coordinator 工具测试](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/blob/7762c6f5fd8d08522011e93b6e280538b227be43/backend/tests/test_coordinator.py#L12-L53) 可验证脱敏、scope、工具调用和 fake seam。

### 可借鉴与不采用

适合参考以 fake provider/tool client 覆盖安全和编排路径、将 PII 脱敏置于路由前的测试方式。其内存限速器、mock token 和关键词 planner 不能作为生产级身份、跨进程限速或通用 Agent 的实现；未发现明确许可，不复制。

## 7. Banko AI Assistant

**仓库：** https://github.com/cockroachlabs-field/banko-ai-assistant

**检查 commit：** 892ea2e59681304edb370147ee003d6e9752f7bf

**根许可证：** MIT，见[LICENSE](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/LICENSE#L1-L16)。

### 实际实现

- [收据处理流程](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/banko_ai/agents/receipt_workflow.py#L164-L225) 用 LangGraph StateGraph 编排 receipt → fraud → budget 节点，并用 CockroachDBSaver 编译和持久化 thread。
- [Coach Agent](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/banko_ai/coach/agent.py#L152-L185) 是受 max_steps 限制的 JSON plan/parser 和 Python tool loop；[对话 checkpoint](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/banko_ai/coach/agent.py#L248-L317) 单独写入 CockroachDBSaver。这说明同一项目不同 Agent 子系统也可能采用不同编排方式。
- [工具层](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/banko_ai/coach/tools.py#L39-L94) 通过显式 database_url 调用 SQL，并将预算写入数据库；[checkpoint 测试](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/tests/coach/test_agent_checkpoint.py#L13-L59) 与[工具测试](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/tests/coach/test_tools.py#L21-L47) 依赖外部 DATABASE_URL，无配置时会 skip。
- 项目清单[依赖 LangGraph、CockroachDB、多个 Provider、Kafka 和 OCR 库](https://github.com/cockroachlabs-field/banko-ai-assistant/blob/892ea2e59681304edb370147ee003d6e9752f7bf/pyproject.toml#L31-L92)，远超当前 FinOrch Phase 1 的需要。

### 可借鉴与不采用

可借鉴可替换 LLM invoker/tool overrides、限制步骤数、持久化 thread、显式数据库 URL 的测试 seams。不要因为其 README 概述 multi-agent/LangGraph 就把 LangGraph 加进当前基础架构；先以 FinOrch 自有任务表解决简短工作流，再由 ADR 以真实恢复需求评估持久化图运行时。

## 8. RBC Banking Chatbot

**仓库：** https://github.com/frogcoder/llm-chatbot

**检查 commit：** 6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9

**根许可证：** MIT，见[LICENSE](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/LICENSE#L1-L16)。

### 实际实现

- [IntentDetector](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/chatbot/intent_detector.py#L5-L30) 只识别退出、清空、用户等固定命令，不是银行自然语言意图规划器。
- [SQLite 转账函数](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/chatbot/database.py#L82-L158) 将扣款、入账和 Transfers 写入一个 SQLite transaction 并在异常时 rollback。这是最小事务边界的可读例子；但函数没有在写入前检查 amount > 0、账户余额、账户更新行数或幂等键。
- [认证函数](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/chatbot/database.py#L12-L25) 直接比对数据库密码；源码注释明确限定为 demo。不可当作安全模式。
- [RAG 初始化](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/chatbot/rag/rag_chatbot.py#L1-L69) 接入 Gemini 和检索库；[MCP server](https://github.com/frogcoder/llm-chatbot/blob/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9/chatbot/mcp/server_sse.py#L34-L93) 同时暴露 FAQ、账户和转账工具。Prompt 约束只限制回答范围，不替代服务端授权和交易校验。
- 本次检查的仓库树未发现测试套件。

### 可借鉴与不采用

只借鉴 Python/SQLite transaction 小例子的可读性；实际转账需要增加余额/金额约束、同事务幂等记录、审计和数据库状态断言。MIT 许可允许相应复用，但 Phase 0.5 不复制代码，也不引入其 Gemini/RAG 依赖。

## 许可处置建议

1. **不将 GitHub 搜索可见性当作复用授权。** 根 LICENSE 缺失或模糊时，不复制代码、测试、素材或大段文档。
2. **Kaching 不得复制实现。** 许可只准赛事评审/研究；如未来有明确复用需求，先取得书面授权，并保留第三方依赖许可审查记录。
3. **MIT 项目也不能跳过归属。** 如未来确需复用 Airwallex、Banko 或 RBC 代码片段，先评估必要性、保留版权/许可文本和 NOTICE，并检查所复制文件是否另有声明。当前不复制。
4. **依赖是另一个许可面。** 本次没有执行传递依赖 license inventory；Phase 1 增加依赖或比赛公开前需扫描 runtime/dev/transitive dependencies、字体、图标、数据集、截图和模型许可。
