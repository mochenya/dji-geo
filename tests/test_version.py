"""验证公共版本号与项目配置及安装元数据一致。"""

import tomllib
from importlib.metadata import version
from pathlib import Path

import dji_geo


def test_version_matches_project_and_distribution_metadata():
    project_file = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with project_file.open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]

    assert dji_geo.__version__ == version("dji-geo") == project_version
