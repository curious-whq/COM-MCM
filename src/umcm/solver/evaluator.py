"""Concrete and partial evaluation of the typed expression AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from umcm.errors import SolverError, TraceValidationError
from umcm.ir.event import EventInstance
from umcm.ir.expression import Binary, Call, EventField, Expr, Ite, Literal, Nary, Symbol, Unary


class _Unknown:
    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "UNKNOWN"


UNKNOWN = _Unknown()
Function = Callable[[tuple[Any, ...]], Any]


def _all_equal(arguments: tuple[Any, ...]) -> bool:
    return all(item == arguments[0] for item in arguments[1:]) if arguments else True


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


def _mask_overlap(arguments: tuple[Any, ...]) -> bool:
    if len(arguments) != 2:
        raise SolverError("mask_overlap expects two integer masks")
    left, right = arguments
    return (int(left) & int(right)) != 0


def _mask_covers(arguments: tuple[Any, ...]) -> bool:
    if len(arguments) != 2:
        raise SolverError("mask_covers expects provider and consumer masks")
    provider, consumer = arguments
    provider = int(provider)
    consumer = int(consumer)
    return (provider & consumer) == consumer


DEFAULT_FUNCTIONS: dict[str, Function] = {
    "same_address": _all_equal,
    "same_identity": _all_equal,
    "same_op": _all_equal,
    "same_value": _all_equal,
    "same_block": _same_block,
    "mask_overlap": _mask_overlap,
    "mask_covers": _mask_covers,
}


@dataclass(slots=True)
class EvaluationContext:
    events: Mapping[str, EventInstance]
    assignment: Mapping[str, Any]
    functions: Mapping[str, Function] = field(default_factory=lambda: DEFAULT_FUNCTIONS)

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
