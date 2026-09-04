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
STORE_TRACES = XIANGSHAN / "traces" / "store"
VSQ_TRACES = XIANGSHAN / "traces" / "store_queue"
STORE_COMPOSITION = XIANGSHAN / "composition" / "scalar_store.yaml"
VSQ_COMPOSITION = XIANGSHAN / "composition" / "virtual_store_queue.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def store_result(case: str):
    source = Trace.load(STORE_TRACES / f"{case}.yaml")
    composed = compose_modules(catalog(), CompositionSpec.load(STORE_COMPOSITION), source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


@lru_cache(maxsize=None)
def vsq_result(case: str):
    source = Trace.load(VSQ_TRACES / f"{case}.yaml")
    composed = compose_modules(catalog(), CompositionSpec.load(VSQ_COMPOSITION), source)
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


def test_independent_sta_std_payloads_pair_before_store_writeback() -> None:
    trace = feasible(store_result("cacheable_success"))
    s0 = event(trace, "Store.StageAdvance", stage="s0")
    std = event(trace, "Store.StageAdvance", stage="std")
    s1 = event(trace, "Store.StageAdvance", stage="s1")
    s2 = event(trace, "Store.StageAdvance", stage="s2")
    s3 = event(trace, "Store.StageAdvance", stage="s3")
    address = event(trace, "Store.AddressReady", op_id="S0")
    data = event(trace, "Store.DataReady", op_id="S0")
    writeback = event(trace, "Core.MemoryWriteback", op_id="S0")

    assert s0.cycle < s1.cycle < s2.cycle < s3.cycle < writeback.cycle
    assert std.cycle < data.cycle < writeback.cycle
    assert address.cycle < writeback.cycle
    assert address.fields["address"] == 8200
    assert address.fields["sq_idx"] == data.fields["sq_idx"] == 0
    assert data.fields["value"] == writeback.fields["value"] == 42
    assert not [x for x in trace.events_of_type("Store.StageAdvance") if x.fields.get("stage") == "s4"]


def test_store_replay_and_fault_do_not_complete() -> None:
    replay = feasible(store_result("tlb_replay"))
    decision = event(replay, "Store.ReplayDecision", replay_source="tlb")
    assert decision.fields["cause"] == "tlb_miss"
    assert not list(replay.events_of_type("Store.AddressReady"))
    assert not list(replay.events_of_type("Core.MemoryWriteback"))

    faulted = feasible(store_result("translation_fault"))
    decision = event(faulted, "Store.FaultDecision", fault_source="translation")
    fault = event(faulted, "Core.MemoryFault", op_id="SFAULT")
    assert decision.fields["cause"] == fault.fields["cause"] == "store_page_fault"
    assert not list(faulted.events_of_type("Core.MemoryWriteback"))


def test_redirect_kills_live_store_pipeline() -> None:
    trace = feasible(store_result("redirect_kills"))
    redirect = event(trace, "Core.Redirect")
    killed = event(trace, "Store.ReplayDecision", path="killed")
    assert redirect.cycle < killed.cycle
    assert killed.fields["cause"] == "branch_mispredict"
    assert not list(trace.events_of_type("Core.MemoryWriteback"))


@pytest.mark.parametrize(
    "case",
    ["wrong_address", "wrong_data", "writeback_before_pair", "redirect_late_writeback"],
)
def test_invalid_store_outputs_are_unsat(case: str) -> None:
    assert store_result(case).status is CompletionStatus.INFEASIBLE


def test_vsq_normal_and_redirect_lifetimes() -> None:
    normal = feasible(vsq_result("normal_retire"))
    allocate = event(normal, "SQ.Allocate", op_id="SQ0")
    commit = event(normal, "Core.MemoryCommit", op_id="SQ0")
    retire = event(normal, "SQ.Retire", op_id="SQ0")
    assert allocate.cycle < commit.cycle < retire.cycle

    redirected = feasible(vsq_result("redirect_reclaims"))
    redirect = event(redirected, "Core.Redirect")
    recover = event(redirected, "SQ.RedirectRecover", op_id="SQKILL")
    assert recover.cycle == redirect.cycle + 2
    assert recover.fields["cause"] == "branch_mispredict"
    assert not list(redirected.events_of_type("SQ.Retire"))


def test_vsq_retires_in_order_and_rejects_post_redirect_commit() -> None:
    trace = feasible(vsq_result("in_order_retire"))
    head = event(trace, "SQ.Retire", op_id="SQHEAD")
    tail = event(trace, "SQ.Retire", op_id="SQTAIL")
    assert head.cycle < tail.cycle
    assert vsq_result("out_of_order_retire").status is CompletionStatus.INFEASIBLE
    assert vsq_result("post_redirect_commit").status is CompletionStatus.INFEASIBLE


def test_pipeline_composes_with_vsq_and_store_dtlb() -> None:
    source = Trace.load(STORE_TRACES / "integrated_queue_retire.yaml")
    spec = CompositionSpec.load(XIANGSHAN / "composition" / "scalar_store_queue.yaml")
    composed = compose_modules(catalog(), spec, source)
    trace = feasible(complete_trace(catalog(), source, composed.completion, backend="z3"))
    writeback = event(trace, "Core.MemoryWriteback", op_id="SQINT")
    retire = event(trace, "SQ.Retire", op_id="SQINT")
    assert writeback.cycle < retire.cycle

    source = Trace.load(STORE_TRACES / "integrated_dtlb_hit.yaml")
    spec = CompositionSpec.load(XIANGSHAN / "composition" / "store_translation.yaml")
    composed = compose_modules(catalog(), spec, source)
    trace = feasible(complete_trace(catalog(), source, composed.completion, backend="z3"))
    request = event(trace, "MMU.TranslateRequest", op_id="SINT")
    hit = event(trace, "MMU.L1TLBHit", op_id="SINT")
    response = event(trace, "MMU.TranslateResponse", op_id="SINT")
    address = event(trace, "Store.AddressReady", op_id="SINT")
    assert request.cycle < hit.cycle < response.cycle < address.cycle
    assert address.fields["address"] == 36864


def test_stage8_interface_inventories_and_private_encapsulation() -> None:
    cases = [
        (
            STORE_COMPOSITION,
            STORE_TRACES / "wrong_address.yaml",
            XIANGSHAN / "hierarchy" / "scalar_store_interfaces.yaml",
        ),
        (
            VSQ_COMPOSITION,
            VSQ_TRACES / "in_order_retire.yaml",
            XIANGSHAN / "hierarchy" / "virtual_store_queue_interfaces.yaml",
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
            "modules": [x.to_dict() for x in build_interface_contracts(composed)],
        }
        assert load_data(inventory_path) == expected

    for directory in (STORE_TRACES, VSQ_TRACES):
        for path in directory.glob("*.yaml"):
            for observed in Trace.load(path).events:
                assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage8_source_metadata_is_pinned() -> None:
    source = Trace.load(STORE_TRACES / "cacheable_success.yaml")
    pipeline = compose_modules(
        catalog(), CompositionSpec.load(STORE_COMPOSITION), source
    ).modules[0].spec
    assert pipeline.metadata["source_commit"] == "50cdcfc2c45d0631591310435835c0180c105489"
    assert pipeline.metadata["source_files"] == [
        "src/main/scala/xiangshan/mem/pipeline/NewStoreUnit.scala:37-247,248-537,538-700,701-827,844-975",
        "src/main/scala/xiangshan/mem/pipeline/StdExeUnit.scala:28-83",
        "src/main/scala/xiangshan/mem/pipeline/Bundles.scala:304-318",
        "src/main/scala/xiangshan/mem/pipeline/package.scala:153-190",
        "src/main/scala/xiangshan/mem/MemBlock.scala:957-977",
    ]

    source = Trace.load(VSQ_TRACES / "normal_retire.yaml")
    vsq = compose_modules(
        catalog(), CompositionSpec.load(VSQ_COMPOSITION), source
    ).modules[0].spec
    assert vsq.metadata["parameters"]["virtual_store_queue_size"] == 128
    assert vsq.metadata["source_files"][0] == (
        "src/main/scala/xiangshan/mem/lsqueue/VirtualStoreQueue.scala:30-206,238-389,413-417"
    )


def test_stage8_required_path_coverage_is_complete() -> None:
    report = run_coverage(CoverageSuite.load(XIANGSHAN / "coverage" / "stage8.yaml"), backend="z3")
    assert report.required_complete
    assert [x.status for x in report.results] == [CoverageStatus.COVERED] * 14
