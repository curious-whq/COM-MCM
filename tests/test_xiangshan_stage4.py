from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

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
COMPOSITION = XIANGSHAN / "composition" / "translation_backend.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def result(case: str):
    source = Trace.load(MMU_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(COMPOSITION)
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
    txn_id: str | None = None,
    check_kind: str | None = None,
    stage: str | None = None,
) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    if txn_id is not None:
        matches = [item for item in matches if item.fields.get("txn_id") == txn_id]
    if check_kind is not None:
        matches = [item for item in matches if item.fields.get("check_kind") == check_kind]
    if stage is not None:
        matches = [item for item in matches if item.fields.get("stage") == stage]
    assert len(matches) == 1, (event_type, txn_id, check_kind, stage, matches)
    return matches[0]


def test_l2_hit_resolves_without_page_walk() -> None:
    trace = feasible("l2_hit")
    lookup = event(trace, "MMU.L2TLBLookup", txn_id="L0.a0")
    hit = event(trace, "MMU.L2TLBHit", txn_id="L0.a0")
    response = event(trace, "MMU.PTWResponse", txn_id="L0.a0")

    assert lookup.cycle < hit.cycle < response.cycle
    assert response.fields["paddr"] == 8192
    assert response.fields["fault"] is False
    assert not list(trace.events_of_type("MMU.PTWWalk"))


def test_l2_miss_walks_refills_then_responds() -> None:
    trace = feasible("ptw_refill")
    miss = event(trace, "MMU.L2TLBMiss", txn_id="L0.a0")
    walk = event(trace, "MMU.PTWWalk", txn_id="L0.a0", stage="s1")
    refill = event(trace, "MMU.L2TLBRefill", txn_id="L0.a0")
    response = event(trace, "MMU.PTWResponse", txn_id="L0.a0")

    assert miss.cycle < walk.cycle < refill.cycle < response.cycle


def test_integrated_l1_to_backend_refill_retry_path() -> None:
    source = Trace.load(MMU_TRACES / "end_to_end_refill.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "translation_path.yaml"
    )
    composed = compose_modules(catalog(), composition, source)
    completed = complete_trace(catalog(), source, composed.completion, backend="z3")

    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    trace = completed.completed_trace
    l1_miss = event(trace, "MMU.L1TLBMiss")
    l2_miss = event(trace, "MMU.L2TLBMiss", txn_id="L0.a0")
    l2_refill = event(trace, "MMU.L2TLBRefill", txn_id="L0.a0")
    ptw_response = event(trace, "MMU.PTWResponse", txn_id="L0.a0")
    l1_refill = event(trace, "MMU.L1TLBRefill")
    retry_hit = [
        item
        for item in trace.events_of_type("MMU.L1TLBHit")
        if item.fields.get("attempt") == 1
    ]

    assert len(retry_hit) == 1
    assert l1_miss.cycle < l2_miss.cycle < l2_refill.cycle
    assert l2_refill.cycle < ptw_response.cycle < l1_refill.cycle
    assert l1_refill.cycle < retry_hit[0].cycle


def test_two_stage_translation_orders_vs_before_g_stage() -> None:
    trace = feasible("two_stage_translation")
    s1_walk = event(trace, "MMU.PTWWalk", txn_id="GL0.a0", stage="s1")
    s1_done = event(trace, "MMU.PTWStageComplete", txn_id="GL0.a0", stage="s1")
    s2_walk = event(trace, "MMU.PTWWalk", txn_id="GL0.a0", stage="s2")
    s2_done = event(trace, "MMU.PTWStageComplete", txn_id="GL0.a0", stage="s2")
    response = event(trace, "MMU.PTWResponse", txn_id="GL0.a0")

    assert s1_walk.cycle < s1_done.cycle < s2_walk.cycle < s2_done.cycle
    assert s2_done.cycle < response.cycle
    assert response.fields["gpaddr"] == 12288
    assert response.fields["paddr"] == 32768


