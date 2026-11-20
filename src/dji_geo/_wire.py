"""上游 flysafe-api 线协议参数组装、信封校验与错误映射（内部模块）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from dji_geo.errors import (
    DjiApiError,
    DjiProtocolError,
    InvalidParameterError,
    SearchDistanceExceededError,
)
from dji_geo.models import BBox, DroneModel, LngLat, RawArea

if TYPE_CHECKING:
    from collections.abc import Collection

    import httpx2

IN_RECTANGLE_PATH = "/api/qep/geo/feedback/areas/in_rectangle"
IN_RECTANGLE_ENDPOINT = "in_rectangle"
DRONES_PATH = "/dji/drones"
DRONES_ENDPOINT = "drones"
ZONES_MODE = "flysafe_website"


@dataclass(frozen=True, slots=True)
class ParsedRectanglePayload:
    """解析后的单次矩形查询响应载体。"""

    raw_areas: tuple[RawArea, ...]
    echoed_center: LngLat | None
    echoed_radius_m: float | None


class _InRectangleData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    areas: tuple[RawArea, ...]
    lat: float | None = None
    lng: float | None = None
    radius: float | None = None


class _DronesEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    drones: tuple[DroneModel, ...]


def build_in_rectangle_params(
    bbox: BBox,
    *,
    drone: str,
    levels: Collection[int],
) -> dict[str, str | float]:
    """将输入边界框与查询条件转换为 `in_rectangle` 查询参数字典。"""
    return {
        "ltlat": bbox.north,
        "ltlng": bbox.west,
        "rblat": bbox.south,
        "rblng": bbox.east,
        "drone": drone,
        "zones_mode": ZONES_MODE,
        "level": ",".join(str(level) for level in levels),
    }


def decode_json_object(response: httpx2.Response, *, endpoint: str) -> dict[str, object]:
    """校验 HTTP 状态与 JSON 响应头，并将响应体解码为顶层 JSON 对象。"""
    status_code = response.status_code
    if 300 <= status_code < 400:
        location = response.headers.get("location", "")
        raise DjiProtocolError(
            f"上游返回非预期重定向 HTTP {status_code} (Location={location!r})",
            endpoint=endpoint,
            status_code=status_code,
        )
    if status_code != 200:
        raise DjiProtocolError(
            f"上游返回非预期 HTTP 状态码 {status_code}",
            endpoint=endpoint,
            status_code=status_code,
        )

    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise DjiProtocolError(
            f"上游响应 Content-Type 非 JSON: {content_type!r}",
            endpoint=endpoint,
            status_code=status_code,
        )

    try:
        raw: object = response.json()
    except ValueError as exc:
        raise DjiProtocolError(
            "上游响应正文不是合法 JSON",
            endpoint=endpoint,
            status_code=status_code,
        ) from exc

    if not isinstance(raw, dict):
        raise DjiProtocolError(
            f"上游响应 JSON 顶层不是对象，实际为 {type(raw).__name__}",
            endpoint=endpoint,
            status_code=status_code,
        )
    return cast("dict[str, object]", raw)


def _extract_flysafe_error_text(payload: dict[str, object]) -> str:
    """从 flysafe-api 错误信封提取可读错误消息（兼容中英文字典与字符串 data）。"""
    parts: list[str] = []
    message_obj = payload.get("message")
    if isinstance(message_obj, dict):
        msg_dict = cast("dict[str, object]", message_obj)
        english = msg_dict.get("english")
        chinese = msg_dict.get("chinese")
        if isinstance(english, str) and english.strip():
            parts.append(english.strip())
        if isinstance(chinese, str) and chinese.strip() and chinese.strip() not in parts:
            parts.append(chinese.strip())
    elif isinstance(message_obj, str) and message_obj.strip():
        parts.append(message_obj.strip())

    data_obj = payload.get("data")
    if isinstance(data_obj, str) and data_obj.strip():
        parts.append(data_obj.strip())

    return ": ".join(parts) if parts else "上游返回业务错误"


def parse_in_rectangle_response(response: httpx2.Response) -> ParsedRectanglePayload:
    """校验并解析 `in_rectangle` 接口响应，精准区分协议错与 HTTP 200 业务错。"""
    payload = decode_json_object(response, endpoint=IN_RECTANGLE_ENDPOINT)

    code = payload.get("code")
    # bool 是 int 子类，需显式排除以防止把 JSON true/false 误当作业务码。
    if not isinstance(code, int) or isinstance(code, bool):
        raise DjiProtocolError(
            f"上游响应缺少合法整型 code 字段: {code!r}",
            endpoint=IN_RECTANGLE_ENDPOINT,
            status_code=response.status_code,
        )

    data = payload.get("data")
    if code != 0:
        error_text = _extract_flysafe_error_text(payload)
        lower_text = error_text.lower()
        if code == 1 and ("search distance" in lower_text or "1000 km" in lower_text):
            raise SearchDistanceExceededError(
                error_text,
                code=code,
                endpoint=IN_RECTANGLE_ENDPOINT,
            )
        if "parameter" in lower_text or "invalid" in lower_text:
            raise InvalidParameterError(
                error_text,
                code=code,
                endpoint=IN_RECTANGLE_ENDPOINT,
            )
        raise DjiApiError(
            error_text,
            code=code,
            endpoint=IN_RECTANGLE_ENDPOINT,
        )

    if not isinstance(data, dict):
        raise DjiProtocolError(
            f"上游响应 data 字段结构异常，期望对象实际为 {type(data).__name__}",
            endpoint=IN_RECTANGLE_ENDPOINT,
            status_code=response.status_code,
        )

    try:
        parsed_data = _InRectangleData.model_validate(data)
    except ValidationError as exc:
        raise DjiProtocolError(
            f"上游响应数据结构校验失败: {exc.error_count()} 处错误",
            endpoint=IN_RECTANGLE_ENDPOINT,
            status_code=response.status_code,
        ) from exc

    echoed_center: LngLat | None = None
    if parsed_data.lng is not None and parsed_data.lat is not None:
        echoed_center = (parsed_data.lng, parsed_data.lat)

    return ParsedRectanglePayload(
        raw_areas=parsed_data.areas,
        echoed_center=echoed_center,
        echoed_radius_m=parsed_data.radius,
    )


def parse_drones_response(response: httpx2.Response) -> tuple[DroneModel, ...]:
    """校验并解析 `/dji/drones` 机型目录响应信封。"""
    payload = decode_json_object(response, endpoint=DRONES_ENDPOINT)

    status = payload.get("status")
    # bool 是 int 子类，需显式排除以防止将布尔值误判为成功状态码 0。
    if not isinstance(status, int) or isinstance(status, bool):
        raise DjiProtocolError(
            f"机型目录响应缺少合法整型 status 字段: {status!r}",
            endpoint=DRONES_ENDPOINT,
            status_code=response.status_code,
        )

    if status != 0:
        detail = _extract_flysafe_error_text(payload)
        raise DjiApiError(
            detail,
            code=status,
            endpoint=DRONES_ENDPOINT,
        )

    if not isinstance(payload.get("drones"), list):
        raise DjiProtocolError(
            "机型目录响应缺少列表类型的 drones 字段",
            endpoint=DRONES_ENDPOINT,
            status_code=response.status_code,
        )

    try:
        parsed = _DronesEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise DjiProtocolError(
            f"机型目录响应数据结构校验失败: {exc.error_count()} 处错误",
            endpoint=DRONES_ENDPOINT,
            status_code=response.status_code,
        ) from exc

    return parsed.drones
