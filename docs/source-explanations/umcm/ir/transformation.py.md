# `umcm/ir/transformation.py` 源码讲解

文件职责：定义基于事件角色的有界操作转换规则。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–31 行）

```python
"""Bounded operational transformations over event roles.

A transformation is operational rather than architectural-axiomatic. For every
occurring tuple of input events satisfying ``when``, it requires some occurring
tuple of output events satisfying ``ensure``. Outputs are existential support
events; they are not inherently later than inputs. Timing direction is stated
explicitly in ``ensure``.

Iteration 3 additionally permits input-only transformations to carry structured
state requirements and atomic state updates. Requirements observe the pre-state
at an anchor event. Updates become visible after that event's cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError
from umcm.ir.event import EventCatalog
from umcm.ir.expression import (
    Expr,
    Literal,
    expr_from_dict,
    expr_to_dict,
    iter_event_fields,
)
from umcm.ir.sort import BOOL, INT
from umcm.ir.state import StateRequirement, StateUpdate, StateVariable


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `EventRole` 及全部字段（第 32–38 行）

```python
@dataclass(frozen=True, slots=True)
class EventRole:
    """A named event variable used inside one transformation."""

    name: str
    event_type: str

```

表示一条转换内部使用的命名事件变量。

- `name`：对象或规则的稳定名称。
- `event_type`：关联的事件类型名称。

## 方法 `EventRole.__post_init__`（第 39–44 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("event role name must be non-empty")
        if not self.event_type:
            raise SchemaError("event role type must be non-empty")

```

在 `EventRole` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventRole.to_dict`（第 45–47 行）

```python
    def to_dict(self) -> dict[str, str]:
        return {"role": self.name, "type": self.event_type}

```

把 `EventRole` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `EventRole.from_dict`（第 48–59 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRole":
        if not isinstance(data, Mapping):
            raise SerializationError("event role must be a mapping")
        try:
            return cls(name=str(data["role"]), event_type=str(data["type"]))
        except KeyError as exc:
            raise SerializationError(
                f"event role is missing {exc.args[0]!r}"
            ) from exc


```

校验输入字典的键和值，并递归构造 `EventRole` 实例。

## 类 `Transformation` 及全部字段（第 60–92 行）

```python
@dataclass(frozen=True, slots=True)
class Transformation:
    """A finite, role-based operational rule.

    Semantics for one concrete input binding ``i`` are::

        occurs(i...) and when(i...)
          -> exists output binding o.
               occurs(o...) and ensure(i..., o...)

    When ``exact`` is true, the single output is a derived event: every
    occurring output satisfying ``output_when`` must also be supported by a
    matching enabled input binding.  The output-side guard scopes exactness
    when several transformations produce the same event type (for example,
    hit and MSHR paths both producing load-success events).

    State requirements and updates may be anchored to either input or output
    roles.  When outputs are present, state effects activate only for a complete
    input/output binding satisfying the guard and ``ensure`` relation.
    """

    name: str
    inputs: tuple[EventRole, ...]
    outputs: tuple[EventRole, ...] = ()
    when: Expr = field(default_factory=lambda: Literal(True, BOOL))
    output_when: Expr = field(default_factory=lambda: Literal(True, BOOL))
    ensure: tuple[Expr, ...] = ()
    state_requirements: tuple[StateRequirement, ...] = ()
    state_updates: tuple[StateUpdate, ...] = ()
    exact: bool = False
    description: str = ""
    tags: tuple[str, ...] = ()

```

表示输入、输出、守卫、约束和状态效果组成的有限转换。

- `name`：对象或规则的稳定名称。
- `inputs`：转换的输入事件角色。
- `outputs`：转换的输出事件角色。
- `when`：转换输入发生后需要满足的守卫表达式。
- `output_when`：控制各输出角色发生性的表达式映射。
- `ensure`：输入输出发生时必须满足的转换后置约束。
- `state_requirements`：转换声明的状态前置条件。
- `state_updates`：转换声明的原子状态更新。
- `exact`：控制或记录“精确规则”语义的布尔标志。
- `description`：供人阅读的说明文本。
- `tags`：用于分类和筛选的标签集合。