@pytest.mark.parametrize(
    ("case", "txn_id", "cause"),
    [
        ("page_fault", "PF0.a0", "load_page_fault"),
        ("guest_page_fault", "GPF0.a0", "load_guest_page_fault"),
    ],
)
def test_page_walk_fault_class(case: str, txn_id: str, cause: str) -> None:
    trace = feasible(case)
    fault = event(trace, "MMU.TranslationFault", txn_id=txn_id)
    response = event(trace, "MMU.PTWResponse", txn_id=txn_id)

    assert fault.cycle < response.cycle
    assert response.fields["fault"] is True
    assert response.fields["cause"] == cause
    assert not list(trace.events_of_type("MMU.ProtectionCheck"))


@pytest.mark.parametrize(
    ("case", "txn_id", "denied_kind"),
    [
        ("pmp_access_fault", "PMP0.a0", "pmp"),
        ("pma_access_fault", "PMA0.a0", "pma"),
        ("bitmap_access_fault", "BITMAP0.a0", "bitmap"),
        ("mpt_access_fault", "MPT0.a0", "mpt"),
    ],
)
def test_protection_denial_becomes_access_fault(
    case: str, txn_id: str, denied_kind: str
) -> None:
    trace = feasible(case)
    denied = event(trace, "MMU.ProtectionCheck", txn_id=txn_id, check_kind=denied_kind)
    response = event(trace, "MMU.PTWResponse", txn_id=txn_id)

    assert denied.fields["allowed"] is False
    assert response.fields["fault"] is True
    assert response.fields["cause"] == "load_access_fault"


def test_hfence_invalidates_combined_entry_before_forced_miss() -> None:
    trace = feasible("hfence_forces_l2_miss")
    invalidate = event(trace, "MMU.L2TLBInvalidate")
    lookup = event(trace, "MMU.L2TLBLookup", txn_id="HFLOAD0.a0")
    miss = event(trace, "MMU.L2TLBMiss", txn_id="HFLOAD0.a0")

    assert invalidate.fields["fence_id"] == "HF0"
    assert invalidate.cycle < lookup.cycle < miss.cycle


def test_wrong_public_translation_response_is_unsat() -> None:
    assert result("wrong_translation_response").status is CompletionStatus.INFEASIBLE


def test_stage4_interface_inventory_and_private_encapsulation() -> None:
    source = Trace.load(MMU_TRACES / "l2_hit.yaml")
    composition = CompositionSpec.load(COMPOSITION)
    composed = compose_modules(catalog(), composition, source)
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": composition.name,
        "policy": "ports-only-public-surface",
        "modules": [contract.to_dict() for contract in build_interface_contracts(composed)],
    }
    assert load_data(XIANGSHAN / "hierarchy" / "translation_backend_interfaces.yaml") == expected

    for path in MMU_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage4_source_metadata_is_pinned() -> None:
    source = Trace.load(MMU_TRACES / "l2_hit.yaml")
    composition = CompositionSpec.load(COMPOSITION)
    module = compose_modules(catalog(), composition, source).modules[0].spec
    assert module.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert module.metadata["source_files"] == [
        "src/main/scala/xiangshan/cache/mmu/L2TLB.scala:61-180,220-241,320-459,476-620,758-864",
        "src/main/scala/xiangshan/cache/mmu/L2TLBMissQueue.scala:30-45",
        "src/main/scala/xiangshan/cache/mmu/PageTableCache.scala:120-389,588-874,1068-1284",
        "src/main/scala/xiangshan/cache/mmu/PageTableWalker.scala:104-802,804-1389,1391-1729",
        "src/main/scala/xiangshan/cache/mmu/MMUBundle.scala:780-900,920-1005,1163-1235,1405-1501",
        "src/main/scala/xiangshan/cache/mmu/BitmapCheck.scala:31-104,124-358,364-517",
        "src/main/scala/xiangshan/cache/mmu/MptChecker.scala:31-151,758-947,1175-1347",
        "src/main/scala/xiangshan/backend/fu/PMP.scala:190-289,368-520",
        "src/main/scala/xiangshan/backend/fu/PMA.scala:201-265",
        "src/main/scala/xiangshan/Parameters.scala:48-80,665-681",
        "src/main/scala/top/Configs.scala:241-251",
    ]


def test_stage4_required_path_coverage_is_complete() -> None:
    suite = CoverageSuite.load(XIANGSHAN / "coverage" / "stage4.yaml")
    report = run_coverage(suite, backend="z3")
    assert report.required_complete
    assert [item.status for item in report.results] == [CoverageStatus.COVERED] * 10
