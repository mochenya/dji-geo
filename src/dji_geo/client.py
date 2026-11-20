"""DJI GEO / FlySafe 异步客户端入口与并发、退避、缓存编排。"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

import httpx2
from pydantic import BaseModel, ConfigDict, Field, model_validator

from dji_geo._normalize import normalize_raw_areas
from dji_geo._tiling import deduplicate_raw_areas, split_bbox
from dji_geo._wire import (
    DRONES_ENDPOINT,
    DRONES_PATH,
    IN_RECTANGLE_ENDPOINT,
    IN_RECTANGLE_PATH,
    ParsedRectanglePayload,
    build_in_rectangle_params,
    parse_drones_response,
    parse_in_rectangle_response,
)
from dji_geo.errors import DjiGeoError, DjiTransportError, InvalidParameterError
from dji_geo.models import AirspaceQueryResult, BBox, DroneModel, LngLat, RawArea

if TYPE_CHECKING:
    from collections.abc import Collection

DEFAULT_BASE_URL = "https://flysafe-api.dji.com"
"""大疆现行 FlySafe API 默认基础地址。"""

DEFAULT_LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
"""默认查询的 GEO 管控等级集合，覆盖现行官网前端使用的 `0..10` 全部等级。"""


def _extract_first_dji_error(exc_group: ExceptionGroup[Exception]) -> DjiGeoError | None:
    """从并发任务异常组中深度优先提取首个 `DjiGeoError`，避免向调用方泄露包装细节。"""
    matched = exc_group.subgroup(DjiGeoError)
    if matched is None:
        return None
    current: DjiGeoError | ExceptionGroup[DjiGeoError] = matched
    while isinstance(current, ExceptionGroup):
        current = current.exceptions[0]
    return current


class RetryPolicy(BaseModel):
    """客户端级瞬态故障重试与 Full Jitter 指数退避策略。

    仅作用于幂等 `GET` 请求的瞬态故障（超时、网络错误、HTTP `429` 与 `5xx`）；
    绝不重试业务错误（`DjiApiError`）、协议异常（`DjiProtocolError`）或其他 `4xx`。
    将 `max_retries` 设为 `0` 可完全关闭自动重试。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_retries: int = Field(default=2, ge=0)
    base_delay_s: float = Field(default=0.5, gt=0.0, allow_inf_nan=False)
    max_delay_s: float = Field(default=8.0, gt=0.0, allow_inf_nan=False)
    jitter: bool = True

    @model_validator(mode="after")
    def _validate_delay_bounds(self) -> Self:
        if self.max_delay_s < self.base_delay_s:
            raise ValueError("max_delay_s 不能小于 base_delay_s")
        return self

    def compute_delay(self, retry_index: int) -> float:
        """计算第 `retry_index` 次重试（从 `0` 开始）前的退避等待秒数。

        Args:
            retry_index: 非负重试序号（首次重试为 `0`）。

        Returns:
            本次应休眠的秒数；开启 `jitter` 时采用 `[0, cap]` 均匀分布（Full Jitter）。
        """
        cap = min(self.max_delay_s, self.base_delay_s * (2**retry_index))
        if self.jitter:
            return random.uniform(0.0, cap)
        return cap


