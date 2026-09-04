"""Two-level bounded search: RVWMO skeletons, then public-interface realization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import permutations, product
from math import prod
from typing import Any, Callable, Iterable, Mapping

from umcm.composition import CompositionSpec, PortDirection, compose_modules
from umcm.errors import CompositionError, GraphError, SearchError
from umcm.graph.checker import check_trace_memory_model
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog, EventInstance, Visibility
from umcm.ir.expression import Binary, EventField, Literal, conjunction, disjunction
from umcm.ir.sort import BOOL
from umcm.ir.trace import Trace
from umcm.search.model import (
    HierarchicalSearchSpec,
    InitWriteSpec,
    OperationSlotSpec,
    RealizationStageSpec,
)
from umcm.solver.completion import CompletionStatus, complete_problem
from umcm.solver.problem import BoundedProblem, NamedConstraint, build_problem


Progress = Callable[[str], None]


class StageStatus(str, Enum):
    REALIZABLE = "realizable"
    UNREALIZABLE = "unrealizable"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class SearchStatus(str, Enum):
    WITNESS = "witness"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    UNREALIZABLE = "unrealizable"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class OperationAssignment:
    id: str
    kind: str
    hart: int
    program_index: int
    address: Any
    value: Any
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "hart": self.hart,
            "program_index": self.program_index,
            "address": self.address,
            "value": self.value,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True, slots=True)
class ArchitecturalObligation:
    kind: str
    data: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **dict(self.data)}


@dataclass(slots=True)
class ArchitecturalSkeleton:
    graph: ExecutionGraph
    target_status: str
    obligations: tuple[ArchitecturalObligation, ...]
    violations: tuple[Mapping[str, Any], ...]
    trace: Trace

    def to_dict(self) -> dict[str, Any]:
        graph = self.graph
        preferred = ("po", "rf", "co", "fr", "ppo")
        relations = {
            name: [
                {"from": source, "to": target}
                for source, target in graph.relation(name).sorted_edges()
            ]
            for name in preferred
            if name in graph.relations
        }
        return {
            "status": self.target_status,
            "candidate_id": graph.candidate_id,
            "operations": [
                graph.operations[key].to_dict() for key in sorted(graph.operations)
            ],
            "relations": relations,
            "obligations": [item.to_dict() for item in self.obligations],
            "violations": [dict(item) for item in self.violations],
        }


@dataclass(slots=True)
class StageResult:
    name: str
    kind: str
    required: bool
    status: StageStatus
    reason: str = ""
    attempts: int = 0
    schedule: tuple[str, ...] = ()
    public_observations: tuple[Mapping[str, Any], ...] = ()
    path_evidence: tuple[Mapping[str, Any], ...] = ()
    missing_interfaces: tuple[str, ...] = ()
    witness: Trace | None = None
    witness_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "status": self.status.value,
            "attempts": self.attempts,
        }
        if self.reason:
            data["reason"] = self.reason
        if self.schedule:
            data["schedule"] = list(self.schedule)
        if self.public_observations:
            data["public_observations"] = [
                dict(item) for item in self.public_observations
            ]
        if self.path_evidence:
            data["path_evidence"] = [dict(item) for item in self.path_evidence]
        if self.missing_interfaces:
            data["missing_interfaces"] = list(self.missing_interfaces)
        if self.witness_path:
            data["witness_path"] = self.witness_path
        return data


@dataclass(slots=True)
class HierarchicalSearchReport:
    name: str
    status: SearchStatus
    skeleton: ArchitecturalSkeleton | None
    stages: tuple[StageResult, ...]
    assignments_examined: int
    assignments_rejected: int
    estimated_assignments: int
    architecture_exhausted: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def end_to_end(self) -> bool:
        return self.status is SearchStatus.WITNESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "umcm.search_report.v0.21.0",
            "name": self.name,
            "status": self.status.value,
            "end_to_end": self.end_to_end,
            "metadata": dict(self.metadata),
            "architecture": {
                "assignments_examined": self.assignments_examined,
                "assignments_rejected": self.assignments_rejected,
                "estimated_assignments": self.estimated_assignments,
                "exhausted": self.architecture_exhausted,
                "skeleton": (
                    None if self.skeleton is None else self.skeleton.to_dict()
                ),
            },
            "realization": {
                "stages": [stage.to_dict() for stage in self.stages]
            },
        }


@dataclass(frozen=True, slots=True)
class _ArchitectureOutcome:
    skeleton: ArchitecturalSkeleton | None
    examined: int
    rejected: int
    estimated: int
    exhausted: bool


@dataclass(slots=True)
class _ArchitectureCounters:
    examined: int = 0
    rejected: int = 0
    estimated: int = 0
    candidates: int = 0


def run_hierarchical_search(
    spec: HierarchicalSearchSpec,
    *,
    backend: str = "z3",
    node_limit: int = 500_000,
    progress: Progress | None = None,
) -> HierarchicalSearchReport:
    """Find an architectural target and realize it through declared interfaces.

    Layer one has no microarchitectural vocabulary. Layer two receives only the
    resulting operation/value/relation obligations; each concrete adapter is
    checked against the event catalog and module ports before solving.
    """

    notify = progress or (lambda _message: None)
    notify("layer 1: enumerating architectural executions")
    if (
        spec.architecture.generation == "bounded"
        and any(stage.kind == "boom_end_to_end" for stage in spec.stages)
    ):
        return _run_blind_end_to_end_search(
            spec,
            backend=backend,
            node_limit=node_limit,
            progress=notify,
        )

    architecture = _search_architecture(spec)
    if architecture.skeleton is None:
        return HierarchicalSearchReport(
            name=spec.name,
            status=SearchStatus.NOT_FOUND,
            skeleton=None,
            stages=(),
            assignments_examined=architecture.examined,
            assignments_rejected=architecture.rejected,
            estimated_assignments=architecture.estimated,
            architecture_exhausted=architecture.exhausted,
            metadata=dict(spec.metadata),
        )

    notify(
        f"layer 1: found {architecture.skeleton.target_status} skeleton "
        f"after {architecture.examined} assignment(s)"
    )
    stages: list[StageResult] = []
    for stage in spec.stages:
        notify(f"layer 2: {stage.name} ({stage.kind})")
        if stage.kind == "interface_gap":
            stages.append(
                StageResult(
                    name=stage.name,
                    kind=stage.kind,
                    required=stage.required,
                    status=StageStatus.BLOCKED,
                    reason=stage.reason,
                    missing_interfaces=stage.missing_interfaces,
                )
            )
            continue
        realize = (
            _realize_boom_end_to_end
            if stage.kind == "boom_end_to_end"
            else _realize_coherence
        )
        stages.append(
            realize(
                spec,
                stage,
                architecture.skeleton,
                backend=backend,
                node_limit=node_limit,
                progress=notify,
            )
        )

    status = _overall_status(stages)
    return HierarchicalSearchReport(
        name=spec.name,
        status=status,
        skeleton=architecture.skeleton,
        stages=tuple(stages),
        assignments_examined=architecture.examined,
        assignments_rejected=architecture.rejected,
        estimated_assignments=architecture.estimated,
        architecture_exhausted=architecture.exhausted,
        metadata=dict(spec.metadata),
    )


def _run_blind_end_to_end_search(
    spec: HierarchicalSearchSpec,
    *,
    backend: str,
    node_limit: int,
    progress: Progress,
) -> HierarchicalSearchReport:
    catalog = EventCatalog.load(spec.resolve(spec.catalog))
    graph_model = GraphModelSpec.load(spec.resolve(spec.architecture.model))
    counters = _ArchitectureCounters()
    last_skeleton: ArchitecturalSkeleton | None = None
    last_stages: tuple[StageResult, ...] = ()

    for skeleton in _bounded_architecture_candidates(
        spec, catalog, graph_model, counters
    ):
        last_skeleton = skeleton
        progress(
            "layer 1: candidate "
            f"{counters.candidates} is architecturally {skeleton.target_status}; "
            "checking the complete BOOM path"
        )
        stages: list[StageResult] = []
        for stage in spec.stages:
            if stage.kind == "interface_gap":
                stages.append(
                    StageResult(
                        name=stage.name,
                        kind=stage.kind,
                        required=stage.required,
                        status=StageStatus.BLOCKED,
                        reason=stage.reason,
                        missing_interfaces=stage.missing_interfaces,
                    )
                )
            elif stage.kind == "boom_end_to_end":
                stages.append(
                    _realize_boom_end_to_end(
                        spec,
                        stage,
                        skeleton,
                        backend=backend,
                        node_limit=node_limit,
                        progress=progress,
                    )
                )
            else:
                stages.append(
                    _realize_coherence(
                        spec,
                        stage,
                        skeleton,
                        backend=backend,
                        node_limit=node_limit,
                        progress=progress,
                    )
                )
        last_stages = tuple(stages)
        status = _overall_status(stages)
        if status is SearchStatus.WITNESS:
            return HierarchicalSearchReport(
                name=spec.name,
                status=status,
                skeleton=skeleton,
                stages=last_stages,
                assignments_examined=counters.examined,
                assignments_rejected=counters.rejected,
                estimated_assignments=counters.estimated,
                architecture_exhausted=False,
                metadata={
                    **dict(spec.metadata),
                    "architecture_candidates_realized": counters.candidates,
                },
            )

    return HierarchicalSearchReport(
        name=spec.name,
        status=SearchStatus.NOT_FOUND,
        skeleton=last_skeleton,
        stages=last_stages,
        assignments_examined=counters.examined,
        assignments_rejected=counters.rejected,
        estimated_assignments=counters.estimated,
        architecture_exhausted=(counters.examined < spec.bounds.max_assignments),
        metadata={
            **dict(spec.metadata),
            "architecture_candidates_realized": counters.candidates,
        },
    )


def _overall_status(stages: list[StageResult]) -> SearchStatus:
    required = [stage for stage in stages if stage.required]
    if not required or all(
        stage.status is StageStatus.REALIZABLE for stage in required
    ):
        return SearchStatus.WITNESS
    any_realizable = any(
        stage.status is StageStatus.REALIZABLE for stage in stages
    )
    if any_realizable:
        return SearchStatus.PARTIAL
    if any(stage.status is StageStatus.BLOCKED for stage in required):
        return SearchStatus.BLOCKED
    if any(stage.status is StageStatus.UNKNOWN for stage in required):
        return SearchStatus.PARTIAL
    return SearchStatus.UNREALIZABLE


def _search_architecture(spec: HierarchicalSearchSpec) -> _ArchitectureOutcome:
    catalog = EventCatalog.load(spec.resolve(spec.catalog))
    graph_model = GraphModelSpec.load(spec.resolve(spec.architecture.model))
    if spec.architecture.generation == "bounded":
        return _search_bounded_architecture(spec, catalog, graph_model)
    choices = [_slot_choices(slot) for slot in spec.architecture.operations]
    estimated = prod(len(items) for items in choices)
    examined = 0
    rejected = 0
    exhausted = estimated <= spec.bounds.max_assignments

    for selected in product(*choices):
        if examined >= spec.bounds.max_assignments:
            exhausted = False
            break
        if not _valid_program_assignment(selected):
            rejected += 1
            continue
        examined += 1
        trace = _architecture_trace(spec, selected)
        trace.validate(catalog, partial=False)
        try:
            checked = check_trace_memory_model(
                trace,
                graph_model,
                max_candidates=spec.bounds.max_graph_candidates,
            )
        except GraphError:
            rejected += 1
            continue
        if checked.status.value != spec.architecture.target:
            continue
        representative = checked.representative
        violations = tuple(
            result.to_dict()
            for result in representative.axioms
            if result.status.value == "violated"
        )
        skeleton = ArchitecturalSkeleton(
            graph=representative.graph,
            target_status=checked.status.value,
            obligations=_derive_obligations(representative.graph),
            violations=violations,
            trace=trace,
        )
        return _ArchitectureOutcome(
            skeleton, examined, rejected, estimated, exhausted=False
        )

    return _ArchitectureOutcome(None, examined, rejected, estimated, exhausted)


def _search_bounded_architecture(
    spec: HierarchicalSearchSpec,
    catalog: EventCatalog,
    graph_model: GraphModelSpec,
) -> _ArchitectureOutcome:
    """Generate programs from bounds without a fixed operation skeleton.

    The only reductions are semantic impossibility (a candidate execution needs
    both a read and a non-initial write) and identifier symmetry (the first used
    hart/address is named zero).  No cache/TLB/coherence vocabulary is present
    in this layer.
    """

    counters = _ArchitectureCounters()
    for skeleton in _bounded_architecture_candidates(
        spec, catalog, graph_model, counters
    ):
        return _ArchitectureOutcome(
            skeleton,
            counters.examined,
            counters.rejected,
            counters.estimated,
            exhausted=False,
        )
    return _ArchitectureOutcome(
        None,
        counters.examined,
        counters.rejected,
        counters.estimated,
        exhausted=counters.examined < spec.bounds.max_assignments,
    )


def _bounded_architecture_candidates(
    spec: HierarchicalSearchSpec,
    catalog: EventCatalog,
    graph_model: GraphModelSpec,
    counters: _ArchitectureCounters,
) -> Iterable[ArchitecturalSkeleton]:
    addresses = _bounded_addresses(spec.bounds.addresses)
    values = tuple(range(spec.bounds.values))
    init_writes = tuple(
        InitWriteSpec(
            id=_initial_write_id(address, index),
            address=address,
            value=values[0],
        )
        for index, address in enumerate(addresses)
    )
    choice_count = 2 * spec.bounds.harts * len(addresses) * len(values)
    counters.estimated = sum(
        choice_count**count for count in range(1, spec.bounds.memory_ops + 1)
    )
    raw_choices = tuple(
        (kind, hart, address, value)
        for kind, hart, address, value in product(
            ("load", "store"),
            range(spec.bounds.harts),
            addresses,
            values,
        )
    )
    for count in range(1, spec.bounds.memory_ops + 1):
        for raw in product(raw_choices, repeat=count):
            if counters.examined >= spec.bounds.max_assignments:
                return
            if not _bounded_candidate_is_canonical(raw, addresses[0]):
                counters.rejected += 1
                continue
            selected = _materialize_bounded_operations(raw)
            counters.examined += 1
            trace = _architecture_trace(
                spec,
                selected,
                init_writes=init_writes,
            )
            trace.validate(catalog, partial=False)
            try:
                checked = check_trace_memory_model(
                    trace,
                    graph_model,
                    max_candidates=spec.bounds.max_graph_candidates,
                )
            except GraphError:
                counters.rejected += 1
                continue
            if checked.status.value != spec.architecture.target:
                continue
            representative = checked.representative
            if not _core_order_candidate_possible(representative.graph):
                counters.rejected += 1
                continue
            violations = tuple(
                result.to_dict()
                for result in representative.axioms
                if result.status.value == "violated"
            )
            counters.candidates += 1
            yield ArchitecturalSkeleton(
                graph=representative.graph,
                target_status=checked.status.value,
                obligations=_derive_obligations(representative.graph),
                violations=violations,
                trace=trace,
            )


def _core_order_candidate_possible(graph: ExecutionGraph) -> bool:
    """Cheap BOOM-independent core-order filter before µMCM expansion.

    A hart cannot read from its own future store, retain the initial value past
    an older same-address store, or expose same-hart stores contrary to program
    order.  These are general retirement/store-buffer invariants, not a target
    litmus shape; pushing them ahead of SMT avoids expanding impossible graphs.
    """

    rf_source = {target: source for source, target in graph.relation("rf").edges}
    initial_ids = {
        operation.id
        for operation in graph.operations.values()
        if operation.kind is OperationKind.INIT_WRITE
    }
    writes = [
        operation
        for operation in graph.operations.values()
        if operation.kind is OperationKind.WRITE
    ]
    for read in graph.operations.values():
        if not read.is_read:
            continue
        source = graph.operations[rf_source[read.id]]
        if (
            source.id not in initial_ids
            and source.hart == read.hart
            and source.program_index > read.program_index
        ):
            return False
        if source.id in initial_ids and any(
            write.hart == read.hart
            and write.address == read.address
            and write.program_index < read.program_index
            for write in writes
        ):
            return False

    if "co" in graph.relations:
        coherence = graph.relation("co").edges
        for older in writes:
            for younger in writes:
                if (
                    older.hart == younger.hart
                    and older.address == younger.address
                    and older.program_index < younger.program_index
                    and (younger.id, older.id) in coherence
                ):
                    return False
    return True


def _bounded_addresses(count: int) -> tuple[str, ...]:
    conventional = ("x", "y", "z")
    return tuple(
        conventional[index] if index < len(conventional) else f"x{index}"
        for index in range(count)
    )


def _initial_write_id(address: str, index: int) -> str:
    rendered = "".join(character for character in address if character.isalnum())
    return f"Init{rendered[:1].upper()}{rendered[1:]}" if rendered else f"Init{index}"


def _bounded_candidate_is_canonical(
    raw: tuple[tuple[str, int, Any, Any], ...],
    first_address: Any,
) -> bool:
    kinds = {item[0] for item in raw}
    if kinds != {"load", "store"}:
        return False
    # A first-use renaming always maps the first hart/address to 0/x.
    if raw[0][1] != 0 or raw[0][2] != first_address:
        return False
    return True


def _materialize_bounded_operations(
    raw: tuple[tuple[str, int, Any, Any], ...],
) -> tuple[OperationAssignment, ...]:
    program_indexes: dict[int, int] = {}
    kind_indexes = {"load": 0, "store": 0}
    result: list[OperationAssignment] = []
    for kind, hart, address, value in raw:
        prefix = "L" if kind == "load" else "W"
        op_id = f"{prefix}{kind_indexes[kind]}"
        kind_indexes[kind] += 1
        program_index = program_indexes.get(hart, 0)
        program_indexes[hart] = program_index + 1
        result.append(
            OperationAssignment(
                id=op_id,
                kind=kind,
                hart=hart,
                program_index=program_index,
                address=address,
                value=value,
            )
        )
    return tuple(result)


def _slot_choices(slot: OperationSlotSpec) -> tuple[OperationAssignment, ...]:
    return tuple(
        OperationAssignment(
            id=slot.id,
            kind=kind,
            hart=hart,
            program_index=program_index,
            address=address,
            value=value,
            fields=slot.fields,
        )
        for kind, hart, program_index, address, value in product(
            slot.kinds,
            slot.harts,
            slot.program_indexes,
            slot.addresses,
            slot.values,
        )
    )


def _valid_program_assignment(
    assignments: Iterable[OperationAssignment],
) -> bool:
    positions: set[tuple[int, int]] = set()
    for operation in assignments:
        position = (operation.hart, operation.program_index)
        if position in positions:
            return False
        positions.add(position)
    return True


def _architecture_trace(
    spec: HierarchicalSearchSpec,
    assignments: Iterable[OperationAssignment],
    *,
    init_writes: Iterable[InitWriteSpec] | None = None,
) -> Trace:
    mapping = spec.architecture.events
    assignments = tuple(assignments)
    initial_values = tuple(
        spec.architecture.init_writes if init_writes is None else init_writes
    )
    events: list[EventInstance] = []
    for index, initial in enumerate(initial_values):
        fields = dict(mapping.defaults.get("init_write", {}))
        fields.update(
            op_id=initial.id, address=initial.address, value=initial.value
        )
        events.append(
            EventInstance(
                id=f"search_init_{index}_{initial.id}",
                event_type=mapping.init_write,
                fields=fields,
                cycle=0,
            )
        )

    for index, operation in enumerate(assignments):
        fields = dict(mapping.defaults.get(operation.kind, {}))
        fields.update(dict(operation.fields))
        fields.update(
            op_id=operation.id,
            hart=operation.hart,
            program_index=operation.program_index,
            address=operation.address,
        )
        if operation.kind == "store":
            fields["value"] = operation.value
            events.append(
                EventInstance(
                    id=f"search_store_{index}_{operation.id}",
                    event_type=mapping.store,
                    fields=fields,
                    cycle=index + 1,
                )
            )
            continue
        events.append(
            EventInstance(
                id=f"search_load_{index}_{operation.id}",
                event_type=mapping.load,
                fields=fields,
                cycle=index + 1,
            )
        )
        commit_fields = dict(mapping.defaults.get("commit_read", {}))
        commit_fields.update(op_id=operation.id, value=operation.value)
        events.append(
            EventInstance(
                id=f"search_commit_{index}_{operation.id}",
                event_type=mapping.commit_read,
                fields=commit_fields,
                cycle=len(assignments) + index + 1,
            )
        )
    return Trace(
        events=events,
        partial=False,
        metadata={
            "generated_by": "umcm.search.architecture",
            "microarchitecture_hints": False,
        },
    )


def _derive_obligations(
    graph: ExecutionGraph,
) -> tuple[ArchitecturalObligation, ...]:
    result: list[ArchitecturalObligation] = []
    rf_sources = {
        target: source for source, target in graph.relation("rf").edges
    }
    for operation in sorted(graph.operations.values(), key=lambda item: item.id):
        if operation.kind is OperationKind.INIT_WRITE:
            result.append(
                ArchitecturalObligation(
                    "initial_value",
                    {
                        "op_id": operation.id,
                        "address": operation.address,
                        "value": operation.value,
                    },
                )
            )
        elif operation.is_read:
            result.append(
                ArchitecturalObligation(
                    "read_from",
                    {
                        "read": operation.id,
                        "write": rf_sources[operation.id],
                        "address": operation.address,
                        "value": operation.read_value,
                    },
                )
            )
        if operation.kind is OperationKind.WRITE:
            result.append(
                ArchitecturalObligation(
                    "write_value",
                    {
                        "op_id": operation.id,
                        "address": operation.address,
                        "value": operation.stored_value,
                    },
                )
            )
    for name, kind in (
        ("po", "program_order"),
        ("co", "coherence_order"),
        ("fr", "from_read"),
        ("ppo", "preserved_order"),
    ):
        if name not in graph.relations:
            continue
        for source, target in graph.relation(name).sorted_edges():
            result.append(
                ArchitecturalObligation(kind, {"from": source, "to": target})
            )
    return tuple(result)


def _realize_coherence(
    search_spec: HierarchicalSearchSpec,
    stage: RealizationStageSpec,
    skeleton: ArchitecturalSkeleton,
    *,
    backend: str,
    node_limit: int,
    progress: Progress,
) -> StageResult:
    assert stage.catalog is not None and stage.composition is not None
    catalog = EventCatalog.load(search_spec.resolve(stage.catalog))
    composition = CompositionSpec.load(search_spec.resolve(stage.composition))
    _validate_adapter_surface(catalog, stage)
    schedules = _candidate_schedules(skeleton.graph, stage.max_schedules)
    last_reason = "no candidate schedule was solved"
    saw_unknown = False
    attempts = 0

    for schedule in schedules:
        attempts += 1
        trace = _coherence_input_trace(stage, skeleton.graph, schedule)
        trace.validate(catalog)
        composed = compose_modules(catalog, composition, trace)
        _validate_public_outputs(composed, stage)
        problem = build_problem(catalog, trace, composed.completion)
        _add_coherence_obligations(problem, stage, skeleton.graph)
        solved = complete_problem(
            problem, backend=backend, node_limit=node_limit
        )
        if solved.status is CompletionStatus.FEASIBLE:
            assert solved.completed_trace is not None
            observations = _public_observations(
                solved.completed_trace,
                {
                    *stage.input_event_types,
                    stage.event_types["load_result"],
                    stage.event_types["store_result"],
                },
            )
            progress(
                f"layer 2: {stage.name} realized schedule "
                + " -> ".join(schedule)
            )
            return StageResult(
                name=stage.name,
                kind=stage.kind,
                required=stage.required,
                status=StageStatus.REALIZABLE,
                attempts=attempts,
                schedule=schedule,
                public_observations=observations,
                witness=solved.completed_trace,
                reason=(
                    "architectural value/version obligations were satisfied using "
                    "only declared public request/result events"
                ),
            )
        last_reason = solved.reason or solved.status.value
        if solved.status is CompletionStatus.UNKNOWN:
            saw_unknown = True

    return StageResult(
        name=stage.name,
        kind=stage.kind,
        required=stage.required,
        status=StageStatus.UNKNOWN if saw_unknown else StageStatus.UNREALIZABLE,
        attempts=attempts,
        reason=last_reason,
    )


def _realize_boom_end_to_end(
    search_spec: HierarchicalSearchSpec,
    stage: RealizationStageSpec,
    skeleton: ArchitecturalSkeleton,
    *,
    backend: str,
    node_limit: int,
    progress: Progress,
) -> StageResult:
    """Realize one architectural candidate through the strict BOOM composition."""

    assert stage.catalog is not None and stage.composition is not None
    catalog = EventCatalog.load(search_spec.resolve(stage.catalog))
    coherence_composition = CompositionSpec.load(
        search_spec.resolve(stage.composition)
    )
    assert stage.core_composition is not None
    core_composition = CompositionSpec.load(
        search_spec.resolve(stage.core_composition)
    )
    _validate_adapter_surface(catalog, stage)
    schedules = _candidate_schedules(skeleton.graph, stage.max_schedules)
    configurations = _initial_microarchitecture_configurations(skeleton.graph)
    last_reason = "no public schedule/finite initial-state candidate was solved"
    saw_unknown = False
    attempts = 0

    for schedule in schedules:
        for configuration in configurations:
            attempts += 1
            trace = _boom_input_trace(
                stage,
                skeleton,
                schedule,
                configuration,
            )
            trace.validate(catalog)
            try:
                coherence_trace = _coherence_child_input(trace)
                coherence_model = compose_modules(
                    catalog, coherence_composition, coherence_trace
                )
                problem = build_problem(
                    catalog, coherence_trace, coherence_model.completion
                )
                _add_coherence_obligations(
                    problem, stage, skeleton.graph
                )
                _add_public_protocol_well_formedness(problem, stage)
                coherence_solved = complete_problem(
                    problem,
                    backend=backend,
                    node_limit=node_limit,
                    minimize_slots=False,
                )
            except CompositionError as exc:
                # Some generated candidates do not instantiate every finite
                # role required by a child composition.  That is a local
                # unrealizability result, not a malformed search query.
                last_reason = str(exc)
                continue

            if coherence_solved.status is CompletionStatus.FEASIBLE:
                assert coherence_solved.completed_trace is not None
                retimed_coherence = _retime_trace(
                    coherence_solved.completed_trace, offset=20
                )
                core_trace = _core_input_from_coherence(
                    trace, retimed_coherence
                )
                core_model = compose_modules(
                    catalog, core_composition, core_trace
                )
                _validate_boom_outputs(coherence_model, core_model, stage)
                core_problem = build_problem(
                    catalog, core_trace, core_model.completion
                )
                _add_retirement_obligations(
                    core_problem, stage, skeleton.graph
                )
                _add_core_well_formedness(core_problem)
                core_solved = complete_problem(
                    core_problem,
                    backend=backend,
                    node_limit=node_limit,
                    minimize_slots=False,
                )
                if core_solved.status is not CompletionStatus.FEASIBLE:
                    last_reason = core_solved.reason or core_solved.status.value
                    if core_solved.status is CompletionStatus.UNKNOWN:
                        saw_unknown = True
                    continue
                assert core_solved.completed_trace is not None
                completed = _merge_completed_traces(
                    retimed_coherence,
                    core_solved.completed_trace,
                )
                checked = _check_completed_architecture(
                    search_spec, completed
                )
                if checked != search_spec.architecture.target:
                    last_reason = (
                        "retired architectural projection was " + checked
                    )
                    continue
                observations = _public_observations(
                    completed,
                    {
                        *stage.input_event_types,
                        *stage.event_types.values(),
                        "Core.TranslatedMemory",
                        "Core.MemoryComplete",
                        "ROB.Commit",
                        "TL.Acquire",
                        "TL.Probe",
                        "TL.ProbeAck",
                        "TL.Grant",
                        "TL.GrantAck",
                        "DCache.ProbeRelease",
                    },
                )
                evidence = _path_evidence(completed)
                progress(
                    f"layer 2: {stage.name} realized schedule "
                    + " -> ".join(schedule)
                )
                return StageResult(
                    name=stage.name,
                    kind=stage.kind,
                    required=stage.required,
                    status=StageStatus.REALIZABLE,
                    attempts=attempts,
                    schedule=schedule,
                    public_observations=observations,
                    path_evidence=evidence,
                    witness=completed,
                    reason=(
                        "retired execution is RVWMO-forbidden and every dynamic "
                        "TLB/L1/MSHR/TileLink/ROB event was derived by the strict "
                        "public-interface composition"
                    ),
                )
            last_reason = coherence_solved.reason or coherence_solved.status.value
            if coherence_solved.status is CompletionStatus.UNKNOWN:
                saw_unknown = True

    return StageResult(
        name=stage.name,
        kind=stage.kind,
        required=stage.required,
        status=StageStatus.UNKNOWN if saw_unknown else StageStatus.UNREALIZABLE,
        attempts=attempts,
        reason=last_reason,
    )


def _initial_microarchitecture_configurations(
    graph: ExecutionGraph,
) -> tuple[Mapping[str, Any], ...]:
    """Enumerate coherent finite reset states, not per-access outcomes.

    Warm shared states are tried before cold states because the solver's normal
    objective is the fewest optional dynamic events.  A state says only what is
    resident before the bounded program; hit/miss/probe/grant remain derived.
    """

    dynamic = [
        operation
        for operation in graph.operations.values()
        if operation.kind is not OperationKind.INIT_WRITE
    ]
    used_harts = tuple(sorted({operation.hart for operation in dynamic}))
    load_harts = tuple(sorted({operation.hart for operation in dynamic if operation.is_read}))
    preferred = load_harts or used_harts or (0,)
    line_states: list[Mapping[str, Any]] = []
    for hart in preferred:
        line_states.append(
            {
                "h0_perm": "B" if hart == 0 else "N",
                "h1_perm": "B" if hart == 1 else "N",
                "l2_state": "BRANCH",
                "owner": -1,
            }
        )
    line_states.append(
        {"h0_perm": "N", "h1_perm": "N", "l2_state": "INVALID", "owner": -1}
    )
    tlb_states = tuple(
        {
            hart: (hart != delayed_hart)
            for hart in used_harts
        }
        for delayed_hart in preferred
    ) + (dict.fromkeys(used_harts, True),)
    return tuple(
        {**line_state, "tlb_initial_valid_by_hart": tlb_valid}
        for line_state in line_states
        for tlb_valid in tlb_states
    )


def _boom_input_trace(
    stage: RealizationStageSpec,
    skeleton: ArchitecturalSkeleton,
    schedule: tuple[str, ...],
    configuration: Mapping[str, Any],
) -> Trace:
    graph = skeleton.graph
    events: list[EventInstance] = []
    initial_by_address: dict[Any, MemoryOperation] = {}
    address_indexes: dict[Any, int] = {}

    for index, operation in enumerate(
        sorted(graph.operations.values(), key=lambda item: item.id)
    ):
        if operation.kind is not OperationKind.INIT_WRITE:
            continue
        initial_by_address[operation.address] = operation
        address_indexes[operation.address] = len(address_indexes)
        events.append(
            EventInstance(
                id=f"blind_arch_init_{index}_{operation.id}",
                event_type=stage.event_types["init_write"],
                cycle=0,
                fields={
                    "op_id": operation.id,
                    "address": operation.address,
                    "value": operation.value,
                },
            )
        )
        events.append(
            EventInstance(
                id=f"blind_line_{index}_{operation.id}",
                event_type=stage.event_types["line_init"],
                cycle=0,
                fields={
                    "line_id": str(operation.address),
                    "address": operation.address,
                    "value": operation.value,
                    "version": 0,
                    "source_op_id": operation.id,
                    "h0_perm": configuration["h0_perm"],
                    "h1_perm": configuration["h1_perm"],
                    "l2_state": configuration["l2_state"],
                    "owner": configuration["owner"],
                },
            )
        )

    dynamic = sorted(
        (
            operation
            for operation in graph.operations.values()
            if operation.kind is not OperationKind.INIT_WRITE
        ),
        key=lambda item: (item.hart, item.program_index, item.id),
    )
    for index, operation in enumerate(dynamic):
        initial = initial_by_address[operation.address]
        address_index = address_indexes[operation.address]
        events.append(
            EventInstance(
                id=f"blind_instruction_{index}_{operation.id}",
                event_type=stage.event_types["memory_instruction"],
                cycle=index + 1,
                fields={
                    "op_id": operation.id,
                    "hart": operation.hart,
                    "program_index": operation.program_index,
                    "rob_idx": index,
                    "mem_kind": "load" if operation.is_read else "store",
                    "vaddr": operation.address,
                    "address": operation.address,
                    "vpn": address_index,
                    "value": (
                        operation.read_value if operation.is_read else initial.value
                    ),
                    "write_value": (
                        initial.value if operation.is_read else operation.stored_value
                    ),
                    "byte_mask": 255,
                    "cacheable": True,
                    "io_id": -1,
                    "reservation_id": "NONE",
                    "uses_tlb": True,
                    "execution_class": "ordinary",
                },
            )
        )

    page_keys = sorted(
        {(operation.hart, operation.address) for operation in dynamic},
        key=lambda item: (item[0], str(item[1])),
    )
    for index, (hart, address) in enumerate(page_keys):
        address_index = address_indexes[address]
        events.append(
            EventInstance(
                id=f"blind_page_{index}_h{hart}_{address}",
                event_type=stage.event_types["page_map"],
                cycle=0,
                fields={
                    "map_id": f"MapH{hart}A{address_index}",
                    "hart": hart,
                    "entry_id": f"h{hart}_a{address_index}",
                    "vpn": address_index,
                    "paddr": address,
                    "initial_valid": configuration[
                        "tlb_initial_valid_by_hart"
                    ].get(hart, True),
                    "accessible": True,
                },
            )
        )

    previous = "NONE"
    for index, op_id in enumerate(schedule):
        operation = graph.operations[op_id]
        initial = initial_by_address[operation.address]
        events.append(
            EventInstance(
                id=f"blind_access_{index}_{op_id}",
                event_type=stage.event_types["access"],
                cycle=stage.cycle_start + index * stage.cycle_stride,
                fields={
                    "op_id": operation.id,
                    "hart": operation.hart,
                    "program_index": operation.program_index,
                    "line_id": str(operation.address),
                    "address": operation.address,
                    "mem_kind": "load" if operation.is_read else "store",
                    "write_value": (
                        initial.value if operation.is_read else operation.stored_value
                    ),
                    "after_op_id": previous,
                },
            )
        )
        previous = operation.id

    return Trace(
        events=events,
        partial=True,
        metadata={
            "generated_by": "umcm.search.blind_v021",
            "schedule": list(schedule),
            "finite_initial_state": dict(configuration),
            "input_contract": (
                "bounds-derived public instructions/configuration/accesses only; "
                "no dynamic TLB/cache/MSHR/probe/result event is supplied"
            ),
        },
    )


def _add_retirement_obligations(
    problem: BoundedProblem,
    stage: RealizationStageSpec,
    graph: ExecutionGraph,
) -> None:
    for operation in graph.operations.values():
        if operation.kind is OperationKind.INIT_WRITE:
            continue
        if operation.is_read:
            arch = _matching_public_event(
                problem,
                stage.event_types["arch_load"],
                {
                    "op_id": operation.id,
                    "hart": operation.hart,
                    "program_index": operation.program_index,
                    "address": operation.address,
                },
            )
            commit = _matching_public_event(
                problem,
                stage.event_types["commit_read"],
                {"op_id": operation.id, "value": operation.read_value},
            )
            obligation = conjunction((arch, commit))
        else:
            obligation = _matching_public_event(
                problem,
                stage.event_types["arch_store"],
                {
                    "op_id": operation.id,
                    "hart": operation.hart,
                    "program_index": operation.program_index,
                    "address": operation.address,
                    "value": operation.stored_value,
                },
            )
        problem.constraints.append(
            NamedConstraint(
                name=f"search.retirement.{operation.id}",
                expression=obligation,
                origin="hierarchical-search:retired-architectural-obligation",
            )
        )


def _add_public_protocol_well_formedness(
    problem: BoundedProblem,
    stage: RealizationStageSpec,
) -> None:
    """Rule out unsupported public TileLink traffic without fixing a path."""

    result_types = {
        stage.event_types["load_result"],
        stage.event_types["store_result"],
    }
    results = [event for event in problem.events if event.event_type in result_types]
    transaction_types = ("TL.Acquire", "TL.Probe", "TL.Grant")
    for transaction_type in transaction_types:
        transaction_schema = problem.catalog.resolve(transaction_type)
        transactions = [
            event
            for event in problem.events
            if event.event_type == transaction_type
        ]
        for transaction in transactions:
            matching_refills = []
            for result in results:
                result_schema = problem.catalog.resolve(result.event_type)
                same_transaction = Binary(
                    "eq",
                    EventField(
                        transaction.id,
                        "txn_id",
                        transaction_schema.field_map["txn_id"].sort,
                    ),
                    EventField(
                        result.id,
                        "op_id",
                        result_schema.field_map["op_id"].sort,
                    ),
                )
                refill = Binary(
                    "eq",
                    EventField(
                        result.id,
                        "path",
                        result_schema.field_map["path"].sort,
                    ),
                    Literal(
                        "refill",
                        result_schema.field_map["path"].sort,
                    ),
                )
                matching_refills.append(
                    conjunction(
                        (
                            EventField(result.id, "occurs", BOOL),
                            same_transaction,
                            refill,
                        )
                    )
                )
            problem.constraints.append(
                NamedConstraint(
                    name=(
                        "search.protocol.transaction_requires_refill."
                        f"{transaction.id}"
                    ),
                    expression=Binary(
                        "implies",
                        EventField(transaction.id, "occurs", BOOL),
                        disjunction(matching_refills),
                    ),
                    origin=(
                        "hierarchical-search:public-protocol-"
                        "well-formedness"
                    ),
                )
            )

    probe_schema = problem.catalog.resolve("TL.Probe")
    for probe in (
        event for event in problem.events if event.event_type == "TL.Probe"
    ):
        not_self = Binary(
            "ne",
            EventField(
                probe.id,
                "requester_hart",
                probe_schema.field_map["requester_hart"].sort,
            ),
            EventField(
                probe.id,
                "target_hart",
                probe_schema.field_map["target_hart"].sort,
            ),
        )
        problem.constraints.append(
            NamedConstraint(
                name=f"search.protocol.no_self_probe.{probe.id}",
                expression=Binary(
                    "implies",
                    EventField(probe.id, "occurs", BOOL),
                    not_self,
                ),
                origin="hierarchical-search:public-protocol-well-formedness",
            )
        )


def _add_core_well_formedness(problem: BoundedProblem) -> None:
    """Close optional recovery/cardinality holes for an ordinary input program."""

    absent_without_input = {
        "Core.MemoryFault",
        "ROB.ExceptionRecord",
        "ROB.PreciseException",
        "Core.SquashMemory",
        "Core.BranchKill",
    }
    for event in problem.events:
        if event.event_type not in absent_without_input:
            continue
        problem.constraints.append(
            NamedConstraint(
                name=f"search.core.no_unsourced_recovery.{event.id}",
                expression=Binary(
                    "eq",
                    EventField(event.id, "occurs", BOOL),
                    Literal(False, BOOL),
                ),
                origin="hierarchical-search:ordinary-program-well-formedness",
            )
        )

    for event_type in ("TLB.Miss", "TLB.Retry"):
        schema = problem.catalog.resolve(event_type)
        events = [event for event in problem.events if event.event_type == event_type]
        for left_index, left in enumerate(events):
            for right in events[left_index + 1 :]:
                both = conjunction(
                    (
                        EventField(left.id, "occurs", BOOL),
                        EventField(right.id, "occurs", BOOL),
                    )
                )
                different_entry = disjunction(
                    (
                        Binary(
                            "ne",
                            EventField(
                                left.id,
                                "hart",
                                schema.field_map["hart"].sort,
                            ),
                            EventField(
                                right.id,
                                "hart",
                                schema.field_map["hart"].sort,
                            ),
                        ),
                        Binary(
                            "ne",
                            EventField(
                                left.id,
                                "vpn",
                                schema.field_map["vpn"].sort,
                            ),
                            EventField(
                                right.id,
                                "vpn",
                                schema.field_map["vpn"].sort,
                            ),
                        ),
                    )
                )
                problem.constraints.append(
                    NamedConstraint(
                        name=f"search.core.one_{event_type}.{left.id}.{right.id}",
                        expression=Binary("implies", both, different_entry),
                        origin="hierarchical-search:finite-resource-cardinality",
                    )
                )

    # Optional cacheable-path slots keep the child compositional.  Close their
    # reverse direction for a non-optimizing search solve: MSHR activity must
    # belong to a load whose public coherence result took the refill path.
    load_results = [
        event
        for event in problem.events
        if event.event_type == "Coherence.LoadResult"
    ]
    refill_only_types = {
        "DCache.MSHRRequest",
        "MSHR.PrimaryMissAccept",
        "MSHR.AcquireBlock",
        "MSHR.GrantData",
        "MSHR.RefillComplete",
        "DCache.LongLatencyLoadResponse",
    }
    for event in problem.events:
        if event.event_type not in refill_only_types:
            continue
        event_schema = problem.catalog.resolve(event.event_type)
        matching_refills = []
        for result in load_results:
            result_schema = problem.catalog.resolve(result.event_type)
            matching_refills.append(
                conjunction(
                    (
                        EventField(result.id, "occurs", BOOL),
                        Binary(
                            "eq",
                            EventField(
                                event.id,
                                "op_id",
                                event_schema.field_map["op_id"].sort,
                            ),
                            EventField(
                                result.id,
                                "op_id",
                                result_schema.field_map["op_id"].sort,
                            ),
                        ),
                        Binary(
                            "eq",
                            EventField(
                                result.id,
                                "path",
                                result_schema.field_map["path"].sort,
                            ),
                            Literal(
                                "refill",
                                result_schema.field_map["path"].sort,
                            ),
                        ),
                    )
                )
            )
        problem.constraints.append(
            NamedConstraint(
                name=f"search.core.refill_sources_mshr.{event.id}",
                expression=Binary(
                    "implies",
                    EventField(event.id, "occurs", BOOL),
                    disjunction(matching_refills),
                ),
                origin="hierarchical-search:cacheable-path-well-formedness",
            )
        )

    # Assertion-only LD-LD evidence must name a real older/younger pair;
    # unconstrained monitor slots may not manufacture self or reversed pairs.
    instructions = [
        event
        for event in problem.events
        if event.event_type == "Core.MemoryInstruction"
    ]
    instruction_schema = problem.catalog.resolve("Core.MemoryInstruction")
    for event in problem.events:
        if event.event_type not in {"LSU.LDLDConflict", "LSU.AssertViolation"}:
            continue
        event_schema = problem.catalog.resolve(event.event_type)
        ordered_pairs = []
        for older in instructions:
            for younger in instructions:
                ordered_pairs.append(
                    conjunction(
                        (
                            EventField(older.id, "occurs", BOOL),
                            EventField(younger.id, "occurs", BOOL),
                            Binary(
                                "eq",
                                EventField(
                                    event.id,
                                    "older_op_id",
                                    event_schema.field_map["older_op_id"].sort,
                                ),
                                EventField(
                                    older.id,
                                    "op_id",
                                    instruction_schema.field_map["op_id"].sort,
                                ),
                            ),
                            Binary(
                                "eq",
                                EventField(
                                    event.id,
                                    "younger_op_id",
                                    event_schema.field_map["younger_op_id"].sort,
                                ),
                                EventField(
                                    younger.id,
                                    "op_id",
                                    instruction_schema.field_map["op_id"].sort,
                                ),
                            ),
                            Binary(
                                "eq",
                                EventField(
                                    older.id,
                                    "hart",
                                    instruction_schema.field_map["hart"].sort,
                                ),
                                EventField(
                                    younger.id,
                                    "hart",
                                    instruction_schema.field_map["hart"].sort,
                                ),
                            ),
                            Binary(
                                "eq",
                                EventField(
                                    older.id,
                                    "address",
                                    instruction_schema.field_map["address"].sort,
                                ),
                                EventField(
                                    younger.id,
                                    "address",
                                    instruction_schema.field_map["address"].sort,
                                ),
                            ),
                            Binary(
                                "lt",
                                EventField(
                                    older.id,
                                    "program_index",
                                    instruction_schema.field_map[
                                        "program_index"
                                    ].sort,
                                ),
                                EventField(
                                    younger.id,
                                    "program_index",
                                    instruction_schema.field_map[
                                        "program_index"
                                    ].sort,
                                ),
                            ),
                        )
                    )
                )
        problem.constraints.append(
            NamedConstraint(
                name=f"search.core.real_ldld_pair.{event.id}",
                expression=Binary(
                    "implies",
                    EventField(event.id, "occurs", BOOL),
                    disjunction(ordered_pairs),
                ),
                origin="hierarchical-search:lsq-monitor-well-formedness",
            )
        )


def _coherence_child_input(source: Trace) -> Trace:
    root_types = {"Coherence.LineInit", "Coherence.Access"}
    return Trace(
        events=[event for event in source.events if event.event_type in root_types],
        partial=True,
        metadata={
            **dict(source.metadata),
            "hierarchical_child": "coherence",
        },
    )


def _retime_trace(trace: Trace, *, offset: int) -> Trace:
    """Embed one child model's local bounded cycles in the parent timeline."""

    return Trace(
        events=[
            EventInstance(
                id=event.id,
                event_type=event.event_type,
                fields=dict(event.fields),
                cycle=(
                    event.cycle + offset
                    if isinstance(event.cycle, int) and event.cycle > 0
                    else event.cycle
                ),
                occurs=event.occurs,
                annotations=dict(event.annotations),
            )
            for event in trace.events
        ],
        partial=trace.partial,
        metadata={
            **dict(trace.metadata),
            "hierarchical_cycle_offset": offset,
        },
    )


