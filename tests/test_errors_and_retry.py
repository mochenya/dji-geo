"""异常契约、协议清洗与客户端级 Full Jitter 指数退避核心测试。"""

from __future__ import annotations

import asyncio

import httpx2
import pytest

from dji_geo import (
    BBox,
    DjiApiError,
    DjiGeoClient,
    DjiProtocolError,
    DjiTransportError,
    InvalidParameterError,
    RetryPolicy,
    SearchDistanceExceededError,
)

_SAMPLE_BBOX = BBox(west=10.0, south=20.0, east=10.6, north=20.5)
_EMPTY_SUCCESS = {
    "code": 0,
    "message": {"chinese": "成功", "english": "OK"},
    "data": {"areas": []},
}


async def test_transient_failures_recover_within_retry_budget(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx2.ReadTimeout("simulated read timeout", request=request)
        if attempts == 2:
            return httpx2.Response(503, text="Service Unavailable")
        return httpx2.Response(200, json=_EMPTY_SUCCESS)

    policy = RetryPolicy(max_retries=2, base_delay_s=0.5, max_delay_s=4.0, jitter=False)
    async with DjiGeoClient(
        default_drone="dji-mini-3",
        retry=policy,
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = await client.query_rectangle(_SAMPLE_BBOX)

    assert result.raw_areas == ()
    assert attempts == 3
    assert sleeps == [0.5, 1.0]


async def test_transient_failures_exhaust_retries_and_raise_transport_error(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(429, text="Too Many Requests")

    policy = RetryPolicy(max_retries=2, base_delay_s=0.5, max_delay_s=4.0, jitter=True)
    async with DjiGeoClient(
        default_drone="dji-mini-3",
        retry=policy,
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(DjiTransportError) as exc_info:
            await client.query_rectangle(_SAMPLE_BBOX)

    assert attempts == 3
    assert len(sleeps) == 2
    assert 0.0 <= sleeps[0] <= 0.5
    assert 0.0 <= sleeps[1] <= 1.0
    assert exc_info.value.status_code == 429
    assert exc_info.value.attempts == 3


async def test_max_retries_zero_disables_retry(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectTimeout("simulated connect timeout", request=request)

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        retry=RetryPolicy(max_retries=0),
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(DjiTransportError) as exc_info:
            await client.query_rectangle(_SAMPLE_BBOX)

    assert attempts == 1
    assert sleeps == []
    assert exc_info.value.attempts == 1


@pytest.mark.parametrize(
    ("response", "expected_exc", "expected_code"),
    [
        (
            httpx2.Response(
                200,
                json={
                    "code": 1,
                    "message": {"chinese": "请求错误", "english": "Bad Request"},
                    "data": "search distance greater than 1000 km",
                },
            ),
            SearchDistanceExceededError,
            1,
        ),
        (
            httpx2.Response(
                200,
                json={
                    "code": 5,
                    "message": {"chinese": "记录不存在", "english": "Record Not Found"},
                    "data": None,
                },
            ),
            DjiApiError,
            5,
        ),
        (
            httpx2.Response(
                302,
                headers={"location": "http://www.dji.com/cn/404"},
            ),
            DjiProtocolError,
            None,
        ),
        (
            httpx2.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><body>Not JSON</body></html>",
            ),
            DjiProtocolError,
            None,
        ),
        (
            httpx2.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"{broken-json",
            ),
            DjiProtocolError,
            None,
        ),
        (
            httpx2.Response(
                200,
                json={"code": 0, "data": "unexpected string payload"},
            ),
            DjiProtocolError,
            None,
        ),
        (
            httpx2.Response(
                200,
                json={"code": 0, "data": {"country": "CN"}},
            ),
            DjiProtocolError,
            None,
        ),
    ],
)
async def test_non_retryable_protocol_and_api_errors(
    monkeypatch,
    response,
    expected_exc,
    expected_code,
):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return response

    async with DjiGeoClient(
        default_drone="dji-mini-3",
        retry=RetryPolicy(max_retries=2),
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(expected_exc) as exc_info:
            await client.query_rectangle(_SAMPLE_BBOX)

    assert attempts == 1
    assert sleeps == []
    if expected_code is not None:
        assert isinstance(exc_info.value, DjiApiError)
        assert exc_info.value.code == expected_code
        assert exc_info.value.endpoint == "in_rectangle"


@pytest.mark.parametrize(
    ("default_drone", "drone", "levels"),
    [
        (None, None, (0, 1, 2)),
        (None, "   ", (0, 1, 2)),
        ("dji-mini-3", None, ()),
    ],
)
async def test_local_parameter_validation_raises_without_network(default_drone, drone, levels):
    called = False

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal called
        called = True
        return httpx2.Response(200, json=_EMPTY_SUCCESS)

    async with DjiGeoClient(
        default_drone=default_drone,
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(InvalidParameterError):
            await client.query_rectangle(_SAMPLE_BBOX, drone=drone, levels=levels)

    assert called is False
