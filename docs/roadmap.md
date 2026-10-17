# Roadmap

状态只在代码、测试和文档证据支持时更新。未完成项标为 Planned，不表示已交付或已开工。

## Phase 0 — Repository Foundation

状态：**本轮目标**

- [x] 初始化私有优先的 Monorepo 和最小前后端工程。
- [x] API v1 健康检查及 OpenAPI 到前端类型生成流程。
- [x] 建立 API、Agent Tool、Workflow、Data、安全和协作契约文档。
- [x] 建立治理文件、PR/Issue 模板及 GitHub Actions CI。
- [x] 官方赛事公开信息核对，并记录未确认项。
- [ ] 团队确认版权/授权责任人、比赛官方规则、评分权重和提交资料清单。
- [ ] GitHub 管理员创建/确认 Private 仓库并设置 main 分支保护。

## Phase 1 — 模拟场景与基础体验（Planned）

- 在确认赛题范围后选定优先场景；目标是实现六大场景可演示的基础模拟闭环。
- 建立合成数据集、Domain 规则、持久化和可重置的 Demo seed。
- 实现基本前端体验、服务端权限与确认边界，以及 API/集成测试。
- 按已定义 Tool/Workflow 契约先实现有限、可审计的流程，不接真实银行或支付系统。
- 多工作流并行：A 前端 UX；B Banking Backend & Data；C Agent & Tool Orchestration；D Security, Testing & Integration。
- 开工前选定负责人并将跨模块契约拆成可 Review 的任务；共享 API/Data/Tool 文件先协调所有权。

## Phase 2 — Agent 可靠性与安全增强（Planned）

- 评估 OpenAI-compatible Provider 和受控 Tool Calling，不将模型输出视为权威结果。
- 构建澄清、计划预览、确认挑战、部分成功、取消恢复、幂等和审计能力。
- 建立越权、Prompt Injection、重试、失败和可靠性评测；只据实报告测量结果。
- 若考虑 LangGraph、MCP 或其他编排框架，先记录 ADR 并对比简单自研状态机的复杂度、恢复和可观测性。

## 后续里程碑（待赛事和团队确认）

- 比赛提交包、演示脚本和公开发布准备：按官方最新通知与管理员清单执行。
- 任何部署、真实服务连接或生产级认证均需单独评估；不属于 Phase 0/当前授权范围。
