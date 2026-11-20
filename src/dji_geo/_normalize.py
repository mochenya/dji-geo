"""将上游原始区域记录规范化展开为 `GeoZone`（内部模块）。"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dji_geo.models import (
    CircleGeometry,
    DjiShape,
    GeoZone,
    LinearRing,
    PolygonGeometry,
    RawArea,
    ZoneCategory,
    ZoneGeometry,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_LOGGER = logging.getLogger("dji_geo")

# 颜色在前端与实测样本中存在大小写混用（如 #00be00 / #00BE00），查找前统一转大写。
_CATEGORY_MAP: dict[tuple[int, str], ZoneCategory] = {
    (0, "#FFCC00"): ZoneCategory.WARNING,
    (1, "#1088F2"): ZoneCategory.AUTHORIZATION,
    (2, "#DE4329"): ZoneCategory.RESTRICTED,
    (2, "#979797"): ZoneCategory.ALTITUDE,
    (3, "#EE8815"): ZoneCategory.ENHANCED_WARNING,
    (5, "#00BE00"): ZoneCategory.RECOMMENDED,
    (7, "#37C4DB"): ZoneCategory.REGULATORY_RESTRICTED,
    (8, "#00BE00"): ZoneCategory.APPROVED,
    (10, "#377A26"): ZoneCategory.SPECIAL_HEIGHT,
}


def classify_zone(level: int, color: str) -> ZoneCategory:
    """按 `(level, color.upper())` 联合推导规范化空域类别。"""
    return _CATEGORY_MAP.get((level, color.strip().upper()), ZoneCategory.UNKNOWN)


def _parse_unix_timestamp(value: int) -> datetime | None:
    """将上游 Unix 秒时间戳转为 UTC aware datetime；`<= 0` 哨兵值映射为 `None`。"""
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _is_valid_ring(ring: LinearRing) -> bool:
    """判断单个顶点环是否足以构成闭合多边形（至少 3 个独立顶点）。"""
    if len(ring) < 3:
        return False
    return not (ring[0] == ring[-1] and len(ring) < 4)


def _build_leaf_geometry(
    *,
    area_id: int,
    part_index: int,
    shape: int,
    lng: float,
    lat: float,
    radius: float,
    polygon_points: tuple[LinearRing, ...] | None,
) -> ZoneGeometry | None:
    """从单个非容器节点构建规范化几何；遇到畸形或未知形态时记录告警并返回 `None`。"""
    if shape == DjiShape.CIRCLE:
        if not (math.isfinite(radius) and radius > 0.0) or not (
            math.isfinite(lng) and math.isfinite(lat)
        ):
            _LOGGER.warning(
                "跳过畸形圆形几何: area_id=%s, part_index=%s, lng=%s, lat=%s, radius=%s",
                area_id,
                part_index,
                lng,
                lat,
                radius,
            )
            return None
        return CircleGeometry(center=(lng, lat), radius_m=radius)

    if shape == DjiShape.POLYGON:
        if not polygon_points:
            _LOGGER.warning(
                "跳过缺失顶点的多边形几何: area_id=%s, part_index=%s",
                area_id,
                part_index,
            )
            return None
        valid_rings = tuple(ring for ring in polygon_points if _is_valid_ring(ring))
        if len(valid_rings) < len(polygon_points):
            _LOGGER.warning(
                "忽略多边形中的无效环: area_id=%s, part_index=%s, valid=%s, total=%s",
                area_id,
                part_index,
                len(valid_rings),
                len(polygon_points),
            )
        if not valid_rings:
            return None
        return PolygonGeometry(rings=valid_rings)

    _LOGGER.warning(
        "跳过未知或非叶子几何形态: area_id=%s, part_index=%s, shape=%s",
        area_id,
        part_index,
        shape,
    )
    return None


def normalize_raw_areas(raw_areas: Sequence[RawArea]) -> tuple[GeoZone, ...]:
    """将上游 `RawArea` 序列展开并规范化为不可变 `GeoZone` 元组。

    容器型记录（`shape=2`）会展开其 `sub_areas`，子区继承父区基础元数据并以自身
    `level`/`color`/`height` 为准；单条畸形或未知几何记录仅告警跳过，不中断整次查询。
    """
    zones: list[GeoZone] = []

    for area in raw_areas:
        effective_from = _parse_unix_timestamp(area.begin_at)
        effective_until = _parse_unix_timestamp(area.end_at)

        if area.shape == DjiShape.CONTAINER:
            if not area.sub_areas:
                _LOGGER.warning("跳过空子区容器记录: area_id=%s", area.area_id)
                continue
            for part_index, sub in enumerate(area.sub_areas, start=1):
                geometry = _build_leaf_geometry(
                    area_id=area.area_id,
                    part_index=part_index,
                    shape=sub.shape,
                    lng=sub.lng,
                    lat=sub.lat,
                    radius=sub.radius,
                    polygon_points=sub.polygon_points,
                )
                if geometry is None:
                    continue
                zones.append(
                    GeoZone(
                        area_id=area.area_id,
                        part_index=part_index,
                        name=area.name,
                        country=area.country,
                        area_type=area.type,
                        data_source=area.data_source,
                        category=classify_zone(sub.level, sub.color),
                        level=sub.level,
                        color=sub.color,
                        height_m=sub.height,
                        effective_from=effective_from,
                        effective_until=effective_until,
                        geometry=geometry,
                    )
                )
            continue

        geometry = _build_leaf_geometry(
            area_id=area.area_id,
            part_index=1,
            shape=area.shape,
            lng=area.lng,
            lat=area.lat,
            radius=area.radius,
            polygon_points=area.polygon_points,
        )
        if geometry is None:
            continue

        zones.append(
            GeoZone(
                area_id=area.area_id,
                part_index=1,
                name=area.name,
                country=area.country,
                area_type=area.type,
                data_source=area.data_source,
                category=classify_zone(area.level, area.color),
                level=area.level,
                color=area.color,
                height_m=area.height,
                effective_from=effective_from,
                effective_until=effective_until,
                geometry=geometry,
            )
        )

    return tuple(zones)
