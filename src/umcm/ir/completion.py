"""Finite event-slot declarations and completion-model serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError, TraceValidationError
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import Expr, Symbol, iter_event_fields, expr_from_dict, expr_to_dict
from umcm.ir.sort import BOOL, INT
from umcm.ir.state import StateVariable
from umcm.ir.trace import Trace
from umcm.ir.transformation import Transformation
from umcm.serialization import decode_value, dump_data, encode_value, load_data


COMPLETION_SCHEMA_VERSION = "umcm.completion.v0.6.0"


@dataclass(frozen=True, slots=True)
class EventSlot:
    """One bounded candidate event available to the completion solver.

    ``required`` means that the current witness query demands this event. It is
    not a global liveness claim about every execution of the modeled hardware.
    """

    id: str
    event_type: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    required: bool = False
    cycle: int | Expr | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise SchemaError("event slot id must be non-empty")
        if not self.event_type:
            raise SchemaError("event slot type must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))
        object.__setattr__(self, "annotations", dict(self.annotations))

    def validate(self, catalog: EventCatalog) -> None:
        event_type = catalog.resolve(self.event_type)
        unknown = set(self.fields) - set(event_type.field_map)
        if unknown:
            raise SchemaError(
                f"slot {self.id!r} has unknown field(s): "
                f"{', '.join(sorted(unknown))}"
            )
        for name, value in self.fields.items():
            expected = event_type.field_map[name].sort
            if isinstance(value, Expr):
                if not value.sort.compatible_with(expected):
                    raise SchemaError(
                        f"slot {self.id!r}.{name} expects {expected}, got {value.sort}"
                    )
            elif not expected.accepts_literal(value):
                raise SchemaError(
                    f"slot {self.id!r}.{name} value {value!r} is invalid for {expected}"
                )

    def materialize(self, catalog: EventCatalog) -> EventInstance:
        """Create a symbolic EventInstance for this bounded slot."""

        event_type = catalog.resolve(self.event_type)
        values = dict(self.fields)
        for field_spec in event_type.fields:
            if field_spec.required and field_spec.name not in values:
                values[field_spec.name] = Symbol(
                    f"slot::{self.id}::field::{field_spec.name}",
                    field_spec.sort,
                )
        cycle: int | Expr = (
            self.cycle
            if self.cycle is not None
            else Symbol(f"slot::{self.id}::cycle", INT)
        )
        occurs: bool | Expr = True if self.required else Symbol(
            f"slot::{self.id}::occurs", BOOL
        )
        annotations = dict(self.annotations)
        annotations.setdefault("completion_slot", True)
        annotations.setdefault("required_slot", self.required)
        return EventInstance(
            id=self.id,
            event_type=self.event_type,
            fields=values,
            cycle=cycle,
            occurs=occurs,
            annotations=annotations,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.event_type,
            "required": self.required,
            "fields": encode_value(dict(self.fields)),
        }
        if self.cycle is not None:
            data["cycle"] = encode_value(self.cycle)
        if self.annotations:
            data["annotations"] = encode_value(dict(self.annotations))
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventSlot":
        if not isinstance(data, Mapping):
            raise SerializationError("event slot must be a mapping")
        try:
            fields = decode_value(data.get("fields", {}))
            annotations = decode_value(data.get("annotations", {}))
            if not isinstance(fields, dict):
                raise SerializationError("event slot fields must be a mapping")
            if not isinstance(annotations, dict):
                raise SerializationError("event slot annotations must be a mapping")
            return cls(
                id=str(data["id"]),
                event_type=str(data["type"]),
                fields=fields,
                required=bool(data.get("required", False)),
                cycle=decode_value(data.get("cycle")),
                annotations=annotations,
            )
        except KeyError as exc:
            raise SerializationError(
                f"event slot is missing {exc.args[0]!r}"
            ) from exc


@dataclass(slots=True)
class CompletionSpec:
    """A bounded event universe, operational rules and persistent state."""

    slots: list[EventSlot] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    state_variables: list[StateVariable] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    horizon: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.slots = list(self.slots)
        self.transformations = list(self.transformations)
        self.state_variables = list(self.state_variables)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        if self.horizon < 0:
            raise SchemaError("completion horizon must be non-negative")
        _reject_duplicates(
            [slot.id for slot in self.slots],
            "completion spec contains duplicate slot id(s)",
        )
        _reject_duplicates(
            [item.name for item in self.transformations],
            "completion spec contains duplicate transformation(s)",
        )
        _reject_duplicates(
            [item.name for item in self.state_variables],
            "completion spec contains duplicate state variable(s)",
        )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise SchemaError("completion constraints must be boolean")

    @property
    def state_map(self) -> dict[str, StateVariable]:
        return {item.name: item for item in self.state_variables}

    def validate(self, catalog: EventCatalog, trace: Trace) -> None:
        observed_ids = {event.id for event in trace.events}
        slot_ids = {slot.id for slot in self.slots}
        overlap = observed_ids & slot_ids
        if overlap:
            raise TraceValidationError(
                f"completion slots collide with trace event id(s): "
                f"{', '.join(sorted(overlap))}"
            )
        for slot in self.slots:
            slot.validate(catalog)
        for transformation in self.transformations:
            transformation.validate(catalog, self.state_map)

        event_types_by_id = {
            event.id: catalog.resolve(event.event_type) for event in trace.events
        }
        event_types_by_id.update(
            {slot.id: catalog.resolve(slot.event_type) for slot in self.slots}
        )
        for constraint in self.constraints:
            for reference in iter_event_fields(constraint):
                event_type = event_types_by_id.get(reference.event_id)
                if event_type is None:
                    raise TraceValidationError(
                        f"completion constraint references unknown event id "
                        f"{reference.event_id!r}"
                    )
                if reference.field == "cycle":
                    expected = INT
                elif reference.field == "occurs":
                    expected = BOOL
                else:
                    try:
                        expected = event_type.field_map[reference.field].sort
                    except KeyError as exc:
                        raise TraceValidationError(
                            f"completion constraint references unknown field "
                            f"{reference.event_id}.{reference.field}"
                        ) from exc
                if not reference.sort.compatible_with(expected):
                    raise TraceValidationError(
                        f"completion constraint reference "
                        f"{reference.event_id}.{reference.field} has sort "
                        f"{reference.sort}, expected {expected}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "horizon": self.horizon,
            "metadata": encode_value(self.metadata),
            "slots": [slot.to_dict() for slot in self.slots],
            "state_variables": [item.to_dict() for item in self.state_variables],
            "transformations": [item.to_dict() for item in self.transformations],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompletionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("completion spec must be a mapping")
        allowed = {
            "schema_version", "horizon", "metadata", "slots",
            "state_variables", "transformations", "constraints",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "completion spec contains unknown top-level key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_slots = data.get("slots", [])
        raw_transformations = data.get("transformations", [])
        raw_state_variables = data.get("state_variables", [])
        raw_constraints = data.get("constraints", [])
        for name, value in (
            ("slots", raw_slots),
            ("transformations", raw_transformations),
            ("state_variables", raw_state_variables),
            ("constraints", raw_constraints),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"completion {name} must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("completion metadata must be a mapping")
        return cls(
            slots=[EventSlot.from_dict(item) for item in raw_slots],
            transformations=[
                Transformation.from_dict(item) for item in raw_transformations
            ],
            state_variables=[
                StateVariable.from_dict(item) for item in raw_state_variables
            ],
            constraints=[expr_from_dict(item) for item in raw_constraints],
            horizon=int(data.get("horizon", 8)),
            metadata=metadata,
            schema_version=str(
                data.get("schema_version", COMPLETION_SCHEMA_VERSION)
            ),
        )

    @classmethod
    def load(cls, path: str | Path) -> "CompletionSpec":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


def _reject_duplicates(values: list[str], message: str) -> None:
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise SchemaError(f"{message}: {', '.join(duplicates)}")
