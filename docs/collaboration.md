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

PR 使用 `.github/pull_request_template.md`。普通变更一名其他成员批准；涉及资金、权限和安全契约至少增加一位具备相应审查职责的成员。若团队当前无专职安全成员，由维护者指定另一名成员完成安全 Review，并记录理由。作者不能自审替代此要求。

CI 通过且所有阻断评论已解决后才可合并。维护者需保持代码、契约和文档一致。发布前按另行发布清单执行。

## GitHub 管理员设置（需人工操作）

管理员在仓库 **Settings → Rules → Rulesets**（或 Branches/Branch protection rules）为 `main` 配置：

1. 要求通过 Pull Request 合并，至少 1 个非作者批准；若平台可用，启用 Code Owner Review。
2. 要求状态检查 `phase-0 / checks` 通过后合并（先运行一次 CI，再从列表选择准确名称）。
3. 阻止强制推送和分支删除；禁止绕过规则，或仅对指定管理员开放紧急绕过并审计。
4. 视团队需要要求分支与最新 `main` 同步；不要因启用配置而降低审查要求。
5. 确认仓库可见性为 Private，并只邀请正式成员；按职责使用 Read/Triage/Write/Maintain/Admin 最小权限。

当前本地目录没有 GitHub remote，因此无法读取 GitHub 仓库设置或替管理员启用规则。CI 工作流本身已准备好，但分支保护必须在 GitHub 管理界面配置。

**计划限制：** GitHub 官方文档说明，GitHub Free 下受保护分支适用于公开仓库；私有仓库的受保护分支需要 GitHub Pro、Team 或 Enterprise。管理员应先核对仓库所属账户的当前计划；如果该计划不支持私有仓库分支保护，应保留 Private，并在 GitHub 之外执行 PR、独立 Review 和 CI 必须通过后才合并的团队流程，不要为启用规则而公开仓库。具体计划能力以[官方受保护分支说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)为准，核对日期：2026-10-17。