def _core_input_from_coherence(source: Trace, coherence: Trace) -> Trace:
    bridge_types = {
        "Coherence.Access",
        "Coherence.LoadResult",
        "Coherence.StorePerformed",
        "TL.Acquire",
        "TL.Probe",
        "TL.Grant",
    }
    source_types = {
        "Arch.InitWrite",
        "Core.MemoryInstruction",
        "Core.PageMap",
    }
    events = [event for event in source.events if event.event_type in source_types]
    known = {event.id for event in events}
    events.extend(
        event
        for event in coherence.events
        if event.event_type in bridge_types
        and event.occurs is True
        and event.id not in known
    )
    return Trace(
        events=events,
        partial=True,
        metadata={
            **dict(source.metadata),
            "derived_interface_events": sorted(bridge_types),
            "interface_source": "sifive-inclusive-coherence-v021",
        },
    )


def _merge_completed_traces(*traces: Trace) -> Trace:
    by_id: dict[str, EventInstance] = {}
    for trace in traces:
        for event in trace.events:
            previous = by_id.get(event.id)
            if previous is not None and (
                previous.event_type != event.event_type
                or previous.fields != event.fields
                or previous.cycle != event.cycle
            ):
                raise SearchError(
                    f"hierarchical witness event id {event.id!r} disagrees "
                    "across child compositions"
                )
            by_id[event.id] = event
    return Trace(
        events=sorted(
            by_id.values(),
            key=lambda event: (
                event.cycle if isinstance(event.cycle, int) else 10**18,
                event.id,
            ),
        ),
        partial=False,
        metadata={
            "generated_by": "umcm.search.hierarchical_merge_v021",
            "child_witnesses": len(traces),
            "input_contract": (
                "all dynamic interface events originate in a solved child model"
            ),
        },
    )


