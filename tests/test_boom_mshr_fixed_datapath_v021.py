from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]


def test_fixed_entry_primary_refill_preserves_tilelink_source_and_value():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(
        ROOT / "examples/boom/traces/source_model/mshr_fixed_primary_refill.yaml"
    )
    composition = CompositionSpec.load(
        ROOT / "examples/boom/composition/mshr_fixed_datapath_source_v021.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    completed = solved.completed_trace

    by_type = {
        event.event_type: event
        for event in completed.events
        if event.occurs is True
        and event.event_type
        in {
            "MSHR.AcquireBlock",
            "TL.Acquire",
            "MSHR.GrantData",
            "MSHR.RefillWrite",
            "MSHR.MetaWrite",
            "MSHR.ResponseDequeue",
            "DCache.LongLatencyLoadResponse",
            "MSHR.MemFinish",
            "TL.GrantAck",
        }
    }
    assert set(by_type) == {
        "MSHR.AcquireBlock",
        "TL.Acquire",
        "MSHR.GrantData",
        "MSHR.RefillWrite",
        "MSHR.MetaWrite",
        "MSHR.ResponseDequeue",
        "DCache.LongLatencyLoadResponse",
        "MSHR.MemFinish",
        "TL.GrantAck",
    }
    assert by_type["TL.Acquire"].fields["source_id"] == 0
    assert by_type["MSHR.GrantData"].fields["source_op_id"] == "W"
    assert by_type["MSHR.RefillWrite"].fields["value"] == 9
    assert by_type["MSHR.ResponseDequeue"].fields["value"] == 9
    assert by_type["DCache.LongLatencyLoadResponse"].fields["value"] == 9
    assert by_type["TL.GrantAck"].fields["sink_id"] == 3
