from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]


def test_tilelink_probe_crosses_dcache_probeunit_boundary_and_returns_clean_ack():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/l1_probe_bridge_clean.yaml"
    )
    assert not any(
        event.event_type in {"DCache.ProbeReceive", "TL.ProbeAck"}
        for event in source.events
    )
    composed = compose_modules(
        catalog,
        CompositionSpec.load(
            ROOT / "examples/boom/composition/l1_probe_bridge_source_v021.yaml"
        ),
        source,
    )
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    receive = next(
        event
        for event in solved.completed_trace.events
        if event.event_type == "DCache.ProbeReceive" and event.occurs is True
    )
    ack = next(
        event
        for event in solved.completed_trace.events
        if event.event_type == "TL.ProbeAck" and event.occurs is True
    )
    assert receive.fields["source_op_id"] == ack.fields["txn_id"] == "W0"
    assert receive.fields["probe_param"] == ack.fields["cap"] == "N"
    assert ack.fields["hart"] == 0
    assert ack.fields["has_data"] is False
    assert 2 < receive.cycle < ack.cycle
