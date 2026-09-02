# `umcm/solver/evaluator.py` 源码讲解

文件职责：在部分赋值下对带类型表达式进行三值求值。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–12 行）

```python
"""Concrete and partial evaluation of the typed expression AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from umcm.errors import SolverError, TraceValidationError
from umcm.ir.event import EventInstance
from umcm.ir.expression import Binary, Call, EventField, Expr, Ite, Literal, Nary, Symbol, Unary


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `_Unknown` 定义（第 13–13 行）

```python
class _Unknown:
```

表示部分求值阶段尚不能确定的值。

## 方法 `_Unknown.__repr__`（第 14–17 行）

```python
    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "UNKNOWN"


```

返回该哨兵对象稳定且便于诊断的文本表示。

## 模块变量 `UNKNOWN`（第 18–18 行）

```python
UNKNOWN = _Unknown()
```

这是模块级常量或公开导出声明：`UNKNOWN` 定义枚举成员，表示后端未能确定结果。

## 模块变量 `Function`（第 19–21 行）

```python
Function = Callable[[tuple[Any, ...]], Any]


```

这是模块级常量或公开导出声明：`Function` 保存函数名，供该对象的校验、转换或序列化逻辑使用。

## 函数 `_all_equal`（第 22–25 行）

```python
def _all_equal(arguments: tuple[Any, ...]) -> bool:
    return all(item == arguments[0] for item in arguments[1:]) if arguments else True


```

判断序列内所有值是否相等；空序列和单元素序列视为相等。

## 函数 `_same_block`（第 26–40 行）

```python
def _same_block(arguments: tuple[Any, ...]) -> bool:
    if len(arguments) not in {2, 3}:
        raise SolverError("same_block expects two addresses and optional block size")
    left, right = arguments[:2]
    if len(arguments) == 2:
        return left == right
    size = arguments[2]
    if not isinstance(left, int) or not isinstance(right, int) or not isinstance(size, int):
        # Symbolic names such as "x" identify one abstract location already.
        return left == right
    if size <= 0:
        raise SolverError("same_block block size must be positive")
    return left // size == right // size


```

判断两个整数地址在给定块大小下是否属于同一块，并拒绝非法块大小。

## 模块变量 `DEFAULT_FUNCTIONS`（第 41–49 行）

```python
DEFAULT_FUNCTIONS: dict[str, Function] = {
    "same_address": _all_equal,
    "same_identity": _all_equal,
    "same_op": _all_equal,
    "same_value": _all_equal,
    "same_block": _same_block,
}


```

这是模块级常量或公开导出声明：`DEFAULT_FUNCTIONS` 保存defaultfunctions，供该对象的校验、转换或序列化逻辑使用。

## 类 `EvaluationContext` 及全部字段（第 50–55 行）

```python
@dataclass(slots=True)
class EvaluationContext:
    events: Mapping[str, EventInstance]
    assignment: Mapping[str, Any]
    functions: Mapping[str, Function] = field(default_factory=lambda: DEFAULT_FUNCTIONS)

```

为表达式求值提供事件、符号赋值和函数环境。

- `events`：本对象管理的事件集合。
- `assignment`：符号名到具体值的求解赋值。
- `functions`：表达式求值允许调用的纯函数映射。

## 方法 `EvaluationContext.event_attribute`（第 56–73 行）

```python
    def event_attribute(self, event_id: str, field_name: str) -> Any:
        try:
            event = self.events[event_id]
        except KeyError as exc:
            raise TraceValidationError(f"unknown event id during evaluation: {event_id}") from exc
        if field_name == "occurs":
            value = event.occurs
        elif field_name == "cycle":
            value = event.cycle
        else:
            if field_name not in event.fields:
                return UNKNOWN
            value = event.fields[field_name]
        if isinstance(value, Expr):
            return evaluate(value, self)
        return value


