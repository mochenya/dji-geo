"""DJI GEO / FlySafe 客户端结构化异常层级。

所有库内主动抛出的异常均继承自 `DjiGeoError`，用于清晰区分瞬态传输故障、
协议或结构漂移异常，以及明确的上游或本地参数业务错误。
"""

from __future__ import annotations


class DjiGeoError(Exception):
    """`dji-geo` 所有受控异常的公共基类。"""


class DjiTransportError(DjiGeoError):
    """底层网络传输失败或瞬态 HTTP 故障在重试耗尽后抛出。

    典型触发场景包括连接中断、请求超时，以及持续返回 HTTP `429` 或 `5xx`。
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
        attempts: int | None = None,
    ) -> None:
        """初始化传输异常。

        Args:
            message: 面向调用方的可读错误描述。
            endpoint: 触发失败的接口短名称（如 `"in_rectangle"`）。
            status_code: 若因 HTTP 429/5xx 失败，记录最后一次响应状态码。
            attempts: 已执行的请求总次数（含首次与重试）。
        """
        self.endpoint = endpoint
        self.status_code = status_code
        self.attempts = attempts
        super().__init__(message)


class DjiProtocolError(DjiGeoError):
    """上游响应违反预期 HTTP 或 JSON 协议契约时抛出。

    典型触发场景包括 `3xx` 重定向、非 `200` 且非瞬态的 HTTP 状态码、
    非 JSON `Content-Type`、JSON 解析损坏，以及上游响应结构突变导致校验失败。
    此类错误属于非瞬态契约不匹配，客户端不会自动重试。
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        """初始化协议异常。

        Args:
            message: 面向调用方的可读错误描述。
            endpoint: 触发异常的接口短名称。
            status_code: 上游返回的 HTTP 状态码（如有）。
        """
        self.endpoint = endpoint
        self.status_code = status_code
        super().__init__(message)


class DjiApiError(DjiGeoError):
    """上游在 HTTP 200 下返回明确业务错误，或本地前置参数校验失败时抛出。

    此类错误具有确定性，客户端不会执行退避重试。
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        endpoint: str = "",
    ) -> None:
        """初始化业务异常。

        Args:
            message: 业务错误详情文本。
            code: 上游业务错误码（本地校验失败时为 `None`）。
            endpoint: 关联的接口短名称。
        """
        self.code = code
        self.message = message
        self.endpoint = endpoint
        prefix = f"[{endpoint}] " if endpoint else ""
        code_part = f"(code={code}) " if code is not None else ""
        super().__init__(f"{prefix}{code_part}{message}")


class SearchDistanceExceededError(DjiApiError):
    """查询矩形跨度超过上游单次搜索距离上限（1000 km）时抛出。

    对应 `flysafe-api` 返回 HTTP `200` 且 `code=1`、提示搜索距离超过 1000 km 的场景。
    """


class InvalidParameterError(DjiApiError):
    """请求参数非法或缺失时抛出。

    涵盖本地入参校验（如缺失 `drone`、空 `levels` 集合）、按需机型 slug 校验失败，
    以及上游明确拒绝非法参数的场景。
    """
