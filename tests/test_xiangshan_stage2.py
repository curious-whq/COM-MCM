from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.coverage import CoverageSuite, run_coverage
from umcm.coverage.engine import CoverageStatus
from umcm.hierarchy import build_interface_contracts
from umcm.ir import EventCatalog, Trace
from umcm.ir.event import Visibility
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
XIANGSHAN = ROOT / "examples" / "xiangshan"
CORE_TRACES = XIANGSHAN / "traces" / "core"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def result(case: str):
    source = Trace.load(CORE_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "core_lifecycle.yaml"
    )
    composed = compose_modules(catalog(), composition, source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


def feasible(case: str) -> Trace:
    completed = result(case)
    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    return completed.completed_trace


def event(trace: Trace, event_type: str, op_id: str | None = None):
    matches = list(trace.events_of_type(event_type))
    if op_id is not None:
        identity = "source_op_id" if event_type == "Core.Redirect" else "op_id"
        matches = [item for item in matches if item.fields.get(identity) == op_id]
    assert len(matches) == 1, (event_type, op_id, [item.id for item in matches])
    return matches[0]


def test_normal_memory_uop_runs_dispatch_to_in_order_commit() -> None:
    trace = feasible("normal_commit")

    instruction = event(trace, "Core.MemoryInstruction", "L0")
    allocate = event(trace, "Core.DispatchAllocate", "L0")
    issue = event(trace, "Core.MemoryIssue", "L0")
    complete = event(trace, "Core.MemoryWriteback", "L0")
    rob_writeback = event(trace, "Core.ROBWriteback", "L0")
    select = event(trace, "Core.ROBCommitSelect", "L0")
    commit = event(trace, "Core.MemoryCommit", "L0")

    assert instruction.cycle < allocate.cycle < issue.cycle
    assert issue.cycle < complete.cycle < rob_writeback.cycle
    assert rob_writeback.cycle < select.cycle < commit.cycle


def test_precise_fault_waits_for_older_commit_and_squashes_tail() -> None:
    trace = feasible("precise_exception")

    older_commit = event(trace, "Core.MemoryCommit", "OLD")
    fault = event(trace, "Core.MemoryFault", "FAULT")
    record = event(trace, "Core.ExceptionRecord", "FAULT")
    redirect = event(trace, "Core.Redirect", "FAULT")
    fault_apply = event(trace, "Core.RedirectApply", "FAULT")
    young_apply = event(trace, "Core.RedirectApply", "YOUNG")

    assert event(trace, "Core.MemoryIssue", "FAULT").cycle < fault.cycle
    assert fault.cycle < record.cycle
    assert older_commit.cycle < redirect.cycle
    assert redirect.cycle < fault_apply.cycle
    assert redirect.cycle < young_apply.cycle
    assert {item.fields["op_id"] for item in trace.events_of_type("Core.MemoryCommit")} == {"OLD"}


def test_ghost_commit_without_writeback_is_unsat() -> None:
    assert result("ghost_commit").status is CompletionStatus.INFEASIBLE


def test_redirected_younger_late_writeback_is_unsat() -> None:
    trace = feasible("redirect_clear")
    redirect = event(trace, "Core.Redirect", "FAULT")
    killed = event(trace, "Core.RedirectApply", "KILLED")
    assert redirect.cycle < killed.cycle
    assert not list(trace.events_of_type("Core.MemoryCommit"))

    assert result("redirect_late_writeback").status is CompletionStatus.INFEASIBLE


def test_stage2_interface_inventory_and_private_encapsulation() -> None:
    source = Trace.load(CORE_TRACES / "normal_commit.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "core_lifecycle.yaml"
    )
    composed = compose_modules(catalog(), composition, source)
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": composition.name,
        "policy": "ports-only-public-surface",
        "modules": [
            contract.to_dict() for contract in build_interface_contracts(composed)
        ],
    }
    assert load_data(
        XIANGSHAN / "hierarchy" / "core_lifecycle_interfaces.yaml"
    ) == expected

    for path in CORE_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage2_source_metadata_is_pinned() -> None:
    source = Trace.load(CORE_TRACES / "normal_commit.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "core_lifecycle.yaml"
    )
    module = compose_modules(catalog(), composition, source).modules[0].spec
    assert module.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert module.metadata["source_files"] == [
        "src/main/scala/xiangshan/backend/dispatch/Dispatch.scala:662-748",
        "src/main/scala/xiangshan/backend/rob/Rob.scala:464-493,599-724,792-855,881-929,1031-1085,1131-1150,1198-1269",
        "src/main/scala/xiangshan/backend/rob/RobBundles.scala:208-212",
        "src/main/scala/xiangshan/backend/rob/ExceptionGen.scala:34-180",
    ]


def test_stage2_required_path_coverage_is_complete() -> None:
    suite = CoverageSuite.load(XIANGSHAN / "coverage" / "stage2.yaml")
    report = run_coverage(suite, backend="z3")
    assert report.required_complete
    assert [item.status for item in report.results] == [
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
    ]
