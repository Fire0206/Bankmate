# Roadmap

状态只在代码、测试和文档证据支持时更新。未完成项标为 Planned，不表示已交付或已开工。

## Phase 0 — Repository Foundation

状态：**基础工程已交付；团队与管理员事项仍待完成**

- [x] 初始化私有优先的 Monorepo 和最小前后端工程。
- [x] API v1 健康检查及 OpenAPI 到前端类型生成流程。
- [x] 建立 API、Agent Tool、Workflow、Data、安全和协作契约文档。
- [x] 建立治理文件、PR/Issue 模板及 GitHub Actions CI。
- [x] 官方赛事公开信息核对，并记录未确认项。
- [ ] 团队确认版权/授权责任人、比赛官方规则、评分权重和提交资料清单。
- [x] 创建并核验 Private GitHub 仓库；检查 `main` 保护状态。
- [ ] 管理员确认账户计划；若支持，则在保持 Private 的前提下启用 Ruleset，否则继续采用协作流程中说明的人工门禁。

## Phase 1A — Shared Banking Foundation

状态：**已实现并合并**

- [x] SQLite、SQLAlchemy Session、Alembic 迁移和四个首批数据实体。
- [x] 两个合成 Demo User、账户和卡片 Seed，以及受限的本地/测试 Reset。
- [x] 卡片读取 API、资源归属校验、卡片状态 Domain 规则、冻结/解冻 Application 用例和事务内审计。
- [x] 临时 SQLite 集成测试、迁移/Seed/Reset 测试及 OpenAPI 到 TypeScript 类型同步。

## Phase 1B — 卡片冻结 Agent 垂直切片

状态：**已实现并合并；Phase 1B.5 可靠性恢复 PR #8 已合并**

- [x] Fake 与 OpenAI-compatible Provider 抽象、受控 Tool 注册/Schema、执行记录与错误状态。
- [x] 服务端确认策略/挑战和确认 API；冻结/解冻始终需要本次操作的显式确认。
- [x] 持久化任务/步骤 Workflow、幂等/失败处理及通用追加式审计。
- [x] 前端卡片查询、任务进度、确认/取消交互和服务端状态刷新。
- [x] 安全与集成测试覆盖会话归属、并发确认、重试、事务回滚和审计一致性；真实 Provider 未进行外部调用。
- [x] CI 与 PR 合并完成；Phase 1B 的确认/权限实现自查记录见开发指南，独立人工安全 Review 状态按对应 PR 记录。

## Phase 1C — 账单分析与订阅代扣

状态：**已实现并合并（PR #9；CI 通过）**

- [x] 合成交易流水、按月/类别/商户筛选、收支/类别/六个月趋势汇总。
- [x] 基于固定金额规则的异常提示；明确不代表欺诈检测。
- [x] 由重复周期交易识别并持久化月度订阅，展示费用、状态和下次模拟扣款。
- [x] `subscription.pause/resume/cancel` 经服务端确认、幂等、资源版本检查、事务与审计后更新模拟状态。
- [x] Fake Provider 与 OpenAI-compatible Tool Registry 覆盖三类场景；前端展示流水、汇总、订阅及确认结果。
- [x] 新增 Alembic migration、`phase1c-v1` Seed/Reset 和集成测试；PR #9 的 CI 已通过并合并至 `main`。

## Phase 1D — 智能转账与理财

状态：**五个场景模拟闭环已实现；DeepSeek 真实模型 20 场景联调通过**

- [x] 普通/定时模拟转账、收款人、账户余额、转账历史和确认后的模拟执行。
- [x] AA 金额拆分、参与人及模拟收付款状态；变更需服务端确认。
- [x] 模拟理财产品查询/比较、用户风险等级匹配、确认后申购/赎回、持仓和订单。
- [x] 所有资金变更更新账户余额与交易/持仓，并与确认挑战、幂等和审计记录保持一致。
- [x] 扩展 Agent Tool Registry、Fake Provider、前端结果卡和 OpenAPI 生成类型。
- [x] DeepSeek `deepseek-flash` 本地端到端 20 项：工具选择、参数和任务完成均为 100%；结果和局限见[Agent 可靠性指南](development/agent-reliability.md)。
- [x] 新增 Alembic migration、可重复的 `phase1d-v1` Seed/Reset、集成测试；PR 状态以当前 GitHub 记录为准。

## Phase 1E — 跨场景 Agent 与完整任务闭环

状态：**六场景模拟闭环已实现；2026-10-19 最新一轮 DeepSeek 评测 9/10，详情见[开发指南](development.md)**

