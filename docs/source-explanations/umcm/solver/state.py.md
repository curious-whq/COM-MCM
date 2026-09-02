# `umcm/solver/state.py` 源码讲解

文件职责：在完整赋值上模拟并检查持久状态语义。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–12 行）

```python
"""Concrete operational-state simulation for a fully assigned bounded trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umcm.ir.expression import Expr
from umcm.solver.evaluator import EvaluationContext, UNKNOWN, evaluate
from umcm.solver.problem import BoundedProblem


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `StateChange` 及全部字段（第 13–19 行）

```python
@dataclass(frozen=True, slots=True)
class StateChange:
    state: str
    before: Any
    after: Any
    origins: tuple[str, ...] = ()

```

记录一个状态单元在单步中的前值、后值和更新来源。

- `state`：被条件或更新访问的状态变量名。
- `before`：本周期更新执行前的完整状态。
- `after`：本周期原子更新后的完整状态。
- `origins`：共同造成状态变化的更新来源集合。

## 方法 `StateChange.to_dict`（第 20–28 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "before": self.before,
            "after": self.after,
            "origins": list(self.origins),
        }


```

把 `StateChange` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `StateStep` 及全部字段（第 29–37 行）

```python
@dataclass(frozen=True, slots=True)
class StateStep:
    cycle: int
    before: dict[str, Any]
    after: dict[str, Any]
    active_requirements: tuple[str, ...] = ()
    active_updates: tuple[str, ...] = ()
    changes: tuple[StateChange, ...] = ()

```

记录一个周期的共享前状态、原子更新和变化。

- `cycle`：事件发生周期或诊断环。
- `before`：本周期更新执行前的完整状态。
- `after`：本周期原子更新后的完整状态。
- `active_requirements`：本周期实际生效的状态前置条件名称。
- `active_updates`：本周期实际生效的状态更新名称。
- `changes`：本周期真正发生值变化的状态单元记录。

## 方法 `StateStep.to_dict`（第 38–48 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "before": dict(self.before),
            "after": dict(self.after),
            "active_requirements": list(self.active_requirements),
            "active_updates": list(self.active_updates),
            "changes": [item.to_dict() for item in self.changes],
        }


```

把 `StateStep` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `StateCheckResult` 及全部字段（第 49–57 行）

```python
@dataclass(slots=True)
class StateCheckResult:
    feasible: bool
    initial_state: dict[str, Any] = field(default_factory=dict)
    final_state: dict[str, Any] = field(default_factory=dict)
    steps: tuple[StateStep, ...] = ()
    reason: str = ""


```

汇总状态模拟是否可行以及首尾状态和逐步轨迹。

- `feasible`：控制或记录“可行性结果”语义的布尔标志。
- `initial_state`：状态模拟开始时的完整状态。
- `final_state`：状态模拟结束时的完整状态。
- `steps`：按周期排列的状态模拟步骤。
- `reason`：失败、未知或差异结果的原因。

## 函数 `check_state_semantics`（第 58–214 行）

```python
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
    active_cycles = sorted(set(requirements_by_cycle) | set(updates_by_cycle))
    for cycle in active_cycles:
        before = dict(state)
        active_requirement_names: list[str] = []
        for requirement, expected in requirements_by_cycle.get(cycle, []):
            active_requirement_names.append(requirement.name)
            actual = state[requirement.state]
            holds = actual == expected if requirement.op == "eq" else actual != expected
            if not holds:
                relation = "==" if requirement.op == "eq" else "!="
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

    return StateCheckResult(
        feasible=True,
        initial_state=initial,
        final_state=dict(state),
        steps=tuple(steps),
    )


```

按周期模拟共享前状态和原子更新，检查前置条件、写冲突和值类型并记录逐步变化。

## 函数 `_concrete`（第 215–218 行）

```python
def _concrete(value: Any, context: EvaluationContext) -> Any:
    return evaluate(value, context) if isinstance(value, Expr) else value


```

在值已经具体化时返回其 Python 值；仍是符号时拒绝或返回缺省结果。

## 函数 `_valid_cycle`（第 219–224 行）

```python
def _valid_cycle(value: Any, horizon: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= horizon
    )
```

把具体非负整数规范化为周期；其他值返回空结果。

