# `umcm/solver/completion.py` 源码讲解

文件职责：实现轨迹补全的公共入口和结果物化。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–18 行）

```python
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


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `CompletionStatus` 及全部字段（第 19–24 行）

```python
class CompletionStatus(str, Enum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


```

枚举补全结果为可行、不可行或未知。

- `FEASIBLE`：定义枚举成员，表示补全问题存在可行见证。
- `INFEASIBLE`：定义枚举成员，表示补全问题不存在可行见证。
- `UNKNOWN`：定义枚举成员，表示后端未能确定结果。

## 类 `CompletionResult` 及全部字段（第 25–38 行）

```python
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

```

汇总补全状态、见证轨迹、赋值和状态模拟信息。

- `status`：本次检查或求解的结果状态。
- `backend`：实际使用的求解后端名称。
- `completed_trace`：求解成功后物化出的完整轨迹。
- `assignment`：符号名到具体值的求解赋值。
- `added_event_ids`：补全过程新增且最终发生的事件 ID。
- `explored_nodes`：有限域搜索访问的节点数量。
- `reason`：失败、未知或差异结果的原因。
- `instantiated_constraint_count`：本次有界问题实例化出的约束总数。
- `initial_state`：状态模拟开始时的完整状态。
- `final_state`：状态模拟结束时的完整状态。
- `state_steps`：逐周期状态变化见证。

## 方法 `CompletionResult.feasible`（第 39–43 行）

```python
    @property
    def feasible(self) -> bool:
        return self.status is CompletionStatus.FEASIBLE


```

判断公共补全结果是否为 `FEASIBLE`。

## 函数 `complete_trace`（第 44–122 行）

```python
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

    completed = _materialize_trace(
        problem,
        solved.assignment,
        state_result=solved.state_result,
    )
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
    )


```

校验输入、实例化有界问题并调用有限域后端；成功后物化完整轨迹和状态见证。

## 函数 `_materialize_trace`（第 123–187 行）

```python
def _materialize_trace(
    problem: BoundedProblem,
    assignment: dict[str, Any],
    state_result: Any = None,
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


```

用求解赋值替换事件中的符号值，筛掉未发生事件，并附加补全元数据与状态见证。

## 函数 `_concrete`（第 188–192 行）

```python
def _concrete(value: Any, context: EvaluationContext, path: str) -> Any:
    result = evaluate(value, context) if isinstance(value, Expr) else value
    if result is UNKNOWN:
        raise CompletionError(f"completion left {path} unresolved")
    return result
```

在值已经具体化时返回其 Python 值；仍是符号时拒绝或返回缺省结果。

