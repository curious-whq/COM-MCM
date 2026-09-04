"""Serializable v0.20 two-level hierarchical-search specification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SearchError, SerializationError
from umcm.serialization import load_data


SEARCH_SCHEMA_VERSION = "umcm.search.v0.20.0"
_KINDS = {"load", "store"}
_STAGE_KINDS = {"coherence_access", "interface_gap"}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SerializationError(f"{label} must be a mapping")
    return value


def _domain(value: Any, label: str) -> tuple[Any, ...]:
    items = value if isinstance(value, list) else [value]
    if not items:
        raise SearchError(f"{label} must not be empty")
    return tuple(items)


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SerializationError(f"{label} must be a list")
    return tuple(str(item) for item in value)


@dataclass(frozen=True, slots=True)
class SearchBounds:
    harts: int
    memory_ops: int
    addresses: int
    values: int
    max_assignments: int = 10_000
    max_graph_candidates: int = 10_000

    def __post_init__(self) -> None:
        for name in (
            "harts", "memory_ops", "addresses", "values",
            "max_assignments", "max_graph_candidates",
        ):
            if getattr(self, name) <= 0:
                raise SearchError(f"search bound {name} must be positive")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchBounds":
        data = _mapping(data, "search bounds")
        try:
            return cls(
                harts=int(data["harts"]),
                memory_ops=int(data["memory_ops"]),
                addresses=int(data["addresses"]),
                values=int(data["values"]),
                max_assignments=int(data.get("max_assignments", 10_000)),
                max_graph_candidates=int(data.get("max_graph_candidates", 10_000)),
            )
        except KeyError as exc:
            raise SerializationError(
                f"search bounds are missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, int]:
        return {
            "harts": self.harts,
            "memory_ops": self.memory_ops,
            "addresses": self.addresses,
            "values": self.values,
            "max_assignments": self.max_assignments,
            "max_graph_candidates": self.max_graph_candidates,
        }


@dataclass(frozen=True, slots=True)
class InitWriteSpec:
    id: str
    address: Any
    value: Any

    def __post_init__(self) -> None:
        if not self.id:
            raise SearchError("initial write id must be non-empty")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitWriteSpec":
        data = _mapping(data, "initial write")
        try:
            return cls(str(data["id"]), data["address"], data["value"])
        except KeyError as exc:
            raise SerializationError(
                f"initial write is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "address": self.address, "value": self.value}


@dataclass(frozen=True, slots=True)
class OperationSlotSpec:
    id: str
    kinds: tuple[str, ...]
    harts: tuple[int, ...]
    program_indexes: tuple[int, ...]
    addresses: tuple[Any, ...]
    values: tuple[Any, ...]
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise SearchError("operation slot id must be non-empty")
        unknown = set(self.kinds) - _KINDS
        if unknown:
            raise SearchError(
                f"operation slot {self.id!r} has unsupported kind(s): "
                + ", ".join(sorted(unknown))
            )
        if any(hart < 0 for hart in self.harts):
            raise SearchError(f"operation slot {self.id!r} has a negative hart")
        if any(index < 0 for index in self.program_indexes):
            raise SearchError(
                f"operation slot {self.id!r} has a negative program_index"
            )
        object.__setattr__(self, "fields", dict(self.fields))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperationSlotSpec":
        data = _mapping(data, "operation slot")
        try:
            fields = data.get("fields", {})
            if not isinstance(fields, Mapping):
                raise SerializationError("operation slot fields must be a mapping")
            return cls(
                id=str(data["id"]),
                kinds=tuple(str(item) for item in _domain(data["kind"], "kind")),
                harts=tuple(int(item) for item in _domain(data["hart"], "hart")),
                program_indexes=tuple(
                    int(item)
                    for item in _domain(data["program_index"], "program_index")
                ),
                addresses=_domain(data["address"], "address"),
                values=_domain(data["value"], "value"),
                fields=dict(fields),
            )
        except KeyError as exc:
            raise SerializationError(
                f"operation slot is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": list(self.kinds),
            "hart": list(self.harts),
            "program_index": list(self.program_indexes),
            "address": list(self.addresses),
            "value": list(self.values),
            "fields": dict(self.fields),
        }


@dataclass(frozen=True, slots=True)
class ArchitectureEventMap:
    init_write: str
    load: str
    store: str
    commit_read: str
    defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArchitectureEventMap":
        data = _mapping(data, "architecture event map")
        raw_defaults = data.get("defaults", {})
        if not isinstance(raw_defaults, Mapping):
            raise SerializationError("architecture event defaults must be a mapping")
        defaults: dict[str, dict[str, Any]] = {}
        for key, value in raw_defaults.items():
            if not isinstance(value, Mapping):
                raise SerializationError(
                    f"architecture defaults for {key!r} must be a mapping"
                )
            defaults[str(key)] = dict(value)
        try:
            return cls(
                init_write=str(data["init_write"]),
                load=str(data["load"]),
                store=str(data["store"]),
                commit_read=str(data["commit_read"]),
                defaults=defaults,
            )
        except KeyError as exc:
            raise SerializationError(
                f"architecture event map is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "init_write": self.init_write,
            "load": self.load,
            "store": self.store,
            "commit_read": self.commit_read,
            "defaults": {key: dict(value) for key, value in self.defaults.items()},
        }


@dataclass(frozen=True, slots=True)
class ArchitectureSearchSpec:
    model: str
    target: str
    events: ArchitectureEventMap
    init_writes: tuple[InitWriteSpec, ...]
    operations: tuple[OperationSlotSpec, ...]

    def __post_init__(self) -> None:
        if self.target not in {"allowed", "forbidden"}:
            raise SearchError("architecture target must be allowed or forbidden")
        ids = [item.id for item in (*self.init_writes, *self.operations)]
        if len(ids) != len(set(ids)):
            raise SearchError("architecture search operation ids must be unique")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArchitectureSearchSpec":
        data = _mapping(data, "architecture search")
        raw_init = data.get("init_writes", [])
        raw_ops = data.get("operations", [])
        if not isinstance(raw_init, list) or not isinstance(raw_ops, list):
            raise SerializationError(
                "architecture init_writes and operations must be lists"
            )
        try:
            result = cls(
                model=str(data["model"]),
                target=str(data.get("target", "forbidden")),
                events=ArchitectureEventMap.from_dict(data["events"]),
                init_writes=tuple(InitWriteSpec.from_dict(item) for item in raw_init),
                operations=tuple(OperationSlotSpec.from_dict(item) for item in raw_ops),
            )
        except KeyError as exc:
            raise SerializationError(
                f"architecture search is missing {exc.args[0]!r}"
            ) from exc
        if not result.init_writes or not result.operations:
            raise SearchError(
                "architecture search requires initial writes and operation slots"
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "target": self.target,
            "events": self.events.to_dict(),
            "init_writes": [item.to_dict() for item in self.init_writes],
            "operations": [item.to_dict() for item in self.operations],
        }


@dataclass(frozen=True, slots=True)
class RealizationStageSpec:
    name: str
    kind: str
    required: bool = True
    catalog: str | None = None
    composition: str | None = None
    input_event_types: tuple[str, ...] = ()
    event_types: Mapping[str, str] = field(default_factory=dict)
    cycle_start: int = 1
    cycle_stride: int = 9
    max_schedules: int = 24
    reason: str = ""
    missing_interfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SearchError("realization stage name must be non-empty")
        if self.kind not in _STAGE_KINDS:
            raise SearchError(
                f"realization stage {self.name!r} has unsupported kind {self.kind!r}"
            )
        object.__setattr__(self, "event_types", dict(self.event_types))
        if self.kind == "coherence_access":
            if not self.catalog or not self.composition:
                raise SearchError(
                    f"coherence stage {self.name!r} requires catalog and composition"
                )
            required_names = {
                "line_init", "access", "load_result", "store_result"
            }
            missing = required_names - set(self.event_types)
            if missing:
                raise SearchError(
                    f"coherence stage {self.name!r} event_types missing: "
                    + ", ".join(sorted(missing))
                )
            if self.cycle_start < 0 or self.cycle_stride <= 0:
                raise SearchError("coherence stage cycles must be non-negative")
            if self.max_schedules <= 0:
                raise SearchError("coherence stage max_schedules must be positive")
        elif not self.reason:
            raise SearchError(
                f"interface-gap stage {self.name!r} requires an explicit reason"
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RealizationStageSpec":
        data = _mapping(data, "realization stage")
        raw_events = data.get("event_types", {})
        if not isinstance(raw_events, Mapping):
            raise SerializationError("realization stage event_types must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                required=bool(data.get("required", True)),
                catalog=None if data.get("catalog") is None else str(data["catalog"]),
                composition=(
                    None
                    if data.get("composition") is None
                    else str(data["composition"])
                ),
                input_event_types=_strings(
                    data.get("input_event_types", []),
                    "realization stage input_event_types",
                ),
                event_types={str(k): str(v) for k, v in raw_events.items()},
                cycle_start=int(data.get("cycle_start", 1)),
                cycle_stride=int(data.get("cycle_stride", 9)),
                max_schedules=int(data.get("max_schedules", 24)),
                reason=str(data.get("reason", "")),
                missing_interfaces=_strings(
                    data.get("missing_interfaces", []),
                    "realization stage missing_interfaces",
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"realization stage is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
        }
        if self.catalog is not None:
            data["catalog"] = self.catalog
        if self.composition is not None:
            data["composition"] = self.composition
        if self.input_event_types:
            data["input_event_types"] = list(self.input_event_types)
        if self.event_types:
            data["event_types"] = dict(self.event_types)
        if self.kind == "coherence_access":
            data.update(
                cycle_start=self.cycle_start,
                cycle_stride=self.cycle_stride,
                max_schedules=self.max_schedules,
            )
        if self.reason:
            data["reason"] = self.reason
        if self.missing_interfaces:
            data["missing_interfaces"] = list(self.missing_interfaces)
        return data


@dataclass(slots=True)
class HierarchicalSearchSpec:
    name: str
    catalog: str
    bounds: SearchBounds
    architecture: ArchitectureSearchSpec
    stages: tuple[RealizationStageSpec, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    schema_version: str = SEARCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.metadata = dict(self.metadata)
        if not self.name:
            raise SearchError("hierarchical search name must be non-empty")
        if len(self.architecture.operations) > self.bounds.memory_ops:
            raise SearchError("operation slots exceed the memory_ops bound")
        declared_harts = {
            hart for slot in self.architecture.operations for hart in slot.harts
        }
        if len(declared_harts) > self.bounds.harts:
            raise SearchError("operation domains exceed the harts bound")
        declared_addresses = {
            item.address for item in self.architecture.init_writes
        } | {
            address
            for slot in self.architecture.operations
            for address in slot.addresses
        }
        if len(declared_addresses) > self.bounds.addresses:
            raise SearchError("operation domains exceed the addresses bound")
        declared_values = {
            item.value for item in self.architecture.init_writes
        } | {value for slot in self.architecture.operations for value in slot.values}
        if len(declared_values) > self.bounds.values:
            raise SearchError("operation domains exceed the values bound")
        names = [stage.name for stage in self.stages]
        if len(names) != len(set(names)):
            raise SearchError("realization stage names must be unique")
        if not self.stages or not any(stage.required for stage in self.stages):
            raise SearchError(
                "hierarchical search requires at least one required realization stage"
            )
        if any(
            hart >= self.bounds.harts
            for slot in self.architecture.operations
            for hart in slot.harts
        ):
            raise SearchError(
                "operation hart identifiers must be smaller than the harts bound"
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HierarchicalSearchSpec":
        data = _mapping(data, "hierarchical search")
        realization = data.get("realization", {})
        raw_stages = (
            realization.get("stages", [])
            if isinstance(realization, Mapping)
            else None
        )
        if not isinstance(raw_stages, list):
            raise SerializationError("realization stages must be a list")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise SerializationError("hierarchical search metadata must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                catalog=str(data["catalog"]),
                bounds=SearchBounds.from_dict(data["bounds"]),
                architecture=ArchitectureSearchSpec.from_dict(data["architecture"]),
                stages=tuple(
                    RealizationStageSpec.from_dict(item) for item in raw_stages
                ),
                metadata=dict(metadata),
                schema_version=str(data.get("schema_version", SEARCH_SCHEMA_VERSION)),
            )
        except KeyError as exc:
            raise SerializationError(
                f"hierarchical search is missing {exc.args[0]!r}"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> "HierarchicalSearchSpec":
        source = Path(path).resolve()
        result = cls.from_dict(load_data(source))
        result.source_path = source
        return result

    def resolve(self, path: str) -> Path:
        source_dir = self.source_path.parent if self.source_path else Path.cwd()
        return (source_dir / path).resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "catalog": self.catalog,
            "metadata": dict(self.metadata),
            "bounds": self.bounds.to_dict(),
            "architecture": self.architecture.to_dict(),
            "realization": {
                "stages": [stage.to_dict() for stage in self.stages]
            },
        }
