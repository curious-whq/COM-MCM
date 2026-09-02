# `umcm/ir/completion.py` 源码讲解

文件职责：定义有限事件槽和补全模型。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–18 行）

```python
"""Finite event-slot declarations and completion-model serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError, TraceValidationError
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import Expr, Symbol, iter_event_fields, expr_from_dict, expr_to_dict
from umcm.ir.sort import BOOL, INT
from umcm.ir.state import StateVariable
from umcm.ir.trace import Trace
from umcm.ir.transformation import Transformation
from umcm.serialization import decode_value, dump_data, encode_value, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `COMPLETION_SCHEMA_VERSION`（第 19–21 行）

```python
COMPLETION_SCHEMA_VERSION = "umcm.completion.v0.6.0"


```

这是模块级常量或公开导出声明：`COMPLETION_SCHEMA_VERSION` 保存completionschemaversion，供该对象的校验、转换或序列化逻辑使用。

## 类 `EventSlot` 及全部字段（第 22–36 行）

```python
@dataclass(frozen=True, slots=True)
class EventSlot:
    """One bounded candidate event available to the completion solver.

    ``required`` means that the current witness query demands this event. It is
    not a global liveness claim about every execution of the modeled hardware.
    """

    id: str
    event_type: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    required: bool = False
    cycle: int | Expr | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)

```

表示补全求解器可选择并物化的一个有界候选事件。

- `id`：对象的稳定标识符。
- `event_type`：关联的事件类型名称。
- `fields`：字段名到字段值或字段规则的映射。
- `required`：该候选或字段是否必须存在。
- `cycle`：事件发生周期或诊断环。
- `annotations`：随对象保留的附加注解。

## 方法 `EventSlot.__post_init__`（第 37–44 行）

```python
    def __post_init__(self) -> None:
        if not self.id:
            raise SchemaError("event slot id must be non-empty")
        if not self.event_type:
            raise SchemaError("event slot type must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))
        object.__setattr__(self, "annotations", dict(self.annotations))

```

在 `EventSlot` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventSlot.validate`（第 45–64 行）

```python
    def validate(self, catalog: EventCatalog) -> None:
        event_type = catalog.resolve(self.event_type)
        unknown = set(self.fields) - set(event_type.field_map)
        if unknown:
            raise SchemaError(
                f"slot {self.id!r} has unknown field(s): "
                f"{', '.join(sorted(unknown))}"
            )
        for name, value in self.fields.items():
            expected = event_type.field_map[name].sort
            if isinstance(value, Expr):
                if not value.sort.compatible_with(expected):
                    raise SchemaError(
                        f"slot {self.id!r}.{name} expects {expected}, got {value.sort}"
                    )
            elif not expected.accepts_literal(value):
                raise SchemaError(
                    f"slot {self.id!r}.{name} value {value!r} is invalid for {expected}"
                )

```

检查 `EventSlot` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `EventSlot.materialize`（第 65–95 行）

```python
    def materialize(self, catalog: EventCatalog) -> EventInstance:
        """Create a symbolic EventInstance for this bounded slot."""

        event_type = catalog.resolve(self.event_type)
        values = dict(self.fields)
        for field_spec in event_type.fields:
            if field_spec.required and field_spec.name not in values:
                values[field_spec.name] = Symbol(
                    f"slot::{self.id}::field::{field_spec.name}",
                    field_spec.sort,
                )
        cycle: int | Expr = (
            self.cycle
            if self.cycle is not None
            else Symbol(f"slot::{self.id}::cycle", INT)
        )
        occurs: bool | Expr = True if self.required else Symbol(
            f"slot::{self.id}::occurs", BOOL
        )
        annotations = dict(self.annotations)
        annotations.setdefault("completion_slot", True)
        annotations.setdefault("required_slot", self.required)
        return EventInstance(
            id=self.id,
            event_type=self.event_type,
            fields=values,
            cycle=cycle,
            occurs=occurs,
            annotations=annotations,
        )

```

把声明式的事件转换成求解或输出使用的具体对象。

## 方法 `EventSlot.to_dict`（第 96–108 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.event_type,
            "required": self.required,
            "fields": encode_value(dict(self.fields)),
        }
        if self.cycle is not None:
            data["cycle"] = encode_value(self.cycle)
        if self.annotations:
            data["annotations"] = encode_value(dict(self.annotations))
        return data

```

把 `EventSlot` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `EventSlot.from_dict`（第 109–133 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventSlot":
        if not isinstance(data, Mapping):
            raise SerializationError("event slot must be a mapping")
        try:
            fields = decode_value(data.get("fields", {}))
            annotations = decode_value(data.get("annotations", {}))
            if not isinstance(fields, dict):
                raise SerializationError("event slot fields must be a mapping")
            if not isinstance(annotations, dict):
                raise SerializationError("event slot annotations must be a mapping")
            return cls(
                id=str(data["id"]),
                event_type=str(data["type"]),
                fields=fields,
                required=bool(data.get("required", False)),
                cycle=decode_value(data.get("cycle")),
                annotations=annotations,
            )
        except KeyError as exc:
            raise SerializationError(
                f"event slot is missing {exc.args[0]!r}"
            ) from exc


```

校验输入字典的键和值，并递归构造 `EventSlot` 实例。

## 类 `CompletionSpec` 及全部字段（第 134–145 行）

```python
@dataclass(slots=True)
class CompletionSpec:
    """A bounded event universe, operational rules and persistent state."""

    slots: list[EventSlot] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    state_variables: list[StateVariable] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    horizon: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = COMPLETION_SCHEMA_VERSION

```

