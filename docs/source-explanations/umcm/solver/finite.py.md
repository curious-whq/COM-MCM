# `umcm/solver/finite.py` 源码讲解

文件职责：实现确定性的有限域可满足性搜索。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–23 行）

```python
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
from umcm.solver.state import StateCheckResult, check_state_semantics


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `FiniteStatus` 及全部字段（第 24–29 行）

```python
class FiniteStatus(str, Enum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


```

枚举有限域搜索结果为 SAT、UNSAT 或 UNKNOWN。

- `SAT`：定义枚举成员，表示有限问题可满足。
- `UNSAT`：定义枚举成员，表示有限问题不可满足。
- `UNKNOWN`：定义枚举成员，表示后端未能确定结果。

## 类 `FiniteVariable` 及全部字段（第 30–36 行）

```python
@dataclass(frozen=True, slots=True)
class FiniteVariable:
    name: str
    sort: Sort
    domain: tuple[Any, ...]


```

描述有限域搜索变量的名称、类型和值域。

- `name`：对象或规则的稳定名称。
- `sort`：值或表达式的静态类型。
- `domain`：有限变量可枚举的具体值域。

## 类 `FiniteSolveResult` 及全部字段（第 37–45 行）

```python
@dataclass(slots=True)
class FiniteSolveResult:
    status: FiniteStatus
    assignment: dict[str, Any]
    explored_nodes: int
    reason: str = ""
    state_result: StateCheckResult | None = None


```

保存有限域搜索结果、赋值、节点数和状态检查结果。

- `status`：本次检查或求解的结果状态。
- `assignment`：符号名到具体值的求解赋值。
- `explored_nodes`：有限域搜索访问的节点数量。
- `reason`：失败、未知或差异结果的原因。
- `state_result`：完整赋值对应的状态语义检查结果。

## 函数 `solve_finite`（第 46–135 行）

```python
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
    last_state_failure = ""
    winning_state_result: StateCheckResult | None = None

    def constraints_consistent() -> bool:
        context = EvaluationContext(events=events, assignment=assignment)
        for expression in constraints:
            value = evaluate(expression, context)
            if value is False:
                return False
        return True

    def search(index: int) -> dict[str, Any] | None:
        nonlocal explored, hit_unknown_leaf, last_state_failure, winning_state_result
        explored += 1
        if explored > node_limit:
            return None
        if not constraints_consistent():
            return None
        if index == len(variables):
            context = EvaluationContext(events=events, assignment=assignment)
            values = [evaluate(expression, context) for expression in constraints]
            if all(value is True for value in values):
                state_result = check_state_semantics(problem, assignment)
                if state_result.feasible:
                    winning_state_result = state_result
                    return dict(assignment)
                last_state_failure = state_result.reason
                return None
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
            state_result=winning_state_result,
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
    reason = (
        f"no assignment within cycle horizon 0..{problem.spec.horizon} "
        "and observed finite domains"
    )
    if last_state_failure:
        reason += f"; last state rejection: {last_state_failure}"
    return FiniteSolveResult(
        status=FiniteStatus.UNSAT,
        assignment={},
        explored_nodes=explored,
        reason=reason,
    )


```

建立有限变量并按确定顺序深度优先搜索，利用部分求值剪枝，完整赋值时再检查状态语义。

## 函数 `_build_variables`（第 136–215 行）

```python
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
    for variable in problem.spec.state_variables:
        if isinstance(variable.initial, Expr):
            record_expression(variable.initial)
        else:
            concrete.setdefault(variable.sort, set()).add(variable.initial)
    for requirement in problem.state_requirements:
        record_expression(requirement.activation)
        record_expression(requirement.cycle)
        record_expression(requirement.expected)
    for update in problem.state_updates:
        record_expression(update.activation)
        record_expression(update.cycle)
        record_expression(update.value)

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


```

收集事件和约束中的符号，合并类型要求并为每个符号构造有限候选域。

## 函数 `_domain_for`（第 216–242 行）

```python
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
```

按符号类型和问题中出现的字面量生成确定、有限且包含必要值的搜索域。

