"""Two-level bounded search: RVWMO skeletons, then public-interface realization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import permutations, product
from math import prod
from typing import Any, Callable, Iterable, Mapping

from umcm.composition import CompositionSpec, PortDirection, compose_modules
from umcm.errors import GraphError, SearchError
from umcm.graph.checker import check_trace_memory_model
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog, EventInstance, Visibility
from umcm.ir.expression import Binary, EventField, Literal, conjunction, disjunction
from umcm.ir.sort import BOOL
from umcm.ir.trace import Trace
from umcm.search.model import (
    HierarchicalSearchSpec,
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
            "schema_version": "umcm.search_report.v0.20.0",
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
        stages.append(
            _realize_coherence(
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
) -> Trace:
    mapping = spec.architecture.events
    events: list[EventInstance] = []
    for index, initial in enumerate(spec.architecture.init_writes):
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
                cycle=len(spec.architecture.operations) + index + 1,
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


def _validate_adapter_surface(
    catalog: EventCatalog,
    stage: RealizationStageSpec,
) -> None:
    generated = {stage.event_types["line_init"], stage.event_types["access"]}
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
