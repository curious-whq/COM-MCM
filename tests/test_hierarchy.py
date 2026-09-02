from copy import deepcopy
from pathlib import Path

import pytest

from umcm.errors import GraphError
from umcm.graph import GraphModelSpec, MemoryModelStatus, check_trace_memory_model, iter_execution_graphs
from umcm.hierarchy import (
    AbstractionSpec,
    abstract_trace,
    check_memory_model_preservation,
    check_refinement,
)
from umcm.ir import EventCatalog, EventInstance, Trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests/regressions/boom/legacy_v0_11"


def _catalog() -> EventCatalog:
    return EventCatalog.load(EXAMPLE / "event_types.yaml")


def _abstraction() -> AbstractionSpec:
    return AbstractionSpec.load(EXAMPLE / "hierarchy_abstraction.yaml")


def _graph_model() -> GraphModelSpec:
    return GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml")


def test_buggy_trace_is_compressed_with_provenance() -> None:
    concrete = Trace.load(EXAMPLE / "stage7_buggy_completed.yaml")
    result = abstract_trace(concrete, _catalog(), _abstraction())

    assert len(concrete.events) == 36
    assert len(result.trace.events) == 11
    assert len(result.certificate.hidden_event_ids) == 30
    assert len(result.certificate.summaries) == 5

    rf_l1 = result.trace.get("rf_InitX_L1_l1_hit")
    assert rf_l1.fields == {
        "read_op_id": "L1",
        "write_op_id": "InitX",
        "address": "x",
        "value": 0,
        "path": "l1_hit",
    }
    rf_l0 = result.trace.get("rf_W1_L0_mshr")
    assert rf_l0.fields["write_op_id"] == "W1"
    assert rf_l0.fields["read_op_id"] == "L0"
    assert rf_l0.fields["path"] == "mshr_refill"

    evidence = rf_l0.annotations["abstraction"]
    assert evidence["rule"] == "l0_mshr_read_from"
    assert "l0_mshr_grant_data" in evidence["source_event_ids"]
    assert "l0_long_latency_response" in evidence["source_event_ids"]


def test_abstraction_preserves_buggy_execution_graph_and_violation() -> None:
    concrete = Trace.load(EXAMPLE / "stage7_buggy_completed.yaml")
    abstracted = abstract_trace(concrete, _catalog(), _abstraction()).trace
    preservation = check_memory_model_preservation(
        concrete,
        abstracted,
        _graph_model(),
    )

    assert preservation.preserved
    assert preservation.concrete.status is MemoryModelStatus.FORBIDDEN
    assert preservation.abstract.status is MemoryModelStatus.FORBIDDEN
    assert preservation.concrete_candidate_signatures == preservation.abstract_candidate_signatures

    graph = check_trace_memory_model(abstracted, _graph_model()).representative.graph
    assert graph.relation("rf").edges == frozenset(
        {("InitX", "L1"), ("W1", "L0")}
    )
    assert graph.relation("co").edges == frozenset({("InitX", "W1")})


def test_fixed_recovery_abstraction_preserves_allowed_result() -> None:
    concrete = Trace.load(EXAMPLE / "stage7_fixed_recovery_completed.yaml")
    result = abstract_trace(concrete, _catalog(), _abstraction())
    preservation = check_memory_model_preservation(
        concrete,
        result.trace,
        _graph_model(),
    )

    assert preservation.preserved
    assert preservation.concrete.status is MemoryModelStatus.ALLOWED
    assert preservation.abstract.status is MemoryModelStatus.ALLOWED
    assert result.trace.get("ll_L0_L1_squash").fields["outcome"] == "squash"
    assert "commit_l1" not in {event.id for event in result.trace.events}


def test_refinement_certificate_detects_tampered_summary() -> None:
    concrete = Trace.load(EXAMPLE / "stage7_buggy_completed.yaml")
    abstracted = abstract_trace(concrete, _catalog(), _abstraction()).trace
    assert check_refinement(concrete, abstracted, _catalog(), _abstraction()).valid

    tampered = Trace.from_dict(deepcopy(abstracted.to_dict()))
    tampered.get("rf_W1_L0_mshr").fields["write_op_id"] = "InitX"
    checked = check_refinement(concrete, tampered, _catalog(), _abstraction())
    assert not checked.valid
    assert checked.changed_event_ids == ("rf_W1_L0_mshr",)


def test_abstraction_spec_roundtrip(tmp_path: Path) -> None:
    spec = _abstraction()
    output = tmp_path / "abstraction.json"
    spec.dump(output)
    assert AbstractionSpec.load(output).to_dict() == spec.to_dict()


def _ambiguous_co_trace() -> Trace:
    trace = Trace.load(EXAMPLE / "stage7_same_write_trace.yaml")
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
    return trace


def test_co_hint_filters_ambiguous_coherence_orders() -> None:
    trace = _ambiguous_co_trace()
    assert len(list(iter_execution_graphs(trace, _graph_model()))) == 8
    trace.events.append(
        EventInstance(
            id="co_w0_w1",
            event_type="Hierarchy.CoherenceOrderEvidence",
            fields={
                "before_write_id": "W0",
                "after_write_id": "W1",
                "address": "x",
                "path": "test",
            },
        )
    )
    graphs = list(iter_execution_graphs(trace, _graph_model()))
    assert len(graphs) == 4
    assert all(graph.relation("co").contains("W0", "W1") for graph in graphs)


def test_conflicting_co_hints_are_rejected() -> None:
    trace = _ambiguous_co_trace()
    for before, after in (("W0", "W1"), ("W1", "W0")):
        trace.events.append(
            EventInstance(
                id=f"co_{before}_{after}",
                event_type="Hierarchy.CoherenceOrderEvidence",
                fields={
                    "before_write_id": before,
                    "after_write_id": after,
                    "address": "x",
                    "path": "test",
                },
            )
        )
    with pytest.raises(GraphError, match="co hints.*inconsistent"):
        list(iter_execution_graphs(trace, _graph_model()))
