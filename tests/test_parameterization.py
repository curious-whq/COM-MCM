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
EXAMPLE = ROOT / "tests" / "regressions" / "boom" / "legacy_v0_11"


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


def test_collection_role_and_module_repeat_expand_per_load(tmp_path: Path) -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")

    module_path = tmp_path / "lsu_repeat.yaml"
    module_path.write_text(
        """
schema_version: umcm.module.v0.11.0
name: lsu
ports: []
slots: []
state_variables: []
transformations: []
constraints: []
repeat:
  - over: loads
    as: load
    include:
      state_variables:
        - name: LSU.ldq[${load.ldq_idx}].valid
          sort: {name: bool}
          initial: false
      transformations: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    composition = CompositionSpec.from_dict(
        {
            "schema_version": "umcm.composition.v0.11.0",
            "name": "repeat-loads",
            "modules": [{"name": "lsu", "path": str(module_path)}],
            "connections": [],
            "roles": [
                {
                    "name": "loads",
                    "event_type": "Arch.Load",
                    "cardinality": "many",
                    "exports": {
                        "op_id": "fields.op_id",
                        "address": "fields.address",
                        "ldq_idx": "annotations.microarch.ldq_idx",
                    },
                }
            ],
        }
    )
    composed = compose_modules(catalog, composition, trace)
    assert [item["op_id"] for item in composed.resolved_roles["loads"]] == [
        "LoadAlpha",
        "LoadBeta",
    ]
    names = {state.name for state in composed.completion.state_variables}
    assert names == {"LSU.ldq[13].valid", "LSU.ldq[7].valid"}


def test_role_can_match_multiple_event_types() -> None:
    trace = Trace.from_dict(
        {
            "schema_version": "umcm.trace.v0.14.0",
            "partial": True,
            "events": [
                {
                    "id": "l",
                    "type": "Arch.Load",
                    "occurs": True,
                    "cycle": 0,
                    "fields": {"op_id": "L", "hart": 0, "program_index": 0, "address": "x", "byte_mask": 255},
                },
                {
                    "id": "s",
                    "type": "Arch.Store",
                    "occurs": True,
                    "cycle": 1,
                    "fields": {"op_id": "S", "hart": 0, "program_index": 1, "address": "x", "value": 1, "byte_mask": 255},
                },
            ],
            "constraints": [],
        }
    )
    role = TraceRoleSpec(
        name="memory_ops",
        event_type=("Arch.Load", "Arch.Store"),
        cardinality="many",
        exports={"op_id": "fields.op_id"},
    )
    context = resolve_trace_roles(trace, [role])
    assert [item["op_id"] for item in context["memory_ops"]] == ["L", "S"]


def test_missing_where_path_means_no_match_not_error() -> None:
    trace = Trace.load(ROOT / "examples" / "boom" / "traces" / "l1" / "load_hit.yaml")
    roles = [
        TraceRoleSpec(
            name="lr_loads",
            event_type="Arch.Load",
            where={"annotations.microarch.is_lr": True},
            cardinality="many",
            min_matches=0,
            exports={"op_id": "fields.op_id"},
        )
    ]
    context = resolve_trace_roles(trace, roles)
    assert context["lr_loads"] == []
