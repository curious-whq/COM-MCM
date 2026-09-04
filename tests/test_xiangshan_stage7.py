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
REPLAY_TRACES = XIANGSHAN / "traces" / "replay"
MDP_TRACES = XIANGSHAN / "traces" / "mdp"
REPLAY_COMPOSITION = XIANGSHAN / "composition" / "load_replay.yaml"
MDP_COMPOSITION = XIANGSHAN / "composition" / "memory_dependency_predictor.yaml"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


@lru_cache(maxsize=None)
def replay_result(case: str):
    source = Trace.load(REPLAY_TRACES / f"{case}.yaml")
    composed = compose_modules(catalog(), CompositionSpec.load(REPLAY_COMPOSITION), source)
    return complete_trace(catalog(), source, composed.completion, backend="z3")


@lru_cache(maxsize=None)
def mdp_result(case: str):
    source = Trace.load(MDP_TRACES / f"{case}.yaml")
    composed = compose_modules(catalog(), CompositionSpec.load(MDP_COMPOSITION), source)
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


def test_immediate_and_blocked_replay_paths_preserve_cause_and_priority() -> None:
    immediate = feasible(replay_result("immediate_nack"))
    enqueue = event(immediate, "LQ.ReplayEnqueue")
    issue = event(immediate, "Load.ReplayIssue")
    assert enqueue.fields["blocking"] is False
    assert issue.fields["cause"] == "mshr_nack"
    assert issue.fields["priority"] == "low"
    assert not list(immediate.events_of_type("Load.ReplayWakeup"))

    blocked = feasible(replay_result("blocked_refill"))
    enqueue = event(blocked, "LQ.ReplayEnqueue")
    wakeup = event(blocked, "Load.ReplayWakeup")
    issue = event(blocked, "Load.ReplayIssue")
    assert enqueue.fields["blocking"] is True
    assert enqueue.cycle < wakeup.cycle < issue.cycle
    assert issue.fields["cause"] == "dcache_miss"
    assert issue.fields["priority"] == "high"


def test_replay_feedback_frees_or_reuses_the_same_entry() -> None:
    completed = feasible(replay_result("replay_success"))
    issue = event(completed, "Load.ReplayIssue", op_id="RDONE")
    deallocate = event(completed, "LQ.ReplayDeallocate", path="feedback_complete")
    assert issue.cycle < deallocate.cycle

    repeated = feasible(replay_result("replay_requeues"))
    issue = event(repeated, "Load.ReplayIssue", op_id="RAGAIN")
    requeue = event(repeated, "LQ.ReplayRequeue", op_id="RAGAIN")
    assert issue.cycle < requeue.cycle
    assert requeue.fields["cause"] == "wpu_fail"
    assert not list(repeated.events_of_type("LQ.ReplayDeallocate"))


def test_redirect_cancels_blocked_replay_and_wrong_wakeup_cannot_issue() -> None:
    redirected = feasible(replay_result("redirect_cancels"))
    deallocate = event(redirected, "LQ.ReplayDeallocate", path="redirect")
    assert deallocate.fields["cause"] == "branch_mispredict"
    assert not list(redirected.events_of_type("Load.ReplayIssue"))
    assert replay_result("wrong_wakeup_issue").status is CompletionStatus.INFEASIBLE
    assert replay_result("duplicate_replay_issue").status is CompletionStatus.INFEASIBLE


def test_stage5_nack_feeds_stage7_replay_queue() -> None:
    source = Trace.load(XIANGSHAN / "traces" / "load" / "l1_nack.yaml")
    spec = CompositionSpec.load(XIANGSHAN / "composition" / "scalar_load_replay.yaml")
    composed = compose_modules(catalog(), spec, source)
    result = complete_trace(catalog(), source, composed.completion, backend="z3")
    trace = feasible(result)
    update = event(trace, "Load.PipelineUpdate", op_id="LNACK")
    enqueue = event(trace, "LQ.ReplayEnqueue", op_id="LNACK")
    issue = event(trace, "Load.ReplayIssue", op_id="LNACK")
    assert update.cycle < enqueue.cycle < issue.cycle
    assert issue.fields["attempt"] == 1


