# 几何与 GeoJSON

`GeoZone.geometry` 为 `CircleGeometry` 或 `PolygonGeometry`：

- 圆形的 `kind` 为 `"circle"`，`center` 是 `(经度, 纬度)`，`radius_m` 是米。
- 多边形的 `kind` 为 `"polygon"`，`rings` 是顶点环集合，每个点为 `(经度, 纬度)`。多个环不预设内外洞关系。

坐标系暂按 WGS-84 假设，尚未独立核验。详细几何规则见[上游协议契约](../research/flysafe-api-contract.md)。

## 导出文件

将查询结果 `result` 导出为 GeoJSON：

```python
import json
from pathlib import Path

geojson = result.to_geojson(circle_segments=64)
Path("zones.geojson").write_text(
    json.dumps(geojson, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

也可使用顶层函数 `to_geojson(result)`。返回值是可 JSON 序列化的 `FeatureCollection` 字典；仅导出规范化 `zones`，并在 `dji_source` 中记录查询与坐标系信息。

单环输出 `Polygon`，多环逐环作为独立面输出 `MultiPolygon`；未闭合的有效环会补闭合。圆形使用球面测地公式近似成多边形并标记近似。`circle_segments` 默认为 64，至少为 3；该操作不验证坐标系或执行坐标转换。
