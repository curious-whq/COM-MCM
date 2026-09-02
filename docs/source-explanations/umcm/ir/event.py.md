# `umcm/ir/event.py` 源码讲解

文件职责：定义事件模式、事件目录和动态事件实例。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–15 行）

```python
"""Event schemas, catalogs, and dynamic event instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from umcm.errors import SchemaError, SerializationError, TraceValidationError
from umcm.ir.expression import Expr
from umcm.ir.sort import BOOL, INT, Sort
from umcm.serialization import decode_value, dump_data, encode_value, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `EVENT_CATALOG_SCHEMA_VERSION`（第 16–18 行）

```python
EVENT_CATALOG_SCHEMA_VERSION = "umcm.events.v0.1"


```

这是模块级常量或公开导出声明：`EVENT_CATALOG_SCHEMA_VERSION` 保存事件catalogschemaversion，供该对象的校验、转换或序列化逻辑使用。

## 类 `Visibility` 及全部字段（第 19–24 行）

```python
class Visibility(str, Enum):
    INTERNAL = "internal"
    PUBLIC = "public"
    ARCHITECTURAL = "architectural"


```

枚举事件的内部、公开和架构可见级别。

- `INTERNAL`：定义枚举成员，表示事件仅在模块内部可见。
- `PUBLIC`：定义枚举成员，表示事件可供模块外观察。
- `ARCHITECTURAL`：定义枚举成员，表示事件在架构层可见。

## 类 `FieldSpec` 及全部字段（第 25–32 行）

```python
@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    sort: Sort
    required: bool = True
    identity: bool = False
    description: str = ""

```

描述一个事件字段的名称、类型和模式属性。

- `name`：对象或规则的稳定名称。
- `sort`：值或表达式的静态类型。
- `required`：该候选或字段是否必须存在。
- `identity`：该字段是否参与事件身份判定。
- `description`：供人阅读的说明文本。

## 方法 `FieldSpec.__post_init__`（第 33–36 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("field name must be non-empty")

```

在 `FieldSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `FieldSpec.to_dict`（第 37–48 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "sort": self.sort.to_dict(),
            "required": self.required,
        }
        if self.identity:
            data["identity"] = True
        if self.description:
            data["description"] = self.description
        return data

```

把 `FieldSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `FieldSpec.from_dict`（第 49–64 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldSpec":
        if not isinstance(data, Mapping):
            raise SchemaError("field spec must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                sort=Sort.from_dict(data["sort"]),
                required=bool(data.get("required", True)),
                identity=bool(data.get("identity", False)),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SchemaError(f"field spec is missing {exc.args[0]!r}") from exc


```

校验输入字典的键和值，并递归构造 `FieldSpec` 实例。

## 类 `EventType` 及全部字段（第 65–74 行）

```python
@dataclass(frozen=True, slots=True)
class EventType:
    name: str
    module: str
    layer: str
    fields: tuple[FieldSpec, ...] = ()
    visibility: Visibility = Visibility.INTERNAL
    description: str = ""
    tags: tuple[str, ...] = ()

```

描述一种事件的字段模式、层级、可见性和标签。

- `name`：对象或规则的稳定名称。
- `module`：保存模块名，供该对象的校验、转换或序列化逻辑使用。
- `layer`：保存层级名，供该对象的校验、转换或序列化逻辑使用。
- `fields`：字段名到字段值或字段规则的映射。
- `visibility`：事件类型的可见性级别。
- `description`：供人阅读的说明文本。
- `tags`：用于分类和筛选的标签集合。

## 方法 `EventType.__post_init__`（第 75–87 行）

```python
    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise SchemaError(
                "event type name must be qualified, for example 'LSU.TLBMiss'"
            )
        if not self.module:
            raise SchemaError("event type module must be non-empty")
        if not self.layer:
            raise SchemaError("event type layer must be non-empty")
        names = [item.name for item in self.fields]
        if len(names) != len(set(names)):
            raise SchemaError(f"event type {self.name!r} has duplicate fields")

```

在 `EventType` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventType.field_map`（第 88–91 行）

```python
    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {item.name: item for item in self.fields}