@pytest.mark.parametrize(
    ("case", "path", "ssid", "strict"),
    [
        ("trained_wait", "allocate", 3, False),
        ("attach_store", "attach_store", 5, False),
        ("attach_load", "attach_load", 6, False),
        ("merge_sets", "merge", 4, False),
        ("strict_training", "strict", 12, True),
    ],
)
def test_all_ssit_training_outcomes(case: str, path: str, ssid: int, strict: bool) -> None:
    trace = feasible(mdp_result(case))
    trained = event(trace, "MDP.SSITTrain", path=path)
    assert trained.fields["ssid"] == ssid
    assert trained.fields["strict"] is strict


def test_lfst_prediction_delays_load_but_carries_no_value() -> None:
    trace = feasible(mdp_result("trained_wait"))
    prediction = event(trace, "MDP.WaitPrediction", op_id="L0")
    store_issue = event(trace, "Core.MemoryIssue", op_id="S0")
    load_issue = event(trace, "Core.MemoryIssue", op_id="L0")
    release = event(trace, "MDP.LFSTRelease", path="store_issue")
    assert prediction.cycle < store_issue.cycle < load_issue.cycle
    assert release.cycle > store_issue.cycle
    assert prediction.fields["wait_for_rob_idx"] == 10
    assert "value" not in prediction.fields
    assert mdp_result("wrong_issue_order").status is CompletionStatus.INFEASIBLE


def test_untrained_lookup_and_redirected_store_do_not_predict() -> None:
    untrained = feasible(mdp_result("untrained_lookup"))
    assert not list(untrained.events_of_type("MDP.SSITRead"))
    assert not list(untrained.events_of_type("MDP.WaitPrediction"))

    redirected = feasible(mdp_result("redirect_clears_store"))
    event(redirected, "MDP.LFSTRelease", path="redirect")
    assert not list(redirected.events_of_type("MDP.WaitPrediction"))


def test_stage7_interface_inventories_and_private_encapsulation() -> None:
    cases = [
        (
            REPLAY_COMPOSITION,
            REPLAY_TRACES / "blocked_refill.yaml",
            XIANGSHAN / "hierarchy" / "load_replay_interfaces.yaml",
        ),
        (
            MDP_COMPOSITION,
            MDP_TRACES / "trained_wait.yaml",
            XIANGSHAN / "hierarchy" / "memory_dependency_predictor_interfaces.yaml",
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

    for directory in (REPLAY_TRACES, MDP_TRACES):
        for path in directory.glob("*.yaml"):
            for observed in Trace.load(path).events:
                assert catalog().resolve(observed.event_type).visibility is not Visibility.INTERNAL


def test_stage7_source_metadata_is_pinned() -> None:
    replay_source = Trace.load(REPLAY_TRACES / "immediate_nack.yaml")
    replay = compose_modules(
        catalog(), CompositionSpec.load(REPLAY_COMPOSITION), replay_source
    ).modules[0].spec
    assert replay.metadata["source_commit"] == "50cdcfc2c45d0631591310435835c0180c105489"
    assert replay.metadata["source_files"] == [
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueueReplay.scala:31-72,197-240,242-318,337-463,493-725,742-890",
        "src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala:1029-1088,1494-1549",
        "src/main/scala/xiangshan/mem/lsqueue/LoadQueue.scala:227-317",
    ]

    mdp_source = Trace.load(MDP_TRACES / "trained_wait.yaml")
    mdp = compose_modules(
        catalog(), CompositionSpec.load(MDP_COMPOSITION), mdp_source
    ).modules[0].spec
    assert mdp.metadata["source_files"][0:3] == [
        "src/main/scala/xiangshan/mem/mdp/StoreSet.scala:39-420,423-560",
        "src/main/scala/xiangshan/mem/mdp/WaitTable.scala:1-71",
        "src/main/scala/xiangshan/backend/ctrlblock/MemCtrl.scala:20-43",
    ]


def test_stage7_required_path_coverage_is_complete() -> None:
    report = run_coverage(CoverageSuite.load(XIANGSHAN / "coverage" / "stage7.yaml"), backend="z3")
    assert report.required_complete
    assert [x.status for x in report.results] == [CoverageStatus.COVERED] * 15
