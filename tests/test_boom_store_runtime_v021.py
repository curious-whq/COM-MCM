from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("trace_name", "expect_tlb_retry"),
    [
        ("tlb_lsu_l1_store_hit", False),
        ("tlb_retry_lsu_l1_store_hit", True),
    ],
)
def test_ordinary_store_becomes_rob_ready_before_commit_and_only_then_drains(
    trace_name: str, expect_tlb_retry: bool
):
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / f"examples/boom/traces/source_model/{trace_name}.yaml"
    )
    forbidden = {
        "Core.TranslatedMemory",
        "LSU.STQAllocate",
        "LSU.StoreAddressReady",
        "LSU.StoreDataReady",
        "Core.MemoryComplete",
        "ROB.Commit",
        "LSU.StoreCommitted",
        "LSU.ArbitrationFrame",
        "LSU.ScheduleGrant",
        "LSU.DCacheIssueIntent",
        "LSU.DCacheReqValid",
        "LSU.StoreDrainIssue",
        "DCache.StoreHit",
        "DCache.StoreAck",
        "LSU.StoreCleared",
        "Arch.Store",
    }
    assert not ({event.event_type for event in source.events} & forbidden)
    composed = compose_modules(
        catalog,
        CompositionSpec.load(
            ROOT / "examples/boom/composition/tlb_lsu_l1_source_v021.yaml"
        ),
        source,
    )
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    occurred = [event for event in solved.completed_trace.events if event.occurs is True]

    def one(event_type: str):
        return next(event for event in occurred if event.event_type == event_type)

    allocated = one("LSU.STQAllocate")
    address = one("LSU.StoreAddressReady")
    data = one("LSU.StoreDataReady")
    ready = one("Core.MemoryComplete")
    commit = one("ROB.Commit")
    committed = one("LSU.StoreCommitted")
    frame = one("LSU.ArbitrationFrame")
    grant = one("LSU.ScheduleGrant")
    intent = one("LSU.DCacheIssueIntent")
    valid = one("LSU.DCacheReqValid")
    drain = one("LSU.StoreDrainIssue")
    fire = one("LSU.DCacheReqFire")
    ack = one("DCache.StoreAck")
    cleared = one("LSU.StoreCleared")
    retired = one("Arch.Store")

    misses = [event for event in occurred if event.event_type == "TLB.Miss"]
    retries = [event for event in occurred if event.event_type == "TLB.Retry"]

    assert allocated.fields == {"op_id": "W0", "stq_idx": 0}
    assert address.fields["address"] == "x"
    assert data.fields["value"] == 7
    assert ready.fields["write_value"] == 7
    assert commit.fields["write_value"] == 7
    assert committed.fields["stq_idx"] == 0
    assert frame.fields["can_store_commit"] is True
    assert grant.fields["request_kind"] == "store-commit-slow"
    assert intent.fields["value"] == valid.fields["value"] == 7
    assert valid.fields["queue_kind"] == "stq"
    assert drain.fields["value"] == 7
    assert ack.fields["stq_idx"] == 0
    assert retired.fields["value"] == 7
    assert allocated.cycle <= data.cycle
    assert address.cycle < ready.cycle < commit.cycle
    assert data.cycle < ready.cycle
    assert commit.cycle == committed.cycle < frame.cycle
    assert frame.cycle == grant.cycle == intent.cycle == valid.cycle == drain.cycle
    assert valid.cycle <= fire.cycle < ack.cycle < cleared.cycle
    assert bool(misses) is expect_tlb_retry
    assert bool(retries) is expect_tlb_retry


