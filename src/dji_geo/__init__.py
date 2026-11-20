"""面向大疆（DJI）FlySafe / GEO 空域地理围栏数据的异步 Python 客户端库。"""

from importlib.metadata import version as _distribution_version

from dji_geo.client import DEFAULT_LEVELS, DjiGeoClient, RetryPolicy
from dji_geo.errors import (
    DjiApiError,
    DjiGeoError,
    DjiProtocolError,
    DjiTransportError,
    InvalidParameterError,
    SearchDistanceExceededError,
)
from dji_geo.geojson import to_geojson
from dji_geo.models import (
    AirspaceQueryResult,
    BBox,
    CircleGeometry,
    DjiShape,
    DroneModel,
    GeoZone,
    LinearRing,
    LngLat,
    PolygonGeometry,
    RawArea,
    RawSubArea,
    ZoneCategory,
    ZoneGeometry,
)

__version__ = _distribution_version("dji-geo")

__all__ = [
    "DEFAULT_LEVELS",
    "AirspaceQueryResult",
    "BBox",
    "CircleGeometry",
    "DjiApiError",
    "DjiGeoClient",
    "DjiGeoError",
    "DjiProtocolError",
    "DjiShape",
    "DjiTransportError",
    "DroneModel",
    "GeoZone",
    "InvalidParameterError",
    "LinearRing",
    "LngLat",
    "PolygonGeometry",
    "RawArea",
    "RawSubArea",
    "RetryPolicy",
    "SearchDistanceExceededError",
    "ZoneCategory",
    "ZoneGeometry",
    "__version__",
    "to_geojson",
]
