from dataclasses import replace
from pathlib import Path

from umcm.ir.completion import CompletionSpec, EventSlot
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/boom_load_load"


def _inputs() -> tuple[EventCatalog, Trace, CompletionSpec]:
    return (
        EventCatalog.load(EXAMPLE / "event_types.yaml"),
        Trace.load(EXAMPLE / "partial_trace.yaml"),
        CompletionSpec.load(EXAMPLE / "retry_completion.yaml"),
    )


def test_retry_path_is_completed_with_same_identity() -> None:
    catalog, trace, spec = _inputs()
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.added_event_ids == (
        "l0_tlb_miss",
        "retry_enqueue_0",
        "retry_issue_0",
    )
    assert result.completed_trace is not None
    result.completed_trace.validate(catalog, partial=False)

    miss = result.completed_trace.get("l0_tlb_miss")
    enqueue = result.completed_trace.get("retry_enqueue_0")
    issue = result.completed_trace.get("retry_issue_0")
    load_l0 = result.completed_trace.get("load_l0")
    load_l1 = result.completed_trace.get("load_l1")
    assert miss.fields["op_id"] == enqueue.fields["op_id"] == issue.fields["op_id"] == "L0"
    assert load_l0.cycle < miss.cycle < enqueue.cycle < load_l1.cycle < issue.cycle
    assert issue.annotations["role"] == "query_goal"
    assert issue.annotations["required_slot"] is True


def test_retry_rules_do_not_imply_unconditional_liveness() -> None:
    catalog, trace, spec = _inputs()
    spec.slots = [
        replace(slot, required=False) if slot.id == "retry_issue_0" else slot
        for slot in spec.slots
    ]

    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.added_event_ids == ()
    assert result.completed_trace is not None
    assert all(
        event.id not in {"l0_tlb_miss", "retry_enqueue_0", "retry_issue_0"}
        for event in result.completed_trace.events
    )


def test_retry_path_is_infeasible_when_horizon_is_too_small() -> None:
    catalog, trace, spec = _inputs()
    spec.horizon = 1
    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_completion_spec_roundtrip(tmp_path: Path) -> None:
    _, _, spec = _inputs()
    path = tmp_path / "model.json"
    spec.dump(path)
    assert CompletionSpec.load(path).to_dict() == spec.to_dict()


def test_event_slot_preserves_cycle_zero() -> None:
    catalog, _, _ = _inputs()
    slot = EventSlot(
        id="fixed_zero",
        event_type="LSU.TLBMiss",
        fields={"op_id": "L0"},
        required=True,
        cycle=0,
    )
    assert slot.materialize(catalog).cycle == 0


def test_missing_required_int_field_is_completed() -> None:
    from umcm.ir.event import EventInstance, EventType, FieldSpec
    from umcm.ir.sort import INT, Sort

    event_type = EventType(
        name="Test.Event",
        module="Test",
        layer="test",
        fields=(
            FieldSpec("op_id", Sort("op_id")),
            FieldSpec("index", INT),
        ),
    )
    catalog = EventCatalog({event_type.name: event_type})
    trace = Trace(
        events=[EventInstance("e0", "Test.Event", {"op_id": "E0"})],
        partial=True,
    )
    spec = CompletionSpec(horizon=2)

    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.completed_trace.get("e0").fields["index"] == 0
    result.completed_trace.validate(catalog, partial=False)
