# 异常与重试

库主动抛出的结构化异常以 `DjiGeoError` 为基类：

| 异常 | 含义 |
| --- | --- |
| `DjiTransportError` | 传输失败，包括瞬态错误重试耗尽；可查看 `endpoint`、`status_code`、`attempts`。 |
| `DjiProtocolError` | HTTP 状态、内容类型、JSON 或响应结构不符合预期；可查看 `endpoint`、`status_code`。 |
| `DjiApiError` | 上游业务错误或本地业务参数错误；可查看 `endpoint`、`code`、`message`。 |
| `InvalidParameterError` | `DjiApiError` 子类，如未指定机型或等级集合为空。 |
| `SearchDistanceExceededError` | `DjiApiError` 子类，上游拒绝过大的单次查询范围。 |

按错误类型处理：

```python
from dji_geo import DjiApiError, DjiTransportError

try:
    result = await client.query_rectangle(bbox)
except DjiTransportError as exc:
    print("传输失败：", exc.endpoint, exc.status_code, exc.attempts)
except DjiApiError as exc:
    print("查询被拒绝：", exc.endpoint, exc.code, exc.message)
```

也可单独处理 `DjiProtocolError`，或通过 `DjiGeoError` 捕获库内结构化异常。构造 `BBox` 等模型时的校验错误和关闭客户端后的 `RuntimeError` 不属于上述异常层级。

## 重试策略

默认仅重试超时、网络错误、HTTP 429 和 5xx，最多重试 2 次（总计最多 3 次尝试），指数退避带随机抖动。业务错误、协议错误和其他 4xx 不自动重试；HTTP 200 也可能包含业务错误。

```python
from dji_geo import DjiGeoClient, RetryPolicy

client = DjiGeoClient(
    default_drone="dji-mini-3",
    retry=RetryPolicy(max_retries=2, base_delay_s=0.5, max_delay_s=8.0),
)
```

手动创建的 `client` 使用完毕后应 `await client.aclose()`，或使用 `async with`。`max_retries=0` 可禁用重试；`jitter=False` 可关闭随机抖动。分片请求任何一项失败会使整次查询失败；单条畸形几何的处理见[业务模型](models.md)。
