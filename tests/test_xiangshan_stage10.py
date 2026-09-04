from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.coverage import CoverageSuite, run_coverage
from umcm.coverage.engine import CoverageStatus
from umcm.hierarchy import build_interface_contracts
from umcm.ir import EventCatalog, EventInstance, Trace
from umcm.ir.event import Visibility
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
XIANGSHAN = ROOT / "examples" / "xiangshan"
SBUFFER_TRACES = XIANGSHAN / "traces" / "sbuffer"
SBUFFER_COMPOSITION = XIANGSHAN / "composition" / "sbuffer.yaml"
INTEGRATED_COMPOSITION = XIANGSHAN / "composition" / "scalar_store_sbuffer.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def sbuffer_result(case: str):
    source = Trace.load(SBUFFER_TRACES / f"{case}.yaml")
    composed = compose_modules(
        catalog(), CompositionSpec.load(SBUFFER_COMPOSITION), source
    )
    return complete_trace(catalog(), source, composed.completion, backend="z3")


@lru_cache(maxsize=None)
def integrated_result(case: str):
    source = Trace.load(XIANGSHAN / "traces" / "store" / f"{case}.yaml")
    composed = compose_modules(
        catalog(), CompositionSpec.load(INTEGRATED_COMPOSITION), source
    )
    return complete_trace(catalog(), source, composed.completion, backend="z3")


def feasible(result) -> Trace:
    assert result.status is CompletionStatus.FEASIBLE, result.reason
    assert result.completed_trace is not None
    return result.completed_trace


def event(trace: Trace, event_type: str, **fields: object) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    for name, value in fields.items():
        matches = [item for item in matches if item.fields.get(name) == value]
    assert len(matches) == 1, (event_type, fields, [(x.id, x.fields) for x in matches])
    return matches[0]


def test_single_store_is_shifted_to_one_cache_line_request() -> None:
    trace = feasible(sbuffer_result("single_store_hit"))
    drain = event(trace, "Store.Drain", op_id="S0")
    allocation = event(trace, "SBuffer.Allocate", entry_id="E0")
    request = event(trace, "L1.Request", txn_id="E0")
    accepted = event(trace, "SBuffer.WriteAccepted", entry_id="E0")
    assert drain.cycle < allocation.cycle < request.cycle < accepted.cycle
    assert request.fields["address"] == 8192
    assert request.fields["byte_mask"] == 15 << 8
    assert request.fields["line_data"] == 170 << 64


def test_same_line_merge_preserves_old_byte_and_overwrites_new_byte() -> None:
    trace = feasible(sbuffer_result("merged_store"))
    merge = event(trace, "SBuffer.Merge", entry_id="EM")
    request = event(trace, "L1.Request", txn_id="EM")
    assert merge.fields["byte_mask"] == request.fields["byte_mask"] == 0b11
    assert merge.fields["line_data"] == request.fields["line_data"] == 0xAA11
    assert len([x for x in trace.events_of_type("L1.Request") if x.fields["attempt"] == 0]) == 1


def test_dcache_replay_keeps_payload_and_retries_before_release() -> None:
    trace = feasible(sbuffer_result("replay_then_retry"))
    replay = event(trace, "L1.Response", txn_id="ER")
    retry = event(trace, "L1.Request", txn_id="ER:retry")
    hit = event(trace, "L1.Response", txn_id="ER:retry")
    accepted = event(trace, "SBuffer.WriteAccepted", txn_id="ER:retry")
    assert not replay.fields["success"] and replay.fields["response_kind"] == "replay"
    assert replay.cycle < retry.cycle < hit.cycle == accepted.cycle
    assert retry.fields["line_data"] == 90 and retry.fields["byte_mask"] == 1


def test_fence_completion_waits_until_older_entry_is_accepted() -> None:
    trace = feasible(sbuffer_result("fence_drain"))
    fence = event(trace, "Core.FenceRequest", op_id="F0")
    accepted = event(trace, "SBuffer.WriteAccepted", entry_id="EF")
    ordered = event(trace, "Core.MemoryOrdered", op_id="F0")
    assert fence.cycle < accepted.cycle < ordered.cycle


def test_same_block_inflight_entries_are_serialized() -> None:
    trace = feasible(sbuffer_result("same_block_serialized"))
    older_accept = event(trace, "SBuffer.WriteAccepted", entry_id="E0")
    younger_request = event(trace, "L1.Request", txn_id="E1")
    assert older_accept.cycle < younger_request.cycle


@pytest.mark.parametrize(
    "case",
    ["wrong_merged_payload", "fence_completes_early", "same_block_bypass"],
)
def test_illegal_sbuffer_behaviors_are_unsat(case: str) -> None:
    assert sbuffer_result(case).status is CompletionStatus.INFEASIBLE


def test_committed_scalar_store_closes_through_l1_acceptance() -> None:
    trace = feasible(integrated_result("integrated_sbuffer"))
    commit = event(trace, "SQ.Commit", op_id="SBINT")
    drain = event(trace, "Store.Drain", op_id="SBINT")
    request = event(trace, "L1.Request", txn_id="ESB")
    response = event(trace, "L1.Response", txn_id="ESB")
    assert commit.cycle < drain.cycle < request.cycle < response.cycle
    assert request.fields["line_data"] == 42 << 64


def test_uncommitted_store_cannot_escape_through_sbuffer() -> None:
    assert integrated_result("uncommitted_sbuffer_request").status is CompletionStatus.INFEASIBLE


def test_stage10_interface_inventories_and_private_encapsulation() -> None:
    cases = [
        (
            SBUFFER_COMPOSITION,
            SBUFFER_TRACES / "single_store_hit.yaml",
            XIANGSHAN / "hierarchy" / "sbuffer_interfaces.yaml",
        ),
        (
            INTEGRATED_COMPOSITION,
            XIANGSHAN / "traces" / "store" / "integrated_sbuffer.yaml",
            XIANGSHAN / "hierarchy" / "scalar_store_sbuffer_interfaces.yaml",
        ),
    ]
    for composition_path, trace_path, inventory_path in cases:
        source = Trace.load(trace_path)
        composition = CompositionSpec.load(composition_path)
        composed = compose_modules(catalog(), composition, source)
        expected = {
            "schema_version": "umcm.interfaces.v0.15.0",
            "composition": composition.name,
            "policy": "ports-only-public-surface",
            "modules": [item.to_dict() for item in build_interface_contracts(composed)],
        }
        assert load_data(inventory_path) == expected

    for path in SBUFFER_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage10_source_metadata_is_pinned() -> None:
    source = Trace.load(SBUFFER_TRACES / "single_store_hit.yaml")
    module = compose_modules(
        catalog(), CompositionSpec.load(SBUFFER_COMPOSITION), source
    ).modules[0].spec
    assert module.metadata["source_commit"] == "50cdcfc2c45d0631591310435835c0180c105489"
    assert module.metadata["source_sha256"] == "56c6e5d5fb5395f2e6c988f6b9fb88b19eec999d5b5354dbea616cf9f526152d"
    assert module.metadata["parameters"] == {
        "store_buffer_size": 16,
        "store_buffer_threshold": 9,
        "ensbuffer_width": 2,
        "cache_line_bytes": 64,
        "vector_length_bytes": 16,
        "dcache_write_ports": 1,
        "replay_delay_cycles": 16,
    }


def test_stage10_required_path_coverage_is_complete() -> None:
    report = run_coverage(
        CoverageSuite.load(XIANGSHAN / "coverage" / "stage10.yaml"), backend="z3"
    )
    assert report.required_complete
    assert [item.status for item in report.results] == [CoverageStatus.COVERED] * 7
