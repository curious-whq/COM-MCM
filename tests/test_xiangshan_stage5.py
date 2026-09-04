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
LOAD_TRACES = XIANGSHAN / "traces" / "load"
SCALAR_COMPOSITION = XIANGSHAN / "composition" / "scalar_load.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def result(case: str):
    source = Trace.load(LOAD_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(SCALAR_COMPOSITION)
    composed = compose_modules(catalog(), composition, source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


def feasible(case: str) -> Trace:
    completed = result(case)
    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    return completed.completed_trace


def event(
    trace: Trace,
    event_type: str,
    **field_values: object,
) -> EventInstance:
    matches = list(trace.events_of_type(event_type))
    for field, value in field_values.items():
        matches = [item for item in matches if item.fields.get(field) == value]
    assert len(matches) == 1, (
        event_type,
        field_values,
        [(item.id, item.fields) for item in matches],
    )
    return matches[0]


def test_cache_hit_reaches_s3_and_writes_cache_value() -> None:
    trace = feasible("cache_hit")
    s0 = event(trace, "Load.StageAdvance", stage="s0")
    s1 = event(trace, "Load.StageAdvance", stage="s1")
    s2 = event(trace, "Load.StageAdvance", stage="s2")
    s3 = event(trace, "Load.StageAdvance", stage="s3")
    writeback = event(trace, "Core.MemoryWriteback", op_id="L0")
    update = event(trace, "Load.PipelineUpdate", op_id="L0")

    assert s0.cycle < s1.cycle < s2.cycle < s3.cycle < writeback.cycle
    assert s2.fields["data_source"] == "l1"
    assert writeback.fields["value"] == 42
    assert update.fields["succeeded"] is True
    assert not [
        item
        for item in trace.events_of_type("Load.StageAdvance")
        if item.fields.get("stage") == "s4"
    ]


def test_full_store_forward_supplies_writeback_value() -> None:
    trace = feasible("full_forward")
    selected = event(trace, "Load.ForwardSelect", data_source="store_forward")
    writeback = event(trace, "Core.MemoryWriteback", op_id="LFWD")

    assert selected.fields["value"] == 99
    assert writeback.fields["value"] == 99
    assert not [
        item
        for item in trace.events_of_type("Load.ForwardSelect")
        if item.fields.get("data_source") == "l1"
    ]


@pytest.mark.parametrize(
    ("case", "source", "cause"),
    [
        ("tlb_replay", "tlb", "tlb_miss"),
        ("l1_nack", "l1_nack", "mshr_nack"),
        ("dcache_miss", "l1_miss", "dcache_miss"),
        ("forward_invalid", "forward_invalid", "forward_data_invalid"),
    ],
)
def test_replay_causes_do_not_write_back(
    case: str, source: str, cause: str
) -> None:
    trace = feasible(case)
    decision = event(trace, "Load.ReplayDecision", replay_source=source)
    update = event(trace, "Load.PipelineUpdate")

    assert decision.fields["cause"] == cause
    assert update.fields["succeeded"] is False
    assert update.fields["replay_cause"] == cause
    assert not list(trace.events_of_type("Core.MemoryWriteback"))


@pytest.mark.parametrize(
    ("case", "source", "cause"),
    [
        ("translation_fault", "translation", "load_page_fault"),
        ("l1_denied", "l1_denied", "load_access_fault"),
        ("l1_corrupt", "l1_corrupt", "hardware_error"),
    ],
)
def test_faults_reach_core_without_writeback(
    case: str, source: str, cause: str
) -> None:
    trace = feasible(case)
    decision = event(trace, "Load.FaultDecision", fault_source=source)
    fault = event(trace, "Core.MemoryFault")
    update = event(trace, "Load.PipelineUpdate")

    assert decision.fields["cause"] == cause
    assert fault.fields["cause"] == cause
    assert update.fields["fault"] is True
    assert update.fields["succeeded"] is False
    assert not list(trace.events_of_type("Core.MemoryWriteback"))


@pytest.mark.parametrize("case", ["nack_cannot_writeback", "wrong_forward_value"])
def test_invalid_public_completion_is_unsat(case: str) -> None:
    assert result(case).status is CompletionStatus.INFEASIBLE


def test_scalar_load_integrates_with_l1_dtlb_hit() -> None:
    source = Trace.load(LOAD_TRACES / "integrated_dtlb_hit.yaml")
    composition = CompositionSpec.load(
        XIANGSHAN / "composition" / "load_translation.yaml"
    )
    composed = compose_modules(catalog(), composition, source)
    completed = complete_trace(catalog(), source, composed.completion, backend="z3")

    assert completed.status is CompletionStatus.FEASIBLE, completed.reason
    assert completed.completed_trace is not None
    trace = completed.completed_trace
    request = event(trace, "MMU.TranslateRequest", op_id="LINT", attempt=0)
    hit = event(trace, "MMU.L1TLBHit", op_id="LINT", attempt=0)
    response = event(trace, "MMU.TranslateResponse", op_id="LINT", attempt=0)
    writeback = event(trace, "Core.MemoryWriteback", op_id="LINT")

    assert request.cycle < hit.cycle < response.cycle < writeback.cycle
    assert response.fields["paddr"] == 8192
    assert writeback.fields["value"] == 123


def test_stage5_interface_inventory_and_private_encapsulation() -> None:
    source = Trace.load(LOAD_TRACES / "cache_hit.yaml")
    composition = CompositionSpec.load(SCALAR_COMPOSITION)
    composed = compose_modules(catalog(), composition, source)
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": composition.name,
        "policy": "ports-only-public-surface",
        "modules": [
            contract.to_dict() for contract in build_interface_contracts(composed)
        ],
    }
    assert load_data(XIANGSHAN / "hierarchy" / "scalar_load_interfaces.yaml") == expected

    for path in LOAD_TRACES.glob("*.yaml"):
        for observed in Trace.load(path).events:
            assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage5_source_metadata_is_pinned() -> None:
    source = Trace.load(LOAD_TRACES / "cache_hit.yaml")
    composition = CompositionSpec.load(SCALAR_COMPOSITION)
    module = compose_modules(catalog(), composition, source).modules[0].spec

    assert module.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert module.metadata["source_files"] == [
        "src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala:43-490,492-793,794-1234,1236-1769,1770-1895,1954-2110",
        "src/main/scala/xiangshan/mem/pipeline/Bundles.scala:29-237",
        "src/main/scala/xiangshan/mem/pipeline/package.scala:24-55",
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueueReplay.scala:31-59",
        "src/main/scala/xiangshan/mem/MemBlock.scala:885-938",
    ]


def test_stage5_required_path_coverage_is_complete() -> None:
    suite = CoverageSuite.load(XIANGSHAN / "coverage" / "stage5.yaml")
    report = run_coverage(suite, backend="z3")
    assert report.required_complete
    assert [item.status for item in report.results] == [CoverageStatus.COVERED] * 11
