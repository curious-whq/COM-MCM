# `umcm/ir/expression.py` 源码讲解

文件职责：定义带类型表达式 AST、序列化和遍历工具。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–11 行）

```python
"""Typed expression AST shared by future transformations and axioms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence, TypeAlias

from umcm.errors import ExpressionTypeError, SerializationError
from umcm.ir.sort import BOOL, INT, STRING, Sort


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `Expr` 定义（第 12–14 行）

```python
class Expr:
    """Marker base class for immutable expression nodes."""

```

所有不可变表达式节点的抽象基类。

## 方法 `Expr.sort`（第 15–18 行）

```python
    @property
    def sort(self) -> Sort:  # pragma: no cover - abstract protocol
        raise NotImplementedError

```

返回该表达式节点在构造时已经验证的静态类型。

## 方法 `Expr.to_dict`（第 19–22 行）

```python
    def to_dict(self) -> dict[str, Any]:
        return expr_to_dict(self)


```

把 `Expr` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 类 `Literal` 及全部字段（第 23–27 行）

```python
@dataclass(frozen=True, slots=True)
class Literal(Expr):
    value: Any
    literal_sort: Sort | None = None

```

表示一个已知类型的常量表达式。

- `value`：该节点、字段或状态写入承载的值。
- `literal_sort`：字面量表达式的静态类型。

## 方法 `Literal.__post_init__`（第 28–35 行）

```python
    def __post_init__(self) -> None:
        inferred = self.literal_sort or _infer_literal_sort(self.value)
        if not inferred.accepts_literal(self.value):
            raise ExpressionTypeError(
                f"literal {self.value!r} is not valid for sort {inferred}"
            )
        object.__setattr__(self, "literal_sort", inferred)

```

在 `Literal` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Literal.sort`（第 36–41 行）

```python
    @property
    def sort(self) -> Sort:
        assert self.literal_sort is not None
        return self.literal_sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Symbol` 及全部字段（第 42–46 行）

```python
@dataclass(frozen=True, slots=True)
class Symbol(Expr):
    name: str
    symbol_sort: Sort

```

表示求解赋值中的一个带类型自由符号。

- `name`：对象或规则的稳定名称。
- `symbol_sort`：自由符号的静态类型。

## 方法 `Symbol.__post_init__`（第 47–50 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise ExpressionTypeError("symbol name must be non-empty")

```

在 `Symbol` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Symbol.sort`（第 51–55 行）

```python
    @property
    def sort(self) -> Sort:
        return self.symbol_sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `EventField` 及全部字段（第 56–61 行）

```python
@dataclass(frozen=True, slots=True)
class EventField(Expr):
    event_id: str
    field: str
    field_sort: Sort

```

表示对指定事件属性或字段的带类型引用。

- `event_id`：关联事件的稳定 ID。
- `field`：被事件字段表达式引用的字段或公共属性名。
- `field_sort`：被引用事件字段的静态类型。

## 方法 `EventField.__post_init__`（第 62–65 行）

```python
    def __post_init__(self) -> None:
        if not self.event_id or not self.field:
            raise ExpressionTypeError("event field requires non-empty event_id and field")

```

在 `EventField` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `EventField.sort`（第 66–70 行）

```python
    @property
    def sort(self) -> Sort:
        return self.field_sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Unary` 及全部字段（第 71–75 行）

```python
@dataclass(frozen=True, slots=True)
class Unary(Expr):
    op: str
    operand: Expr

```

表示一元运算表达式。

- `op`：表达式、关系或状态比较使用的运算符。
- `operand`：一元表达式的操作数。

## 方法 `Unary.__post_init__`（第 76–83 行）

```python
    def __post_init__(self) -> None:
        if self.op == "not":
            _require_bool(self.operand, "not")
        elif self.op == "neg":
            _require_numeric(self.operand, "neg")
        else:
            raise ExpressionTypeError(f"unsupported unary operator: {self.op}")

```

在 `Unary` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Unary.sort`（第 84–88 行）