## 方法 `Transformation.__post_init__`（第 93–118 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("transformation name must be non-empty")
        role_names = [role.name for role in (*self.inputs, *self.outputs)]
        if len(role_names) != len(set(role_names)):
            raise SchemaError(
                f"transformation {self.name!r} has duplicate role names"
            )
        if not self.when.sort.is_bool:
            raise SchemaError(
                f"transformation {self.name!r} guard must be bool"
            )
        if not self.output_when.sort.is_bool:
            raise SchemaError(
                f"transformation {self.name!r} output guard must be bool"
            )
        for expression in self.ensure:
            if not expression.sort.is_bool:
                raise SchemaError(
                    f"transformation {self.name!r} ensure expressions must be bool"
                )
        if self.exact and len(self.outputs) != 1:
            raise SchemaError(
                f"exact transformation {self.name!r} must have exactly one output role"
            )

```

在 `Transformation` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Transformation.role_map`（第 119–122 行）

```python
    @property
    def role_map(self) -> dict[str, EventRole]:
        return {role.name: role for role in (*self.inputs, *self.outputs)}

```

构造输入输出角色名到角色声明的映射。

## 方法 `Transformation.is_stateful`（第 123–126 行）

```python
    @property
    def is_stateful(self) -> bool:
        return bool(self.state_requirements or self.state_updates)

```

判断转换是否声明了任何状态前置条件或状态更新。

## 方法 `Transformation.validate`（第 127–193 行）

```python
    def validate(
        self,
        catalog: EventCatalog,
        state_variables: Mapping[str, StateVariable] | None = None,
    ) -> None:
        roles = self.role_map
        input_names = {role.name for role in self.inputs}
        output_names = {role.name for role in self.outputs}
        all_role_names = set(roles)
        for role in roles.values():
            catalog.resolve(role.event_type)

        guard_refs = {field.event_id for field in iter_event_fields(self.when)}
        illegal_guard_refs = guard_refs - input_names
        if illegal_guard_refs:
            raise SchemaError(
                f"transformation {self.name!r} guard references non-input role(s): "
                f"{', '.join(sorted(illegal_guard_refs))}"
            )

        output_guard_refs = {
            field.event_id for field in iter_event_fields(self.output_when)
        }
        illegal_output_guard_refs = output_guard_refs - output_names
        if illegal_output_guard_refs:
            raise SchemaError(
                f"transformation {self.name!r} output guard references "
                f"non-output role(s): "
                f"{', '.join(sorted(illegal_output_guard_refs))}"
            )

        for expression in (self.when, self.output_when, *self.ensure):
            self._validate_role_expression(expression, roles, catalog)

        state_map = dict(state_variables or {})
        if self.is_stateful and not state_map:
            raise SchemaError(
                f"stateful transformation {self.name!r} requires declared state variables"
            )
        for requirement in self.state_requirements:
            if requirement.at not in all_role_names:
                raise SchemaError(
                    f"state requirement in {self.name!r} anchors to unknown role "
                    f"{requirement.at!r}"
                )
            variable = self._resolve_state(requirement.state, state_map)
            if not requirement.value.sort.compatible_with(variable.sort):
                raise SchemaError(
                    f"state requirement {requirement.state!r} in {self.name!r} "
                    f"expects {variable.sort}, got {requirement.value.sort}"
                )
            self._validate_role_expression(requirement.value, roles, catalog)

        for update in self.state_updates:
            if update.at not in all_role_names:
                raise SchemaError(
                    f"state update in {self.name!r} anchors to unknown role "
                    f"{update.at!r}"
                )
            variable = self._resolve_state(update.state, state_map)
            if not update.value.sort.compatible_with(variable.sort):
                raise SchemaError(
                    f"state update {update.state!r} in {self.name!r} expects "
                    f"{variable.sort}, got {update.value.sort}"
                )
            self._validate_role_expression(update.value, roles, catalog)

```

