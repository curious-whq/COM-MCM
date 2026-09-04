from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.provenance import audit_source_ledger, verify_source_checkout
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "examples/boom/source/v021.yaml"


def test_v021_source_ledger_is_structurally_valid_and_honestly_incomplete():
    report = audit_source_ledger(LEDGER)
    assert report.behavior_count >= 20
    assert not report.complete
    assert report.implemented_count < report.behavior_count
    assert not any("dcache." in item for item in report.blockers)
    assert not any("lsu.resource-arbitration" in item for item in report.blockers)
    assert not any("mshr.primary-secondary-allocation" in item for item in report.blockers)
    assert not any("integration.mshr-file-entry-readiness" in item for item in report.blockers)
    assert any("integration.default-detailed-memory-composition" in item for item in report.blockers)


def test_v021_ledger_pins_real_upstream_checkouts_when_available():
    upstream = ROOT.parent / "upstream"
    boom = upstream / "riscv-boom"
    rocket_chip = upstream / "rocket-chip-v021"
    inclusive = upstream / "block-inclusivecache-sifive"
    if not boom.is_dir() or not rocket_chip.is_dir() or not inclusive.is_dir():
        return
    verify_source_checkout(
        LEDGER,
        {
            "boom": boom,
            "rocket_chip": rocket_chip,
            "inclusive_cache": inclusive,
            "chipyard": upstream / "chipyard-v021",
        },
    )


def test_v021_acceptance_forbids_the_old_summary_path():
    ledger = load_data(LEDGER)
    forbidden = ledger["acceptance"]["forbidden_default_module_prefixes"]
    assert "examples/boom/model/search/" in forbidden

    search = load_data(ROOT / "examples/boom/search/v021.yaml")
    stage = search["realization"]["stages"][0]
    assert stage["kind"] == "interface_gap"
    assert "composition" not in stage
    assert "core_composition" not in stage

    prototype = load_data(ROOT / "examples/boom/composition/core_blind_v021.yaml")
    referenced = [item["path"] for item in prototype["modules"]]
    assert any("model/search/cacheable_path.yaml" in path for path in referenced)


