from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace

ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"


def _complete(trace_name: str, composition_name: str = "lsq.yaml"):
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / trace_name)
    composition = CompositionSpec.load(BOOM / "composition" / composition_name)
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion, backend="z3")
    return catalog, trace, composed, result


def test_boom_examples_are_current_models_not_stage_archives() -> None:
    assert (BOOM / "model" / "lsu" / "module.yaml").is_file()
    assert (BOOM / "composition" / "lsq.yaml").is_file()
    assert not list(BOOM.rglob("stage*.yaml"))
    assert (ROOT / "tests" / "regressions" / "boom" / "legacy_v0_11").is_dir()


def test_lsq_instantiates_ldq_and_stq_from_trace() -> None:
    _, _, composed, _ = _complete("store_load_forward.yaml")
    state_names = {item.name for item in composed.completion.state_variables}
    assert "LSU.ldq[5].valid" in state_names
    assert "LSU.stq[2].valid" in state_names
    transformation_names = {item.name for item in composed.completion.transformations}
    assert "stld_unforwarded_violation_S0_L0" in transformation_names
    assert "selected_store_load_forward_S0_L0" in transformation_names


def test_load_nack_wakeup_reexecute_path_is_feasible() -> None:
    _, _, _, result = _complete("load_nack_wakeup.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.final_state["LSU.ldq[5].valid"] is False
    assert result.final_state["LSU.ldq[5].executed"] is True
    assert result.final_state["LSU.ldq[5].succeeded"] is True
    assert result.final_state["LSU.ldq[5].value"] == 42


def test_store_load_forward_path_is_feasible() -> None:
    _, _, _, result = _complete("store_load_forward.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.final_state["LSU.ldq[5].forward_std_val"] is True
    assert result.final_state["LSU.ldq[5].forward_stq_idx"] == 2
    assert result.final_state["LSU.ldq[5].value"] == 42


def test_store_load_violation_has_source_provenance_and_exception() -> None:
    _, _, _, result = _complete("store_load_violation.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    fail = next(
        event
        for event in result.completed_trace.events
        if event.event_type == "LSU.LoadOrderFail" and event.occurs is True
    )
    assert fail.fields["op_id"] == "L0"
    assert fail.fields["source_op_id"] == "S0"
    assert fail.fields["reason"] == "stld"
    assert result.final_state["LSU.ldq[5].order_fail"] is True
    assert any(
        event.event_type == "Core.MemoryOrderingException"
        and event.fields["op_id"] == "L0"
        for event in result.completed_trace.events
    )


def test_store_tlb_miss_retry_and_drain_preserves_identity() -> None:
    _, _, _, result = _complete("store_tlb_retry.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.final_state["LSU.stq[2].valid"] is False
    assert result.final_state["LSU.stq[2].succeeded"] is True
    address_event = result.completed_trace.get("store_addr_0")
    assert address_event.fields["op_id"] == "S0"
    assert address_event.fields["stq_idx"] == 2
    assert address_event.fields["address"] == "x"


def test_uncommitted_store_is_flushed_by_exception() -> None:
    _, _, _, result = _complete("store_exception_flush.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    flushed = result.completed_trace.get("store_flushed_0")
    assert flushed.fields == {"op_id": "S0", "stq_idx": 2, "reason": "exception"}
    assert result.final_state["LSU.stq[2].valid"] is False
    assert result.final_state["LSU.stq[2].addr_valid"] is False
    assert result.final_state["LSU.stq[2].data_valid"] is False


def test_store_commit_drain_ack_clear_lifecycle() -> None:
    _, _, _, result = _complete("store_commit_drain.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.final_state["LSU.stq[2].committed"] is True
    assert result.final_state["LSU.stq[2].succeeded"] is True
    assert result.final_state["LSU.stq[2].cleared"] is True
    assert result.final_state["LSU.stq[2].valid"] is False


def test_fence_waits_for_dcache_ordered() -> None:
    _, _, _, result = _complete("fence_ordering.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    release = result.completed_trace.get("fence_release_0")
    assert release.cycle >= result.completed_trace.get("ordered").cycle
    assert result.final_state["LSU.fence[1].valid"] is False


def test_full_buggy_boom_path_remains_forbidden() -> None:
    catalog, _, _, result = _complete("load_load_bug.yaml", "memory_buggy.yaml")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.FORBIDDEN
    graph = checked.representative.graph
    assert ("StoreGamma", "LoadAlpha") in graph.relation("rf").edges
    assert ("LoadAlpha", "LoadBeta") in graph.relation("ppo").edges
    assert ("LoadBeta", "StoreGamma") in graph.relation("fr").edges


def test_fixed_reference_recovers_and_blocks_bad_commit() -> None:
    catalog, _, _, recovered = _complete(
        "load_load_fixed_reference.yaml", "memory_fixed_reference.yaml"
    )
    assert recovered.status is CompletionStatus.FEASIBLE
    assert recovered.completed_trace is not None
    assert recovered.final_state["LSU.ldq[7].order_fail"] is True
    assert recovered.final_state["LSU.ldq[7].squashed"] is True
    fail = next(
        e for e in recovered.completed_trace.events
        if e.event_type == "LSU.LoadOrderFail" and e.fields.get("op_id") == "LoadBeta"
    )
    assert fail.fields["source_op_id"] == "LoadAlpha"
    checked = check_trace_memory_model(
        recovered.completed_trace,
        GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.ALLOWED

    _, _, _, forbidden = _complete("load_load_bug.yaml", "memory_fixed_reference.yaml")
    assert forbidden.status is CompletionStatus.INFEASIBLE
