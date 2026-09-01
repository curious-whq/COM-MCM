from pathlib import Path

import pytest

from umcm.errors import TraceValidationError
from umcm.ir.event import EventCatalog, EventInstance, EventType, FieldSpec
from umcm.ir.expression import Binary, EventField, Symbol
from umcm.ir.sort import INT, Sort
from umcm.ir.trace import Trace


def _catalog() -> EventCatalog:
    event_type = EventType(
        name="Arch.Load",
        module="Architecture",
        layer="architectural",
        fields=(FieldSpec("op_id", Sort("op_id")),),
    )
    return EventCatalog({event_type.name: event_type})


def test_duplicate_event_ids_are_rejected() -> None:
    with pytest.raises(TraceValidationError):
        Trace(
            events=[
                EventInstance("l0", "Arch.Load", {"op_id": "L0"}),
                EventInstance("l0", "Arch.Load", {"op_id": "L1"}),
            ]
        )


def test_constraint_cannot_reference_unknown_event() -> None:
    trace = Trace(
        events=[EventInstance("l0", "Arch.Load", {"op_id": "L0"})],
        constraints=[
            Binary(
                "lt",
                EventField("missing", "cycle", INT),
                Symbol("c1", INT),
            )
        ],
    )
    with pytest.raises(TraceValidationError):
        trace.validate(_catalog())


def test_trace_yaml_and_json_roundtrip(tmp_path: Path) -> None:
    trace = Trace(
        events=[EventInstance("l0", "Arch.Load", {"op_id": "L0"}, cycle=Symbol("c0", INT))],
        metadata={"purpose": "roundtrip"},
    )
    for suffix in ("yaml", "json"):
        path = tmp_path / f"trace.{suffix}"
        trace.dump(path)
        assert Trace.load(path).to_dict() == trace.to_dict()


def test_constraint_cannot_reference_unknown_field() -> None:
    trace = Trace(
        events=[EventInstance("l0", "Arch.Load", {"op_id": "L0"})],
        constraints=[
            Binary(
                "eq",
                EventField("l0", "missing", INT),
                Symbol("v", INT),
            )
        ],
    )
    with pytest.raises(TraceValidationError):
        trace.validate(_catalog())
