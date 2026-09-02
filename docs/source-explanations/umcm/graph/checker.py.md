# `umcm/graph/checker.py` 源码讲解

文件职责：在有限候选执行图上检查关系公理并汇总判定。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–16 行）

```python
"""Axiom checking over finite execution-graph candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from umcm.errors import GraphError
from umcm.graph.builder import iter_execution_graphs
from umcm.graph.execution import ExecutionGraph
from umcm.graph.model import AxiomSpec, GraphModelSpec
from umcm.graph.relation import LabeledEdge, Relation, find_labeled_cycle, union_relations
from umcm.ir.trace import Trace


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `AxiomStatus` 及全部字段（第 17–21 行）

```python
class AxiomStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"


```

枚举单条公理满足或违反两种状态。

- `SATISFIED`：定义枚举成员，表示公理得到满足。
- `VIOLATED`：定义枚举成员，表示公理被违反。

## 类 `AxiomResult` 及全部字段（第 22–30 行）

```python
@dataclass(frozen=True, slots=True)
class AxiomResult:
    axiom: str
    status: AxiomStatus
    kind: str
    relations: tuple[str, ...]
    cycle: tuple[LabeledEdge, ...] = ()
    offending_edges: tuple[tuple[str, str], ...] = ()

```

记录单条公理的判定及用于诊断的环和边。

- `axiom`：被检查公理的稳定名称。
- `status`：本次检查或求解的结果状态。
- `kind`：节点、操作、公理或输出值的类别。
- `relations`：命名关系或参与运算的关系集合。
- `cycle`：事件发生周期或诊断环。
- `offending_edges`：直接构成公理违例的关系边。

## 方法 `AxiomResult.to_dict`（第 31–47 行）

```python
    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "axiom": self.axiom,
            "status": self.status.value,
            "kind": self.kind,
            "relations": list(self.relations),
        }
        if self.cycle:
            data["cycle"] = [edge.to_dict() for edge in self.cycle]
        if self.offending_edges:
            data["offending_edges"] = [
                {"from": source, "to": target}
                for source, target in self.offending_edges
            ]
        return data


```

把 `AxiomResult` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `CandidateCheck` 及全部字段（第 48–52 行）

```python
@dataclass(frozen=True, slots=True)
class CandidateCheck:
    graph: ExecutionGraph
    axioms: tuple[AxiomResult, ...]

```

记录一个候选执行图及其全部公理检查结果。

- `graph`：当前被检查的候选执行图。
- `axioms`：逐条公理的检查结果或配置。

## 方法 `CandidateCheck.allowed`（第 53–57 行）

```python
    @property
    def allowed(self) -> bool:
        return all(result.status is AxiomStatus.SATISFIED for result in self.axioms)


```

仅当该候选的每条公理都处于满足状态时返回真。

## 类 `MemoryModelStatus` 及全部字段（第 58–62 行）

```python
class MemoryModelStatus(str, Enum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


```

枚举轨迹在内存模型下允许或禁止的状态。

- `ALLOWED`：定义枚举成员，表示内存模型允许该轨迹。
- `FORBIDDEN`：定义枚举成员，表示内存模型禁止该轨迹。

## 类 `MemoryModelCheck` 及全部字段（第 63–67 行）

```python
@dataclass(frozen=True, slots=True)
class MemoryModelCheck:
    status: MemoryModelStatus
    candidates: tuple[CandidateCheck, ...]

```

汇总一个轨迹的全部候选图检查结果。

- `status`：本次检查或求解的结果状态。
- `candidates`：该轨迹枚举出的候选执行图检查结果。

## 方法 `MemoryModelCheck.representative`（第 68–76 行）

```python
    @property
    def representative(self) -> CandidateCheck:
        if not self.candidates:
            raise GraphError("memory-model check has no candidates")
        if self.status is MemoryModelStatus.ALLOWED:
            return next(candidate for candidate in self.candidates if candidate.allowed)
        return self.candidates[0]


```

优先返回允许候选；若不存在则返回第一个候选，空集合返回空值。

## 函数 `check_axiom`（第 77–112 行）

```python
def check_axiom(graph: ExecutionGraph, axiom: AxiomSpec) -> AxiomResult:
    try:
        relations = tuple(graph.relation(name) for name in axiom.relations)
    except GraphError:
        raise

    if axiom.kind == "acyclic":
        cycle = find_labeled_cycle(relations)
        return AxiomResult(
            axiom=axiom.name,
            status=(
                AxiomStatus.SATISFIED if cycle is None else AxiomStatus.VIOLATED
            ),
            kind=axiom.kind,
            relations=axiom.relations,
            cycle=cycle or (),
        )

    combined = union_relations(f"axiom:{axiom.name}", relations)
    if axiom.kind == "irreflexive":
        offending = tuple(sorted(edge for edge in combined.edges if edge[0] == edge[1]))
    elif axiom.kind == "empty":
        offending = tuple(sorted(combined.edges))
    else:  # guarded by AxiomSpec
        raise GraphError(f"unsupported axiom kind: {axiom.kind}")
    return AxiomResult(
        axiom=axiom.name,
        status=(
            AxiomStatus.SATISFIED if not offending else AxiomStatus.VIOLATED
        ),
        kind=axiom.kind,
        relations=axiom.relations,
        offending_edges=offending,
    )


```

合并公理引用的关系；按 acyclic、irreflexive 或 empty 语义检查，并构造违例诊断。

## 函数 `check_execution_graph`（第 113–122 行）

```python
def check_execution_graph(
    graph: ExecutionGraph,
    axioms: Iterable[AxiomSpec],
) -> CandidateCheck:
    return CandidateCheck(
        graph=graph,
        axioms=tuple(check_axiom(graph, axiom) for axiom in axioms),
    )


```

对一个候选执行图逐条检查模型公理。

## 函数 `check_trace_memory_model`（第 123–144 行）

```python
def check_trace_memory_model(
    trace: Trace,
    spec: GraphModelSpec,
    *,
    max_candidates: int = 10_000,
) -> MemoryModelCheck:
    candidates: list[CandidateCheck] = []
    for graph in iter_execution_graphs(
        trace,
        spec,
        max_candidates=max_candidates,
    ):
        checked = check_execution_graph(graph, spec.axioms)
        candidates.append(checked)
    if not candidates:
        raise GraphError("trace generated no execution-graph candidates")
    status = (
        MemoryModelStatus.ALLOWED
        if any(candidate.allowed for candidate in candidates)
        else MemoryModelStatus.FORBIDDEN
    )
    return MemoryModelCheck(status=status, candidates=tuple(candidates))
```

枚举轨迹的全部候选执行图；只要存在全部公理满足的候选就判为允许。

