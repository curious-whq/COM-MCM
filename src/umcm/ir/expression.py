"""Typed expression AST shared by future transformations and axioms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence, TypeAlias

from umcm.errors import ExpressionTypeError, SerializationError
from umcm.ir.sort import BOOL, INT, STRING, Sort


class Expr:
    """Marker base class for immutable expression nodes."""

    @property
    def sort(self) -> Sort:  # pragma: no cover - abstract protocol
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return expr_to_dict(self)


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    value: Any
    literal_sort: Sort | None = None

    def __post_init__(self) -> None:
        inferred = self.literal_sort or _infer_literal_sort(self.value)
        if not inferred.accepts_literal(self.value):
            raise ExpressionTypeError(
                f"literal {self.value!r} is not valid for sort {inferred}"
            )
        object.__setattr__(self, "literal_sort", inferred)

    @property
    def sort(self) -> Sort:
        assert self.literal_sort is not None
        return self.literal_sort


@dataclass(frozen=True, slots=True)
class Symbol(Expr):
    name: str
    symbol_sort: Sort

    def __post_init__(self) -> None:
        if not self.name:
            raise ExpressionTypeError("symbol name must be non-empty")

    @property
    def sort(self) -> Sort:
        return self.symbol_sort


@dataclass(frozen=True, slots=True)
class EventField(Expr):
    event_id: str
    field: str
    field_sort: Sort

    def __post_init__(self) -> None:
        if not self.event_id or not self.field:
            raise ExpressionTypeError("event field requires non-empty event_id and field")

    @property
    def sort(self) -> Sort:
        return self.field_sort


@dataclass(frozen=True, slots=True)
class Unary(Expr):
    op: str
    operand: Expr

    def __post_init__(self) -> None:
        if self.op == "not":
            _require_bool(self.operand, "not")
        elif self.op == "neg":
            _require_numeric(self.operand, "neg")
        else:
            raise ExpressionTypeError(f"unsupported unary operator: {self.op}")

    @property
    def sort(self) -> Sort:
        return BOOL if self.op == "not" else self.operand.sort


@dataclass(frozen=True, slots=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr

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

    @property
    def sort(self) -> Sort:
        if self.op in {"and", "or", "implies", "xor", "eq", "ne", "lt", "le", "gt", "ge"}:
            return BOOL
        return self.left.sort


@dataclass(frozen=True, slots=True)
class Nary(Expr):
    op: str
    operands: tuple[Expr, ...]

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

    @property
    def sort(self) -> Sort:
        return BOOL


@dataclass(frozen=True, slots=True)
class Ite(Expr):
    condition: Expr
    then_expr: Expr
    else_expr: Expr

    def __post_init__(self) -> None:
        _require_bool(self.condition, "ite condition")
        _require_compatible(self.then_expr, self.else_expr, "ite branches")

    @property
    def sort(self) -> Sort:
        return self.then_expr.sort


@dataclass(frozen=True, slots=True)
class Call(Expr):
    function: str
    arguments: tuple[Expr, ...]
    return_sort: Sort

    def __post_init__(self) -> None:
        if not self.function:
            raise ExpressionTypeError("call function name must be non-empty")

    @property
    def sort(self) -> Sort:
        return self.return_sort


Expression: TypeAlias = Literal | Symbol | EventField | Unary | Binary | Nary | Ite | Call


def literal(value: Any, sort: Sort | None = None) -> Literal:
    return Literal(value, sort)


def symbol(name: str, sort: Sort) -> Symbol:
    return Symbol(name, sort)


def event_field(event_id: str, field: str, sort: Sort) -> EventField:
    return EventField(event_id, field, sort)


def unary(op: str, operand: Expr) -> Unary:
    return Unary(op, operand)


def binary(op: str, left: Expr, right: Expr) -> Binary:
    return Binary(op, left, right)


def nary(op: str, operands: Iterable[Expr]) -> Nary:
    return Nary(op, tuple(operands))


def call(function: str, arguments: Iterable[Expr], return_sort: Sort) -> Call:
    return Call(function, tuple(arguments), return_sort)


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


def _require_bool(expr: Expr, context: str) -> None:
    if not expr.sort.is_bool:
        raise ExpressionTypeError(f"{context} requires bool, got {expr.sort}")


def _require_numeric(expr: Expr, context: str) -> None:
    if not (expr.sort.is_int or expr.sort.is_bitvector):
        raise ExpressionTypeError(f"{context} requires int/bv, got {expr.sort}")


def _require_ordered(expr: Expr, context: str) -> None:
    if not (expr.sort.is_int or expr.sort.is_bitvector):
        raise ExpressionTypeError(f"{context} requires an ordered int/bv sort, got {expr.sort}")


def _require_compatible(left: Expr, right: Expr, context: str) -> None:
    if not left.sort.compatible_with(right.sort):
        raise ExpressionTypeError(
            f"{context} requires matching sorts, got {left.sort} and {right.sort}"
        )