- [x] 为合成交易增加来源卡关联和同日同商户同金额的可解释重复收费规则；提示不等同于欺诈检测。
- [x] 实现服务端资金计划工具 `finance.payday_plan`，按模拟余额、月度收支、转账及预留金额计算可投资额度。
- [x] 完成可疑扣款处置：读账单证据和订阅，逐个确认冻结卡和暂停自动扣费。
- [x] 完成发薪日资金调度：读账户和账单，服务端计算计划，逐步确认模拟转账和理财申购。
- [x] 确认后续跑同一持久化 Task；支持多个确认、刷新恢复、取消、部分成功、失败后继续，并阻止已成功写操作重放。
- [x] 完成状态门禁：明确请求的写操作必须有成功服务端工具记录后才能把任务标为完成；陌生收款人和不匹配风险等级均保持安全失败/追问。
- [x] Web 展示跨场景进度、真实工具结果、确认和最终账户/持仓状态；类型由 OpenAPI 重新生成。
- [x] 增加临时 SQLite 集成测试和 10 项 DeepSeek 跨场景、澄清、取消、失败与恢复评测；评测结果与模型偏差见开发指南。

## Phase 2 — Agent 可靠性与安全增强（进行中）

- [x] 离线复核 Phase 2D 报告并使用 v2 评分器；缺少原始证据的审计/注入行为不作推断。
- [x] 修复不完整写参数、AA 分账字段校验和发薪日转账/理财依赖顺序；使用 Fake Provider 与回归测试验证。
- [x] 用 32 例开发集完成调优，并冻结新的 40 例 Holdout 两轮评测；开发集 32/32、Holdout 63/80，解释及限制见[开发指南](development.md)。
- 持续改进 DeepSeek 工具路由和任务结束状态，不把小样本通过率当作普遍成功率。
- 验证进程崩溃后的任务续跑、长时间运行取消、并发跨任务幂等和工具/provider 中断恢复。
- 评估 REST 轮询之外的任务事件推送；如考虑 SSE/WebSocket，先审查认证和隐私边界。
- 建立越权、Prompt Injection、重试、失败和可靠性评测；只据实报告测量结果。
- 若考虑 LangGraph、MCP 或其他编排框架，先记录 ADR 并对比简单自研状态机的复杂度、恢复和可观测性。

## Phase 3 — 比赛功能补全与交付（进行中）

状态：**六场景相关后端能力和本地演示数据已扩展；Phase 3 Final 的真实模型开发集、冻结留出集和最终交付检查仍待完成。** 逐项功能状态及队友 `/showcase` 的实际缺口见[Phase 3 验收矩阵](phase3-acceptance.md)。

- [x] 补齐银行卡限额、交易限制、申请、挂失/补卡及高风险模拟 OTP；消费限制在服务端模拟扣款路径实际执行。
- [x] 补齐年度账单、续费提醒、风险问卷、增强转账/理财确认及生日预算预留、到期订单二次确认。
- [x] 为可疑扣款、发薪日调度和生日订单保存轻量依赖 DAG，并为受阻任务提供本地模拟人工接管。
- [x] 建立独立于旧 Phase 3 Holdout 的 Phase 3 Final 开发集与留出集；留出集须在最终实现提交后冻结，并只运行一次。
- [ ] 完成有限预算的 DeepSeek 开发集修复循环和冻结留出集端到端验收，分别记录任务、工具/参数、服务端风险拦截和最终数据库状态。
- [ ] 完成队友 `/showcase` 的生日订单影响信息与 OTP 输入交接后复测；当前 UI 缺口及未执行的高风险确认均已如实记录。
- [ ] 完成最终测试、文档一致性与私有仓库 CI 检查，再按既有授权提交和交付。

## 后续扩展（Planned）

- 丰富六个模拟场景的数据与演示，但不连接真实银行、支付网络或商户。
- 五人工作流建议：A Banking Core & Database；B Banking Business APIs；C Agent & Tool Orchestration；D Frontend & UX；E Security, Testing & Integration。Phase 1A 完成共享 Banking Core 最小底座，详细职责见[Phase 1 实施计划](research/phase1-implementation-plan.md)。
- 跨模块任务开始前协调负责人和文件所有权；共享 API/Data/Tool 文件先锁定接口，再并行实现。

## 后续里程碑（待赛事和团队确认）

- 比赛提交包、演示脚本和公开发布准备：按官方最新通知与管理员清单执行。
- 任何部署、真实服务连接或生产级认证均需单独评估；不属于 Phase 0/当前授权范围。
