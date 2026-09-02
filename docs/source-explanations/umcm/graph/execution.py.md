# `umcm/graph/execution.py` 源码讲解

文件职责：定义内存操作、执行图及其序列化格式。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–14 行）

```python
"""Execution-graph nodes, relations, and serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from umcm.errors import GraphError, SerializationError
from umcm.graph.relation import Relation
from umcm.serialization import dump_data, load_data


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `EXECUTION_GRAPH_SCHEMA_VERSION`（第 15–17 行）

```python
EXECUTION_GRAPH_SCHEMA_VERSION = "umcm.execution_graph.v0.1"


```

这是模块级常量或公开导出声明：`EXECUTION_GRAPH_SCHEMA_VERSION` 保存executiongraphschemaversion，供该对象的校验、转换或序列化逻辑使用。

## 类 `OperationKind` 及全部字段（第 18–23 行）

```python
class OperationKind(str, Enum):
    INIT_WRITE = "init_write"
    READ = "read"
    WRITE = "write"


```

区分初始写、读和普通写三类内存操作。

- `INIT_WRITE`：定义枚举成员，表示操作是初始内存写。
- `READ`：定义枚举成员，表示操作是内存读。
- `WRITE`：定义枚举成员，表示操作是普通内存写。

## 类 `MemoryOperation` 及全部字段（第 24–35 行）

```python
@dataclass(frozen=True, slots=True)
class MemoryOperation:
    id: str
    kind: OperationKind
    address: Any
    value: Any
    hart: int | None = None
    program_index: int | None = None
    source_event_id: str = ""
    commit_event_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

```

表示执行图中的一个规范化内存访问节点。

- `id`：对象的稳定标识符。
- `kind`：节点、操作、公理或输出值的类别。
- `address`：内存访问地址。
- `value`：该节点、字段或状态写入承载的值。
- `hart`：执行该操作的硬件线程标识。
- `program_index`：操作在该硬件线程程序序中的位置。
- `source_event_id`：该内存操作对应的源轨迹事件 ID。
- `commit_event_id`：证明读已经提交的源事件 ID。
- `metadata`：不参与核心语义的扩展元数据。

## 方法 `MemoryOperation.__post_init__`（第 36–46 行）

```python
    def __post_init__(self) -> None:
        if not self.id:
            raise GraphError("memory operation id must be non-empty")
        if self.kind is not OperationKind.INIT_WRITE:
            if self.hart is None or self.program_index is None:
                raise GraphError(
                    f"operation {self.id!r} requires hart and program_index"
                )
        if self.kind is OperationKind.READ and not self.commit_event_id:
            raise GraphError(f"read {self.id!r} requires a commit event")

```

在 `MemoryOperation` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `MemoryOperation.is_read`（第 47–50 行）

```python
    @property
    def is_read(self) -> bool:
        return self.kind is OperationKind.READ

```

检查 `MemoryOperation` 实例 是否满足“读操作”这一快速分类条件。

## 方法 `MemoryOperation.is_write`（第 51–54 行）

```python
    @property
    def is_write(self) -> bool:
        return self.kind in {OperationKind.WRITE, OperationKind.INIT_WRITE}

```

检查 `MemoryOperation` 实例 是否满足“写操作”这一快速分类条件。

## 方法 `MemoryOperation.to_dict`（第 55–73 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind.value,
            "address": self.address,
            "value": self.value,
        }
        if self.hart is not None:
            data["hart"] = self.hart
        if self.program_index is not None:
            data["program_index"] = self.program_index
        if self.source_event_id:
            data["source_event_id"] = self.source_event_id
        if self.commit_event_id:
            data["commit_event_id"] = self.commit_event_id
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

```

把 `MemoryOperation` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `MemoryOperation.from_dict`（第 74–100 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryOperation":
        if not isinstance(data, Mapping):
            raise SerializationError("execution-graph operation must be a mapping")
        try:
            metadata = data.get("metadata", {})
            if not isinstance(metadata, Mapping):
                raise SerializationError("operation metadata must be a mapping")
            return cls(
                id=str(data["id"]),
                kind=OperationKind(str(data["kind"])),
                address=data["address"],
                value=data["value"],
                hart=None if data.get("hart") is None else int(data["hart"]),
                program_index=(
                    None
                    if data.get("program_index") is None
                    else int(data["program_index"])
                ),
                source_event_id=str(data.get("source_event_id", "")),
                commit_event_id=str(data.get("commit_event_id", "")),
                metadata=dict(metadata),
            )
        except (KeyError, ValueError) as exc:
            raise SerializationError(f"invalid execution-graph operation: {exc}") from exc


```

校验输入字典的键和值，并递归构造 `MemoryOperation` 实例。

## 类 `ExecutionGraph` 及全部字段（第 101–108 行）

```python
@dataclass(slots=True)
class ExecutionGraph:
    operations: dict[str, MemoryOperation]
    relations: dict[str, Relation]
    candidate_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = EXECUTION_GRAPH_SCHEMA_VERSION

