"""Public trace-completion API."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from umcm.errors import CompletionError, SolverError
from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import Expr
from umcm.ir.trace import Trace
from umcm.solver.evaluator import EvaluationContext, UNKNOWN, evaluate
from umcm.solver.finite import FiniteStatus, solve_finite
from umcm.solver.problem import BoundedProblem, build_problem


class CompletionStatus(str, Enum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class CompletionResult:
    status: CompletionStatus
    backend: str
    completed_trace: Trace | None = None
    assignment: dict[str, Any] = field(default_factory=dict)
    added_event_ids: tuple[str, ...] = ()
    explored_nodes: int = 0
    reason: str = ""
    instantiated_constraint_count: int = 0

    @property
    def feasible(self) -> bool:
        return self.status is CompletionStatus.FEASIBLE


def complete_trace(
    catalog: EventCatalog,
    trace: Trace,
    spec: CompletionSpec,
    *,
    backend: str = "auto",
    node_limit: int = 500_000,
) -> CompletionResult:
    """Complete *trace* within the bounded event universe from *spec*.

    ``auto`` currently selects the dependency-free finite backend.  The backend
    boundary is explicit so an SMT implementation can consume the same
    :class:`~umcm.solver.problem.BoundedProblem` later.
    """

    normalized_backend = backend.lower()
    if normalized_backend == "auto":
        normalized_backend = "finite"
    if normalized_backend != "finite":
        raise SolverError(
            f"unsupported completion backend {backend!r}; available: finite"
        )

    problem = build_problem(catalog, trace, spec)
    solved = solve_finite(problem, node_limit=node_limit)
    if solved.status is FiniteStatus.UNSAT:
        return CompletionResult(
            status=CompletionStatus.INFEASIBLE,
            backend="finite",
            explored_nodes=solved.explored_nodes,
            reason=solved.reason,
            instantiated_constraint_count=len(problem.constraints),
        )
    if solved.status is FiniteStatus.UNKNOWN:
        return CompletionResult(
            status=CompletionStatus.UNKNOWN,
            backend="finite",
            explored_nodes=solved.explored_nodes,
            reason=solved.reason,
            instantiated_constraint_count=len(problem.constraints),
        )

    completed = _materialize_trace(problem, solved.assignment)
    completed.validate(catalog, partial=False)
    selected_slot_ids = tuple(
        event.id
        for event in completed.events
        if event.id in set(problem.slot_ids)
    )
    return CompletionResult(
        status=CompletionStatus.FEASIBLE,
        backend="finite",
        completed_trace=completed,
        assignment=solved.assignment,
        added_event_ids=selected_slot_ids,
        explored_nodes=solved.explored_nodes,
        instantiated_constraint_count=len(problem.constraints),
    )


def _materialize_trace(
    problem: BoundedProblem,
    assignment: dict[str, Any],
) -> Trace:
    context = EvaluationContext(events=problem.event_map, assignment=assignment)
    events: list[EventInstance] = []
    for event in problem.events:
        occurs = _concrete(event.occurs, context, f"{event.id}.occurs")
        if not isinstance(occurs, bool):
            raise CompletionError(
                f"completed occurrence value for {event.id!r} is not boolean"
            )
        if not occurs:
            continue

        cycle = None
        if event.cycle is not None:
            cycle = _concrete(event.cycle, context, f"{event.id}.cycle")
            if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 0:
                raise CompletionError(
                    f"completed cycle for {event.id!r} is invalid: {cycle!r}"
                )

        fields: dict[str, Any] = {}
        for name, value in event.fields.items():
            fields[name] = _concrete(value, context, f"{event.id}.{name}")

        annotations = dict(event.annotations)
        if event.id in problem.slot_ids:
            annotations["completed"] = True
        events.append(
            EventInstance(
                id=event.id,
                event_type=event.event_type,
                fields=fields,
                cycle=cycle,
                occurs=True,
                annotations=annotations,
            )
        )

    metadata = dict(problem.source_trace.metadata)
    metadata["completion"] = {
        "backend": "finite",
        "horizon": problem.spec.horizon,
        "model": problem.spec.metadata,
        "selected_slots": [
            event.id for event in events if event.id in problem.slot_ids
        ],
    }
    return Trace(
        events=events,
        constraints=list(problem.source_trace.constraints),
        partial=False,
        metadata=metadata,
    )


def _concrete(value: Any, context: EvaluationContext, path: str) -> Any:
    result = evaluate(value, context) if isinstance(value, Expr) else value
    if result is UNKNOWN:
        raise CompletionError(f"completion left {path} unresolved")
    return result