```

构造字段名到字段模式的映射，供事件校验和类型查询使用。

## 方法 `EventType.to_dict`（第 92–105 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "module": self.module,
            "layer": self.layer,
            "visibility": self.visibility.value,
            "fields": [item.to_dict() for item in self.fields],
        }
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

```

把 `EventType` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `EventType.from_dict`（第 106–128 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventType":
        if not isinstance(data, Mapping):
            raise SchemaError("event type must be a mapping")
        try:
            raw_fields = data.get("fields", [])
            if not isinstance(raw_fields, list):
                raise SchemaError("event type fields must be a list")
            return cls(
                name=str(data["name"]),
                module=str(data["module"]),
                layer=str(data["layer"]),
                fields=tuple(FieldSpec.from_dict(item) for item in raw_fields),
                visibility=Visibility(str(data.get("visibility", "internal"))),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SchemaError(f"event type is missing {exc.args[0]!r}") from exc
        except ValueError as exc:
            raise SchemaError(str(exc)) from exc


```

校验输入字典的键和值，并递归构造 `EventType` 实例。

## 类 `EventInstance` 及全部字段（第 129–137 行）

```python
@dataclass(slots=True)
class EventInstance:
    id: str
    event_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    cycle: int | Expr | None = None
    occurs: bool | Expr = True
    annotations: dict[str, Any] = field(default_factory=dict)

```

表示轨迹中的一个动态事件及其观测字段。

- `id`：对象的稳定标识符。
- `event_type`：关联的事件类型名称。
- `fields`：字段名到字段值或字段规则的映射。
- `cycle`：事件发生周期或诊断环。
- `occurs`：事件是否实际发生，未知时可由求解器决定。
- `annotations`：随对象保留的附加注解。

## 方法 `EventInstance.__post_init__`（第 138–146 行）

```python
    def __post_init__(self) -> None:
        if not self.id:
            raise TraceValidationError("event id must be non-empty")
        if not self.event_type:
            raise TraceValidationError("event_type must be non-empty")
        self.fields = dict(self.fields)
        self.annotations = dict(self.annotations)
        self._validate_common_attributes()

```

在 `EventInstance` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventInstance._validate_common_attributes`（第 147–162 行）

```python
    def _validate_common_attributes(self) -> None:
        if isinstance(self.cycle, int):
            if isinstance(self.cycle, bool) or self.cycle < 0:
                raise TraceValidationError("event cycle must be a non-negative int")
        elif isinstance(self.cycle, Expr):
            if not self.cycle.sort.compatible_with(INT):
                raise TraceValidationError("symbolic event cycle must have int sort")
        elif self.cycle is not None:
            raise TraceValidationError("event cycle must be int, Expr, or null")

        if isinstance(self.occurs, Expr):
            if not self.occurs.sort.compatible_with(BOOL):
                raise TraceValidationError("symbolic occurs must have bool sort")
        elif not isinstance(self.occurs, bool):
            raise TraceValidationError("occurs must be bool or Expr")

```

检查 `EventInstance` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `EventInstance.validate_against`（第 163–198 行）

```python
    def validate_against(self, event_type: EventType, *, partial: bool) -> None:
        if self.event_type != event_type.name:
            raise TraceValidationError(
                f"event {self.id!r} has type {self.event_type!r}, expected {event_type.name!r}"
            )

        specs = event_type.field_map
        unknown = set(self.fields) - set(specs)
        if unknown:
            raise TraceValidationError(
                f"event {self.id!r} has unknown field(s): {', '.join(sorted(unknown))}"
            )

        if not partial:
            missing = [
                spec.name
                for spec in event_type.fields
                if spec.required and spec.name not in self.fields
            ]
            if missing:
                raise TraceValidationError(
                    f"event {self.id!r} is missing required field(s): {', '.join(missing)}"
                )

        for name, value in self.fields.items():
            spec = specs[name]
            if isinstance(value, Expr):
                if not value.sort.compatible_with(spec.sort):
                    raise TraceValidationError(
                        f"event {self.id!r}.{name} expects {spec.sort}, got {value.sort}"
                    )
            elif not spec.sort.accepts_literal(value):
                raise TraceValidationError(
                    f"event {self.id!r}.{name} value {value!r} is invalid for {spec.sort}"
                )

```

检查 `EventInstance` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `EventInstance.to_dict`（第 199–211 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.event_type,
            "occurs": encode_value(self.occurs),
            "fields": encode_value(self.fields),
        }
        if self.cycle is not None:
            data["cycle"] = encode_value(self.cycle)
        if self.annotations:
            data["annotations"] = encode_value(self.annotations)
        return data