```

保存候选内存操作节点、命名关系及图元数据。

- `operations`：投影得到的内存操作序列。
- `relations`：命名关系或参与运算的关系集合。
- `candidate_id`：候选执行图的稳定编号。
- `metadata`：不参与核心语义的扩展元数据。
- `schema_version`：序列化模式版本。

## 方法 `ExecutionGraph.__post_init__`（第 109–128 行）

```python
    def __post_init__(self) -> None:
        self.operations = dict(self.operations)
        self.relations = dict(self.relations)
        self.metadata = dict(self.metadata)
        for op_id, operation in self.operations.items():
            if op_id != operation.id:
                raise GraphError(
                    f"operation key {op_id!r} does not match id {operation.id!r}"
                )
        for name, relation in self.relations.items():
            if name != relation.name:
                raise GraphError(
                    f"relation key {name!r} does not match name {relation.name!r}"
                )
            for source, target in relation.edges:
                if source not in self.operations or target not in self.operations:
                    raise GraphError(
                        f"relation {name!r} references unknown edge {source!r}->{target!r}"
                    )

```

在 `ExecutionGraph` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `ExecutionGraph.relation`（第 129–134 行）

```python
    def relation(self, name: str) -> Relation:
        try:
            return self.relations[name]
        except KeyError as exc:
            raise GraphError(f"unknown relation: {name}") from exc

```

按名称取得执行图关系；未知名称返回同名空关系，简化派生和检查逻辑。

## 方法 `ExecutionGraph.to_dict`（第 135–147 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "metadata": dict(self.metadata),
            "operations": [
                self.operations[op_id].to_dict() for op_id in sorted(self.operations)
            ],
            "relations": [
                self.relations[name].to_dict() for name in sorted(self.relations)
            ],
        }

```

把 `ExecutionGraph` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `ExecutionGraph.from_dict`（第 148–186 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionGraph":
        if not isinstance(data, Mapping):
            raise SerializationError("execution graph must be a mapping")
        raw_operations = data.get("operations", [])
        raw_relations = data.get("relations", [])
        if not isinstance(raw_operations, list) or not isinstance(raw_relations, list):
            raise SerializationError("execution graph operations/relations must be lists")
        operations = [MemoryOperation.from_dict(item) for item in raw_operations]
        relations: list[Relation] = []
        for raw in raw_relations:
            if not isinstance(raw, Mapping):
                raise SerializationError("execution-graph relation must be a mapping")
            name = str(raw.get("name", ""))
            raw_edges = raw.get("edges", [])
            if not isinstance(raw_edges, list):
                raise SerializationError("relation edges must be a list")
            edges = []
            for edge in raw_edges:
                if not isinstance(edge, Mapping):
                    raise SerializationError("relation edge must be a mapping")
                try:
                    edges.append((str(edge["from"]), str(edge["to"])))
                except KeyError as exc:
                    raise SerializationError("relation edge requires from/to") from exc
            relations.append(Relation.from_edges(name, edges))
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise SerializationError("execution graph metadata must be a mapping")
        return cls(
            operations={item.id: item for item in operations},
            relations={item.name: item for item in relations},
            candidate_id=int(data.get("candidate_id", 0)),
            metadata=dict(metadata),
            schema_version=str(
                data.get("schema_version", EXECUTION_GRAPH_SCHEMA_VERSION)
            ),
        )

```

校验输入字典的键和值，并递归构造 `ExecutionGraph` 实例。

## 方法 `ExecutionGraph.load`（第 187–190 行）

```python
    @classmethod
    def load(cls, path: str | Path) -> "ExecutionGraph":
        return cls.from_dict(load_data(path))

```

从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `ExecutionGraph`。

## 方法 `ExecutionGraph.dump`（第 191–193 行）

```python
    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)

```

调用 `to_dict` 后把 `ExecutionGraph` 安全写成 YAML/JSON。

## 方法 `ExecutionGraph.relation_counts`（第 194–196 行）

```python
    def relation_counts(self) -> dict[str, int]:
        return {name: len(relation.edges) for name, relation in self.relations.items()}

```

生成关系名到边数的稳定映射，供摘要输出和诊断使用。

## 方法 `ExecutionGraph.with_relations`（第 197–207 行）

```python
    def with_relations(self, relations: Iterable[Relation]) -> "ExecutionGraph":
        merged = dict(self.relations)
        for relation in relations:
            merged[relation.name] = relation
        return ExecutionGraph(
            operations=self.operations,
            relations=merged,
            candidate_id=self.candidate_id,
            metadata=self.metadata,
            schema_version=self.schema_version,
        )
```

复制当前执行图并用给定映射替换命名关系，其余节点和元数据保持不变。

