"""DJI GEO / FlySafe 公共数据模型、枚举与输入值对象。

提供输入边界框（`BBox`）、上游无损原始结构（`RawArea`、`RawSubArea`）、
规范化空间管控单元（`GeoZone`）及带溯源信息的查询结果（`AirspaceQueryResult`）。
所有公共模型均不可变（`frozen=True`）。
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type LngLat = tuple[float, float]
"""经纬度坐标点元组 `(经度, 纬度)`，十进制度；按行业惯例暂定为未独立校核的 WGS-84。"""

type LinearRing = tuple[LngLat, ...]
"""多边形单个顶点环序列，元素按 `(经度, 纬度)` 排列；多环之间不预设内外洞拓扑关系。"""


class DjiShape(IntEnum):
    """上游空域几何形态枚举。

    对应大疆 FlySafe 前端渲染分派规则，用于区分独立圆形、独立多边形与子区容器。
    """

    CIRCLE = 0
    """独立圆形区域；按上游规则映射，几何由 `lng`、`lat` 与 `radius`（米）确定。"""

    POLYGON = 1
    """独立多边形区域；按上游规则映射，几何由 `polygon_points` 环序列确定。"""

    CONTAINER = 2
    """容器型区域；按上游规则映射，顶层仅作参考包络，实际空间几何须展开 `sub_areas`。"""


class ZoneCategory(StrEnum):
    """规范化空域管控类别。

    由上游管控等级码 `level` 与十六进制颜色 `color` 联合推导，用于消除
    `level=2` 同时承载禁飞区与限高区的歧义，并为未知上游组合提供安全兜底。
    """

    WARNING = "warning"
    """警示区；按上游规则映射自 `level=0` 与 `#FFCC00`（黄色），用于安全提醒。"""

    AUTHORIZATION = "authorization"
    """授权区；按上游规则映射自 `level=1` 与 `#1088F2`（蓝色），设备侧支持账号认证自解禁。"""

    RESTRICTED = "restricted"
    """禁飞区；按上游规则映射自 `level=2` 与 `#DE4329`（红色），设备侧默认禁止起飞。"""

    ALTITUDE = "altitude"
    """限高区；按上游规则映射自 `level=2` 与 `#979797`（灰色），须结合 `height_m` 读取限高。"""

    ENHANCED_WARNING = "enhanced_warning"
    """加强警示区；按上游规则映射自 `level=3` 与 `#EE8815`（橙色），需操作者确认提示。"""

    RECOMMENDED = "recommended"
    """推荐区；按上游规则映射自 `level=5` 与 `#00BE00`（绿色），为推荐飞行区域。"""

    REGULATORY_RESTRICTED = "regulatory_restricted"
    """法规限制区；按上游规则映射自 `level=7` 与 `#37C4DB`（青色），提示当地法规限制。"""

    APPROVED = "approved"
    """适飞/批准区；按上游规则映射自 `level=8` 与 `#00BE00`（绿色），表示特定地区批准区域。"""

    SPECIAL_HEIGHT = "special_height"
    """特殊限高区；按上游规则映射自 `level=10` 与 `#377A26`（深绿）。

    具体高度限制逻辑基于前端配置与样本推断，官方未公开完整语义。
    """

    UNKNOWN = "unknown"
    """未知类别兜底；当上游返回未覆盖的 `(level, color)` 组合时使用，防止新增枚举导致解析中断。"""


class BBox(BaseModel):
    """轴对齐经纬度矩形查询范围（Bounding Box）。

    采用十进制度 WGS-84 坐标假设，要求 `west < east` 且 `south < north`，
    不支持跨越 180° 国际日期变更线的矩形框。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    west: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    south: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    east: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    north: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.south >= self.north:
            raise ValueError("BBox 南纬 south 必须严格小于北纬 north")
        if self.west >= self.east:
            raise ValueError("BBox 西经 west 必须严格小于东经 east（不支持跨 180° 日界线）")
        return self

    @classmethod
    def from_nw_se(
        cls,
        *,
        ltlat: float,
        ltlng: float,
        rblat: float,
        rblng: float,
    ) -> Self:
        """按大疆矩形接口的西北角/东南角参数顺序构造 `BBox`。

        Args:
            ltlat: 西北角（左上）纬度，十进制度。
            ltlng: 西北角（左上）经度，十进制度。
            rblat: 东南角（右下）纬度，十进制度。
            rblng: 东南角（右下）经度，十进制度。

        Returns:
            通过边界校验的 `BBox` 实例。
        """
        return cls(west=ltlng, south=rblat, east=rblng, north=ltlat)


