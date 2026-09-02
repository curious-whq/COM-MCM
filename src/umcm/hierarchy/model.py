"""Loadable hierarchy and trace-abstraction specifications.

The abstraction language is intentionally small.  A rule matches one or more
concrete events, unifies selected fields through ``$variables``, and emits one
summary event.  The result is itself a normal :class:`~umcm.ir.trace.Trace`, so
several abstraction levels can be applied in sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import AbstractionError, SerializationError
from umcm.serialization import decode_value, dump_data, encode_value, load_data


ABSTRACTION_SCHEMA_VERSION = "umcm.abstraction.v0.1"


def _unknown_keys(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise SerializationError(
            f"{context} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


@dataclass(frozen=True, slots=True)
class MatchValue:
    """A role-field pattern: either a unification variable or a literal."""

    variable: str | None = None
    literal: Any = None
    is_literal: bool = False

    def __post_init__(self) -> None:
        if self.variable is not None:
            if not self.variable:
                raise AbstractionError("abstraction variable must be non-empty")
            if self.is_literal:
                raise AbstractionError("match value cannot be variable and literal")
        elif not self.is_literal:
            raise AbstractionError("match value must be variable or literal")

    @classmethod
    def from_data(cls, data: Any) -> "MatchValue":
        if isinstance(data, str) and data.startswith("$"):
            return cls(variable=data[1:])
        if isinstance(data, Mapping):
            if set(data) != {"literal"}:
                raise SerializationError(
                    "abstraction match mapping must contain only 'literal'"
                )
            return cls(literal=decode_value(data["literal"]), is_literal=True)
        return cls(literal=decode_value(data), is_literal=True)

    def to_data(self) -> Any:
        if self.variable is not None:
            return f"${self.variable}"
        if isinstance(self.literal, str) and self.literal.startswith("$"):
            return {"literal": encode_value(self.literal)}
        return encode_value(self.literal)


@dataclass(frozen=True, slots=True)
class OutputValue:
    """A summary-field value drawn from a binding, role field, or literal."""

    kind: str
    value: Any

    def __post_init__(self) -> None:
        if self.kind not in {"variable", "field", "literal"}:
            raise AbstractionError(f"unsupported output value kind: {self.kind}")
        if self.kind in {"variable", "field"} and not str(self.value):
            raise AbstractionError(f"{self.kind} output reference must be non-empty")

    @classmethod
    def from_data(cls, data: Any) -> "OutputValue":
        if isinstance(data, str) and data.startswith("$"):
            return cls("variable", data[1:])
        if isinstance(data, Mapping):
            if set(data) == {"from"}:
                return cls("field", str(data["from"]))
            if set(data) == {"literal"}:
                return cls("literal", decode_value(data["literal"]))
            raise SerializationError(
                "abstraction output mapping must contain exactly 'from' or 'literal'"
            )
        return cls("literal", decode_value(data))

    def to_data(self) -> Any:
        if self.kind == "variable":
            return f"${self.value}"
        if self.kind == "field":
            return {"from": self.value}
        if isinstance(self.value, str) and self.value.startswith("$"):
            return {"literal": encode_value(self.value)}
        return encode_value(self.value)


@dataclass(frozen=True, slots=True)
class EventRoleSpec:
    name: str
    event_type: str
    fields: Mapping[str, MatchValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("abstraction role name must be non-empty")
        if not self.event_type:
            raise AbstractionError("abstraction role event_type must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRoleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("abstraction role must be a mapping")
        _unknown_keys(data, {"name", "event_type", "fields"}, "abstraction role")
        raw_fields = data.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            raise SerializationError("abstraction role fields must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                event_type=str(data["event_type"]),
                fields={
                    str(name): MatchValue.from_data(value)
                    for name, value in raw_fields.items()
                },
            )
        except KeyError as exc:
            raise SerializationError(
                f"abstraction role is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event_type": self.event_type,
            "fields": {
                name: value.to_data() for name, value in self.fields.items()
            },
        }


@dataclass(frozen=True, slots=True)
class SummaryEventSpec:
    event_type: str
    id_template: str
    fields: Mapping[str, OutputValue]
    cycle_from: str = "last"
    annotations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type:
            raise AbstractionError("summary event_type must be non-empty")
        if not self.id_template:
            raise AbstractionError("summary id_template must be non-empty")
        if not self.cycle_from:
            raise AbstractionError("summary cycle_from must be non-empty")
        object.__setattr__(self, "fields", dict(self.fields))
        object.__setattr__(self, "annotations", dict(self.annotations))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SummaryEventSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("summary output must be a mapping")
        _unknown_keys(
            data,
            {"event_type", "id", "fields", "cycle_from", "annotations"},
            "summary output",
        )
        raw_fields = data.get("fields", {})
        raw_annotations = decode_value(data.get("annotations", {}))
        if not isinstance(raw_fields, Mapping):
            raise SerializationError("summary output fields must be a mapping")
        if not isinstance(raw_annotations, Mapping):
            raise SerializationError("summary output annotations must be a mapping")
        try:
            return cls(
                event_type=str(data["event_type"]),
                id_template=str(data["id"]),
                fields={
                    str(name): OutputValue.from_data(value)
                    for name, value in raw_fields.items()
                },
                cycle_from=str(data.get("cycle_from", "last")),
                annotations=dict(raw_annotations),
            )
        except KeyError as exc:
            raise SerializationError(
                f"summary output is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "event_type": self.event_type,
            "id": self.id_template,
            "cycle_from": self.cycle_from,
            "fields": {
                name: value.to_data() for name, value in self.fields.items()
            },
        }
        if self.annotations:
            data["annotations"] = encode_value(dict(self.annotations))
        return data


@dataclass(frozen=True, slots=True)
class SummaryRuleSpec:
    name: str
    roles: tuple[EventRoleSpec, ...]
    output: SummaryEventSpec
    ordered: bool = True
    strict_order: bool = False
    distinct_events: bool = True
    hide_sources: bool = True
    min_matches: int = 0
    max_matches: int = 10_000

    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("summary rule name must be non-empty")
        if not self.roles:
            raise AbstractionError(f"summary rule {self.name!r} needs at least one role")
        names = [role.name for role in self.roles]
        if len(names) != len(set(names)):
            raise AbstractionError(f"summary rule {self.name!r} has duplicate roles")
        if self.min_matches < 0:
            raise AbstractionError("summary min_matches cannot be negative")
        if self.max_matches <= 0 or self.max_matches < self.min_matches:
            raise AbstractionError("summary max_matches is invalid")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SummaryRuleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("summary rule must be a mapping")
        _unknown_keys(
            data,
            {
                "name",
                "roles",
                "output",
                "ordered",
                "strict_order",
                "distinct_events",
                "hide_sources",
                "min_matches",
                "max_matches",
            },
            "summary rule",
        )
        raw_roles = data.get("roles", [])
        if not isinstance(raw_roles, list):
            raise SerializationError("summary rule roles must be a list")
        try:
            return cls(
                name=str(data["name"]),
                roles=tuple(EventRoleSpec.from_dict(item) for item in raw_roles),
                output=SummaryEventSpec.from_dict(data["output"]),
                ordered=bool(data.get("ordered", True)),
                strict_order=bool(data.get("strict_order", False)),
                distinct_events=bool(data.get("distinct_events", True)),
                hide_sources=bool(data.get("hide_sources", True)),
                min_matches=int(data.get("min_matches", 0)),
                max_matches=int(data.get("max_matches", 10_000)),
            )
        except KeyError as exc:
            raise SerializationError(
                f"summary rule is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": [role.to_dict() for role in self.roles],
            "output": self.output.to_dict(),
            "ordered": self.ordered,
            "strict_order": self.strict_order,
            "distinct_events": self.distinct_events,
            "hide_sources": self.hide_sources,
            "min_matches": self.min_matches,
            "max_matches": self.max_matches,
        }


@dataclass(frozen=True, slots=True)
class RetainSpec:
    event_types: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    visibilities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RetainSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("retain must be a mapping")
        _unknown_keys(data, {"event_types", "event_ids", "visibilities"}, "retain")
        for field_name in ("event_types", "event_ids", "visibilities"):
            if not isinstance(data.get(field_name, []), list):
                raise SerializationError(f"retain.{field_name} must be a list")
        return cls(
            event_types=tuple(str(item) for item in data.get("event_types", [])),
            event_ids=tuple(str(item) for item in data.get("event_ids", [])),
            visibilities=tuple(str(item) for item in data.get("visibilities", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": list(self.event_types),
            "event_ids": list(self.event_ids),
            "visibilities": list(self.visibilities),
        }


@dataclass(slots=True)
class AbstractionSpec:
    name: str
    source_level: str
    target_level: str
    retain: RetainSpec = field(default_factory=RetainSpec)
    summaries: tuple[SummaryRuleSpec, ...] = ()
    default_action: str = "hide"
    retain_metadata: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = ABSTRACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.name:
            raise AbstractionError("abstraction name must be non-empty")
        if not self.source_level or not self.target_level:
            raise AbstractionError("source_level and target_level must be non-empty")
        if self.default_action not in {"hide", "keep"}:
            raise AbstractionError("default_action must be 'hide' or 'keep'")
        names = [rule.name for rule in self.summaries]
        if len(names) != len(set(names)):
            raise AbstractionError("duplicate abstraction summary rule name")
        self.metadata = dict(self.metadata)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbstractionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("abstraction spec must be a mapping")
        _unknown_keys(
            data,
            {
                "schema_version",
                "name",
                "source_level",
                "target_level",
                "default_action",
                "retain",
                "retain_metadata",
                "summaries",
                "metadata",
            },
            "abstraction spec",
        )
        raw_summaries = data.get("summaries", [])
        raw_retain_metadata = data.get("retain_metadata", [])
        raw_metadata = decode_value(data.get("metadata", {}))
        if not isinstance(raw_summaries, list):
            raise SerializationError("abstraction summaries must be a list")
        if not isinstance(raw_retain_metadata, list):
            raise SerializationError("retain_metadata must be a list")
        if not isinstance(raw_metadata, Mapping):
            raise SerializationError("abstraction metadata must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                source_level=str(data["source_level"]),
                target_level=str(data["target_level"]),
                retain=RetainSpec.from_dict(data.get("retain", {})),
                summaries=tuple(
                    SummaryRuleSpec.from_dict(item) for item in raw_summaries
                ),
                default_action=str(data.get("default_action", "hide")),
                retain_metadata=tuple(str(item) for item in raw_retain_metadata),
                metadata=dict(raw_metadata),
                schema_version=str(
                    data.get("schema_version", ABSTRACTION_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"abstraction spec is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "source_level": self.source_level,
            "target_level": self.target_level,
            "default_action": self.default_action,
            "retain": self.retain.to_dict(),
            "retain_metadata": list(self.retain_metadata),
            "summaries": [rule.to_dict() for rule in self.summaries],
            "metadata": encode_value(dict(self.metadata)),
        }

    @classmethod
    def load(cls, path: str | Path) -> "AbstractionSpec":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
