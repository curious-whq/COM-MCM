# `umcm/graph/builder.py` 源码讲解

文件职责：把具体事件轨迹投影成候选架构执行图。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–17 行）

```python
"""Projection of concrete traces into candidate architectural execution graphs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import permutations, product
from typing import Any, Iterable, Iterator, Mapping

from umcm.errors import GraphError
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import DerivedRelationSpec, GraphModelSpec, ProjectionSpec
from umcm.graph.relation import Relation, union_relations
from umcm.ir.event import EventInstance
from umcm.ir.trace import Trace


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `CandidateSpace` 及全部字段（第 18–23 行）

```python
@dataclass(frozen=True, slots=True)
class CandidateSpace:
    operations: Mapping[str, MemoryOperation]
    rf_choices: Mapping[str, tuple[str, ...]]
    co_orders: Mapping[Any, tuple[tuple[str, ...], ...]]

```

保存投影后的内存操作以及读源、相干序候选空间。

- `operations`：投影得到的内存操作序列。
- `rf_choices`：每个读操作允许选择的写操作 ID。
- `co_orders`：每个地址可采用的写操作全序候选。

## 方法 `CandidateSpace.estimated_candidates`（第 24–33 行）

```python
    @property
    def estimated_candidates(self) -> int:
        count = 1
        for choices in self.rf_choices.values():
            count *= len(choices)
        for orders in self.co_orders.values():
            count *= len(orders)
        return count


```

将每个读的读源选择数与每个地址的写序排列数相乘，估算候选执行图总数。

## 函数 `_concrete_event`（第 34–41 行）

```python
def _concrete_event(event: EventInstance) -> bool:
    if event.occurs is not True:
        return False
    if any(hasattr(value, "sort") for value in event.fields.values()):
        raise GraphError(f"event {event.id!r} has symbolic fields")
    return True


```

仅接收已确定发生的事件；对未发生或发生性仍为符号的事件返回空结果。

## 函数 `_field`（第 42–50 行）

```python
def _field(event: EventInstance, name: str) -> Any:
    try:
        return event.fields[name]
    except KeyError as exc:
        raise GraphError(
            f"event {event.id!r} ({event.event_type}) is missing field {name!r}"
        ) from exc


```

从事件字段映射中读取必需值；字段缺失时用带事件上下文的图错误终止投影。

## 函数 `project_operations`（第 51–119 行）

```python
def project_operations(trace: Trace, projection: ProjectionSpec) -> dict[str, MemoryOperation]:
    events = [event for event in trace.events if _concrete_event(event)]
    commits: dict[str, EventInstance] = {}
    for event in events:
        if event.event_type != projection.load_commit_event:
            continue
        op_id = str(_field(event, projection.id_field))
        if op_id in commits:
            raise GraphError(f"multiple load commits for operation {op_id!r}")
        commits[op_id] = event

    operations: dict[str, MemoryOperation] = {}

    def add(operation: MemoryOperation) -> None:
        if operation.id in operations:
            raise GraphError(f"duplicate architectural operation id: {operation.id}")
        operations[operation.id] = operation

    for event in events:
        if event.event_type == projection.init_write_event:
            op_id = str(_field(event, projection.id_field))
            add(
                MemoryOperation(
                    id=op_id,
                    kind=OperationKind.INIT_WRITE,
                    address=_field(event, projection.address_field),
                    value=_field(event, projection.value_field),
                    source_event_id=event.id,
                )
            )
        elif event.event_type == projection.store_event:
            op_id = str(_field(event, projection.id_field))
            add(
                MemoryOperation(
                    id=op_id,
                    kind=OperationKind.WRITE,
                    address=_field(event, projection.address_field),
                    value=_field(event, projection.value_field),
                    hart=int(_field(event, projection.hart_field)),
                    program_index=int(_field(event, projection.program_index_field)),
                    source_event_id=event.id,
                )
            )
        elif event.event_type == projection.load_event:
            op_id = str(_field(event, projection.id_field))
            commit = commits.get(op_id)
            if commit is None:
                if projection.require_committed_loads:
                    raise GraphError(f"load {op_id!r} has no {projection.load_commit_event}")
                continue
            value = _field(commit, projection.value_field)
            add(
                MemoryOperation(
                    id=op_id,
                    kind=OperationKind.READ,
                    address=_field(event, projection.address_field),
                    value=value,
                    hart=int(_field(event, projection.hart_field)),
                    program_index=int(_field(event, projection.program_index_field)),
                    source_event_id=event.id,
                    commit_event_id=commit.id,
                )
            )

    if not operations:
        raise GraphError("trace projects to no architectural memory operations")
    return operations