```

解析事件公共属性或 `fields.<name>` 路径；缺失、未发生或未赋值时返回 UNKNOWN。

## 函数 `evaluate`（第 74–123 行）

```python
def evaluate(expr: Expr, context: EvaluationContext) -> Any:
    """Evaluate an expression under a possibly partial assignment.

    The result is a Python literal or :data:`UNKNOWN`.  Boolean operators use
    three-valued short-circuiting, which lets the finite solver reject partial
    assignments as soon as a constraint is definitely false.
    """

    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Symbol):
        return context.assignment.get(expr.name, UNKNOWN)
    if isinstance(expr, EventField):
        return context.event_attribute(expr.event_id, expr.field)
    if isinstance(expr, Unary):
        operand = evaluate(expr.operand, context)
        if operand is UNKNOWN:
            return UNKNOWN
        if expr.op == "not":
            return not operand
        if expr.op == "neg":
            return -operand
        raise SolverError(f"unsupported unary operator: {expr.op}")
    if isinstance(expr, Binary):
        return _evaluate_binary(expr, context)
    if isinstance(expr, Nary):
        return _evaluate_nary(expr, context)
    if isinstance(expr, Ite):
        condition = evaluate(expr.condition, context)
        if condition is True:
            return evaluate(expr.then_expr, context)
        if condition is False:
            return evaluate(expr.else_expr, context)
        then_value = evaluate(expr.then_expr, context)
        else_value = evaluate(expr.else_expr, context)
        if then_value is not UNKNOWN and then_value == else_value:
            return then_value
        return UNKNOWN
    if isinstance(expr, Call):
        values = tuple(evaluate(item, context) for item in expr.arguments)
        if any(value is UNKNOWN for value in values):
            return UNKNOWN
        try:
            function = context.functions[expr.function]
        except KeyError as exc:
            raise SolverError(f"unknown expression function: {expr.function}") from exc
        return function(values)
    raise SolverError(f"unsupported expression node: {type(expr).__name__}")


```

递归求值表达式；未知输入保留为 UNKNOWN，布尔运算使用可提前判定的三值短路语义。

## 函数 `_evaluate_binary`（第 124–182 行）

```python
def _evaluate_binary(expr: Binary, context: EvaluationContext) -> Any:
    left = evaluate(expr.left, context)
    right = evaluate(expr.right, context)

    if expr.op == "and":
        if left is False or right is False:
            return False
        if left is True and right is True:
            return True
        return UNKNOWN
    if expr.op == "or":
        if left is True or right is True:
            return True
        if left is False and right is False:
            return False
        return UNKNOWN
    if expr.op == "implies":
        if left is False or right is True:
            return True
        if left is True and right is False:
            return False
        return UNKNOWN
    if expr.op == "xor":
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        return bool(left) ^ bool(right)

    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN

    if expr.op == "eq":
        return left == right
    if expr.op == "ne":
        return left != right
    if expr.op == "lt":
        return left < right
    if expr.op == "le":
        return left <= right
    if expr.op == "gt":
        return left > right
    if expr.op == "ge":
        return left >= right
    if expr.op == "add":
        return left + right
    if expr.op == "sub":
        return left - right
    if expr.op == "mul":
        return left * right
    if expr.op == "div":
        if right == 0:
            raise SolverError("division by zero in expression")
        return left // right
    if expr.op == "mod":
        if right == 0:
            raise SolverError("modulo by zero in expression")
        return left % right
    raise SolverError(f"unsupported binary operator: {expr.op}")


```

实现二元比较、算术和布尔运算，并在未知操作数下遵循三值短路规则。

## 函数 `_evaluate_nary`（第 183–204 行）

```python
def _evaluate_nary(expr: Nary, context: EvaluationContext) -> Any:
    values = [evaluate(item, context) for item in expr.operands]
    if expr.op == "and":
        if any(value is False for value in values):
            return False
        if all(value is True for value in values):
            return True
        return UNKNOWN
    if expr.op == "or":
        if any(value is True for value in values):
            return True
        if all(value is False for value in values):
            return False
        return UNKNOWN
    if expr.op == "distinct":
        concrete = [value for value in values if value is not UNKNOWN]
        if len(concrete) != len(set(concrete)):
            return False
        if len(concrete) == len(values):
            return True
        return UNKNOWN
    raise SolverError(f"unsupported n-ary operator: {expr.op}")
```

实现多元合取、析取和全等，在部分未知时尽早得出可确定结果。

