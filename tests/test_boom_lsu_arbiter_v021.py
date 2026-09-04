from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.trace import Trace
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"
CATALOG = EventCatalog.load(BOOM / "events.yaml")
ARBITER = CompositionSpec.load(
    BOOM / "composition" / "lsu_port_scheduler_source_v021.yaml"
)


def _frame(**overrides) -> EventInstance:
    fields = {
        "frame_id": "F",
        "hart": 0,
        "hardware_cycle": 0,
        "port": 0,
        "lsu_width": 1,
        "can_sfence": False,
        "can_store_commit": False,
        "stq_almost_full": False,
        "can_load_agen": False,
        "can_store_agen": False,
        "can_release": False,
        "can_hella_incoming": False,
        "can_hella_wakeup": False,
        "can_store_retry": False,
        "can_load_retry": False,
        "can_load_wakeup": False,
        "sfence_op_id": "SF",
        "store_commit_op_id": "SC",
        "load_agen_op_id": "LA",
        "store_agen_op_id": "SA",
        "release_op_id": "REL",
        "hella_incoming_op_id": "HI",
        "hella_wakeup_op_id": "HW",
        "store_retry_op_id": "SR",
        "load_retry_op_id": "LR",
        "load_wakeup_op_id": "LW",
    }
    fields.update(overrides)
    return EventInstance(
        id="frame",
        event_type="LSU.ArbitrationFrame",
        fields=fields,
        cycle=0,
        occurs=True,
    )


def _solve(frame: EventInstance):
    trace = Trace(events=[frame], partial=True)
    composed = compose_modules(CATALOG, ARBITER, trace)
    return complete_trace(CATALOG, trace, composed.completion, backend="z3")


@pytest.mark.parametrize(
    ("candidate", "extra", "expected"),
    [
        ("can_sfence", {}, "sfence"),
        ("can_store_commit", {"stq_almost_full": True}, "store-commit-fast"),
        ("can_load_agen", {}, "load-agen-exec"),
        ("can_store_agen", {}, "store-agen"),
        ("can_release", {}, "release"),
        ("can_hella_incoming", {}, "hella-incoming"),
        ("can_hella_wakeup", {}, "hella-wakeup"),
        ("can_store_retry", {}, "store-retry"),
        ("can_load_retry", {}, "load-retry"),
        ("can_load_wakeup", {}, "load-wakeup"),
        ("can_store_commit", {}, "store-commit-slow"),
    ],
)
def test_each_source_request_class_can_win(candidate, extra, expected):
    solved = _solve(_frame(**{candidate: True}, **extra))
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    grants = [
        event.fields["request_kind"]
        for event in solved.completed_trace.events
        if event.event_type == "LSU.ScheduleGrant" and event.occurs is True
    ]
    assert grants == [expected]


def test_source_priority_and_disjoint_resource_coissue():
    trace = Trace.load(BOOM / "traces" / "source_model" / "lsu_port_arbitration.yaml")
    composed = compose_modules(CATALOG, ARBITER, trace)
    solved = complete_trace(CATALOG, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    grants = {
        (event.fields["frame_id"], event.fields["request_kind"])
        for event in solved.completed_trace.events
        if event.event_type == "LSU.ScheduleGrant" and event.occurs is True
    }
    assert grants == {
        ("F0", "store-commit-fast"),
        ("F0", "load-agen"),
        ("F1", "release"),
        ("F2", "store-retry"),
        ("F3", "hella-incoming"),
    }


def test_fixed_port_guards_reject_release_on_non_last_port():
    trace = Trace.load(
        BOOM / "traces" / "source_model" / "lsu_port_arbitration_invalid.yaml"
    )
    composed = compose_modules(CATALOG, ARBITER, trace)
    solved = complete_trace(CATALOG, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.INFEASIBLE


def test_scheduler_selected_request_enters_generalized_l1():
    trace = Trace.load(
        BOOM / "traces" / "source_model" / "lsu_l1_scheduled_hit.yaml"
    )
    composition = CompositionSpec.load(
        BOOM / "composition" / "lsu_l1_source_v021.yaml"
    )
    composed = compose_modules(CATALOG, composition, trace)
    solved = complete_trace(CATALOG, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    occurred = {
        event.event_type
        for event in solved.completed_trace.events
        if event.occurs is True
    }
    assert {
        "LSU.ScheduleGrant",
        "LSU.DCacheReqValid",
        "LSU.DCacheReqFire",
        "DCache.LoadHit",
        "DCache.LoadResponse",
    } <= occurred
    response = next(
        event
        for event in solved.completed_trace.events
        if event.event_type == "DCache.LoadResponse" and event.occurs is True
    )
    assert response.fields["op_id"] == "L0"
    assert response.fields["value"] == 42


def test_scheduler_model_lists_all_twelve_source_priority_calls():
    model = load_data(BOOM / "model" / "lsu" / "port_scheduler_v021.yaml")
    rules = model["repeat"][0]["include"]["transformations"]
    priorities = {
        tag
        for rule in rules
        for tag in rule.get("tags", [])
        if str(tag).startswith("priority-")
    }
    assert priorities == {f"priority-{index}" for index in range(12)}
