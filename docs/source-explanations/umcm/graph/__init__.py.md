# `umcm/graph/__init__.py` 源码讲解

文件职责：汇总执行图构造、关系运算和公理检查的公开接口。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–30 行）

```python
"""Execution-graph construction and axiom checking."""

from umcm.graph.builder import CandidateSpace, build_candidate_space, iter_execution_graphs, project_operations
from umcm.graph.checker import (
    AxiomResult,
    AxiomStatus,
    CandidateCheck,
    MemoryModelCheck,
    MemoryModelStatus,
    check_axiom,
    check_execution_graph,
    check_trace_memory_model,
)
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import (
    AxiomSpec,
    COHintSpec,
    DerivedRelationSpec,
    GraphModelSpec,
    ProjectionSpec,
    RFHintSpec,
)
from umcm.graph.relation import (
    Edge,
    LabeledEdge,
    Relation,
    find_labeled_cycle,
    union_relations,
)

```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `__all__`（第 31–58 行）

```python
__all__ = [
    "AxiomResult",
    "AxiomSpec",
    "AxiomStatus",
    "CandidateCheck",
    "CandidateSpace",
    "COHintSpec",
    "DerivedRelationSpec",
    "Edge",
    "ExecutionGraph",
    "GraphModelSpec",
    "LabeledEdge",
    "MemoryModelCheck",
    "MemoryModelStatus",
    "MemoryOperation",
    "OperationKind",
    "ProjectionSpec",
    "RFHintSpec",
    "Relation",
    "build_candidate_space",
    "check_axiom",
    "check_execution_graph",
    "check_trace_memory_model",
    "find_labeled_cycle",
    "iter_execution_graphs",
    "project_operations",
    "union_relations",
]
```

这是模块级常量或公开导出声明：`__all__` 保存all，供该对象的校验、转换或序列化逻辑使用。

