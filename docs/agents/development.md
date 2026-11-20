# 开发检查与约定

## 本地检查与 CI

### 常用命令（均通过 `uv` 运行）

```bash
# 1. 同步项目与开发依赖
uv sync

# 2. 自动格式化代码（开发完毕必跑）
uv run ruff format .

# 3. 格式化检查（CI / 验收门禁）
uv run ruff format --check .

# 4. 代码 Lint 与导入整理检查（自动修复可用 --fix）
uv run ruff check .

# 5. 静态类型检查（src/ 为 strict，tests/ 为 basic）
uv run pyright

# 6. 运行核心测试套件
uv run pytest

# 7. 运行单个测试文件（迭代期快速反馈）
uv run pytest tests/test_query_rectangle.py -q
```

### 完整验收门禁

每次改动开发完毕后，按以下顺序运行并确认全部退出码为 `0`：

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

提交或最终收口前使用只读格式检查：

```bash
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
```

### GitHub Actions CI

`.github/workflows/ci.yaml` 在推送、拉取请求和手动触发时运行，使用 Ubuntu、Python 3.12 和项目锁文件完成格式、Lint、类型、测试及构建检查。工作流只验证，不上传构建产物或发布到包仓库，也不需要 PyPI 凭证。

工作流文件提交并推送后，可在 GitHub 仓库的 Actions 页面查看运行记录和每一步日志。手动运行使用 Actions → CI → Run workflow；`workflow_dispatch` 需要工作流文件已存在于仓库默认分支。CI 构建结果只用于验证，不作为 GitHub Actions artifact 保存。


## 文档维护

文档面向具备基础知识的开发者，语言简洁，聚焦接口语义和业务边界。README 提供项目、业务模型、简短安装与使用入口；具体调用放在使用文档，避免重复维护完整细节。

功能或行为的重要变更完成前，检查并更新受影响的人读文档（README、`docs/usage/`）及 Agent 内部文档（`docs/agents/`、必要时 `AGENTS.md`）；接口契约、上游边界或术语变化也同步对应研究文档和术语表。只更新受影响内容，并检查导航和示例与实现一致。

## Git 提交信息

提交信息遵循 Conventional Commits，标题格式为 `<type>(<scope>): <中文描述>`，不使用 emoji。`scope` 标识主要涉及的模块或部分，如 `client`、`models`、`docs`；描述简洁说明变更。常用类型包括 `feat`、`fix`、`docs`、`refactor`、`test`、`build` 和 `chore`。

```text
feat(client): 支持矩形范围查询
fix(models): 修正区域类别映射
docs(usage): 补充调用示例
```

需要补充背景、行为变化或验证信息时，标题与正文之间空一行，正文使用中文。存在不兼容变更时可使用 `!` 标记，并在正文的 `BREAKING CHANGE:` 后用中文说明影响和迁移方式。
