from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]


def test_general_l1_cold_miss_reaches_inclusive_l2_without_supplied_path_ids():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/l1_mshr_l2_cold_load.yaml"
    )
    forbidden = {
        "DCache.LoadMiss",
        "DCache.MSHRAdmissionRequest",
        "DCache.MSHRRequest",
        "MSHR.PrimaryAccept",
        "TL.Acquire",
        "TL.Grant",
        "MSHR.ResponseDequeue",
    }
    assert not ({event.event_type for event in source.events} & forbidden)
    composition = CompositionSpec.load(
        ROOT / "examples/boom/composition/l1_mshr_l2_source_v021.yaml"
    )
    composed = compose_modules(catalog, composition, source)
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    completed = solved.completed_trace

    def one(event_type: str):
        return next(
            event
            for event in completed.events
            if event.event_type == event_type and event.occurs is True
        )

    admission = one("DCache.MSHRAdmissionRequest")
    request = one("DCache.MSHRRequest")
    acquire = one("TL.Acquire")
    grant = one("TL.Grant")
    response = one("MSHR.ResponseDequeue")
    assert request.fields["mshr_id"] == 0
    assert request.fields["secondary"] is False
    assert acquire.fields["source_id"] == request.fields["mshr_id"]
    assert grant.fields["source_id"] == acquire.fields["source_id"]
    assert response.fields["mshr_id"] == request.fields["mshr_id"]
    assert response.fields["value"] == grant.fields["value"] == 9
    assert admission.fields["op_id"] == response.fields["op_id"] == "L0"
    assert one("TL.GrantAck").fields["sink_id"] == grant.fields["sink_id"]
