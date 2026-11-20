"""单次矩形查询端到端、规范化展开、容错与客户端生命周期核心测试。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest

from dji_geo import (
    BBox,
    CircleGeometry,
    DjiGeoClient,
    PolygonGeometry,
    ZoneCategory,
)


def _sample_rectangle_payload() -> dict[str, object]:
    """构造覆盖典型几何与分类分支的合成响应（含限高子区与未知颜色条目）。"""
    return {
        "code": 0,
        "message": {"chinese": "成功", "english": "OK"},
        "data": {
            "country": "XX",
            "lat": 20.25,
            "lng": 10.3,
            "radius": 41000,
            "areas": [
                {
                    "area_id": 10001,
                    "name": "Sample Airport",
                    "type": 10,
                    "shape": 2,
                    "lat": 20.35,
                    "lng": 10.31,
                    "radius": 6000,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "city": "SampleCity",
                    "address": "",
                    "description": "",
                    "url": "",
                    "data_source": 2,
                    "polygon_points": None,
                    "extra_upstream_field": "ignored",
                    "sub_areas": [
                        {
                            "shape": 1,
                            "level": 2,
                            "color": "#DE4329",
                            "height": 0,
                            "lat": 20.32,
                            "lng": 10.28,
                            "radius": 13500,
                            "polygon_points": [
                                [
                                    [10.24, 20.30],
                                    [10.19, 20.22],
                                    [10.26, 20.20],
                                    [10.24, 20.30],
                                ]
                            ],
                        },
                        {
                            "shape": 1,
                            "level": 2,
                            "color": "#979797",
                            "height": 120,
                            "lat": 20.40,
                            "lng": 10.24,
                            "radius": 15000,
                            "polygon_points": [
                                [
                                    [10.41, 20.48],
                                    [10.34, 20.49],
                                    [10.31, 20.44],
                                    [10.41, 20.48],
                                ]
                            ],
                        },
                    ],
                },
                {
                    "area_id": 10002,
                    "name": "Sample Landmark",
                    "type": 43,
                    "shape": 2,
                    "lat": 20.18,
                    "lng": 10.28,
                    "radius": 500,
                    "level": 3,
                    "height": 0,
                    "color": "#EE8815",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "city": "SampleCity",
                    "data_source": 0,
                    "polygon_points": None,
                    "sub_areas": [
                        {
                            "shape": 1,
                            "level": 3,
                            "color": "#ee8815",
                            "height": 0,
                            "lat": 20.18,
                            "lng": 10.28,
                            "radius": 500,
                            "polygon_points": [
                                [
                                    [10.27, 20.17],
                                    [10.29, 20.17],
                                    [10.29, 20.19],
                                    [10.27, 20.19],
                                    [10.27, 20.17],
                                ]
                            ],
                        }
                    ],
                },
                {
                    "area_id": 10003,
                    "name": "Sample Controlled Circle",
                    "type": 29,
                    "shape": 0,
                    "lat": 20.14,
                    "lng": 10.20,
                    "radius": 500,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 1684166400,
                    "end_at": 1861891200,
                    "country": "XX",
                    "data_source": 0,
                    "polygon_points": None,
                    "sub_areas": None,
                },
                {
                    "area_id": 10099,
                    "name": "未知类别测试区",
                    "type": 99,
                    "shape": 0,
                    "lat": 20.20,
                    "lng": 10.25,
                    "radius": 300,
                    "level": 2,
                    "height": 50,
                    "color": "#123456",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                    "polygon_points": None,
                    "sub_areas": None,
                },
            ],
        },
    }


async def test_query_rectangle_end_to_end_and_normalization():
    captured_requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        return httpx2.Response(200, json=_sample_rectangle_payload())

    bbox = BBox.from_nw_se(ltlat=20.5, ltlng=10.0, rblat=20.0, rblng=10.6)
    transport = httpx2.MockTransport(handler)

    async with DjiGeoClient(default_drone="dji-mini-3", transport=transport) as client:
        result = await client.query_rectangle(bbox)

    # 1. 请求 URL 与查询参数准确
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.url.path == "/api/qep/geo/feedback/areas/in_rectangle"
    assert req.url.params["ltlat"] == "20.5"
    assert req.url.params["ltlng"] == "10.0"
    assert req.url.params["rblat"] == "20.0"
    assert req.url.params["rblng"] == "10.6"
    assert req.url.params["drone"] == "dji-mini-3"
    assert req.url.params["zones_mode"] == "flysafe_website"
    assert req.url.params["level"] == "0,1,2,3,4,5,6,7,8,9,10"

    # 2. 溯源与无损原始数据
    assert result.source == "dji_geo"
    assert result.endpoint == "in_rectangle"
    assert result.drone == "dji-mini-3"
    assert result.request_bbox == bbox
    assert result.assumed_crs == "WGS-84"
    assert result.crs_verified is False
    assert result.tiles_queried == 1
    assert result.echoed_center == (10.3, 20.25)
    assert result.echoed_radius_m == 41000.0
    assert len(result.raw_areas) == 4
    assert len(result.zones) == 5

    # 3. 容器子区展开、part_index、继承属性与 (level, color) 分类
    z_airport_1, z_airport_2, z_landmark, z_circle, z_unknown = result.zones

    assert (z_airport_1.area_id, z_airport_1.part_index) == (10001, 1)
    assert z_airport_1.name == "Sample Airport"
    assert z_airport_1.country == "XX"
    assert z_airport_1.area_type == 10
    assert z_airport_1.data_source == 2
    assert z_airport_1.category is ZoneCategory.RESTRICTED
    assert z_airport_1.height_m == 0
    assert isinstance(z_airport_1.geometry, PolygonGeometry)

    assert (z_airport_2.area_id, z_airport_2.part_index) == (10001, 2)
    assert z_airport_2.name == "Sample Airport"
    assert z_airport_2.category is ZoneCategory.ALTITUDE
    assert z_airport_2.height_m == 120
    assert isinstance(z_airport_2.geometry, PolygonGeometry)

    assert (z_landmark.area_id, z_landmark.part_index) == (10002, 1)
    assert z_landmark.category is ZoneCategory.ENHANCED_WARNING

    # 4. 独立圆形几何、UTC 时效转换与 is_active_at
    assert (z_circle.area_id, z_circle.part_index) == (10003, 1)
    assert z_circle.category is ZoneCategory.RESTRICTED
    assert isinstance(z_circle.geometry, CircleGeometry)
    assert z_circle.geometry.center == (10.20, 20.14)
    assert z_circle.geometry.radius_m == 500.0
    assert z_circle.effective_from == datetime(2023, 5, 15, 16, 0, tzinfo=UTC)
    assert z_circle.effective_until == datetime(2028, 12, 31, 16, 0, tzinfo=UTC)

    utc_plus_8 = timezone(timedelta(hours=8))
    assert z_circle.is_active_at(datetime(2026, 11, 20, 9, 0, tzinfo=utc_plus_8)) is True
    assert z_circle.is_active_at(datetime(2023, 5, 15, 23, 59, tzinfo=utc_plus_8)) is False
    assert z_circle.is_active_at(datetime(2029, 1, 1, 0, 1, tzinfo=utc_plus_8)) is False
    with pytest.raises(ValueError, match="timezone-aware"):
        z_circle.is_active_at(datetime(2026, 11, 20, 9, 0))

    # 5. 未设时限（0 哨兵）与未知类别兜底
    assert z_airport_1.effective_from is None
    assert z_airport_1.effective_until is None
    assert z_airport_1.is_active_at(datetime(2020, 1, 1, tzinfo=UTC)) is True
    assert z_unknown.category is ZoneCategory.UNKNOWN


async def test_malformed_and_unknown_geometries_warn_without_failing(caplog):
    payload = {
        "code": 0,
        "message": {"chinese": "成功", "english": "OK"},
        "data": {
            "areas": [
                {
                    "area_id": 1,
                    "name": "空容器",
                    "type": 10,
                    "shape": 2,
                    "lat": 20.2,
                    "lng": 10.2,
                    "radius": 1000,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                    "sub_areas": [],
                },
                {
                    "area_id": 2,
                    "name": "无效半径圆",
                    "type": 29,
                    "shape": 0,
                    "lat": 20.2,
                    "lng": 10.2,
                    "radius": 0,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                },
                {
                    "area_id": 3,
                    "name": "退化多边形",
                    "type": 10,
                    "shape": 1,
                    "lat": 20.2,
                    "lng": 10.2,
                    "radius": 100,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                    "polygon_points": [[[10.2, 20.2], [10.3, 20.2]]],
                },
                {
                    "area_id": 4,
                    "name": "未知形态",
                    "type": 10,
                    "shape": 99,
                    "lat": 20.2,
                    "lng": 10.2,
                    "radius": 100,
                    "level": 2,
                    "height": 0,
                    "color": "#DE4329",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                },
                {
                    "area_id": 5,
                    "name": "合法圆形",
                    "type": 29,
                    "shape": 0,
                    "lat": 20.21,
                    "lng": 10.21,
                    "radius": 250,
                    "level": 1,
                    "height": 0,
                    "color": "#1088F2",
                    "begin_at": 0,
                    "end_at": 0,
                    "country": "XX",
                    "data_source": 0,
                },
            ]
        },
    }
    bbox = BBox(west=10.0, south=20.0, east=10.6, north=20.5)
    transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))

    with caplog.at_level(logging.WARNING, logger="dji_geo"):
        async with DjiGeoClient(default_drone="dji-mini-3", transport=transport) as client:
            result = await client.query_rectangle(bbox)

    assert len(result.raw_areas) == 5
    assert len(result.zones) == 1
    assert result.zones[0].area_id == 5
    assert result.zones[0].category is ZoneCategory.AUTHORIZATION
    assert len(caplog.records) >= 4


async def test_client_lifecycle_and_injected_http_client():
    bbox = BBox(west=10.0, south=20.0, east=10.6, north=20.5)
    empty_payload = {
        "code": 0,
        "message": {"chinese": "成功", "english": "OK"},
        "data": {"areas": []},
    }
    transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=empty_payload))

    # 互斥校验
    async with httpx2.AsyncClient(transport=transport) as external_http:
        with pytest.raises(ValueError, match="互斥"):
            DjiGeoClient(http_client=external_http, transport=transport)

        # 外部注入 http_client 在退出 async with 后不被关闭
        async with DjiGeoClient(default_drone="dji-mini-3", http_client=external_http) as client:
            res = await client.query_rectangle(bbox)
            assert res.zones == ()
        assert external_http.is_closed is False

    # 托管客户端显式关闭后再调用抛 RuntimeError
    managed = DjiGeoClient(default_drone="dji-mini-3", transport=transport)
    res = await managed.query_rectangle(bbox)
    assert res.raw_areas == ()
    await managed.aclose()
    with pytest.raises(RuntimeError, match="已关闭"):
        await managed.query_rectangle(bbox)


@pytest.mark.parametrize(
    ("west", "south", "east", "north"),
    [
        (10.6, 20.0, 10.0, 20.5),
        (10.0, 20.5, 10.6, 20.0),
        (10.0, 20.0, 10.0, 20.5),
    ],
)
def test_bbox_rejects_inverted_or_degenerate_bounds(west, south, east, north):
    with pytest.raises(ValueError):
        BBox(west=west, south=south, east=east, north=north)
