# Coding Standards

本文件定义 `dji-geo` 的代码风格、类型系统、Pydantic 建模、文档注释与精简测试规范，用于编写和代码审查。

## 1. 静态类型（Type Hints）

- 运行目标为 **Python >= 3.12**，统一使用现代类型语法：`X | None`、内置泛型 `tuple[...]` / `dict[...]`、PEP 695 `type Alias = ...`、`Literal`、`Self`。
- **`src/` 保持 `pyright` strict 零报错**：所有公共与内部函数、方法、类属性必须完整标注参数与返回类型，禁止引入隐式 `Any`（仅 `to_geojson` 返回 JSON 字典等确需动态结构处允许显式标注 `dict[str, Any]`）。
- **`tests/` 保持 `pyright` basic 宽松模式**：测试中允许省略测试函数返回类型与夹具细节标注，不因测试代码陷入无意义的类型体操。

## 2. Pydantic v2 建模准则

- **所有对外数据模型不可变**：统一配置 `model_config = ConfigDict(frozen=True, ...)`。
- **输入严格、上游宽容**：
  - 调用方输入与配置模型（如 `BBox`、`RetryPolicy`）使用 `extra="forbid"`，第一时间暴露拼写与越界错误；
  - 上游响应模型（如 `RawArea`、`RawSubArea`、`DroneModel`）使用 `extra="ignore"`，兼容大疆未通知的新增字段。
- **用可辨识联合表达互斥几何**：`ZoneGeometry` 严格限定为 `CircleGeometry | PolygonGeometry`（`Field(discriminator="kind")`），从类型层面消除“容器被当成圆”的非法状态。
- **热点坐标避免对象化**：顶点与环使用 `type LngLat = tuple[float, float]` 和 `type LinearRing = tuple[LngLat, ...]`，不为每个坐标点实例化 `BaseModel`。
- **上游原始码值不闭集硬校验**：`RawArea`/`RawSubArea` 的 `shape`、`level`、`type`、`data_source` 保留原始 `int`，由规范化层映射到带 `UNKNOWN` 兜底的 `ZoneCategory`。

## 3. 异常与容错约定

- 所有库内主动抛出的异常继承自 `DjiGeoError`，清晰区分：
  - `DjiTransportError`（瞬态网络、超时、HTTP 429/5xx 重试耗尽）
  - `DjiProtocolError`（302 重定向、非 JSON、非预期 HTTP 状态、响应结构突变校验失败）
  - `DjiApiError` 及其子类 `SearchDistanceExceededError`、`InvalidParameterError`
- 禁止吞掉上游 HTTP 200 内的业务错误；单条畸形上游几何记录 `logging.getLogger("dji_geo").warning(...)` 并在 `raw_areas` 无损保留，不中断整次查询。

## 4. 中文 Docstring 与注释规范

- **统一使用 Google Style 中文 Docstring**：覆盖所有公共模块、类、方法、函数与异常类。
  - 首行一句话概括契约语义；空行后按需补充不变式、坐标系/合规边界或注意事项；
  - `Args:` / `Returns:` / `Raises:` 只写类型标注无法表达的语义（单位、范围、副作用、异常触发条件），**不要重复类型签名**。
- **枚举成员使用属性 Docstring（Attribute Docstring）**：在每个枚举成员下一行紧跟三引号中文说明，确保 IDE 悬停可读；涉及非公开上游码值时，必须明确写明是“按上游规则映射”还是“基于实测样本推断，官方未公开完整语义”。
- **行内注释只写 `Why`**：只解释非显而易见的设计意图或上游规避逻辑（如大小写归一化原因、禁用重定向原因）；代码本身能直接读懂的流程不加复述型注释。
- **源码注释保持纯净**：只记录此刻有效的事实与约束，不写入 PR 编号、Issue 编号、变更日志或外部 `docs/` 文档路径引用。

## 5. 核心测试准则（Pytest）

测试只落在公共接缝（`DjiGeoClient` + `httpx2.MockTransport` 及公共纯函数），追求**少而狠**，不追求堆砌覆盖率数字：

- **必测的核心路径**：
  1. 矩形查询端到端：容器子区展开、父子字段继承、`(level, color)` 分类（含 `level=2` 禁飞红 vs 限高灰区分）、圆形/多边形可辨识联合与 UTC 时效判断；
  2. 协议与错误契约：HTTP 200 业务错（`code=1` 超距、`data` 类型突变）、`302` 重定向拦截、非 JSON 与结构突变校验失败；
  3. 退避重试边界：瞬态超时/5xx 重试成功与重试耗尽、确定性业务错不重试、`max_retries=0` 零重试；
  4. 机型目录：懒缓存、并发首次调用防击穿、`force_refresh=True`、`validate_drone=True` 拦截非法 slug；
  5. 大框自动切块：小框不切块保留回显、大框切块并发限流与 `area_id` 确定性去重排序、任一分片失败整体 Fail-fast；
  6. 容错与导出：畸形/未知几何告警降级且 `raw_areas` 无损、`to_geojson` 单环 `Polygon` / 多环 `MultiPolygon` / 自动闭合 / 圆形离散近似标记。
- **避免编写的低价值测试**：
  - 不测 Pydantic 原生字段赋值、冻结或基础类型校验；
  - 不直接测试 `_wire`/`_normalize`/`_tiling` 的私有实现细节（测试应能扛住内部重构）；
  - 不为简单常量、等价参数组合复制粘贴重复用例（同类边界合并使用 `@pytest.mark.parametrize`）。
- **异步测试要求**：超时退避测试须注入可控退避等待（或使用极短 `base_delay_s` / 可控 sleep），保持整套单测毫秒级完成，且**核心单测零真实外网请求**。
