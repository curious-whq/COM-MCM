# `umcm/ir/state.py` 源码讲解

文件职责：定义有界微架构轨迹中的持久状态、前置条件和更新。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–19 行）

```python
"""Persistent operational state for bounded microarchitectural traces.

A ``StateVariable`` declares one scalar state cell.  A stateful transformation
can attach ``StateRequirement`` objects, which inspect the pre-state at an
anchor event, and ``StateUpdate`` objects, which atomically write the post-state
of that event cycle.  Cells not written in a cycle stutter automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict
from umcm.ir.sort import Sort
from umcm.serialization import decode_value, encode_value


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `StateVariable` 及全部字段（第 20–28 行）

```python
@dataclass(frozen=True, slots=True)
class StateVariable:
    """One persistent scalar state cell."""

    name: str
    sort: Sort
    initial: Any
    description: str = ""

```

描述一个带初值的持久标量状态单元。

- `name`：对象或规则的稳定名称。
- `sort`：值或表达式的静态类型。
- `initial`：持久状态单元的初始值。
- `description`：供人阅读的说明文本。

## 方法 `StateVariable.__post_init__`（第 29–46 行）

```python
    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise SchemaError(
                "state variable name must be qualified, for example "
                "'LSU.retry_queue.valid'"
            )
        if isinstance(self.initial, Expr):
            if not self.initial.sort.compatible_with(self.sort):
                raise SchemaError(
                    f"state variable {self.name!r} initial expression has sort "
                    f"{self.initial.sort}, expected {self.sort}"
                )
        elif not self.sort.accepts_literal(self.initial):
            raise SchemaError(
                f"state variable {self.name!r} initial value "
                f"{self.initial!r} is invalid for {self.sort}"
            )

```

在 `StateVariable` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `StateVariable.to_dict`（第 47–56 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "sort": self.sort.to_dict(),
            "initial": encode_value(self.initial),
        }
        if self.description:
            data["description"] = self.description
        return data

```

把 `StateVariable` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `StateVariable.from_dict`（第 57–73 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateVariable":
        if not isinstance(data, Mapping):
            raise SerializationError("state variable must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                sort=Sort.from_dict(data["sort"]),
                initial=decode_value(data["initial"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state variable is missing {exc.args[0]!r}"
            ) from exc


```

校验输入字典的键和值，并递归构造 `StateVariable` 实例。

## 类 `StateRequirement` 及全部字段（第 74–83 行）

```python
@dataclass(frozen=True, slots=True)
class StateRequirement:
    """A pre-state comparison anchored to an input event role."""

    state: str
    at: str
    op: str
    value: Expr
    description: str = ""

```

描述锚定到事件角色的前状态比较条件。

- `state`：被条件或更新访问的状态变量名。
- `at`：作为状态条件或更新时间锚点的事件角色。
- `op`：表达式、关系或状态比较使用的运算符。
- `value`：该节点、字段或状态写入承载的值。
- `description`：供人阅读的说明文本。

## 方法 `StateRequirement.__post_init__`（第 84–94 行）

```python
    def __post_init__(self) -> None:
        if not self.state:
            raise SchemaError("state requirement must name a state variable")
        if not self.at:
            raise SchemaError("state requirement must name an anchor role")
        if self.op not in {"eq", "ne"}:
            raise SchemaError(
                f"unsupported state requirement operator {self.op!r}; "
                "available: eq, ne"
            )

```

在 `StateRequirement` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `StateRequirement.to_dict`（第 95–105 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "state": self.state,
            "at": self.at,
            "op": self.op,
            "value": expr_to_dict(self.value),
        }
        if self.description:
            data["description"] = self.description
        return data

```

把 `StateRequirement` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `StateRequirement.from_dict`（第 106–123 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateRequirement":
        if not isinstance(data, Mapping):
            raise SerializationError("state requirement must be a mapping")
        try:
            return cls(
                state=str(data["state"]),
                at=str(data["at"]),
                op=str(data.get("op", "eq")),
                value=expr_from_dict(data["value"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state requirement is missing {exc.args[0]!r}"
            ) from exc


```

校验输入字典的键和值，并递归构造 `StateRequirement` 实例。

## 类 `StateUpdate` 及全部字段（第 124–132 行）

```python
@dataclass(frozen=True, slots=True)
class StateUpdate:
    """An atomic post-state write anchored to an input event role."""

    state: str
    at: str
    value: Expr
    description: str = ""

```

描述锚定到事件角色的原子后状态写入。

- `state`：被条件或更新访问的状态变量名。
- `at`：作为状态条件或更新时间锚点的事件角色。
- `value`：该节点、字段或状态写入承载的值。
- `description`：供人阅读的说明文本。

## 方法 `StateUpdate.__post_init__`（第 133–138 行）

```python
    def __post_init__(self) -> None:
        if not self.state:
            raise SchemaError("state update must name a state variable")
        if not self.at:
            raise SchemaError("state update must name an anchor role")

```

在 `StateUpdate` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `StateUpdate.to_dict`（第 139–148 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "state": self.state,
            "at": self.at,
            "value": expr_to_dict(self.value),
        }
        if self.description:
            data["description"] = self.description
        return data

```

把 `StateUpdate` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `StateUpdate.from_dict`（第 149–163 行）

```python
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateUpdate":
        if not isinstance(data, Mapping):
            raise SerializationError("state update must be a mapping")
        try:
            return cls(
                state=str(data["state"]),
                at=str(data["at"]),
                value=expr_from_dict(data["value"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state update is missing {exc.args[0]!r}"
            ) from exc
```

校验输入字典的键和值，并递归构造 `StateUpdate` 实例。

