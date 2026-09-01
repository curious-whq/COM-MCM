"""Deterministic bounded-domain feasibility backend.

This backend is intentionally small and dependency-free.  It is not a general
SMT solver: integer and bit-vector symbols are searched within the completion
horizon, while domain sorts are restricted to concrete values already present
in the bounded problem.  The same problem IR is designed to admit a Z3 backend
later without changing models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from umcm.errors import SolverError
from umcm.ir.expression import Expr, Symbol, iter_literals, iter_symbols
from umcm.ir.sort import BOOL, INT, Sort
from umcm.solver.evaluator import EvaluationContext, UNKNOWN, evaluate
from umcm.solver.problem import BoundedProblem


class FiniteStatus(str, Enum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FiniteVariable:
    name: str
    sort: Sort
    domain: tuple[Any, ...]


@dataclass(slots=True)
class FiniteSolveResult:
    status: FiniteStatus
    assignment: dict[str, Any]
    explored_nodes: int
    reason: str = ""


def solve_finite(
    problem: BoundedProblem,
    *,
    node_limit: int = 500_000,
) -> FiniteSolveResult:
    variables = _build_variables(problem)
    events = problem.event_map
    constraints = [item.expression for item in problem.constraints]
    assignment: dict[str, Any] = {}
    explored = 0
    hit_unknown_leaf = False

    def constraints_consistent() -> bool:
        context = EvaluationContext(events=events, assignment=assignment)
        for expression in constraints:
            value = evaluate(expression, context)
            if value is False:
                return False
        return True

    def search(index: int) -> dict[str, Any] | None:
        nonlocal explored, hit_unknown_leaf
        explored += 1
        if explored > node_limit:
            return None
        if not constraints_consistent():
            return None
        if index == len(variables):
            context = EvaluationContext(events=events, assignment=assignment)
            values = [evaluate(expression, context) for expression in constraints]
            if all(value is True for value in values):
                return dict(assignment)
            if any(value is UNKNOWN for value in values):
                hit_unknown_leaf = True
            return None

        variable = variables[index]
        for value in variable.domain:
            assignment[variable.name] = value
            witness = search(index + 1)
            if witness is not None:
                return witness
            if explored > node_limit:
                break
        assignment.pop(variable.name, None)
        return None

    witness = search(0)
    if witness is not None:
        return FiniteSolveResult(
            status=FiniteStatus.SAT,
            assignment=witness,
            explored_nodes=explored,
        )
    if explored > node_limit:
        return FiniteSolveResult(
            status=FiniteStatus.UNKNOWN,
            assignment={},
            explored_nodes=explored,
            reason=f"finite search exceeded node limit {node_limit}",
        )
    if hit_unknown_leaf:
        return FiniteSolveResult(
            status=FiniteStatus.UNKNOWN,
            assignment={},
            explored_nodes=explored,
            reason="some fully assigned constraints still contained unknown values",
        )
    return FiniteSolveResult(
        status=FiniteStatus.UNSAT,
        assignment={},
        explored_nodes=explored,
        reason=(
            f"no assignment within cycle horizon 0..{problem.spec.horizon} "
            "and observed finite domains"
        ),
    )


def _build_variables(problem: BoundedProblem) -> list[FiniteVariable]:
    symbols: dict[str, Sort] = {}
    concrete: dict[Sort, set[Any]] = {}

    def record_symbol(symbol: Symbol) -> None:
        previous = symbols.get(symbol.name)
        if previous is not None and previous != symbol.sort:
            raise SolverError(
                f"symbol {symbol.name!r} is used with incompatible sorts "
                f"{previous} and {symbol.sort}"
            )
        symbols[symbol.name] = symbol.sort

    def record_expression(expression: Expr) -> None:
        for symbol in iter_symbols(expression):
            record_symbol(symbol)
        for literal in iter_literals(expression):
            concrete.setdefault(literal.sort, set()).add(literal.value)

    for event in problem.events:
        event_type = problem.catalog.resolve(event.event_type)
        if isinstance(event.occurs, Expr):
            record_expression(event.occurs)
        else:
            concrete.setdefault(BOOL, set()).add(event.occurs)
        if isinstance(event.cycle, Expr):
            record_expression(event.cycle)
        elif event.cycle is not None:
            concrete.setdefault(INT, set()).add(event.cycle)
        for name, value in event.fields.items():
            field_sort = event_type.field_map[name].sort
            if isinstance(value, Expr):
                record_expression(value)
            else:
                concrete.setdefault(field_sort, set()).add(value)

    for constraint in problem.constraints:
        record_expression(constraint.expression)

    variables: list[FiniteVariable] = []
    for name, sort in symbols.items():
        domain = _domain_for(sort, concrete.get(sort, set()), problem.spec.horizon)
        variables.append(FiniteVariable(name=name, sort=sort, domain=domain))

    # Occurrence and identity decisions usually prune much earlier than cycle
    # choices, so keep bounded integers last.  The remaining ordering is stable.
    def priority(variable: FiniteVariable) -> tuple[int, int, str]:
        if variable.sort.is_bool:
            rank = 0
        elif not (
            variable.sort.is_int
            or variable.sort.is_bitvector
            or variable.sort.is_string
        ):
            rank = 1
        elif variable.sort.is_string:
            rank = 1
        elif variable.sort.is_bitvector:
            rank = 2
        else:
            rank = 3
        return (rank, len(variable.domain), variable.name)

    variables.sort(key=priority)
    return variables


def _domain_for(sort: Sort, observed: set[Any], horizon: int) -> tuple[Any, ...]:
    if sort.is_bool:
        return (False, True)
    if sort.is_int:
        values = set(range(horizon + 1)) | {
            value
            for value in observed
            if isinstance(value, int) and not isinstance(value, bool)
        }
        return tuple(sorted(values))
    if sort.is_bitvector:
        assert sort.width is not None
        maximum = (1 << sort.width) - 1
        values = {
            value
            for value in observed
            if isinstance(value, int) and not isinstance(value, bool)
        }
        values |= set(range(min(maximum, horizon) + 1))
        return tuple(sorted(values))
    if sort.is_string or sort.name not in {"bool", "int", "bv"}:
        if not observed:
            raise SolverError(
                f"finite backend has no concrete domain values for sort {sort}"
            )
        return tuple(sorted(observed, key=lambda value: (type(value).__name__, repr(value))))
    raise SolverError(f"finite backend does not support sort {sort}")
