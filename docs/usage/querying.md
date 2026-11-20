# 查询指南

## 查找机型

```python
async with DjiGeoClient() as client:
    drones = await client.list_drones()
    for drone in drones:
        print(drone.name, drone.slug)
```

`slug` 是查询时的 `drone` 参数。目录在客户端实例内懒加载并缓存；`await client.list_drones(force_refresh=True)` 可刷新。目录和机型可能随上游变化。

## 查询范围和选项

`BBox(west=..., south=..., east=..., north=...)` 使用十进制度，经度范围为 -180 到 180，纬度范围为 -90 到 90；要求 `west < east`、`south < north`，不支持跨 180° 经线。也可通过 `BBox.from_nw_se(ltlat=..., ltlng=..., rblat=..., rblng=...)` 使用西北角和东南角构造。

```python
result = await client.query_rectangle(
    bbox,
    drone="dji-mini-3",
    levels=(0, 1, 2, 3),
    auto_tile=True,
    validate_drone=True,
)
```

| 参数 | 含义 |
| --- | --- |
| `bbox` | 必填，查询矩形。 |
| `drone` | 机型 slug；省略时使用客户端 `default_drone`，两者都未提供时出错。 |
| `levels` | 非空的上游等级集合；默认 `DEFAULT_LEVELS`，即 0 到 10。 |
| `auto_tile` | 默认 `True`，超过客户端切块阈值时自动切分。 |
| `validate_drone` | 默认 `False`；开启后先使用机型目录校验 slug，可能产生额外请求。 |

上游按矩形外接圆检索，可能返回矩形之外的区域，本库不裁剪结果。自动切块后按 `area_id` 去重并排序；任一分片失败时整次查询失败。关闭自动切块可能触发上游单次查询约 1000 km 的跨度上限。

## 客户端配置

`DjiGeoClient` 的常用构造参数均为关键字参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `default_drone` | `None` | 查询默认机型。 |
| `timeout_s` | `15.0` | 自建 HTTP 客户端的单次请求超时，单位秒。 |
| `retry` | `RetryPolicy()` | 瞬态错误重试策略，见[异常与重试](errors.md)。 |
| `max_tile_diagonal_km` | `350.0` | 自动切块的目标最大对角线跨度，单位千米。 |
| `max_concurrency` | `4` | 切块请求的最大并发数。 |
| `http_client` | `None` | 注入外部 `httpx2.AsyncClient`，调用方负责关闭及其超时配置。 |
| `transport` | `None` | 注入 `httpx2.AsyncBaseTransport`，可用于测试；与 `http_client` 互斥。 |
| `base_url` | 大疆 FlySafe 服务地址 | 覆盖请求基础地址。 |

结果字段见[业务模型](models.md)。
