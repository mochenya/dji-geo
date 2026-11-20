"""纯标准库球面跨度估算、BBox 均匀网格切块与确定性去重合并（内部模块）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from dji_geo.models import BBox, RawArea

if TYPE_CHECKING:
    from collections.abc import Sequence

_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """用 Haversine 公式计算两点间的球面大圆距离（千米）。"""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlng = math.radians(lng2 - lng1)
    sin_half_lat = math.sin(dlat / 2.0)
    sin_half_lng = math.sin(dlng / 2.0)
    h = sin_half_lat**2 + math.cos(lat1_r) * math.cos(lat2_r) * (sin_half_lng**2)
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def _east_west_span_km(bbox: BBox) -> float:
    """计算矩形范围内最宽纬线（最靠近赤道）上的东西弧长（千米）。"""
    widest_lat = 0.0 if bbox.south <= 0.0 <= bbox.north else min((bbox.south, bbox.north), key=abs)
    return (
        _EARTH_RADIUS_KM * math.cos(math.radians(widest_lat)) * math.radians(bbox.east - bbox.west)
    )


def bbox_diagonal_km(bbox: BBox) -> float:
    """估算 `BBox` 的对角线球面跨度（千米）。"""
    # 经度跨度超过 180° 时大圆距离会沿日界线抄近路，改用经纬跨度合成避免低估。
    if bbox.east - bbox.west > 180.0:
        ns_km = haversine_km(0.0, bbox.south, 0.0, bbox.north)
        ew_km = _east_west_span_km(bbox)
        return math.hypot(ns_km, ew_km)
    return haversine_km(bbox.west, bbox.south, bbox.east, bbox.north)


def _build_grid_tiles(bbox: BBox, cols: int, rows: int) -> tuple[BBox, ...]:
    """按给定行列数生成无接缝均匀子矩形列表。"""
    # 首尾直接锚定原始边界，避免浮点累加漂移越出原 BBox。
    lng_edges = [
        bbox.west
        if i == 0
        else (bbox.east if i == cols else bbox.west + (bbox.east - bbox.west) * i / cols)
        for i in range(cols + 1)
    ]
    lat_edges = [
        bbox.south
        if j == 0
        else (bbox.north if j == rows else bbox.south + (bbox.north - bbox.south) * j / rows)
        for j in range(rows + 1)
    ]

    tiles: list[BBox] = []
    for row in range(rows):
        south = lat_edges[row]
        north = lat_edges[row + 1]
        for col in range(cols):
            tiles.append(
                BBox(
                    west=lng_edges[col],
                    south=south,
                    east=lng_edges[col + 1],
                    north=north,
                )
            )
    return tuple(tiles)


def _max_tile_diagonal_km(bbox: BBox, cols: int, rows: int) -> float:
    """计算指定网格划分下最大子分片的对角线跨度（千米）。"""
    return max(bbox_diagonal_km(tile) for tile in _build_grid_tiles(bbox, cols, rows))


def split_bbox(bbox: BBox, *, max_tile_diagonal_km: float) -> tuple[BBox, ...]:
    """当 `BBox` 对角线跨度超过阈值时，按最小均匀网格切分为子矩形集合。"""
    if not math.isfinite(max_tile_diagonal_km) or max_tile_diagonal_km <= 0.0:
        raise ValueError("max_tile_diagonal_km 必须为大于 0 的有限数值")

    if bbox_diagonal_km(bbox) <= max_tile_diagonal_km:
        return (bbox,)

    ns_km = haversine_km(0.0, bbox.south, 0.0, bbox.north)
    ew_km = _east_west_span_km(bbox)
    target_side = max_tile_diagonal_km / math.sqrt(2.0)

    cols = max(1, math.ceil(ew_km / target_side))
    rows = max(1, math.ceil(ns_km / target_side))

    while _max_tile_diagonal_km(bbox, cols, rows) > max_tile_diagonal_km:
        if ew_km / cols >= ns_km / rows:
            cols += 1
        else:
            rows += 1

    # 按实际球面跨度回缩冗余维度，减少狭长或边界矩形的不必要分片请求。
    while True:
        shrunk = False
        if cols > 1 and _max_tile_diagonal_km(bbox, cols - 1, rows) <= max_tile_diagonal_km:
            cols -= 1
            shrunk = True
        if rows > 1 and _max_tile_diagonal_km(bbox, cols, rows - 1) <= max_tile_diagonal_km:
            rows -= 1
            shrunk = True
        if not shrunk:
            break

    return _build_grid_tiles(bbox, cols, rows)


def deduplicate_raw_areas(batches: Sequence[Sequence[RawArea]]) -> tuple[RawArea, ...]:
    """按 `area_id` 去重并升序排列，保证多片并发合并的输出完全确定。"""
    by_id: dict[int, RawArea] = {}
    for batch in batches:
        for area in batch:
            by_id.setdefault(area.area_id, area)
    return tuple(by_id[area_id] for area_id in sorted(by_id))
