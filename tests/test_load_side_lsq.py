from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests" / "regressions" / "boom" / "legacy_v0_11"


def test_generic_load_side_nack_wakeup_reexecute_commit() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage11_load_side_nack_wakeup.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/load_side_generic_composition.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    assert composed.resolved_roles["loads"][0]["op_id"] == "LoadA"
    result = complete_trace(catalog, trace, composed.completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.final_state["LSU.ldq[5].valid"] is False
    assert result.final_state["LSU.ldq[5].executed"] is True
    assert result.final_state["LSU.ldq[5].succeeded"] is True
    assert result.final_state["LSU.ldq[5].value"] == 42
    allocation = result.completed_trace.get("ldq_allocate_0")
    assert allocation.occurs is True
    assert allocation.fields == {"op_id": "LoadA", "ldq_idx": 5}


def test_generic_load_wakeup_is_blocked_while_entry_still_executed() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage11_load_side_bad_wakeup.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/load_side_generic_composition.yaml"
    )
    result = complete_trace(
        catalog, trace, compose_modules(catalog, composition, trace).completion
    )
    assert result.status is CompletionStatus.INFEASIBLE
    assert "LSU.ldq[5].executed == False" in result.reason


def test_real_bug_composition_instantiates_unrelated_third_load_automatically() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage11_three_load_trace.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/buggy_parameterized_composition.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    assert [item["op_id"] for item in composed.resolved_roles["loads"]] == [
        "LoadAlpha", "LoadBeta", "LoadExtra"
    ]
    result = complete_trace(catalog, trace, composed.completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.final_state["LSU.ldq[21].valid"] is True
    assert result.final_state["LSU.ldq[21].executed"] is False
    assert result.final_state["LSU.ldq[21].succeeded"] is False
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.FORBIDDEN


def test_parameterized_fixed_recovery_still_works_with_generic_ldq_family() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage10_parameterized_recovery_trace.yaml")
    composition = CompositionSpec.load(
        EXAMPLE / "modular/fixed_parameterized_composition.yaml"
    )
    result = complete_trace(
        catalog, trace, compose_modules(catalog, composition, trace).completion
    )
    assert result.status is CompletionStatus.FEASIBLE
    assert result.final_state["LSU.ldq[7].order_fail"] is True
    assert result.final_state["LSU.ldq[7].squashed"] is True
    assert result.final_state["LSU.ldq[7].valid"] is False
