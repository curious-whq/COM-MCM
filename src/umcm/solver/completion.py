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
from umcm.solver.z3ctypes import solve_z3
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
    initial_state: dict[str, Any] = field(default_factory=dict)
    final_state: dict[str, Any] = field(default_factory=dict)
    state_steps: tuple[dict[str, Any], ...] = ()
    active_transformations: tuple[dict[str, Any], ...] = ()

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

    ``auto`` preserves the deterministic finite reference backend for backward
    compatibility.  ``z3`` may be selected explicitly for larger bounded models.
    """

    problem = build_problem(catalog, trace, spec)
    return complete_problem(problem, backend=backend, node_limit=node_limit)


def complete_problem(
    problem: BoundedProblem,
    *,
    backend: str = "auto",
    node_limit: int = 500_000,
    minimize_slots: bool = True,
) -> CompletionResult:
    """Solve an already-instantiated problem.

    Coverage and search queries use this entry point to add obligations to the
    same bounded problem that implements normal trace completion.  Z3 callers
    may disable slot minimization when they need the first feasible model and
    separately enforce witness well-formedness.
    """

    normalized_backend = backend.lower()
    if normalized_backend == "auto":
        normalized_backend = "finite"
    if normalized_backend not in {"finite", "z3"}:
        raise SolverError(
            f"unsupported completion backend {backend!r}; available: finite, z3"
        )

    solved = (
        solve_z3(problem, minimize_slots=minimize_slots)
        if normalized_backend == "z3"
        else solve_finite(problem, node_limit=node_limit)
    )
    if solved.status is FiniteStatus.UNSAT:
        return CompletionResult(
            status=CompletionStatus.INFEASIBLE,
            backend=normalized_backend,
            explored_nodes=solved.explored_nodes,
            reason=solved.reason,
            instantiated_constraint_count=len(problem.constraints),
        )
    if solved.status is FiniteStatus.UNKNOWN:
        return CompletionResult(
            status=CompletionStatus.UNKNOWN,
            backend=normalized_backend,
            explored_nodes=solved.explored_nodes,
            reason=solved.reason,
            instantiated_constraint_count=len(problem.constraints),
        )

    completed = _materialize_trace(
        problem,
        solved.assignment,
        state_result=solved.state_result,
        backend=normalized_backend,
    )
    completed.validate(problem.catalog, partial=False)
    selected_slot_ids = tuple(
        event.id
        for event in completed.events
        if event.id in set(problem.slot_ids)
    )
    active_transformations = _active_transformations(
        problem, solved.assignment, solved.state_result
    )
    completed.metadata["completion"]["active_transformations"] = [
        dict(item) for item in active_transformations
    ]
    return CompletionResult(
        status=CompletionStatus.FEASIBLE,
        backend=normalized_backend,
        completed_trace=completed,
        assignment=solved.assignment,
        added_event_ids=selected_slot_ids,
        explored_nodes=solved.explored_nodes,
        instantiated_constraint_count=len(problem.constraints),
        initial_state=(
            dict(solved.state_result.initial_state)
            if solved.state_result is not None
            else {}
        ),
        final_state=(
            dict(solved.state_result.final_state)
            if solved.state_result is not None
            else {}
        ),
        state_steps=(
            tuple(step.to_dict() for step in solved.state_result.steps)
            if solved.state_result is not None
            else ()
        ),
        active_transformations=active_transformations,
    )


def _active_transformations(
    problem: BoundedProblem,
    assignment: dict[str, Any],
    state_result: Any,
) -> tuple[dict[str, Any], ...]:
    context = EvaluationContext(events=problem.event_map, assignment=assignment)
    active: list[dict[str, Any]] = []
    for candidate in problem.transformation_activations:
        if evaluate(candidate.expression, context) is not True:
            continue
        if candidate.state_predicates and not _state_predicates_hold(
            candidate.state_predicates, context, state_result
        ):
            continue
        active.append(
            {
                "name": candidate.name,
                "transformation": candidate.transformation,
                "binding": dict(candidate.binding),
            }
        )
    return tuple(sorted(active, key=lambda item: (item["transformation"], item["name"])))


def _state_predicates_hold(predicates, context, state_result: Any) -> bool:
    if state_result is None:
        return False
    for predicate in predicates:
        cycle = evaluate(predicate.cycle, context)
        expected = evaluate(predicate.expected, context)
        if not isinstance(cycle, int) or isinstance(cycle, bool):
            return False
        state = dict(state_result.initial_state)
        for step in sorted(state_result.steps, key=lambda item: item.cycle):
            if step.cycle >= cycle:
                break
            state = dict(step.after)
        actual = state.get(predicate.state, UNKNOWN)
        if actual is UNKNOWN or expected is UNKNOWN:
            return False
        comparison = {
            "eq": actual == expected,
            "ne": actual != expected,
            "lt": actual < expected,
            "le": actual <= expected,
            "gt": actual > expected,
            "ge": actual >= expected,
        }[predicate.op]
        if not comparison:
            return False
    return True


def _materialize_trace(
    problem: BoundedProblem,
    assignment: dict[str, Any],
    state_result: Any = None,
    backend: str = "finite",
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
        "backend": backend,
        "horizon": problem.spec.horizon,
        "model": problem.spec.metadata,
        "selected_slots": [
            event.id for event in events if event.id in problem.slot_ids
        ],
    }
    if state_result is not None:
        metadata["completion"]["state"] = {
            "initial": dict(state_result.initial_state),
            "final": dict(state_result.final_state),
            "steps": [step.to_dict() for step in state_result.steps],
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
