from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]


def test_older_retry_finding_observed_younger_reaches_boom_source_assertion():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/lsq_runtime_observed_younger.yaml"
    )
    forbidden = {
        "LSU.LDQAllocate",
        "LSU.LoadExecuted",
        "LSU.LoadSucceeded",
        "LSU.LoadObserved",
        "LSU.LDLDSearch",
        "LSU.LDLDConflict",
        "LSU.AssertViolation",
    }
    assert not ({event.event_type for event in source.events} & forbidden)
    composed = compose_modules(
        catalog,
        CompositionSpec.load(
            ROOT / "examples/boom/composition/lsq_runtime_source_v021.yaml"
        ),
        source,
    )
    solved = complete_trace(catalog, source, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    occurred = [
        event
        for event in solved.completed_trace.events
        if event.occurs is True
    ]
    conflict = next(event for event in occurred if event.event_type == "LSU.LDLDConflict")
    assertion = next(event for event in occurred if event.event_type == "LSU.AssertViolation")
    observed = next(
        event
        for event in occurred
        if event.event_type == "LSU.LoadObserved" and event.fields["op_id"] == "L1"
    )
    search = next(
        event
        for event in occurred
        if event.event_type == "LSU.LDLDSearch"
        and event.fields["searcher_op_id"] == "L0"
    )
    assert conflict.fields["older_op_id"] == "L0"
    assert conflict.fields["younger_op_id"] == "L1"
    assert assertion.fields["property"] == "older_load_found_observed_younger"
    assert observed.cycle < search.cycle == conflict.cycle == assertion.cycle
