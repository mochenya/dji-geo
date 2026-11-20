# 快速开始

## 安装

要求 Python 3.12 或更高版本。从 PyPI 安装：

```bash
pip install dji-geo
```

或在 uv 项目中添加依赖：

```bash
uv add dji-geo
```

发行包名为 `dji-geo`，导入名为 `dji_geo`。源码开发可克隆仓库并在仓库目录执行 `uv sync`。

## 查询区域

以下查询使用示例坐标和机型；实际数据取决于上游与查询时间。

```python
import asyncio

from dji_geo import BBox, DjiGeoClient


async def main() -> None:
    bbox = BBox(west=116.2, south=39.8, east=116.6, north=40.1)
    async with DjiGeoClient(default_drone="dji-mini-3") as client:
        result = await client.query_rectangle(bbox)
        print(f"机型：{result.drone}，区域数：{len(result.zones)}")
        for zone in result.zones:
            print(zone.name, zone.category.value, zone.geometry.kind)


if __name__ == "__main__":
    asyncio.run(main())
```

查询会访问大疆上游服务。客户端支持 `async with` 或显式调用 `await client.aclose()`；注入的外部 `http_client` 由调用方管理。

[查询指南](querying.md) · [业务模型](models.md)
