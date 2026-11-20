# 版本、构建与发布

`.github/workflows/publish.yaml` 只通过 Actions → Publish → Run workflow 手动触发，选择 `testpypi` 或 `pypi`（默认 `testpypi`）和要发布的分支。工作流先运行完整检查并构建，再将构建产物交给独立发布任务；发布任务使用同名 GitHub Environment 和 OIDC Trusted Publishing，不使用长期 token。构建使用 `pyproject.toml` 中的版本，不从 Git 标签推导。每次运行会重新构建，因此发布前应检查所选分支、版本和目标；不同运行的产物不承诺字节一致。

使用前须分别在 TestPyPI 和 PyPI 配置 Trusted Publisher，项目名 `dji-geo`、仓库 `mochenya/dji-geo`、工作流文件名 `publish.yaml`，Environment 分别是 `testpypi` 和 `pypi`。项目尚不存在时使用 pending publisher；pending 配置不预留包名。GitHub 仓库 Environment 的保护规则须单独配置。此工作流会实际上传，运行前需按本项目变更审批约定确认。

## 项目版本

`pyproject.toml` 中的 `project.version` 是唯一维护的包版本，使用符合 PEP 440 的版本号；不从 Git 推导，也不在 Python 源码中重复硬编码。`uv.lock` 保存锁定的项目版本，`dji_geo.__version__` 读取已安装的发行包元数据。

```bash
uv version                         # 查看当前版本
uv version --bump patch --dry-run  # 预览修订版本变更
uv version --bump patch            # 更新版本、重新锁定并同步环境
uv lock --check                    # 检查锁文件是否与项目配置一致
uv run python -c 'import dji_geo; print(dji_geo.__version__)'
```

当前 `0.x` 阶段，兼容的问题修复升级修订版本；新增功能或不兼容的公共接口变更升级次版本，后者需要说明迁移方式。发行版本、Git 标签和发布流程留待实际发布时确定；Python 最低版本 `requires-python` 与项目版本分别维护。

## 构建与发布目标

构建不区分 PyPI 与 TestPyPI：`uv build` 通过 Hatchling 生成同一份源码分发包和 wheel，默认输出到 `dist/`。发布前先运行完整验收门禁并检查构建产物和版本，避免上传目录中的旧文件。

```bash
uv lock --check
uv build
```

正式 PyPI 是 uv 的默认发布目标；TestPyPI 使用 `pyproject.toml` 中显式命名的 `testpypi` 索引，不参与普通依赖解析。以下是以当前版本为例的发布命令，实际发布前需检查目标、文件和认证，并获得发布授权：

```bash
# 以 0.1.0 为例；文件名随版本变化
uv publish --index testpypi dist/dji_geo-0.1.0.tar.gz dist/dji_geo-0.1.0-py3-none-any.whl
uv publish dist/dji_geo-0.1.0.tar.gz dist/dji_geo-0.1.0-py3-none-any.whl
```

两个仓库的账号与认证分别配置。本地手动发布可通过 `UV_PUBLISH_TOKEN` 提供对应仓库的 token；未来 GitHub Actions 可配置 Trusted Publishing，无需保存长期 token。不要将凭证写入项目文件。配置发布索引本身不会创建仓库项目、预留名称或上传文件。
