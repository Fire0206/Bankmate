# FinOrch Team Codex Skill

仓库内的 `skills/finorch-banking-agent/` 是团队共享的 Codex Skill 包。它把 FinOrch 的产品原则、架构边界、六场景后端实施手册、安全评测和 Demo 规范放在一起，供团队成员在自己的 Codex 中调用。

它不是业务代码，也不会自动改变仓库状态。它读取仓库里的 `AGENTS.md`、契约和当前实现，帮助 Codex 按同一套规则产出 PRD、接口、后端切片、测试和答辩材料。

## Windows 安装

在仓库根目录打开 PowerShell：

```powershell
$skillRoot = if ($env:CODEX_HOME) {
  Join-Path $env:CODEX_HOME "skills"
} else {
  Join-Path $env:USERPROFILE ".codex\skills"
}

New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
Copy-Item -Recurse -Force ".\skills\finorch-banking-agent" $skillRoot
```

## macOS / Linux 安装

在仓库根目录执行：

```bash
skill_root="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skill_root"
cp -R ./skills/finorch-banking-agent "$skill_root/"
```

安装后重启 Codex，或新建一个对话，让 Skill 列表重新加载。然后可以显式调用：

```text
Use $finorch-banking-agent to review the current FinOrch task.
```

也可以直接描述 FinOrch 的 PRD、六场景后端、工具契约、安全评测或答辩任务，Codex 会根据 Skill 描述自动匹配。

## 使用方式

- 产品/范围：要求输出 PRD、场景矩阵和验收标准。
- 后端六场景：要求按 `references/six-scenario-backend.md` 拆工具、API、状态、确认、审计和测试。
- 安全/评测：要求补威胁模型、攻击用例和指标。
- 演示/答辩：要求按 `references/demo.md` 生成脚本、PPT 结构和评委问答。

第一次使用建议先让 Codex 读：

1. `AGENTS.md`
2. `docs/architecture.md`
3. `docs/agent-contract.md`
4. `docs/data-contract.md`
5. `docs/api-contract.md`
6. `docs/security.md`

## 更新

仓库里的 `skills/finorch-banking-agent/` 是团队版本。修改 Skill 时：

1. 在仓库中修改并提交；
2. 重新执行安装命令覆盖本机副本；
3. 新建 Codex 对话验证行为。

不要只改本机 `~/.codex/skills` 里的副本而不回写仓库，否则队友拿不到更新。
