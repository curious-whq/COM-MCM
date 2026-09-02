from dataclasses import replace
from pathlib import Path

import pytest

from umcm.errors import GraphError
from umcm.graph.builder import iter_execution_graphs
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.execution import ExecutionGraph
from umcm.graph.model import GraphModelSpec
from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests/regressions/boom/legacy_v0_11"


def _completed_buggy_trace() -> Trace:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage6_trace.yaml")
    completion = CompletionSpec.load(
        EXAMPLE / "load_load_buggy_mshr_completion.yaml"
    )
    result = complete_trace(catalog, trace, completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    return result.completed_trace


def _model() -> GraphModelSpec:
    return GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml")


def test_buggy_trace_projects_expected_relations_and_violation() -> None:
    trace = _completed_buggy_trace()
    checked = check_trace_memory_model(trace, _model())

    assert checked.status is MemoryModelStatus.FORBIDDEN
    assert len(checked.candidates) == 1
    graph = checked.representative.graph
    assert set(graph.operations) == {"InitX", "W1", "L0", "L1"}
    assert graph.relation("rf").edges == frozenset(
        {("InitX", "L1"), ("W1", "L0")}
    )
    assert graph.relation("co").edges == frozenset({("InitX", "W1")})
    assert graph.relation("fr").edges == frozenset({("L1", "W1")})
    assert graph.relation("po").edges == frozenset({("L0", "L1")})
    assert graph.relation("ppo").edges == frozenset({("L0", "L1")})
    assert graph.relation("hb").edges == frozenset(
        {("InitX", "L1"), ("W1", "L0"), ("L0", "L1")}
    )

    axiom = checked.representative.axioms[0]
    assert axiom.status.value == "violated"
    assert {(edge.source, edge.relation, edge.target) for edge in axiom.cycle} == {
        ("L1", "fr", "W1"),
        ("W1", "rfe", "L0"),
        ("L0", "ppo", "L1"),
    }


def test_allowed_control_has_graph_candidate_without_cycle() -> None:
    trace = Trace.load(EXAMPLE / "stage7_allowed_trace.yaml")
    checked = check_trace_memory_model(trace, _model())
    assert checked.status is MemoryModelStatus.ALLOWED
    graph = checked.representative.graph
    assert graph.relation("rf").edges == frozenset(
        {("InitX", "L0"), ("W1", "L1")}
    )
    assert graph.relation("ppo").edges == frozenset({("L0", "L1")})


def test_same_write_control_does_not_generate_load_load_ppo() -> None:
    trace = Trace.load(EXAMPLE / "stage7_same_write_trace.yaml")
    checked = check_trace_memory_model(trace, _model())
    assert checked.status is MemoryModelStatus.ALLOWED
    assert checked.representative.graph.relation("ppo").edges == frozenset()


def test_execution_graph_roundtrip(tmp_path: Path) -> None:
    trace = _completed_buggy_trace()
    graph = next(iter_execution_graphs(trace, _model()))
    output = tmp_path / "graph.json"
    graph.dump(output)
    assert ExecutionGraph.load(output).to_dict() == graph.to_dict()


def test_graph_model_roundtrip(tmp_path: Path) -> None:
    model = _model()
    output = tmp_path / "model.json"
    model.dump(output)
    assert GraphModelSpec.load(output).to_dict() == model.to_dict()


def test_mshr_rf_hint_must_match_hint_value() -> None:
    trace = _completed_buggy_trace()
    grant = trace.get("l0_mshr_grant_data")
    grant.fields["value"] = 0
    with pytest.raises(GraphError, match="inconsistent value"):
        list(iter_execution_graphs(trace, _model()))


def test_candidate_enumeration_handles_ambiguous_equal_value_writes() -> None:
    trace = Trace.load(EXAMPLE / "stage7_same_write_trace.yaml")
    # Add another write of zero. Both reads now have two possible rf sources.
    from umcm.ir.event import EventInstance

    trace.events.append(
        EventInstance(
            id="store_w0",
            event_type="Arch.Store",
            fields={
                "op_id": "W0",
                "hart": 2,
                "program_index": 0,
                "address": "x",
                "value": 0,
            },
        )
    )
    graphs = list(iter_execution_graphs(trace, _model()))
    # 2 choices for each read and 2 coherence orders for W0/W1.
    assert len(graphs) == 8


def test_fixed_recovery_hides_squashed_uncommitted_load() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage6_recovery_trace.yaml")
    completion = CompletionSpec.load(
        EXAMPLE / "load_load_fixed_mshr_completion.yaml"
    )
    result = complete_trace(catalog, trace, completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None

    checked = check_trace_memory_model(result.completed_trace, _model())
    assert checked.status is MemoryModelStatus.ALLOWED
    graph = checked.representative.graph
    assert set(graph.operations) == {"InitX", "W1", "L0"}
    assert "L1" not in graph.operations
    assert graph.relation("rf").edges == frozenset({("W1", "L0")})
    assert graph.relation("ppo").edges == frozenset()
