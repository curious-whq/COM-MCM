from __future__ import annotations

from pathlib import Path

import pytest

from umcm.errors import GraphError
from umcm.graph.checker import check_rvwmo_execution_graph
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.execution import ExecutionGraph, MemoryOperation, OperationKind
from umcm.graph.model import GraphModelSpec, ProjectionSpec, RelationHintSpec
from umcm.graph.relation import Relation
from umcm.ir.event import EventInstance
from umcm.ir.trace import Trace


ROOT = Path(__file__).resolve().parents[1]


def init(op_id: str, address: str, value: int = 0) -> MemoryOperation:
    return MemoryOperation(op_id, OperationKind.INIT_WRITE, address, value)


def read(
    op_id: str,
    hart: int,
    index: int,
    address: str,
    value: int,
    **metadata,
) -> MemoryOperation:
    return MemoryOperation(
        op_id,
        OperationKind.READ,
        address,
        value,
        hart=hart,
        program_index=index,
        source_event_id=f"event_{op_id}",
        commit_event_id=f"commit_{op_id}",
        metadata=metadata,
    )


def write(
    op_id: str,
    hart: int,
    index: int,
    address: str,
    value: int,
    **metadata,
) -> MemoryOperation:
    return MemoryOperation(
        op_id,
        OperationKind.WRITE,
        address,
        value,
        hart=hart,
        program_index=index,
        source_event_id=f"event_{op_id}",
        metadata=metadata,
    )


def amo(
    op_id: str,
    hart: int,
    index: int,
    address: str,
    read_value: int,
    write_value: int,
    **metadata,
) -> MemoryOperation:
    return MemoryOperation(
        op_id,
        OperationKind.AMO,
        address,
        read_value,
        write_value=write_value,
        hart=hart,
        program_index=index,
        source_event_id=f"event_{op_id}",
        commit_event_id=f"commit_{op_id}",
        metadata=metadata,
    )


def graph(
    operations: list[MemoryOperation],
    *,
    rf: list[tuple[str, str]],
    co: list[tuple[str, str]],
    **relations: list[tuple[str, str]],
) -> ExecutionGraph:
    relation_map = {
        "rf": Relation.from_edges("rf", rf),
        "co": Relation.from_edges("co", co),
    }
    relation_map.update(
        {name: Relation.from_edges(name, edges) for name, edges in relations.items()}
    )
    return ExecutionGraph(
        operations={operation.id: operation for operation in operations},
        relations=relation_map,
    )


def violated_names(result) -> set[str]:
    return {item.axiom for item in result.axioms if item.status.value == "violated"}


