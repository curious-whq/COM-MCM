from dataclasses import replace
from pathlib import Path

from umcm.ir.completion import CompletionSpec, EventSlot
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests/regressions/boom/legacy_v0_11"


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


def _v03_inputs() -> tuple[EventCatalog, Trace, CompletionSpec]:
    return (
        EventCatalog.load(EXAMPLE / "event_types.yaml"),
        Trace.load(EXAMPLE / "partial_trace.yaml"),
        CompletionSpec.load(EXAMPLE / "retry_dcache_completion.yaml"),
    )


def test_retry_reaches_dcache_accept_transition_with_stateful_identity() -> None:
    catalog, trace, spec = _v03_inputs()
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.added_event_ids == (
        "l0_tlb_miss",
        "retry_enqueue_0",
        "retry_issue_0",
        "l0_tlb_hit",
        "dcache_req_valid_0",
        "dcache_req_ready_0",
        "dcache_req_fire_0",
    )
    assert result.completed_trace is not None
    issue = result.completed_trace.get("retry_issue_0")
    hit = result.completed_trace.get("l0_tlb_hit")
    valid = result.completed_trace.get("dcache_req_valid_0")
    ready = result.completed_trace.get("dcache_req_ready_0")
    fire = result.completed_trace.get("dcache_req_fire_0")
    assert issue.cycle == hit.cycle == valid.cycle == ready.cycle == fire.cycle
    assert issue.fields["op_id"] == valid.fields["op_id"] == fire.fields["op_id"] == "L0"
    assert issue.fields["ldq_idx"] == valid.fields["ldq_idx"] == fire.fields["ldq_idx"] == 0

    assert result.initial_state["LSU.retry_queue.valid"] is False
    assert result.final_state["LSU.retry_queue.valid"] is False
    steps = {step["cycle"]: step for step in result.state_steps}
    enqueue_cycle = result.completed_trace.get("retry_enqueue_0").cycle
    issue_cycle = issue.cycle
    assert steps[enqueue_cycle]["before"]["LSU.retry_queue.valid"] is False
    assert steps[enqueue_cycle]["after"]["LSU.retry_queue.valid"] is True
    assert steps[enqueue_cycle]["after"]["LSU.retry_queue.op_id"] == "L0"
    assert steps[issue_cycle]["before"]["LSU.retry_queue.valid"] is True
    assert steps[issue_cycle]["before"]["LSU.retry_queue.op_id"] == "L0"
    assert steps[issue_cycle]["after"]["LSU.retry_queue.valid"] is False


def test_required_branch_kill_blocks_retry_issue() -> None:
    catalog, trace, spec = _v03_inputs()
    trace.get("load_l0").cycle = 0
    trace.get("load_l1").cycle = 3
    fixed_cycles = {
        "l0_tlb_miss": 1,
        "retry_enqueue_0": 2,
        "retry_issue_0": 4,
        "l0_tlb_hit": 4,
        "dcache_req_valid_0": 4,
        "dcache_req_ready_0": 4,
        "dcache_req_fire_0": 4,
        "branch_kill_0": 3,
        "exception_0": 3,
    }
    spec.slots = [
        replace(
            slot,
            required=slot.required or slot.id == "branch_kill_0",
            cycle=fixed_cycles[slot.id],
        )
        for slot in spec.slots
    ]

    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.INFEASIBLE
    assert "LSU.retry_queue.valid == True" in result.reason
    assert "pre-state is False" in result.reason


def test_dcache_accept_transition_requires_ready_guard() -> None:
    from umcm.ir.expression import EventField, Unary
    from umcm.ir.sort import BOOL

    catalog, trace, spec = _v03_inputs()
    spec.constraints.append(
        Unary("not", EventField("dcache_req_ready_0", "occurs", BOOL))
    )

    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_v03_completion_spec_roundtrip(tmp_path: Path) -> None:
    _, _, spec = _v03_inputs()
    path = tmp_path / "v03.json"
    spec.dump(path)
    loaded = CompletionSpec.load(path)
    assert loaded.to_dict() == spec.to_dict()
    assert len(loaded.state_variables) == 4
    assert any(item.is_stateful for item in loaded.transformations)


def test_completion_spec_rejects_separate_handshake_section() -> None:
    import pytest

    from umcm.errors import SerializationError

    with pytest.raises(SerializationError, match=r"unknown top-level key\(s\): handshakes"):
        CompletionSpec.from_dict(
            {
                "schema_version": "umcm.completion.v0.3.1",
                "handshakes": [],
            }
        )


