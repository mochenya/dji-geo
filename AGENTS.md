# dji-geo

面向大疆（DJI）FlySafe / GEO 空域地理围栏数据的异步 Python 客户端库（Python >= 3.12，`uv` 管理）。

## 文档索引（按需查阅）

- **领域术语表** — [GLOSSARY.md](GLOSSARY.md)：命名模型、字段、测试或任务时查阅，统一使用术语表词汇，避免近义词漂移。
- **架构与边界** — [docs/agents/architecture.md](docs/agents/architecture.md)：新增模块、调整依赖方向、改动公开接口/接缝或评估功能边界前查阅。
- **代码与测试规范** — [docs/agents/coding-standards.md](docs/agents/coding-standards.md)：编写或审查源码、Type Hints、Pydantic 模型、中文 Docstring、枚举注释与核心单测前查阅。
- **开发工作流** — [docs/agents/workflow.md](docs/agents/workflow.md)：规划或执行项目变更、验证与交付时查阅。
- **开发检查与约定** — [docs/agents/development.md](docs/agents/development.md)：运行本地检查、维护文档或编写提交信息时查阅。
- **版本与发布** — [docs/agents/release.md](docs/agents/release.md)：调整版本、构建或发布时查阅。
- **使用文档** — [docs/usage/index.md](docs/usage/index.md)：改动使用方式、公开接口、业务模型或使用边界时查阅。
- **上游协议契约** — [docs/research/flysafe-api-contract.md](docs/research/flysafe-api-contract.md)：核对 `flysafe-api` 参数、响应结构、`(level, color)` 映射与 `shape` 几何约束时查阅。
- **上游异常与边界** — [docs/research/upstream-quirks-and-boundaries.md](docs/research/upstream-quirks-and-boundaries.md)：处理 HTTP 200 业务错、1000 km 切块上限、旧域坑点或核对已知未知与合规红线时查阅。

## 变更验收门禁

任何源码或配置改动完成后，必须全部通过以下命令：

```bash
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
```