```python
    @property
    def sort(self) -> Sort:
        return BOOL if self.op == "not" else self.operand.sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Binary` 及全部字段（第 89–94 行）

```python
@dataclass(frozen=True, slots=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr

```

表示二元运算表达式。

- `op`：表达式、关系或状态比较使用的运算符。
- `left`：二元表达式的左操作数。
- `right`：二元表达式的右操作数。

## 方法 `Binary.__post_init__`（第 95–109 行）

```python
    def __post_init__(self) -> None:
        if self.op in {"and", "or", "implies", "xor"}:
            _require_bool(self.left, self.op)
            _require_bool(self.right, self.op)
        elif self.op in {"eq", "ne"}:
            _require_compatible(self.left, self.right, self.op)
        elif self.op in {"lt", "le", "gt", "ge"}:
            _require_compatible(self.left, self.right, self.op)
            _require_ordered(self.left, self.op)
        elif self.op in {"add", "sub", "mul", "div", "mod"}:
            _require_compatible(self.left, self.right, self.op)
            _require_numeric(self.left, self.op)
        else:
            raise ExpressionTypeError(f"unsupported binary operator: {self.op}")

```

在 `Binary` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Binary.sort`（第 110–116 行）

```python
    @property
    def sort(self) -> Sort:
        if self.op in {"and", "or", "implies", "xor", "eq", "ne", "lt", "le", "gt", "ge"}:
            return BOOL
        return self.left.sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Nary` 及全部字段（第 117–121 行）

```python
@dataclass(frozen=True, slots=True)
class Nary(Expr):
    op: str
    operands: tuple[Expr, ...]

```

表示可变参数的合取、析取或全等表达式。

- `op`：表达式、关系或状态比较使用的运算符。
- `operands`：多元表达式的操作数元组。

## 方法 `Nary.__post_init__`（第 122–134 行）

```python
    def __post_init__(self) -> None:
        if not self.operands:
            raise ExpressionTypeError(f"{self.op} requires at least one operand")
        if self.op in {"and", "or"}:
            for operand in self.operands:
                _require_bool(operand, self.op)
        elif self.op == "distinct":
            head = self.operands[0]
            for operand in self.operands[1:]:
                _require_compatible(head, operand, self.op)
        else:
            raise ExpressionTypeError(f"unsupported n-ary operator: {self.op}")

```

在 `Nary` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Nary.sort`（第 135–139 行）

```python
    @property
    def sort(self) -> Sort:
        return BOOL


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Ite` 及全部字段（第 140–145 行）

```python
@dataclass(frozen=True, slots=True)
class Ite(Expr):
    condition: Expr
    then_expr: Expr
    else_expr: Expr

```

表示 if-then-else 条件表达式。

- `condition`：条件表达式。
- `then_expr`：条件为真时选择的表达式。
- `else_expr`：条件为假时选择的表达式。

## 方法 `Ite.__post_init__`（第 146–149 行）

```python
    def __post_init__(self) -> None:
        _require_bool(self.condition, "ite condition")
        _require_compatible(self.then_expr, self.else_expr, "ite branches")

```

在 `Ite` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Ite.sort`（第 150–154 行）

```python
    @property
    def sort(self) -> Sort:
        return self.then_expr.sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 类 `Call` 及全部字段（第 155–160 行）

```python
@dataclass(frozen=True, slots=True)
class Call(Expr):
    function: str
    arguments: tuple[Expr, ...]
    return_sort: Sort

```

表示对已登记纯函数的带类型调用。

- `function`：保存函数名，供该对象的校验、转换或序列化逻辑使用。
- `arguments`：保存参数集合，供该对象的校验、转换或序列化逻辑使用。
- `return_sort`：函数调用表达式声明的返回类型。

## 方法 `Call.__post_init__`（第 161–164 行）

```python
    def __post_init__(self) -> None:
        if not self.function:
            raise ExpressionTypeError("call function name must be non-empty")

```

在 `Call` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Call.sort`（第 165–169 行）

```python
    @property
    def sort(self) -> Sort:
        return self.return_sort


