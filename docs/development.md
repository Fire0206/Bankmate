# 开发指南

## 工具链

- Node.js 24.x（最低要求 `>=22.12.0`），pnpm 11.x
- Python 3.13.x，uv
- Git

Windows、macOS 和 Linux 使用相同的 pnpm、uv 项目配置；以下命令不依赖 Bash 脚本。首次开发无需模型密钥、数据库服务或外部银行账户。

## 安装依赖

在仓库根目录运行：

```powershell
Copy-Item .env.example .env
pnpm install
uv sync --project apps/api
```

macOS/Linux 复制环境文件用 `cp .env.example .env`。

`.env` 是本地开发设置并被 Git 忽略；当前不放任何 API Key 或个人/金融数据。

`pnpm-workspace.yaml` 对 npm 包启用严格的 24 小时最低发布年龄策略，避免新发布版本被自动加入例外。若新依赖被该策略拦截，先等待发布年龄满足策略再安装；不要为方便而扩大例外范围。

## 启动

API：

```powershell
uv run --project apps/api python -m finorch_api
```

Web（另开终端）：

```powershell
pnpm --filter @finorch/web dev
```

Vite 将 `/api` 代理到本地 API。打开终端输出的地址查看占位首页；Swagger UI 位于 `http://127.0.0.1:8000/docs`，健康端点为 `http://127.0.0.1:8000/api/v1/health`。

## 验证命令

```powershell
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api ruff check --config apps/api/pyproject.toml apps/api
uv run --project apps/api ruff format --check --config apps/api/pyproject.toml apps/api
pnpm --filter @finorch/web lint
pnpm --filter @finorch/web typecheck
pnpm --filter @finorch/web build
pnpm run format:check
```

更新 API 类型：`pnpm run api:types`。CI 安装依赖时使用 `pnpm install --frozen-lockfile` 和 `uv sync --project apps/api --locked`。

## 配置说明

环境变量示例见根目录 `.env.example`。API 使用 `FINORCH_` 前缀，默认监听 `127.0.0.1:8000`。不要将本地服务绑定公网地址；当前 API 未实现认证。

## 分支与私有仓库

本地开发和 CI 按私有仓库流程运行。管理员邀请正式团队成员并分配最小权限；管理员需在 GitHub 配置 `main` 分支保护。不得将工作复制到未经批准的公共 fork 或公开 CI Artifact。正式提交前依照[仓库公开检查清单](development/public-release-checklist.md)执行。

## 常见问题

- 若 `pnpm` 未找到，安装/启用 pnpm 11 并重新打开终端。
- 若 Python 版本不符，安装 Python 3.13 后运行 `uv sync --project apps/api`。
- 前端显示 API 未连接时，先确认 API 在 `127.0.0.1:8000` 正在运行，再刷新页面。
- OpenAPI 类型有变化时运行 `pnpm run api:types` 并提交两项生成物。
