# DJI GEO

面向大疆（DJI）FlySafe / GEO 空域地理围栏数据的异步查询与空间模型规范化上下文，旨在将上游非公开 HTTP 响应清洗为类型安全、带溯源信息的空域数据结构。

## Language

### 查询与溯源

**Bounding Box (`BBox`)**:
以十进制度经纬度表示的轴对齐矩形查询范围，由西经、南纬、东经、北纬四个边界值定义。
_Avoid_: Viewport, rect, area box

**Query Tile**:
当请求的 `BBox` 跨度超过安全阈值时，由客户端按规则网格切分出的单个子矩形请求单元。
_Avoid_: Chunk, shard, page

**Airspace Query Result (`AirspaceQueryResult`)**:
一次空域查询的不可变返回结果，同时包含规范化后的 `GeoZone` 集合、无损保留的 `RawArea` 集合以及本次查询的溯源元数据（机型、查询时间、数据来源与坐标系声明）。
_Avoid_: Response, payload, area list

**Assumed CRS**:
上游响应未显式声明坐标参考系时，系统基于顶点顺序与行业惯例暂定的坐标系假设（当前为未独立校核的 `WGS-84`）。
_Avoid_: Confirmed CRS, projection

**Geofence Reference**:
大疆设备与飞控侧使用的地理围栏参考数据，仅反映厂商设备限制，不等同于民航监管部门（如 UOM / USS）发布的法定空域或审批结论。
_Avoid_: Legal airspace, regulatory ban, no-fly clearance

### 上游原始结构与规范化空域

**Raw Area (`RawArea`)**:
上游空域接口返回的单条顶层区域记录，可能是独立几何，也可能是包含多个子区的复合容器。
_Avoid_: Zone, feature, restriction

**Raw Sub-Area (`RawSubArea`)**:
隶属于容器型 `RawArea` 的单条子区域记录，拥有独立几何及可覆盖父级的管控等级、颜色与限高值。
_Avoid_: Child area, polygon item

**Geo Zone (`GeoZone`)**:
从 `RawArea` 与 `RawSubArea` 展开、继承父级元数据并完成类别推导后的最小独立空间管控单元，对应唯一一种确定几何形态。
_Avoid_: Area, polygon, zone container

**Zone Category (`ZoneCategory`)**:
由上游管控等级码与颜色值联合推导出的规范化业务类别（例如禁飞区、限高区、授权区、加强警示区及未知兜底类别）。
_Avoid_: Level, color type, zone type

**Zone Geometry**:
`GeoZone` 的精确空间几何表达，严格限定为圆形（`CircleGeometry`）或多环多边形（`PolygonGeometry`）两种形态之一。
_Avoid_: Shape, coordinates

**Linear Ring**:
按 `[经度, 纬度]` 顺序排列的多边形顶点序列；同一多边形下多个环之间不预设内外洞拓扑关系。
_Avoid_: Polygon, hole, boundary

### 机型目录

**Drone Model (`DroneModel`)**:
上游机型目录中的单个大疆机型条目，由展示名称与查询标识组成。
_Avoid_: Aircraft, device, UAV

**Drone Slug**:
上游机型目录中用于空域查询参数的机型唯一字符串标识（如 `dji-mini-3`）。
_Avoid_: Drone ID, model name, drone code
