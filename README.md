# DJI GEO

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Typed](https://img.shields.io/badge/types-PEP%20561-blue)](src/dji_geo/py.typed)
[![CI](https://github.com/mochenya/dji-geo/actions/workflows/ci.yaml/badge.svg)](https://github.com/mochenya/dji-geo/actions/workflows/ci.yaml)

异步 Python 客户端，用于查询 DJI FlySafe / GEO 设备地理围栏数据，将结果转换为结构化模型或 GeoJSON。

本项目基于对大疆 FlySafe 网站使用的**非公开接口及其响应数据的分析**实现，并非大疆官方 SDK；上游接口和数据结构可能发生变化。

> DJI GEO 是厂商设备侧地理围栏参考，不等同于法定空域或飞行审批结论。

[使用文档](docs/usage/index.md) · [快速开始](docs/usage/quickstart.md) · [业务模型](docs/usage/models.md)

## 功能

- 按经纬度矩形和机型查询地理围栏，获取机型目录。
- 自动拆分较大的查询范围，合并并去重结果。
- 将上游区域及子区域展开为统一的业务模型，并支持导出 GeoJSON。

## 安装

需要 Python **3.12 或更高版本**。源码安装：

```bash
git clone https://github.com/mochenya/dji-geo.git
cd dji-geo
python -m pip install .
```

开发环境可使用 `uv sync`。详见[快速开始](docs/usage/quickstart.md)。

## 简单使用

```python
import asyncio
from dji_geo import BBox, DjiGeoClient


async def main():
    async with DjiGeoClient(default_drone="dji-mini-3") as client:
        result = await client.query_rectangle(BBox(west=116.2, south=39.8, east=116.6, north=40.1))
        for zone in result.zones:
            print(zone.name, zone.category.value)


asyncio.run(main())
```

机型目录与查询参数见[使用文档](docs/usage/index.md)。

## 核心模型

| 模型 | 业务含义 |
| --- | --- |
| `BBox` | 查询使用的经纬度矩形范围。 |
| `DroneModel` | 上游机型目录条目，包含名称和查询标识。 |
| `AirspaceQueryResult` | 一次查询的结果，包含区域与查询溯源信息。 |
| `RawArea` / `RawSubArea` | 按模型解析的上游区域及子区域记录。 |
| `GeoZone` | 规范化后的独立区域，包含类别、限高、有效时间和几何。 |
| `CircleGeometry` / `PolygonGeometry` | 区域的圆形或多边形几何。 |

一个上游区域可能包含多个子区域，因此一个 `RawArea` 可能展开为多个 `GeoZone`。区域类别由上游等级和颜色共同推导。详情见[业务模型](docs/usage/models.md)。

## 使用边界

上游按矩形外接圆检索，结果可能包含矩形外的区域。坐标系暂按 WGS-84 假设、尚未独立核验；高度字段的基准尚未核实。空结果不代表允许飞行。使用、展示或再分发数据前，请自行确认适用条款和授权。

## 文档

从 [使用文档首页](docs/usage/index.md) 开始，查看安装、查询、模型、GeoJSON 和异常处理；上游研究记录见 [接口契约](docs/research/flysafe-api-contract.md)和[已知边界](docs/research/upstream-quirks-and-boundaries.md)。
