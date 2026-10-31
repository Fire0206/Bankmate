# BankMate

BankMate 是一款面向个人金融场景的银行业务助手。用户可以用日常语言查询收支、管理银行卡和订阅、办理转账与理财，并在同一项事务中安排多步操作。涉及资金或账户状态变化时，页面会先展示具体内容，用户确认后再更新账户记录。

## 功能

- **转账**：按收款人办理转账，安排定时转账，创建 AA 分账并查看记录。
- **账单**：查看月度和年度收支、分类统计、交易明细及需要核对的记录。
- **理财**：查看产品、完成风险评估、申购或赎回并查看持仓。
- **银行卡**：申请、冻结、解冻、挂失、补卡及调整交易限额。
- **订阅**：查看周期扣费和续费时间，暂停、恢复或取消自动续费。
- **跨场景办理**：联动处理可疑扣款、规划发薪日资金，以及生日预算和预约安排。

账户、交易和产品使用本地虚拟数据，不连接真实银行、支付网络或商户。

## 本地运行

需要 Node.js 22 以上、pnpm 11、Python 3.13 和 uv。

```powershell
Copy-Item .env.example .env
pnpm install
uv sync --project apps/api
.\scripts\demo.ps1 -Mode reset
```

分别在两个终端启动服务：

```powershell
.\scripts\demo.ps1 -Mode api
```

```powershell
.\scripts\demo.ps1 -Mode web
```

打开 Vite 输出的本地地址即可进入 BankMate。默认使用本地规则处理请求；如需接入兼容模型服务，在本机 `.env` 配置服务地址、模型和密钥。密钥只由 API 读取，不要放入网页配置或提交到仓库。启用外部服务前，请确认发送的数据范围。

## 项目材料

- [作品简介](docs/submission/作品简介.md)
- [系统架构图](docs/submission/系统架构图.md)
- [核心算法说明](docs/submission/核心算法说明.md)
- [安全设计文档](docs/submission/安全设计文档.md)
- [安全自评报告](docs/submission/安全自评报告.md)
- [题目与评审要求对照](docs/submission/题目与评审要求对照.md)

项目参加 [2026 深圳国际金融科技大赛人工智能赛道](https://fintechathon.g-ican.com/)。

## 检查

```powershell
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
uv run --project apps/api pytest apps/api/tests
```

## 许可证

Apache License 2.0，详见 [LICENSE](LICENSE)。