```

返回该表达式节点在构造时已经验证的静态类型。

## 模块变量 `Expression`（第 170–172 行）

```python
Expression: TypeAlias = Literal | Symbol | EventField | Unary | Binary | Nary | Ite | Call


```

这是模块级常量或公开导出声明：`Expression` 保存expression，供该对象的校验、转换或序列化逻辑使用。

## 函数 `literal`（第 173–176 行）

```python
def literal(value: Any, sort: Sort | None = None) -> Literal:
    return Literal(value, sort)


```

根据 Python 常量推断或采用显式类型，构造字面量节点。

## 函数 `symbol`（第 177–180 行）

```python
def symbol(name: str, sort: Sort) -> Symbol:
    return Symbol(name, sort)


```

构造指定名称和类型的自由符号节点。

## 函数 `event_field`（第 181–184 行）

```python
def event_field(event_id: str, field: str, sort: Sort) -> EventField:
    return EventField(event_id, field, sort)


```

构造对事件字段或公共属性的带类型引用。

## 函数 `unary`（第 185–188 行）

```python
def unary(op: str, operand: Expr) -> Unary:
    return Unary(op, operand)


```

构造一元表达式，并由节点初始化逻辑检查运算符与类型。

## 函数 `binary`（第 189–192 行）

```python
def binary(op: str, left: Expr, right: Expr) -> Binary:
    return Binary(op, left, right)


```

构造二元表达式，并检查操作数兼容性和结果类型。

## 函数 `nary`（第 193–196 行）

```python
def nary(op: str, operands: Iterable[Expr]) -> Nary:
    return Nary(op, tuple(operands))


```

把操作数冻结为元组后构造多元表达式并执行类型检查。

## 函数 `call`（第 197–200 行）

```python
def call(function: str, arguments: Iterable[Expr], return_sort: Sort) -> Call:
    return Call(function, tuple(arguments), return_sort)


```

构造带函数名、参数和显式返回类型的调用表达式。

## 函数 `expr_to_dict`（第 201–256 行）

```python
def expr_to_dict(expr: Expr) -> dict[str, Any]:
    if isinstance(expr, Literal):
        return {
            "node": "literal",
            "sort": expr.sort.to_dict(),
            "value": expr.value,
        }
    if isinstance(expr, Symbol):
        return {
            "node": "symbol",
            "name": expr.name,
            "sort": expr.sort.to_dict(),
        }
    if isinstance(expr, EventField):
        return {
            "node": "event_field",
            "event_id": expr.event_id,
            "field": expr.field,
            "sort": expr.sort.to_dict(),
        }
    if isinstance(expr, Unary):
        return {
            "node": "unary",
            "op": expr.op,
            "operand": expr_to_dict(expr.operand),
        }
    if isinstance(expr, Binary):
        return {
            "node": "binary",
            "op": expr.op,
            "left": expr_to_dict(expr.left),
            "right": expr_to_dict(expr.right),
        }
    if isinstance(expr, Nary):
        return {
            "node": "nary",
            "op": expr.op,
            "operands": [expr_to_dict(item) for item in expr.operands],
        }
    if isinstance(expr, Ite):
        return {
            "node": "ite",
            "condition": expr_to_dict(expr.condition),
            "then": expr_to_dict(expr.then_expr),
            "else": expr_to_dict(expr.else_expr),
        }
    if isinstance(expr, Call):
        return {
            "node": "call",
            "function": expr.function,
            "arguments": [expr_to_dict(item) for item in expr.arguments],
            "sort": expr.return_sort.to_dict(),
        }
    raise SerializationError(f"unsupported expression type: {type(expr).__name__}")