def test_exact_interface_transition_is_not_unconditional_liveness() -> None:
    catalog, trace, spec = _v03_inputs()
    spec.slots = [
        replace(slot, required=False)
        if slot.id == "dcache_req_fire_0"
        else slot
        for slot in spec.slots
    ]

    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.added_event_ids == ()


def _v04_inputs(
    model: str = "young_load_probe_completion.yaml",
    trace_name: str = "stage4_trace.yaml",
) -> tuple[EventCatalog, Trace, CompletionSpec]:
    return (
        EventCatalog.load(EXAMPLE / "event_types.yaml"),
        Trace.load(EXAMPLE / trace_name),
        CompletionSpec.load(EXAMPLE / model),
    )


def test_young_load_old_hit_response_probe_and_observed_path() -> None:
    catalog, trace, spec = _v04_inputs()
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.added_event_ids == (
        "l0_tlb_miss",
        "retry_enqueue_0",
        "retry_issue_0",
        "l0_tlb_hit",
        "dcache_req_valid_0",
        "dcache_req_ready_0",
        "dcache_req_fire_0",
        "l1_dcache_req_valid",
        "l1_dcache_req_ready",
        "l1_dcache_req_fire",
        "l1_load_executed",
        "l1_dcache_hit",
        "l1_dcache_response",
        "l1_load_succeeded",
        "probe_receive_x",
        "probe_release_x",
        "l1_load_observed",
    )

    completed = result.completed_trace
    assert completed.get("l1_dcache_req_fire").cycle < completed.get("l1_load_executed").cycle
    assert completed.get("l1_load_executed").cycle < completed.get("l1_dcache_hit").cycle
    assert completed.get("l1_dcache_hit").cycle < completed.get("l1_dcache_response").cycle
    assert completed.get("l1_dcache_response").fields["value"] == 0
    assert completed.get("l1_load_succeeded").fields["value"] == 0
    assert completed.get("l1_load_succeeded").cycle < completed.get("store_w1").cycle
    assert completed.get("store_w1").cycle < completed.get("probe_receive_x").cycle
    assert completed.get("probe_receive_x").cycle < completed.get("probe_release_x").cycle
    assert completed.get("probe_release_x").cycle < completed.get("l1_load_observed").cycle
    assert completed.get("l1_load_observed").cycle < completed.get("retry_issue_0").cycle

    assert result.final_state["LSU.ldq.L1.executed"] is True
    assert result.final_state["LSU.ldq.L1.succeeded"] is True
    assert result.final_state["LSU.ldq.L1.observed"] is True
    assert result.final_state["LSU.ldq.L1.value"] == 0
    assert result.final_state["DCache.probe.pending"] is False
    assert result.final_state["DCache.probe.address"] == "x"
    assert result.final_state["DCache.probe.source_op_id"] == "W1"


def test_probe_release_for_different_block_cannot_mark_l1_observed() -> None:
    catalog, trace, spec = _v04_inputs("young_load_probe_address_mismatch.yaml")
    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_dcache_nack_clears_executed_and_does_not_succeed() -> None:
    catalog, trace, spec = _v04_inputs("young_load_nack_completion.yaml")
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert "l1_dcache_nack" in result.added_event_ids
    assert "l1_dcache_hit" not in result.added_event_ids
    assert "l1_dcache_response" not in result.added_event_ids
    assert "l1_load_succeeded" not in result.added_event_ids
    assert "l1_load_observed" not in result.added_event_ids
    assert result.final_state["LSU.ldq.L1.executed"] is False
    assert result.final_state["LSU.ldq.L1.succeeded"] is False
    assert result.final_state["LSU.ldq.L1.observed"] is False
    assert result.final_state["LSU.ldq.L1.value"] == "UNSET_VALUE"


def test_same_load_attempt_cannot_be_nacked_and_succeed() -> None:
    catalog, trace, spec = _v04_inputs("young_load_nack_plus_success.yaml")
    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_v04_completion_spec_roundtrip(tmp_path: Path) -> None:
    _, _, spec = _v04_inputs()
    path = tmp_path / "v04.json"
    spec.dump(path)
    loaded = CompletionSpec.load(path)
    assert loaded.to_dict() == spec.to_dict()
    assert loaded.schema_version == "umcm.completion.v0.4.0"
    assert len(loaded.state_variables) == 15



def _v05_inputs(
    model: str,
    trace_name: str = "stage5_trace.yaml",
) -> tuple[EventCatalog, Trace, CompletionSpec]:
    return (
        EventCatalog.load(EXAMPLE / "event_types.yaml"),
        Trace.load(EXAMPLE / trace_name),
        CompletionSpec.load(EXAMPLE / model),
    )


