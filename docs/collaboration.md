# 协作流程

## 私有优先策略

仓库采用 **Private-first, Open-source-on-submission**。GitHub 项目在开发阶段设置为 Private，只邀请正式团队成员，按职责授予最小权限。Issues、PR、Projects、CI 和技术文档均按私有仓库管理。准备 Apache-2.0 文件不构成公开授权。

由仓库管理员在比赛提交阶段核实官方要求、团队权属和许可、安全及依赖检查后，手动决定是否将仓库设为 Public。Codex 不更改可见性。公开前检查见 [`development/public-release-checklist.md`](development/public-release-checklist.md)。

## Git 工作流

- `main`：可运行、通过 CI 的稳定分支；不直接推送。
- `feat/*`：新功能；`fix/*`：缺陷；`docs/*`：文档；`refactor/*`：重构；`chore/*`：维护。
- PR 合并到 `main`。普通 PR 至少一名其他成员 Review；资金操作、权限和安全契约变更还需额外安全 Review。
- CI 必须通过；合并前解决 Review 请求。优先小 PR，避免长时间分支。
- 提交使用 Conventional Commits，如 `feat(agent): define tool result contract`。
- 有长期架构影响的决策新增 ADR；不要用 ADR 替代契约文档。

## 跨模块责任与并行建议

以下是工作流边界，不绑定姓名，也不代表 Phase 1 已启动：

| 工作流                             | 主要范围                                        | 需要协商的共享接口                     |
| ---------------------------------- | ----------------------------------------------- | -------------------------------------- |
| A. Frontend & UX                   | 页面、交互、可访问性、任务状态呈现              | API Schema、Workflow 事件和错误码      |
| B. Banking Backend & Data          | 模拟业务用例、Domain 规则、存储、迁移和复现数据 | API、Money、Data、幂等与事务语义       |
| C. Agent & Tool Orchestration      | Provider 抽象、工具注册、规划和执行状态         | Tool Schema、权限、确认、任务/步骤模型 |
| D. Security, Testing & Integration | 威胁建模、策略/审计、集成测试、CI 和安全 Review | 权限、确认、错误、事件和测试数据       |

工作流可由多人共享或合并。建议各自先分模块实现，跨接口尽量只由接口负责人修改契约文件；先通过 ADR/契约 PR 协调，再由提供方和消费者分别更新代码，降低同时编辑同一入口文件的冲突。

## 接口变更流程

1. 在 PR 描述说明受影响的 API、Tool、Workflow、Data 契约和兼容性。
2. 先更新对应契约、OpenAPI 和 ADR（必要时），标明状态是 Proposed/Planned 或 Implemented。
3. 提供方实现 schema/行为及测试；消费者更新调用和类型。禁止两边手写不一致接口。
4. 对破坏性变更说明迁移/版本策略，并由相关工作流负责人 Review。
5. 资金、权限、确认、审计相关改动请求额外安全 Review。

## Pull Request 与 Review

PR 使用 `.github/pull_request_template.md`。多人协作时，普通变更由至少一名其他成员批准；涉及资金、权限和安全契约至少增加一位具备相应审查职责的成员。若团队当前无专职安全成员，由维护者指定另一名成员完成安全 Review，并记录理由。作者自审不能替代独立 Review。单人维护期间的人工流程例外见下文；安全敏感变更应等待独立审查。

CI 通过且所有阻断评论已解决后才可合并。维护者需保持代码、契约和文档一致。发布前按另行发布清单执行。

## GitHub 管理员设置与当前状态

仓库管理员可在 **Settings → Rules → Rulesets** 为 `main` 设置规则：要求 PR、配置至少 1 个非作者批准、要求 `phase-0 / checks` 通过、阻止强制推送和分支删除，并限制绕过权限。启用前先让 CI 成功运行一次，以便选择准确的状态检查名称。

### 当前核查结果（2026-10-17）

- `Fire0206/finorch-banking-agent` 当前为 **Private**，默认分支为 `main`。
- GitHub Branch Protection API 对 `main` 返回 `Branch not protected (404)`；仓库 Rulesets API 返回空列表。因此目前既未启用传统分支保护，也没有适用的 Ruleset。CI 会运行，但当前没有服务端规则强制阻止直接推送或阻止未通过 CI 的合并。
- GitHub REST API 未提供当前个人账户的计划字段；需由账户持有人在 **Settings → Billing and licensing → Plans** 手动确认。此次未更改仓库可见性或 GitHub 设置。

GitHub 官方说明：Rulesets 在 GitHub Free 下适用于公开仓库；GitHub Pro、Team、Enterprise Cloud 支持私有仓库 Rulesets。受保护分支对 Free 和付费计划的私有仓库支持范围也有相同限制。参见[Rulesets 计划支持](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)及[受保护分支计划支持](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)，核对日期：2026-10-17。

### Private 仓库的协作替代方案

若账户当前为 GitHub Free 且无法为 Private 仓库启用规则，保持仓库私有，并执行以下人工门禁：

1. 所有变更从 `feat/*`、`fix/*` 等分支提交 PR 到 `main`；团队约定不直接推送 `main`。
2. 合并人逐项确认 CI `checks` 通过、PR 清单完整、变更已 Review；资金、权限和安全契约变更需额外安全 Review。
3. 多人协作时由非作者成员独立 Review；单人维护期间，将 PR 作为审计记录并自行复核 Diff 与 CI，但明确这不是独立 Review，也不是 GitHub 强制规则。
4. 限制仓库写权限，仅邀请正式成员；管理员定期检查 `main` 和 PR 历史。

该方案可形成清楚的团队流程，但无法技术性阻止有写权限的成员绕过流程直接推送。若必须由 GitHub 强制执行 PR、Review 和必需 CI，应由管理员确认计划后升级到支持 Private Rulesets 的计划（个人仓库可评估 Pro；组织仓库可评估 Team/Enterprise），无需公开仓库。