```

按表达式节点种类递归编码为带 `kind` 标签的字典。

## 函数 `expr_from_dict`（第 257–304 行）

```python
def expr_from_dict(data: Mapping[str, Any]) -> Expr:
    if not isinstance(data, Mapping):
        raise SerializationError("expression must be a mapping")
    node = data.get("node")
    try:
        if node == "literal":
            return Literal(data.get("value"), Sort.from_dict(data["sort"]))
        if node == "symbol":
            return Symbol(str(data["name"]), Sort.from_dict(data["sort"]))
        if node == "event_field":
            return EventField(
                str(data["event_id"]),
                str(data["field"]),
                Sort.from_dict(data["sort"]),
            )
        if node == "unary":
            return Unary(str(data["op"]), expr_from_dict(data["operand"]))
        if node == "binary":
            return Binary(
                str(data["op"]),
                expr_from_dict(data["left"]),
                expr_from_dict(data["right"]),
            )
        if node == "nary":
            operands = data.get("operands")
            if not isinstance(operands, Sequence):
                raise SerializationError("nary.operands must be a sequence")
            return Nary(str(data["op"]), tuple(expr_from_dict(item) for item in operands))
        if node == "ite":
            return Ite(
                expr_from_dict(data["condition"]),
                expr_from_dict(data["then"]),
                expr_from_dict(data["else"]),
            )
        if node == "call":
            arguments = data.get("arguments", [])
            if not isinstance(arguments, Sequence):
                raise SerializationError("call.arguments must be a sequence")
            return Call(
                str(data["function"]),
                tuple(expr_from_dict(item) for item in arguments),
                Sort.from_dict(data["sort"]),
            )
    except KeyError as exc:
        raise SerializationError(f"expression node {node!r} is missing {exc.args[0]!r}") from exc
    raise SerializationError(f"unknown expression node: {node!r}")


```

读取 `kind` 标签并递归解析子表达式，重建带类型表达式 AST。

## 函数 `_infer_literal_sort`（第 305–316 行）

```python
def _infer_literal_sort(value: Any) -> Sort:
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return INT
    if isinstance(value, str):
        return STRING
    raise ExpressionTypeError(
        f"cannot infer sort for literal type {type(value).__name__}; pass an explicit sort"
    )


```

根据布尔、整数或字符串值推断字面量类型，拒绝其他 Python 类型。

## 函数 `_require_bool`（第 317–321 行）

```python
def _require_bool(expr: Expr, context: str) -> None:
    if not expr.sort.is_bool:
        raise ExpressionTypeError(f"{context} requires bool, got {expr.sort}")


```

要求表达式为布尔类型，否则抛出表达式类型错误。

## 函数 `_require_numeric`（第 322–326 行）

```python
def _require_numeric(expr: Expr, context: str) -> None:
    if not (expr.sort.is_int or expr.sort.is_bitvector):
        raise ExpressionTypeError(f"{context} requires int/bv, got {expr.sort}")


```

要求表达式为整数或位向量类型。

## 函数 `_require_ordered`（第 327–331 行）

```python
def _require_ordered(expr: Expr, context: str) -> None:
    if not (expr.sort.is_int or expr.sort.is_bitvector):
        raise ExpressionTypeError(f"{context} requires an ordered int/bv sort, got {expr.sort}")


```

要求表达式类型支持大小比较。

## 函数 `_require_compatible`（第 332–338 行）

```python
def _require_compatible(left: Expr, right: Expr, context: str) -> None:
    if not left.sort.compatible_with(right.sort):
        raise ExpressionTypeError(
            f"{context} requires matching sorts, got {left.sort} and {right.sort}"
        )


```

要求两个表达式类型可直接比较或组合。

## 函数 `iter_event_fields`（第 339–360 行）

```python
def iter_event_fields(expr: Expr) -> Iterator[EventField]:
    """Yield all event-field references contained in *expr*."""

    if isinstance(expr, EventField):
        yield expr
    elif isinstance(expr, Unary):
        yield from iter_event_fields(expr.operand)
    elif isinstance(expr, Binary):
        yield from iter_event_fields(expr.left)
        yield from iter_event_fields(expr.right)
    elif isinstance(expr, Nary):
        for operand in expr.operands:
            yield from iter_event_fields(operand)
    elif isinstance(expr, Ite):
        yield from iter_event_fields(expr.condition)
        yield from iter_event_fields(expr.then_expr)
        yield from iter_event_fields(expr.else_expr)
    elif isinstance(expr, Call):
        for argument in expr.arguments:
            yield from iter_event_fields(argument)