def test_buggy_ldld_conflict_reaches_assert_without_order_fail_and_commits() -> None:
    catalog, trace, spec = _v05_inputs("load_load_buggy_completion.yaml")
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    completed = result.completed_trace

    assert completed.get("dcache_req_fire_0").cycle < completed.get("l0_ldld_search").cycle
    assert completed.get("l0_ldld_search").cycle == completed.get("l0_l1_ldld_conflict").cycle
    assert completed.get("l0_l1_ldld_conflict").cycle == completed.get("ldld_assert_violation").cycle
    assert completed.get("commit_l0").cycle < completed.get("commit_l1").cycle
    assert completed.get("commit_l1").fields["value"] == 0

    assert "l1_order_fail" not in result.added_event_ids
    assert "l1_mem_order_exception" not in result.added_event_ids
    assert "l1_squash" not in result.added_event_ids
    assert result.final_state["LSU.ldq.L1.order_fail"] is False
    assert result.final_state["LSU.ldq.L1.squashed"] is False
    # Retirement consumes the still-valid LDQ entry in the buggy model.
    assert result.final_state["LSU.ldq.L1.valid"] is False


def test_fixed_ldld_conflict_generates_order_fail_exception_and_squash() -> None:
    catalog, trace, spec = _v05_inputs(
        "load_load_fixed_completion.yaml",
        "stage5_recovery_trace.yaml",
    )
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    completed = result.completed_trace
    assert completed.get("l0_ldld_search").cycle == completed.get("l0_l1_ldld_conflict").cycle
    assert completed.get("l0_l1_ldld_conflict").cycle == completed.get("l1_order_fail").cycle
    assert completed.get("l1_order_fail").cycle < completed.get("l1_mem_order_exception").cycle
    assert completed.get("l1_mem_order_exception").cycle < completed.get("l1_squash").cycle
    assert "ldld_assert_violation" not in result.added_event_ids
    assert "commit_l1" not in {event.id for event in completed.events}
    assert result.final_state["LSU.ldq.L1.order_fail"] is True
    assert result.final_state["LSU.ldq.L1.squashed"] is True
    assert result.final_state["LSU.ldq.L1.valid"] is False


def test_fixed_model_blocks_the_same_forbidden_l1_retirement() -> None:
    catalog, trace, spec = _v05_inputs("load_load_fixed_completion.yaml")
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.INFEASIBLE
    assert "l1_commit_requires_valid_executed_succeeded_load" in result.reason
    assert "LSU.ldq.L1.valid == True" in result.reason
    assert "pre-state is False" in result.reason


def test_ldld_conflict_requires_the_observed_younger_state() -> None:
    catalog, trace, spec = _v05_inputs("load_load_buggy_completion.yaml")
    spec.slots = [
        replace(slot, required=False)
        if slot.id == "l1_load_observed"
        else slot
        for slot in spec.slots
    ]
    from umcm.ir.expression import EventField, Unary
    from umcm.ir.sort import BOOL

    spec.constraints.append(
        Unary("not", EventField("l1_load_observed", "occurs", BOOL))
    )
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.INFEASIBLE
    assert "LSU.ldq.L1.observed == True" in result.reason


def test_v05_models_roundtrip(tmp_path: Path) -> None:
    for model in (
        "load_load_buggy_completion.yaml",
        "load_load_fixed_completion.yaml",
    ):
        _, _, spec = _v05_inputs(model)
        path = tmp_path / f"{model}.json"
        spec.dump(path)
        loaded = CompletionSpec.load(path)
        assert loaded.to_dict() == spec.to_dict()
        assert loaded.schema_version == "umcm.completion.v0.5.0"
        assert len(loaded.state_variables) == 18



def _v06_inputs(
    model: str = "load_load_buggy_mshr_completion.yaml",
    trace_name: str = "stage6_trace.yaml",
) -> tuple[EventCatalog, Trace, CompletionSpec]:
    return (
        EventCatalog.load(EXAMPLE / "event_types.yaml"),
        Trace.load(EXAMPLE / trace_name),
        CompletionSpec.load(EXAMPLE / model),
    )


