"""大框自动切块、并发限流、确定性去重与 Fail-fast 核心测试。"""

from __future__ import annotations

import asyncio
import math

import httpx2
import pytest

from dji_geo import (
    BBox,
    DjiGeoClient,
    DjiTransportError,
    RetryPolicy,
    SearchDistanceExceededError,
)


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371.0088
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return 2.0 * r * math.asin(math.sqrt(min(1.0, a)))


def _circle_area(area_id: int, lng: float, lat: float) -> dict[str, object]:
    return {
        "area_id": area_id,
        "name": f"Zone-{area_id}",
        "type": 29,
        "shape": 0,
        "lat": lat,
        "lng": lng,
        "radius": 500,
        "level": 2,
        "height": 0,
        "color": "#DE4329",
        "begin_at": 0,
        "end_at": 0,
        "country": "XX",
        "data_source": 0,
    }


async def test_city_scale_bbox_does_not_tile_and_keeps_echo_metadata():
    # 城市尺度矩形（对角线约 157 km），低于 350 km 阈值
    city_bbox = BBox.from_nw_se(ltlat=31.05, ltlng=10.00, rblat=30.00, rblng=11.10)
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            200,
            json={
                "code": 0,
                "message": {"english": "OK"},
                "data": {
                    "lat": 30.525,
                    "lng": 10.55,
                    "radius": 78600,
                    "areas": [_circle_area(10001, 10.5, 30.5)],
                },
            },
        )

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        max_tile_diagonal_km=350.0,
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = await client.query_rectangle(city_bbox)

    assert calls == 1
    assert result.tiles_queried == 1
    assert result.echoed_center == (10.55, 30.525)
    assert result.echoed_radius_m == 78600.0
    assert [area.area_id for area in result.raw_areas] == [10001]


async def test_province_scale_bbox_auto_tiles_with_concurrency_limit_and_deterministic_dedup():
    # 跨度约 687 km 的大框（类似省级范围）
    large_bbox = BBox.from_nw_se(ltlat=34.5, ltlng=10.0, rblat=30.0, rblng=15.0)
    max_tile_diagonal_km = 350.0
    max_concurrency = 2

    in_flight = 0
    peak_in_flight = 0
    tile_diagonals: list[float] = []
    call_index = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal in_flight, peak_in_flight, call_index
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        my_idx = call_index
        call_index += 1
        try:
            ltlat = float(request.url.params["ltlat"])
            ltlng = float(request.url.params["ltlng"])
            rblat = float(request.url.params["rblat"])
            rblng = float(request.url.params["rblng"])
            tile_diagonals.append(_haversine_km(ltlng, rblat, rblng, ltlat))

            # 故意制造倒序延迟，验证最终结果顺序完全确定
            await asyncio.sleep(0.01 * (4 - (my_idx % 4)))

            # 每个分片返回一个共享重复 ID（100）和一个乱序独立 ID
            unique_id = 500 - my_idx * 10
            return httpx2.Response(
                200,
                json={
                    "code": 0,
                    "message": {"english": "OK"},
                    "data": {
                        "lat": (ltlat + rblat) / 2,
                        "lng": (ltlng + rblng) / 2,
                        "radius": 150000,
                        "areas": [
                            _circle_area(unique_id, ltlng, rblat),
                            _circle_area(100, 12.5, 32.0),
                        ],
                    },
                },
            )
        finally:
            in_flight -= 1

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        max_tile_diagonal_km=max_tile_diagonal_km,
        max_concurrency=max_concurrency,
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = await client.query_rectangle(large_bbox)

    assert result.tiles_queried > 1
    assert len(tile_diagonals) == result.tiles_queried
    assert all(diag <= max_tile_diagonal_km for diag in tile_diagonals)
    assert peak_in_flight <= max_concurrency
    assert result.echoed_center is None
    assert result.echoed_radius_m is None

    raw_ids = [area.area_id for area in result.raw_areas]
    zone_ids = [zone.area_id for zone in result.zones]
    assert raw_ids == sorted(set(raw_ids))
    assert zone_ids == raw_ids
    assert raw_ids.count(100) == 1
    assert len(raw_ids) == result.tiles_queried + 1


async def test_partial_tile_failure_fails_fast_without_partial_result(monkeypatch):
    async def fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    large_bbox = BBox.from_nw_se(ltlat=34.5, ltlng=10.0, rblat=30.0, rblng=15.0)
    seen_tiles: set[tuple[str, str]] = set()
    failing_tile: tuple[str, str] | None = None

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal failing_tile
        key = (request.url.params["ltlat"], request.url.params["ltlng"])
        seen_tiles.add(key)
        if failing_tile is None and len(seen_tiles) == 2:
            failing_tile = key
        if key == failing_tile:
            raise httpx2.ReadTimeout("tile permanently timed out", request=request)
        return httpx2.Response(
            200,
            json={"code": 0, "message": {"english": "OK"}, "data": {"areas": []}},
        )

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        max_tile_diagonal_km=350.0,
        retry=RetryPolicy(max_retries=1, base_delay_s=0.01, max_delay_s=0.02, jitter=False),
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(DjiTransportError):
            await client.query_rectangle(large_bbox)


async def test_auto_tile_false_sends_single_request_and_surfaces_distance_error():
    oversized_bbox = BBox.from_nw_se(ltlat=38.0, ltlng=10.0, rblat=30.0, rblng=18.0)
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            200,
            json={
                "code": 1,
                "message": {"chinese": "请求错误", "english": "Bad Request"},
                "data": "search distance greater than 1000 km",
            },
        )

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(SearchDistanceExceededError):
            await client.query_rectangle(oversized_bbox, auto_tile=False)

    assert calls == 1
