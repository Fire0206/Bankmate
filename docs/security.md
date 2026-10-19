# 安全设计

> 当前状态：Phase 1B 已实现本地 Demo Identity、卡片资源归属检查、受控 Agent Tools、持久化 Task/Workflow、服务端一次性确认挑战、幂等和通用审计。未实现生产身份认证、真实银行数据/服务或生产部署。Demo Identity 仅用于本地 development/test，不具备生产级安全性。下文未标为已实现的能力仍是设计约束。

## 权限与风险

- 当前 API 的 actor 由服务端 `FINORCH_DEMO_USER_ID` 配置提供，只在 `development`/`test` 环境启用；生产环境不可用。客户端的 `user_id` 和角色字段不可信，也不作为身份来源。这个本机 Demo 身份不适用于远程共享或真实用户场景。
- 卡片读取在 SQL 查询中按 actor 所属用户范围过滤；不属于 actor 的卡片与不存在卡片统一返回 404。未来 API 在应用边界验证真实身份并做资源级授权；只在后端授予最小权限。
- 工具权限建议分为 `read_only`、`reversible_write`、`high_risk_write`；风险级别为 `low`、`medium`、`high`、`critical`。操作权限和操作风险分别评估。
- 读取类工具仍需要用户/资源授权。写入按风险、可逆性、金额/影响和场景制定服务端策略。
- 当前卡片冻结/解冻均为 `reversible_write`、`medium`，服务端策略要求每次确认。challenge 绑定 actor、card ID、tool 名称/版本、目标状态、规范化参数摘要、卡片版本、policy 版本、幂等键和 5 分钟有效期；参数改变会失效，确认时在 SQLite `BEGIN IMMEDIATE` 写事务中重新授权并校验所有绑定字段。
- 确认消费、Card 状态变更、Task/Step/ToolExecution 结果和 AuditEvent 同事务提交；写入失败时整体回滚。challenge 消费和执行记录受唯一约束及事务锁保护，重复确认不会产生第二次业务副作用。卡片的乐观版本变化会拒绝旧 challenge。
- 卡片写入只能从受控 Tool proposal 与服务端确认 API 到达 `confirm_card_change` Application 用例；没有普通冻结/解冻 API。模型不能设置 actor、权限、目标资源身份、策略等级或绕过确认。
- 额度、余额、交易限制、幂等和合法状态由确定性后端逻辑判定，不能由 LLM 推断。

## Prompt Injection 与模型隔离

- 用户文本、交易描述、检索文档、网页、OCR 和工具返回都视为非可信内容；其中嵌入的指令不可提升权限或更改系统策略。
- Agent 只能使用当前用户允许且服务端注册的工具；每次调用重新执行 schema、权限和风险校验。
- 代码层只接受 `ToolRegistry` 中的工具名，Pydantic 校验 Input/Output；Fake Provider 和 OpenAI-compatible Adapter 都不能自行增删可用工具。OpenAI-compatible 模式把有限用户文本、可信的合成上下文和工具定义发送到配置的模型服务，因此只应与合成数据和管理员信任的 endpoint 一起使用。
- 模型适配器已通过 Mock HTTP 测试；真实 Provider 行为、Prompt Injection 抵抗和外部数据处理尚未在实际模型服务上验证，不得作为安全已验证功能描述。
- 任务恢复接口始终按服务端 actor 过滤；最近任务查询同时要求会话关联 ID，幂等结果查询还绑定 operation 与非创建任务 ID。浏览器保存的会话 ID 和 pending-write 数据仅用于关联/同键重试，不是身份、授权或确认凭证；所有执行仍由服务端校验。
- 不把密钥或系统提示词放入用户可见上下文；工具返回经过长度、格式和敏感数据控制。
- 对越权工具请求、间接提示注入、恶意字段和模型拒绝/幻觉建立对抗测试集。
- 检索到的内容只能作为事实候选并带来源，不能被当作授权或业务规则。

## 审计与隐私

- `audit_events` 为追加式通用事件结构，记录 actor、event type、resource、request/task/tool execution ID、执行 outcome、可选前后状态摘要及 UTC 时间。卡片状态改变时保留 `previous_status`、`new_status`、`resource_version` 等旧卡片字段语义；task/tool/confirmation 事件与业务写入按对应事务追加。
- 审计不保存 API Key、原始敏感 payload 或完整拼装 Prompt。Agent Task 为恢复和展示流程会受限保存用户请求文本；只允许合成演示请求，不要在本地输入真实个人或金融信息。Fake Provider 不发外部网络请求。
- 浏览器 `sessionStorage` 可能短暂保存待核实请求的文本、操作参数和幂等键，以便先查询结果或用同键安全重试；它不是可信存储，数据可被本机用户或页面脚本读取。真实个人/金融信息仍禁止输入。
- 审计日志采用追加式记录；正常业务路径不覆盖历史。仅受限 development/test 的显式 Demo Reset 会清空合成审计数据并重置数据库。保留期限、访问权限和删除义务需在真实业务范围确定后审议。
- 日志和错误响应按最小需要记录；遮蔽账户标识和手机号，永不记录完整卡号、认证材料、访问令牌、API Key 或不必要的 prompt/正文。
- 全部开发、测试、演示金融记录均为合成数据；当前 seed 使用固定 ID 和 `phase1a-v1` 数据集版本，可重复执行。显式 reset 的路径白名单见[数据契约](data-contract.md)。

## 错误、幂等和滥用防护

- 错误体不回显原始请求、模型上下文或敏感值；客户端用稳定错误码处理。
- 写请求使用幂等键并在服务端防重。超时后状态不明时查询结果，不盲目重试。
- 任务 GET 在发现已过期确认时会惰性更新 Workflow 终态并追加过期审计；确认过期不会修改卡片。独立人工安全 Review 尚未完成，自动化测试和作者自查不替代该 Review。
- 后续认证上线时，按端点风险增加速率限制、暴力尝试控制、会话撤销和审计。
- request ID 用于关联请求；不可用作身份或授权凭证。

## 依赖与发布

- 新增依赖前核对维护状态、许可证、传递依赖和漏洞；提交锁文件。
- GitHub Secret 只放在受控 Secret Store，不落入源码、CI 输出、Issue 或构建产物。
- CI 使用最小权限（当前 `contents: read`），不需要部署凭证，不执行发布或部署。
- 仓库公开前执行 [发布检查清单](development/public-release-checklist.md)。漏洞报告渠道需由管理员配置。
