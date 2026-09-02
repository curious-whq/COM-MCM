"""Serializable module and composition models for operational µMCM fragments.

A :class:`ModuleSpec` owns a bounded set of event slots, state variables, and
operational transformations.  It also declares typed event ports.  A
:class:`CompositionSpec` loads several modules and connects their ports.

Two connection modes are supported:

``shared_event``
    Both modules observe the same event instance.  This is appropriate for one
    physical boundary action, such as an accepted ready/valid request.

``event_map``
    The source and target use distinct event types.  Composition generates an
    exact operational transformation that copies selected fields and, by
    default, the cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import CompositionError, SchemaError, SerializationError
from umcm.ir.completion import EventSlot
from umcm.ir.event import EventCatalog
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict
from umcm.ir.state import StateVariable
from umcm.ir.transformation import Transformation
from umcm.composition.parameterization import TraceRoleSpec
from umcm.serialization import decode_value, dump_data, encode_value, load_data


MODULE_SCHEMA_VERSION = "umcm.module.v0.13.0"
COMPOSITION_SCHEMA_VERSION = "umcm.composition.v0.13.0"


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class ConnectionMode(str, Enum):
    SHARED_EVENT = "shared_event"
    EVENT_MAP = "event_map"


@dataclass(frozen=True, slots=True)
class ModulePort:
    """One typed module boundary port."""

    name: str
    direction: PortDirection
    event_type: str
    required_connection: bool = False
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("module port name must be non-empty")
        if not self.event_type:
            raise SchemaError("module port event_type must be non-empty")

    def validate(self, catalog: EventCatalog) -> None:
        catalog.resolve(self.event_type)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "direction": self.direction.value,
            "event_type": self.event_type,
            "required_connection": self.required_connection,
        }
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModulePort":
        if not isinstance(data, Mapping):
            raise SerializationError("module port must be a mapping")
        allowed = {
            "name", "direction", "event_type", "required_connection",
            "description", "tags",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "module port contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        try:
            direction = PortDirection(str(data["direction"]))
            default_required = direction is PortDirection.INPUT
            return cls(
                name=str(data["name"]),
                direction=direction,
                event_type=str(data["event_type"]),
                required_connection=bool(
                    data.get("required_connection", default_required)
                ),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SerializationError(
                f"module port is missing {exc.args[0]!r}"
            ) from exc
        except ValueError as exc:
            raise SerializationError(str(exc)) from exc


@dataclass(slots=True)
class ModuleSpec:
    """One independently loadable operational model fragment."""

    name: str
    ports: list[ModulePort] = field(default_factory=list)
    slots: list[EventSlot] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    state_variables: list[StateVariable] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = MODULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("module name must be non-empty")
        self.ports = list(self.ports)
        self.slots = list(self.slots)
        self.transformations = list(self.transformations)
        self.state_variables = list(self.state_variables)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        _reject_duplicates(
            [port.name for port in self.ports],
            f"module {self.name!r} contains duplicate port(s)",
        )
        _reject_duplicates(
            [slot.id for slot in self.slots],
            f"module {self.name!r} contains duplicate slot id(s)",
        )
        _reject_duplicates(
            [item.name for item in self.transformations],
            f"module {self.name!r} contains duplicate transformation(s)",
        )
        _reject_duplicates(
            [item.name for item in self.state_variables],
            f"module {self.name!r} contains duplicate state variable(s)",
        )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise SchemaError(
                    f"module {self.name!r} constraints must be boolean"
                )

    @property
    def port_map(self) -> dict[str, ModulePort]:
        return {port.name: port for port in self.ports}

    @property
    def state_map(self) -> dict[str, StateVariable]:
        return {item.name: item for item in self.state_variables}

    def validate(self, catalog: EventCatalog) -> None:
        for port in self.ports:
            port.validate(catalog)
        for slot in self.slots:
            slot.validate(catalog)

        # Every event type used by a transformation must be part of the
        # module's declared surface: either a bounded local slot or a typed
        # interface port.  Without this check a module could silently depend
        # on another module's event type while bypassing CompositionSpec.
        declared_event_types = {port.event_type for port in self.ports}
        declared_event_types.update(slot.event_type for slot in self.slots)

        # State ownership is local: a module transformation may only access
        # state variables declared by that same module.
        for transformation in self.transformations:
            referenced_event_types = {
                role.event_type
                for role in (*transformation.inputs, *transformation.outputs)
            }
            undeclared = referenced_event_types - declared_event_types
            if undeclared:
                raise SchemaError(
                    f"module {self.name!r} transformation "
                    f"{transformation.name!r} references event type(s) not "
                    "declared by a slot or port: "
                    + ", ".join(sorted(undeclared))
                )
            transformation.validate(catalog, self.state_map)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "metadata": encode_value(self.metadata),
            "ports": [port.to_dict() for port in self.ports],
            "slots": [slot.to_dict() for slot in self.slots],
            "state_variables": [
                item.to_dict() for item in self.state_variables
            ],
            "transformations": [
                item.to_dict() for item in self.transformations
            ],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModuleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("module spec must be a mapping")
        allowed = {
            "schema_version", "name", "metadata", "ports", "slots",
            "state_variables", "transformations", "constraints",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "module spec contains unknown top-level key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_ports = data.get("ports", [])
        raw_slots = data.get("slots", [])
        raw_states = data.get("state_variables", [])
        raw_transformations = data.get("transformations", [])
        raw_constraints = data.get("constraints", [])
        for label, value in (
            ("ports", raw_ports),
            ("slots", raw_slots),
            ("state_variables", raw_states),
            ("transformations", raw_transformations),
            ("constraints", raw_constraints),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"module {label} must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("module metadata must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                ports=[ModulePort.from_dict(item) for item in raw_ports],
                slots=[EventSlot.from_dict(item) for item in raw_slots],
                state_variables=[
                    StateVariable.from_dict(item) for item in raw_states
                ],
                transformations=[
                    Transformation.from_dict(item)
                    for item in raw_transformations
                ],
                constraints=[expr_from_dict(item) for item in raw_constraints],
                metadata=metadata,
                schema_version=str(
                    data.get("schema_version", MODULE_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"module spec is missing {exc.args[0]!r}"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> "ModuleSpec":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


@dataclass(frozen=True, slots=True)
class ModuleReference:
    name: str
    path: str

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("module reference name must be non-empty")
        if not self.path:
            raise SchemaError("module reference path must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModuleReference":
        if not isinstance(data, Mapping):
            raise SerializationError("module reference must be a mapping")
        try:
            return cls(name=str(data["name"]), path=str(data["path"]))
        except KeyError as exc:
            raise SerializationError(
                f"module reference is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class PortEndpoint:
    module: str
    port: str

    def __post_init__(self) -> None:
        if not self.module or not self.port:
            raise SchemaError("connection endpoint module and port are required")

    def to_dict(self) -> dict[str, str]:
        return {"module": self.module, "port": self.port}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortEndpoint":
        if not isinstance(data, Mapping):
            raise SerializationError("connection endpoint must be a mapping")
        try:
            return cls(module=str(data["module"]), port=str(data["port"]))
        except KeyError as exc:
            raise SerializationError(
                f"connection endpoint is missing {exc.args[0]!r}"
            ) from exc

    @property
    def qualified_name(self) -> str:
        return f"{self.module}.{self.port}"


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    """One directed interface connection between module ports."""

    name: str
    source: PortEndpoint
    target: PortEndpoint
    mode: ConnectionMode = ConnectionMode.SHARED_EVENT
    field_map: Mapping[str, str] = field(default_factory=dict)
    same_cycle: bool = True
    exact: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("connection name must be non-empty")
        object.__setattr__(self, "field_map", dict(self.field_map))
        if self.source == self.target:
            raise SchemaError("connection source and target must differ")
        if self.mode is ConnectionMode.SHARED_EVENT and self.field_map:
            raise SchemaError(
                f"shared_event connection {self.name!r} cannot have field_map"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "mode": self.mode.value,
            "same_cycle": self.same_cycle,
            "exact": self.exact,
        }
        if self.field_map:
            data["field_map"] = dict(self.field_map)
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConnectionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("connection must be a mapping")
        allowed = {
            "name", "source", "target", "mode", "field_map",
            "same_cycle", "exact", "description",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "connection contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        field_map = data.get("field_map", {})
        if not isinstance(field_map, Mapping):
            raise SerializationError("connection field_map must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                source=PortEndpoint.from_dict(data["source"]),
                target=PortEndpoint.from_dict(data["target"]),
                mode=ConnectionMode(
                    str(data.get("mode", ConnectionMode.SHARED_EVENT.value))
                ),
                # Keys are target fields and values are source fields.
                field_map={str(k): str(v) for k, v in field_map.items()},
                same_cycle=bool(data.get("same_cycle", True)),
                exact=bool(data.get("exact", True)),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"connection is missing {exc.args[0]!r}"
            ) from exc
        except ValueError as exc:
            raise SerializationError(str(exc)) from exc


@dataclass(slots=True)
class CompositionSpec:
    """A set of module files plus explicit interface connections."""

    name: str
    modules: list[ModuleReference]
    connections: list[ConnectionSpec] = field(default_factory=list)
    roles: list[TraceRoleSpec] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)
    horizon: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = COMPOSITION_SCHEMA_VERSION
    source_path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("composition name must be non-empty")
        self.modules = list(self.modules)
        self.connections = list(self.connections)
        self.roles = list(self.roles)
        self.constraints = list(self.constraints)
        self.metadata = dict(self.metadata)
        if self.horizon < 0:
            raise SchemaError("composition horizon must be non-negative")
        _reject_duplicates(
            [module.name for module in self.modules],
            "composition contains duplicate module reference(s)",
        )
        _reject_duplicates(
            [connection.name for connection in self.connections],
            "composition contains duplicate connection(s)",
        )
        _reject_duplicates(
            [role.name for role in self.roles],
            "composition contains duplicate trace role(s)",
        )
        for constraint in self.constraints:
            if not constraint.sort.is_bool:
                raise SchemaError("composition constraints must be boolean")

    @property
    def base_dir(self) -> Path:
        if self.source_path is None:
            return Path.cwd()
        return self.source_path.parent

    def resolve_module_path(self, reference: ModuleReference) -> Path:
        path = Path(reference.path)
        return path if path.is_absolute() else self.base_dir / path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "horizon": self.horizon,
            "metadata": encode_value(self.metadata),
            "modules": [module.to_dict() for module in self.modules],
            "connections": [item.to_dict() for item in self.connections],
            "roles": [item.to_dict() for item in self.roles],
            "constraints": [expr_to_dict(item) for item in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompositionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("composition spec must be a mapping")
        allowed = {
            "schema_version", "name", "horizon", "metadata", "modules",
            "connections", "roles", "constraints",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "composition spec contains unknown top-level key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_modules = data.get("modules", [])
        raw_connections = data.get("connections", [])
        raw_roles = data.get("roles", [])
        raw_constraints = data.get("constraints", [])
        for label, value in (
            ("modules", raw_modules),
            ("connections", raw_connections),
            ("roles", raw_roles),
            ("constraints", raw_constraints),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"composition {label} must be a list")
        metadata = decode_value(data.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise SerializationError("composition metadata must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                modules=[ModuleReference.from_dict(item) for item in raw_modules],
                connections=[
                    ConnectionSpec.from_dict(item) for item in raw_connections
                ],
                roles=[TraceRoleSpec.from_dict(item) for item in raw_roles],
                constraints=[expr_from_dict(item) for item in raw_constraints],
                horizon=int(data.get("horizon", 8)),
                metadata=metadata,
                schema_version=str(
                    data.get("schema_version", COMPOSITION_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"composition spec is missing {exc.args[0]!r}"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> "CompositionSpec":
        source = Path(path).resolve()
        spec = cls.from_dict(load_data(source))
        spec.source_path = source
        return spec

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)


def _reject_duplicates(values: list[str], message: str) -> None:
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise CompositionError(f"{message}: {', '.join(duplicates)}")
