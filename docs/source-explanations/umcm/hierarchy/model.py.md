# `umcm/hierarchy/model.py` 源码讲解

文件职责：定义层次抽象规则的可序列化配置模型。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–18 行）

```python
"""Loadable hierarchy and trace-abstraction specifications.

The abstraction language is intentionally small.  A rule matches one or more
concrete events, unifies selected fields through ``$variables``, and emits one
summary event.  The result is itself a normal :class:`~umcm.ir.trace.Trace`, so
several abstraction levels can be applied in sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import AbstractionError, SerializationError
from umcm.serialization import decode_value, dump_data, encode_value, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `ABSTRACTION_SCHEMA_VERSION`（第 19–21 行）

```python
ABSTRACTION_SCHEMA_VERSION = "umcm.abstraction.v0.1"


```

这是模块级常量或公开导出声明：`ABSTRACTION_SCHEMA_VERSION` 保存abstractionschemaversion，供该对象的校验、转换或序列化逻辑使用。

## 函数 `_unknown_keys`（第 22–29 行）

```python
def _unknown_keys(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise SerializationError(
            f"{context} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


```

计算输入映射中模式未声明的键，用于严格拒绝拼写错误和多余配置。

## 类 `MatchValue` 及全部字段（第 30–37 行）

```python
@dataclass(frozen=True, slots=True)
class MatchValue:
    """A role-field pattern: either a unification variable or a literal."""

    variable: str | None = None
    literal: Any = None
    is_literal: bool = False

```

表示角色字段模式中的变量或字面量。

- `variable`：字段统一匹配时绑定的变量名。
- `literal`：匹配模式直接要求的字面量。
- `is_literal`：当前匹配值是否应按字面量而非变量解释。

## 方法 `MatchValue.__post_init__`（第 38–46 行）

```python
    def __post_init__(self) -> None:
        if self.variable is not None:
            if not self.variable:
                raise AbstractionError("abstraction variable must be non-empty")
            if self.is_literal:
                raise AbstractionError("match value cannot be variable and literal")
        elif not self.is_literal:
            raise AbstractionError("match value must be variable or literal")

```

在 `MatchValue` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `MatchValue.from_data`（第 47–58 行）

```python
    @classmethod
    def from_data(cls, data: Any) -> "MatchValue":
        if isinstance(data, str) and data.startswith("$"):
            return cls(variable=data[1:])
        if isinstance(data, Mapping):
            if set(data) != {"literal"}:
                raise SerializationError(
                    "abstraction match mapping must contain only 'literal'"
                )
            return cls(literal=decode_value(data["literal"]), is_literal=True)
        return cls(literal=decode_value(data), is_literal=True)

```

识别紧凑配置值的形式并构造对应的 `MatchValue`。

## 方法 `MatchValue.to_data`（第 59–66 行）

```python
    def to_data(self) -> Any:
        if self.variable is not None:
            return f"${self.variable}"
        if isinstance(self.literal, str) and self.literal.startswith("$"):
            return {"literal": encode_value(self.literal)}
        return encode_value(self.literal)


```

把 `MatchValue` 转回其紧凑配置表示，保留变量、引用和字面量的区别。

## 类 `OutputValue` 及全部字段（第 67–73 行）

```python
@dataclass(frozen=True, slots=True)
class OutputValue:
    """A summary-field value drawn from a binding, role field, or literal."""

    kind: str
    value: Any

```

表示摘要字段从绑定、角色字段或字面量取值的方式。

- `kind`：节点、操作、公理或输出值的类别。
- `value`：该节点、字段或状态写入承载的值。

## 方法 `OutputValue.__post_init__`（第 74–79 行）

```python
    def __post_init__(self) -> None:
        if self.kind not in {"variable", "field", "literal"}:
            raise AbstractionError(f"unsupported output value kind: {self.kind}")
        if self.kind in {"variable", "field"} and not str(self.value):
            raise AbstractionError(f"{self.kind} output reference must be non-empty")

```

在 `OutputValue` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `OutputValue.from_data`（第 80–93 行）

```python
    @classmethod
    def from_data(cls, data: Any) -> "OutputValue":
        if isinstance(data, str) and data.startswith("$"):
            return cls("variable", data[1:])
        if isinstance(data, Mapping):
            if set(data) == {"from"}:
                return cls("field", str(data["from"]))
            if set(data) == {"literal"}:
                return cls("literal", decode_value(data["literal"]))
            raise SerializationError(
                "abstraction output mapping must contain exactly 'from' or 'literal'"
            )
        return cls("literal", decode_value(data))

```

识别紧凑配置值的形式并构造对应的 `OutputValue`。

## 方法 `OutputValue.to_data`（第 94–103 行）

```python
    def to_data(self) -> Any:
        if self.kind == "variable":
            return f"${self.value}"
        if self.kind == "field":
            return {"from": self.value}
        if isinstance(self.value, str) and self.value.startswith("$"):
            return {"literal": encode_value(self.value)}
        return encode_value(self.value)


```

把 `OutputValue` 转回其紧凑配置表示，保留变量、引用和字面量的区别。

## 类 `EventRoleSpec` 及全部字段（第 104–109 行）

```python
@dataclass(frozen=True, slots=True)
class EventRoleSpec:
    name: str
    event_type: str
    fields: Mapping[str, MatchValue] = field(default_factory=dict)

```

描述摘要规则中的一个事件角色及字段匹配模式。

- `name`：对象或规则的稳定名称。
- `event_type`：关联的事件类型名称。
- `fields`：字段名到字段值或字段规则的映射。

## 方法 `EventRoleSpec.__post_init__`（第 110–116 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("abstraction role name must be non-empty")
        if not self.event_type:
            raise AbstractionError("abstraction role event_type must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))

```

在 `EventRoleSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventRoleSpec.from_dict`（第 117–138 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRoleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("abstraction role must be a mapping")
        _unknown_keys(data, {"name", "event_type", "fields"}, "abstraction role")
        raw_fields = data.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            raise SerializationError("abstraction role fields must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                event_type=str(data["event_type"]),
                fields={
                    str(name): MatchValue.from_data(value)
                    for name, value in raw_fields.items()
                },
            )
        except KeyError as exc:
            raise SerializationError(
                f"abstraction role is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `EventRoleSpec` 实例。

## 方法 `EventRoleSpec.to_dict`（第 139–148 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event_type": self.event_type,
            "fields": {
                name: value.to_data() for name, value in self.fields.items()
            },
        }


```

把 `EventRoleSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `SummaryEventSpec` 及全部字段（第 149–156 行）

```python
@dataclass(frozen=True, slots=True)
class SummaryEventSpec:
    event_type: str
    id_template: str
    fields: Mapping[str, OutputValue]
    cycle_from: str = "last"
    annotations: Mapping[str, Any] = field(default_factory=dict)

```

描述摘要事件的类型、标识模板、字段和注解。

- `event_type`：关联的事件类型名称。
- `id_template`：使用绑定值生成摘要事件 ID 的格式模板。
- `fields`：字段名到字段值或字段规则的映射。
- `cycle_from`：提供摘要事件周期的源角色名。
- `annotations`：随对象保留的附加注解。

## 方法 `SummaryEventSpec.__post_init__`（第 157–166 行）

```python
    def __post_init__(self) -> None:
        if not self.event_type:
            raise AbstractionError("summary event_type must be non-empty")
        if not self.id_template:
            raise AbstractionError("summary id_template must be non-empty")
        if not self.cycle_from:
            raise AbstractionError("summary cycle_from must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))
        object.__setattr__(self, "annotations", dict(self.annotations))

```

在 `SummaryEventSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `SummaryEventSpec.from_dict`（第 167–197 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SummaryEventSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("summary output must be a mapping")
        _unknown_keys(
            data,
            {"event_type", "id", "fields", "cycle_from", "annotations"},
            "summary output",
        )
        raw_fields = data.get("fields", {})
        raw_annotations = decode_value(data.get("annotations", {}))
        if not isinstance(raw_fields, Mapping):
            raise SerializationError("summary output fields must be a mapping")
        if not isinstance(raw_annotations, Mapping):
            raise SerializationError("summary output annotations must be a mapping")
        try:
            return cls(
                event_type=str(data["event_type"]),
                id_template=str(data["id"]),
                fields={
                    str(name): OutputValue.from_data(value)
                    for name, value in raw_fields.items()
                },
                cycle_from=str(data.get("cycle_from", "last")),
                annotations=dict(raw_annotations),
            )
        except KeyError as exc:
            raise SerializationError(
                f"summary output is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `SummaryEventSpec` 实例。

## 方法 `SummaryEventSpec.to_dict`（第 198–211 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "event_type": self.event_type,
            "id": self.id_template,
            "cycle_from": self.cycle_from,
            "fields": {
                name: value.to_data() for name, value in self.fields.items()
            },
        }
        if self.annotations:
            data["annotations"] = encode_value(dict(self.annotations))
        return data


```

把 `SummaryEventSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `SummaryRuleSpec` 及全部字段（第 212–223 行）

```python
@dataclass(frozen=True, slots=True)
class SummaryRuleSpec:
    name: str
    roles: tuple[EventRoleSpec, ...]
    output: SummaryEventSpec
    ordered: bool = True
    strict_order: bool = False
    distinct_events: bool = True
    hide_sources: bool = True
    min_matches: int = 0
    max_matches: int = 10_000

```

描述多角色匹配、输出摘要和源事件隐藏策略。

- `name`：对象或规则的稳定名称。
- `roles`：摘要规则需要共同匹配的事件角色。
- `output`：摘要规则生成的事件声明。
- `ordered`：控制或记录“顺序匹配”语义的布尔标志。
- `strict_order`：角色匹配周期是否必须严格递增。
- `distinct_events`：是否要求不同角色绑定到不同事件。
- `hide_sources`：生成摘要后是否隐藏参与匹配的源事件。
- `min_matches`：一条摘要规则至少必须找到的匹配数。
- `max_matches`：一条摘要规则最多允许采用的匹配数。

## 方法 `SummaryRuleSpec.__post_init__`（第 224–236 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("summary rule name must be non-empty")
        if not self.roles:
            raise AbstractionError(f"summary rule {self.name!r} needs at least one role")
        names = [role.name for role in self.roles]
        if len(names) != len(set(names)):
            raise AbstractionError(f"summary rule {self.name!r} has duplicate roles")
        if self.min_matches < 0:
            raise AbstractionError("summary min_matches cannot be negative")
        if self.max_matches <= 0 or self.max_matches < self.min_matches:
            raise AbstractionError("summary max_matches is invalid")

```

在 `SummaryRuleSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `SummaryRuleSpec.from_dict`（第 237–275 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SummaryRuleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("summary rule must be a mapping")
        _unknown_keys(
            data,
            {
                "name",
                "roles",
                "output",
                "ordered",
                "strict_order",
                "distinct_events",
                "hide_sources",
                "min_matches",
                "max_matches",
            },
            "summary rule",
        )
        raw_roles = data.get("roles", [])
        if not isinstance(raw_roles, list):
            raise SerializationError("summary rule roles must be a list")
        try:
            return cls(
                name=str(data["name"]),
                roles=tuple(EventRoleSpec.from_dict(item) for item in raw_roles),
                output=SummaryEventSpec.from_dict(data["output"]),
                ordered=bool(data.get("ordered", True)),
                strict_order=bool(data.get("strict_order", False)),
                distinct_events=bool(data.get("distinct_events", True)),
                hide_sources=bool(data.get("hide_sources", True)),
                min_matches=int(data.get("min_matches", 0)),
                max_matches=int(data.get("max_matches", 10_000)),
            )
        except KeyError as exc:
            raise SerializationError(
                f"summary rule is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `SummaryRuleSpec` 实例。

## 方法 `SummaryRuleSpec.to_dict`（第 276–289 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": [role.to_dict() for role in self.roles],
            "output": self.output.to_dict(),
            "ordered": self.ordered,
            "strict_order": self.strict_order,
            "distinct_events": self.distinct_events,
            "hide_sources": self.hide_sources,
            "min_matches": self.min_matches,
            "max_matches": self.max_matches,
        }


```

把 `SummaryRuleSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `RetainSpec` 及全部字段（第 290–295 行）

```python
@dataclass(frozen=True, slots=True)
class RetainSpec:
    event_types: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    visibilities: tuple[str, ...] = ()

```

描述抽象时按类型、标识或可见性保留哪些事件。

- `event_types`：事件类型定义或筛选集合。
- `event_ids`：显式选择的事件 ID 集合。
- `visibilities`：显式保留的事件可见性级别集合。

## 方法 `RetainSpec.from_dict`（第 296–309 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RetainSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("retain must be a mapping")
        _unknown_keys(data, {"event_types", "event_ids", "visibilities"}, "retain")
        for field_name in ("event_types", "event_ids", "visibilities"):
            if not isinstance(data.get(field_name, []), list):
                raise SerializationError(f"retain.{field_name} must be a list")
        return cls(
            event_types=tuple(str(item) for item in data.get("event_types", [])),
            event_ids=tuple(str(item) for item in data.get("event_ids", [])),
            visibilities=tuple(str(item) for item in data.get("visibilities", [])),
        )

```

校验输入字典的键和值，并递归构造 `RetainSpec` 实例。

## 方法 `RetainSpec.to_dict`（第 310–317 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": list(self.event_types),
            "event_ids": list(self.event_ids),
            "visibilities": list(self.visibilities),
        }


```

把 `RetainSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `AbstractionSpec` 及全部字段（第 318–329 行）

```python
@dataclass(slots=True)
class AbstractionSpec:
    name: str
    source_level: str
    target_level: str
    retain: RetainSpec = field(default_factory=RetainSpec)
    summaries: tuple[SummaryRuleSpec, ...] = ()
    default_action: str = "hide"
    retain_metadata: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = ABSTRACTION_SCHEMA_VERSION

```

聚合一层到另一层的保留规则、摘要规则和元数据。

- `name`：对象或规则的稳定名称。
- `source_level`：抽象规则接受的源层级名称。
- `target_level`：抽象规则产生的目标层级名称。
- `retain`：抽象时显式保留事件的筛选配置。
- `summaries`：摘要规则或抽象证书中的摘要证据集合。
- `default_action`：未被规则命中时对事件采取保留或丢弃的动作。
- `retain_metadata`：是否把源轨迹元数据复制到抽象轨迹。
- `metadata`：不参与核心语义的扩展元数据。
- `schema_version`：序列化模式版本。

## 方法 `AbstractionSpec.__post_init__`（第 330–341 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("abstraction name must be non-empty")
        if not self.source_level or not self.target_level:
            raise AbstractionError("source_level and target_level must be non-empty")
        if self.default_action not in {"hide", "keep"}:
            raise AbstractionError("default_action must be 'hide' or 'keep'")
        names = [rule.name for rule in self.summaries]
        if len(names) != len(set(names)):
            raise AbstractionError("duplicate abstraction summary rule name")
        self.metadata = dict(self.metadata)

```

在 `AbstractionSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `AbstractionSpec.from_dict`（第 342–390 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbstractionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("abstraction spec must be a mapping")
        _unknown_keys(
            data,
            {
                "schema_version",
                "name",
                "source_level",
                "target_level",
                "default_action",
                "retain",
                "retain_metadata",
                "summaries",
                "metadata",
            },
            "abstraction spec",
        )
        raw_summaries = data.get("summaries", [])
        raw_retain_metadata = data.get("retain_metadata", [])
        raw_metadata = decode_value(data.get("metadata", {}))
        if not isinstance(raw_summaries, list):
            raise SerializationError("abstraction summaries must be a list")
        if not isinstance(raw_retain_metadata, list):
            raise SerializationError("retain_metadata must be a list")
        if not isinstance(raw_metadata, Mapping):
            raise SerializationError("abstraction metadata must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                source_level=str(data["source_level"]),
                target_level=str(data["target_level"]),
                retain=RetainSpec.from_dict(data.get("retain", {})),
                summaries=tuple(
                    SummaryRuleSpec.from_dict(item) for item in raw_summaries
                ),
                default_action=str(data.get("default_action", "hide")),
                retain_metadata=tuple(str(item) for item in raw_retain_metadata),
                metadata=dict(raw_metadata),
                schema_version=str(
                    data.get("schema_version", ABSTRACTION_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"abstraction spec is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `AbstractionSpec` 实例。

## 方法 `AbstractionSpec.to_dict`（第 391–403 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "source_level": self.source_level,
            "target_level": self.target_level,
            "default_action": self.default_action,
            "retain": self.retain.to_dict(),
            "retain_metadata": list(self.retain_metadata),
            "summaries": [rule.to_dict() for rule in self.summaries],
            "metadata": encode_value(dict(self.metadata)),
        }

```

把 `AbstractionSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `AbstractionSpec.load`（第 404–407 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "AbstractionSpec":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `AbstractionSpec`。

## 方法 `AbstractionSpec.dump`（第 408–409 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
```

调用 `to_dict` 后把 `AbstractionSpec` 安全写成 YAML/JSON。

