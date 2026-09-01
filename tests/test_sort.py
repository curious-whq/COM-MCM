import pytest

from umcm.errors import SchemaError
from umcm.ir.sort import BOOL, INT, Sort, bitvec


def test_sort_roundtrip() -> None:
    original = Sort("address", width=56)
    assert Sort.from_dict(original.to_dict()) == original


def test_bitvector_literal_range() -> None:
    nibble = bitvec(4)
    assert nibble.accepts_literal(15)
    assert not nibble.accepts_literal(16)
    assert not nibble.accepts_literal(-1)


def test_invalid_bool_width() -> None:
    with pytest.raises(SchemaError):
        Sort("bool", width=1)


def test_builtin_literal_types_are_strict() -> None:
    assert BOOL.accepts_literal(True)
    assert not BOOL.accepts_literal(1)
    assert INT.accepts_literal(1)
    assert not INT.accepts_literal(True)
