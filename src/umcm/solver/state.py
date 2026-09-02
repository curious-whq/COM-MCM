"""Concrete operational-state simulation for a fully assigned bounded trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umcm.ir.expression import Expr
from umcm.solver.evaluator import EvaluationContext, UNKNOWN, evaluate
from umcm.solver.problem import BoundedProblem


@dataclass(frozen=True, slots=True)
class StateChange:
    state: str
    before: Any
    after: Any
    origins: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "before": self.before,
            "after": self.after,
            "origins": list(self.origins),
        }


@dataclass(frozen=True, slots=True)
class StateStep:
    cycle: int
    before: dict[str, Any]
    after: dict[str, Any]
    active_requirements: tuple[str, ...] = ()
    active_updates: tuple[str, ...] = ()
    changes: tuple[StateChange, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "before": dict(self.before),
            "after": dict(self.after),
            "active_requirements": list(self.active_requirements),
            "active_updates": list(self.active_updates),
            "changes": [item.to_dict() for item in self.changes],
        }


@dataclass(slots=True)
class StateCheckResult:
    feasible: bool
    initial_state: dict[str, Any] = field(default_factory=dict)
    final_state: dict[str, Any] = field(default_factory=dict)
    steps: tuple[StateStep, ...] = ()
    reason: str = ""


def check_state_semantics(
    problem: BoundedProblem,
    assignment: dict[str, Any],
) -> StateCheckResult:
    """Simulate declared persistent state for one concrete assignment.

    Requirements at a cycle observe one shared pre-state. Updates at that cycle
    are then applied atomically. Unwritten cells retain their value. Multiple
    active writes to one cell must agree.
    """

    context = EvaluationContext(events=problem.event_map, assignment=assignment)
    state: dict[str, Any] = {}
    for variable in problem.spec.state_variables:
        value = _concrete(variable.initial, context)
        if value is UNKNOWN:
            return StateCheckResult(
                feasible=False,
                reason=f"initial state {variable.name!r} remained unresolved",
            )
        state[variable.name] = value
    initial = dict(state)

    requirements_by_cycle: dict[int, list[tuple[Any, Any]]] = {}
    updates_by_cycle: dict[int, list[tuple[Any, Any]]] = {}

    for requirement in problem.state_requirements:
        active = _concrete(requirement.activation, context)
        if active is UNKNOWN:
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"activation of {requirement.name!r} remained unresolved",
            )
        if active is not True:
            continue
        cycle = _concrete(requirement.cycle, context)
        expected = _concrete(requirement.expected, context)
        if not _valid_cycle(cycle, problem.spec.horizon):
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"state requirement {requirement.name!r} has invalid cycle {cycle!r}",
            )
        if expected is UNKNOWN:
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"state requirement {requirement.name!r} remained unresolved",
            )
        requirements_by_cycle.setdefault(cycle, []).append((requirement, expected))

    for update in problem.state_updates:
        active = _concrete(update.activation, context)
        if active is UNKNOWN:
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"activation of {update.name!r} remained unresolved",
            )
        if active is not True:
            continue
        cycle = _concrete(update.cycle, context)
        value = _concrete(update.value, context)
        if not _valid_cycle(cycle, problem.spec.horizon):
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"state update {update.name!r} has invalid cycle {cycle!r}",
            )
        if value is UNKNOWN:
            return StateCheckResult(
                feasible=False,
                initial_state=initial,
                reason=f"state update {update.name!r} remained unresolved",
            )
        updates_by_cycle.setdefault(cycle, []).append((update, value))

    steps: list[StateStep] = []
    pre_state_by_cycle: dict[int, dict[str, Any]] = {}
    active_cycles = set(requirements_by_cycle) | set(updates_by_cycle)
    for cycle in range(problem.spec.horizon + 1):
        before = dict(state)
        pre_state_by_cycle[cycle] = before
        active_requirement_names: list[str] = []
        for requirement, expected in requirements_by_cycle.get(cycle, []):
            active_requirement_names.append(requirement.name)
            actual = state[requirement.state]
            holds, relation = _compare_state(requirement.op, actual, expected)
            if not holds:
                return StateCheckResult(
                    feasible=False,
                    initial_state=initial,
                    final_state=dict(state),
                    steps=tuple(steps),
                    reason=(
                        f"cycle {cycle}: {requirement.name} requires "
                        f"{requirement.state} {relation} {expected!r}, "
                        f"but pre-state is {actual!r}"
                    ),
                )

        grouped: dict[str, list[tuple[Any, Any]]] = {}
        for update, value in updates_by_cycle.get(cycle, []):
            grouped.setdefault(update.state, []).append((update, value))

        active_update_names: list[str] = []
        changes: list[StateChange] = []
        for state_name, writes in sorted(grouped.items()):
            values = {value for _, value in writes}
            if len(values) != 1:
                rendered = ", ".join(
                    f"{update.name}={value!r}" for update, value in writes
                )
                return StateCheckResult(
                    feasible=False,
                    initial_state=initial,
                    final_state=dict(state),
                    steps=tuple(steps),
                    reason=(
                        f"cycle {cycle}: conflicting atomic writes to "
                        f"{state_name}: {rendered}"
                    ),
                )
            value = next(iter(values))
            for update, _ in writes:
                active_update_names.append(update.name)
            old = state[state_name]
            state[state_name] = value
            if old != value:
                changes.append(
                    StateChange(
                        state=state_name,
                        before=old,
                        after=value,
                        origins=tuple(update.name for update, _ in writes),
                    )
                )

        if cycle in active_cycles:
            steps.append(
                StateStep(
                    cycle=cycle,
                    before=before,
                    after=dict(state),
                    active_requirements=tuple(active_requirement_names),
                    active_updates=tuple(active_update_names),
                    changes=tuple(changes),
                )
            )

    guarded_error = _check_guarded_transitions(
        problem, context, pre_state_by_cycle
    )
    if guarded_error:
        return StateCheckResult(
            feasible=False,
            initial_state=initial,
            final_state=dict(state),
            steps=tuple(steps),
            reason=guarded_error,
        )

    return StateCheckResult(
        feasible=True,
        initial_state=initial,
        final_state=dict(state),
        steps=tuple(steps),
    )


def _compare_state(op: str, actual: Any, expected: Any) -> tuple[bool, str]:
    comparators = {
        "eq": (lambda a, b: a == b, "=="),
        "ne": (lambda a, b: a != b, "!="),
        "lt": (lambda a, b: a < b, "<"),
        "le": (lambda a, b: a <= b, "<="),
        "gt": (lambda a, b: a > b, ">"),
        "ge": (lambda a, b: a >= b, ">="),
    }
    predicate, relation = comparators[op]
    return bool(predicate(actual, expected)), relation


def _guard_predicates_hold(predicates, context, pre_state_by_cycle, horizon: int):
    for predicate in predicates:
        cycle = _concrete(predicate.cycle, context)
        expected = _concrete(predicate.expected, context)
        if not _valid_cycle(cycle, horizon) or expected is UNKNOWN:
            return None, f"guard predicate for {predicate.state} remained unresolved"
        actual = pre_state_by_cycle[cycle][predicate.state]
        holds, _ = _compare_state(predicate.op, actual, expected)
        if not holds:
            return False, ""
    return True, ""


def _check_guarded_transitions(problem, context, pre_state_by_cycle) -> str:
    for item in problem.guarded_forwards:
        antecedent = _concrete(item.antecedent, context)
        if antecedent is UNKNOWN:
            return f"state-guarded transition {item.name} antecedent remained unresolved"
        if antecedent is not True:
            continue
        guards, error = _guard_predicates_hold(
            item.predicates, context, pre_state_by_cycle, problem.spec.horizon
        )
        if error:
            return f"state-guarded transition {item.name}: {error}"
        if guards is not True:
            continue
        consequent = _concrete(item.consequent, context)
        if consequent is not True:
            return (
                f"state-guarded transition {item.name} is enabled by pre-state "
                "but no matching output event occurs"
            )

    for item in problem.guarded_supports:
        antecedent = _concrete(item.antecedent, context)
        if antecedent is UNKNOWN:
            return f"state-guarded support {item.name} antecedent remained unresolved"
        if antecedent is not True:
            continue
        supported = False
        for candidate in item.supports:
            expression = _concrete(candidate.expression, context)
            if expression is not True:
                continue
            guards, error = _guard_predicates_hold(
                candidate.predicates, context, pre_state_by_cycle, problem.spec.horizon
            )
            if error:
                return f"state-guarded support {item.name}: {error}"
            if guards is True:
                supported = True
                break
        if not supported:
            return (
                f"state-guarded support {item.name} has an occurring output "
                "without an enabled input/state witness"
            )
    return ""


def _concrete(value: Any, context: EvaluationContext) -> Any:
    return evaluate(value, context) if isinstance(value, Expr) else value


def _valid_cycle(value: Any, horizon: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= horizon
    )