def test_buggy_full_mshr_path_completes_l0_new_value_and_both_retire() -> None:
    catalog, trace, spec = _v06_inputs()
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    completed = result.completed_trace

    expected_path = (
        "l0_dcache_miss",
        "l0_mshr_primary_accept",
        "l0_mshr_rpq_enqueue",
        "l0_mshr_acquire",
        "l0_mshr_grant_data",
        "l0_mshr_refill_complete",
        "l0_mshr_drain_rpq",
        "l0_long_latency_response",
        "l0_load_succeeded",
    )
    for event_id in expected_path:
        assert event_id in result.added_event_ids

    assert completed.get("l0_dcache_miss").cycle == 14
    assert completed.get("l0_mshr_primary_accept").cycle == 14
    assert completed.get("l0_mshr_acquire").cycle == 15
    assert completed.get("l0_mshr_grant_data").cycle == 16
    assert completed.get("l0_mshr_drain_rpq").cycle == 17
    assert completed.get("l0_load_succeeded").fields["value"] == 1
    assert completed.get("commit_l0").fields["value"] == 1
    assert completed.get("commit_l1").fields["value"] == 0

    assert result.final_state["MSHR.0.req_op_id"] == "L0"
    assert result.final_state["MSHR.0.req_ldq_idx"] == 0
    assert result.final_state["MSHR.0.rpq_valid"] is False
    assert result.final_state["MSHR.0.line_value"] == 1
    assert result.final_state["MSHR.0.line_source_op_id"] == "W1"
    assert result.final_state["LSU.ldq.L0.succeeded"] is True
    assert result.final_state["LSU.ldq.L0.value"] == 1
    assert result.final_state["LSU.ldq.L0.valid"] is False


def test_scoped_exact_producers_allow_l0_and_l1_executed_events() -> None:
    catalog, trace, spec = _v06_inputs()
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert result.completed_trace.get("l0_load_executed").fields["op_id"] == "L0"
    assert result.completed_trace.get("l1_load_executed").fields["op_id"] == "L1"

    l0_rule = next(
        item for item in spec.transformations
        if item.name == "l0_accepted_request_marks_executed"
    )
    l1_rule = next(
        item for item in spec.transformations
        if item.name == "l1_accepted_request_marks_executed"
    )
    assert l0_rule.exact and l1_rule.exact
    assert l0_rule.output_when.to_dict() != l1_rule.output_when.to_dict()


def test_grant_data_must_be_sourced_from_the_visible_store() -> None:
    catalog, trace, spec = _v06_inputs()
    spec.slots = [
        replace(
            slot,
            fields={**slot.fields, "source_op_id": "InitX"},
        )
        if slot.id == "l0_mshr_grant_data"
        else slot
        for slot in spec.slots
    ]

    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_rpq_identity_mismatch_blocks_long_latency_response() -> None:
    catalog, trace, spec = _v06_inputs()
    spec.slots = [
        replace(slot, fields={**slot.fields, "ldq_idx": 1})
        if slot.id == "l0_mshr_rpq_enqueue"
        else slot
        for slot in spec.slots
    ]

    result = complete_trace(catalog, trace, spec)
    assert result.status is CompletionStatus.INFEASIBLE


def test_fixed_full_path_keeps_l0_refill_but_squashes_l1() -> None:
    catalog, trace, spec = _v06_inputs(
        "load_load_fixed_mshr_completion.yaml",
        "stage6_recovery_trace.yaml",
    )
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    completed_ids = {event.id for event in result.completed_trace.events}
    assert "l0_load_succeeded" in completed_ids
    assert "commit_l0" in completed_ids
    assert "l1_order_fail" in completed_ids
    assert "l1_mem_order_exception" in completed_ids
    assert "l1_squash" in completed_ids
    assert "commit_l1" not in completed_ids
    assert result.final_state["LSU.ldq.L0.value"] == 1
    assert result.final_state["LSU.ldq.L1.squashed"] is True


def test_fixed_full_model_blocks_same_forbidden_two_load_retirement() -> None:
    catalog, trace, spec = _v06_inputs("load_load_fixed_mshr_completion.yaml")
    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.INFEASIBLE
    assert "l1_commit_requires_valid_executed_succeeded_load" in result.reason
    assert "LSU.ldq.L1.valid == True" in result.reason


def test_v06_models_roundtrip(tmp_path: Path) -> None:
    for model in (
        "load_load_buggy_mshr_completion.yaml",
        "load_load_fixed_mshr_completion.yaml",
    ):
        _, _, spec = _v06_inputs(model)
        path = tmp_path / f"{model}.json"
        spec.dump(path)
        loaded = CompletionSpec.load(path)
        assert loaded.to_dict() == spec.to_dict()
        assert loaded.schema_version == "umcm.completion.v0.6.0"
        assert len(loaded.state_variables) == 32
