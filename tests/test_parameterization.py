from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.composition.parameterization import (
    TraceRoleSpec,
    render_template,
    resolve_trace_roles,
)
from umcm.errors import CompositionError, SchemaError
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


def test_queue_indices_are_derived_from_dispatch_order_not_annotations() -> None:
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    # Deliberately ignore the trace's historical microarch annotations.  BOOM
    # allocates successive LDQ entries from ldq_tail at dispatch; under the
    # bounded empty-queue reset used here that is the per-hart load ordinal.
    roles = [
        TraceRoleSpec(
            name="loads",
            event_type="Arch.Load",
            cardinality="many",
            exports={"op_id": "fields.op_id", "hart": "fields.hart"},
            derived={
                "ldq_idx": {
                    "kind": "queue_index",
                    "group_by": "fields.hart",
                    "start": 0,
                    "capacity": 16,
                }
            },
        )
    ]
    context = resolve_trace_roles(trace, roles)
    assert [item["op_id"] for item in context["loads"]] == [
        "LoadAlpha",
        "LoadBeta",
    ]
    assert [item["ldq_idx"] for item in context["loads"]] == [0, 1]


def test_switch_derived_export_selects_literal_or_event_field() -> None:
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    roles = [
        TraceRoleSpec(
            name="memory",
            event_type=("Arch.Load", "Arch.Store"),
            cardinality="many",
            exports={"op_id": "fields.op_id"},
            derived={
                "queue_kind": {
                    "kind": "switch",
                    "path": "event_type",
                    "cases": {
                        "Arch.Load": {"value": "ldq"},
                        "Arch.Store": {"value": "stq"},
                    },
                },
                "payload": {
                    "kind": "switch",
                    "path": "event_type",
                    "cases": {
                        "Arch.Load": {"path": "fields.address"},
                        "Arch.Store": {"path": "fields.address"},
                    },
                },
            },
        )
    ]
    context = resolve_trace_roles(trace, roles)
    assert [item["queue_kind"] for item in context["memory"]] == [
        "ldq",
        "ldq",
        "stq",
    ]
    assert [item["payload"] for item in context["memory"]] == [
        "data0",
        "data0",
        "data0",
    ]


def test_collection_role_can_expand_a_finite_attempt_bound() -> None:
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    roles = [
        TraceRoleSpec(
            name="load_attempts",
            event_type="Arch.Load",
            cardinality="many",
            copies=2,
            exports={"op_id": "fields.op_id", "frame_id": "fields.op_id"},
            copy_exports={"frame_id": "${copy.frame_id}.${copy.copy_index}"},
            derived={
                "ldq_idx": {
                    "kind": "queue_index",
                    "group_by": "fields.hart",
                    "start": 0,
                    "capacity": 16,
                }
            },
        )
    ]
    attempts = resolve_trace_roles(trace, roles)["load_attempts"]
    assert [(item["op_id"], item["ldq_idx"], item["copy_index"], item["frame_id"]) for item in attempts] == [
        ("LoadAlpha", 0, 0, "LoadAlpha.0"),
        ("LoadAlpha", 0, 1, "LoadAlpha.1"),
        ("LoadBeta", 1, 0, "LoadBeta.0"),
        ("LoadBeta", 1, 1, "LoadBeta.1"),
    ]


def test_role_copies_requires_collection_cardinality() -> None:
    with pytest.raises(SchemaError, match="copies requires cardinality=many"):
        TraceRoleSpec(name="bad", event_type="Arch.Load", copies=2)


def test_composition_static_parameters_can_instantiate_finite_resources(
    tmp_path: Path,
) -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_trace.yaml")
    module_path = tmp_path / "resources.yaml"
    module_path.write_text(
        """
schema_version: umcm.module.v0.15.0
name: resources
ports: []
slots: []
state_variables: []
transformations: []
constraints: []
repeat:
- over: mshr_resources
  as: resource
  include:
    state_variables:
    - name: MSHR[${resource.mshr_id}].valid
      sort: {name: bool}
      initial: false
""".strip()
        + "\n",
        encoding="utf-8",
    )
    composition = CompositionSpec.from_dict(
        {
            "schema_version": "umcm.composition.v0.15.0",
            "name": "static-resource-domain",
            "parameters": {
                "mshr_resources": [{"mshr_id": 0}, {"mshr_id": 1}]
            },
            "modules": [{"name": "resources", "path": str(module_path)}],
            "connections": [],
        }
    )
    composed = compose_modules(catalog, composition, trace)
    assert {state.name for state in composed.completion.state_variables} == {
        "MSHR[0].valid",
        "MSHR[1].valid",
    }


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