```

递归遍历表达式树并产出全部事件字段引用。

## 函数 `iter_symbols`（第 361–382 行）

```python
def iter_symbols(expr: Expr) -> Iterator[Symbol]:
    """Yield all free symbols contained in *expr*."""

    if isinstance(expr, Symbol):
        yield expr
    elif isinstance(expr, Unary):
        yield from iter_symbols(expr.operand)
    elif isinstance(expr, Binary):
        yield from iter_symbols(expr.left)
        yield from iter_symbols(expr.right)
    elif isinstance(expr, Nary):
        for operand in expr.operands:
            yield from iter_symbols(operand)
    elif isinstance(expr, Ite):
        yield from iter_symbols(expr.condition)
        yield from iter_symbols(expr.then_expr)
        yield from iter_symbols(expr.else_expr)
    elif isinstance(expr, Call):
        for argument in expr.arguments:
            yield from iter_symbols(argument)


```

递归遍历表达式树并产出全部自由符号。

## 函数 `iter_literals`（第 383–404 行）

```python
def iter_literals(expr: Expr) -> Iterator[Literal]:
    """Yield all literal nodes contained in *expr*."""

    if isinstance(expr, Literal):
        yield expr
    elif isinstance(expr, Unary):
        yield from iter_literals(expr.operand)
    elif isinstance(expr, Binary):
        yield from iter_literals(expr.left)
        yield from iter_literals(expr.right)
    elif isinstance(expr, Nary):
        for operand in expr.operands:
            yield from iter_literals(operand)
    elif isinstance(expr, Ite):
        yield from iter_literals(expr.condition)
        yield from iter_literals(expr.then_expr)
        yield from iter_literals(expr.else_expr)
    elif isinstance(expr, Call):
        for argument in expr.arguments:
            yield from iter_literals(argument)


```

递归遍历表达式树并产出全部字面量节点。

## 函数 `substitute_event_ids`（第 405–437 行）

```python
def substitute_event_ids(expr: Expr, mapping: Mapping[str, str]) -> Expr:
    """Replace event/role identifiers while preserving the typed AST."""

    if isinstance(expr, EventField):
        return EventField(mapping.get(expr.event_id, expr.event_id), expr.field, expr.sort)
    if isinstance(expr, Unary):
        return Unary(expr.op, substitute_event_ids(expr.operand, mapping))
    if isinstance(expr, Binary):
        return Binary(
            expr.op,
            substitute_event_ids(expr.left, mapping),
            substitute_event_ids(expr.right, mapping),
        )
    if isinstance(expr, Nary):
        return Nary(
            expr.op,
            tuple(substitute_event_ids(item, mapping) for item in expr.operands),
        )
    if isinstance(expr, Ite):
        return Ite(
            substitute_event_ids(expr.condition, mapping),
            substitute_event_ids(expr.then_expr, mapping),
            substitute_event_ids(expr.else_expr, mapping),
        )
    if isinstance(expr, Call):
        return Call(
            expr.function,
            tuple(substitute_event_ids(item, mapping) for item in expr.arguments),
            expr.return_sort,
        )
    return expr


```

递归重建表达式树，把角色形式的事件 ID 替换为具体事件 ID。

## 函数 `conjunction`（第 438–448 行）

```python
def conjunction(expressions: Iterable[Expr]) -> Expr:
    """Build a conjunction, using ``true`` for an empty sequence."""

    items = tuple(expressions)
    if not items:
        return Literal(True, BOOL)
    if len(items) == 1:
        return items[0]
    return Nary("and", items)


```

用多元 `and` 组合表达式；空输入规范化为真。

## 函数 `disjunction`（第 449–457 行）

```python
def disjunction(expressions: Iterable[Expr]) -> Expr:
    """Build a disjunction, using ``false`` for an empty sequence."""

    items = tuple(expressions)
    if not items:
        return Literal(False, BOOL)
    if len(items) == 1:
        return items[0]
    return Nary("or", items)
```

用多元 `or` 组合表达式；空输入规范化为假。

