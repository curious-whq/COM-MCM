"""Execution-graph construction and axiom checking."""

from umcm.graph.builder import CandidateSpace, build_candidate_space, iter_execution_graphs, project_operations
from umcm.graph.checker import (
    AxiomResult,
    AxiomStatus,
    CandidateCheck,
    MemoryModelCheck,
    MemoryModelStatus,
    check_axiom,
    check_execution_graph,
    check_trace_memory_model,
)
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import (
    AxiomSpec,
    COHintSpec,
    DerivedRelationSpec,
    GraphModelSpec,
    ProjectionSpec,
    RFHintSpec,
)
from umcm.graph.relation import (
    Edge,
    LabeledEdge,
    Relation,
    find_labeled_cycle,
    union_relations,
)

__all__ = [
    "AxiomResult",
    "AxiomSpec",
    "AxiomStatus",
    "CandidateCheck",
    "CandidateSpace",
    "COHintSpec",
    "DerivedRelationSpec",
    "Edge",
    "ExecutionGraph",
    "GraphModelSpec",
    "LabeledEdge",
    "MemoryModelCheck",
    "MemoryModelStatus",
    "MemoryOperation",
    "OperationKind",
    "ProjectionSpec",
    "RFHintSpec",
    "Relation",
    "build_candidate_space",
    "check_axiom",
    "check_execution_graph",
    "check_trace_memory_model",
    "find_labeled_cycle",
    "iter_execution_graphs",
    "project_operations",
    "union_relations",
]
