"""Finite, architectural RVWMO v2.0 relation construction and checks.

The implementation is intentionally an architectural checker, not an ISA
decoder.  Syntactic dependencies and fence orderings are supplied as relation
edges by the projection front-end.  The checker implements the thirteen PPO
rules over those edges and the projected memory operations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from umcm.errors import GraphError
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.relation import LabeledEdge, Relation, find_labeled_cycle, union_relations


RVWMO_PPO_RELATIONS = tuple(f"ppo_rule{index}" for index in range(1, 14))
RVWMO_INPUT_RELATIONS = ("addr", "data", "ctrl", "fence", "pair", "pipeline")
RVWMO_ORDER_RELATIONS = ("ppo", "rfe", "co", "fr")


@dataclass(frozen=True, slots=True)
class RVWMOOutcome:
    name: str
    satisfied: bool
    kind: str
    relations: tuple[str, ...]
    cycle: tuple[LabeledEdge, ...] = ()
    offending_edges: tuple[tuple[str, str], ...] = ()


def _footprint(operation: MemoryOperation) -> frozenset[Any]:
    explicit = operation.metadata.get("byte_addresses")
    if explicit is not None:
        if not isinstance(explicit, (list, tuple, set, frozenset)) or not explicit:
            raise GraphError(
                f"operation {operation.id!r} byte_addresses must be a non-empty sequence"
            )
        try:
            return frozenset(explicit)
        except TypeError as exc:
            raise GraphError(
                f"operation {operation.id!r} has unhashable byte address"
            ) from exc

    byte_mask = operation.metadata.get("byte_mask")
    if isinstance(operation.address, int) and isinstance(byte_mask, int):
        if byte_mask <= 0:
            raise GraphError(f"operation {operation.id!r} has an empty byte_mask")
        return frozenset(
            operation.address + offset
            for offset in range(byte_mask.bit_length())
            if byte_mask & (1 << offset)
        )

    size = operation.metadata.get("size", 1)
    if isinstance(operation.address, int) and isinstance(size, int):
        if size <= 0:
            raise GraphError(f"operation {operation.id!r} size must be positive")
        return frozenset(range(operation.address, operation.address + size))
    try:
        return frozenset({operation.address})
    except TypeError as exc:
        raise GraphError(f"operation {operation.id!r} has an unhashable address") from exc


def _overlap(left: MemoryOperation, right: MemoryOperation) -> bool:
    return bool(_footprint(left) & _footprint(right))


def _same_location(left: MemoryOperation, right: MemoryOperation) -> bool:
    return _footprint(left) == _footprint(right)


def _regular(operation: MemoryOperation) -> bool:
    region = str(operation.metadata.get("memory_region", "main")).lower()
    return region in {"main", "regular", "memory"}


def _tokens(operation: MemoryOperation) -> set[str]:
    raw = operation.metadata.get("ordering", ())
    if isinstance(raw, str):
        values: Iterable[Any] = (raw,)
    elif isinstance(raw, (list, tuple, set, frozenset)):
        values = raw
    else:
        values = ()
    return {str(value).lower().replace("-", "_") for value in values}


def _acquire(operation: MemoryOperation) -> bool:
    tokens = _tokens(operation)
    return bool(operation.metadata.get("acquire", False)) or bool(
        tokens & {"acquire", "acquire_rcpc", "acquire_rcsc", "aq"}
    )


def _release(operation: MemoryOperation) -> bool:
    tokens = _tokens(operation)
    return bool(operation.metadata.get("release", False)) or bool(
        tokens & {"release", "release_rcpc", "release_rcsc", "rl"}
    )


def _rcsc(operation: MemoryOperation) -> bool:
    tokens = _tokens(operation)
    return bool(operation.metadata.get("rcsc", False)) or bool(
        tokens & {"acquire_rcsc", "release_rcsc", "rcsc", "aq", "rl"}
    )


def _relation(relations: Mapping[str, Relation], name: str) -> Relation:
    return relations.get(name, Relation.from_edges(name, ()))


def _canonical_po(operations: Mapping[str, MemoryOperation]) -> Relation:
    by_hart: dict[int, list[MemoryOperation]] = defaultdict(list)
    for operation in operations.values():
        if operation.hart is not None:
            by_hart[operation.hart].append(operation)
    edges: set[tuple[str, str]] = set()
    for hart, hart_operations in by_hart.items():
        ordered = sorted(hart_operations, key=lambda item: (item.program_index, item.id))
        indexes = [item.program_index for item in ordered]
        if len(indexes) != len(set(indexes)):
            raise GraphError(f"two operations on hart {hart} share a program_index")
        for index, source in enumerate(ordered):
            for target in ordered[index + 1 :]:
                edges.add((source.id, target.id))
    return Relation.from_edges("po", edges)


def _validate_scalar_locations(operations: Mapping[str, MemoryOperation]) -> None:
    memory = [operation for operation in operations.values()]
    for index, left in enumerate(memory):
        for right in memory[index + 1 :]:
            if _overlap(left, right) and not _same_location(left, right):
                raise GraphError(
                    "v0.16 rejects partially overlapping mixed-size accesses: "
                    f"{left.id!r} and {right.id!r}"
                )


def _rf_sources(
    operations: Mapping[str, MemoryOperation], rf: Relation
) -> dict[str, str]:
    incoming: dict[str, list[str]] = defaultdict(list)
    for source_id, read_id in rf.edges:
        if source_id not in operations or read_id not in operations:
            raise GraphError(f"rf references unknown operation {source_id!r}->{read_id!r}")
        source = operations[source_id]
        read = operations[read_id]
        if not source.is_write or not read.is_read or source_id == read_id:
            raise GraphError(f"invalid rf edge {source_id!r}->{read_id!r}")
        if not _same_location(source, read):
            raise GraphError(f"rf edge {source_id!r}->{read_id!r} crosses locations")
        if source.stored_value != read.read_value:
            raise GraphError(f"rf edge {source_id!r}->{read_id!r} has unequal values")
        incoming[read_id].append(source_id)
    result: dict[str, str] = {}
    for operation in operations.values():
        if not operation.is_read:
            continue
        sources = incoming.get(operation.id, [])
        if len(sources) != 1:
            raise GraphError(
                f"read {operation.id!r} requires exactly one rf source, got {len(sources)}"
            )
        result[operation.id] = sources[0]
    return result


def _validate_co(
    operations: Mapping[str, MemoryOperation], co: Relation
) -> None:
    writes = [operation for operation in operations.values() if operation.is_write]
    for source_id, target_id in co.edges:
        source = operations.get(source_id)
        target = operations.get(target_id)
        if source is None or target is None or not source.is_write or not target.is_write:
            raise GraphError(f"invalid co edge {source_id!r}->{target_id!r}")
        if source_id == target_id or not _same_location(source, target):
            raise GraphError(f"invalid co edge {source_id!r}->{target_id!r}")

    for index, left in enumerate(writes):
        for right in writes[index + 1 :]:
            if not _same_location(left, right):
                continue
            directions = int((left.id, right.id) in co.edges) + int(
                (right.id, left.id) in co.edges
            )
            if directions != 1:
                raise GraphError(
                    f"co is not total for writes {left.id!r} and {right.id!r}"
                )
    if find_labeled_cycle((co,)) is not None:
        raise GraphError("co must be acyclic")
    for init in (item for item in writes if item.kind is OperationKind.INIT_WRITE):
        for write in writes:
            if write.id != init.id and _same_location(init, write):
                if (init.id, write.id) not in co.edges:
                    raise GraphError(
                        f"initial write {init.id!r} must be first in coherence order"
                    )


def _between(
    source: MemoryOperation,
    middle: MemoryOperation,
    target: MemoryOperation,
) -> bool:
    return (
        source.hart is not None
        and source.hart == middle.hart == target.hart
        and source.program_index is not None
        and middle.program_index is not None
        and target.program_index is not None
        and source.program_index < middle.program_index < target.program_index
    )


def _validate_input_edges(
    relation: Relation,
    po: Relation,
    operations: Mapping[str, MemoryOperation],
) -> None:
    for edge in relation.edges:
        if edge[0] not in operations or edge[1] not in operations:
            raise GraphError(f"relation {relation.name!r} references unknown edge {edge}")
        if edge not in po.edges:
            raise GraphError(f"relation {relation.name!r} edge {edge} is not in po")


def derive_ppo(
    operations: Mapping[str, MemoryOperation],
    relations: Mapping[str, Relation],
    rf_sources: Mapping[str, str],
) -> tuple[Relation, ...]:
    """Return rule1..rule13 and their union, following RVWMO section 17.1.1.3."""

    po = _relation(relations, "po")
    inputs = {name: _relation(relations, name) for name in RVWMO_INPUT_RELATIONS}
    for relation in inputs.values():
        _validate_input_edges(relation, po, operations)

    rules: list[set[tuple[str, str]]] = [set() for _ in range(13)]
    for source_id, target_id in po.edges:
        source = operations[source_id]
        target = operations[target_id]
        if not (_regular(source) and _regular(target)):
            continue

        # 1. Older overlapping access before a store.
        if target.is_write and _overlap(source, target):
            rules[0].add((source_id, target_id))

        # 2. Same-byte loads, no intervening store, different source writes.
        if source.is_read and target.is_read and _overlap(source, target):
            common = _footprint(source) & _footprint(target)
            intervening = any(
                middle.is_write
                and _between(source, middle, target)
                and bool(common & _footprint(middle))
                for middle in operations.values()
            )
            if not intervening and rf_sources[source_id] != rf_sources[target_id]:
                rules[1].add((source_id, target_id))

        # 3. A load reading from an older AMO/SC write.
        if (
            source.atomic_kind in {"amo", "sc"}
            and target.is_read
            and rf_sources[target_id] == source_id
        ):
            rules[2].add((source_id, target_id))

        # 4-8. Explicit synchronization.
        if (source_id, target_id) in inputs["fence"].edges:
            rules[3].add((source_id, target_id))
        if _acquire(source):
            rules[4].add((source_id, target_id))
        if _release(target):
            rules[5].add((source_id, target_id))
        if _rcsc(source) and _rcsc(target):
            rules[6].add((source_id, target_id))
        if (source_id, target_id) in inputs["pair"].edges:
            rules[7].add((source_id, target_id))

        # 9-11. Syntactic dependencies supplied by the ISA front-end.
        if (source_id, target_id) in inputs["addr"].edges:
            rules[8].add((source_id, target_id))
        if target.is_write and (source_id, target_id) in inputs["data"].edges:
            rules[9].add((source_id, target_id))
        if target.is_write and (source_id, target_id) in inputs["ctrl"].edges:
            rules[10].add((source_id, target_id))

        # 12. Store-to-load pipeline dependency.
        if target.is_read:
            for middle in operations.values():
                if (
                    middle.is_write
                    and _between(source, middle, target)
                    and rf_sources[target_id] == middle.id
                    and (
                        (source_id, middle.id) in inputs["addr"].edges
                        or (source_id, middle.id) in inputs["data"].edges
                    )
                ):
                    rules[11].add((source_id, target_id))
                    break

        # 13. Address dependency through an intervening instruction.  Direct
        # pipeline hints cover non-memory intermediate instructions omitted by
        # the architectural projection.
        if target.is_write:
            if (source_id, target_id) in inputs["pipeline"].edges:
                rules[12].add((source_id, target_id))
            else:
                for middle in operations.values():
                    if _between(source, middle, target) and (
                        (source_id, middle.id) in inputs["addr"].edges
                    ):
                        rules[12].add((source_id, target_id))
                        break

    named = tuple(
        Relation.from_edges(name, edges)
        for name, edges in zip(RVWMO_PPO_RELATIONS, rules, strict=True)
    )
    return named + (union_relations("ppo", named),)


def _topological_total_order(
    node_ids: Iterable[str], relations: Iterable[Relation]
) -> tuple[str, ...] | None:
    nodes = set(node_ids)
    successors: dict[str, set[str]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for relation in relations:
        for source, target in relation.edges:
            if target not in successors[source]:
                successors[source].add(target)
                indegree[target] += 1
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(successors.get(node, ())):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return tuple(order) if len(order) == len(nodes) else None


def complete_rvwmo_relations(graph: ExecutionGraph) -> ExecutionGraph:
    """Validate base relations and add RVWMO-derived relations plus one GMO witness."""

    operations = graph.operations
    non_regular = sorted(
        operation.id for operation in operations.values() if not _regular(operation)
    )
    if non_regular:
        raise GraphError(
            "RVWMO v0.16 only accepts regular main-memory operations; got "
            + ", ".join(non_regular)
        )
    _validate_scalar_locations(operations)
    canonical_po = _canonical_po(operations)
    existing_po = graph.relations.get("po")
    if existing_po is not None and existing_po.edges != canonical_po.edges:
        raise GraphError("po relation disagrees with hart/program_index metadata")

    relations = dict(graph.relations)
    relations["po"] = canonical_po
    try:
        rf = relations["rf"]
        co = relations["co"]
    except KeyError as exc:
        raise GraphError(f"RVWMO graph requires relation {exc.args[0]!r}") from exc
    rf_sources = _rf_sources(operations, rf)
    _validate_co(operations, co)

    rfi = Relation.from_edges(
        "rfi",
        (
            edge
            for edge in rf.edges
            if operations[edge[0]].hart == operations[edge[1]].hart
        ),
    )
    rfe = Relation.from_edges("rfe", rf.edges - rfi.edges)
    fr = Relation.from_edges(
        "fr",
        (
            (read_id, later_write)
            for source_write, read_id in rf.edges
            for before_write, later_write in co.edges
            if before_write == source_write and later_write != read_id
        ),
    )
    fri = Relation.from_edges(
        "fri",
        (
            edge
            for edge in fr.edges
            if operations[edge[0]].hart == operations[edge[1]].hart
        ),
    )
    fre = Relation.from_edges("fre", fr.edges - fri.edges)
    relations.update({item.name: item for item in (rfi, rfe, fr, fri, fre)})
    relations.update(
        {
            item.name: item
            for item in derive_ppo(operations, relations, rf_sources)
        }
    )

    order_relations = tuple(relations[name] for name in RVWMO_ORDER_RELATIONS)
    gmo_order = _topological_total_order(operations, order_relations)
    if gmo_order is None:
        gmo = Relation.from_edges("gmo", ())
    else:
        gmo = Relation.from_edges(
            "gmo",
            (
                (source, target)
                for index, source in enumerate(gmo_order)
                for target in gmo_order[index + 1 :]
            ),
        )
    relations["gmo"] = gmo
    metadata = dict(graph.metadata)
    metadata["builtin_model"] = "rvwmo"
    metadata["gmo_order"] = list(gmo_order or ())
    return ExecutionGraph(
        operations=operations,
        relations=relations,
        candidate_id=graph.candidate_id,
        metadata=metadata,
        schema_version=graph.schema_version,
    )


def _load_value_offenses(graph: ExecutionGraph) -> tuple[tuple[str, str], ...]:
    if not graph.metadata.get("gmo_order"):
        return ()
    position = {
        operation_id: index
        for index, operation_id in enumerate(graph.metadata["gmo_order"])
    }
    po = graph.relation("po")
    rf_sources = _rf_sources(graph.operations, graph.relation("rf"))
    offenses: list[tuple[str, str]] = []
    for read in (item for item in graph.operations.values() if item.is_read):
        eligible = [
            write
            for write in graph.operations.values()
            if write.is_write
            and write.id != read.id
            and _same_location(write, read)
            and (
                position[write.id] < position[read.id]
                or (write.id, read.id) in po.edges
            )
        ]
        if not eligible:
            offenses.append((rf_sources[read.id], read.id))
            continue
        latest = max(eligible, key=lambda item: position[item.id])
        if latest.id != rf_sources[read.id]:
            offenses.append((rf_sources[read.id], read.id))
    return tuple(sorted(offenses))


def _amo_offenses(graph: ExecutionGraph) -> tuple[tuple[str, str], ...]:
    co = graph.relation("co")
    rf_sources = _rf_sources(graph.operations, graph.relation("rf"))
    offenses: list[tuple[str, str]] = []
    for amo in (
        item for item in graph.operations.values() if item.atomic_kind == "amo"
    ):
        if not (amo.is_read and amo.is_write):
            offenses.append((amo.id, amo.id))
            continue
        source_id = rf_sources[amo.id]
        if (source_id, amo.id) not in co.edges:
            offenses.append((source_id, amo.id))
            continue
        intervening = any(
            write.is_write
            and write.id not in {source_id, amo.id}
            and _same_location(write, amo)
            and (source_id, write.id) in co.edges
            and (write.id, amo.id) in co.edges
            for write in graph.operations.values()
        )
        if intervening:
            offenses.append((source_id, amo.id))
    return tuple(sorted(offenses))


def _lr_sc_offenses(graph: ExecutionGraph) -> tuple[tuple[str, str], ...]:
    co = graph.relation("co")
    pair = _relation(graph.relations, "pair")
    rf_sources = _rf_sources(graph.operations, graph.relation("rf"))
    offenses: list[tuple[str, str]] = []
    incoming_pairs: dict[str, list[str]] = defaultdict(list)
    outgoing_pairs: dict[str, list[str]] = defaultdict(list)
    for lr_id, sc_id in pair.edges:
        incoming_pairs[sc_id].append(lr_id)
        outgoing_pairs[lr_id].append(sc_id)
    for sc in (
        item for item in graph.operations.values() if item.atomic_kind == "sc"
    ):
        if len(incoming_pairs.get(sc.id, ())) != 1:
            offenses.append((sc.id, sc.id))
    for lr_id, targets in outgoing_pairs.items():
        if len(targets) != 1:
            raise GraphError(f"LR {lr_id!r} is paired with multiple SC operations")
    for lr_id, sc_id in pair.edges:
        lr = graph.operations[lr_id]
        sc = graph.operations[sc_id]
        if lr.atomic_kind != "lr" or sc.atomic_kind != "sc":
            raise GraphError(f"pair edge {lr_id!r}->{sc_id!r} is not LR->SC")
        source_id = rf_sources[lr_id]
        if (source_id, sc_id) not in co.edges:
            offenses.append((lr_id, sc_id))
            continue
        intervening_external = any(
            write.is_write
            and write.id not in {source_id, sc_id}
            and write.hart != lr.hart
            and _overlap(write, lr)
            and (source_id, write.id) in co.edges
            and (write.id, sc_id) in co.edges
            for write in graph.operations.values()
        )
        if intervening_external:
            offenses.append((lr_id, sc_id))
    return tuple(sorted(offenses))


def check_rvwmo(graph: ExecutionGraph) -> tuple[RVWMOOutcome, ...]:
    """Check a graph completed by :func:`complete_rvwmo_relations`."""

    order_relations = tuple(graph.relation(name) for name in RVWMO_ORDER_RELATIONS)
    cycle = find_labeled_cycle(order_relations)
    load_value = _load_value_offenses(graph)
    amo = _amo_offenses(graph)
    lr_sc = _lr_sc_offenses(graph)
    return (
        RVWMOOutcome(
            name="rvwmo_global_memory_order",
            satisfied=cycle is None,
            kind="acyclic",
            relations=RVWMO_ORDER_RELATIONS,
            cycle=cycle or (),
        ),
        RVWMOOutcome(
            name="rvwmo_load_value",
            satisfied=not load_value,
            kind="latest-visible-write",
            relations=("po", "rf", "co", "gmo"),
            offending_edges=load_value,
        ),
        RVWMOOutcome(
            name="rvwmo_amo_atomicity",
            satisfied=not amo,
            kind="atomicity",
            relations=("rf", "co"),
            offending_edges=amo,
        ),
        RVWMOOutcome(
            name="rvwmo_lr_sc_atomicity",
            satisfied=not lr_sc,
            kind="atomicity",
            relations=("pair", "rf", "co"),
            offending_edges=lr_sc,
        ),
        RVWMOOutcome(
            name="rvwmo_progress_finite",
            satisfied=True,
            kind="finite-progress",
            relations=("gmo",),
        ),
    )