```

遍历具体且发生的事件，按投影配置识别初始写、读和写，并规范化为内存操作。

## 类 `_RFHintEvidence` 及全部字段（第 120–126 行）

```python
@dataclass(frozen=True, slots=True)
class _RFHintEvidence:
    write_id: str
    address: Any
    value: Any
    event_id: str

```

保存一条读源提示的规范化证据，并提供稳定去重键。

- `write_id`：读源提示指定的写操作 ID。
- `address`：内存访问地址。
- `value`：该节点、字段或状态写入承载的值。
- `event_id`：关联事件的稳定 ID。

## 方法 `_RFHintEvidence.semantic_key`（第 127–131 行）

```python
    @property
    def semantic_key(self) -> tuple[str, Any, Any]:
        return (self.write_id, self.address, self.value)


```

把提示的语义字段组成元组，供稳定排序、冲突检测和去重使用。

## 函数 `_rf_hints`（第 132–154 行）

```python
def _rf_hints(trace: Trace, spec: GraphModelSpec) -> dict[str, _RFHintEvidence]:
    hints: dict[str, _RFHintEvidence] = {}
    for hint_spec in spec.projection.rf_hints:
        for event in trace.events_of_type(hint_spec.event_type):
            if not _concrete_event(event):
                continue
            read_id = str(_field(event, hint_spec.read_id_field))
            evidence = _RFHintEvidence(
                write_id=str(_field(event, hint_spec.write_id_field)),
                address=_field(event, hint_spec.address_field),
                value=_field(event, hint_spec.value_field),
                event_id=event.id,
            )
            previous = hints.get(read_id)
            if previous is not None and previous.semantic_key != evidence.semantic_key:
                raise GraphError(
                    f"conflicting rf hints for read {read_id!r}: "
                    f"{previous.write_id!r}, {evidence.write_id!r}"
                )
            hints[read_id] = evidence
    return hints


```

扫描配置指定的提示事件，规范化读、写、地址和值并按读操作分组。

## 类 `_COHintEvidence` 及全部字段（第 155–161 行）

```python
@dataclass(frozen=True, slots=True)
class _COHintEvidence:
    before_write_id: str
    after_write_id: str
    address: Any
    event_id: str

```

保存一条相干序提示的规范化证据，并提供稳定去重键。

- `before_write_id`：相干序边起点写操作的 ID。
- `after_write_id`：相干序边终点写操作的 ID。
- `address`：内存访问地址。
- `event_id`：关联事件的稳定 ID。

## 方法 `_COHintEvidence.semantic_key`（第 162–166 行）

```python
    @property
    def semantic_key(self) -> tuple[str, str, Any]:
        return (self.before_write_id, self.after_write_id, self.address)


```

把提示的语义字段组成元组，供稳定排序、冲突检测和去重使用。

## 函数 `_co_hints`（第 167–182 行）

```python
def _co_hints(trace: Trace, spec: GraphModelSpec) -> tuple[_COHintEvidence, ...]:
    hints: dict[tuple[str, str, Any], _COHintEvidence] = {}
    for hint_spec in spec.projection.co_hints:
        for event in trace.events_of_type(hint_spec.event_type):
            if not _concrete_event(event):
                continue
            evidence = _COHintEvidence(
                before_write_id=str(_field(event, hint_spec.before_write_id_field)),
                after_write_id=str(_field(event, hint_spec.after_write_id_field)),
                address=_field(event, hint_spec.address_field),
                event_id=event.id,
            )
            hints.setdefault(evidence.semantic_key, evidence)
    return tuple(hints[key] for key in sorted(hints, key=repr))


