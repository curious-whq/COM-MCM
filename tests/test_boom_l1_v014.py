from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.hierarchy import AbstractionSpec, abstract_trace, check_memory_model_preservation
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace

ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"


def _complete_l1(name: str):
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / "l1" / f"{name}.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "l1.yaml")
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


def test_load_hit_runs_s0_s1_s2_and_returns_data() -> None:
    _, _, _, result = _complete_l1("load_hit")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "L1.MetaDataRead")) == 1
    assert len(_occurring(result, "L1.PipelineS1")) == 1
    assert len(_occurring(result, "L1.PipelineS2")) == 1
    assert _occurring(result, "DCache.LoadHit")[0].fields["value"] == 42
    assert _occurring(result, "DCache.LoadResponse")[0].fields["value"] == 42


def test_data_bank_conflict_becomes_nack() -> None:
    _, _, _, result = _complete_l1("load_nack_data_bank")
    assert result.status is CompletionStatus.FEASIBLE
    cause = _occurring(result, "L1.NackCause")[0]
    assert cause.fields["cause"] == "data_bank"
    assert len(_occurring(result, "DCache.LoadNack")) == 1
    assert not _occurring(result, "DCache.LoadResponse")


def test_load_miss_dispatches_to_mshr_interface() -> None:
    _, _, _, result = _complete_l1("load_miss_mshr")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "DCache.LoadMiss")) == 1
    request = _occurring(result, "DCache.MSHRRequest")[0]
    assert request.fields["op_id"] == "L0"


def test_clean_probe_releases_lsu_and_updates_metadata() -> None:
    _, _, _, result = _complete_l1("probe_clean")
    assert result.status is CompletionStatus.FEASIBLE
    for event_type in (
        "DCache.ProbeReceive",
        "L1.ProbeMetaRead",
        "L1.ProbeMSHRCheck",
        "DCache.ProbeRelease",
        "L1.ProbeAck",
        "L1.ProbeMetaWrite",
    ):
        assert len(_occurring(result, event_type)) == 1
    assert result.final_state["L1.probe.busy"] is False


def test_dirty_probe_routes_through_writeback_unit() -> None:
    _, _, _, result = _complete_l1("probe_dirty")
    assert result.status is CompletionStatus.FEASIBLE
    order = [
        "L1.ProbeWritebackRequest",
        "L1.WritebackAccept",
        "L1.WritebackFill",
        "L1.WritebackLSURelease",
        "L1.WritebackTLRelease",
        "L1.WritebackDone",
        "L1.ProbeMetaWrite",
    ]
    cycles = [_occurring(result, kind)[0].cycle for kind in order]
    assert cycles == sorted(cycles)
    assert result.final_state["L1.writeback.busy"] is False


def test_probe_miss_does_not_write_metadata() -> None:
    _, _, _, result = _complete_l1("probe_miss")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "DCache.ProbeRelease")) == 1
    assert len(_occurring(result, "L1.ProbeAck")) == 1
    assert not _occurring(result, "L1.ProbeMetaWrite")


def test_store_hit_acks_and_writes_data_array() -> None:
    _, _, _, result = _complete_l1("store_hit")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "L1.StoreHit")) == 1
    assert len(_occurring(result, "DCache.StoreAck")) == 1
    write = _occurring(result, "L1.StoreDataWrite")[0]
    assert write.fields["value"] == 9


def test_store_load_bypass_requires_temporally_prior_store_write() -> None:
    _, _, _, result = _complete_l1("store_load_bypass")
    assert result.status is CompletionStatus.FEASIBLE
    bypass = _occurring(result, "L1.StoreLoadBypass")[0]
    assert bypass.fields["store_op_id"] == "S0"
    assert bypass.fields["load_op_id"] == "L0"
    store_write = _occurring(result, "L1.StoreDataWrite")[0]
    load_s2 = next(
        event
        for event in _occurring(result, "L1.PipelineS2")
        if event.fields["op_id"] == "L0"
    )
    assert store_write.cycle <= load_s2.cycle


