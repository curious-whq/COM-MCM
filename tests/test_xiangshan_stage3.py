from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.coverage import CoverageSuite, run_coverage
from umcm.coverage.engine import CoverageStatus
from umcm.hierarchy import build_interface_contracts
from umcm.ir import EventCatalog, EventInstance, Trace
from umcm.ir.event import Visibility
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
XIANGSHAN = ROOT / "examples" / "xiangshan"
MMU_TRACES = XIANGSHAN / "traces" / "mmu"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def result(case: str):
    source = Trace.load(MMU_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(XIANGSHAN / "composition" / "dtlb_l1.yaml")
    composed = compose_modules(catalog(), composition, source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


def feasible(case: str) -> Trace:
    completed = result(case)
    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    return completed.completed_trace


def event(
    trace: Trace,
    event_type: str,
    *,
    op_id: str | None = None,
    attempt: int | None = None,
) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    if op_id is not None:
        matches = [item for item in matches if item.fields.get("op_id") == op_id]
    if attempt is not None:
        matches = [item for item in matches if item.fields.get("attempt") == attempt]
    assert len(matches) == 1, (
        event_type,
        op_id,
        attempt,
        [(item.id, item.fields) for item in matches],
    )
    return matches[0]


def test_valid_entry_returns_l1_hit_without_replay() -> None:
    trace = feasible("l1_hit")

    request = event(trace, "MMU.TranslateRequest", op_id="L0", attempt=0)
    lookup = event(trace, "MMU.L1TLBLookup", op_id="L0", attempt=0)
    hit = event(trace, "MMU.L1TLBHit", op_id="L0", attempt=0)
    response = event(trace, "MMU.TranslateResponse", op_id="L0", attempt=0)

    assert request.cycle < lookup.cycle < hit.cycle < response.cycle
    assert response.fields["paddr"] == 8192
    assert response.fields["hit_level"] == "l1"
    assert response.fields["replay"] is False
    assert not list(trace.events_of_type("MMU.PTWRequest"))


def test_miss_replays_then_refill_enables_explicit_retry() -> None:
    trace = feasible("miss_refill_retry")

    first = event(trace, "MMU.TranslateRequest", op_id="L0", attempt=0)
    first_lookup = event(trace, "MMU.L1TLBLookup", op_id="L0", attempt=0)
    miss = event(trace, "MMU.L1TLBMiss", op_id="L0", attempt=0)
    replay = event(trace, "MMU.TranslateResponse", op_id="L0", attempt=0)
    ptw_request = event(trace, "MMU.PTWRequest", op_id="L0")
    ptw_response = event(trace, "MMU.PTWResponse", op_id="L0")
    decision = event(trace, "MMU.L1TLBPTWDecision", op_id="L0", attempt=0)
    refill = event(trace, "MMU.L1TLBRefill", op_id="L0", attempt=0)
    retry = event(trace, "MMU.TranslateRequest", op_id="L0", attempt=1)
    retry_lookup = event(trace, "MMU.L1TLBLookup", op_id="L0", attempt=1)
    retry_hit = event(trace, "MMU.L1TLBHit", op_id="L0", attempt=1)
    retry_response = event(trace, "MMU.TranslateResponse", op_id="L0", attempt=1)

    assert first.cycle < first_lookup.cycle < miss.cycle < replay.cycle
    assert replay.fields["replay"] is True
    assert replay.cycle < ptw_request.cycle < ptw_response.cycle
    assert ptw_response.cycle < decision.cycle < refill.cycle < retry.cycle
    assert retry.cycle < retry_lookup.cycle < retry_hit.cycle < retry_response.cycle
    assert decision.fields["accepted"] is True
    assert ptw_request.fields["txn_id"] == "L0.a0"
    assert retry_response.fields["replay"] is False


def test_matching_sfence_invalidates_before_later_lookup() -> None:
    trace = feasible("sfence_forces_miss")

    sfence = event(trace, "Core.SFence", op_id="F0")
    invalidate = event(trace, "MMU.L1TLBInvalidate")
    lookup = event(trace, "MMU.L1TLBLookup", op_id="L0", attempt=0)
    miss = event(trace, "MMU.L1TLBMiss", op_id="L0", attempt=0)
    response = event(trace, "MMU.TranslateResponse", op_id="L0", attempt=0)

    assert sfence.cycle < invalidate.cycle < lookup.cycle < miss.cycle < response.cycle
    assert invalidate.fields["fence_id"] == "F0"
    assert response.fields["replay"] is True


def test_sfence_drops_inflight_ptw_response_without_refill() -> None:
    trace = feasible("sfence_drops_inflight_refill")

    ptw_request = event(trace, "MMU.PTWRequest", op_id="L0")
    sfence = event(trace, "Core.SFence", op_id="F0")
    pending_flush = event(trace, "MMU.L1TLBPendingFlush", op_id="L0", attempt=0)
    ptw_response = event(trace, "MMU.PTWResponse", op_id="L0")
    decision = event(trace, "MMU.L1TLBPTWDecision", op_id="L0", attempt=0)
    drop = event(trace, "MMU.L1TLBPTWDrop", op_id="L0", attempt=0)

    assert ptw_request.cycle < sfence.cycle < pending_flush.cycle
    assert pending_flush.cycle < ptw_response.cycle < decision.cycle < drop.cycle
    assert decision.fields["accepted"] is False
    assert not list(trace.events_of_type("MMU.L1TLBRefill"))


def test_retry_without_supported_refill_is_unsat() -> None:
    assert result("retry_without_refill").status is CompletionStatus.INFEASIBLE


def test_store_tlb_cannot_hit_from_load_tlb_state() -> None:
    assert result("store_does_not_share_load_tlb").status is CompletionStatus.INFEASIBLE


def test_stage3_interface_inventory_and_private_encapsulation() -> None:
    source = Trace.load(MMU_TRACES / "l1_hit.yaml")
    composition = CompositionSpec.load(XIANGSHAN / "composition" / "dtlb_l1.yaml")
    composed = compose_modules(catalog(), composition, source)
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": composition.name,
        "policy": "ports-only-public-surface",
        "modules": [contract.to_dict() for contract in build_interface_contracts(composed)],
    }
    assert load_data(XIANGSHAN / "hierarchy" / "dtlb_l1_interfaces.yaml") == expected

    for path in MMU_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage3_source_metadata_is_pinned() -> None:
    source = Trace.load(MMU_TRACES / "l1_hit.yaml")
    composition = CompositionSpec.load(XIANGSHAN / "composition" / "dtlb_l1.yaml")
    module = compose_modules(catalog(), composition, source).modules[0].spec
    assert module.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert module.metadata["source_files"] == [
        "src/main/scala/xiangshan/cache/mmu/TLB.scala:39-83,251-300,303-411,556-601,701-733,821",
        "src/main/scala/xiangshan/cache/mmu/TLBStorage.scala:86-200,203-230",
        "src/main/scala/xiangshan/cache/mmu/Repeater.scala:163-390",
        "src/main/scala/xiangshan/mem/MemBlock.scala:582-590,602-652,681-724",
        "src/main/scala/xiangshan/cache/mmu/MMUConst.scala:27-42",
        "src/main/scala/top/Configs.scala:199-240",
    ]


def test_stage3_required_path_coverage_is_complete() -> None:
    suite = CoverageSuite.load(XIANGSHAN / "coverage" / "stage3.yaml")
    report = run_coverage(suite, backend="z3")
    assert report.required_complete
    assert [item.status for item in report.results] == [
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
    ]