class DjiGeoClient:
    """面向大疆现行 FlySafe 接口的异步客户端。

    生命周期行为与 `httpx2.AsyncClient` 一致：推荐使用 `async with` 托管连接池，
    也允许直接实例化并在使用结束后显式调用 `await client.aclose()`。
    若通过 `http_client` 注入外部客户端，关闭本实例时不会关闭外部客户端。
    """

    def __init__(
        self,
        *,
        default_drone: str | None = None,
        timeout_s: float = 15.0,
        retry: RetryPolicy | None = None,
        max_tile_diagonal_km: float = 350.0,
        max_concurrency: int = 4,
        http_client: httpx2.AsyncClient | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        """初始化异步客户端实例。

        Args:
            default_drone: 默认机型 slug（如 `"dji-mini-3"`），单次查询未指定 `drone` 时使用。
            timeout_s: 托管模式下单次 HTTP 请求超时秒数，必须大于 `0`。
            retry: 客户端级瞬态重试策略；省略时使用 `RetryPolicy()` 默认值。
            max_tile_diagonal_km: 自动切块单分片最大对角线跨度（千米），默认 `350.0`，
                须大于 `0` 且远低于上游 1000 km 硬上限以兼顾高密度区与超时风险。
            max_concurrency: 多分片并发请求上限，必须大于等于 `1`。
            http_client: 可选的外部 `httpx2.AsyncClient`，与 `transport` 互斥；
                传入后由调用方自行管理其关闭生命周期。
            transport: 可选的自定义 `httpx2.AsyncBaseTransport`（常用于测试注入
                `httpx2.MockTransport`），与 `http_client` 互斥。
            base_url: 上游 FlySafe 服务基础地址。

        Raises:
            ValueError: 当同时传入 `http_client` 与 `transport`，或超时/切块/并发配置非法时抛出。
        """
        if http_client is not None and transport is not None:
            raise ValueError("http_client 与 transport 互斥，不能同时传入")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s 必须为大于 0 的有限数值")
        if not math.isfinite(max_tile_diagonal_km) or max_tile_diagonal_km <= 0:
            raise ValueError("max_tile_diagonal_km 必须为大于 0 的有限数值")
        if max_concurrency < 1:
            raise ValueError("max_concurrency 必须大于等于 1")

        self._default_drone = default_drone
        self._retry = retry if retry is not None else RetryPolicy()
        self._max_tile_diagonal_km = max_tile_diagonal_km
        self._max_concurrency = max_concurrency
        self._base_url = base_url.rstrip("/")
        self._custom_base_url = base_url != DEFAULT_BASE_URL
        self._closed = False
        self._drones_cache: tuple[DroneModel, ...] | None = None
        self._drones_lock = asyncio.Lock()

        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            # 显式禁用自动重定向，防止上游废弃路由静默跳转到 HTML 404 页面。
            self._client = httpx2.AsyncClient(
                base_url=self._base_url,
                timeout=timeout_s,
                transport=transport,
                follow_redirects=False,
            )
            self._owns_client = True

    async def __aenter__(self) -> Self:
        """进入异步上下文管理器并返回当前客户端实例。"""
        self._ensure_open()
        return self

    async def __aexit__(self, *args: object) -> None:
        """退出异步上下文管理器并释放托管资源。"""
        await self.aclose()

    async def aclose(self) -> None:
        """关闭客户端并释放内部托管的 HTTP 连接池。

        可幂等重复调用；若客户端使用外部注入的 `http_client`，不会关闭该外部实例。
        """
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("DjiGeoClient 已关闭，无法继续发起请求")

    def _resolve_url(self, path: str) -> str:
        if self._owns_client:
            return path
        if str(self._client.base_url) and not self._custom_base_url:
            return path
        return f"{self._base_url}{path}"

    async def _get_with_retry(
        self,
        path: str,
        *,
        endpoint: str,
        params: dict[str, str | float] | None = None,
    ) -> httpx2.Response:
        """发起带瞬态重试的 HTTP GET 请求，仅重试超时、网络故障与 HTTP 429/5xx。"""
        total_attempts = self._retry.max_retries + 1
        url = self._resolve_url(path)
        attempt = 0

        while True:
            try:
                # 即使调用方注入了自定义 http_client，单次请求也强制禁止自动重定向。
                response = await self._client.get(
                    url,
                    params=params,
                    follow_redirects=False,
                )
            except (httpx2.TimeoutException, httpx2.NetworkError) as exc:
                if attempt + 1 >= total_attempts:
                    raise DjiTransportError(
                        f"请求 {endpoint} 经 {total_attempts} 次尝试后仍遇瞬态传输故障: {exc}",
                        endpoint=endpoint,
                        attempts=total_attempts,
                    ) from exc
                await asyncio.sleep(self._retry.compute_delay(attempt))
                attempt += 1
                continue
            except httpx2.HTTPError as exc:
                raise DjiTransportError(
                    f"请求 {endpoint} 发生不可重试传输异常: {exc}",
                    endpoint=endpoint,
                    attempts=attempt + 1,
                ) from exc

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt + 1 >= total_attempts:
                    raise DjiTransportError(
                        f"请求 {endpoint} 经 {total_attempts} 次尝试后"
                        f"仍返回 HTTP {response.status_code}",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        attempts=total_attempts,
                    )
                await asyncio.sleep(self._retry.compute_delay(attempt))
                attempt += 1
                continue

            return response

    async def _fetch_rectangle_tile(
        self,
        tile: BBox,
        *,
        drone: str,
        levels: tuple[int, ...],
    ) -> ParsedRectanglePayload:
        params = build_in_rectangle_params(tile, drone=drone, levels=levels)
        response = await self._get_with_retry(
            IN_RECTANGLE_PATH,
            endpoint=IN_RECTANGLE_ENDPOINT,
            params=params,
        )
        return parse_in_rectangle_response(response)

    async def list_drones(
        self,
        *,
        force_refresh: bool = False,
    ) -> tuple[DroneModel, ...]:
        """获取大疆 FlySafe 支持的机型目录并做进程内并发安全懒缓存。

        首次调用时请求上游 `/dji/drones` 并缓存在当前客户端实例内；多个并发首次调用
        通过锁双重检查合并为单次上游请求。

        Args:
            force_refresh: 设为 `True` 时跳过本地缓存，强制重新拉取并刷新缓存。

        Returns:
            不可变的大疆机型条目元组。

        Raises:
            RuntimeError: 客户端已关闭时抛出。
            DjiApiError: 上游返回非零 `status` 业务错误时抛出。
            DjiProtocolError: 上游返回重定向、非 JSON 或数据结构突变时抛出。
            DjiTransportError: 瞬态网络故障、超时或 HTTP 429/5xx 重试耗尽时抛出。
        """
        self._ensure_open()

        if not force_refresh and self._drones_cache is not None:
            return self._drones_cache

        # 双重检查加锁，防止冷启动高并发时重复击穿上游机型目录接口。
        async with self._drones_lock:
            if not force_refresh and self._drones_cache is not None:
                return self._drones_cache
            response = await self._get_with_retry(
                DRONES_PATH,
                endpoint=DRONES_ENDPOINT,
            )
            drones = parse_drones_response(response)
            self._drones_cache = drones
            return drones

    async def query_rectangle(
        self,
        bbox: BBox,
        *,
        drone: str | None = None,
        levels: Collection[int] = DEFAULT_LEVELS,
        auto_tile: bool = True,
        validate_drone: bool = False,
    ) -> AirspaceQueryResult:
        """按经纬度矩形范围查询大疆设备侧地理围栏数据。

        上游按矩形外接圆检索，返回结果可能包含矩形四角之外的少量周边区域，
        客户端不对其执行几何裁剪。当开启 `auto_tile` 且矩形对角线超过
        `max_tile_diagonal_km` 时，自动切分为均匀网格并发拉取、按 `area_id`
        去重升序合并；任一分片经重试后仍失败时整次查询 Fail-fast，绝不返回残缺数据。
        返回数据仅代表大疆设备地理围栏参考，不等同于民航监管部门的法定空域结论。

        Args:
            bbox: 目标查询矩形范围。
            drone: 机型 slug；省略时回退至构造参数 `default_drone`。
            levels: 待查询的 GEO 管控等级集合，默认覆盖 `0..10`。
            auto_tile: 是否在矩形跨度超过 `max_tile_diagonal_km` 时自动切块并发查询；
                设为 `False` 时直接单次请求上游。
            validate_drone: 设为 `True` 时，在发起空域请求前通过 `list_drones()`
                核对 `drone` 是否为合法机型 slug；默认 `False` 以避免额外网络请求。

        Returns:
            包含规范化 `zones`、无损 `raw_areas` 与完整查询溯源信息的 `AirspaceQueryResult`。
            单分片查询保留上游回显的 `echoed_center` 与 `echoed_radius_m`；
            多分片合并时两者置为 `None`。

        Raises:
            RuntimeError: 客户端已关闭时抛出。
            InvalidParameterError: 未提供有效 `drone`、`levels` 为空集合，或开启
                `validate_drone=True` 后目标机型 slug 不存在时抛出。
            SearchDistanceExceededError: 单次查询跨度超过上游 1000 km 限制时抛出。
            DjiApiError: 上游返回其他明确业务错误时抛出。
            DjiProtocolError: 上游返回重定向、非 JSON 或数据结构突变时抛出。
            DjiTransportError: 任一分片遇瞬态网络故障、超时或 HTTP 429/5xx 且重试耗尽时抛出。
        """
        self._ensure_open()

        target_drone = drone if drone is not None else self._default_drone
        if not target_drone or not target_drone.strip():
            raise InvalidParameterError(
                "必须通过参数 drone 或客户端 default_drone 提供有效的机型 slug",
                endpoint=IN_RECTANGLE_ENDPOINT,
            )

        level_tuple = tuple(levels)
        if not level_tuple:
            raise InvalidParameterError(
                "levels 不能为空集合",
                endpoint=IN_RECTANGLE_ENDPOINT,
            )

        if validate_drone:
            drones = await self.list_drones()
            if not any(model.slug == target_drone for model in drones):
                raise InvalidParameterError(
                    f"未知的机型 slug: {target_drone!r}",
                    endpoint=IN_RECTANGLE_ENDPOINT,
                )

        tiles = (
            split_bbox(bbox, max_tile_diagonal_km=self._max_tile_diagonal_km)
            if auto_tile
            else (bbox,)
        )

        echoed_center: LngLat | None
        echoed_radius_m: float | None
        raw_areas: tuple[RawArea, ...]

        if len(tiles) == 1:
            parsed = await self._fetch_rectangle_tile(
                tiles[0],
                drone=target_drone,
                levels=level_tuple,
            )
            raw_areas = parsed.raw_areas
            echoed_center = parsed.echoed_center
            echoed_radius_m = parsed.echoed_radius_m
        else:
            raw_areas = await self._fetch_tiled_areas(
                tiles,
                drone=target_drone,
                levels=level_tuple,
            )
            echoed_center = None
            echoed_radius_m = None

        zones = normalize_raw_areas(raw_areas)

        return AirspaceQueryResult(
            drone=target_drone,
            request_bbox=bbox,
            queried_at=datetime.now(tz=UTC),
            tiles_queried=len(tiles),
            echoed_center=echoed_center,
            echoed_radius_m=echoed_radius_m,
            zones=zones,
            raw_areas=raw_areas,
        )

    async def _fetch_tiled_areas(
        self,
        tiles: tuple[BBox, ...],
        *,
        drone: str,
        levels: tuple[int, ...],
    ) -> tuple[RawArea, ...]:
        """受并发上限控制地拉取全部子分片并确定性去重；任一分片失败立即取消其余分片。"""
        semaphore = asyncio.Semaphore(self._max_concurrency)
        # 按固定分片索引落位，保证去重顺序不受并发返回乱序影响。
        ordered_batches: list[tuple[RawArea, ...]] = [() for _ in tiles]

        async def _run_tile(index: int, tile: BBox) -> None:
            async with semaphore:
                payload = await self._fetch_rectangle_tile(
                    tile,
                    drone=drone,
                    levels=levels,
                )
                ordered_batches[index] = payload.raw_areas

        try:
            async with asyncio.TaskGroup() as tg:
                for idx, tile in enumerate(tiles):
                    tg.create_task(_run_tile(idx, tile))
        except ExceptionGroup as exc_group:
            # 任一分片失败后 TaskGroup 已取消其余在途分片；向上还原首个领域异常。
            first_error = _extract_first_dji_error(exc_group)
            if first_error is not None:
                raise first_error from first_error.__cause__
            raise

        return deduplicate_raw_areas(ordered_batches)
