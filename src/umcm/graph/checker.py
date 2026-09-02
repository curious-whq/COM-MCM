"""Axiom checking over finite execution-graph candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from umcm.errors import GraphError
from umcm.graph.builder import iter_execution_graphs
from umcm.graph.execution import ExecutionGraph
from umcm.graph.model import AxiomSpec, GraphModelSpec
from umcm.graph.relation import LabeledEdge, Relation, find_labeled_cycle, union_relations
from umcm.ir.trace import Trace


class AxiomStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"


@dataclass(frozen=True, slots=True)
class AxiomResult:
    axiom: str
    status: AxiomStatus
    kind: str
    relations: tuple[str, ...]
    cycle: tuple[LabeledEdge, ...] = ()
    offending_edges: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "axiom": self.axiom,
            "status": self.status.value,
            "kind": self.kind,
            "relations": list(self.relations),
        }
        if self.cycle:
            data["cycle"] = [edge.to_dict() for edge in self.cycle]
        if self.offending_edges:
            data["offending_edges"] = [
                {"from": source, "to": target}
                for source, target in self.offending_edges
            ]
        return data


@dataclass(frozen=True, slots=True)
class CandidateCheck:
    graph: ExecutionGraph
    axioms: tuple[AxiomResult, ...]

    @property
    def allowed(self) -> bool:
        return all(result.status is AxiomStatus.SATISFIED for result in self.axioms)


class MemoryModelStatus(str, Enum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class MemoryModelCheck:
    status: MemoryModelStatus
    candidates: tuple[CandidateCheck, ...]

    @property
    def representative(self) -> CandidateCheck:
        if not self.candidates:
            raise GraphError("memory-model check has no candidates")
        if self.status is MemoryModelStatus.ALLOWED:
            return next(candidate for candidate in self.candidates if candidate.allowed)
        return self.candidates[0]


def check_axiom(graph: ExecutionGraph, axiom: AxiomSpec) -> AxiomResult:
    try:
        relations = tuple(graph.relation(name) for name in axiom.relations)
    except GraphError:
        raise

    if axiom.kind == "acyclic":
        cycle = find_labeled_cycle(relations)
        return AxiomResult(
            axiom=axiom.name,
            status=(
                AxiomStatus.SATISFIED if cycle is None else AxiomStatus.VIOLATED
            ),
            kind=axiom.kind,
            relations=axiom.relations,
            cycle=cycle or (),
        )

    combined = union_relations(f"axiom:{axiom.name}", relations)
    if axiom.kind == "irreflexive":
        offending = tuple(sorted(edge for edge in combined.edges if edge[0] == edge[1]))
    elif axiom.kind == "empty":
        offending = tuple(sorted(combined.edges))
    else:  # guarded by AxiomSpec
        raise GraphError(f"unsupported axiom kind: {axiom.kind}")
    return AxiomResult(
        axiom=axiom.name,
        status=(
            AxiomStatus.SATISFIED if not offending else AxiomStatus.VIOLATED
        ),
        kind=axiom.kind,
        relations=axiom.relations,
        offending_edges=offending,
    )


def check_execution_graph(
    graph: ExecutionGraph,
    axioms: Iterable[AxiomSpec],
) -> CandidateCheck:
    return CandidateCheck(
        graph=graph,
        axioms=tuple(check_axiom(graph, axiom) for axiom in axioms),
    )


def check_trace_memory_model(
    trace: Trace,
    spec: GraphModelSpec,
    *,
    max_candidates: int = 10_000,
) -> MemoryModelCheck:
    candidates: list[CandidateCheck] = []
    for graph in iter_execution_graphs(
        trace,
        spec,
        max_candidates=max_candidates,
    ):
        checked = check_execution_graph(graph, spec.axioms)
        candidates.append(checked)
    if not candidates:
        raise GraphError("trace generated no execution-graph candidates")
    status = (
        MemoryModelStatus.ALLOWED
        if any(candidate.allowed for candidate in candidates)
        else MemoryModelStatus.FORBIDDEN
    )
    return MemoryModelCheck(status=status, candidates=tuple(candidates))
