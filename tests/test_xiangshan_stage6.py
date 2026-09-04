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
LQ_TRACES = XIANGSHAN / "traces" / "load_queue"
LQ_COMPOSITION = XIANGSHAN / "composition" / "load_queue.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def result(case: str):
    source = Trace.load(LQ_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(LQ_COMPOSITION)
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
    **field_values: object,
) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    for field, value in field_values.items():
        matches = [item for item in matches if item.fields.get(field) == value]
    assert len(matches) == 1, (
        event_type,
        field_values,
        [(item.id, item.fields) for item in matches],
    )
    return matches[0]


def test_success_and_replay_have_distinct_vlq_lifetimes() -> None:
    completed = feasible("normal_release")
    allocate = event(completed, "LQ.Allocate", op_id="L0")
    update = event(completed, "Load.PipelineUpdate", op_id="L0")
    deallocate = event(completed, "LQ.Deallocate", op_id="L0")
    assert allocate.cycle < update.cycle < deallocate.cycle
    assert deallocate.fields["path"] == "completion"

    replay = feasible("replay_retains_entry")
    event(replay, "LQ.Allocate", op_id="LREP")
    assert not list(replay.events_of_type("LQ.Deallocate"))


def test_redirect_reclaims_live_vlq_entry() -> None:
    trace = feasible("redirect_reclaims")
    redirect = event(trace, "Core.Redirect", source_op_id="OLD")
    deallocate = event(trace, "LQ.Deallocate", op_id="LKILL")
    assert redirect.cycle < deallocate.cycle
    assert deallocate.fields["path"] == "redirect"
    assert deallocate.fields["cause"] == "branch_mispredict"


def test_completed_vlq_entries_reclaim_in_program_order() -> None:
    trace = feasible("in_order_dequeue")
    older_update = event(trace, "Load.PipelineUpdate", op_id="LHEAD")
    younger_update = event(trace, "Load.PipelineUpdate", op_id="LTAIL")
    older_deallocate = event(trace, "LQ.Deallocate", op_id="LHEAD")
    younger_deallocate = event(trace, "LQ.Deallocate", op_id="LTAIL")

    assert younger_update.cycle < older_update.cycle
    assert older_deallocate.cycle < younger_deallocate.cycle


def test_rar_release_violation_uses_flush_after() -> None:
    trace = feasible("rar_violation")
    track = event(trace, "LQ.RARTrack", path="tracked")
    released = event(trace, "LQ.RARTrack", path="released")
    violation = event(trace, "LQ.RARViolation")
    report = event(trace, "Core.MemoryViolation", cause="rar")
    redirect = event(trace, "Core.Redirect", cause="rar")

    assert track.cycle < released.cycle < violation.cycle < report.cycle < redirect.cycle
    assert redirect.fields["source_op_id"] == "LOLD"
    assert redirect.fields["target_op_id"] == "LYNG"
    assert redirect.fields["flush_self"] is False
    assert not [
        item
        for item in trace.events_of_type("LQ.Deallocate")
        if item.fields.get("op_id") == "LOLD"
    ]
    event(trace, "LQ.Deallocate", op_id="LYNG", path="redirect")


def test_raw_overlap_redirects_load_itself() -> None:
    trace = feasible("raw_violation")
    track = event(trace, "LQ.RAWTrack", source_op_id="S0", target_op_id="LRAW")
    violation = event(trace, "LQ.RAWViolation")
    report = event(trace, "Core.MemoryViolation", cause="raw")
    redirect = event(trace, "Core.Redirect", cause="raw")

    assert track.fields["byte_mask"] & 3
    assert track.cycle < violation.cycle < report.cycle < redirect.cycle
    assert redirect.fields["source_op_id"] == "LRAW"
    assert redirect.fields["flush_self"] is True
    event(trace, "LQ.Deallocate", op_id="LRAW", path="redirect")


def test_disjoint_raw_masks_do_not_report_a_violation() -> None:
    trace = feasible("raw_no_overlap")
    event(trace, "LQ.RAWTrack")
    assert not list(trace.events_of_type("LQ.RAWViolation"))
    assert not list(trace.events_of_type("Core.MemoryViolation"))
    assert not list(trace.events_of_type("Core.Redirect"))


@pytest.mark.parametrize(
    "case",
    ["rar_requires_release", "raw_disjoint_cannot_redirect", "post_redirect_update"],
)
def test_invalid_public_recovery_is_unsat(case: str) -> None:
    assert result(case).status is CompletionStatus.INFEASIBLE


def test_stage5_scalar_load_drives_stage6_queue() -> None:
    source = Trace.load(XIANGSHAN / "traces" / "load" / "cache_hit.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "scalar_load_queue.yaml"
    )
    composed = compose_modules(catalog(), composition, source)
    completed = complete_trace(catalog(), source, composed.completion, backend="z3")

    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    trace = completed.completed_trace
    query = event(trace, "Load.OrderQuery", op_id="L0")
    update = event(trace, "Load.PipelineUpdate", op_id="L0")
    deallocate = event(trace, "LQ.Deallocate", op_id="L0")
    assert query.fields["address"] == 8192
    assert query.cycle < update.cycle < deallocate.cycle


def test_stage6_interface_inventory_and_private_encapsulation() -> None:
    # The RAW witness instantiates both the per-load RAR/VLQ surface and the
    # store×load RAW product, so the generated inventory covers the full slice.
    source = Trace.load(LQ_TRACES / "raw_violation.yaml")
    composition = CompositionSpec.load(LQ_COMPOSITION)
    composed = compose_modules(catalog(), composition, source)
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": composition.name,
        "policy": "ports-only-public-surface",
        "modules": [
            contract.to_dict() for contract in build_interface_contracts(composed)
        ],
    }
    assert load_data(XIANGSHAN / "hierarchy" / "load_queue_interfaces.yaml") == expected

    for path in LQ_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage6_source_metadata_is_pinned() -> None:
    source = Trace.load(LQ_TRACES / "normal_release.yaml")
    composition = CompositionSpec.load(LQ_COMPOSITION)
    module = compose_modules(catalog(), composition, source).modules[0].spec

    assert module.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert module.metadata["source_files"] == [
        "src/main/scala/xiangshan/mem/lsqueue/VirtualLoadQueue.scala:34-257",
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueueRAR.scala:29-285",
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueueRAW.scala:32-400",
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueue.scala:167-343",
        "src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala:1409-1447",
        "src/main/scala/xiangshan/mem/MemBlock.scala:1036-1047,1115-1119",
    ]


def test_stage6_required_path_coverage_is_complete() -> None:
    suite = CoverageSuite.load(XIANGSHAN / "coverage" / "stage6.yaml")
    report = run_coverage(suite, backend="z3")
    assert report.required_complete
    assert [item.status for item in report.results] == [CoverageStatus.COVERED] * 10
