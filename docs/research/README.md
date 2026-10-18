# Phase 0.5：开源源码调研与架构建议

**核对日期：2026-10-18**

**范围：技术研究与 Phase 1 实施计划；不实现业务、不调整既有契约。**

## 本轮结论

- 保留现有 React + TypeScript + Vite + Tailwind、FastAPI + Pydantic、pnpm + uv 的模块化单体，不增加生产依赖。
- Banking Core 采用模拟数据与 SQLite；建议用整数最小货币单位、小型双分录账本、数据库事务和唯一幂等键实现可验证的模拟资金操作。
- Agent 默认采用模型无关 Provider 接口、单 Agent 有界调用循环、Pydantic Tool Registry 和独立持久化 Workflow 状态。暂缓 LangGraph、Google ADK、MCP 和 Multi-Agent。
- 第一条垂直切片建议实现“冻结一张模拟银行卡”：通过服务端授权、确认、幂等、SQLite 状态变更和审计；不处理资金转移。
- 最值得借鉴的源码设计来自 agentBANK、Airwallex Agentic Banking 和 Aegis Banking Agent。Kaching Copilot 的审批设计有研究价值，但许可证明确限制代码复用。

以上均是建议，不代表 Phase 1 已开始或已实现。当前六大场景仍为规划状态。

## 范围与方法

按指定的八个 GitHub 仓库做源码级检查，记录固定 commit、文件路径、代码范围和根许可证。源代码通过仓库 Git 对象只读检查；未安装或执行第三方项目，也未复制任何第三方代码。“源码已验证”只表示实现路径可从指定源码看到，不代表本轮执行了该项目或运行了其全部测试。

官方赛事网站在本次检查时无法正常抓取；报名工作台显示登录页，登录前未展示完整规则、时间表或提交材料。赛事是否要求公开源代码、作品权属及官方截止日期均未在本轮确认。六大场景是 FinOrch 的项目规划，不能据此宣称为官方赛题最低要求。

## 项目索引

| 项目                                                                                                                                      | 检查 commit                              | 根许可证状态                                           | 源码重点                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------ | --------------------------------------------------- |
| [BankPilot](https://github.com/souravmighty/banking-agent/tree/6508bb7afbccbfcac80dc73665f41c8fc63ed0ba)                                  | 6508bb7afbccbfcac80dc73665f41c8fc63ed0ba | 未发现根 LICENSE；个别 Google 文件有 Apache-2.0 文件头 | Google ADK、BigQuery 转账服务、OTP、MCP             |
| [SBI Dost](https://github.com/JatinGargz/sbi-dost/tree/61331ab73a3f2ff3c21961a9c4554523495757f4)                                          | 61331ab73a3f2ff3c21961a9c4554523495757f4 | 未发现根 LICENSE；README 声称 MIT                      | React 展示、内存状态、固定关键词工作流              |
| [agentBANK](https://github.com/watsongm/agentbank/tree/400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a)                                          | 400c3ecfc3c9cae9c76e6b0e5cb5de7aa004252a | 未发现根 LICENSE；README 有 MIT 徽章                   | Fastify API、Prisma/PostgreSQL、支付与审计          |
| [Airwallex Agentic Banking](https://github.com/everyai-com/airwallex-hackathon/tree/627a954ee78e4557c9b1574765950fc0778f18e6)             | 627a954ee78e4557c9b1574765950fc0778f18e6 | MIT                                                    | 模拟支付、审批、幂等、纯函数账本                    |
| [Kaching Copilot](https://github.com/Syaahnhl/kaching-copilot-fintechathon-2026/tree/830acf47954b1685b10230d5c7899ce04e613864)            | 830acf47954b1685b10230d5c7899ce04e613864 | 自定义评审/研究许可；不授权一般复制、修改或再分发      | 服务端动作白名单、PIN/角色、提案过期与审计          |
| [Aegis Banking Agent](https://github.com/vendra020-art/agentic-ai-system-banking-assistant/tree/7762c6f5fd8d08522011e93b6e280538b227be43) | 7762c6f5fd8d08522011e93b6e280538b227be43 | 未发现根 LICENSE                                       | Mock-first 边界、脱敏、工具隔离和测试               |
| [Banko AI Assistant](https://github.com/cockroachlabs-field/banko-ai-assistant/tree/892ea2e59681304edb370147ee003d6e9752f7bf)             | 892ea2e59681304edb370147ee003d6e9752f7bf | MIT                                                    | LangGraph 收据流程、CockroachDB 检查点、多 Provider |
| [RBC Banking Chatbot](https://github.com/frogcoder/llm-chatbot/tree/6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9)                             | 6eb2dd49f5ac2caf95a4348dd55fbe84257f81a9 | MIT                                                    | Python/SQLite、规则式命令、MCP 工具和 RAG           |

逐项目证据、许可判断及局限见[源码审查](open-source-review.md)。

## 技术建议入口

- [六大场景对照](feature-comparison.md)：实际源码能力、共享依赖与最小验收建议。
- [架构推荐](architecture-recommendations.md)：Adopt / Adapt / Defer / Reject 结论、数据和安全设计。
- [Phase 1 实施计划](phase1-implementation-plan.md)：五条并行工作流、依赖边界和第一条垂直切片。

## 赛事来源及待核实事项

截至 2026-10-18 检查：

- [赛事官方网站](https://fintechathon.g-ican.com/)：本次自动读取超时，未能核验具体规则。
- [人工智能赛道报名工作台](https://apply.g-ican.com/)：公开页面可确认其为 2026 深圳国际金融科技大赛的人工智能赛道报名入口，但页面要求登录；报名、组队和作品材料问题引导联系赛事客服。公开登录页没有给出完整规则或日期。

以下均应由团队通过官方渠道核实后再写为事实：赛题任务与强制场景、提交截止时间、答辩/展示材料、团队和作品权属、是否强制开源、代码仓库访问要求、提交后能否公开。不要用往届赛事、其他赛道或项目建议替代本年度规则。既有 docs/competition/ 材料由其他队友负责，本轮没有检查、评价或修改。

## 许可证提醒

仓库保持 Private。公开仓库中的代码可供阅读，不代表有复制和再分发许可。只有根许可证明确授予相应权利的项目才能进入后续依赖/代码复用评审；Kaching 的自定义许可仅授权赛事评审用途。根 LICENSE 缺失时按未授予明确许可处理。无论许可为何，本轮没有复制第三方实现。依赖清单、传递依赖、素材和模型许可仍须在公开前单独审查。

此目录仅交付研究与建议；不会自动变更现有架构、API、Agent、数据或安全契约。