def _validate_boom_outputs(
    coherence_model: Any,
    core_model: Any,
    stage: RealizationStageSpec,
) -> None:
    output_types = {
        port.event_type
        for composed in (coherence_model, core_model)
        for loaded in composed.modules
        for port in loaded.spec.ports
        if port.direction is PortDirection.OUTPUT
    }
    required = {
        stage.event_types["load_result"],
        stage.event_types["store_result"],
        stage.event_types["arch_load"],
        stage.event_types["arch_store"],
        stage.event_types["commit_read"],
        "Core.MemoryComplete",
    }
    missing = required - output_types
    if missing:
        raise SearchError(
            f"end-to-end obligation output(s) are not public module ports: "
            + ", ".join(sorted(missing))
        )


def _check_completed_architecture(
    search_spec: HierarchicalSearchSpec,
    completed: Trace,
) -> str:
    architecture_types = {
        search_spec.architecture.events.init_write,
        search_spec.architecture.events.load,
        search_spec.architecture.events.store,
        search_spec.architecture.events.commit_read,
    }
    projected = Trace(
        events=[
            event
            for event in completed.events
            if event.event_type in architecture_types
        ],
        partial=False,
        metadata={"generated_by": "umcm.search.retired_projection"},
    )
    graph_model = GraphModelSpec.load(
        search_spec.resolve(search_spec.architecture.model)
    )
    checked = check_trace_memory_model(
        projected,
        graph_model,
        max_candidates=search_spec.bounds.max_graph_candidates,
    )
    return checked.status.value


