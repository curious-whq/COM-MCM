"""Hierarchical trace abstraction and refinement checks."""

from umcm.hierarchy.engine import (
    AbstractionCertificate,
    AbstractionResult,
    MemoryModelPreservationCheck,
    RefinementCheck,
    SummaryEvidence,
    abstract_trace,
    check_memory_model_preservation,
    check_refinement,
)
from umcm.hierarchy.interface import (
    InterfaceProjectionCertificate,
    InterfaceProjectionResult,
    ModuleInterfaceContract,
    PortContract,
    build_interface_contracts,
    project_interface_trace,
)
from umcm.hierarchy.model import (
    ABSTRACTION_SCHEMA_VERSION,
    AbstractionSpec,
    EventRoleSpec,
    MatchValue,
    OutputValue,
    RetainSpec,
    SummaryEventSpec,
    SummaryRuleSpec,
)

__all__ = [
    "ABSTRACTION_SCHEMA_VERSION",
    "AbstractionCertificate",
    "AbstractionResult",
    "AbstractionSpec",
    "EventRoleSpec",
    "MatchValue",
    "MemoryModelPreservationCheck",
    "OutputValue",
    "RefinementCheck",
    "RetainSpec",
    "SummaryEventSpec",
    "SummaryEvidence",
    "SummaryRuleSpec",
    "InterfaceProjectionCertificate",
    "InterfaceProjectionResult",
    "ModuleInterfaceContract",
    "PortContract",
    "build_interface_contracts",
    "project_interface_trace",
    "abstract_trace",
    "check_memory_model_preservation",
    "check_refinement",
]
