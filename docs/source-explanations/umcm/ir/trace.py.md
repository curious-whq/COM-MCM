# `umcm/ir/trace.py` 源码讲解

文件职责：定义由动态事件、约束和部分观测组成的轨迹。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–14 行）

```python
"""Partial traces composed of dynamic events and typed constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SerializationError, TraceValidationError
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict
from umcm.serialization import decode_value, dump_data, encode_value, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `TRACE_SCHEMA_VERSION`（第 15–17 行）

```python
TRACE_SCHEMA_VERSION = "umcm.trace.v0.1"


```

这是模块级常量或公开导出声明：`TRACE_SCHEMA_VERSION` 保存traceschemaversion，供该对象的校验、转换或序列化逻辑使用。

## 类 `PartialObservation` 及全部字段（第 18–31 行）

```python
@dataclass(frozen=True, slots=True)
class PartialObservation:
    """A normalized observation over one event attribute.

    ``path`` is ``cycle``, ``occurs`` or ``fields.<name>``.  Event instances are
    still the canonical storage format; this helper is useful for tooling that
    wants to enumerate exactly what a partial trace has observed.
    """

    event_id: str
    path: str
    value: Any


```

把一个事件属性的部分观测规范化为路径和值。

- `event_id`：关联事件的稳定 ID。
- `path`：部分观测指向的公共属性或字段路径。
- `value`：该节点、字段或状态写入承载的值。

## 类 `Trace` 及全部字段（第 32–39 行）

```python
@dataclass(slots=True)
class Trace:
    events: list[EventInstance] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    partial: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = TRACE_SCHEMA_VERSION

```

保存动态事件、类型约束、部分标记和轨迹元数据。

- `events`：本对象管理的事件集合。
- `constraints`：必须同时成立的表达式约束。
- `partial`：轨迹是否允许包含未完全观测的信息。
- `metadata`：不参与核心语义的扩展元数据。
- `schema_version`：序列化模式版本。

## 方法 `Trace.__post_init__`（第 40–45 行）

```python
    def __post_init__(self) -> None:
        self.events = list(self.events)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        self._validate_structure()

```

在 `Trace` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Trace._validate_structure`（第 46–58 行）

```python
    def _validate_structure(self) -> None:
        ids = [event.id for event in self.events]
        duplicates = sorted({event_id for event_id in ids if ids.count(event_id) > 1})
        if duplicates:
            raise TraceValidationError(
                f"trace contains duplicate event id(s): {', '.join(duplicates)}"
            )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise TraceValidationError(
                    f"trace constraint must be bool, got {constraint.sort}"
                )

```

检查 `Trace` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `Trace.validate`（第 59–94 行）

```python
    def validate(self, catalog: EventCatalog, *, partial: bool | None = None) -> None:
        self._validate_structure()
        catalog.validate_events(
            self.events,
            partial=self.partial if partial is None else partial,
        )
        event_map = {event.id: event for event in self.events}
        from umcm.ir.expression import iter_event_fields
        from umcm.ir.sort import BOOL, INT

        for constraint in self.constraints:
            for reference in iter_event_fields(constraint):
                event = event_map.get(reference.event_id)
                if event is None:
                    raise TraceValidationError(
                        f"constraint references unknown event id {reference.event_id!r}"
                    )
                if reference.field == "cycle":
                    expected = INT
                elif reference.field == "occurs":
                    expected = BOOL
                else:
                    event_type = catalog.resolve(event.event_type)
                    try:
                        expected = event_type.field_map[reference.field].sort
                    except KeyError as exc:
                        raise TraceValidationError(
                            f"constraint references unknown field "
                            f"{reference.event_id}.{reference.field}"
                        ) from exc
                if not reference.sort.compatible_with(expected):
                    raise TraceValidationError(
                        f"constraint reference {reference.event_id}.{reference.field} "
                        f"has sort {reference.sort}, expected {expected}"
                    )

```

检查 `Trace` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `Trace.get`（第 95–100 行）

```python
    def get(self, event_id: str) -> EventInstance:
        for event in self.events:
            if event.id == event_id:
                return event
        raise TraceValidationError(f"unknown event id: {event_id}")

```

按 ID 查找轨迹事件，未知 ID 时返回空值。

## 方法 `Trace.events_of_type`（第 101–103 行）

```python
    def events_of_type(self, event_type: str) -> list[EventInstance]:
        return [event for event in self.events if event.event_type == event_type]

```

筛选并返回指定事件类型的全部轨迹事件。

## 方法 `Trace.observations`（第 104–115 行）

```python
    def observations(self) -> list[PartialObservation]:
        result: list[PartialObservation] = []
        for event in self.events:
            result.append(PartialObservation(event.id, "occurs", event.occurs))
            if event.cycle is not None:
                result.append(PartialObservation(event.id, "cycle", event.cycle))
            result.extend(
                PartialObservation(event.id, f"fields.{name}", value)
                for name, value in sorted(event.fields.items())
            )
        return result

```

展开事件公共属性和字段，生成规范化的部分观测列表。

## 方法 `Trace.to_dict`（第 116–124 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "partial": self.partial,
            "metadata": encode_value(self.metadata),
            "events": [event.to_dict() for event in self.events],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

```

把 `Trace` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `Trace.from_dict`（第 125–145 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Trace":
        if not isinstance(data, Mapping):
            raise SerializationError("trace must be a mapping")
        raw_events = data.get("events", [])
        raw_constraints = data.get("constraints", [])
        if not isinstance(raw_events, list):
            raise SerializationError("trace events must be a list")
        if not isinstance(raw_constraints, list):
            raise SerializationError("trace constraints must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("trace metadata must be a mapping")
        return cls(
            events=[EventInstance.from_dict(item) for item in raw_events],
            constraints=[expr_from_dict(item) for item in raw_constraints],
            partial=bool(data.get("partial", True)),
            metadata=metadata,
            schema_version=str(data.get("schema_version", TRACE_SCHEMA_VERSION)),
        )

```

校验输入字典的键和值，并递归构造 `Trace` 实例。

## 方法 `Trace.load`（第 146–149 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "Trace":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `Trace`。

## 方法 `Trace.dump`（第 150–153 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


```

调用 `to_dict` 后把 `Trace` 安全写成 YAML/JSON。

## 函数 `_event_references`（第 154–179 行）

```python
def _event_references(expr: Expr) -> set[str]:
    from umcm.ir.expression import Binary, Call, EventField, Ite, Nary, Unary

    if isinstance(expr, EventField):
        return {expr.event_id}
    if isinstance(expr, Unary):
        return _event_references(expr.operand)
    if isinstance(expr, Binary):
        return _event_references(expr.left) | _event_references(expr.right)
    if isinstance(expr, Nary):
        refs: set[str] = set()
        for operand in expr.operands:
            refs |= _event_references(operand)
        return refs
    if isinstance(expr, Ite):
        return (
            _event_references(expr.condition)
            | _event_references(expr.then_expr)
            | _event_references(expr.else_expr)
        )
    if isinstance(expr, Call):
        refs: set[str] = set()
        for argument in expr.arguments:
            refs |= _event_references(argument)
        return refs
    return set()
```

递归遍历表达式，收集其中引用的事件 ID。