def test_v021_lsq_allocates_indices_without_microarchitecture_annotations():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(
        ROOT / "examples/boom/traces/source_model/lsq_internal_allocation.yaml"
    )
    assert all("microarch" not in event.annotations for event in trace.events)
    composition = CompositionSpec.load(
        ROOT / "examples/boom/composition/lsq_source_v021.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    assert [item["ldq_idx"] for item in composed.resolved_roles["loads"]] == [0, 1]
    assert [item["stq_idx"] for item in composed.resolved_roles["local_stores"]] == [0]
    states = {item.name for item in composed.completion.state_variables}
    assert "LSU.ldq[0].valid" in states
    assert "LSU.ldq[1].valid" in states
    assert "LSU.stq[0].valid" in states

    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    allocations = {
        (event.event_type, event.fields["op_id"]): event.fields
        for event in solved.completed_trace.events
        if event.event_type in {"LSU.LDQAllocate", "LSU.STQAllocate"}
    }
    assert allocations[("LSU.LDQAllocate", "LoadA")]["ldq_idx"] == 0
    assert allocations[("LSU.LDQAllocate", "LoadB")]["ldq_idx"] == 1
    assert allocations[("LSU.STQAllocate", "StoreC")]["stq_idx"] == 0


def test_v021_mshr_grant_is_driven_by_inclusive_l2_tilelink_d():
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(
        ROOT / "examples/boom/traces/source_model/mshr_tilelink_primary.yaml"
    )
    composition = CompositionSpec.load(
        ROOT / "examples/boom/composition/mshr_tilelink_source_v021.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    grant_d = next(
        event
        for event in solved.completed_trace.events
        if event.event_type == "TL.Grant" and event.occurs is True
    )
    mshr_grant = next(
        event
        for event in solved.completed_trace.events
        if event.event_type == "MSHR.GrantData" and event.occurs is True
    )
    assert grant_d.fields["source_id"] == mshr_grant.fields["mshr_id"] == 0
    assert grant_d.fields["txn_id"] == mshr_grant.fields["op_id"] == "Ld0"
    assert grant_d.fields["value"] == mshr_grant.fields["value"] == 11
    assert grant_d.fields["source_op_id"] == mshr_grant.fields["source_op_id"]
    assert grant_d.cycle == mshr_grant.cycle
    assert any(
        event.event_type == "TL.GrantAck" and event.occurs is True
        for event in solved.completed_trace.events
    )


def _complete_allocator_trace(name: str):
    catalog = EventCatalog.load(ROOT / "examples/boom/events.yaml")
    trace = Trace.load(ROOT / f"examples/boom/traces/source_model/{name}.yaml")
    composition = CompositionSpec.load(
        ROOT / "examples/boom/composition/mshr_allocator_source_v021.yaml"
    )
    composed = compose_modules(catalog, composition, trace)
    solved = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert solved.status is CompletionStatus.FEASIBLE
    assert solved.completed_trace is not None
    return solved.completed_trace


def test_v021_mshr_file_selects_primary_and_secondary_ids_internally():
    completed = _complete_allocator_trace("mshr_internal_allocation")
    requests = {
        event.fields["op_id"]: event.fields
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    }
    assert requests["A"]["mshr_id"] == 0
    assert requests["A"]["secondary"] is False
    assert requests["B"]["mshr_id"] == 0
    assert requests["B"]["secondary"] is True
    assert requests["C"]["mshr_id"] == 1
    assert requests["C"]["secondary"] is False
    source = Trace.load(
        ROOT / "examples/boom/traces/source_model/mshr_internal_allocation.yaml"
    )
    assert all("mshr_id" not in event.fields for event in source.events)
    assert all("secondary" not in event.fields for event in source.events)


def test_v021_mshr_file_blocks_same_index_different_tag():
    completed = _complete_allocator_trace("mshr_index_conflict")
    assert not any(
        event.event_type == "DCache.MSHRRequest"
        and event.occurs is True
        and event.fields["op_id"] == "Conflict"
        for event in completed.events
    )
    blocked = next(
        event
        for event in completed.events
        if event.event_type == "MSHRFile.RequestBlocked"
        and event.occurs is True
        and event.fields["op_id"] == "Conflict"
    )
    assert blocked.fields["reason"] == "index-conflict-0"


def test_v021_mshr_file_reports_all_busy_without_allocating_a_third_entry():
    completed = _complete_allocator_trace("mshr_all_busy")
    requests = [
        event
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    ]
    assert {(event.fields["op_id"], event.fields["mshr_id"]) for event in requests} == {
        ("A", 0),
        ("B", 1),
    }
    blocked = next(
        event
        for event in completed.events
        if event.event_type == "MSHRFile.RequestBlocked"
        and event.occurs is True
        and event.fields["op_id"] == "C"
    )
    assert blocked.fields["reason"] == "all-busy"


def test_v021_mshr_file_reuses_an_entry_only_after_mem_finish():
    completed = _complete_allocator_trace("mshr_finish_reuse")
    requests = {
        event.fields["op_id"]: event.fields["mshr_id"]
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    }
    assert requests == {"A": 0, "B": 1, "C": 0}


def test_v021_mshr_file_rejects_secondary_requiring_another_acquire():
    completed = _complete_allocator_trace("mshr_secondary_not_ready")
    assert not any(
        event.event_type == "DCache.MSHRRequest"
        and event.occurs is True
        and event.fields["op_id"] == "B"
        for event in completed.events
    )
    blocked = next(
        event
        for event in completed.events
        if event.event_type == "MSHRFile.RequestBlocked"
        and event.occurs is True
        and event.fields["op_id"] == "B"
    )
    assert blocked.fields["reason"] == "second-acquire-0"


def test_v021_mshr_file_derives_secondary_write_intent_matrix():
    completed = _complete_allocator_trace("mshr_secondary_command_matrix")
    requests = {
        event.fields["op_id"]: event.fields
        for event in completed.events
        if event.event_type == "DCache.MSHRRequest" and event.occurs is True
    }
    assert set(requests) == {"A", "B", "C"}
    assert requests["A"]["mshr_id"] == 0
    assert requests["A"]["secondary"] is False
    assert requests["B"]["mshr_id"] == requests["C"]["mshr_id"] == 0
    assert requests["B"]["secondary"] is requests["C"]["secondary"] is True


def test_v021_mshr_file_classifies_lr_as_write_intent():
    completed = _complete_allocator_trace("mshr_lr_requires_second_acquire")
    blocked = next(
        event
        for event in completed.events
        if event.event_type == "MSHRFile.RequestBlocked"
        and event.occurs is True
        and event.fields["op_id"] == "LR"
    )
    assert blocked.fields["reason"] == "second-acquire-0"


def test_v021_mshr_file_blocks_probe_from_secondary_path():
    completed = _complete_allocator_trace("mshr_probe_secondary_block")
    blocked = next(
        event
        for event in completed.events
        if event.event_type == "MSHRFile.RequestBlocked"
        and event.occurs is True
        and event.fields["op_id"] == "P"
    )
    assert blocked.fields["reason"] == "probe-0"
