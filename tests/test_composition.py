from __future__ import annotations

from pathlib import Path

import pytest

from umcm.composition import (
    CompositionSpec,
    ConnectionMode,
    ConnectionSpec,
    ModulePort,
    ModuleReference,
    ModuleSpec,
    PortDirection,
    PortEndpoint,
    compose_modules,
)
from umcm.errors import CompositionError, SchemaError
from umcm.graph.checker import MemoryModelStatus, check_trace_memory_model
from umcm.graph.model import GraphModelSpec
from umcm.ir.completion import CompletionSpec, EventSlot
from umcm.ir.event import EventCatalog, EventType, FieldSpec
from umcm.ir.sort import Sort
from umcm.ir.trace import Trace
from umcm.ir.transformation import EventRole, Transformation
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/boom_load_load"


def _semantic_event_signature(trace: Trace) -> dict[str, tuple[object, ...]]:
    return {
        event.id: (
            event.event_type,
            event.cycle,
            event.occurs,
            tuple(sorted(event.fields.items())),
        )
        for event in trace.events
    }


def _candidate_signature(result) -> set[tuple[tuple[str, tuple[tuple[str, str], ...]], ...]]:
    signatures = set()
    for candidate in result.candidates:
        graph = candidate.graph
        signatures.add(
            tuple(
                sorted(
                    (
                        name,
                        tuple(sorted(relation.edges)),
                    )
                    for name, relation in graph.relations.items()
                )
            )
        )
    return signatures


def test_module_and_composition_roundtrip(tmp_path: Path) -> None:
    module = ModuleSpec.load(EXAMPLE / "modular/modules/lsu_buggy.yaml")
    module_path = tmp_path / "module.json"
    module.dump(module_path)
    assert ModuleSpec.load(module_path).to_dict() == module.to_dict()

    composition = CompositionSpec.load(EXAMPLE / "modular/buggy_composition.yaml")
    composition_path = tmp_path / "composition.json"
    composition.dump(composition_path)
    loaded = CompositionSpec.load(composition_path)
    assert loaded.to_dict() == composition.to_dict()


def test_buggy_modular_composition_matches_monolithic_witness() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    trace = Trace.load(EXAMPLE / "stage6_trace.yaml")
    monolithic = CompletionSpec.load(
        EXAMPLE / "load_load_buggy_mshr_completion.yaml"
    )
    composition = CompositionSpec.load(EXAMPLE / "modular/buggy_composition.yaml")
    composed = compose_modules(catalog, composition)

    monolithic_result = complete_trace(catalog, trace, monolithic)
    modular_result = complete_trace(catalog, trace, composed.completion)
    assert monolithic_result.status is CompletionStatus.FEASIBLE
    assert modular_result.status is CompletionStatus.FEASIBLE
    assert monolithic_result.completed_trace is not None
    assert modular_result.completed_trace is not None
    assert _semantic_event_signature(modular_result.completed_trace) == (
        _semantic_event_signature(monolithic_result.completed_trace)
    )
    assert modular_result.final_state == monolithic_result.final_state

    graph_model = GraphModelSpec.load(
        EXAMPLE / "rvwmo_load_load_fragment.yaml"
    )
    monolithic_graphs = check_trace_memory_model(
        monolithic_result.completed_trace, graph_model
    )
    modular_graphs = check_trace_memory_model(
        modular_result.completed_trace, graph_model
    )
    assert monolithic_graphs.status is MemoryModelStatus.FORBIDDEN
    assert modular_graphs.status is MemoryModelStatus.FORBIDDEN
    assert _candidate_signature(modular_graphs) == _candidate_signature(
        monolithic_graphs
    )

    manifest = composed.manifest
    assert manifest["totals"] == {
        "slots": 36,
        "state_variables": 32,
        "transformations": 37,
        "constraints": 21,
        "horizon": 20,
    }
    assert [item.reference_name for item in composed.modules] == [
        "lsu", "dcache", "mshr", "coherence", "rob"
    ]


def test_fixed_modular_recovery_allows_recovery_trace_and_blocks_bad_commit() -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    composition = CompositionSpec.load(EXAMPLE / "modular/fixed_composition.yaml")
    composed = compose_modules(catalog, composition)

    recovery_trace = Trace.load(EXAMPLE / "stage6_recovery_trace.yaml")
    recovery = complete_trace(catalog, recovery_trace, composed.completion)
    monolithic = complete_trace(
        catalog,
        recovery_trace,
        CompletionSpec.load(EXAMPLE / "load_load_fixed_mshr_completion.yaml"),
    )
    assert recovery.status is CompletionStatus.FEASIBLE
    assert monolithic.status is CompletionStatus.FEASIBLE
    assert recovery.completed_trace is not None
    assert monolithic.completed_trace is not None
    assert _semantic_event_signature(recovery.completed_trace) == (
        _semantic_event_signature(monolithic.completed_trace)
    )
    assert recovery.final_state == monolithic.final_state
    assert recovery.final_state["LSU.ldq.L1.order_fail"] is True
    assert recovery.final_state["LSU.ldq.L1.squashed"] is True
    assert recovery.final_state["LSU.ldq.L1.valid"] is False

    checked = check_trace_memory_model(
        recovery.completed_trace,
        GraphModelSpec.load(EXAMPLE / "rvwmo_load_load_fragment.yaml"),
    )
    assert checked.status is MemoryModelStatus.ALLOWED

    forbidden_trace = Trace.load(EXAMPLE / "stage6_trace.yaml")
    forbidden = complete_trace(catalog, forbidden_trace, composed.completion)
    assert forbidden.status is CompletionStatus.INFEASIBLE
    assert "LSU.ldq.L1.valid == True" in forbidden.reason