```

扫描相干序提示事件，规范化前后写和地址并按地址分组。

## 函数 `build_candidate_space`（第 183–290 行）

```python
def build_candidate_space(trace: Trace, spec: GraphModelSpec) -> CandidateSpace:
    operations = project_operations(trace, spec.projection)
    writes = [item for item in operations.values() if item.is_write]
    reads = [item for item in operations.values() if item.is_read]
    hints = _rf_hints(trace, spec)
    co_hints = _co_hints(trace, spec)

    rf_choices: dict[str, tuple[str, ...]] = {}
    for read in sorted(reads, key=lambda item: item.id):
        candidates = [
            write.id
            for write in writes
            if write.address == read.address and write.value == read.value
        ]
        if read.id in hints:
            evidence = hints[read.id]
            hinted = evidence.write_id
            if hinted not in operations or not operations[hinted].is_write:
                raise GraphError(
                    f"rf hint for read {read.id!r} names non-write {hinted!r}"
                )
            write = operations[hinted]
            if evidence.address != read.address or evidence.address != write.address:
                raise GraphError(
                    f"rf hint event {evidence.event_id!r} has inconsistent address"
                )
            if evidence.value != read.value or evidence.value != write.value:
                raise GraphError(
                    f"rf hint event {evidence.event_id!r} has inconsistent value"
                )
            if hinted not in candidates:
                raise GraphError(
                    f"rf hint {hinted!r}->{read.id!r} disagrees with address/value"
                )
            candidates = [hinted]
        if not candidates:
            raise GraphError(
                f"read {read.id!r} value {read.value!r} at {read.address!r} "
                "has no candidate source write"
            )
        rf_choices[read.id] = tuple(sorted(candidates))

    writes_by_address: dict[Any, list[MemoryOperation]] = defaultdict(list)
    for write in writes:
        writes_by_address[write.address].append(write)

    co_orders: dict[Any, tuple[tuple[str, ...], ...]] = {}
    for address, address_writes in writes_by_address.items():
        init_writes = sorted(
            (item.id for item in address_writes if item.kind is OperationKind.INIT_WRITE)
        )
        if len(init_writes) > 1:
            raise GraphError(f"address {address!r} has multiple initial writes")
        ordinary = sorted(
            item.id for item in address_writes if item.kind is OperationKind.WRITE
        )
        prefix = tuple(init_writes)
        candidates = tuple(prefix + order for order in permutations(ordinary))
        relevant_hints = tuple(hint for hint in co_hints if hint.address == address)
        for hint in relevant_hints:
            for write_id in (hint.before_write_id, hint.after_write_id):
                operation = operations.get(write_id)
                if operation is None or not operation.is_write:
                    raise GraphError(
                        f"co hint event {hint.event_id!r} names non-write {write_id!r}"
                    )
                if operation.address != address:
                    raise GraphError(
                        f"co hint event {hint.event_id!r} has inconsistent address"
                    )
            if hint.before_write_id == hint.after_write_id:
                raise GraphError(
                    f"co hint event {hint.event_id!r} orders a write before itself"
                )
        candidates = tuple(
            order
            for order in candidates
            if all(
                order.index(hint.before_write_id) < order.index(hint.after_write_id)
                for hint in relevant_hints
            )
        )
        if not candidates:
            rendered = ", ".join(
                f"{hint.before_write_id}->{hint.after_write_id}"
                for hint in relevant_hints
            )
            raise GraphError(
                f"co hints for address {address!r} are inconsistent: {rendered}"
            )
        co_orders[address] = candidates

    unknown_hint_addresses = {
        hint.address for hint in co_hints if hint.address not in writes_by_address
    }
    if unknown_hint_addresses:
        raise GraphError(
            "co hints reference address(es) without writes: "
            + ", ".join(repr(item) for item in sorted(unknown_hint_addresses, key=repr))
        )

    return CandidateSpace(
        operations=operations,
        rf_choices=rf_choices,
        co_orders=co_orders,
    )


```

结合显式提示和语义兼容性为每个读构造读源候选，并为各地址枚举合法写序。

## 函数 `_po_relation`（第 291–307 行）

```python
def _po_relation(operations: Mapping[str, MemoryOperation]) -> Relation:
    edges: set[tuple[str, str]] = set()
    by_hart: dict[int, list[MemoryOperation]] = defaultdict(list)
    for operation in operations.values():
        if operation.hart is not None:
            by_hart[operation.hart].append(operation)
    for hart_ops in by_hart.values():
        ordered = sorted(hart_ops, key=lambda item: (item.program_index, item.id))
        indexes = [item.program_index for item in ordered]
        if len(indexes) != len(set(indexes)):
            raise GraphError("two architectural operations share a hart/program_index")
        for index, source in enumerate(ordered):
            for target in ordered[index + 1 :]:
                edges.add((source.id, target.id))
    return Relation.from_edges("po", edges)


```

按同一 hart 的程序索引排序操作，生成线程内程序序 `po` 边。

## 函数 `_co_relation`（第 308–316 行）

```python
def _co_relation(orders: Iterable[tuple[str, ...]]) -> Relation:
    edges: set[tuple[str, str]] = set()
    for order in orders:
        for index, source in enumerate(order):
            for target in order[index + 1 :]:
                edges.add((source, target))
    return Relation.from_edges("co", edges)


```

把每个地址选定的全序展开为写之间的 `co` 边。

## 函数 `_rfe_relation`（第 317–327 行）

```python
def _rfe_relation(rf: Relation, operations: Mapping[str, MemoryOperation]) -> Relation:
    return Relation.from_edges(
        "rfe",
        (
            (source, target)
            for source, target in rf.edges
            if operations[source].hart != operations[target].hart
        ),
    )


