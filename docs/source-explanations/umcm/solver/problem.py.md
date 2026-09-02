# `umcm/solver/problem.py` 源码讲解

文件职责：把角色转换规则实例化为有界求解问题。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–26 行）

```python
"""Instantiation of role-based transformations over a bounded event universe."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Iterator, Mapping

from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import (
    Binary,
    Symbol,
    EventField,
    Expr,
    Literal,
    conjunction,
    disjunction,
    substitute_event_ids,
)
from umcm.ir.sort import BOOL, INT
from umcm.ir.trace import Trace
from umcm.ir.transformation import EventRole, Transformation


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `NamedConstraint` 及全部字段（第 27–33 行）

```python
@dataclass(frozen=True, slots=True)
class NamedConstraint:
    name: str
    expression: Expr
    origin: str


```

给表达式约束附加稳定名称和来源。

- `name`：对象或规则的稳定名称。
- `expression`：命名约束实际检查的表达式。
- `origin`：约束或状态效果的来源说明。

## 类 `StateRequirementInstance` 及全部字段（第 34–44 行）

```python
@dataclass(frozen=True, slots=True)
class StateRequirementInstance:
    name: str
    state: str
    cycle: Expr
    activation: Expr
    op: str
    expected: Expr
    origin: str


```

表示转换绑定后的一条具体状态前置条件。

- `name`：对象或规则的稳定名称。
- `state`：被条件或更新访问的状态变量名。
- `cycle`：事件发生周期或诊断环。
- `activation`：决定该状态效果是否生效的布尔表达式。
- `op`：表达式、关系或状态比较使用的运算符。
- `expected`：状态比较条件右侧的期望表达式。
- `origin`：约束或状态效果的来源说明。

## 类 `StateUpdateInstance` 及全部字段（第 45–54 行）

```python
@dataclass(frozen=True, slots=True)
class StateUpdateInstance:
    name: str
    state: str
    cycle: Expr
    activation: Expr
    value: Expr
    origin: str


```

表示转换绑定后的一条具体状态更新。

- `name`：对象或规则的稳定名称。
- `state`：被条件或更新访问的状态变量名。
- `cycle`：事件发生周期或诊断环。
- `activation`：决定该状态效果是否生效的布尔表达式。
- `value`：该节点、字段或状态写入承载的值。
- `origin`：约束或状态效果的来源说明。

## 类 `BoundedProblem` 及全部字段（第 55–65 行）

```python
@dataclass(slots=True)
class BoundedProblem:
    catalog: EventCatalog
    source_trace: Trace
    spec: CompletionSpec
    events: list[EventInstance]
    constraints: list[NamedConstraint]
    state_requirements: list[StateRequirementInstance]
    state_updates: list[StateUpdateInstance]
    slot_ids: tuple[str, ...]

```

汇总补全求解所需的事件、约束和状态实例。

- `catalog`：事件类型目录。
- `source_trace`：用于构造问题的原始部分轨迹。
- `spec`：本次操作采用的模型配置。
- `events`：本对象管理的事件集合。
- `constraints`：必须同时成立的表达式约束。
- `state_requirements`：转换声明的状态前置条件。
- `state_updates`：转换声明的原子状态更新。
- `slot_ids`：由补全事件槽引入的问题事件 ID。

## 方法 `BoundedProblem.event_map`（第 66–70 行）

```python
    @property
    def event_map(self) -> dict[str, EventInstance]:
        return {event.id: event for event in self.events}


```

构造问题内事件 ID 到事件实例的映射。

## 类 `_TransformationInstantiation` 及全部字段（第 71–77 行）

```python
@dataclass(frozen=True, slots=True)
class _TransformationInstantiation:
    constraints: tuple[NamedConstraint, ...]
    requirements: tuple[StateRequirementInstance, ...]
    updates: tuple[StateUpdateInstance, ...]