class DroneModel(BaseModel):
    """上游机型目录中的单个大疆机型条目。

    `slug` 为发起空域查询时 `drone` 参数所需的唯一字符串标识（如 `"dji-mini-3"`）。
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    slug: str


class RawSubArea(BaseModel):
    """上游容器型 `RawArea` 下的单条原始子区域记录。

    保持开放世界容错（`extra="ignore"`）并保留上游原始整型码值，
    避免上游静默新增字段或枚举导致反序列化失败。
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    shape: int
    level: int
    color: str
    height: int
    lat: float
    lng: float
    radius: float
    polygon_points: tuple[LinearRing, ...] | None = None


class RawArea(BaseModel):
    """上游空域接口返回的单条顶层原始区域记录。

    无损保留上游原始字段与整型码值（`shape`、`level`、`type`、`data_source`、
    `begin_at`、`end_at`）。`type` 与 `data_source` 的完整码表官方未公开，
    具体含义需以实测样本谨慎解读。
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    area_id: int
    name: str
    type: int
    shape: int
    lat: float
    lng: float
    radius: float
    level: int
    height: int
    color: str
    begin_at: int
    end_at: int
    country: str
    city: str = ""
    address: str = ""
    description: str = ""
    url: str = ""
    data_source: int
    polygon_points: tuple[LinearRing, ...] | None = None
    sub_areas: tuple[RawSubArea, ...] | None = None


class CircleGeometry(BaseModel):
    """规范化圆形空间几何。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["circle"] = "circle"
    center: LngLat
    radius_m: float = Field(gt=0.0, allow_inf_nan=False)


class PolygonGeometry(BaseModel):
    """规范化多环多边形空间几何。

    `rings` 原样保留上游环序列，不预先假设多环之间存在外环/内洞拓扑关系。
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["polygon"] = "polygon"
    rings: tuple[LinearRing, ...] = Field(min_length=1)


type ZoneGeometry = Annotated[
    CircleGeometry | PolygonGeometry,
    Field(discriminator="kind"),
]
"""规范化空域几何的可辨识联合类型，严格限定为圆形或多边形。"""


class GeoZone(BaseModel):
    """规范化后的最小独立空间管控单元。

    由 `RawArea` 与 `RawSubArea` 展开、继承父级元数据并完成类别推导后生成。
    `height_m` 原样保留上游整型高度值（单位米），高度基准（真高/海拔等）官方未公开核实；
    大疆地理围栏仅反映厂商设备侧限制，不等同于民航监管法定空域结论。
    """

    model_config = ConfigDict(frozen=True)

    area_id: int
    part_index: int = Field(ge=1)
    name: str
    country: str
    area_type: int
    data_source: int
    category: ZoneCategory
    level: int
    color: str
    height_m: int
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    geometry: ZoneGeometry

    def is_active_at(self, at: datetime) -> bool:
        """判断该管控单元在指定时刻是否处于有效时间窗口内。

        采用闭区间判定（`effective_from <= at <= effective_until`）；
        若任一端点为 `None`，表示该方向未设时限。

        Args:
            at: 待判定的时间点，必须携带时区信息（timezone-aware）。

        Returns:
            若 `at` 落在有效窗口内返回 `True`，否则返回 `False`。

        Raises:
            ValueError: 当 `at` 不含时区信息（naive datetime）时抛出。
        """
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at 必须为带时区信息的 datetime（timezone-aware）")
        if self.effective_from is not None and at < self.effective_from:
            return False
        return not (self.effective_until is not None and at > self.effective_until)


class AirspaceQueryResult(BaseModel):
    """一次空域查询的不可变返回结果。

    同时提供规范化后的 `zones` 与无损保留的 `raw_areas` 双视图，并附带完整查询溯源信息。
    上游未显式声明坐标参考系，当前以 `assumed_crs="WGS-84"` 与 `crs_verified=False`
    标注暂定假设；结果仅代表厂商设备地理围栏参考，不等同于法定空域或飞行审批结论。
    """

    model_config = ConfigDict(frozen=True)

    source: Literal["dji_geo"] = "dji_geo"
    endpoint: Literal["in_rectangle"] = "in_rectangle"
    drone: str
    request_bbox: BBox
    queried_at: datetime
    assumed_crs: Literal["WGS-84"] = "WGS-84"
    crs_verified: bool = False
    tiles_queried: int = Field(default=1, ge=1)
    echoed_center: LngLat | None = None
    echoed_radius_m: float | None = None
    zones: tuple[GeoZone, ...]
    raw_areas: tuple[RawArea, ...]

    def to_geojson(self, *, circle_segments: int = 64) -> dict[str, Any]:
        """将当前查询结果导出为 RFC 7946 `FeatureCollection` 字典。

        Args:
            circle_segments: 圆形离散近似的分段顶点数，必须大于等于 `3`。

        Returns:
            可直接 JSON 序列化的 GeoJSON `FeatureCollection` 字典。

        Raises:
            ValueError: 当 `circle_segments < 3` 时抛出。
        """
        from dji_geo.geojson import to_geojson

        return to_geojson(self, circle_segments=circle_segments)
