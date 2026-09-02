"""Execution-graph nodes, relations, and serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from umcm.errors import GraphError, SerializationError
from umcm.graph.relation import Relation
from umcm.serialization import dump_data, load_data


EXECUTION_GRAPH_SCHEMA_VERSION = "umcm.execution_graph.v0.1"


class OperationKind(str, Enum):
    INIT_WRITE = "init_write"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class MemoryOperation:
    id: str
    kind: OperationKind
    address: Any
    value: Any
    hart: int | None = None
    program_index: int | None = None
    source_event_id: str = ""
    commit_event_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise GraphError("memory operation id must be non-empty")
        if self.kind is not OperationKind.INIT_WRITE:
            if self.hart is None or self.program_index is None:
                raise GraphError(
                    f"operation {self.id!r} requires hart and program_index"
                )
        if self.kind is OperationKind.READ and not self.commit_event_id:
            raise GraphError(f"read {self.id!r} requires a commit event")

    @property
    def is_read(self) -> bool:
        return self.kind is OperationKind.READ

    @property
    def is_write(self) -> bool:
        return self.kind in {OperationKind.WRITE, OperationKind.INIT_WRITE}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind.value,
            "address": self.address,
            "value": self.value,
        }
        if self.hart is not None:
            data["hart"] = self.hart
        if self.program_index is not None:
            data["program_index"] = self.program_index
        if self.source_event_id:
            data["source_event_id"] = self.source_event_id
        if self.commit_event_id:
            data["commit_event_id"] = self.commit_event_id
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryOperation":
        if not isinstance(data, Mapping):
            raise SerializationError("execution-graph operation must be a mapping")
        try:
            metadata = data.get("metadata", {})
            if not isinstance(metadata, Mapping):
                raise SerializationError("operation metadata must be a mapping")
            return cls(
                id=str(data["id"]),
                kind=OperationKind(str(data["kind"])),
                address=data["address"],
                value=data["value"],
                hart=None if data.get("hart") is None else int(data["hart"]),
                program_index=(
                    None
                    if data.get("program_index") is None
                    else int(data["program_index"])
                ),
                source_event_id=str(data.get("source_event_id", "")),
                commit_event_id=str(data.get("commit_event_id", "")),
                metadata=dict(metadata),
            )
        except (KeyError, ValueError) as exc:
            raise SerializationError(f"invalid execution-graph operation: {exc}") from exc


@dataclass(slots=True)
class ExecutionGraph:
    operations: dict[str, MemoryOperation]
    relations: dict[str, Relation]
    candidate_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = EXECUTION_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.operations = dict(self.operations)
        self.relations = dict(self.relations)
        self.metadata = dict(self.metadata)
        for op_id, operation in self.operations.items():
            if op_id != operation.id:
                raise GraphError(
                    f"operation key {op_id!r} does not match id {operation.id!r}"
                )
        for name, relation in self.relations.items():
            if name != relation.name:
                raise GraphError(
                    f"relation key {name!r} does not match name {relation.name!r}"
                )
            for source, target in relation.edges:
                if source not in self.operations or target not in self.operations:
                    raise GraphError(
                        f"relation {name!r} references unknown edge {source!r}->{target!r}"
                    )

    def relation(self, name: str) -> Relation:
        try:
            return self.relations[name]
        except KeyError as exc:
            raise GraphError(f"unknown relation: {name}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "metadata": dict(self.metadata),
            "operations": [
                self.operations[op_id].to_dict() for op_id in sorted(self.operations)
            ],
            "relations": [
                self.relations[name].to_dict() for name in sorted(self.relations)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionGraph":
        if not isinstance(data, Mapping):
            raise SerializationError("execution graph must be a mapping")
        raw_operations = data.get("operations", [])
        raw_relations = data.get("relations", [])
        if not isinstance(raw_operations, list) or not isinstance(raw_relations, list):
            raise SerializationError("execution graph operations/relations must be lists")
        operations = [MemoryOperation.from_dict(item) for item in raw_operations]
        relations: list[Relation] = []
        for raw in raw_relations:
            if not isinstance(raw, Mapping):
                raise SerializationError("execution-graph relation must be a mapping")
            name = str(raw.get("name", ""))
            raw_edges = raw.get("edges", [])
            if not isinstance(raw_edges, list):
                raise SerializationError("relation edges must be a list")
            edges = []
            for edge in raw_edges:
                if not isinstance(edge, Mapping):
                    raise SerializationError("relation edge must be a mapping")
                try:
                    edges.append((str(edge["from"]), str(edge["to"])))
                except KeyError as exc:
                    raise SerializationError("relation edge requires from/to") from exc
            relations.append(Relation.from_edges(name, edges))
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise SerializationError("execution graph metadata must be a mapping")
        return cls(
            operations={item.id: item for item in operations},
            relations={item.name: item for item in relations},
            candidate_id=int(data.get("candidate_id", 0)),
            metadata=dict(metadata),
            schema_version=str(
                data.get("schema_version", EXECUTION_GRAPH_SCHEMA_VERSION)
            ),
        )

    @classmethod
    def load(cls, path: str | Path) -> "ExecutionGraph":
        return cls.from_dict(load_data(path))

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)

    def relation_counts(self) -> dict[str, int]:
        return {name: len(relation.edges) for name, relation in self.relations.items()}

    def with_relations(self, relations: Iterable[Relation]) -> "ExecutionGraph":
        merged = dict(self.relations)
        for relation in relations:
            merged[relation.name] = relation
        return ExecutionGraph(
            operations=self.operations,
            relations=merged,
            candidate_id=self.candidate_id,
            metadata=self.metadata,
            schema_version=self.schema_version,
        )
