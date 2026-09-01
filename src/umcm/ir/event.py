"""Event schemas, catalogs, and dynamic event instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from umcm.errors import SchemaError, SerializationError, TraceValidationError
from umcm.ir.expression import Expr
from umcm.ir.sort import BOOL, INT, Sort
from umcm.serialization import decode_value, dump_data, encode_value, load_data


EVENT_CATALOG_SCHEMA_VERSION = "umcm.events.v0.1"


class Visibility(str, Enum):
    INTERNAL = "internal"
    PUBLIC = "public"
    ARCHITECTURAL = "architectural"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    sort: Sort
    required: bool = True
    identity: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("field name must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "sort": self.sort.to_dict(),
            "required": self.required,
        }
        if self.identity:
            data["identity"] = True
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldSpec":
        if not isinstance(data, Mapping):
            raise SchemaError("field spec must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                sort=Sort.from_dict(data["sort"]),
                required=bool(data.get("required", True)),
                identity=bool(data.get("identity", False)),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SchemaError(f"field spec is missing {exc.args[0]!r}") from exc


@dataclass(frozen=True, slots=True)
class EventType:
    name: str
    module: str
    layer: str
    fields: tuple[FieldSpec, ...] = ()
    visibility: Visibility = Visibility.INTERNAL
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise SchemaError(
                "event type name must be qualified, for example 'LSU.TLBMiss'"
            )
        if not self.module:
            raise SchemaError("event type module must be non-empty")
        if not self.layer:
            raise SchemaError("event type layer must be non-empty")
        names = [item.name for item in self.fields]
        if len(names) != len(set(names)):
            raise SchemaError(f"event type {self.name!r} has duplicate fields")

    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {item.name: item for item in self.fields}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "module": self.module,
            "layer": self.layer,
            "visibility": self.visibility.value,
            "fields": [item.to_dict() for item in self.fields],
        }
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventType":
        if not isinstance(data, Mapping):
            raise SchemaError("event type must be a mapping")
        try:
            raw_fields = data.get("fields", [])
            if not isinstance(raw_fields, list):
                raise SchemaError("event type fields must be a list")
            return cls(
                name=str(data["name"]),
                module=str(data["module"]),
                layer=str(data["layer"]),
                fields=tuple(FieldSpec.from_dict(item) for item in raw_fields),
                visibility=Visibility(str(data.get("visibility", "internal"))),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SchemaError(f"event type is missing {exc.args[0]!r}") from exc
        except ValueError as exc:
            raise SchemaError(str(exc)) from exc


@dataclass(slots=True)
class EventInstance:
    id: str
    event_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    cycle: int | Expr | None = None
    occurs: bool | Expr = True
    annotations: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise TraceValidationError("event id must be non-empty")
        if not self.event_type:
            raise TraceValidationError("event_type must be non-empty")
        self.fields = dict(self.fields)
        self.annotations = dict(self.annotations)
        self._validate_common_attributes()

    def _validate_common_attributes(self) -> None:
        if isinstance(self.cycle, int):
            if isinstance(self.cycle, bool) or self.cycle < 0:
                raise TraceValidationError("event cycle must be a non-negative int")
        elif isinstance(self.cycle, Expr):
            if not self.cycle.sort.compatible_with(INT):
                raise TraceValidationError("symbolic event cycle must have int sort")
        elif self.cycle is not None:
            raise TraceValidationError("event cycle must be int, Expr, or null")

        if isinstance(self.occurs, Expr):
            if not self.occurs.sort.compatible_with(BOOL):
                raise TraceValidationError("symbolic occurs must have bool sort")
        elif not isinstance(self.occurs, bool):
            raise TraceValidationError("occurs must be bool or Expr")

    def validate_against(self, event_type: EventType, *, partial: bool) -> None:
        if self.event_type != event_type.name:
            raise TraceValidationError(
                f"event {self.id!r} has type {self.event_type!r}, expected {event_type.name!r}"
            )

        specs = event_type.field_map
        unknown = set(self.fields) - set(specs)
        if unknown:
            raise TraceValidationError(
                f"event {self.id!r} has unknown field(s): {', '.join(sorted(unknown))}"
            )

        if not partial:
            missing = [
                spec.name
                for spec in event_type.fields
                if spec.required and spec.name not in self.fields
            ]
            if missing:
                raise TraceValidationError(
                    f"event {self.id!r} is missing required field(s): {', '.join(missing)}"
                )

        for name, value in self.fields.items():
            spec = specs[name]
            if isinstance(value, Expr):
                if not value.sort.compatible_with(spec.sort):
                    raise TraceValidationError(
                        f"event {self.id!r}.{name} expects {spec.sort}, got {value.sort}"
                    )
            elif not spec.sort.accepts_literal(value):
                raise TraceValidationError(
                    f"event {self.id!r}.{name} value {value!r} is invalid for {spec.sort}"
                )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.event_type,
            "occurs": encode_value(self.occurs),
            "fields": encode_value(self.fields),
        }
        if self.cycle is not None:
            data["cycle"] = encode_value(self.cycle)
        if self.annotations:
            data["annotations"] = encode_value(self.annotations)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventInstance":
        if not isinstance(data, Mapping):
            raise SerializationError("event instance must be a mapping")
        try:
            fields = decode_value(data.get("fields", {}))
            annotations = decode_value(data.get("annotations", {}))
            if not isinstance(fields, dict):
                raise SerializationError("event fields must be a mapping")
            if not isinstance(annotations, dict):
                raise SerializationError("event annotations must be a mapping")
            return cls(
                id=str(data["id"]),
                event_type=str(data["type"]),
                fields=fields,
                cycle=decode_value(data.get("cycle")),
                occurs=decode_value(data.get("occurs", True)),
                annotations=annotations,
            )
        except KeyError as exc:
            raise SerializationError(f"event instance is missing {exc.args[0]!r}") from exc


@dataclass(slots=True)
class EventCatalog:
    event_types: dict[str, EventType] = field(default_factory=dict)
    schema_version: str = EVENT_CATALOG_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.event_types = dict(self.event_types)
        self.metadata = dict(self.metadata)
        for name, event_type in self.event_types.items():
            if name != event_type.name:
                raise SchemaError(
                    f"catalog key {name!r} does not match event type name {event_type.name!r}"
                )

    def register(self, event_type: EventType) -> None:
        if event_type.name in self.event_types:
            raise SchemaError(f"duplicate event type: {event_type.name}")
        self.event_types[event_type.name] = event_type

    def resolve(self, name: str) -> EventType:
        try:
            return self.event_types[name]
        except KeyError as exc:
            raise TraceValidationError(f"unknown event type: {name}") from exc

    def validate_events(self, events: Iterable[EventInstance], *, partial: bool) -> None:
        for event in events:
            event.validate_against(self.resolve(event.event_type), partial=partial)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "metadata": encode_value(self.metadata),
            "events": [
                self.event_types[name].to_dict()
                for name in sorted(self.event_types)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventCatalog":
        if not isinstance(data, Mapping):
            raise SerializationError("event catalog must be a mapping")
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            raise SerializationError("event catalog events must be a list")
        event_types: dict[str, EventType] = {}
        for item in raw_events:
            event_type = EventType.from_dict(item)
            if event_type.name in event_types:
                raise SchemaError(f"duplicate event type: {event_type.name}")
            event_types[event_type.name] = event_type
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("event catalog metadata must be a mapping")
        return cls(
            event_types=event_types,
            schema_version=str(data.get("schema_version", EVENT_CATALOG_SCHEMA_VERSION)),
            metadata=metadata,
        )

    @classmethod
    def load(cls, path: str | Path) -> "EventCatalog":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