def test_store_mshr_replay_writes_cache_but_does_not_emit_second_ack() -> None:
    _, trace, _, result = _complete_l1("mshr_replay_store")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "L1.MSHRReplayS1")) == 1
    assert len(_occurring(result, "L1.MSHRReplayS2")) == 1
    assert len(_occurring(result, "L1.StoreDataWrite")) == 1
    # No StoreAck is requested in this replay-only trace; replay itself must not
    # synthesize one.  The initial store-miss ack belongs to the original miss.
    assert not [e for e in result.completed_trace.events if e.event_type == "DCache.StoreAck" and e.id not in {x.id for x in trace.events} and e.occurs is True]


def test_mshr_eviction_uses_writeback_unit_and_releases_lsu() -> None:
    _, _, _, result = _complete_l1("mshr_eviction_writeback")
    assert result.status is CompletionStatus.FEASIBLE
    assert len(_occurring(result, "L1.WritebackAccept")) == 1
    assert len(_occurring(result, "L1.WritebackLSURelease")) == 1
    assert len(_occurring(result, "L1.WritebackTLRelease")) == 1
    assert len(_occurring(result, "L1.WritebackDone")) == 1


def test_lr_sc_reservation_success_and_clear() -> None:
    _, _, _, result = _complete_l1("lr_sc_success")
    assert result.status is CompletionStatus.FEASIBLE
    lr = _occurring(result, "L1.LRReservationSet")[0]
    sc = _occurring(result, "L1.SCResult")[0]
    assert lr.fields["address"] == sc.fields["address"] == "x"
    assert sc.fields["success"] is True
    assert result.final_state["L1.lrsc.valid"] is False


def test_full_boom_bug_uses_formal_l1_and_remains_forbidden() -> None:
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "memory_buggy.yaml")
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    types = {event.event_type for event in result.completed_trace.events if event.occurs is True}
    assert {
        "L1.MetaDataRead",
        "L1.PipelineS1",
        "L1.PipelineS2",
        "DCache.LoadHit",
        "DCache.LoadMiss",
        "L1.ProbeMetaRead",
        "L1.ProbeMSHRCheck",
        "DCache.ProbeRelease",
        "L1.ProbeAck",
    } <= types
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.FORBIDDEN


def test_full_fixed_model_remains_allowed_and_bad_commit_is_blocked() -> None:
    catalog = EventCatalog.load(BOOM / "events.yaml")
    recovery = Trace.load(BOOM / "traces" / "load_load_fixed_reference.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "memory_fixed_reference.yaml")
    composed = compose_modules(catalog, composition, recovery)
    result = complete_trace(catalog, recovery, composed.completion, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    checked = check_trace_memory_model(
        result.completed_trace,
        GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.ALLOWED

    bad = Trace.load(BOOM / "traces" / "load_load_bug.yaml")
    composed_bad = compose_modules(catalog, composition, bad)
    blocked = complete_trace(catalog, bad, composed_bad.completion, backend="z3")
    assert blocked.status is CompletionStatus.INFEASIBLE


def test_v014_hierarchy_preserves_formal_l1_forbidden_result() -> None:
    catalog = EventCatalog.load(BOOM / "events.yaml")
    concrete = Trace.load(ROOT / "tests" / "regressions" / "boom" / "v0_14" / "load_load_bug_completed.yaml")
    abstraction = AbstractionSpec.load(BOOM / "abstraction" / "hierarchy.yaml")
    abstracted = abstract_trace(concrete, catalog, abstraction).trace
    model = GraphModelSpec.load(BOOM / "axioms" / "rvwmo_load_load_fragment.yaml")
    preservation = check_memory_model_preservation(concrete, abstracted, model)
    assert preservation.preserved
    assert preservation.concrete.status is MemoryModelStatus.FORBIDDEN
    assert preservation.abstract.status is MemoryModelStatus.FORBIDDEN
