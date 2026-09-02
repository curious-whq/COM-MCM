from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace

ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"


def _complete_mshr(name: str):
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / "mshr" / f"{name}.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "mshr.yaml")
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion, backend="z3")
    return catalog, trace, composed, result


def _occurring(result, event_type: str):
    assert result.completed_trace is not None
    return [
        event
        for event in result.completed_trace.events
        if event.occurs is True and event.event_type == event_type
    ]


def test_primary_load_refill_direct_response_and_respq() -> None:
    _, _, _, result = _complete_mshr("primary_load_refill")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "MSHR.PrimaryAccept")) == 1
    assert len(_occurring(result, "MSHR.AcquireBlock")) == 1
    assert len(_occurring(result, "MSHR.GrantData")) == 1
    assert len(_occurring(result, "MSHR.RefillComplete")) == 1
    assert len(_occurring(result, "MSHR.DirectLoadResponse")) == 1
    response = _occurring(result, "MSHR.ResponseDequeue")[0]
    assert response.fields["op_id"] == "Ld0"
    assert response.fields["value"] == 11
    assert result.final_state["MSHR.req[Ld0].rpq_valid"] is False
    assert result.final_state["MSHR.req[Ld0].responseq_valid"] is False


def test_secondary_miss_shares_one_refill_and_returns_both_loads() -> None:
    _, _, composed, result = _complete_mshr("secondary_merge")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(composed.resolved_roles["mshr_requests"]) == 2
    # distinct_by(mshr_id) creates one persistent MSHR instance for both requests.
    assert len(composed.resolved_roles["mshr_instances"]) == 1
    assert len(_occurring(result, "MSHR.PrimaryAccept")) == 1
    assert len(_occurring(result, "MSHR.SecondaryMissAccept")) == 1
    assert len(_occurring(result, "MSHR.AcquireBlock")) == 1
    assert len(_occurring(result, "MSHR.GrantData")) == 1
    direct = _occurring(result, "MSHR.DirectLoadResponse")
    assert {event.fields["op_id"] for event in direct} == {"Ld0", "Ld1"}
    responses = _occurring(result, "MSHR.ResponseDequeue")
    assert {event.fields["op_id"] for event in responses} == {"Ld0", "Ld1"}
    assert {event.fields["value"] for event in responses} == {11}


def test_branch_kill_removes_secondary_rpq_entry() -> None:
    _, _, _, result = _complete_mshr("branch_kill_secondary")
    assert result.status is CompletionStatus.FEASIBLE
    kills = _occurring(result, "MSHR.RPQKill")
    assert len(kills) == 1
    assert kills[0].fields["op_id"] == "Ld1"
    assert kills[0].fields["reason"] == "branch"
    responses = _occurring(result, "MSHR.ResponseDequeue")
    assert {event.fields["op_id"] for event in responses} == {"Ld0"}
    assert result.final_state["MSHR.req[Ld1].killed"] is True
    assert result.final_state["MSHR.req[Ld1].rpq_valid"] is False


def test_store_no_data_grant_replays_and_frees_sdq() -> None:
    _, _, _, result = _complete_mshr("store_no_data_replay")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "MSHR.GrantNoData")) == 1
    replay = _occurring(result, "MSHR.Replay")[0]
    assert replay.fields["op_id"] == "St0"
    assert replay.fields["value"] == 9
    assert len(_occurring(result, "MSHR.SDQAllocate")) == 1
    assert len(_occurring(result, "MSHR.SDQFree")) == 1
    assert result.final_state["MSHR.req[St0].sdq_valid"] is False
    assert result.final_state["MSHR.req[St0].rpq_valid"] is False


def test_dirty_metadata_path_writebacks_refills_meta_and_finishes() -> None:
    _, _, _, result = _complete_mshr("dirty_writeback_finish")
    assert result.status is CompletionStatus.FEASIBLE
    for event_type in (
        "MSHR.MetaClear",
        "MSHR.WritebackRequest",
        "MSHR.WritebackDone",
        "MSHR.CommitLine",
        "MSHR.RefillWrite",
        "MSHR.MetaWrite",
        "MSHR.MemFinish",
    ):
        assert len(_occurring(result, event_type)) == 1
    assert result.final_state["MSHR[2].state"] == "INVALID"
    assert result.final_state["MSHR[2].grantack_valid"] is False
    assert result.final_state["MSHR[2].probe_rdy"] is True


def test_fence_and_probe_blocking_are_state_guarded() -> None:
    _, _, _, result = _complete_mshr("probe_and_fence_blocked")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "MSHR.FenceBlocked")) == 1
    assert len(_occurring(result, "MSHR.ProbeBlocked")) == 1


def test_iomshr_load_state_machine() -> None:
    _, _, _, result = _complete_mshr("iomshr_load")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "IOMSHR.MemAccess")) == 1
    assert len(_occurring(result, "IOMSHR.MemAck")) == 1
    response = _occurring(result, "IOMSHR.Response")[0]
    assert response.fields["value"] == 77
    assert result.final_state["IOMSHR[5].state"] == "IDLE"


def test_full_boom_bug_still_uses_formal_mshr_and_is_forbidden() -> None:
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "memory_buggy.yaml")
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    types = {
        event.event_type
        for event in result.completed_trace.events
        if event.occurs is True
    }
    assert {
        "MSHR.PrimaryAccept",
        "MSHR.RPQInsert",
        "MSHR.AcquireBlock",
        "MSHR.GrantData",
        "MSHR.LineBufferWrite",
        "MSHR.RefillComplete",
        "MSHR.DirectLoadResponse",
        "MSHR.ResponseEnqueue",
        "MSHR.ResponseDequeue",
    } <= types
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.FORBIDDEN


def test_v013_hierarchy_abstraction_preserves_forbidden_result() -> None:
    from umcm.hierarchy import AbstractionSpec, abstract_trace, check_memory_model_preservation

    concrete = Trace.load(ROOT / "tests" / "regressions" / "boom" / "v0_13" / "load_load_bug_completed.yaml")
    catalog = EventCatalog.load(BOOM / "events.yaml")
    abstraction = AbstractionSpec.load(BOOM / "abstraction" / "hierarchy.yaml")
    abstracted = abstract_trace(concrete, catalog, abstraction).trace
    model = GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml")
    preservation = check_memory_model_preservation(concrete, abstracted, model)
    assert preservation.preserved
    assert preservation.concrete.status is MemoryModelStatus.FORBIDDEN
    assert preservation.abstract.status is MemoryModelStatus.FORBIDDEN
    rf = abstracted.get("rf_StoreGamma_LoadAlpha_mshr")
    assert rf.fields["read_op_id"] == "LoadAlpha"
    assert rf.fields["write_op_id"] == "StoreGamma"
