from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.composition.parameterization import (
    TraceRoleSpec,
    render_template,
    resolve_trace_roles,
)
from umcm.errors import CompositionError
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "boom_load_load"


def test_trace_role_binding_preserves_typed_values() -> None:
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    roles = [
        TraceRoleSpec(
            name="older",
            event_type="Arch.Load",
            where={"fields.hart": 0, "fields.program_index": 0},
            exports={
                "op_id": "fields.op_id",
                "ldq_idx": "annotations.microarch.ldq_idx",
                "mshr_id": "annotations.microarch.mshr_id",
            },
        )
    ]
    context = resolve_trace_roles(trace, roles)
    assert context["older"]["op_id"] == "LoadAlpha"
    assert context["older"]["ldq_idx"] == 13
    assert context["older"]["mshr_id"] == 3
    rendered = render_template(
        {
            "field": "${older.ldq_idx}",
            "state": "LSU.ldq[${older.ldq_idx}].valid",
        },
        context,
    )
    assert rendered["field"] == 13
    assert isinstance(rendered["field"], int)
    assert rendered["state"] == "LSU.ldq[13].valid"


def test_parameterized_composition_requires_instantiation_trace() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/buggy_parameterized_composition.yaml"
    )
    with pytest.raises(CompositionError, match="declares trace roles"):
        compose_modules(catalog, composition)


def test_parameterized_buggy_model_works_with_renamed_ops_and_indices() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/buggy_parameterized_composition.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    assert composed.resolved_roles["older_load"]["op_id"] == "LoadAlpha"
    assert composed.resolved_roles["older_load"]["ldq_idx"] == 13
    assert composed.resolved_roles["older_load"]["mshr_id"] == 3
    assert composed.resolved_roles["younger_load"]["ldq_idx"] == 7
    state_names = {item.name for item in composed.completion.state_variables}
    assert "LSU.ldq[13].valid" in state_names
    assert "LSU.ldq[7].observed" in state_names
    assert "MSHR[3].state" in state_names
    assert all("LSU.ldq.L0" not in name for name in state_names)
    assert all("LSU.ldq.L1" not in name for name in state_names)

    result = complete_trace(catalog, trace, composed.completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.FORBIDDEN
    graph = checked.representative.graph
    assert ("StoreGamma", "LoadAlpha") in graph.relation("rf").edges
    assert ("LoadAlpha", "LoadBeta") in graph.relation("ppo").edges
    assert ("LoadBeta", "StoreGamma") in graph.relation("fr").edges


def test_parameterized_fixed_model_blocks_same_bad_commit() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/fixed_parameterized_composition.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion)
    assert result.status is CompletionStatus.INFEASIBLE
    assert "LSU.ldq[7].valid == True" in result.reason


def test_parameterized_fixed_recovery_remains_allowed() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_recovery_trace.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/fixed_parameterized_composition.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.final_state["LSU.ldq[7].order_fail"] is True
    assert result.final_state["LSU.ldq[7].squashed"] is True
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.ALLOWED


def test_parameterized_templates_contain_no_witness_specific_operation_names() -> None:
    template_dir = EXAMPLE / "modular/templates"
    for path in template_dir.glob("*.template.yaml"):
        text = path.read_text()
        assert "LSU.ldq.L0" not in text
        assert "LSU.ldq.L1" not in text
        assert "MSHR.0." not in text
        # Concrete operation identities must come from trace roles.
        assert "value: L0\n" not in text
        assert "value: L1\n" not in text
        assert "value: W1\n" not in text
