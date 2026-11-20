# 业务模型

查询使用 `BBox` 和机型 slug，返回 `AirspaceQueryResult`。本库从 `dji_geo` 顶层导出公共模型；模型不可变，坐标点按 `(经度, 纬度)` 排列。

## 一次查询的结果

| 字段 | 含义 |
| --- | --- |
| `zones` | 规范化后的 `GeoZone` 元组，通常用于业务处理。 |
| `raw_areas` | 解析得到的 `RawArea` 元组，用于查看上游码值和区域结构。 |
| `drone` / `request_bbox` | 实际查询机型和输入范围。 |
| `queried_at` | 客户端生成的查询时间，带 UTC 时区。 |
| `source` / `endpoint` | 数据来源 `dji_geo` 和接口标识 `in_rectangle`。 |
| `assumed_crs` / `crs_verified` | 当前为 `WGS-84` 假设及 `False`：坐标系尚未独立核验。 |
| `tiles_queried` | 实际查询的分片数。 |
| `echoed_center` / `echoed_radius_m` | 单分片时的上游回显；多分片合并时为 `None`。 |

`raw_areas` 保存模型定义的字段和原始码值，但未知字段会被忽略，因此不是完整的原始 HTTP 响应。分片请求失败会使整个查询失败；另一方面，单条几何畸形或未知时会记录告警并跳过对应规范化几何，其区域记录仍在 `raw_areas` 中，所以 `zones` 数量不一定等于上游区域数量。

## 从上游区域到 GeoZone

`RawArea` 是上游顶层记录；容器型记录的 `sub_areas` 含 `RawSubArea`。容器的子区展开为各自的 `GeoZone`，继承父区基础信息，并使用子区自身的等级、颜色和高度。独立圆形或多边形也可生成 `GeoZone`。

| `GeoZone` 字段 | 含义 |
| --- | --- |
| `area_id`, `part_index` | 上游区域 ID 和从 1 开始的部分序号。 |
| `name`, `country` | 区域名称和国家字段。 |
| `area_type`, `data_source` | 上游原始类型和数据来源码，完整码表未公开。 |
| `category` | 根据 `(level, color)` 推导的 `ZoneCategory`。 |
| `level`, `color`, `height_m` | 等级、颜色及高度值；高度单位米，基准未核实。 |
| `effective_from`, `effective_until` | 带时区的生效起止时间；`None` 表示该方向无时限。 |
| `geometry` | `CircleGeometry` 或 `PolygonGeometry`，详见 [GeoJSON](geojson.md)。 |

`zone.is_active_at(at)` 判断时刻是否落在闭区间内，参数必须是带时区的 `datetime`，否则抛出 `ValueError`。它只判断时间窗口，不代表飞行许可。

## 区域类别

分类依据上游 `level` 与 `color`，未知组合为 `UNKNOWN`；它是对厂商数据的解释，不是监管许可判断。

| `ZoneCategory` | 值 | 上游等级、颜色 | 含义 |
| --- | --- | --- | --- |
| `WARNING` | `warning` | 0, `#FFCC00` | 警示区 |
| `AUTHORIZATION` | `authorization` | 1, `#1088F2` | 授权区 |
| `RESTRICTED` | `restricted` | 2, `#DE4329` | 禁飞区 |
| `ALTITUDE` | `altitude` | 2, `#979797` | 限高区 |
| `ENHANCED_WARNING` | `enhanced_warning` | 3, `#EE8815` | 加强警示区 |
| `RECOMMENDED` | `recommended` | 5, `#00BE00` | 推荐区 |
| `REGULATORY_RESTRICTED` | `regulatory_restricted` | 7, `#37C4DB` | 法规限制提示区 |
| `APPROVED` | `approved` | 8, `#00BE00` | 适飞/批准区 |
| `SPECIAL_HEIGHT` | `special_height` | 10, `#377A26` | 特殊限高，具体语义尚未完整核实 |
| `UNKNOWN` | `unknown` | 其他组合 | 未识别 |

`DjiShape` 对应上游形态：`CIRCLE=0`、`POLYGON=1`、`CONTAINER=2`；原始模型中的 `shape` 保留整数，未知值不会被强制转成枚举。更多上游含义见[接口契约](../research/flysafe-api-contract.md)。
