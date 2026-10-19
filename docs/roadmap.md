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

## 后续业务场景（Planned）

- 在确认赛题范围后选定优先场景；目标是实现六大场景可演示的基础模拟闭环。
- 在 Phase 1A 和 Phase 1C 的共享合成数据、Domain 规则、迁移和 Demo seed 上扩展智能转账、理财和跨场景联动。
- 实现基本前端体验、服务端权限与确认边界，以及 API/集成测试。
- 按已定义 Tool/Workflow 契约先实现有限、可审计的流程，不接真实银行或支付系统。
- 五条工作流建议：A Banking Core & Database；B Banking Business APIs；C Agent & Tool Orchestration；D Frontend & UX；E Security, Testing & Integration。Phase 1A 完成共享 Banking Core 最小底座，详细职责见[Phase 1 实施计划](research/phase1-implementation-plan.md)。
- 开工前选定负责人并将跨模块契约拆成可 Review 的任务；共享 API/Data/Tool 文件先协调所有权。

## Phase 2 — Agent 可靠性与安全增强（Planned）

- 通过真实模型沙箱验证 OpenAI-compatible Provider 行为并建立可靠性评测，不将模型输出视为权威结果。
- 对多步部分成功、超时、崩溃恢复、长时间运行取消、异步状态推送和跨场景幂等进行设计与验证。
- 建立越权、Prompt Injection、重试、失败和可靠性评测；只据实报告测量结果。
- 若考虑 LangGraph、MCP 或其他编排框架，先记录 ADR 并对比简单自研状态机的复杂度、恢复和可观测性。

## 后续里程碑（待赛事和团队确认）

- 比赛提交包、演示脚本和公开发布准备：按官方最新通知与管理员清单执行。
- 任何部署、真实服务连接或生产级认证均需单独评估；不属于 Phase 0/当前授权范围。
