# 银序 BankAgent 比赛示范模板

> 状态：Planned / 设计模板。本文档不代表仓库已经实现这些功能；当前工程状态以根目录 README 和 `docs/roadmap.md` 为准。

这是“快速蒸馏档”的第一版正式模板，主叙事已定为：

> 管家前台 + 平台后台

主 Demo 已定为：

> 可疑扣款处置

## 文件结构

- `SKILL.md`：正式模板，包含五个核心原则、六场景矩阵、评分映射、评委问答和反模式。
- `DEMO_SCRIPT.md`：三分钟主 Demo 的逐段台词、屏幕动线和彩排检查。
- `PPT_OUTLINE.md`：10 页答辩 PPT 的标题、画面和讲述重点。
- `SAFETY_TEST_CASES.md`：15 条安全测试用例和记录模板。
- `TEMPLATE_SKELETON.md`：v0.1 历史骨架，保留作为快速档过程记录。
- `references/research/`：微众、Sierra、Rocket Money/Copilot、综合提炼和决策记录。
- `references/slides/`：2026 技术公开课的公开截图，作为本地研究素材。
- `wireframe/`：桌面端线框图、说明和绘制脚本。

## 30 分钟使用顺序

1. 读 `SKILL.md` 的“主叙事”和“五个核心原则”。
2. 用 `DEMO_SCRIPT.md` 排一遍三分钟 Demo。
3. 用 `PPT_OUTLINE.md` 建 10 页 PPT。
4. 用 `SAFETY_TEST_CASES.md` 跑第一批攻击用例。
5. 把模板中的指标占位符换成你们自己的实测值。

## 重要提醒

- 模板里的业务指标是占位符，不要直接引用微众公开课的数据冒充自己的结果。
- 演示只使用模拟银行核心和合成数据。
- 安全结论必须由你们自己的测试记录支撑。