def _path_evidence(trace: Trace) -> tuple[Mapping[str, Any], ...]:
    evidence_types = {
        "TLB.Miss",
        "TLB.Retry",
        "Core.TranslatedMemory",
        "Coherence.LoadResult",
        "Coherence.StorePerformed",
        "DCache.LoadResponse",
        "DCache.LongLatencyLoadResponse",
        "DCache.ProbeRelease",
        "MSHR.PrimaryMissAccept",
        "MSHR.AcquireBlock",
        "MSHR.GrantData",
        "MSHR.RefillWrite",
        "TL.Acquire",
        "TL.Probe",
        "TL.Grant",
        "LSU.LoadObserved",
        "LSU.LDLDConflict",
        "LSU.AssertViolation",
        "ROB.Commit",
    }
    return _public_observations(trace, evidence_types)


def _validate_adapter_surface(
    catalog: EventCatalog,
    stage: RealizationStageSpec,
) -> None:
    generated = {stage.event_types["line_init"], stage.event_types["access"]}
    if stage.kind == "boom_end_to_end":
        generated.update(
            {
                stage.event_types["init_write"],
                stage.event_types["memory_instruction"],
                stage.event_types["page_map"],
            }
        )
    undeclared = generated - set(stage.input_event_types)
    if undeclared:
        raise SearchError(
            f"stage {stage.name!r} adapter would inject undeclared input type(s): "
            + ", ".join(sorted(undeclared))
        )
    for event_type in (*stage.input_event_types, *stage.event_types.values()):
        declared = catalog.resolve(event_type)
        if declared.visibility is Visibility.INTERNAL:
            raise SearchError(
                f"stage {stage.name!r} references private event type {event_type!r}"
            )


