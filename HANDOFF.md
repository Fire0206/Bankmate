# FinOrch 当前工作交接

> 保存日期：2026-10-22  
> 当前目的：记录本轮 Web 前端产品化重构。下午继续沟通时，先读本文件即可恢复上下文。

## 1. 当前结论

前端已从单页 Agent 原型升级为多页面产品工作台，并直接接入仓库现有 FastAPI 后端。

当前包含：

- 本地 Demo 进入页。
- 财务总览、Agent、账单、银行卡、转账、订阅、模拟理财七个页面。
- 浏览器 Hash 路由：刷新、前进、后退可用。
- View Transition 页面切换。
- 导航连续选中背景动效。
- 确认 Modal、筛选 Modal、交易详情 Drawer、审计 Drawer。
- Toast 成功、等待确认和错误反馈。
- 真实 API 数据加载与结构化 Skeleton。
- 桌面与手机响应式布局。

当前仍然没有：

- 生产级真实认证登录。
- 真实银行、支付、商户或券商连接。
- 正式 `dispute.submit` 争议申诉工具。
- 信用评分功能。

Demo 进入页是“本地演示身份入口”，不是真实登录系统。

## 2. 当前 Git 状态

- 实际仓库：`F:\finnorch-banking-agent\finorch-banking-agent`
- 当前分支：`feat/web-product-redesign`
- 基线：本地 `main` 的 `c164424`
- 工作区修改：未提交、未推送
- 远端同步：本轮尝试 `git fetch` 时 GitHub 连接被重置；当前基于之前已有的本地 `origin/main` 引用继续。

用户已有未跟踪文件必须保留：

- `extract-neo-card-apply.ps1`
- `extract-neo-payment-more2.ps1`

不要删除或擅自提交这两个脚本。

## 3. 本地网站

- Web：`http://127.0.0.1:5173/`
- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

页面入口：

- `#/overview`
- `#/assistant`
- `#/bills`
- `#/cards`
- `#/transfers`
- `#/subscriptions`
- `#/investments`

如果当前直接进入总览，点击右上角头像“退出演示”可回到 Demo 进入页。

## 4. 当前前端交互

### Demo 进入页

- 展示合成身份、数据集版本、Provider 模式和服务连接状态。
- 只允许在 API 与 Demo Session 就绪后进入。
- 明确标注不是真实用户登录。
- 手机端改为上下布局，无横向溢出。

实现文件：`apps/web/src/components/DemoGate.tsx`

### 页面切换

- 使用 `document.startViewTransition`。
- 侧边栏、顶部栏保持固定。
- 主内容执行淡出、上移和重新进入。
- 浏览器不支持或开启 `prefers-reduced-motion` 时自动降级。
- 浏览器后退、前进同样触发转场。

实现位置：`apps/web/src/App.tsx`、`apps/web/src/index.css`

### 导航动效

- 选中背景使用共享动画元素 `nav-active-surface`。
- 页面变化时胶囊从旧菜单移动到新菜单。
- 已验证 View Transition 实际调用，导航文字和图标最终状态正常。

### 加载状态

- 总览、账单、卡片、转账、订阅、理财均有结构化 Skeleton。
- 慢网络验证时同时出现 11 个 Skeleton/图表占位元素。
- 图表加载使用柱状骨架，表格使用行骨架，卡片使用卡片骨架。

实现文件：`apps/web/src/components/Skeleton.tsx` 及各页面。

## 5. 页面能力

| 页面       | 当前内容                                       | 真实交互                                |
| ---------- | ---------------------------------------------- | --------------------------------------- |
| 财务总览   | 余额、支出、订阅、卡片、六个月现金流、异常提示 | 跳转账单、卡片或交给 Agent              |
| 智能助手   | 对话、任务步骤、结果卡、执行上下文             | 创建任务、补充输入、确认、取消、恢复    |
| 账单分析   | 月度 KPI、现金流图、分类、交易明细             | 筛选 Modal、交易详情 Drawer、交给 Agent |
| 银行卡     | 卡片视觉、状态、控制列表                       | 冻结/解冻确认 Modal                     |
| 转账与分账 | 账户、收款人、记录、AA 分账                    | 向 Agent 发起转账/分账任务              |
| 订阅代扣   | 月费、下次扣款、状态、列表                     | 暂停、恢复、取消确认                    |
| 模拟理财   | 资产、风险等级、产品、持仓、订单               | 产品风险匹配、申购/赎回任务             |

