# Architecture

本文描述 `dji-geo` 的目录布局、模块职责、依赖方向、测试接缝以及明确的非目标边界。随代码演进同步更新，只反映当前架构现状。

## 目录结构

```text
.
├── AGENTS.md                   # 轻索引入口（渐进式披露）
├── GLOSSARY.md                 # 纯领域术语表
├── pyproject.toml              # uv / hatchling / ruff / pyright / pytest 配置
├── docs/
│   ├── usage/                  # 面向使用者的安装、调用、模型与错误指南
│   ├── agents/                 # 面向开发与 Agent 的架构、规范及工作流文档
│   └── research/               # 上游协议契约与异常边界参考（flysafe-api-contract / upstream-quirks-and-boundaries）
├── src/dji_geo/
│   ├── __init__.py             # 最小公开出口（__all__）
│   ├── py.typed                # PEP 561 类型分发标记
│   ├── client.py               # 深模块入口：DjiGeoClient、RetryPolicy、并发/重试/缓存编排
│   ├── models.py               # 公共 Pydantic v2 模型、枚举与输入值对象
│   ├── errors.py               # 结构化异常树
│   ├── geojson.py              # 零重依赖 to_geojson 导出与圆形测地离散化
│   ├── _wire.py                # [内部] flysafe-api 信封解析、HTTP 200 业务错提取
│   ├── _normalize.py           # [内部] shape 展开、父子字段继承、(level, color) 分类
│   └── _tiling.py              # [内部] Haversine 跨度估算、BBox 切块与确定性去重合并
└── tests/                      # 经公共接缝验证核心行为的精简测试套件
```

## 模块职责与依赖方向

依赖严格单向无环；外部调用方只应依赖 `dji_geo` 顶层导出，不得导入下划线私有模块（`_wire`、`_normalize`、`_tiling`）：

```text
__init__.py
  ├── client.py  ──▶ models.py, errors.py, _wire.py, _normalize.py, _tiling.py
  ├── geojson.py ──▶ models.py
  ├── _wire.py   ──▶ models.py, errors.py
  ├── _normalize.py ──▶ models.py
  └── _tiling.py ──▶ models.py
```

- **`client.py`**：唯一 I/O 编排入口。负责 `httpx2.AsyncClient` 生命周期（托管或外部注入）、实例级带 Full Jitter 指数退避、大框切块并发（`asyncio.Semaphore`）与 Fail-fast、以及 `list_drones` 懒加载内存缓存（`asyncio.Lock` 防并发击穿）。
- **`_wire.py`**：吸收上游非公开协议怪癖。拦截 `302` 重定向与非 JSON 响应，解析 `flysafe-api` 外层信封，把 HTTP 200 内的业务错误（含 `code=1` 超距、`data` 类型突变）转换为 `errors.py` 异常。
- **`_normalize.py`**：吸收空间嵌套怪癖。按 `shape=0/1/2` 展平容器与子区，继承父区元数据，以 `(level, color.upper())` 联合推导 `ZoneCategory`；单条畸形或未知几何记录告警并在 `raw_areas` 中无损保留，不中断整次查询。
- **`_tiling.py`**：纯计算模块。用标准库 `math` 估算 Haversine 对角线跨度，超过 `max_tile_diagonal_km`（默认 `350 km`）时均匀网格切分，并按 `area_id` 去重后升序排列以保证并发输出确定性。
- **`geojson.py`**：零 GIS 依赖导出。单环输出 `Polygon`，多环输出 `MultiPolygon`（保持大疆前端逐环渲染语义，不臆断内洞），自动补闭未闭合环，圆形经测地公式近似并显式标记近似与未核验 CRS 元数据。
- **包版本**：`pyproject.toml` 的 `project.version` 是唯一维护来源，顶层 `dji_geo.__version__` 从已安装发行包 `dji-geo` 的元数据读取；使用前需安装项目（开发环境可运行 `uv sync`）。

## 唯一外部接缝（Testing Seam）

DJI FlySafe HTTP API 是外部第三方依赖。`DjiGeoClient` 直接以 **`httpx2.AsyncClient` / `httpx2.AsyncBaseTransport`** 作为唯一外部接缝：

- 生产环境支持默认托管连接池（`async with DjiGeoClient()` 或显式 `await client.aclose()`），也支持注入外部 `http_client`（托管标志 `_owns_client=False`，关闭时不误关外部 client）。
- 单元测试通过 `transport=httpx2.MockTransport(...)` 穿过公开接口运行完整协议、重试、切块与建模链路。

## 边界与关键权衡（Non-goals & Trade-offs）

1. **v0.1 仅封装现行 `flysafe-api` 主线**：只实现 `in_rectangle` 与 `drones`，明确排除旧域 `www-api`（`areas`、`point-info`），避免在核心客户端背负废弃域下线、签名校验与响应头泄漏风险；旧接口坑点与排除依据留存 [upstream-quirks-and-boundaries.md](../research/upstream-quirks-and-boundaries.md)。
2. **核心包零 GIS 重依赖、不做多数据源抽象**：运行依赖仅限 `httpx2` 与 `pydantic`。不引入 `shapely`/`pyproj`、不做地理编码、不做 WGS-84 ↔ GCJ-02 转换，也不提前抽象面向民航局 UOM/USS 的多源基类（当前只有一个真实适配器）；通过结果上的 `source` 与 `assumed_crs` 字段保留未来上层适配扩展点。
3. **不二次包装 `httpx2` Transport 协议**：直接复用 `httpx2.AsyncBaseTransport` 接缝，避免单实现薄抽象层。
4. **响应开放世界容错**：上游接口未公开 Schema，响应模型采用 `extra="ignore"` 且原始码值保留 `int`/`str` 配合 `ZoneCategory.UNKNOWN` 兜底，防止上游新增字段或枚举引发线上雪崩。
5. **切块失败坚持 Fail-fast 且不做边缘裁剪**：空域禁飞场景绝不静默返回残缺数据，任一分片重试耗尽则整次查询失败；服务端按外接圆查询带来的四角外少量边缘区域原样返回，不在客户端做几何裁剪。
