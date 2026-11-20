# DJI FlySafe API 协议契约与解析约束

本文沉淀大疆（DJI）现行 `flysafe-api` 主线接口的实测协议契约、数据模型语义与几何/分类解析不变式。

> **前提声明**：以下接口为大疆官网 FlySafe 地图使用的**非公开只读 HTTP GET 接口**，当前可匿名访问（无需账号 Token、API Key 或 Cookie），但无官方文档、Schema 承诺、商业授权或 SLA。数据仅代表厂商设备地理围栏参考（Geofence Reference），不等同于民航监管部门发布的法定空域或审批结论。

---

## 1. 主线端点总览

| 简称 | 方法与端点 | 用途 |
| --- | --- | --- |
| `in_rectangle` | `GET https://flysafe-api.dji.com/api/qep/geo/feedback/areas/in_rectangle` | 按轴对齐经纬度矩形框拉取空域围栏几何与属性 |
| `drones` | `GET https://flysafe-api.dji.com/dji/drones` | 拉取合法的机型目录及 `slug` 标识 |

---

## 2. `in_rectangle` 矩形空域查询契约

### 2.1 查询参数（Query）

| 参数 | 类型 | 必填 | 语义与约束 | 示例 |
| --- | --- | --- | --- | --- |
| `ltlat` | `number` | 是 | 西北角（左上）纬度，十进制度；须满足 `rblat < ltlat` | `20.5` |
| `ltlng` | `number` | 是 | 西北角（左上）经度，十进制度；须满足 `ltlng < rblng` | `10.0` |
| `rblat` | `number` | 是 | 东南角（右下）纬度，十进制度 | `20.0` |
| `rblng` | `number` | 是 | 东南角（右下）经度，十进制度 | `10.6` |
| `drone` | `string` | 是 | 机型唯一 `slug`，取自 `/dji/drones` | `dji-mini-3` |
| `zones_mode` | `string` | 是 | 区域模式，现行官网固定为 `flysafe_website` | `flysafe_website` |
| `level` | `string` | 是 | 英文逗号分隔的管控等级集合；现行官网覆盖 `0..10` | `0,1,2,3,4,5,6,7,8,9,10` |

### 2.2 成功响应信封与判定规则

```json
{
  "code": 0,
  "message": {
    "chinese": "成功",
    "english": "OK"
  },
  "data": {
    "areas": [],
    "country": "XX",
    "lat": 20.25,
    "lng": 10.3,
    "radius": 41000
  }
}
```

- **成功判定不变式**：必须同时满足 `HTTP 200`、`Content-Type` 为 JSON、`code === 0`（强类型排除布尔值 `false`）、`data` 为对象且 `data.areas` 为数组。
- **回显字段**：`data.lat`、`data.lng`、`data.radius` 为服务端由输入矩形换算出的中心点与等效外接圆半径（米）。

---

## 3. `drones` 机型目录查询契约

- **请求**：无 Query 参数。
- **成功响应信封**：

```json
{
  "status": 0,
  "drones": [
    { "name": "DJI Mini 3", "slug": "dji-mini-3" }
  ]
}
```

- **成功判定不变式**：`HTTP 200`、`Content-Type` 为 JSON、`status === 0`（排除布尔值）且 `drones` 为数组。
- **缓存特性**：目录变更低频（实测规模约 75 个机型），适合客户端懒加载并内存缓存，按需提供强制刷新。

---

## 4. 区域数据结构约束（`RawArea` / `RawSubArea`）

### 4.1 关键字段语义与开放世界约定

上游未公开 Schema，反序列化**必须容忍未知新增字段**（`extra="ignore"`）并对整型枚举码采用**开放世界容错**（保留原始 `int`，禁止闭集硬校验阻断解析）。

| 字段 | 层级 | 语义、哨兵值与未公开边界 |
| --- | --- | --- |
| `area_id` | 父区 | 区域唯一整型 ID，是多片查询去重合并的主键 |
| `name`、`country` | 父区 | 区域名称（中英文混用）与 ISO 国家/地区码；子区须继承 |
| `shape` | 父/子 | 几何形态分派码：`0`=圆形、`1`=多边形、`2`=容器 |
| `lat`、`lng`、`radius` | 父/子 | 圆心/参考中心与米制半径；仅 `shape=0` 为真实圆边界，`shape=2` 顶层仅为参考包络 |
| `polygon_points` | 父/子 | 顶点环序列 `[[[lng, lat], ...], ...]`；容器顶层常为 `null` |
| `sub_areas` | 父区 | 子区数组；`shape=2` 时为非空数组，`shape=0` 时常为 `null` |
| `level`、`color` | 父/子 | 管控等级码与十六进制色值；**必须联合推导真实业务类别**，容器以子区自身值为准 |
| `height` | 父/子 | 限高值（整数，单位米）；`0` 常表示禁飞或无单独限高；**高度基准（AGL/MSL 等）未核实** |
| `begin_at`、`end_at` | 父区 | Unix 秒级时间戳；`0` 为未设时限/长期有效哨兵值（保留原值，业务层解释为无界） |
| `type`、`data_source` | 父区 | 区域地物类型码（如机场/景区/管控区等）与内部数据来源枚举（实测见 `0`、`2`）；**完整码表未公开** |
| `city`、`address`、`description`、`url` | 父区 | 辅助文本字段，常为空字符串 `""` |

