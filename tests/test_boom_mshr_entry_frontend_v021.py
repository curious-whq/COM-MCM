from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION = ROOT / "examples/boom/composition/mshr_entry_frontend_source_v021.yaml"


def _complete(name: str):
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(ROOT / f"examples/boom/traces/source_model/{name}.yaml")
    composition = CompositionSpec.load(COMPOSITION)
    composed = compose_modules(catalog, composition, trace)
    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    return trace, composed, solved.completed_trace


def test_allocator_selection_is_accepted_by_the_selected_fixed_entry():
    source, composed, completed = _complete("mshr_internal_allocation")
    requests = {
        event.fields["op_id"]: event.fields
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    }
    assert requests["A"]["mshr_id"] == 0 and requests["A"]["secondary"] is False
    assert requests["B"]["mshr_id"] == 0 and requests["B"]["secondary"] is True
    assert requests["C"]["mshr_id"] == 1 and requests["C"]["secondary"] is False

    primary = {
        (event.fields["op_id"], event.fields["mshr_id"])
        for event in completed.events
        if event.event_type == "MSHR.PrimaryAccept" and event.occurs is True
    }
    secondary = {
        (event.fields["op_id"], event.fields["mshr_id"])
        for event in completed.events
        if event.event_type == "MSHR.SecondaryMissAccept" and event.occurs is True
    }
    assert primary == {("A", 0), ("C", 1)}
    assert secondary == {("B", 0)}

    inserts = {
        (event.fields["op_id"], event.fields["mshr_id"], event.fields["admission"])
        for event in completed.events
        if event.event_type == "MSHR.RPQInsert" and event.occurs is True
    }
    assert inserts == {("A", 0, "primary"), ("B", 0, "secondary"), ("C", 1, "primary")}
    assert all("mshr_id" not in event.fields for event in source.events)
    assert "MSHREntry[0].phase" in {item.name for item in composed.completion.state_variables}


def test_store_misses_receive_internal_mshr_and_sdq_ids():
    source, _, completed = _complete("mshr_entry_store_sdq")
    assert all("mshr_id" not in event.fields for event in source.events)
    assert all("sdq_id" not in event.fields for event in source.events)

    requests = {
        event.fields["op_id"]: event.fields
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    }
    assert requests["StoreA"]["mshr_id"] == 0
    assert requests["StoreB"]["mshr_id"] == 1
    assert requests["StoreA"]["sdq_id"] == 0
    assert requests["StoreB"]["sdq_id"] == 1

    allocations = {
        (event.fields["op_id"], event.fields["sdq_id"], event.fields["value"])
        for event in completed.events
        if event.event_type == "MSHR.SDQAllocate" and event.occurs is True
    }
    assert allocations == {("StoreA", 0, 17), ("StoreB", 1, 23)}


def test_secondary_ready_is_not_an_environment_annotation():
    source, _, completed = _complete("mshr_internal_allocation")
    assert all(event.event_type != "MSHRFile.SecondaryReady" for event in source.events)
    ready = [
        event
        for event in completed.events
        if event.event_type == "MSHRFile.SecondaryReady"
        and event.occurs is True
        and event.fields["op_id"] == "B"
    ]
    assert len(ready) == 1
    assert ready[0].fields["mshr_id"] == 0
    assert ready[0].fields["rpq_ready"] is True


def test_matching_entry_rejects_secondary_after_meta_write_phase():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(
        ROOT / "examples/boom/traces/source_model/mshr_secondary_after_meta_write.yaml"
    )
    composition = CompositionSpec.load(COMPOSITION)
    composed = compose_modules(catalog, composition, trace)
    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.INFEASIBLE