检查 `Transformation` 实例 的结构、引用与类型约束；发现不一致时抛出项目专用异常。

## 方法 `Transformation._validate_role_expression`（第 194–227 行）

```python
    def _validate_role_expression(
        self,
        expression: Expr,
        roles: Mapping[str, EventRole],
        catalog: EventCatalog,
    ) -> None:
        for reference in iter_event_fields(expression):
            try:
                role = roles[reference.event_id]
            except KeyError as exc:
                raise SchemaError(
                    f"transformation {self.name!r} references unknown role "
                    f"{reference.event_id!r}"
                ) from exc
            event_type = catalog.resolve(role.event_type)
            if reference.field == "occurs":
                expected = BOOL
            elif reference.field == "cycle":
                expected = INT
            else:
                try:
                    expected = event_type.field_map[reference.field].sort
                except KeyError as exc:
                    raise SchemaError(
                        f"transformation {self.name!r} references unknown field "
                        f"{role.name}.{reference.field}"
                    ) from exc
            if not reference.sort.compatible_with(expected):
                raise SchemaError(
                    f"transformation {self.name!r} reference "
                    f"{role.name}.{reference.field} has sort {reference.sort}, "
                    f"expected {expected}"
                )

```

检查表达式中的事件引用只使用已声明角色，并核对字段存在且类型一致。

## 方法 `Transformation._resolve_state`（第 228–237 行）

```python
    @staticmethod
    def _resolve_state(
        name: str,
        state_variables: Mapping[str, StateVariable],
    ) -> StateVariable:
        try:
            return state_variables[name]
        except KeyError as exc:
            raise SchemaError(f"unknown state variable: {name}") from exc

```

按名称解析状态变量并校验声明存在。

## 方法 `Transformation.to_dict`（第 238–260 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "inputs": [role.to_dict() for role in self.inputs],
            "outputs": [role.to_dict() for role in self.outputs],
            "when": expr_to_dict(self.when),
            "output_when": expr_to_dict(self.output_when),
            "ensure": [expr_to_dict(expression) for expression in self.ensure],
        }
        if self.state_requirements:
            data["state_requirements"] = [
                item.to_dict() for item in self.state_requirements
            ]
        if self.state_updates:
            data["state_updates"] = [item.to_dict() for item in self.state_updates]
        if self.exact:
            data["exact"] = True
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

```

把 `Transformation` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `Transformation.from_dict`（第 261–315 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Transformation":
        if not isinstance(data, Mapping):
            raise SerializationError("transformation must be a mapping")
        allowed = {
            "name", "inputs", "outputs", "when", "output_when", "ensure",
            "state_requirements", "state_updates", "exact",
            "description", "tags",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "transformation contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_inputs = data.get("inputs", [])
        raw_outputs = data.get("outputs", [])
        raw_ensure = data.get("ensure", [])
        raw_requirements = data.get("state_requirements", [])
        raw_updates = data.get("state_updates", [])
        for name, value in (
            ("inputs", raw_inputs),
            ("outputs", raw_outputs),
            ("ensure", raw_ensure),
            ("state_requirements", raw_requirements),
            ("state_updates", raw_updates),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"transformation {name} must be a list")
        try:
            return cls(
                name=str(data["name"]),
                inputs=tuple(EventRole.from_dict(item) for item in raw_inputs),
                outputs=tuple(EventRole.from_dict(item) for item in raw_outputs),
                when=expr_from_dict(
                    data.get("when", Literal(True, BOOL).to_dict())
                ),
                output_when=expr_from_dict(
                    data.get("output_when", Literal(True, BOOL).to_dict())
                ),
                ensure=tuple(expr_from_dict(item) for item in raw_ensure),
                state_requirements=tuple(
                    StateRequirement.from_dict(item) for item in raw_requirements
                ),
                state_updates=tuple(
                    StateUpdate.from_dict(item) for item in raw_updates
                ),
                exact=bool(data.get("exact", False)),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SerializationError(
                f"transformation is missing {exc.args[0]!r}"
            ) from exc
```

校验输入字典的键和值，并递归构造 `Transformation` 实例。

