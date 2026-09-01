import pytest

from umcm.errors import ExpressionTypeError
from umcm.ir.expression import Binary, Call, EventField, Literal, Symbol, expr_from_dict
from umcm.ir.sort import BOOL, INT, Sort


def test_expression_roundtrip() -> None:
    expr = Binary(
        "and",
        Binary("lt", Symbol("c0", INT), Symbol("c1", INT)),
        Call(
            "same_address",
            (
                EventField("l0", "address", Sort("address", width=64)),
                EventField("l1", "address", Sort("address", width=64)),
            ),
            BOOL,
        ),
    )
    assert expr_from_dict(expr.to_dict()) == expr
    assert expr.sort == BOOL


def test_bad_boolean_operator_is_rejected() -> None:
    with pytest.raises(ExpressionTypeError):
        Binary("and", Literal(1), Literal(2))


def test_mismatched_equality_is_rejected() -> None:
    with pytest.raises(ExpressionTypeError):
        Binary("eq", Literal(1), Literal("1"))