## 6. 弹窗与覆盖层

### Confirmation Modal

- 真实服务端确认挑战。
- 展示资源、当前状态、目标状态、影响和有效期。
- 桌面居中 Modal，手机底部 Bottom Sheet。
- 支持遮罩关闭、Escape、焦点恢复和基础焦点循环。
- `busy` 时不能误关闭。

实现文件：

- `apps/web/src/components/ConfirmationModal.tsx`
- `apps/web/src/components/ConfirmationCard.tsx`

### Filter Modal

- 月份、类别、收支方向和商户关键词。
- 点击“应用筛选”后才更新账单、图表和交易列表。
- 当前后端筛选按 actor 限定。

实现文件：`apps/web/src/pages/BillsPage.tsx`

### Transaction Drawer

- 从右侧打开交易详情。
- 显示金额、时间、类别、说明、来源卡、交易编号。
- 异常交易显示确定性规则原因。
- 可直接交给 FinOrch 继续处理。

实现文件：

- `apps/web/src/components/SideDrawer.tsx`
- `apps/web/src/pages/BillsPage.tsx`

### Audit Drawer

- 点击“操作记录”打开。
- 展示任务状态、处理步骤和服务端审计事件。
- 有待确认挑战时可直接重新打开确认 Modal。

实现文件：`apps/web/src/App.tsx`、`apps/web/src/components/TaskDetails.tsx`

### Toast

- 任务完成：成功提示。
- 等待确认：警告提示。
- 操作失败：错误提示。
- 不替代卡片、订阅或任务页面的持久状态。

实现文件：`apps/web/src/components/Toast.tsx`

## 7. 关键文件

| 路径                                            | 作用                                         |
| ----------------------------------------------- | -------------------------------------------- |
| `apps/web/src/App.tsx`                          | 页面状态、路由、Agent 任务、确认和覆盖层编排 |
| `apps/web/src/pageConfig.ts`                    | 七个页面的路由与导航元数据                   |
| `apps/web/src/api/client.ts`                    | 现有后端 API 客户端                          |
| `apps/web/src/components/DemoGate.tsx`          | Demo 进入页                                  |
| `apps/web/src/components/WorkspaceOverview.tsx` | 财务总览                                     |
| `apps/web/src/components/CashflowChart.tsx`     | Lightweight Charts 现金流图                  |
| `apps/web/src/components/ConfirmationModal.tsx` | 高风险确认 Modal                             |
| `apps/web/src/components/SideDrawer.tsx`        | 交易/审计 Drawer                             |
| `apps/web/src/components/Skeleton.tsx`          | 结构化加载占位                               |
| `apps/web/src/components/Toast.tsx`             | 操作反馈                                     |
| `apps/web/src/pages/BillsPage.tsx`              | 账单分析、筛选和交易详情                     |
| `apps/web/src/pages/CardsPage.tsx`              | 银行卡页面                                   |
| `apps/web/src/pages/TransfersPage.tsx`          | 转账与 AA 分账页面                           |
| `apps/web/src/pages/SubscriptionsPage.tsx`      | 订阅与代扣页面                               |
| `apps/web/src/pages/InvestmentsPage.tsx`        | 模拟理财页面                                 |
| `apps/web/src/index.css`                        | 视觉系统、响应式、弹窗、骨架和转场           |

新增依赖：

- `lightweight-charts@5.2.1`

## 8. 已验证结果

本轮实际运行并通过：

```powershell
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm exec prettier --check ...
.\.venv\Scripts\ruff.exe check --config apps/api/pyproject.toml apps/api
.\.venv\Scripts\ruff.exe format --check --config apps/api/pyproject.toml apps/api
.\.venv\Scripts\python.exe -m pytest apps/api/tests
```