def _validate_public_outputs(composed: Any, stage: RealizationStageSpec) -> None:
    output_types = {
        port.event_type
        for loaded in composed.modules
        for port in loaded.spec.ports
        if port.direction is PortDirection.OUTPUT
    }
    required = {
        stage.event_types["load_result"], stage.event_types["store_result"]
    }
    if stage.kind == "boom_end_to_end":
        required.update(
            {
                stage.event_types["arch_load"],
                stage.event_types["arch_store"],
                stage.event_types["commit_read"],
                "Core.MemoryComplete",
            }
        )
    missing = required - output_types
    if missing:
        raise SearchError(
            f"stage {stage.name!r} obligation output(s) are not public module ports: "
            + ", ".join(sorted(missing))
        )


def _candidate_schedules(
    graph: ExecutionGraph,
    limit: int,
) -> tuple[tuple[str, ...], ...]:
    dynamic = tuple(
        sorted(
            operation.id
            for operation in graph.operations.values()
            if operation.kind is not OperationKind.INIT_WRITE
        )
    )
    preferred: set[tuple[str, str]] = set()
    init_ids = {
        operation.id
        for operation in graph.operations.values()
        if operation.kind is OperationKind.INIT_WRITE
    }
    for name in ("rf", "co", "fr"):
        if name not in graph.relations:
            continue
        preferred.update(
            (source, target)
            for source, target in graph.relation(name).edges
            if source not in init_ids and target not in init_ids
        )

    def score(order: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
        positions = {op_id: index for index, op_id in enumerate(order)}
        violations = sum(
            positions[source] >= positions[target]
            for source, target in preferred
        )
        return violations, order

    ordered = sorted(permutations(dynamic), key=score)
    return tuple(ordered[:limit])


def _coherence_input_trace(
    stage: RealizationStageSpec,
    graph: ExecutionGraph,
    schedule: tuple[str, ...],
) -> Trace:
    events: list[EventInstance] = []
    initial_by_address: dict[Any, MemoryOperation] = {}
    for index, operation in enumerate(
        sorted(graph.operations.values(), key=lambda item: item.id)
    ):
        if operation.kind is not OperationKind.INIT_WRITE:
            continue
        initial_by_address[operation.address] = operation
        events.append(
            EventInstance(
                id=f"search_line_{index}_{operation.id}",
                event_type=stage.event_types["line_init"],
                cycle=0,
                fields={
                    "line_id": str(operation.address),
                    "address": operation.address,
                    "value": operation.value,
                    "version": 0,
                    "source_op_id": operation.id,
                },
            )
        )

    previous = "NONE"
    for index, op_id in enumerate(schedule):
        operation = graph.operations[op_id]
        if operation.address not in initial_by_address:
            raise SearchError(
                f"operation {op_id!r} has no initial value for address "
                f"{operation.address!r}"
            )
        write_value = (
            operation.stored_value
            if operation.kind is OperationKind.WRITE
            else initial_by_address[operation.address].value
        )
        events.append(
            EventInstance(
                id=f"search_access_{index}_{op_id}",
                event_type=stage.event_types["access"],
                cycle=stage.cycle_start + index * stage.cycle_stride,
                fields={
                    "op_id": operation.id,
                    "hart": operation.hart,
                    "program_index": operation.program_index,
                    "line_id": str(operation.address),
                    "address": operation.address,
                    "mem_kind": (
                        "load" if operation.is_read else "store"
                    ),
                    "write_value": write_value,
                    "after_op_id": previous,
                },
            )
        )
        previous = operation.id

    return Trace(
        events=events,
        partial=True,
        metadata={
            "generated_by": "umcm.search.coherence_access",
            "schedule": list(schedule),
            "input_contract": (
                "public line/access requests only; no hit, miss, probe, grant, "
                "MSHR, queue index, or result event is supplied"
            ),
        },
    )


def _add_coherence_obligations(
    problem: BoundedProblem,
    stage: RealizationStageSpec,
    graph: ExecutionGraph,
) -> None:
    rf_sources = {
        target: source for source, target in graph.relation("rf").edges
    }
    for operation in graph.operations.values():
        if operation.kind is OperationKind.INIT_WRITE:
            continue
        if operation.is_read:
            expression = _matching_public_event(
                problem,
                stage.event_types["load_result"],
                {
                    "op_id": operation.id,
                    "address": operation.address,
                    "value": operation.read_value,
                    "source_op_id": rf_sources[operation.id],
                },
            )
            label = f"read_from.{operation.id}.{rf_sources[operation.id]}"
        else:
            expression = _matching_public_event(
                problem,
                stage.event_types["store_result"],
                {
                    "op_id": operation.id,
                    "address": operation.address,
                    "value": operation.stored_value,
                    "source_op_id": operation.id,
                },
            )
            label = f"write_value.{operation.id}"
        problem.constraints.append(
            NamedConstraint(
                name=f"search.obligation.{label}",
                expression=expression,
                origin="hierarchical-search:architectural-obligation",
            )
        )


def _matching_public_event(
    problem: BoundedProblem,
    event_type: str,
    expected: Mapping[str, Any],
):
    event_schema = problem.catalog.resolve(event_type)
    alternatives = []
    for event in problem.events:
        if event.event_type != event_type:
            continue
        comparisons = [EventField(event.id, "occurs", BOOL)]
        for field_name, value in expected.items():
            try:
                sort = event_schema.field_map[field_name].sort
            except KeyError as exc:
                raise SearchError(
                    f"public obligation event {event_type!r} has no "
                    f"field {field_name!r}"
                ) from exc
            comparisons.append(
                Binary(
                    "eq",
                    EventField(event.id, field_name, sort),
                    Literal(value, sort),
                )
            )
        alternatives.append(conjunction(comparisons))
    if not alternatives:
        raise SearchError(
            f"composition produced no bounded public {event_type!r} output slot"
        )
    return disjunction(alternatives)


def _public_observations(
    trace: Trace,
    event_types: set[str],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        event.to_dict()
        for event in sorted(
            (
                event
                for event in trace.events
                if event.event_type in event_types and event.occurs is True
            ),
            key=lambda item: (
                item.cycle if isinstance(item.cycle, int) else 10**18,
                item.id,
            ),
        )
    )
