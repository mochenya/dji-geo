"""零依赖 GeoJSON 导出、多环语义保护与圆形测地离散近似核心测试。"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from dji_geo import (
    AirspaceQueryResult,
    BBox,
    CircleGeometry,
    GeoZone,
    PolygonGeometry,
    ZoneCategory,
    to_geojson,
)


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6_371_008.8
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return 2.0 * r * math.asin(math.sqrt(min(1.0, a)))


def _sample_result() -> AirspaceQueryResult:
    bbox = BBox(west=10.0, south=20.0, east=10.6, north=20.5)
    unclosed_ring = (
        (10.24, 20.30),
        (10.19, 20.22),
        (10.26, 20.20),
    )
    ring_a = (
        (10.28, 20.18),
        (10.29, 20.18),
        (10.29, 20.19),
        (10.28, 20.18),
    )
    ring_b = (
        (10.30, 20.18),
        (10.31, 20.18),
        (10.31, 20.19),
    )
    zones = (
        GeoZone(
            area_id=10001,
            part_index=1,
            name="Sample Airport",
            country="XX",
            area_type=10,
            data_source=2,
            category=ZoneCategory.RESTRICTED,
            level=2,
            color="#DE4329",
            height_m=0,
            effective_from=None,
            effective_until=None,
            geometry=PolygonGeometry(rings=(unclosed_ring,)),
        ),
        GeoZone(
            area_id=10002,
            part_index=1,
            name="双环多边形示例",
            country="XX",
            area_type=43,
            data_source=0,
            category=ZoneCategory.ENHANCED_WARNING,
            level=3,
            color="#EE8815",
            height_m=120,
            effective_from=None,
            effective_until=None,
            geometry=PolygonGeometry(rings=(ring_a, ring_b)),
        ),
        GeoZone(
            area_id=10003,
            part_index=1,
            name="Sample Controlled Circle",
            country="XX",
            area_type=29,
            data_source=0,
            category=ZoneCategory.RESTRICTED,
            level=2,
            color="#DE4329",
            height_m=0,
            effective_from=datetime(2023, 5, 15, 16, 0, tzinfo=UTC),
            effective_until=datetime(2028, 12, 31, 16, 0, tzinfo=UTC),
            geometry=CircleGeometry(
                center=(10.20, 20.14),
                radius_m=500.0,
            ),
        ),
    )
    return AirspaceQueryResult(
        drone="dji-mini-3",
        request_bbox=bbox,
        queried_at=datetime(2026, 11, 20, 1, 0, tzinfo=UTC),
        tiles_queried=2,
        zones=zones,
        raw_areas=(),
    )


def test_to_geojson_polygons_multipolygon_circle_and_provenance():
    result = _sample_result()
    fc = result.to_geojson(circle_segments=32)

    # 快捷方法与顶层纯函数等价，且可直接序列化为 JSON
    assert fc == to_geojson(result, circle_segments=32)
    serialized = json.dumps(fc, ensure_ascii=False)
    assert isinstance(serialized, str)

    # 顶层 FeatureCollection 与 dji_source 溯源元数据
    assert fc["type"] == "FeatureCollection"
    assert fc["dji_source"] == {
        "drone": "dji-mini-3",
        "queried_at_utc": "2026-11-20T01:00:00+00:00",
        "requested_bbox": [10.0, 20.0, 10.6, 20.5],
        "assumed_crs": "WGS-84",
        "crs_verified": False,
        "tiles_queried": 2,
        "usage": "DJI GEO device geofence reference",
    }

    f_single, f_multi, f_circle = fc["features"]

    # 1. 单环未闭合多边形 -> 自动闭合的 Polygon
    assert f_single["id"] == "10001-1"
    assert f_single["geometry"]["type"] == "Polygon"
    single_ring = f_single["geometry"]["coordinates"][0]
    assert len(single_ring) == 4
    assert single_ring[0] == single_ring[-1]
    assert f_single["properties"] == {
        "name": "Sample Airport",
        "area_id": 10001,
        "part_index": 1,
        "category": "restricted",
        "level": 2,
        "color": "#DE4329",
        "height_m": 0,
        "effective_from": None,
        "effective_until": None,
        "area_type": 10,
        "country": "XX",
        "crs_verified": False,
    }

    # 2. 多环多边形 -> MultiPolygon，每环独立成面（非内洞）且各自首尾闭合
    assert f_multi["id"] == "10002-1"
    assert f_multi["geometry"]["type"] == "MultiPolygon"
    polygons = f_multi["geometry"]["coordinates"]
    assert len(polygons) == 2
    assert len(polygons[0]) == 1 and polygons[0][0][0] == polygons[0][0][-1]
    assert len(polygons[1]) == 1 and len(polygons[1][0]) == 4
    assert polygons[1][0][0] == polygons[1][0][-1]

    # 3. 圆形 -> 球面测地近似闭合 Polygon + 显式近似标记
    assert f_circle["id"] == "10003-1"
    assert f_circle["geometry"]["type"] == "Polygon"
    circle_ring = f_circle["geometry"]["coordinates"][0]
    assert len(circle_ring) == 33
    assert circle_ring[0] == circle_ring[-1]

    center_lng, center_lat = 10.20, 20.14
    for lng, lat in circle_ring[:-1]:
        dist_m = _haversine_m(center_lng, center_lat, lng, lat)
        assert abs(dist_m - 500.0) < 0.01

    props = f_circle["properties"]
    assert props["circle_polygon_approximation"] is True
    assert props["center"] == [center_lng, center_lat]
    assert props["radius_m"] == 500.0
    assert props["crs_verified"] is False
    assert props["effective_from"] == "2023-05-15T16:00:00+00:00"
    assert props["effective_until"] == "2028-12-31T16:00:00+00:00"


@pytest.mark.parametrize("segments", [0, 1, 2, -5, False, True])
def test_to_geojson_rejects_invalid_circle_segments(segments):
    result = _sample_result()
    with pytest.raises(ValueError, match="circle_segments"):
        to_geojson(result, circle_segments=segments)
