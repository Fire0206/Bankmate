<p align="center">
  <img src="apps/web/public/logo-mark.svg" alt="BankMate 标志" width="84" />
</p>

<h1 align="center">BankMate</h1>

<p align="center">
  LEDGER · 用日常语言管理账户、账单与资金安排
</p>

<p align="center">
  React · TypeScript · FastAPI · SQLite
</p>

<p align="center">
  <a href="#产品能力">产品能力</a> ·
  <a href="#操作如何完成">操作流程</a> ·
  <a href="#本地运行">本地运行</a> ·
  <a href="#项目资料">项目资料</a>
</p>

BankMate 将账户查询和常见银行事务放在同一处。用户可以查看资金情况、提出办理需求、核对操作影响，并从页面查看服务端返回的处理结果。

## 产品能力

| 场景           | 可以办理的事情                                       |
| -------------- | ---------------------------------------------------- |
| **账单分析**   | 查看收支、分类、年度账单和需要核对的交易。           |
| **银行卡**     | 申请、冻结或解冻、挂失补卡，并管理交易限额与限制。   |
| **转账**       | 管理收款人，办理转账、预约转账和 AA 分账。           |
| **订阅代扣**   | 查看周期扣费与续费时间，暂停、恢复或取消代扣。       |
| **理财**       | 了解产品与风险等级，查看持仓并办理模拟申购或赎回。   |
| **跨场景办理** | 将账单、订阅、银行卡、账户和理财信息组合成连续任务。 |

## 操作如何完成

**提出需求 → 查看方案 → 确认操作 → 查看结果**

- 查询前校验当前身份与数据归属。
- 资金或账户状态变更会先呈现操作对象和影响，再由用户确认。
- 高风险操作按服务端策略进行额外验证；业务结果和操作记录以服务端返回为准。

### 系统结构

<p align="center">
  <img src="docs/submission/assets/system-architecture.svg" alt="BankMate 系统结构和操作权限" width="920" />
</p>

## 准备演示数据

仓库提供一组固定的合成数据，覆盖账户总览、银行卡、账单、订阅、转账、AA 分账和理财页面。每次重置都会重新生成相同的展示记录，方便录制时从一致的起点开始。

视频数据保存在独立的 `.data/bankmate-showcase.db`，不会覆盖普通开发库 `.data/bankmate.db`。Windows 在仓库根目录运行：

```powershell
.\scripts\demo.ps1 -Mode reset -DataProfile video -Showcase
```

macOS / Linux：

```bash
mkdir -p .data
export BANKMATE_ENVIRONMENT=development
export BANKMATE_DATABASE_URL=sqlite:///./.data/bankmate-showcase.db
export BANKMATE_DEMO_NOW=2026-10-28T12:00:00+00:00
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api python -m bankmate_api.reset --confirm --showcase
```

重置只允许写入专用展示数据库。每次重置会恢复同一组合成记录，便于从固定起点录制。

## 本地运行

默认规则模式不需要 API Key，也不调用外部模型。支持的常用请求由本地规则识别，账户查询和业务变更仍由 BankMate API 校验并写入 SQLite；规则无法确定意图时会请求补充信息。可选的 OpenAI-compatible 模型服务需由 API 在本机 `.env` 配置。

评委可以先试这些请求：

- `我能办理哪些业务？`：查看固定的功能说明，不依赖模型或联网。
- `查询我的账户余额`：读取当前合成账户。
- `我这个月花了多少钱`：查看账单汇总。
- `冻结尾号 1042 的卡`：查看并确认一项银行卡操作。

涉及资金或账户状态变化的请求仍需经过服务端确认；页面显示的是 API 返回的业务结果。

### Windows

需要 Node.js 24、pnpm 11、Python 3.13 和 uv。

```powershell
Copy-Item .env.example .env
pnpm install
uv sync --project apps/api
.\scripts\demo.ps1 -Mode reset
```

分别在两个终端启动：

```powershell
.\scripts\demo.ps1 -Mode api
```

录制视频时，API 使用展示数据库启动：

```powershell
.\scripts\demo.ps1 -Mode api -DataProfile video
```

默认 `rules` 模式可直接进行常用查询和模拟业务操作，不需要密钥。若另行配置兼容模型服务，可追加 `-Provider openai-compatible`。红色高风险操作所需的本地验证码可在另一个终端通过以下命令生成，再输入页面：

```powershell
.\scripts\demo.ps1 -Mode otp -DataProfile video
```

```powershell
.\scripts\demo.ps1 -Mode web
```

### macOS / Linux

```bash
cp .env.example .env
pnpm install
uv sync --project apps/api
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api python -m bankmate_api.reset --confirm
```

在两个终端分别运行：

```bash
uv run --project apps/api uvicorn --app-dir apps/api/src bankmate_api.main:app --host 127.0.0.1 --port 8000
```

```bash
pnpm --filter @bankmate/web exec vite --host 127.0.0.1
```

运行 API 前保持 `.env` 中的 `BANKMATE_DATABASE_URL` 指向 `.data/bankmate-showcase.db`，并将 `BANKMATE_ENVIRONMENT` 设为 `development`。

## 测试与检查

API 测试使用临时 SQLite 数据库；前端检查、构建和格式验证可分别运行：

```bash
uv run --project apps/api pytest apps/api/tests
pnpm --filter @bankmate/web lint
pnpm --filter @bankmate/web typecheck
pnpm --filter @bankmate/web build
pnpm run format:check
```

提交材料压缩包应包含本 README、源代码、部署启动说明和测试用例。可直接从 Git 跟踪文件生成源码包，不包含 `.env`、`.data`、依赖缓存或构建产物；压缩包上限为 300 MB。

## 项目资料

- [作品简介](docs/submission/作品简介.md)
- [系统架构图](docs/submission/系统架构图.md)
- [核心算法说明](docs/submission/核心算法说明.md)
- [安全设计文档](docs/submission/安全设计文档.md)
- [安全自评报告](docs/submission/安全自评报告.md)
- [题目与评审要求对照](docs/submission/题目与评审要求对照.md)

## 许可证

[Apache License 2.0](LICENSE)