```

把 `EventInstance` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `EventInstance.from_dict`（第 212–234 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventInstance":
        if not isinstance(data, Mapping):
            raise SerializationError("event instance must be a mapping")
        try:
            fields = decode_value(data.get("fields", {}))
            annotations = decode_value(data.get("annotations", {}))
            if not isinstance(fields, dict):
                raise SerializationError("event fields must be a mapping")
            if not isinstance(annotations, dict):
                raise SerializationError("event annotations must be a mapping")
            return cls(
                id=str(data["id"]),
                event_type=str(data["type"]),
                fields=fields,
                cycle=decode_value(data.get("cycle")),
                occurs=decode_value(data.get("occurs", True)),
                annotations=annotations,
            )
        except KeyError as exc:
            raise SerializationError(f"event instance is missing {exc.args[0]!r}") from exc


```

校验输入字典的键和值，并递归构造 `EventInstance` 实例。

## 类 `EventCatalog` 及全部字段（第 235–240 行）

```python
@dataclass(slots=True)
class EventCatalog:
    event_types: dict[str, EventType] = field(default_factory=dict)
    schema_version: str = EVENT_CATALOG_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

```

管理事件类型并负责事件集合的模式校验。

- `event_types`：事件类型定义或筛选集合。
- `schema_version`：序列化模式版本。
- `metadata`：不参与核心语义的扩展元数据。

## 方法 `EventCatalog.__post_init__`（第 241–249 行）

```python
    def __post_init__(self) -> None:
        self.event_types = dict(self.event_types)
        self.metadata = dict(self.metadata)
        for name, event_type in self.event_types.items():
            if name != event_type.name:
                raise SchemaError(
                    f"catalog key {name!r} does not match event type name {event_type.name!r}"
                )

```

在 `EventCatalog` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventCatalog.register`（第 250–254 行）

```python
    def register(self, event_type: EventType) -> None:
        if event_type.name in self.event_types:
            raise SchemaError(f"duplicate event type: {event_type.name}")
        self.event_types[event_type.name] = event_type

```

校验名称未登记后把新事件类型加入目录。

## 方法 `EventCatalog.resolve`（第 255–260 行）

```python
    def resolve(self, name: str) -> EventType:
        try:
            return self.event_types[name]
        except KeyError as exc:
            raise TraceValidationError(f"unknown event type: {name}") from exc

```

按名称解析事件类型；未知类型抛出带名称的模式错误。

## 方法 `EventCatalog.validate_events`（第 261–264 行）

```python
    def validate_events(self, events: Iterable[EventInstance], *, partial: bool) -> None:
        for event in events:
            event.validate_against(self.resolve(event.event_type), partial=partial)

```

逐个调用事件实例的模式校验，确保整个集合符合目录。

## 方法 `EventCatalog.to_dict`（第 265–274 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "metadata": encode_value(self.metadata),
            "events": [
                self.event_types[name].to_dict()
                for name in sorted(self.event_types)
            ],
        }

```

把 `EventCatalog` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `EventCatalog.from_dict`（第 275–296 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventCatalog":
        if not isinstance(data, Mapping):
            raise SerializationError("event catalog must be a mapping")
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            raise SerializationError("event catalog events must be a list")
        event_types: dict[str, EventType] = {}
        for item in raw_events:
            event_type = EventType.from_dict(item)
            if event_type.name in event_types:
                raise SchemaError(f"duplicate event type: {event_type.name}")
            event_types[event_type.name] = event_type
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("event catalog metadata must be a mapping")
        return cls(
            event_types=event_types,
            schema_version=str(data.get("schema_version", EVENT_CATALOG_SCHEMA_VERSION)),
            metadata=metadata,
        )

```

校验输入字典的键和值，并递归构造 `EventCatalog` 实例。

## 方法 `EventCatalog.load`（第 297–300 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "EventCatalog":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `EventCatalog`。

## 方法 `EventCatalog.dump`（第 301–302 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
```

调用 `to_dict` 后把 `EventCatalog` 安全写成 YAML/JSON。