### 4.2 最小脱敏结构骨架（合成占位数据）

```json
[
  {
    "area_id": 10001,
    "name": "Sample Airport",
    "type": 10,
    "shape": 2,
    "lat": 20.25,
    "lng": 10.30,
    "radius": 6000,
    "level": 2,
    "height": 0,
    "color": "#DE4329",
    "begin_at": 0,
    "end_at": 0,
    "country": "XX",
    "data_source": 2,
    "polygon_points": null,
    "sub_areas": [
      {
        "shape": 1,
        "level": 2,
        "color": "#DE4329",
        "height": 0,
        "lat": 20.24,
        "lng": 10.29,
        "radius": 12000,
        "polygon_points": [[[10.20, 20.20], [10.30, 20.20], [10.30, 20.30], [10.20, 20.20]]]
      }
    ]
  },
  {
    "area_id": 10002,
    "name": "Sample Controlled Circle",
    "type": 29,
    "shape": 0,
    "lat": 20.15,
    "lng": 10.15,
    "radius": 500,
    "level": 2,
    "height": 0,
    "color": "#DE4329",
    "begin_at": 1700000000,
    "end_at": 1800000000,
    "country": "XX",
    "data_source": 0,
    "polygon_points": null,
    "sub_areas": null
  }
]
```

---

## 5. 管控类别推导约束（`level` + `color`）

以下映射提取自现行官网前端配置。**严禁仅凭 `level` 单独分类**，因为 `level=2` 同时承载“禁飞区”和“限高区”。

| `level` | `color`（归一化大写） | 官网前端枚举 | 规范化类别 | 解析注意 |
| --- | --- | --- | --- | --- |
| `0` | `#FFCC00` | `warningZone` | 警示区 | 安全提醒 |
| `1` | `#1088F2` | `authorizationZone` | 授权区 | 设备侧可账号认证自解禁 |
| `2` | `#DE4329` | `restrictedZone` | **禁飞区** | 与限高区共用 `level=2`，须看颜色 |
| `2` | `#979797` | `altitudeZone` | **限高区** | 与禁飞区共用 `level=2`，限高读 `height` |
| `3` | `#EE8815` | `enhancedWarningZone` | 加强警示区 | 需操作者确认提示 |
| `5` | `#00BE00` | `recommendedZone` | 推荐区 | 推荐飞行区域 |
| `7` | `#37C4DB` | `regulatoryRestrictedZone` | 法规限制区 | 对应当地法规限制提示 |
| `8` | `#00BE00` | `approvedZone` | 适飞/批准区 | 前端源码存在小写 `#00be00` |
| `10` | `#377A26` | `specialHeightRestrictedZone` | 特殊限高区 | 前端源码存在小写 `#377a26`；具体规则未公开 |

- **大小写归一化**：前端配置与接口样本均存在颜色大小写混用，查表前必须执行 `strip().upper()`。
- **未知兜底**：任何未命中上述组合的 `(level, color)` 必须映射为 `UNKNOWN` 兜底，保留原始 `level`/`color` 且不中断解析。

---

## 6. 几何展开、拓扑与坐标系约束

1. **按 `shape` 严格分派**：
   - `shape === 0`（圆）：取 `(lng, lat, radius)`。点在圆内判定须用测地距离（如 Haversine / WGS-84 椭球测地线）；仅在导出 GeoJSON 渲染时才离散近似为闭合多边形，并显式标注近似标记。
   - `shape === 1`（多边形）：从 `polygon_points` 提取顶点环。
   - `shape === 2`（容器）：**忽略顶层圆参数**，遍历 `sub_areas` 并按子区 `shape` 提取。子区继承父区 `area_id`、`name`、`country`、`type`、`data_source`、`begin_at`、`end_at`，同时**以子区自身的 `level`、`color`、`height` 为准**。
2. **多环不预设内洞**：现行官网前端对 `polygon_points` 中的多环按**逐环独立多边形**渲染。未经拓扑包含检测，禁止把第 2 个环默认当作 GeoJSON `Polygon` 的内洞（Hole）；零重依赖导出时应单环输出 `Polygon`、多环输出 `MultiPolygon`，并对未闭合环自动补闭。
3. **保留分区粒度**：禁止把同一容器下的多个 `sub_areas` 无条件几何合并（Union），否则会丢失各子区独立的 `level`、`color` 或 `height`。
4. **单条畸形容错**：遇到空容器、非正半径、退化环或未知 `shape` 时，应告警跳过规范化展开并在原始记录集合中无损保留，不得导致整次查询失败。
5. **坐标顺序与 Assumed CRS**：
   - 顶点顺序固定为 `[经度, 纬度]`（Longitude first），与 RFC 7946 一致。
   - 响应体**未显式声明坐标参考系（CRS）**；结合坐标格式与行业实现暂定为 `WGS-84`（标记 `crs_verified=False`）。叠加 GCJ-02 等偏移底图前须用控制点独立校核，并在展示层一次性转换；内部存储与计算统一保持 WGS-84。
