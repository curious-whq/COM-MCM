from copy import deepcopy
from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, ModuleSpec, compose_modules
from umcm.composition.parameterization import TraceRoleSpec, resolve_trace_roles
from umcm.errors import CompositionError
from umcm.graph import GraphModelSpec, MemoryModelStatus, check_trace_memory_model
from umcm.hierarchy import build_interface_contracts, project_interface_trace
from umcm.ir import EventCatalog, Trace
from umcm.ir.expression import expr_from_dict


ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"
REG = ROOT / "tests" / "regressions" / "boom" / "v0_15"


def _catalog() -> EventCatalog:
    return EventCatalog.load(BOOM / "events.yaml")


def _buggy_composition() -> CompositionSpec:
    return CompositionSpec.load(BOOM / "composition" / "memory_buggy.yaml")


def _fixed_composition() -> CompositionSpec:
    return CompositionSpec.load(BOOM / "composition" / "memory_fixed_reference.yaml")


def _graph_model() -> GraphModelSpec:
    return GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml")


def test_trace_role_accepts_multiple_event_types_and_missing_where_path_is_nonmatch() -> None:
    trace = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    role = TraceRoleSpec.from_dict(
        {
            "name": "mshr_memory_ops",
            "event_type": ["Arch.Load", "Arch.Store"],
            "where": {"annotations.microarch.uses_mshr": True},
            "cardinality": "many",
            "min_matches": 1,
            "exports": {"op_id": "fields.op_id"},
        }
    )
    resolved = resolve_trace_roles(trace, [role])
    assert [item["op_id"] for item in resolved["mshr_memory_ops"]] == ["LoadAlpha"]
    assert role.to_dict()["event_type"] == ["Arch.Load", "Arch.Store"]


def test_module_internal_event_vocabulary_is_not_a_port() -> None:
    catalog = _catalog()
    query = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    composed = compose_modules(catalog, _buggy_composition(), query)
    module = next(item.spec for item in composed.modules if item.reference_name == "dcache")
    assert "DCache.LoadHit" in module.internal_events
    assert "DCache.LoadMiss" in module.internal_events
    assert "DCache.LoadHit" not in {port.event_type for port in module.ports}
    assert "DCache.LoadMiss" not in {port.event_type for port in module.ports}
    assert ModuleSpec.from_dict(module.to_dict()).to_dict() == module.to_dict()


def test_boom_interface_contracts_hide_implementation_vocabulary() -> None:
    catalog = _catalog()
    query = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    composed = compose_modules(catalog, _buggy_composition(), query)
    contracts = {item.module: item for item in build_interface_contracts(composed)}

    lsu = contracts["lsu"]
    assert "LSU.TLBMiss" in lsu.private_event_types
    assert "LSU.LoadExecuted" in lsu.private_event_types
    assert "LSU.LDLDConflict" in lsu.private_event_types
    assert "LSU.TLBMiss" not in lsu.public_event_types

    l1 = contracts["dcache"]
    assert "DCache.LoadHit" in l1.private_event_types
    assert "DCache.LoadMiss" in l1.private_event_types
    assert "DCache.LoadResponse" in l1.public_event_types
    assert "DCache.MSHRRequest" in l1.public_event_types

    mshr = contracts["mshr"]
    assert "MSHR.PrimaryAccept" in mshr.private_event_types
    assert "MSHR.RPQInsert" in mshr.private_event_types
    assert "MSHR.ResponseDequeue" in mshr.public_event_types


def test_strict_composition_rejects_private_child_event_constraint() -> None:
    catalog = _catalog()
    query = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    spec = _buggy_composition()
    spec.constraints.append(
        expr_from_dict(
            {
                "node": "event_field",
                "event_id": "younger_dcache_hit",
                "field": "occurs",
                "sort": {"name": "bool"},
            }
        )
    )
    with pytest.raises(CompositionError, match="reaches through module boundary"):
        compose_modules(catalog, spec, query)


def test_interface_projection_only_hides_and_preserves_bug_violation() -> None:
    catalog = _catalog()
    concrete = Trace.load(REG / "load_load_bug_completed.yaml")
    composed = compose_modules(catalog, _buggy_composition(), concrete)
    projected = project_interface_trace(concrete, composed)

    assert len(concrete.events) == 45
    assert len(projected.trace.events) == 19
    assert len(projected.certificate.hidden_event_ids) == 26
    assert "older_tlb_miss" in projected.certificate.hidden_event_ids
    assert "younger_dcache_hit" in projected.certificate.hidden_event_ids
    assert "primary_0" in projected.certificate.hidden_event_ids
    assert all(not event.event_type.startswith("Hierarchy.") for event in projected.trace.events)

    result = check_trace_memory_model(projected.trace, _graph_model())
    assert result.status is MemoryModelStatus.FORBIDDEN


def test_interface_projection_preserves_fixed_allowed_result() -> None:
    catalog = _catalog()
    concrete = Trace.load(REG / "load_load_fixed_completed.yaml")
    composed = compose_modules(catalog, _fixed_composition(), concrete)
    projected = project_interface_trace(concrete, composed)
    result = check_trace_memory_model(projected.trace, _graph_model())

    assert len(concrete.events) == 46
    assert len(projected.trace.events) == 20
    assert result.status is MemoryModelStatus.ALLOWED
    assert "memory_order_exception_1" in {
        event.id for event in projected.trace.events
    }
    assert "ldld_order_fail_0_1" in projected.certificate.hidden_event_ids
