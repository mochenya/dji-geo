"""机型目录并发安全懒缓存、强制刷新与按需校验核心测试。"""

from __future__ import annotations

import asyncio

import httpx2
import pytest

from dji_geo import (
    BBox,
    DjiApiError,
    DjiGeoClient,
    DroneModel,
    InvalidParameterError,
)

_SAMPLE_BBOX = BBox(west=10.0, south=20.0, east=10.6, north=20.5)


async def test_list_drones_concurrent_lazy_cache_and_force_refresh():
    calls = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        assert request.url.path == "/dji/drones"
        calls += 1
        # 让出事件循环以暴露并发首次请求的竞争窗口
        await asyncio.sleep(0)
        if calls == 1:
            return httpx2.Response(
                200,
                json={
                    "status": 0,
                    "drones": [
                        {"name": "DJI Mini 3", "slug": "dji-mini-3", "extra": 1},
                        {"name": "DJI Mini 4K", "slug": "dji-mini-4k"},
                    ],
                },
            )
        return httpx2.Response(
            200,
            json={
                "status": 0,
                "drones": [
                    {"name": "DJI Mini 3", "slug": "dji-mini-3"},
                    {"name": "DJI Air 3S", "slug": "dji-air-3s"},
                ],
            },
        )

    async with DjiGeoClient(transport=httpx2.MockTransport(handler)) as client:
        batch = await asyncio.gather(*(client.list_drones() for _ in range(5)))
        assert calls == 1
        expected_first = (
            DroneModel(name="DJI Mini 3", slug="dji-mini-3"),
            DroneModel(name="DJI Mini 4K", slug="dji-mini-4k"),
        )
        assert all(result == expected_first for result in batch)

        refreshed = await client.list_drones(force_refresh=True)
        assert calls == 2
        assert refreshed == (
            DroneModel(name="DJI Mini 3", slug="dji-mini-3"),
            DroneModel(name="DJI Air 3S", slug="dji-air-3s"),
        )


async def test_validate_drone_flag_controls_catalog_lookup_and_blocks_invalid_slug():
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if request.url.path == "/dji/drones":
            return httpx2.Response(
                200,
                json={
                    "status": 0,
                    "drones": [{"name": "DJI Mini 3", "slug": "dji-mini-3"}],
                },
            )
        return httpx2.Response(
            200,
            json={"code": 0, "message": {"english": "OK"}, "data": {"areas": []}},
        )

    async with DjiGeoClient(transport=httpx2.MockTransport(handler)) as client:
        # 默认 validate_drone=False 不触发 /dji/drones
        await client.query_rectangle(_SAMPLE_BBOX, drone="unverified-slug")
        assert paths == ["/api/qep/geo/feedback/areas/in_rectangle"]

        # 开启 validate_drone=True，非法 slug 直接报错且不发 in_rectangle
        with pytest.raises(InvalidParameterError, match="nonexistent-model"):
            await client.query_rectangle(
                _SAMPLE_BBOX,
                drone="nonexistent-model",
                validate_drone=True,
            )
        assert paths == [
            "/api/qep/geo/feedback/areas/in_rectangle",
            "/dji/drones",
        ]

        # 合法 slug 复用已缓存目录并放行 in_rectangle
        result = await client.query_rectangle(
            _SAMPLE_BBOX,
            drone="dji-mini-3",
            validate_drone=True,
        )
        assert result.drone == "dji-mini-3"
        assert paths == [
            "/api/qep/geo/feedback/areas/in_rectangle",
            "/dji/drones",
            "/api/qep/geo/feedback/areas/in_rectangle",
        ]


async def test_list_drones_nonzero_status_raises_api_error():
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(200, json={"status": 5001, "message": "catalog unavailable"})
    )

    async with DjiGeoClient(transport=transport) as client:
        with pytest.raises(DjiApiError) as exc_info:
            await client.list_drones()

    assert exc_info.value.code == 5001
    assert exc_info.value.endpoint == "drones"
