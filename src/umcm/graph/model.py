"""Loadable architectural projection, relation, and axiom specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import AxiomError, SerializationError
from umcm.serialization import dump_data, load_data


GRAPH_MODEL_SCHEMA_VERSION = "umcm.graph_model.v0.1"


def _unknown_keys(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise SerializationError(
            f"{context} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


@dataclass(frozen=True, slots=True)
class RFHintSpec:
    event_type: str
    read_id_field: str = "op_id"
    write_id_field: str = "source_op_id"
    address_field: str = "address"
    value_field: str = "value"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RFHintSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("rf hint must be a mapping")
        _unknown_keys(
            data,
            {
                "event_type",
                "read_id_field",
                "write_id_field",
                "address_field",
                "value_field",
            },
            "rf hint",
        )
        try:
            return cls(
                event_type=str(data["event_type"]),
                read_id_field=str(data.get("read_id_field", "op_id")),
                write_id_field=str(data.get("write_id_field", "source_op_id")),
                address_field=str(data.get("address_field", "address")),
                value_field=str(data.get("value_field", "value")),
            )
        except KeyError as exc:
            raise SerializationError("rf hint requires event_type") from exc

    def to_dict(self) -> dict[str, str]:
        return {
            "event_type": self.event_type,
            "read_id_field": self.read_id_field,
            "write_id_field": self.write_id_field,
            "address_field": self.address_field,
            "value_field": self.value_field,
        }


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    init_write_event: str
    load_event: str
    store_event: str
    load_commit_event: str
    id_field: str = "op_id"
    address_field: str = "address"
    value_field: str = "value"
    hart_field: str = "hart"
    program_index_field: str = "program_index"
    require_committed_loads: bool = True
    rf_hints: tuple[RFHintSpec, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("projection must be a mapping")
        _unknown_keys(
            data,
            {
                "init_write_event",
                "load_event",
                "store_event",
                "load_commit_event",
                "id_field",
                "address_field",
                "value_field",
                "hart_field",
                "program_index_field",
                "require_committed_loads",
                "rf_hints",
            },
            "projection",
        )
        raw_hints = data.get("rf_hints", [])
        if not isinstance(raw_hints, list):
            raise SerializationError("projection.rf_hints must be a list")
        try:
            return cls(
                init_write_event=str(data["init_write_event"]),
                load_event=str(data["load_event"]),
                store_event=str(data["store_event"]),
                load_commit_event=str(data["load_commit_event"]),
                id_field=str(data.get("id_field", "op_id")),
                address_field=str(data.get("address_field", "address")),
                value_field=str(data.get("value_field", "value")),
                hart_field=str(data.get("hart_field", "hart")),
                program_index_field=str(
                    data.get("program_index_field", "program_index")
                ),
                require_committed_loads=bool(
                    data.get("require_committed_loads", True)
                ),
                rf_hints=tuple(RFHintSpec.from_dict(item) for item in raw_hints),
            )
        except KeyError as exc:
            raise SerializationError(
                f"projection is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "init_write_event": self.init_write_event,
            "load_event": self.load_event,
            "store_event": self.store_event,
            "load_commit_event": self.load_commit_event,
            "id_field": self.id_field,
            "address_field": self.address_field,
            "value_field": self.value_field,
            "hart_field": self.hart_field,
            "program_index_field": self.program_index_field,
            "require_committed_loads": self.require_committed_loads,
            "rf_hints": [item.to_dict() for item in self.rf_hints],
        }


@dataclass(frozen=True, slots=True)
class DerivedRelationSpec:
    name: str
    op: str
    relations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise AxiomError("derived relation name must be non-empty")
        if self.op not in {
            "union",
            "intersection",
            "difference",
            "inverse",
            "compose",
            "transitive_closure",
        }:
            raise AxiomError(f"unsupported derived relation op: {self.op}")
        arity = len(self.relations)
        if self.op in {"inverse", "transitive_closure"} and arity != 1:
            raise AxiomError(f"{self.op} requires exactly one relation")
        if self.op in {"intersection", "difference", "compose"} and arity != 2:
            raise AxiomError(f"{self.op} requires exactly two relations")
        if self.op == "union" and arity < 1:
            raise AxiomError("union requires at least one relation")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DerivedRelationSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("derived relation must be a mapping")
        _unknown_keys(data, {"name", "op", "relations"}, "derived relation")
        raw_relations = data.get("relations", [])
        if not isinstance(raw_relations, list):
            raise SerializationError("derived relation relations must be a list")
        try:
            return cls(
                name=str(data["name"]),
                op=str(data["op"]),
                relations=tuple(str(item) for item in raw_relations),
            )
        except KeyError as exc:
            raise SerializationError(
                f"derived relation is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "op": self.op, "relations": list(self.relations)}


@dataclass(frozen=True, slots=True)
class AxiomSpec:
    name: str
    kind: str
    relations: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise AxiomError("axiom name must be non-empty")
        if self.kind not in {"acyclic", "irreflexive", "empty"}:
            raise AxiomError(f"unsupported axiom kind: {self.kind}")
        if not self.relations:
            raise AxiomError(f"axiom {self.name!r} needs at least one relation")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AxiomSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("axiom must be a mapping")
        _unknown_keys(data, {"name", "kind", "relations", "description"}, "axiom")
        raw_relations = data.get("relations", [])
        if not isinstance(raw_relations, list):
            raise SerializationError("axiom relations must be a list")
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                relations=tuple(str(item) for item in raw_relations),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(f"axiom is missing {exc.args[0]!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "relations": list(self.relations),
        }
        if self.description:
            data["description"] = self.description
        return data


@dataclass(slots=True)
class GraphModelSpec:
    model: str
    projection: ProjectionSpec
    derived_relations: tuple[DerivedRelationSpec, ...] = ()
    axioms: tuple[AxiomSpec, ...] = ()
    ppo_rules: tuple[str, ...] = ("load_load_different_write",)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = GRAPH_MODEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.model:
            raise AxiomError("graph model name must be non-empty")
        self.metadata = dict(self.metadata)
        supported = {"load_load_different_write"}
        unknown = set(self.ppo_rules) - supported
        if unknown:
            raise AxiomError(
                f"unsupported ppo rule(s): {', '.join(sorted(unknown))}"
            )
        names = [item.name for item in self.derived_relations]
        if len(names) != len(set(names)):
            raise AxiomError("duplicate derived relation name")
        axiom_names = [item.name for item in self.axioms]
        if len(axiom_names) != len(set(axiom_names)):
            raise AxiomError("duplicate axiom name")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphModelSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("graph model must be a mapping")
        _unknown_keys(
            data,
            {
                "schema_version",
                "model",
                "metadata",
                "projection",
                "ppo_rules",
                "derived_relations",
                "axioms",
            },
            "graph model",
        )
        raw_derived = data.get("derived_relations", [])
        raw_axioms = data.get("axioms", [])
        raw_ppo = data.get("ppo_rules", ["load_load_different_write"])
        metadata = data.get("metadata", {})
        if not isinstance(raw_derived, list):
            raise SerializationError("derived_relations must be a list")
        if not isinstance(raw_axioms, list):
            raise SerializationError("axioms must be a list")
        if not isinstance(raw_ppo, list):
            raise SerializationError("ppo_rules must be a list")
        if not isinstance(metadata, Mapping):
            raise SerializationError("graph model metadata must be a mapping")
        try:
            return cls(
                model=str(data["model"]),
                projection=ProjectionSpec.from_dict(data["projection"]),
                derived_relations=tuple(
                    DerivedRelationSpec.from_dict(item) for item in raw_derived
                ),
                axioms=tuple(AxiomSpec.from_dict(item) for item in raw_axioms),
                ppo_rules=tuple(str(item) for item in raw_ppo),
                metadata=dict(metadata),
                schema_version=str(
                    data.get("schema_version", GRAPH_MODEL_SCHEMA_VERSION)
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"graph model is missing {exc.args[0]!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model": self.model,
            "metadata": dict(self.metadata),
            "projection": self.projection.to_dict(),
            "ppo_rules": list(self.ppo_rules),
            "derived_relations": [item.to_dict() for item in self.derived_relations],
            "axioms": [item.to_dict() for item in self.axioms],
        }

    @classmethod
    def load(cls, path: str | Path) -> "GraphModelSpec":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)