聚合事件槽、转换、状态变量、约束和求解时域。

- `slots`：补全模型允许使用的有限候选事件槽。
- `transformations`：补全模型包含的操作转换规则。
- `state_variables`：补全模型声明的持久状态单元。
- `constraints`：必须同时成立的表达式约束。
- `horizon`：保存求解周期上界，供该对象的校验、转换或序列化逻辑使用。
- `metadata`：不参与核心语义的扩展元数据。
- `schema_version`：序列化模式版本。

## 方法 `CompletionSpec.__post_init__`（第 146–169 行）

```python
    def __post_init__(self) -> None:
        self.slots = list(self.slots)
        self.transformations = list(self.transformations)
        self.state_variables = list(self.state_variables)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        if self.horizon < 0:
            raise SchemaError("completion horizon must be non-negative")
        _reject_duplicates(
            [slot.id for slot in self.slots],
            "completion spec contains duplicate slot id(s)",
        )
        _reject_duplicates(
            [item.name for item in self.transformations],
            "completion spec contains duplicate transformation(s)",
        )
        _reject_duplicates(
            [item.name for item in self.state_variables],
            "completion spec contains duplicate state variable(s)",
        )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise SchemaError("completion constraints must be boolean")

```

在 `CompletionSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `CompletionSpec.state_map`（第 170–173 行）

```python
    @property
    def state_map(self) -> dict[str, StateVariable]:
        return {item.name: item for item in self.state_variables}

```

构造状态变量名到声明的映射，供转换和求解问题快速解析引用。

## 方法 `CompletionSpec.validate`（第 174–220 行）

```python
    def validate(self, catalog: EventCatalog, trace: Trace) -> None:
        observed_ids = {event.id for event in trace.events}
        slot_ids = {slot.id for slot in self.slots}
        overlap = observed_ids & slot_ids
        if overlap:
            raise TraceValidationError(
                f"completion slots collide with trace event id(s): "
                f"{', '.join(sorted(overlap))}"
            )
        for slot in self.slots:
            slot.validate(catalog)
        for transformation in self.transformations:
            transformation.validate(catalog, self.state_map)

        event_types_by_id = {
            event.id: catalog.resolve(event.event_type) for event in trace.events
        }
        event_types_by_id.update(
            {slot.id: catalog.resolve(slot.event_type) for slot in self.slots}
        )
        for constraint in self.constraints:
            for reference in iter_event_fields(constraint):
                event_type = event_types_by_id.get(reference.event_id)
                if event_type is None:
                    raise TraceValidationError(
                        f"completion constraint references unknown event id "
                        f"{reference.event_id!r}"
                    )
                if reference.field == "cycle":
                    expected = INT
                elif reference.field == "occurs":
                    expected = BOOL
                else:
                    try:
                        expected = event_type.field_map[reference.field].sort
                    except KeyError as exc:
                        raise TraceValidationError(
                            f"completion constraint references unknown field "
                            f"{reference.event_id}.{reference.field}"
                        ) from exc
                if not reference.sort.compatible_with(expected):
                    raise TraceValidationError(
                        f"completion constraint reference "
                        f"{reference.event_id}.{reference.field} has sort "
                        f"{reference.sort}, expected {expected}"
                    )

```

检查 `CompletionSpec` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `CompletionSpec.to_dict`（第 221–231 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "horizon": self.horizon,
            "metadata": encode_value(self.metadata),
            "slots": [slot.to_dict() for slot in self.slots],
            "state_variables": [item.to_dict() for item in self.state_variables],
            "transformations": [item.to_dict() for item in self.transformations],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

```

把 `CompletionSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `CompletionSpec.from_dict`（第 232–276 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompletionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("completion spec must be a mapping")
        allowed = {
            "schema_version", "horizon", "metadata", "slots",
            "state_variables", "transformations", "constraints",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "completion spec contains unknown top-level key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_slots = data.get("slots", [])
        raw_transformations = data.get("transformations", [])
        raw_state_variables = data.get("state_variables", [])
        raw_constraints = data.get("constraints", [])
        for name, value in (
            ("slots", raw_slots),
            ("transformations", raw_transformations),
            ("state_variables", raw_state_variables),
            ("constraints", raw_constraints),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"completion {name} must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("completion metadata must be a mapping")
        return cls(
            slots=[EventSlot.from_dict(item) for item in raw_slots],
            transformations=[
                Transformation.from_dict(item) for item in raw_transformations
            ],
            state_variables=[
                StateVariable.from_dict(item) for item in raw_state_variables
            ],
            constraints=[expr_from_dict(item) for item in raw_constraints],
            horizon=int(data.get("horizon", 8)),
            metadata=metadata,
            schema_version=str(
                data.get("schema_version", COMPLETION_SCHEMA_VERSION)
            ),
        )

```

校验输入字典的键和值，并递归构造 `CompletionSpec` 实例。

## 方法 `CompletionSpec.load`（第 277–280 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "CompletionSpec":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `CompletionSpec`。

## 方法 `CompletionSpec.dump`（第 281–284 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


```

调用 `to_dict` 后把 `CompletionSpec` 安全写成 YAML/JSON。

## 函数 `_reject_duplicates`（第 285–288 行）

```python
def _reject_duplicates(values: list[str], message: str) -> None:
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise SchemaError(f"{message}: {', '.join(duplicates)}")
```

检查给定名称序列是否重复，发现重复时报告带上下文的模式错误。