```

暂存一次转换实例化产生的普通约束和状态效果。

- `constraints`：必须同时成立的表达式约束。
- `requirements`：一次转换实例化产生的状态前置条件。
- `updates`：一次转换实例化产生的状态更新。

## 函数 `build_problem`（第 78–147 行）

```python
def build_problem(
    catalog: EventCatalog,
    trace: Trace,
    spec: CompletionSpec,
) -> BoundedProblem:
    trace.validate(catalog)
    spec.validate(catalog, trace)

    observed_events = [
        _materialize_partial_event(catalog, event) for event in trace.events
    ]
    slot_events = [slot.materialize(catalog) for slot in spec.slots]
    events = [*observed_events, *slot_events]
    constraints: list[NamedConstraint] = []
    state_requirements: list[StateRequirementInstance] = []
    state_updates: list[StateUpdateInstance] = []
    constraints.extend(
        NamedConstraint(
            name=f"trace.constraint.{index}",
            expression=expression,
            origin="trace",
        )
        for index, expression in enumerate(trace.constraints)
    )
    constraints.extend(
        NamedConstraint(
            name=f"completion.constraint.{index}",
            expression=expression,
            origin="completion",
        )
        for index, expression in enumerate(spec.constraints)
    )

    for event in events:
        if event.cycle is None:
            continue
        occurs = EventField(event.id, "occurs", BOOL)
        cycle = EventField(event.id, "cycle", INT)
        in_range = conjunction(
            (
                Binary("le", Literal(0, INT), cycle),
                Binary("le", cycle, Literal(spec.horizon, INT)),
            )
        )
        constraints.append(
            NamedConstraint(
                name=f"cycle.bound.{event.id}",
                expression=Binary("implies", occurs, in_range),
                origin="completion",
            )
        )

    for transformation in spec.transformations:
        instantiated = _instantiate_transformation(transformation, events)
        constraints.extend(instantiated.constraints)
        state_requirements.extend(instantiated.requirements)
        state_updates.extend(instantiated.updates)

    return BoundedProblem(
        catalog=catalog,
        source_trace=trace,
        spec=spec,
        events=events,
        constraints=constraints,
        state_requirements=state_requirements,
        state_updates=state_updates,
        slot_ids=tuple(slot.id for slot in spec.slots),
    )


