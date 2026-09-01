import pytest

from umcm.errors import TraceValidationError
from umcm.ir.event import EventInstance, EventType, FieldSpec, Visibility
from umcm.ir.expression import Symbol
from umcm.ir.sort import INT, Sort


LOAD = EventType(
    name="Arch.Load",
    module="Architecture",
    layer="architectural",
    visibility=Visibility.ARCHITECTURAL,
    fields=(
        FieldSpec("op_id", Sort("op_id"), identity=True),
        FieldSpec("hart", INT),
    ),
)


def test_partial_event_may_omit_required_field() -> None:
    event = EventInstance("l0", "Arch.Load", {"op_id": "L0"})
    event.validate_against(LOAD, partial=True)


def test_complete_event_requires_field() -> None:
    event = EventInstance("l0", "Arch.Load", {"op_id": "L0"})
    with pytest.raises(TraceValidationError):
        event.validate_against(LOAD, partial=False)


def test_symbolic_field_must_have_declared_sort() -> None:
    event = EventInstance(
        "l0",
        "Arch.Load",
        {"op_id": "L0", "hart": Symbol("hart", Sort("string"))},
    )
    with pytest.raises(TraceValidationError):
        event.validate_against(LOAD, partial=False)


def test_unknown_event_field_is_rejected() -> None:
    event = EventInstance(
        "l0",
        "Arch.Load",
        {"op_id": "L0", "hart": 0, "unknown": 1},
    )
    with pytest.raises(TraceValidationError):
        event.validate_against(LOAD, partial=False)
