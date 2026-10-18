# Sierra AI：高风险客户 Agent 的安全与运营模式

## 来源范围

- Sierra 官方首页：https://sierra.ai/
- 官方定位：帮助企业构建更自然、更可靠的 AI 客户体验。
- 公开页面展示的产品能力：Ghostwriter、Guardrails、Observability、Monitors、Experiments、Long-horizon planning、Customer context、Outcome optimization、Proactive engagement。

## 核心模式

### 1. Guardrails 是构建时能力，不是事后补丁

Sierra 的 Ghostwriter 从 SOP、转录、白板照片、音频或自然语言目标生成可投产的多语言、多渠道 Agent，并内置 guardrails。

**可迁移原则**：安全规则要和工具定义、任务编排一起设计，不能等 Demo 做完再加“请确认”。

### 2. 全链路可观测

官方页面强调可以看到每一次 Agent 动作：工具调用、知识库查询、延迟等；还有 Supervisor、Decisions、Responses 的推理面板。

**可迁移原则**：Demo 中要有“为什么这么做”的可见面板，而不只是最终回答。

### 3. 主动发现需要人工介入的对话

Monitors 用于主动识别需要额外关注的对话；官方还展示了“为什么对话被转给人工”的分析报表。

**可迁移原则**：人工接管要有可解释的触发原因和可统计的转人工率。

### 4. 长程规划与客户上下文

Long-horizon planning 把复杂目标拆成跨越数天或数月的步骤；Customer context 通过记忆连接对话、系统和触点。

**可迁移原则**：跨场景任务需要持久化状态、下一步计划和用户授权记录。

### 5. 在 guardrails 内优化结果

Outcome optimization 强调在遵守 guardrails 的前提下，个性化决策以提升满意度和业务结果；Proactive engagement 根据现实信号触发 next-best-action 工作流。

**可迁移原则**：商业优化和安全约束不是二选一，展示“在边界内优化”的指标。

### 6. 持续实验与改进

Experiments 支持多变量测试，优化对话设计和 Agent 表现。

**可迁移原则**：模板应包含“评测—发现—修正—再评测”的闭环，而不是一次性演示。

## 可迁移到银行 Agent 的设计

- 风险分级：低风险自动执行，中风险确认，高风险二次确认/冷静期/转人工。
- 权限边界：按用户、账户、金额、收款人、场景和渠道做最小权限校验。
- 可解释动作：每次工具调用都记录输入、依据、结果和影响。
- 人工接管：明确触发条件、交接上下文、处理结果回写。
- 主动服务：工资到账、异常扣款、订阅到期等事件触发，但必须获得授权。

## 局限

- Sierra 主要面向企业客户服务，不是个人银行核心系统。
- 官方首页是产品营销材料，未公开完整的安全评测方法和失败率。
- 其商业模式、渠道集成和运营体系不能直接照搬到比赛项目。
- 不能把“有 guardrails”当成“绝对安全”；仍需自己的攻击用例和评测集。
