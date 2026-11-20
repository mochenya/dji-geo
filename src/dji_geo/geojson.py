"""零重依赖 RFC 7946 GeoJSON 导出与圆形测地多边形离散化。

纯 Python 标准库实现，不依赖 `shapely` 或 `pyproj`。圆形几何通过球面测地公式
近似离散为闭合多边形，并在要素属性中显式标记近似与未核验 CRS 元数据。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from dji_geo.models import (
    AirspaceQueryResult,
    CircleGeometry,
    GeoZone,
    LinearRing,
)

_EARTH_RADIUS_M = 6_371_008.8


def _format_utc_iso(value: datetime) -> str:
    """将时间对象格式化为 UTC ISO 8601 字符串。"""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _close_ring(ring: LinearRing) -> list[list[float]]:
    """将坐标环转换为 GeoJSON 坐标列表，并为未首尾闭合的环自动补齐闭合点。"""
    coords = [[lng, lat] for lng, lat in ring]
    if coords[0] != coords[-1]:
        coords.append(coords[0].copy())
    return coords


def _approximate_circle_ring(
    *,
    center_lng: float,
    center_lat: float,
    radius_m: float,
    segments: int,
) -> list[list[float]]:
    """按球面测地正向公式将圆形逆时针离散为首尾闭合的 GeoJSON 顶点环。"""
    lat1 = math.radians(center_lat)
    lng1 = math.radians(center_lng)
    delta = radius_m / _EARTH_RADIUS_M

    sin_lat1 = math.sin(lat1)
    cos_lat1 = math.cos(lat1)
    sin_delta = math.sin(delta)
    cos_delta = math.cos(delta)

    ring: list[list[float]] = []
    for idx in range(segments):
        # 遵循 RFC 7946 外环右手定则，从正北起逆时针采样顶点。
        bearing = -2.0 * math.pi * idx / segments
        sin_lat2 = max(
            -1.0,
            min(1.0, sin_lat1 * cos_delta + cos_lat1 * sin_delta * math.cos(bearing)),
        )
        lat2 = math.asin(sin_lat2)
        lng2 = lng1 + math.atan2(
            math.sin(bearing) * sin_delta * cos_lat1,
            cos_delta - sin_lat1 * sin_lat2,
        )
        lng2_deg = ((math.degrees(lng2) + 180.0) % 360.0) - 180.0
        lat2_deg = math.degrees(lat2)
        ring.append([lng2_deg, lat2_deg])

    ring.append(ring[0].copy())
    return ring


def _zone_to_feature(
    zone: GeoZone,
    *,
    crs_verified: bool,
    circle_segments: int,
) -> dict[str, Any]:
    """将单个 `GeoZone` 序列化为 GeoJSON `Feature` 字典。"""
    properties: dict[str, Any] = {
        "name": zone.name,
        "area_id": zone.area_id,
        "part_index": zone.part_index,
        "category": zone.category.value,
        "level": zone.level,
        "color": zone.color,
        "height_m": zone.height_m,
        "effective_from": (
            _format_utc_iso(zone.effective_from) if zone.effective_from is not None else None
        ),
        "effective_until": (
            _format_utc_iso(zone.effective_until) if zone.effective_until is not None else None
        ),
        "area_type": zone.area_type,
        "country": zone.country,
        "crs_verified": crs_verified,
    }

    geometry = zone.geometry
    geojson_geometry: dict[str, Any]
    if isinstance(geometry, CircleGeometry):
        ring = _approximate_circle_ring(
            center_lng=geometry.center[0],
            center_lat=geometry.center[1],
            radius_m=geometry.radius_m,
            segments=circle_segments,
        )
        geojson_geometry = {
            "type": "Polygon",
            "coordinates": [ring],
        }
        properties["center"] = [geometry.center[0], geometry.center[1]]
        properties["radius_m"] = geometry.radius_m
        properties["circle_polygon_approximation"] = True
    else:
        if len(geometry.rings) == 1:
            geojson_geometry = {
                "type": "Polygon",
                "coordinates": [_close_ring(geometry.rings[0])],
            }
        else:
            # 上游前端按环独立渲染，多环输出为 MultiPolygon 以避免误将后续环当作内洞。
            geojson_geometry = {
                "type": "MultiPolygon",
                "coordinates": [[_close_ring(ring)] for ring in geometry.rings],
            }

    return {
        "type": "Feature",
        "id": f"{zone.area_id}-{zone.part_index}",
        "geometry": geojson_geometry,
        "properties": properties,
    }


def to_geojson(
    result: AirspaceQueryResult,
    *,
    circle_segments: int = 64,
) -> dict[str, Any]:
    """将空域查询结果导出为可直接 JSON 序列化的 RFC 7946 `FeatureCollection` 字典。

    单环多边形导出为 `Polygon`；多环多边形导出为 `MultiPolygon`（逐环独立成面，
    不臆断内洞）；未首尾闭合的有效环自动补齐闭合点；圆形经球面测地公式近似为
    闭合 `Polygon` 并显式附加 `circle_polygon_approximation=True`。顶层附带
    `dji_source` 溯源元数据并标明坐标参考系尚未独立校核及仅作厂商设备围栏参考。

    Args:
        result: 空域查询结果对象。
        circle_segments: 圆形离散近似的分段顶点数（不含末尾闭合重复点），必须大于等于 `3`。

    Returns:
        符合 RFC 7946 结构的 `FeatureCollection` 字典。

    Raises:
        ValueError: 当 `circle_segments < 3` 时抛出。
    """
    if isinstance(circle_segments, bool) or circle_segments < 3:
        raise ValueError("circle_segments 必须为大于等于 3 的整数")

    bbox = result.request_bbox
    return {
        "type": "FeatureCollection",
        "dji_source": {
            "drone": result.drone,
            "queried_at_utc": _format_utc_iso(result.queried_at),
            "requested_bbox": [bbox.west, bbox.south, bbox.east, bbox.north],
            "assumed_crs": result.assumed_crs,
            "crs_verified": result.crs_verified,
            "tiles_queried": result.tiles_queried,
            "usage": "DJI GEO device geofence reference",
        },
        "features": [
            _zone_to_feature(
                zone,
                crs_verified=result.crs_verified,
                circle_segments=circle_segments,
            )
            for zone in result.zones
        ],
    }
