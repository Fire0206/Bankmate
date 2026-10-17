# ADR-0002：FastAPI OpenAPI 是前后端 API 契约的单一事实来源

- 状态：Accepted
- 日期：2026-10-17
- 决策人：FinOrch 项目团队（待团队成员确认）

## 背景

前后端由不同语言和成员实现，分别维护接口类型容易产生偏差。

## 决策

API 请求/响应模型由 FastAPI/Pydantic 声明，生成 OpenAPI JSON；Web 类型使用 `openapi-typescript` 生成。契约变更需同步提交 OpenAPI 快照、生成类型、测试和文档。CI 重新生成并检查快照是否漂移。人工不得编辑生成物。

## 备选方案

- 前端手写接口类型：有重复事实来源和漂移风险，故不选。
- 独立维护 OpenAPI YAML：会与 FastAPI 的实际验证模型形成双重来源，故不选。

## 影响

Python API Schema 是唯一手工维护的类型来源。生成步骤需要 Python 和 pnpm 工具链；客户端生成文件只作为编译输入，不作为契约定义。