```

从读源关系中筛出跨 hart 的边，生成外部读源关系 `rfe`。

## 函数 `_ppo_relation`（第 328–361 行）

```python
def _ppo_relation(
    po: Relation,
    rf_sources: Mapping[str, str],
    operations: Mapping[str, MemoryOperation],
    rules: tuple[str, ...],
) -> Relation:
    edges: set[tuple[str, str]] = set()
    if "load_load_different_write" not in rules:
        return Relation.from_edges("ppo", edges)

    for source_id, target_id in po.edges:
        source = operations[source_id]
        target = operations[target_id]
        if not source.is_read or not target.is_read:
            continue
        if source.address != target.address:
            continue
        if rf_sources[source.id] == rf_sources[target.id]:
            continue
        assert source.hart == target.hart
        assert source.program_index is not None and target.program_index is not None
        intervening_store = any(
            operation.kind is OperationKind.WRITE
            and operation.hart == source.hart
            and operation.address == source.address
            and source.program_index < operation.program_index < target.program_index
            for operation in operations.values()
            if operation.program_index is not None
        )
        if not intervening_store:
            edges.add((source.id, target.id))
    return Relation.from_edges("ppo", edges)


```

按模型声明的操作种类对过滤 `po`，生成保留程序序 `ppo`。

## 函数 `_derive_relation`（第 362–392 行）

```python
def _derive_relation(
    relation_spec: DerivedRelationSpec,
    relations: Mapping[str, Relation],
    node_ids: Iterable[str],
) -> Relation:
    try:
        operands = [relations[name] for name in relation_spec.relations]
    except KeyError as exc:
        raise GraphError(
            f"derived relation {relation_spec.name!r} references unknown relation "
            f"{exc.args[0]!r}"
        ) from exc

    if relation_spec.op == "union":
        return union_relations(relation_spec.name, operands)
    if relation_spec.op == "intersection":
        return operands[0].intersection(operands[1], name=relation_spec.name)
    if relation_spec.op == "difference":
        return operands[0].difference(operands[1], name=relation_spec.name)
    if relation_spec.op == "inverse":
        return operands[0].inverse(relation_spec.name)
    if relation_spec.op == "compose":
        return operands[0].compose(operands[1], name=relation_spec.name)
    if relation_spec.op == "transitive_closure":
        return operands[0].transitive_closure(
            nodes=node_ids,
            name=relation_spec.name,
        )
    raise GraphError(f"unsupported derived relation op: {relation_spec.op}")


```

按配置对已有关系执行逆、并、交、差、复合或传递闭包，得到一个派生关系。

## 函数 `iter_execution_graphs`（第 393–454 行）

```python
def iter_execution_graphs(
    trace: Trace,
    spec: GraphModelSpec,
    *,
    max_candidates: int = 10_000,
) -> Iterator[ExecutionGraph]:
    if max_candidates <= 0:
        raise GraphError("max_candidates must be positive")
    space = build_candidate_space(trace, spec)
    if space.estimated_candidates > max_candidates:
        raise GraphError(
            f"candidate space {space.estimated_candidates} exceeds limit {max_candidates}"
        )

    read_ids = tuple(sorted(space.rf_choices))
    addresses = tuple(sorted(space.co_orders, key=repr))
    rf_products = product(*(space.rf_choices[read_id] for read_id in read_ids))
    co_products_materialized = tuple(
        product(*(space.co_orders[address] for address in addresses))
    )
    po = _po_relation(space.operations)

    candidate_id = 0
    for rf_writes in rf_products:
        rf_sources = dict(zip(read_ids, rf_writes, strict=True))
        rf = Relation.from_edges(
            "rf",
            ((write_id, read_id) for read_id, write_id in rf_sources.items()),
        )
        for co_selected in co_products_materialized:
            co = _co_relation(co_selected)
            fr = rf.inverse("rf_inv").compose(co, name="fr")
            rfe = _rfe_relation(rf, space.operations)
            ppo = _ppo_relation(po, rf_sources, space.operations, spec.ppo_rules)
            relations: dict[str, Relation] = {
                item.name: item for item in (po, rf, rfe, co, fr, ppo)
            }
            for derived in spec.derived_relations:
                relation = _derive_relation(
                    derived,
                    relations,
                    space.operations.keys(),
                )
                if relation.name in relations:
                    raise GraphError(f"derived relation overwrites {relation.name!r}")
                relations[relation.name] = relation

            metadata = {
                "graph_model": spec.model,
                "rf_assignment": dict(sorted(rf_sources.items())),
                "co_orders": {
                    str(address): list(order)
                    for address, order in zip(addresses, co_selected, strict=True)
                },
            }
            yield ExecutionGraph(
                operations=dict(space.operations),
                relations=relations,
                candidate_id=candidate_id,
                metadata=metadata,
            )
            candidate_id += 1
```

对读源选择与相干序排列做笛卡尔枚举，构造基础关系、派生关系及稳定编号的执行图。