```

合并源轨迹与事件槽，物化部分事件，实例化全局约束和各转换绑定，形成统一有界问题。

## 函数 `_instantiate_transformation`（第 148–330 行）

```python
def _instantiate_transformation(
    transformation: Transformation,
    events: list[EventInstance],
) -> _TransformationInstantiation:
    """Instantiate one operational transition over the bounded event universe.

    Normal transformations add the forward rule ``inputs && guard -> outputs``.
    An ``exact`` transformation additionally requires every occurring output to
    be justified by some matching input binding.  This is a general derived-
    event facility; ready/valid/fire does not have a separate semantics layer.

    State effects are attached to complete transition instances.  Therefore a
    rule may read pre-state, emit output events, and update post-state as one
    operational transition.
    """

    by_type: dict[str, list[EventInstance]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

    input_bindings = list(_role_bindings(transformation.inputs, by_type))
    output_bindings = list(_role_bindings(transformation.outputs, by_type))
    constraints: list[NamedConstraint] = []
    requirements: list[StateRequirementInstance] = []
    updates: list[StateUpdateInstance] = []

    for input_index, input_binding in enumerate(input_bindings):
        input_ids = tuple(input_binding.values())
        if len(input_ids) != len(set(input_ids)):
            continue

        input_mapping = dict(input_binding)
        input_occurs = tuple(
            EventField(event_id, "occurs", BOOL)
            for event_id in input_binding.values()
        )
        guard = substitute_event_ids(transformation.when, input_mapping)
        antecedent = conjunction((*input_occurs, guard))

        alternatives: list[Expr] = []
        complete_instances: list[tuple[dict[str, str], Expr, str]] = []
        for output_index, output_binding in enumerate(output_bindings):
            all_ids = (*input_binding.values(), *output_binding.values())
            if len(all_ids) != len(set(all_ids)):
                continue
            complete_mapping = {**input_binding, **output_binding}
            output_occurs = tuple(
                EventField(event_id, "occurs", BOOL)
                for event_id in output_binding.values()
            )
            output_guard = substitute_event_ids(
                transformation.output_when, complete_mapping
            )
            ensured = tuple(
                substitute_event_ids(expression, complete_mapping)
                for expression in transformation.ensure
            )
            output_alternative = conjunction(
                (*output_occurs, output_guard, *ensured)
            )
            alternatives.append(output_alternative)
            activation = conjunction(
                (*input_occurs, guard, *output_occurs, output_guard, *ensured)
            )
            bound_outputs = (
                ",".join(output_binding.values())
                if output_binding
                else "no-output"
            )
            complete_instances.append(
                (complete_mapping, activation, f"{output_index}.{bound_outputs}")
            )

        bound_inputs = ",".join(input_ids) if input_ids else "global"
        forward_name = (
            f"transformation.{transformation.name}.forward."
            f"{input_index}.{bound_inputs}"
        )
        constraints.append(
            NamedConstraint(
                name=forward_name,
                expression=Binary(
                    "implies", antecedent, disjunction(alternatives)
                ),
                origin=f"transformation:{transformation.name}",
            )
        )

        if transformation.is_stateful:
            for complete_mapping, activation, instance_suffix in complete_instances:
                effect_prefix = f"{forward_name}.instance.{instance_suffix}"
                for effect_index, requirement in enumerate(
                    transformation.state_requirements
                ):
                    anchor_id = complete_mapping[requirement.at]
                    requirements.append(
                        StateRequirementInstance(
                            name=(
                                f"{effect_prefix}.requirement.{effect_index}"
                            ),
                            state=requirement.state,
                            cycle=EventField(anchor_id, "cycle", INT),
                            activation=activation,
                            op=requirement.op,
                            expected=substitute_event_ids(
                                requirement.value, complete_mapping
                            ),
                            origin=f"transformation:{transformation.name}",
                        )
                    )
                for effect_index, update in enumerate(
                    transformation.state_updates
                ):
                    anchor_id = complete_mapping[update.at]
                    updates.append(
                        StateUpdateInstance(
                            name=f"{effect_prefix}.update.{effect_index}",
                            state=update.state,
                            cycle=EventField(anchor_id, "cycle", INT),
                            activation=activation,
                            value=substitute_event_ids(
                                update.value, complete_mapping
                            ),
                            origin=f"transformation:{transformation.name}",
                        )
                    )

    if transformation.exact:
        for output_index, output_binding in enumerate(output_bindings):
            output_ids = tuple(output_binding.values())
            if len(output_ids) != len(set(output_ids)):
                continue
            output_occurs = conjunction(
                EventField(event_id, "occurs", BOOL)
                for event_id in output_binding.values()
            )
            output_scope = substitute_event_ids(
                transformation.output_when, output_binding
            )
            supports: list[Expr] = []
            for input_binding in input_bindings:
                all_ids = (*input_binding.values(), *output_binding.values())
                if len(all_ids) != len(set(all_ids)):
                    continue
                complete_mapping = {**input_binding, **output_binding}
                input_occurs = tuple(
                    EventField(event_id, "occurs", BOOL)
                    for event_id in input_binding.values()
                )
                guarded = substitute_event_ids(
                    transformation.when, complete_mapping
                )
                ensured = tuple(
                    substitute_event_ids(expression, complete_mapping)
                    for expression in transformation.ensure
                )
                supports.append(
                    conjunction((*input_occurs, guarded, *ensured))
                )

            bound_outputs = ",".join(output_ids) if output_ids else "global"
            constraints.append(
                NamedConstraint(
                    name=(
                        f"transformation.{transformation.name}.support."
                        f"{output_index}.{bound_outputs}"
                    ),
                    expression=Binary(
                        "implies",
                        conjunction((output_occurs, output_scope)),
                        disjunction(supports),
                    ),
                    origin=f"transformation:{transformation.name}",
                )
            )

    return _TransformationInstantiation(
        constraints=tuple(constraints),
        requirements=tuple(requirements),
        updates=tuple(updates),
    )


```

枚举输入输出角色绑定并替换表达式；生成前向蕴含、exact 反向证明及状态条件和更新。

## 函数 `_role_bindings`（第 331–344 行）

```python
def _role_bindings(
    roles: tuple[EventRole, ...],
    by_type: Mapping[str, list[EventInstance]],
) -> Iterator[dict[str, str]]:
    if not roles:
        yield {}
        return
    candidate_lists = [by_type.get(role.event_type, []) for role in roles]
    if any(not candidates for candidates in candidate_lists):
        return
    for chosen in product(*candidate_lists):
        yield {role.name: event.id for role, event in zip(roles, chosen, strict=True)}


```

对每个角色筛选类型兼容事件，再计算无重复事件的笛卡尔绑定。

## 函数 `_materialize_partial_event`（第 345–366 行）

```python
def _materialize_partial_event(
    catalog: EventCatalog,
    event: EventInstance,
) -> EventInstance:
    """Fill missing required fields of an observed partial event with symbols."""

    event_type = catalog.resolve(event.event_type)
    fields = deepcopy(event.fields)
    for field_spec in event_type.fields:
        if field_spec.required and field_spec.name not in fields:
            fields[field_spec.name] = Symbol(
                f"trace::{event.id}::field::{field_spec.name}",
                field_spec.sort,
            )
    return EventInstance(
        id=event.id,
        event_type=event.event_type,
        fields=fields,
        cycle=deepcopy(event.cycle),
        occurs=deepcopy(event.occurs),
        annotations=deepcopy(event.annotations),
    )
```

保留已观测字段，并为缺失的必填字段创建稳定命名、类型正确的符号。

