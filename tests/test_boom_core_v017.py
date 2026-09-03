from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from umcm.composition.engine import compose_modules
from umcm.composition.model import CompositionSpec
from umcm.graph.model import GraphModelSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"
CORE_TRACES = BOOM / "traces" / "core"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(BOOM / "events.yaml")


@lru_cache(maxsize=None)
def completed(case: str) -> Trace:
    source = Trace.load(CORE_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "core_side_v017.yaml")
    model = compose_modules(catalog(), composition, source).completion
    result = complete_trace(catalog(), source, model, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE, result.reason
    assert result.completed_trace is not None
    return result.completed_trace


def event(
    trace: Trace,
    event_type: str,
    op_id: str | None = None,
    attempt: int | None = None,
):
    matches = list(trace.events_of_type(event_type))
    if op_id is not None:
        matches = [item for item in matches if item.fields.get("op_id") == op_id]
    if attempt is not None:
        matches = [item for item in matches if item.fields.get("attempt") == attempt]
    assert len(matches) == 1, (event_type, op_id, attempt, [item.id for item in matches])
    return matches[0]


def test_core_composition_uses_only_declared_public_boundaries() -> None:
    source = Trace.load(CORE_TRACES / "amo_hit.yaml")
    result = compose_modules(
        catalog(),
        CompositionSpec.load(BOOM / "composition" / "core_side_v017.yaml"),
        source,
    )
    assert len(result.modules) == 9
    assert len(result.spec.connections) == 10
    for connection in result.spec.connections:
        source_module = next(item.spec for item in result.modules if item.reference_name == connection.source.module)
        target_module = next(item.spec for item in result.modules if item.reference_name == connection.target.module)
        assert connection.source.port in source_module.port_map
        assert connection.target.port in target_module.port_map
    private = result.completion.metadata["hierarchy"]["modules"]["boom_v4_nbdtlb"]
    assert "NBDTLB.entry[h0_v2].valid" in private["private_state_names"]
    assert "NBDTLB[0].state" in private["private_state_names"]


def test_tlb_miss_refill_and_retry_are_derived_not_supplied() -> None:
    source = Trace.load(CORE_TRACES / "tlb_retry_mmio_load.yaml")
    assert not any(item.event_type.startswith("TLB.") for item in source.events)
    trace = completed("tlb_retry_mmio_load")
    decision = event(trace, "TLB.Decision", "IO_LOAD", attempt=0)
    retry_decision = event(trace, "TLB.Decision", "IO_LOAD", attempt=1)
    miss = event(trace, "TLB.Miss", "IO_LOAD")
    refill = event(trace, "TLB.Refill", "IO_LOAD")
    retry = event(trace, "TLB.Retry", "IO_LOAD")
    translated = event(trace, "Core.TranslatedMemory", "IO_LOAD")
    assert decision.fields["hit"] is False
    assert retry_decision.fields["hit"] is True
    assert translated.fields["tlb_path"] == "retry"
    assert decision.cycle < miss.cycle < refill.cycle < retry.cycle
    assert retry.cycle < retry_decision.cycle < translated.cycle


def test_initially_valid_entry_derives_hit_and_amo_is_atomic() -> None:
    trace = completed("amo_hit")
    decision = event(trace, "TLB.Decision", "A0", attempt=0)
    read = event(trace, "Atomic.AMORead", "A0")
    write = event(trace, "Atomic.AMOWrite", "A0")
    done = event(trace, "Core.MemoryComplete", "A0")
    commit = event(trace, "ROB.Commit", "A0")
    arch = event(trace, "Arch.AMO", "A0")
    assert decision.fields["hit"] is True
    assert not list(trace.events_of_type("TLB.Miss"))
    assert done.fields["success"] is True
    assert read.cycle < write.cycle < done.cycle < commit.cycle < arch.cycle


def test_same_vpn_uses_independent_per_hart_tlb_state() -> None:
    trace = completed("tlb_two_hart_isolation")
    h0 = event(trace, "TLB.Decision", "H0_LOAD", attempt=0)
    h1 = event(trace, "TLB.Decision", "H1_LOAD", attempt=0)
    assert h0.fields["hit"] is True
    assert h1.fields["hit"] is False
    assert event(trace, "Core.TranslatedMemory", "H0_LOAD").fields["tlb_path"] == "hit"
    assert event(trace, "Core.TranslatedMemory", "H1_LOAD").fields["tlb_path"] == "retry"


def test_sfence_invalidates_hit_and_forces_source_grounded_retry() -> None:
    trace = completed("sfence_tlb_retry")
    sfence = event(trace, "TLB.SFence")
    invalidate = event(trace, "TLB.Invalidate")
    initial = event(trace, "TLB.Decision", "AFTER_SFENCE", attempt=0)
    retried = event(trace, "TLB.Decision", "AFTER_SFENCE", attempt=1)
    assert initial.fields["hit"] is False
    assert retried.fields["hit"] is True
    assert sfence.cycle < invalidate.cycle < initial.cycle
    assert event(trace, "Core.TranslatedMemory", "AFTER_SFENCE").fields["tlb_path"] == "retry"


def test_tlb_metadata_is_pinned_to_official_boom_v4_source() -> None:
    source = Trace.load(CORE_TRACES / "amo_hit.yaml")
    result = compose_modules(
        catalog(),
        CompositionSpec.load(BOOM / "composition" / "core_side_v017.yaml"),
        source,
    )
    module = next(item.spec for item in result.modules if item.reference_name == "boom_v4_nbdtlb")
    assert module.metadata["source_commit"] == "58ef2720eae13be26b3008c02b5a74ce29c61c44"
    assert "src/main/scala/v4/lsu/tlb.scala:18-373" in module.metadata["source_files"]
    retry = next(item.spec for item in result.modules if item.reference_name == "boom_v4_lsu_translation")
    assert "src/main/scala/v4/lsu/lsu.scala:506-547,595-606,644-830,890-905,960-984" in retry.metadata["source_files"]


def test_lr_sc_success_is_state_derived_and_paired() -> None:
    trace = completed("lr_sc_success")
    reservation = event(trace, "Atomic.ReservationSet", "LR0")
    decision = event(trace, "Atomic.SCDecision", "SC0")
    write = event(trace, "Atomic.SCWrite", "SC0")
    pair = event(trace, "Arch.LRSCPair")
    assert decision.fields["success"] is True
    assert reservation.cycle < decision.cycle < write.cycle
    assert pair.fields == {"source_op_id": "LR0", "target_op_id": "SC0"}


def test_probe_invalidates_lr_and_forces_sc_failure() -> None:
    trace = completed("lr_probe_sc_fail")
    reservation = event(trace, "Atomic.ReservationSet", "LR1")
    probe = event(trace, "Core.ReservationInvalidate")
    decision = event(trace, "Atomic.SCDecision", "SC1")
    failure = event(trace, "Arch.SCFailure", "SC1")
    assert reservation.cycle < probe.cycle < decision.cycle < failure.cycle
    assert decision.fields["success"] is False
    assert not [item for item in trace.events_of_type("Atomic.SCWrite") if item.fields["op_id"] == "SC1"]
    assert not [item for item in trace.events_of_type("Arch.SC") if item.fields["op_id"] == "SC1"]


def test_precise_page_fault_waits_for_older_commit_and_squashes_tail() -> None:
    trace = completed("precise_page_fault")
    older_commit = event(trace, "ROB.Commit", "OLD")
    precise = event(trace, "ROB.PreciseException", "FAULT")
    fault_squash = event(trace, "Core.SquashMemory", "FAULT")
    younger_squash = event(trace, "Core.SquashMemory", "YOUNG")
    assert older_commit.cycle < precise.cycle < fault_squash.cycle
    assert precise.cycle < younger_squash.cycle
    committed_ids = {item.fields["op_id"] for item in trace.events_of_type("ROB.Commit")}
    assert committed_ids == {"OLD"}


def test_fence_waits_for_public_ordered_observation_before_commit() -> None:
    trace = completed("fence_wait")
    fence = event(trace, "Arch.Fence", "F0")
    ordered = event(trace, "DCache.Ordered")
    done = event(trace, "Core.MemoryComplete", "F0")
    commit = event(trace, "ROB.Commit", "F0")
    retired = event(trace, "Arch.CommitFence", "F0")
    assert fence.cycle < ordered.cycle < done.cycle < commit.cycle < retired.cycle


def test_uncacheable_load_and_store_use_distinct_iomshr_completion_rules() -> None:
    load = completed("tlb_retry_mmio_load")
    assert event(load, "IOMSHR.Request", "IO_LOAD").cycle < event(load, "IOMSHR.Response", "IO_LOAD").cycle
    store = completed("mmio_store")
    request = event(store, "IOMSHR.Request", "IO_STORE")
    ack = event(store, "IOMSHR.MemAck", "IO_STORE")
    done = event(store, "Core.MemoryComplete", "IO_STORE")
    assert request.cycle < ack.cycle < done.cycle
    assert not list(store.events_of_type("IOMSHR.Response"))


def test_branch_recovery_squashes_and_broadcasts_kill_without_commit() -> None:
    trace = completed("branch_recovery")
    branch = event(trace, "Core.BranchMispredict")
    squash = event(trace, "Core.SquashMemory", "SPEC")
    kill = event(trace, "Core.BranchKill", "SPEC")
    assert branch.cycle < squash.cycle
    assert branch.cycle < kill.cycle
    assert not list(trace.events_of_type("ROB.Commit"))


def test_boom_rvwmo_projection_includes_atomic_events_and_lrsc_pair() -> None:
    model = GraphModelSpec.load(BOOM / "axioms" / "rvwmo.yaml")
    assert model.projection.amo_event == "Arch.AMO"
    assert model.projection.lr_event == "Arch.LR"
    assert model.projection.sc_event == "Arch.SC"
    pair = next(item for item in model.projection.relation_hints if item.name == "pair")
    assert pair.event_type == "Arch.LRSCPair"