def test_cold_store_is_acked_on_mshr_accept_then_replayed_from_sdq_into_l1():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/tlb_lsu_l1_mshr_l2_cold_store.yaml"
    )
    forbidden = {
        "Core.TranslatedMemory",
        "LSU.STQAllocate",
        "LSU.ScheduleGrant",
        "LSU.DCacheReqValid",
        "DCache.TagMiss",
        "DCache.MSHRAdmissionRequest",
        "DCache.MSHRRequest",
        "DCache.StoreAck",
        "MSHR.PrimaryAccept",
        "MSHR.SDQAllocate",
        "TL.Acquire",
        "TL.Grant",
        "MSHR.RefillWrite",
        "MSHR.Replay",
        "DCache.ReplayS1",
        "DCache.ReplayS2",
        "DCache.StoreDataWrite",
        "MSHR.MetaWrite",
        "TL.GrantAck",
        "Arch.Store",
    }
    assert not ({event.event_type for event in source.events} & forbidden)
    composed = compose_modules(
        catalog,
        CompositionSpec.load(
            ROOT / "examples/boom/composition/tlb_lsu_l1_source_v021.yaml"
        ),
        source,
    )
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    occurred = [event for event in solved.completed_trace.events if event.occurs is True]

    def one(event_type: str):
        return next(event for event in occurred if event.event_type == event_type)

    request = one("DCache.MSHRRequest")
    ack = one("DCache.StoreAck")
    cleared = one("LSU.StoreCleared")
    acquire = one("TL.Acquire")
    grant = one("TL.Grant")
    refill = one("MSHR.RefillWrite")
    replay = one("MSHR.Replay")
    replay_s1 = one("DCache.ReplayS1")
    replay_s2 = one("DCache.ReplayS2")
    data_write = one("DCache.StoreDataWrite")
    meta = one("MSHR.MetaWrite")
    finish = one("MSHR.MemFinish")
    grant_ack = one("TL.GrantAck")
    retired = one("Arch.Store")

    assert request.fields["mem_kind"] == "store"
    assert request.fields["mshr_id"] == 0
    assert request.fields["queue_kind"] == "stq"
    assert ack.cycle == request.cycle
    assert ack.cycle < cleared.cycle
    assert acquire.fields["grow"] == "NtoT"
    assert acquire.fields["source_id"] == request.fields["mshr_id"]
    assert grant.fields["cap"] == "T"
    assert refill.fields["value"] == grant.fields["value"] == 3
    assert replay.fields["value"] == data_write.fields["value"] == 7
    assert replay.fields["queue_kind"] == "stq"
    assert replay.fields["mshr_id"] == request.fields["mshr_id"]
    assert meta.fields["permission"] == "dirty"
    assert grant_ack.fields["sink_id"] == grant.fields["sink_id"]
    assert request.cycle < acquire.cycle < grant.cycle < refill.cycle < replay.cycle
    assert replay.cycle < replay_s1.cycle < replay_s2.cycle < data_write.cycle
    assert replay.cycle < meta.cycle < finish.cycle == grant_ack.cycle
    assert retired.fields["value"] == 7


def test_dcache_nacked_store_rewinds_reenqueues_and_reenters_exact_scheduler():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/store_nack_redrain.yaml"
    )
    composed = compose_modules(
        catalog,
        CompositionSpec.load(
            ROOT / "examples/boom/composition/store_nack_redrain_source_v021.yaml"
        ),
        source,
    )
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    occurred = [event for event in solved.completed_trace.events if event.occurs is True]

    frames = sorted(
        (event for event in occurred if event.event_type == "LSU.ArbitrationFrame"),
        key=lambda event: event.cycle,
    )
    grants = sorted(
        (event for event in occurred if event.event_type == "LSU.ScheduleGrant"),
        key=lambda event: event.cycle,
    )
    drains = sorted(
        (event for event in occurred if event.event_type == "LSU.StoreDrainIssue"),
        key=lambda event: event.cycle,
    )
    flush = next(
        event for event in occurred if event.event_type == "LSU.StoreExecuteQueueFlush"
    )
    reenqueue = next(
        event for event in occurred if event.event_type == "LSU.StoreReenqueue"
    )
    nack = next(event for event in occurred if event.event_type == "DCache.RequestNack")

    assert [event.fields["frame_id"] for event in frames] == ["W0.0", "W0.1"]
    assert [event.fields["frame_id"] for event in grants] == ["W0.0", "W0.1"]
    assert [event.fields["request_kind"] for event in grants] == [
        "store-commit-slow",
        "store-commit-slow",
    ]
    assert [event.fields["frame_id"] for event in drains] == ["W0.0", "W0.1"]
    assert flush.cycle == nack.cycle < reenqueue.cycle < frames[1].cycle
    assert frames[0].cycle == grants[0].cycle == drains[0].cycle < nack.cycle
    assert frames[1].cycle == grants[1].cycle == drains[1].cycle
