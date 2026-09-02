# `umcm/graph/model.py` 源码讲解

文件职责：定义可加载的投影规则、派生关系和公理模型。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–12 行）

```python
"""Loadable architectural projection, relation, and axiom specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import AxiomError, SerializationError
from umcm.serialization import dump_data, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `GRAPH_MODEL_SCHEMA_VERSION`（第 13–15 行）

```python
GRAPH_MODEL_SCHEMA_VERSION = "umcm.graph_model.v0.2"


```

这是模块级常量或公开导出声明：`GRAPH_MODEL_SCHEMA_VERSION` 保存graph模型schemaversion，供该对象的校验、转换或序列化逻辑使用。

## 函数 `_unknown_keys`（第 16–23 行）

```python
def _unknown_keys(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise SerializationError(
            f"{context} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


```

计算输入映射中模式未声明的键，用于严格拒绝拼写错误和多余配置。

## 类 `RFHintSpec` 及全部字段（第 24–31 行）

```python
@dataclass(frozen=True, slots=True)
class RFHintSpec:
    event_type: str
    read_id_field: str = "op_id"
    write_id_field: str = "source_op_id"
    address_field: str = "address"
    value_field: str = "value"

```

描述如何从具体事件中读取读源提示。

- `event_type`：关联的事件类型名称。
- `read_id_field`：读源提示中保存读操作 ID 的字段名。
- `write_id_field`：读源提示中保存写操作 ID 的字段名。
- `address_field`：指定从事件中读取“address”时使用的字段名。
- `value_field`：指定从事件中读取“value”时使用的字段名。

## 方法 `RFHintSpec.from_dict`（第 32–57 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RFHintSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("rf hint must be a mapping")
        _unknown_keys(
            data,
            {
                "event_type",
                "read_id_field",
                "write_id_field",
                "address_field",
                "value_field",
            },
            "rf hint",
        )
        try:
            return cls(
                event_type=str(data["event_type"]),
                read_id_field=str(data.get("read_id_field", "op_id")),
                write_id_field=str(data.get("write_id_field", "source_op_id")),
                address_field=str(data.get("address_field", "address")),
                value_field=str(data.get("value_field", "value")),
            )
        except KeyError as exc:
            raise SerializationError("rf hint requires event_type") from exc

```

校验输入字典的键和值，并递归构造 `RFHintSpec` 实例。

## 方法 `RFHintSpec.to_dict`（第 58–67 行）

```python
    def to_dict(self) -> dict[str, str]:
        return {
            "event_type": self.event_type,
            "read_id_field": self.read_id_field,
            "write_id_field": self.write_id_field,
            "address_field": self.address_field,
            "value_field": self.value_field,
        }


```

把 `RFHintSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `COHintSpec` 及全部字段（第 68–76 行）

```python
@dataclass(frozen=True, slots=True)
class COHintSpec:
    """A concrete trace event that fixes one coherence-order edge."""

    event_type: str
    before_write_id_field: str = "before_write_id"
    after_write_id_field: str = "after_write_id"
    address_field: str = "address"

```

描述如何从具体事件中读取一条相干序边提示。

- `event_type`：关联的事件类型名称。
- `before_write_id_field`：指定从事件中读取“前置写操作标识符”时使用的字段名。
- `after_write_id_field`：指定从事件中读取“后继写操作标识符”时使用的字段名。
- `address_field`：指定从事件中读取“address”时使用的字段名。

## 方法 `COHintSpec.from_dict`（第 77–104 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "COHintSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("co hint must be a mapping")
        _unknown_keys(
            data,
            {
                "event_type",
                "before_write_id_field",
                "after_write_id_field",
                "address_field",
            },
            "co hint",
        )
        try:
            return cls(
                event_type=str(data["event_type"]),
                before_write_id_field=str(
                    data.get("before_write_id_field", "before_write_id")
                ),
                after_write_id_field=str(
                    data.get("after_write_id_field", "after_write_id")
                ),
                address_field=str(data.get("address_field", "address")),
            )
        except KeyError as exc:
            raise SerializationError("co hint requires event_type") from exc

```

校验输入字典的键和值，并递归构造 `COHintSpec` 实例。

## 方法 `COHintSpec.to_dict`（第 105–113 行）

```python
    def to_dict(self) -> dict[str, str]:
        return {
            "event_type": self.event_type,
            "before_write_id_field": self.before_write_id_field,
            "after_write_id_field": self.after_write_id_field,
            "address_field": self.address_field,
        }


```

把 `COHintSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `ProjectionSpec` 及全部字段（第 114–128 行）

```python
@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    init_write_event: str
    load_event: str
    store_event: str
    load_commit_event: str
    id_field: str = "op_id"
    address_field: str = "address"
    value_field: str = "value"
    hart_field: str = "hart"
    program_index_field: str = "program_index"
    require_committed_loads: bool = True
    rf_hints: tuple[RFHintSpec, ...] = ()
    co_hints: tuple[COHintSpec, ...] = ()

```

描述把具体事件投影成内存操作时使用的类型名和字段名。

- `init_write_event`：投影为初始写的事件类型名。
- `load_event`：投影为读操作的事件类型名。
- `store_event`：投影为普通写操作的事件类型名。
- `load_commit_event`：用于确认读已提交的事件类型名。
- `id_field`：投影时读取操作 ID 所用的事件字段名。
- `address_field`：指定从事件中读取“address”时使用的字段名。
- `value_field`：指定从事件中读取“value”时使用的字段名。
- `hart_field`：投影时读取 hart 标识所用的事件字段名。
- `program_index_field`：投影时读取程序序位置所用的事件字段名。
- `require_committed_loads`：是否只投影能够找到提交事件的读。
- `rf_hints`：从具体事件读取读源提示的配置。
- `co_hints`：从具体事件读取相干序提示的配置。

## 方法 `ProjectionSpec.from_dict`（第 129–180 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("projection must be a mapping")
        _unknown_keys(
            data,
            {
                "init_write_event",
                "load_event",
                "store_event",
                "load_commit_event",
                "id_field",
                "address_field",
                "value_field",
                "hart_field",
                "program_index_field",
                "require_committed_loads",
                "rf_hints",
                "co_hints",
            },
            "projection",
        )
        raw_hints = data.get("rf_hints", [])
        raw_co_hints = data.get("co_hints", [])
        if not isinstance(raw_hints, list):
            raise SerializationError("projection.rf_hints must be a list")
        if not isinstance(raw_co_hints, list):
            raise SerializationError("projection.co_hints must be a list")
        try:
            return cls(
                init_write_event=str(data["init_write_event"]),
                load_event=str(data["load_event"]),
                store_event=str(data["store_event"]),
                load_commit_event=str(data["load_commit_event"]),
                id_field=str(data.get("id_field", "op_id")),
                address_field=str(data.get("address_field", "address")),
                value_field=str(data.get("value_field", "value")),
                hart_field=str(data.get("hart_field", "hart")),
                program_index_field=str(
                    data.get("program_index_field", "program_index")
                ),
                require_committed_loads=bool(
                    data.get("require_committed_loads", True)
                ),
                rf_hints=tuple(RFHintSpec.from_dict(item) for item in raw_hints),
                co_hints=tuple(COHintSpec.from_dict(item) for item in raw_co_hints),
            )
        except KeyError as exc:
            raise SerializationError(
                f"projection is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `ProjectionSpec` 实例。

## 方法 `ProjectionSpec.to_dict`（第 181–197 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "init_write_event": self.init_write_event,
            "load_event": self.load_event,
            "store_event": self.store_event,
            "load_commit_event": self.load_commit_event,
            "id_field": self.id_field,
            "address_field": self.address_field,
            "value_field": self.value_field,
            "hart_field": self.hart_field,
            "program_index_field": self.program_index_field,
            "require_committed_loads": self.require_committed_loads,
            "rf_hints": [item.to_dict() for item in self.rf_hints],
            "co_hints": [item.to_dict() for item in self.co_hints],
        }


```

把 `ProjectionSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `DerivedRelationSpec` 及全部字段（第 198–203 行）

```python
@dataclass(frozen=True, slots=True)
class DerivedRelationSpec:
    name: str
    op: str
    relations: tuple[str, ...]

```

描述通过逆、并、交、差、复合或闭包生成命名关系的规则。

- `name`：对象或规则的稳定名称。
- `op`：表达式、关系或状态比较使用的运算符。
- `relations`：命名关系或参与运算的关系集合。

## 方法 `DerivedRelationSpec.__post_init__`（第 204–223 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise AxiomError("derived relation name must be non-empty")
        if self.op not in {
            "union",
            "intersection",
            "difference",
            "inverse",
            "compose",
            "transitive_closure",
        }:
            raise AxiomError(f"unsupported derived relation op: {self.op}")
        arity = len(self.relations)
        if self.op in {"inverse", "transitive_closure"} and arity != 1:
            raise AxiomError(f"{self.op} requires exactly one relation")
        if self.op in {"intersection", "difference", "compose"} and arity != 2:
            raise AxiomError(f"{self.op} requires exactly two relations")
        if self.op == "union" and arity < 1:
            raise AxiomError("union requires at least one relation")

```

在 `DerivedRelationSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `DerivedRelationSpec.from_dict`（第 224–242 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DerivedRelationSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("derived relation must be a mapping")
        _unknown_keys(data, {"name", "op", "relations"}, "derived relation")
        raw_relations = data.get("relations", [])
        if not isinstance(raw_relations, list):
            raise SerializationError("derived relation relations must be a list")
        try:
            return cls(
                name=str(data["name"]),
                op=str(data["op"]),
                relations=tuple(str(item) for item in raw_relations),
            )
        except KeyError as exc:
            raise SerializationError(
                f"derived relation is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `DerivedRelationSpec` 实例。

## 方法 `DerivedRelationSpec.to_dict`（第 243–246 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "op": self.op, "relations": list(self.relations)}


```

把 `DerivedRelationSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `AxiomSpec` 及全部字段（第 247–253 行）

```python
@dataclass(frozen=True, slots=True)
class AxiomSpec:
    name: str
    kind: str
    relations: tuple[str, ...]
    description: str = ""

```

描述一条关系公理的名称、种类和参与关系。

- `name`：对象或规则的稳定名称。
- `kind`：节点、操作、公理或输出值的类别。
- `relations`：命名关系或参与运算的关系集合。
- `description`：供人阅读的说明文本。

## 方法 `AxiomSpec.__post_init__`（第 254–261 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise AxiomError("axiom name must be non-empty")
        if self.kind not in {"acyclic", "irreflexive", "empty"}:
            raise AxiomError(f"unsupported axiom kind: {self.kind}")
        if not self.relations:
            raise AxiomError(f"axiom {self.name!r} needs at least one relation")

```

在 `AxiomSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `AxiomSpec.from_dict`（第 262–279 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AxiomSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("axiom must be a mapping")
        _unknown_keys(data, {"name", "kind", "relations", "description"}, "axiom")
        raw_relations = data.get("relations", [])
        if not isinstance(raw_relations, list):
            raise SerializationError("axiom relations must be a list")
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                relations=tuple(str(item) for item in raw_relations),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(f"axiom is missing {exc.args[0]!r}") from exc

```

校验输入字典的键和值，并递归构造 `AxiomSpec` 实例。

## 方法 `AxiomSpec.to_dict`（第 280–290 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "relations": list(self.relations),
        }
        if self.description:
            data["description"] = self.description
        return data


```

把 `AxiomSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `GraphModelSpec` 及全部字段（第 291–300 行）

```python
@dataclass(slots=True)
class GraphModelSpec:
    model: str
    projection: ProjectionSpec
    derived_relations: tuple[DerivedRelationSpec, ...] = ()
    axioms: tuple[AxiomSpec, ...] = ()
    ppo_rules: tuple[str, ...] = ("load_load_different_write",)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = GRAPH_MODEL_SCHEMA_VERSION

```

聚合投影配置、派生关系、PPO 规则和内存模型公理。

- `model`：内存模型的稳定名称。
- `projection`：具体事件到架构内存操作的投影配置。
- `derived_relations`：按基础关系计算的命名派生关系规则。
- `axioms`：逐条公理的检查结果或配置。
- `ppo_rules`：从程序序筛选保留程序序的操作种类规则。
- `metadata`：不参与核心语义的扩展元数据。
- `schema_version`：序列化模式版本。

## 方法 `GraphModelSpec.__post_init__`（第 301–317 行）

```python
    def __post_init__(self) -> None:
        if not self.model:
            raise AxiomError("graph model name must be non-empty")
        self.metadata = dict(self.metadata)
        supported = {"load_load_different_write"}
        unknown = set(self.ppo_rules) - supported
        if unknown:
            raise AxiomError(
                f"unsupported ppo rule(s): {', '.join(sorted(unknown))}"
            )
        names = [item.name for item in self.derived_relations]
        if len(names) != len(set(names)):
            raise AxiomError("duplicate derived relation name")
        axiom_names = [item.name for item in self.axioms]
        if len(axiom_names) != len(set(axiom_names)):
            raise AxiomError("duplicate axiom name")

```

在 `GraphModelSpec` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `GraphModelSpec.from_dict`（第 318–365 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphModelSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("graph model must be a mapping")
        _unknown_keys(
            data,
            {
                "schema_version",
                "model",
                "metadata",
                "projection",
                "ppo_rules",
                "derived_relations",
                "axioms",
            },
            "graph model",
        )
        raw_derived = data.get("derived_relations", [])
        raw_axioms = data.get("axioms", [])
        raw_ppo = data.get("ppo_rules", ["load_load_different_write"])
        metadata = data.get("metadata", {})
        if not isinstance(raw_derived, list):
            raise SerializationError("derived_relations must be a list")
        if not isinstance(raw_axioms, list):
            raise SerializationError("axioms must be a list")
        if not isinstance(raw_ppo, list):
            raise SerializationError("ppo_rules must be a list")
        if not isinstance(metadata, Mapping):
            raise SerializationError("graph model metadata must be a mapping")
        try:
            return cls(
                model=str(data["model"]),
                projection=ProjectionSpec.from_dict(data["projection"]),
                derived_relations=tuple(
                    DerivedRelationSpec.from_dict(item) for item in raw_derived
                ),
                axioms=tuple(AxiomSpec.from_dict(item) for item in raw_axioms),
                ppo_rules=tuple(str(item) for item in raw_ppo),
                metadata=dict(metadata),
                schema_version=str(
                    data.get("schema_version", GRAPH_MODEL_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"graph model is missing {exc.args[0]!r}"
            ) from exc

```

校验输入字典的键和值，并递归构造 `GraphModelSpec` 实例。

## 方法 `GraphModelSpec.to_dict`（第 366–376 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model": self.model,
            "metadata": dict(self.metadata),
            "projection": self.projection.to_dict(),
            "ppo_rules": list(self.ppo_rules),
            "derived_relations": [item.to_dict() for item in self.derived_relations],
            "axioms": [item.to_dict() for item in self.axioms],
        }

```

把 `GraphModelSpec` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `GraphModelSpec.load`（第 377–380 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "GraphModelSpec":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `GraphModelSpec`。

## 方法 `GraphModelSpec.dump`（第 381–382 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
```

调用 `to_dict` 后把 `GraphModelSpec` 安全写成 YAML/JSON。

