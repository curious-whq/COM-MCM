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


@dataclass(frozen=True, slots=True)
class CandidateSpace:
    operations: Mapping[str, MemoryOperation]
    rf_choices: Mapping[str, tuple[str, ...]]
    co_orders: Mapping[Any, tuple[tuple[str, ...], ...]]
    relation_hints: Mapping[str, Relation]

    @property
    def estimated_candidates(self) -> int:
        count = 1
        for choices in self.rf_choices.values():
            count *= len(choices)
        for orders in self.co_orders.values():
            count *= len(orders)
        return count


def _concrete_event(event: EventInstance) -> bool:
    if event.occurs is not True:
        return False
    if any(hasattr(value, "sort") for value in event.fields.values()):
        raise GraphError(f"event {event.id!r} has symbolic fields")
    return True


def _field(event: EventInstance, name: str) -> Any:
    try:
        return event.fields[name]
    except KeyError as exc:
        raise GraphError(
            f"event {event.id!r} ({event.event_type}) is missing field {name!r}"
        ) from exc


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

    def metadata(event: EventInstance, *, atomic_kind: str | None = None) -> dict[str, Any]:
        result = {
            semantic_name: event.fields[field_name]
            for semantic_name, field_name in projection.metadata_fields.items()
            if field_name in event.fields
        }
        if atomic_kind is not None:
            result["atomic_kind"] = atomic_kind
        return result

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
                    metadata=metadata(event),
                )
            )
        elif projection.amo_event is not None and event.event_type == projection.amo_event:
            op_id = str(_field(event, projection.id_field))
            commit = commits.get(op_id)
            if commit is None:
                if projection.require_committed_loads:
                    raise GraphError(f"AMO {op_id!r} has no {projection.load_commit_event}")
                continue
            add(
                MemoryOperation(
                    id=op_id,
                    kind=OperationKind.AMO,
                    address=_field(event, projection.address_field),
                    value=_field(commit, projection.value_field),
                    write_value=_field(event, projection.write_value_field),
                    hart=int(_field(event, projection.hart_field)),
                    program_index=int(_field(event, projection.program_index_field)),
                    source_event_id=event.id,
                    commit_event_id=commit.id,
                    metadata=metadata(event, atomic_kind="amo"),
                )
            )
        elif event.event_type in {
            projection.store_event,
            projection.sc_event,
        }:
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
                    metadata=metadata(
                        event,
                        atomic_kind=(
                            "sc"
                            if projection.sc_event is not None
                            and event.event_type == projection.sc_event
                            else None
                        ),
                    ),
                )
            )
        elif event.event_type in {
            projection.load_event,
            projection.lr_event,
        }:
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
                    metadata=metadata(
                        event,
                        atomic_kind=(
                            "lr"
                            if projection.lr_event is not None
                            and event.event_type == projection.lr_event
                            else None
                        ),
                    ),
                )
            )

    if not operations:
        raise GraphError("trace projects to no architectural memory operations")
    return operations


@dataclass(frozen=True, slots=True)
class _RFHintEvidence:
    write_id: str
    address: Any
    value: Any
    event_id: str

    @property
    def semantic_key(self) -> tuple[str, Any, Any]:
        return (self.write_id, self.address, self.value)


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


@dataclass(frozen=True, slots=True)
class _COHintEvidence:
    before_write_id: str
    after_write_id: str
    address: Any
    event_id: str

    @property
    def semantic_key(self) -> tuple[str, str, Any]:
        return (self.before_write_id, self.after_write_id, self.address)


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


def _relation_hints(
    trace: Trace,
    spec: GraphModelSpec,
    operations: Mapping[str, MemoryOperation],
) -> dict[str, Relation]:
    edges: dict[str, set[tuple[str, str]]] = defaultdict(set)
    declared_names = {hint.name for hint in spec.projection.relation_hints}
    for hint in spec.projection.relation_hints:
        for event in trace.events_of_type(hint.event_type):
            if not _concrete_event(event):
                continue
            source = str(_field(event, hint.source_id_field))
            target = str(_field(event, hint.target_id_field))
            if source not in operations or target not in operations:
                raise GraphError(
                    f"relation hint event {event.id!r} references unknown operation "
                    f"{source!r}->{target!r}"
                )
            edges[hint.name].add((source, target))
    return {
        name: Relation.from_edges(name, edges.get(name, ()))
        for name in sorted(declared_names)
    }


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
            if write.id != read.id
            and write.address == read.address
            and write.stored_value == read.read_value
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
            if evidence.value != read.read_value or evidence.value != write.stored_value:
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
        relation_hints=_relation_hints(trace, spec, operations),
    )


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


def _co_relation(orders: Iterable[tuple[str, ...]]) -> Relation:
    edges: set[tuple[str, str]] = set()
    for order in orders:
        for index, source in enumerate(order):
            for target in order[index + 1 :]:
                edges.add((source, target))
    return Relation.from_edges("co", edges)


def _rfe_relation(rf: Relation, operations: Mapping[str, MemoryOperation]) -> Relation:
    return Relation.from_edges(
        "rfe",
        (
            (source, target)
            for source, target in rf.edges
            if operations[source].hart != operations[target].hart
        ),
    )


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
            relations.update(space.relation_hints)
            graph = ExecutionGraph(
                operations=dict(space.operations),
                relations=relations,
                candidate_id=candidate_id,
                metadata={
                    "graph_model": spec.model,
                    "rf_assignment": dict(sorted(rf_sources.items())),
                    "co_orders": {
                        str(address): list(order)
                        for address, order in zip(addresses, co_selected, strict=True)
                    },
                },
            )
            if spec.builtin_model == "rvwmo":
                from umcm.graph.rvwmo import complete_rvwmo_relations

                graph = complete_rvwmo_relations(graph)
                relations = dict(graph.relations)
            for derived in spec.derived_relations:
                relation = _derive_relation(
                    derived,
                    relations,
                    space.operations.keys(),
                )
                if relation.name in relations:
                    raise GraphError(f"derived relation overwrites {relation.name!r}")
                relations[relation.name] = relation

            yield ExecutionGraph(
                operations=dict(space.operations),
                relations=relations,
                candidate_id=candidate_id,
                metadata=graph.metadata,
            )
            candidate_id += 1