def test_load_load_different_write_cycle_is_forbidden() -> None:
    candidate = graph(
        [init("I", "x"), write("W", 1, 0, "x", 1), read("R0", 0, 0, "x", 1), read("R1", 0, 1, "x", 0)],
        rf=[("W", "R0"), ("I", "R1")],
        co=[("I", "W")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert not result.allowed
    assert result.graph.relation("ppo_rule2").edges == frozenset({("R0", "R1")})
    assert "rvwmo_global_memory_order" in violated_names(result)


def test_store_buffering_outcome_is_allowed() -> None:
    candidate = graph(
        [
            init("IX", "x"), init("IY", "y"),
            write("WX", 0, 0, "x", 1), read("RY", 0, 1, "y", 0),
            write("WY", 1, 0, "y", 1), read("RX", 1, 1, "x", 0),
        ],
        rf=[("IY", "RY"), ("IX", "RX")],
        co=[("IX", "WX"), ("IY", "WY")],
    )
    assert check_rvwmo_execution_graph(candidate).allowed


def test_overlapping_load_store_and_store_store_use_rule1() -> None:
    candidate = graph(
        [init("I", "x"), read("R", 0, 0, "x", 0), write("W0", 0, 1, "x", 1), write("W1", 0, 2, "x", 2)],
        rf=[("I", "R")],
        co=[("I", "W0"), ("I", "W1"), ("W0", "W1")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.allowed
    assert result.graph.relation("ppo_rule1").edges == frozenset(
        {("R", "W0"), ("R", "W1"), ("W0", "W1")}
    )


def test_fence_edge_uses_rule4() -> None:
    candidate = graph(
        [init("IX", "x"), init("IY", "y"), write("W", 0, 0, "x", 1), read("R", 0, 1, "y", 0)],
        rf=[("IY", "R")],
        co=[("IX", "W")],
        fence=[("W", "R")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.graph.relation("ppo_rule4").edges == frozenset({("W", "R")})


def test_acquire_release_and_rcsc_use_rules5_to7() -> None:
    candidate = graph(
        [
            init("IX", "x"), init("IY", "y"),
            read("A", 0, 0, "x", 0, acquire=True, rcsc=True),
            write("B", 0, 1, "y", 1, release=True, rcsc=True),
        ],
        rf=[("IX", "A")],
        co=[("IY", "B")],
    )
    result = check_rvwmo_execution_graph(candidate)
    for rule in (5, 6, 7):
        assert result.graph.relation(f"ppo_rule{rule}").edges == frozenset({("A", "B")})


def test_lr_sc_pair_uses_rule8() -> None:
    candidate = graph(
        [init("I", "x"), read("LR", 0, 0, "x", 0, atomic_kind="lr"), write("SC", 0, 1, "x", 1, atomic_kind="sc")],
        rf=[("I", "LR")],
        co=[("I", "SC")],
        pair=[("LR", "SC")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.allowed
    assert result.graph.relation("ppo_rule8").edges == frozenset({("LR", "SC")})


def test_address_and_data_dependencies_use_rules9_and10() -> None:
    candidate = graph(
        [init("IX", "x"), init("IY", "y"), read("R", 0, 0, "x", 0), write("W", 0, 1, "y", 1)],
        rf=[("IX", "R")],
        co=[("IY", "W")],
        addr=[("R", "W")],
        data=[("R", "W")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.graph.relation("ppo_rule9").edges == frozenset({("R", "W")})
    assert result.graph.relation("ppo_rule10").edges == frozenset({("R", "W")})


def test_control_dependency_only_orders_a_target_store_by_rule11() -> None:
    candidate = graph(
        [
            init("IX", "x"), init("IY", "y"), init("IZ", "z"),
            read("R0", 0, 0, "x", 0), read("R1", 0, 1, "y", 0),
            write("W", 0, 2, "z", 1),
        ],
        rf=[("IX", "R0"), ("IY", "R1")],
        co=[("IZ", "W")],
        ctrl=[("R0", "R1"), ("R0", "W")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.graph.relation("ppo_rule11").edges == frozenset({("R0", "W")})


def test_pipeline_store_to_load_dependency_uses_rule12() -> None:
    candidate = graph(
        [
            init("IX", "x"), init("IY", "y"),
            read("R0", 0, 0, "x", 0), write("W", 0, 1, "y", 1),
            read("R1", 0, 2, "y", 1),
        ],
        rf=[("IX", "R0"), ("W", "R1")],
        co=[("IY", "W")],
        data=[("R0", "W")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.graph.relation("ppo_rule12").edges == frozenset({("R0", "R1")})


def test_pipeline_address_chain_to_store_uses_rule13() -> None:
    candidate = graph(
        [
            init("IX", "x"), init("IY", "y"), init("IZ", "z"),
            read("R0", 0, 0, "x", 0), read("M", 0, 1, "y", 0),
            write("W", 0, 2, "z", 1),
        ],
        rf=[("IX", "R0"), ("IY", "M")],
        co=[("IZ", "W")],
        addr=[("R0", "M")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.graph.relation("ppo_rule13").edges == frozenset({("R0", "W")})


def test_amo_write_followed_by_read_uses_rule3() -> None:
    candidate = graph(
        [init("I", "x"), amo("A", 0, 0, "x", 0, 1), read("R", 0, 1, "x", 1)],
        rf=[("I", "A"), ("A", "R")],
        co=[("I", "A")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert result.allowed
    assert result.graph.relation("ppo_rule3").edges == frozenset({("A", "R")})


def test_amo_must_read_immediate_co_predecessor() -> None:
    candidate = graph(
        [init("I", "x"), write("W", 1, 0, "x", 2), amo("A", 0, 0, "x", 0, 1)],
        rf=[("I", "A")],
        co=[("I", "W"), ("I", "A"), ("W", "A")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert not result.allowed
    assert "rvwmo_amo_atomicity" in violated_names(result)


def test_lr_sc_rejects_intervening_external_store() -> None:
    candidate = graph(
        [
            init("I", "x"), read("LR", 0, 0, "x", 0, atomic_kind="lr"),
            write("SC", 0, 1, "x", 1, atomic_kind="sc"), write("W", 1, 0, "x", 2),
        ],
        rf=[("I", "LR")],
        co=[("I", "W"), ("I", "SC"), ("W", "SC")],
        pair=[("LR", "SC")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert not result.allowed
    assert "rvwmo_lr_sc_atomicity" in violated_names(result)


def test_successful_sc_requires_one_lr_pair() -> None:
    candidate = graph(
        [init("I", "x"), write("SC", 0, 0, "x", 1, atomic_kind="sc")],
        rf=[],
        co=[("I", "SC")],
    )
    result = check_rvwmo_execution_graph(candidate)
    assert not result.allowed
    assert "rvwmo_lr_sc_atomicity" in violated_names(result)


def test_lr_sc_allows_intervening_same_hart_store() -> None:
    candidate = graph(
        [
            init("I", "x"), read("LR", 0, 0, "x", 0, atomic_kind="lr"),
            write("W", 0, 1, "x", 2), write("SC", 0, 2, "x", 1, atomic_kind="sc"),
        ],
        rf=[("I", "LR")],
        co=[("I", "W"), ("I", "SC"), ("W", "SC")],
        pair=[("LR", "SC")],
    )
    assert check_rvwmo_execution_graph(candidate).allowed


def test_load_value_rejects_value_mismatched_rf() -> None:
    candidate = graph(
        [init("I", "x", 0), read("R", 0, 0, "x", 1)],
        rf=[("I", "R")],
        co=[],
    )
    with pytest.raises(GraphError, match="unequal values"):
        check_rvwmo_execution_graph(candidate)


def test_partial_mixed_size_overlap_is_rejected_explicitly() -> None:
    candidate = graph(
        [
            MemoryOperation("I", OperationKind.INIT_WRITE, 0, 0, metadata={"size": 8}),
            write("W", 0, 0, 4, 1, size=8),
        ],
        rf=[],
        co=[],
    )
    with pytest.raises(GraphError, match="mixed-size"):
        check_rvwmo_execution_graph(candidate)


def test_trace_projection_carries_metadata_and_relation_hints() -> None:
    model = GraphModelSpec(
        model="rvwmo-projection-test",
        builtin_model="rvwmo",
        projection=ProjectionSpec(
            init_write_event="Arch.InitWrite",
            load_event="Arch.Load",
            store_event="Arch.Store",
            load_commit_event="Arch.CommitRead",
            metadata_fields={"acquire": "aq"},
            relation_hints=(
                RelationHintSpec("addr", "Arch.AddressDependency"),
            ),
        ),
    )
    trace = Trace(
        partial=False,
        events=[
            EventInstance("ix", "Arch.InitWrite", {"op_id": "IX", "address": "x", "value": 0}),
            EventInstance("iy", "Arch.InitWrite", {"op_id": "IY", "address": "y", "value": 0}),
            EventInstance("r", "Arch.Load", {"op_id": "R", "hart": 0, "program_index": 0, "address": "x", "aq": True}),
            EventInstance("cr", "Arch.CommitRead", {"op_id": "R", "value": 0}),
            EventInstance("w", "Arch.Store", {"op_id": "W", "hart": 0, "program_index": 1, "address": "y", "value": 1}),
            EventInstance("dep", "Arch.AddressDependency", {"source_op_id": "R", "target_op_id": "W"}),
        ],
    )
    result = check_trace_memory_model(trace, model)
    assert result.status is MemoryModelStatus.ALLOWED
    checked = result.representative
    assert checked.graph.operations["R"].metadata["acquire"] is True
    assert checked.graph.relation("addr").edges == frozenset({("R", "W")})
    assert checked.graph.relation("ppo_rule9").edges == frozenset({("R", "W")})


def test_builtin_rvwmo_preserves_boom_bug_and_fixed_regressions() -> None:
    model = GraphModelSpec.load(ROOT / "examples/boom/axioms/rvwmo.yaml")
    regression = ROOT / "tests/regressions/boom/v0_15"
    buggy = check_trace_memory_model(
        Trace.load(regression / "load_load_bug_completed.yaml"), model
    )
    fixed = check_trace_memory_model(
        Trace.load(regression / "load_load_fixed_completed.yaml"), model
    )
    assert buggy.status is MemoryModelStatus.FORBIDDEN
    assert fixed.status is MemoryModelStatus.ALLOWED
    assert buggy.representative.graph.relation("ppo_rule2").edges
