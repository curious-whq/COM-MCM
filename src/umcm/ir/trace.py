"""Partial traces composed of dynamic events and typed constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SerializationError, TraceValidationError
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict
from umcm.serialization import decode_value, dump_data, encode_value, load_data


TRACE_SCHEMA_VERSION = "umcm.trace.v0.1"


@dataclass(frozen=True, slots=True)
class PartialObservation:
    """A normalized observation over one event attribute.

    ``path`` is ``cycle``, ``occurs`` or ``fields.<name>``.  Event instances are
    still the canonical storage format; this helper is useful for tooling that
    wants to enumerate exactly what a partial trace has observed.
    """

    event_id: str
    path: str
    value: Any


@dataclass(slots=True)
class Trace:
    events: list[EventInstance] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    partial: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.events = list(self.events)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        self._validate_structure()

    def _validate_structure(self) -> None:
        ids = [event.id for event in self.events]
        duplicates = sorted({event_id for event_id in ids if ids.count(event_id) > 1})
        if duplicates:
            raise TraceValidationError(
                f"trace contains duplicate event id(s): {', '.join(duplicates)}"
            )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise TraceValidationError(
                    f"trace constraint must be bool, got {constraint.sort}"
                )

    def validate(self, catalog: EventCatalog, *, partial: bool | None = None) -> None:
        self._validate_structure()
        catalog.validate_events(
            self.events,
            partial=self.partial if partial is None else partial,
        )
        event_map = {event.id: event for event in self.events}
        from umcm.ir.expression import iter_event_fields
        from umcm.ir.sort import BOOL, INT

        for constraint in self.constraints:
            for reference in iter_event_fields(constraint):
                event = event_map.get(reference.event_id)
                if event is None:
                    raise TraceValidationError(
                        f"constraint references unknown event id {reference.event_id!r}"
                    )
                if reference.field == "cycle":
                    expected = INT
                elif reference.field == "occurs":
                    expected = BOOL
                else:
                    event_type = catalog.resolve(event.event_type)
                    try:
                        expected = event_type.field_map[reference.field].sort
                    except KeyError as exc:
                        raise TraceValidationError(
                            f"constraint references unknown field "
                            f"{reference.event_id}.{reference.field}"
                        ) from exc
                if not reference.sort.compatible_with(expected):
                    raise TraceValidationError(
                        f"constraint reference {reference.event_id}.{reference.field} "
                        f"has sort {reference.sort}, expected {expected}"
                    )

    def get(self, event_id: str) -> EventInstance:
        for event in self.events:
            if event.id == event_id:
                return event
        raise TraceValidationError(f"unknown event id: {event_id}")

    def events_of_type(self, event_type: str) -> list[EventInstance]:
        return [event for event in self.events if event.event_type == event_type]

    def observations(self) -> list[PartialObservation]:
        result: list[PartialObservation] = []
        for event in self.events:
            result.append(PartialObservation(event.id, "occurs", event.occurs))
            if event.cycle is not None:
                result.append(PartialObservation(event.id, "cycle", event.cycle))
            result.extend(
                PartialObservation(event.id, f"fields.{name}", value)
                for name, value in sorted(event.fields.items())
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "partial": self.partial,
            "metadata": encode_value(self.metadata),
            "events": [event.to_dict() for event in self.events],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Trace":
        if not isinstance(data, Mapping):
            raise SerializationError("trace must be a mapping")
        raw_events = data.get("events", [])
        raw_constraints = data.get("constraints", [])
        if not isinstance(raw_events, list):
            raise SerializationError("trace events must be a list")
        if not isinstance(raw_constraints, list):
            raise SerializationError("trace constraints must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("trace metadata must be a mapping")
        return cls(
            events=[EventInstance.from_dict(item) for item in raw_events],
            constraints=[expr_from_dict(item) for item in raw_constraints],
            partial=bool(data.get("partial", True)),
            metadata=metadata,
            schema_version=str(data.get("schema_version", TRACE_SCHEMA_VERSION)),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Trace":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


def _event_references(expr: Expr) -> set[str]:
    from umcm.ir.expression import Binary, Call, EventField, Ite, Nary, Unary

    if isinstance(expr, EventField):
        return {expr.event_id}
    if isinstance(expr, Unary):
        return _event_references(expr.operand)
    if isinstance(expr, Binary):
        return _event_references(expr.left) | _event_references(expr.right)
    if isinstance(expr, Nary):
        refs: set[str] = set()
        for operand in expr.operands:
            refs |= _event_references(operand)
        return refs
    if isinstance(expr, Ite):
        return (
            _event_references(expr.condition)
            | _event_references(expr.then_expr)
            | _event_references(expr.else_expr)
        )
    if isinstance(expr, Call):
        refs: set[str] = set()
        for argument in expr.arguments:
            refs |= _event_references(argument)
        return refs
    return set()
