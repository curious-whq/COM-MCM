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
PSQ_TRACES = XIANGSHAN / "traces" / "physical_store_queue"
PSQ_COMPOSITION = XIANGSHAN / "composition" / "physical_store_queue.yaml"
INTEGRATED_COMPOSITION = XIANGSHAN / "composition" / "scalar_store_physical_queue.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def psq_result(case: str):
    source = Trace.load(PSQ_TRACES / f"{case}.yaml")
    composed = compose_modules(catalog(), CompositionSpec.load(PSQ_COMPOSITION), source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


def feasible(result) -> Trace:
    assert result.status is CompletionStatus.FEASIBLE, result.reason
    assert result.completed_trace is not None
    return result.completed_trace


def event(trace: Trace, event_type: str, **fields: object) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    for name, value in fields.items():
        matches = [item for item in matches if item.fields.get(name) == value]
    assert len(matches) == 1, (event_type, fields, [(x.id, x.fields) for x in matches])
    return matches[0]


def test_physical_entry_pairs_payloads_before_commit_and_drain() -> None:
    trace = feasible(psq_result("aligned_drain"))
    address = event(trace, "SQ.AddressWrite", op_id="S0")
    data = event(trace, "SQ.DataWrite", op_id="S0")
    ready = event(trace, "SQ.EntryReady", op_id="S0")
    commit = event(trace, "SQ.Commit", op_id="S0")
    drain = event(trace, "Store.Drain", op_id="S0", beat=0)
    assert address.cycle < ready.cycle and data.cycle < ready.cycle
    assert ready.cycle < commit.cycle < drain.cycle
    assert drain.fields["address"] == 8192
    assert drain.fields["value"] == 170
    assert drain.fields["byte_mask"] == 15


def test_partial_mask_and_youngest_store_forwarding() -> None:
    partial = feasible(psq_result("forward_partial"))
    response = event(partial, "Store.ForwardResponse", op_id="LF")
    assert response.fields["source_op_id"] == "SF"
    assert response.fields["byte_mask"] == 12
    assert response.fields["value"] == 2864434397
    assert response.fields["match"] and not response.fields["data_invalid"]

    youngest = feasible(psq_result("forward_youngest"))
    candidates = list(youngest.events_of_type("SQ.ForwardSelect"))
    assert [x.fields["source_op_id"] for x in sorted(candidates, key=lambda x: x.cycle)] == [
        "SO",
        "SY",
    ]
    response = event(youngest, "Store.ForwardResponse", op_id="LY")
    assert response.fields["source_op_id"] == "SY"
    assert response.fields["value"] == 34


def test_forward_data_invalid_and_disjoint_miss_are_distinct() -> None:
    invalid = event(
        feasible(psq_result("forward_data_invalid")),
        "Store.ForwardResponse",
        op_id="LI",
    )
    assert invalid.fields["match"] and invalid.fields["data_invalid"]
    assert invalid.fields["source_op_id"] == "SI"

    miss = event(feasible(psq_result("forward_miss")), "Store.ForwardResponse", op_id="LM")
    assert not miss.fields["match"] and not miss.fields["data_invalid"]
    assert miss.fields["byte_mask"] == 0


def test_unaligned_normalization_and_split_preserve_beats() -> None:
    within = feasible(psq_result("within16_drain"))
    only = event(within, "Store.Drain", op_id="SW", beat=0)
    assert only.fields["last"] is True
    assert only.fields["address"] == 8192 and only.fields["byte_mask"] == 24

    cross = feasible(psq_result("cross16_drain"))
    low = event(cross, "Store.Drain", op_id="SX", beat=0)
    high = event(cross, "Store.Drain", op_id="SX", beat=1)
    assert (low.fields["address"], low.fields["byte_mask"], low.fields["last"]) == (
        8192,
        61440,
        False,
    )
    assert (high.fields["address"], high.fields["byte_mask"], high.fields["last"]) == (
        8208,
        15,
        True,
    )

    page = feasible(psq_result("cross_page_drain"))
    tail = event(page, "Store.UnalignedTailReady", op_id="SP")
    high = event(page, "Store.Drain", op_id="SP", beat=1)
    assert tail.fields["address"] == high.fields["address"] == 20480
    assert high.fields["cross_page"] is True


def test_redirect_reclaims_uncommitted_physical_entry() -> None:
    trace = feasible(psq_result("redirect_reclaims"))
    redirect = event(trace, "Core.Redirect")
    cancel = event(trace, "SQ.PhysicalCancel", op_id="SR")
    assert cancel.cycle == redirect.cycle + 1
    assert cancel.fields["cause"] == "branch_mispredict"
    assert not list(trace.events_of_type("Store.Drain"))


@pytest.mark.parametrize(
    "case",
    [
        "wrong_forward_source",
        "uncommitted_drain",
        "drain_before_commit",
        "cross_page_missing_tail",
        "redirect_late_address",
        "younger_cannot_bypass_head",
    ],
)
def test_illegal_physical_queue_behaviors_are_unsat(case: str) -> None:
    assert psq_result(case).status is CompletionStatus.INFEASIBLE


def test_stage8_store_pipeline_closes_through_stage9_drain() -> None:
    source = Trace.load(XIANGSHAN / "traces" / "store" / "integrated_psq_drain.yaml")
    spec = CompositionSpec.load(INTEGRATED_COMPOSITION)
    composed = compose_modules(catalog(), spec, source)
    trace = feasible(complete_trace(catalog(), source, composed.completion, backend="z3"))
    writeback = event(trace, "Core.MemoryWriteback", op_id="PSQINT")
    commit = event(trace, "SQ.Commit", op_id="PSQINT")
    drain = event(trace, "Store.Drain", op_id="PSQINT", beat=0)
    assert writeback.cycle < commit.cycle < drain.cycle
    assert drain.fields["address"] == 8200 and drain.fields["value"] == 42


def test_stage9_interface_inventories_and_private_encapsulation() -> None:
    cases = [
        (
            PSQ_COMPOSITION,
            PSQ_TRACES / "forward_youngest.yaml",
            XIANGSHAN / "hierarchy" / "physical_store_queue_interfaces.yaml",
        ),
        (
            INTEGRATED_COMPOSITION,
            XIANGSHAN / "traces" / "store" / "integrated_psq_drain.yaml",
            XIANGSHAN / "hierarchy" / "scalar_store_physical_queue_interfaces.yaml",
        ),
    ]
    for composition_path, trace_path, inventory_path in cases:
        source = Trace.load(trace_path)
        composition = CompositionSpec.load(composition_path)
        composed = compose_modules(catalog(), composition, source)
        expected = {
            "schema_version": "umcm.interfaces.v0.15.0",
            "composition": composition.name,
            "policy": "ports-only-public-surface",
            "modules": [x.to_dict() for x in build_interface_contracts(composed)],
        }
        assert load_data(inventory_path) == expected

    for path in PSQ_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage9_source_metadata_is_pinned() -> None:
    source = Trace.load(PSQ_TRACES / "aligned_drain.yaml")
    module = compose_modules(
        catalog(), CompositionSpec.load(PSQ_COMPOSITION), source
    ).modules[0].spec
    assert module.metadata["source_commit"] == "50cdcfc2c45d0631591310435835c0180c105489"
    assert module.metadata["parameters"] == {
        "physical_store_queue_size": 64,
        "commit_width": 4,
        "ensbuffer_width": 2,
        "vector_length_bytes": 16,
        "unalign_queue_size": 2,
    }
    assert module.metadata["source_files"][0] == (
        "src/main/scala/xiangshan/mem/lsqueue/NewStoreQueue.scala:34-178,180-246,247-662,664-807,809-1389,1392-1471,1473-1581,1584-2081"
    )


def test_stage9_required_path_coverage_is_complete() -> None:
    report = run_coverage(CoverageSuite.load(XIANGSHAN / "coverage" / "stage9.yaml"), backend="z3")
    assert report.required_complete
    assert [x.status for x in report.results] == [CoverageStatus.COVERED] * 12