- ESLint：通过
- TypeScript：通过
- Vite 生产构建：通过
- Prettier：通过
- Ruff lint/format：通过
- pytest：`112 passed`
- 七个页面逐页打开：无空白页、无页面级 API 错误
- 390px 手机视口：`documentWidth = 390`，无横向溢出
- View Transition：实际调用验证
- 慢网络 Skeleton：验证到 11 个结构化占位元素
- 筛选 Modal、交易 Drawer、确认 Modal：均已实际打开并截图验证

演示数据已恢复为干净的 `phase1e-v1` 合成数据集。

## 9. 视觉参考结论

已研究 Neo Financial 的：

- Onboarding。
- Accounts 首页。
- Payments 首页。
- 普通转账、定时转账、收款请求。
- Pay a bill。
- Pending 交易详情。
- 取消周期转账。
- Autodeposit。
- 信用卡交易详情。
- Services / Cash Flow 交易详情。
- Insights。
- 卡片管理、冻结、解冻。
- Filtering spending。
- Cash flow information。
- Report an issue。

采用原则：

- 金额和交易对象是第一视觉层级。
- 高风险操作必须服务端确认。
- 证据在确认之前展示。
- 处理中、成功、失败和可取消性必须分开表达。
- 分类统计优先使用可读列表和横向条。
- 长解释不用 Tooltip；使用页面说明、Modal 或 Drawer。
- 不照搬完整卡号、PIN、信用评分和加拿大本地 Interac 生态。

## 10. 当前已知限制

### 前端

- 正式争议申诉流程尚未实现，因为没有后端 `dispute.submit` 工具。
- 登录仅为 Demo 进入页，不是真实认证。
- 尚未完成完整键盘命令面板和全站滚动位置恢复。
- 尚未做正式视觉回归测试或浏览器自动化测试套件。
- 大量视觉规则集中在一个 `index.css` 中，后续可拆分为 tokens、layout、pages、overlays。

### 后端

- Demo Identity 不是生产认证。
- 没有真实金融网络。
- DeepSeek 真实调用不在 CI。
- 独立安全 Review 尚未完成。
- `cross_investment_risk_rejected` 仍是已知模型工具选择失败样本；服务端风险闸门会阻止危险申购。

## 11. 下午继续时建议先做

1. 打开 `http://127.0.0.1:5173/`，从 Demo 进入页逐页检查。
2. 确认视觉方向是否保留深绿导航、暖白背景和金色强调。
3. 在可疑扣款主 Demo 中检查“证据 → 确认 → 后续确认 → 完成”的节奏。
4. 决定是否继续补充：
   - `Ctrl/Cmd + K` 全局命令面板。
   - 滚动位置恢复。
   - 数字滚动和图表逐点绘制。
   - 演示引导高亮。
   - 页面级 Storybook 或视觉回归测试。
5. 确认后再提交 Git，不要在工作未确认前直接推送 `main`。

## 12. 启动方式

当前若本地服务仍在运行，直接访问 Web 地址。

重新启动：

```powershell
cd "F:\finnorch-banking-agent\finorch-banking-agent"
.\.venv\Scripts\python.exe -m finorch_api
```

另开终端：

```powershell
cd "F:\finnorch-banking-agent\finorch-banking-agent"
pnpm --filter @finorch/web dev --host 127.0.0.1
```

重新安装依赖：

```powershell
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e apps/api pytest httpx2 ruff
```

## 13. 下一位代理提示词

```text
请接手 F:\finnorch-banking-agent\finorch-banking-agent 的 FinOrch 前端。
先读取 HANDOFF.md、AGENTS.md、当前 Git diff 和相关契约。
当前分支为 feat/web-product-redesign，基于 main c164424，所有改动尚未提交。
保留 extract-neo-*.ps1 和用户现有改动。
不要伪造真实认证、争议申诉提交或信用评分。
前端已实现七个页面、Demo 门禁、View Transition、导航共享动效、Skeleton、确认 Modal、筛选 Modal、交易/审计 Drawer 和 Toast。
先运行 lint、typecheck、build，并用真实 FastAPI 数据逐页验证后再修改。
```