def test_required_module_port_must_be_connected(tmp_path: Path) -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    module = ModuleSpec(
        name="source",
        ports=[
            ModulePort(
                name="required",
                direction=PortDirection.OUTPUT,
                event_type="LSU.DCacheReqValid",
                required_connection=True,
            )
        ],
    )
    module_path = tmp_path / "source.yaml"
    module.dump(module_path)
    composition = CompositionSpec(
        name="missing-wire",
        modules=[ModuleReference("source", str(module_path))],
    )
    with pytest.raises(CompositionError, match="required port source.required"):
        compose_modules(catalog, composition)


def test_shared_event_connection_requires_identical_event_types(tmp_path: Path) -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    source = ModuleSpec(
        name="source",
        ports=[
            ModulePort(
                "out", PortDirection.OUTPUT, "LSU.DCacheReqValid", True
            )
        ],
    )
    target = ModuleSpec(
        name="target",
        ports=[
            ModulePort(
                "in", PortDirection.INPUT, "DCache.LoadResponse", True
            )
        ],
    )
    source_path = tmp_path / "source.yaml"
    target_path = tmp_path / "target.yaml"
    source.dump(source_path)
    target.dump(target_path)
    composition = CompositionSpec(
        name="bad-shared-wire",
        modules=[
            ModuleReference("source", str(source_path)),
            ModuleReference("target", str(target_path)),
        ],
        connections=[
            ConnectionSpec(
                name="wire",
                source=PortEndpoint("source", "out"),
                target=PortEndpoint("target", "in"),
            )
        ],
    )
    with pytest.raises(CompositionError, match="requires the same event type"):
        compose_modules(catalog, composition)


def test_event_map_connection_generates_exact_transition(tmp_path: Path) -> None:
    op_id = Sort("op_id")
    source_type = EventType(
        name="Source.Send",
        module="Source",
        layer="test",
        fields=(FieldSpec("op_id", op_id),),
    )
    target_type = EventType(
        name="Target.Receive",
        module="Target",
        layer="test",
        fields=(FieldSpec("request_id", op_id),),
    )
    catalog = EventCatalog(
        {source_type.name: source_type, target_type.name: target_type}
    )
    source = ModuleSpec(
        name="source",
        ports=[
            ModulePort("send", PortDirection.OUTPUT, "Source.Send", True)
        ],
        slots=[
            EventSlot(
                id="send_0",
                event_type="Source.Send",
                fields={"op_id": "L0"},
                required=True,
                cycle=1,
            )
        ],
    )
    target = ModuleSpec(
        name="target",
        ports=[
            ModulePort("receive", PortDirection.INPUT, "Target.Receive", True)
        ],
        slots=[
            EventSlot(
                id="receive_0",
                event_type="Target.Receive",
                fields={"request_id": "L0"},
                required=False,
                cycle=1,
            )
        ],
    )
    source_path = tmp_path / "source.yaml"
    target_path = tmp_path / "target.yaml"
    source.dump(source_path)
    target.dump(target_path)
    composition = CompositionSpec(
        name="mapped-wire",
        horizon=2,
        modules=[
            ModuleReference("source", str(source_path)),
            ModuleReference("target", str(target_path)),
        ],
        connections=[
            ConnectionSpec(
                name="send_to_receive",
                source=PortEndpoint("source", "send"),
                target=PortEndpoint("target", "receive"),
                mode=ConnectionMode.EVENT_MAP,
                field_map={"request_id": "op_id"},
            )
        ],
    )
    composed = compose_modules(catalog, composition)
    assert composed.generated_transformations == (
        "connection.send_to_receive",
    )

    result = complete_trace(catalog, Trace(partial=True), composed.completion)
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    receive = result.completed_trace.get("receive_0")
    assert receive.occurs is True
    assert receive.cycle == 1
    assert receive.fields["request_id"] == "L0"


def test_module_transformation_must_use_declared_slots_or_ports() -> None:
    op_id = Sort("op_id")
    source_type = EventType(
        name="Source.Send",
        module="Source",
        layer="test",
        fields=(FieldSpec("op_id", op_id),),
    )
    catalog = EventCatalog({source_type.name: source_type})
    module = ModuleSpec(
        name="source",
        transformations=[
            Transformation(
                name="hidden_dependency",
                inputs=(EventRole("send", "Source.Send"),),
            )
        ],
    )
    with pytest.raises(
        SchemaError,
        match="not declared by a slot or port: Source.Send",
    ):
        module.validate(catalog)


def test_input_port_rejects_multiple_sources(tmp_path: Path) -> None:
    catalog = EventCatalog.load(EXAMPLE / "event_types.yaml")
    modules = []
    for name, direction in (
        ("source_a", PortDirection.OUTPUT),
        ("source_b", PortDirection.OUTPUT),
        ("target", PortDirection.INPUT),
    ):
        module = ModuleSpec(
            name=name,
            ports=[
                ModulePort(
                    "event",
                    direction,
                    "LSU.DCacheReqFire",
                    required_connection=True,
                )
            ],
        )
        path = tmp_path / f"{name}.yaml"
        module.dump(path)
        modules.append(ModuleReference(name, str(path)))

    composition = CompositionSpec(
        name="two-drivers",
        modules=modules,
        connections=[
            ConnectionSpec(
                "a_to_target",
                PortEndpoint("source_a", "event"),
                PortEndpoint("target", "event"),
            ),
            ConnectionSpec(
                "b_to_target",
                PortEndpoint("source_b", "event"),
                PortEndpoint("target", "event"),
            ),
        ],
    )
    with pytest.raises(CompositionError, match="more than one incoming"):
        compose_modules(catalog, composition)
