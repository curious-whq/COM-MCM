from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION = ROOT / "examples/boom/composition/tlb_lsu_l1_source_v021.yaml"
DYNAMIC_INPUTS = {
    "TLB.Miss",
    "TLB.Retry",
    "Core.TranslatedMemory",
    "LSU.ArbitrationFrame",
    "LSU.ScheduleGrant",
    "LSU.DCacheIssueIntent",
    "LSU.DCacheReqValid",
    "DCache.LoadHit",
    "DCache.LoadMiss",
    "DCache.LoadResponse",
    "LSU.LDQAllocate",
    "LSU.LoadExecuted",
    "LSU.LoadSucceeded",
    "Core.MemoryComplete",
    "ROB.Commit",
    "Arch.Load",
    "DCache.MSHRAdmissionRequest",
    "DCache.MSHRRequest",
    "MSHR.PrimaryAccept",
    "TL.Acquire",
    "TL.Grant",
    "MSHR.ResponseDequeue",
    "DCache.LongLatencyLoadResponse",
}


def _complete(name: str):
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(ROOT / f"examples/boom/traces/source_model/{name}.yaml")
    assert not ({event.event_type for event in source.events} & DYNAMIC_INPUTS)
    composition = CompositionSpec.load(COMPOSITION)
    composed = compose_modules(catalog, composition, source)
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    return solved.completed_trace


@pytest.mark.parametrize(
    ("trace_name", "tlb_path", "request_kind", "expect_miss"),
    [
        ("tlb_lsu_l1_hit", "hit", "load-agen-exec", False),
        ("tlb_retry_lsu_l1_hit", "retry", "load-retry", True),
    ],
)
def test_instruction_reaches_l1_through_source_scheduler(
    trace_name: str, tlb_path: str, request_kind: str, expect_miss: bool
):
    completed = _complete(trace_name)
    translated = next(
        event
        for event in completed.events
        if event.event_type == "Core.TranslatedMemory" and event.occurs is True
    )
    grant = next(
        event
        for event in completed.events
        if event.event_type == "LSU.ScheduleGrant" and event.occurs is True
    )
    request = next(
        event
        for event in completed.events
        if event.event_type == "LSU.DCacheReqValid" and event.occurs is True
    )
    response = next(
        event
        for event in completed.events
        if event.event_type == "DCache.LoadResponse" and event.occurs is True
    )
    allocated = next(
        event
        for event in completed.events
        if event.event_type == "LSU.LDQAllocate" and event.occurs is True
    )
    executed = next(
        event
        for event in completed.events
        if event.event_type == "LSU.LoadExecuted" and event.occurs is True
    )
    succeeded = next(
        event
        for event in completed.events
        if event.event_type == "LSU.LoadSucceeded" and event.occurs is True
    )
    complete = next(
        event
        for event in completed.events
        if event.event_type == "Core.MemoryComplete" and event.occurs is True
    )
    commit = next(
        event
        for event in completed.events
        if event.event_type == "ROB.Commit" and event.occurs is True
    )
    retired = next(
        event
        for event in completed.events
        if event.event_type == "Arch.Load" and event.occurs is True
    )
    assert translated.fields["tlb_path"] == tlb_path
    assert grant.fields["request_kind"] == request_kind
    assert request.fields["ldq_idx"] == 0
    assert response.fields["value"] == 42
    assert allocated.fields == {"op_id": "L0", "ldq_idx": 0}
    assert executed.fields["ldq_idx"] == request.fields["ldq_idx"]
    assert succeeded.fields["value"] == response.fields["value"]
    assert complete.fields["value"] == succeeded.fields["value"]
    assert commit.fields["value"] == complete.fields["value"]
    assert retired.fields["value"] == commit.fields["value"]
    assert allocated.cycle < translated.cycle <= request.cycle
    assert request.cycle < response.cycle <= succeeded.cycle
    assert succeeded.cycle < complete.cycle < commit.cycle < retired.cycle
    misses = [
        event
        for event in completed.events
        if event.event_type == "TLB.Miss" and event.occurs is True
    ]
    retries = [
        event
        for event in completed.events
        if event.event_type == "TLB.Retry" and event.occurs is True
    ]
    assert bool(misses) is expect_miss
    assert bool(retries) is expect_miss


def test_cold_load_reaches_mshr_l2_lsq_rob_and_retirement_with_refill_value():
    completed = _complete("tlb_lsu_l1_mshr_l2_cold_load")

    def one(event_type: str):
        return next(
            event
            for event in completed.events
            if event.event_type == event_type and event.occurs is True
        )

    request = one("LSU.DCacheReqFire")
    miss = one("DCache.LoadMiss")
    mshr_request = one("DCache.MSHRRequest")
    acquire = one("TL.Acquire")
    grant = one("TL.Grant")
    long_response = one("DCache.LongLatencyLoadResponse")
    succeeded = one("LSU.LoadSucceeded")
    complete = one("Core.MemoryComplete")
    commit = one("ROB.Commit")
    retired = one("Arch.Load")
    retired_value = one("Arch.CommitLoad")

    assert request.fields["op_id"] == miss.fields["op_id"] == "L0"
    assert mshr_request.fields["mshr_id"] == 0
    assert mshr_request.fields["secondary"] is False
    assert acquire.fields["source_id"] == mshr_request.fields["mshr_id"]
    assert grant.fields["source_id"] == acquire.fields["source_id"]
    assert long_response.fields["mshr_id"] == mshr_request.fields["mshr_id"]
    assert grant.fields["value"] == 9
    assert long_response.fields["value"] == 9
    assert succeeded.fields["value"] == 9
    assert complete.fields["value"] == 9
    assert commit.fields["value"] == 9
    assert retired.fields["value"] == 9
    assert retired_value.fields["value"] == 9
    assert request.cycle < miss.cycle < acquire.cycle < grant.cycle
    assert grant.cycle < long_response.cycle <= succeeded.cycle
    assert succeeded.cycle < complete.cycle < commit.cycle < retired.cycle
