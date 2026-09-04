from pathlib import Path

import pytest

from umcm.composition.model import (
    CompositionSpec,
    ModulePort,
    ModuleReference,
    ModuleSpec,
    PortDirection,
)
from umcm.coverage import CoverageSuite, run_coverage
from umcm.coverage.engine import CoverageStatus
from umcm.coverage.model import (
    AutoGoalSelector,
    CoverageGoal,
    CoverageInput,
    CoverageModel,
    CoverageProbe,
)
from umcm.errors import CoverageError
from umcm.ir.completion import EventSlot
from umcm.ir.event import EventCatalog, EventInstance, EventType
from umcm.ir.expression import Binary, EventField, Literal
from umcm.ir.sort import BOOL, INT
from umcm.ir.state import StateUpdate, StateVariable
from umcm.ir.trace import Trace
from umcm.ir.transformation import EventRole, Transformation
from umcm.solver.completion import CompletionStatus, complete_trace


def _fixture(tmp_path: Path, *, inject_private_input: bool = False) -> CoverageSuite:
    catalog = EventCatalog(
        {
            "Test.Command": EventType("Test.Command", "Test", "input"),
            "Test.Done": EventType("Test.Done", "Test", "private"),
        }
    )
    catalog.dump(tmp_path / "events.yaml")
    module = ModuleSpec(
        name="worker",
        ports=[
            ModulePort("command", PortDirection.INPUT, "Test.Command", False),
            ModulePort("done", PortDirection.OUTPUT, "Test.Done", False),
        ],
        internal_events=["Test.Done"],
        slots=[EventSlot("done_0", "Test.Done")],
        state_variables=[StateVariable("Worker.done", BOOL, False)],
        transformations=[
            Transformation(
                name="do_it",
                inputs=(EventRole("command", "Test.Command"),),
                outputs=(EventRole("done", "Test.Done"),),
                ensure=(
                    Binary(
                        "lt",
                        EventField("command", "cycle", INT),
                        EventField("done", "cycle", INT),
                    ),
                ),
                state_updates=(
                    StateUpdate("Worker.done", "done", Literal(True, BOOL)),
                ),
                exact=True,
            )
        ],
    )
    module.dump(tmp_path / "worker.yaml")
    CompositionSpec(
        name="worker-composition",
        modules=[ModuleReference("worker", "worker.yaml")],
        horizon=3,
    ).dump(tmp_path / "composition.yaml")
    events = [EventInstance("command_0", "Test.Command", cycle=0)]
    if inject_private_input:
        events.append(EventInstance("smuggled", "Test.Done", cycle=1))
    Trace(events=events, partial=True).dump(tmp_path / "input.yaml")
    suite = CoverageSuite(
        name="worker-coverage",
        catalog="events.yaml",
        models=(
            CoverageModel(
                name="worker",
                composition="composition.yaml",
                inputs=(CoverageInput("one-command", "input.yaml"),),
                input_event_types=("Test.Command",),
            ),
        ),
        goals=(
            CoverageGoal(
                id="do_it_path",
                model="worker",
                probes=(
                    CoverageProbe("transformation", "do_it"),
                    CoverageProbe("event", "Test.Done"),
                    CoverageProbe(
                        "state_transition",
                        {"state": "Worker.done", "from": False, "to": True},
                    ),
                ),
                required=True,
            ),
        ),
        auto_goals=(
            AutoGoalSelector(
                model="worker",
                kind="public_interface",
                include=("worker.done",),
            ),
        ),
        source_path=tmp_path / "suite.yaml",
    )
    suite.validate()
    suite.dump(tmp_path / "suite.yaml")
    return suite


def test_completion_reports_actual_transformation_activation(tmp_path: Path) -> None:
    suite = _fixture(tmp_path)
    catalog = EventCatalog.load(tmp_path / suite.catalog)
    module = ModuleSpec.load(tmp_path / "worker.yaml")
    trace = Trace.load(tmp_path / "input.yaml")
    from umcm.ir.completion import CompletionSpec

    result = complete_trace(
        catalog,
        trace,
        CompletionSpec(
            slots=module.slots,
            state_variables=module.state_variables,
            transformations=module.transformations,
            horizon=3,
        ),
        backend="z3",
    )
    assert result.status is CompletionStatus.FEASIBLE
    assert [item["transformation"] for item in result.active_transformations] == [
        "do_it"
    ]


def test_coverage_searches_compound_goal_and_auto_interface(tmp_path: Path) -> None:
    report = run_coverage(_fixture(tmp_path), backend="z3")

    assert report.required_complete
    assert [item.status for item in report.results] == [
        CoverageStatus.COVERED,
        CoverageStatus.COVERED,
    ]
    primary = report.results[0]
    assert primary.input_name == "one-command"
    assert primary.witness is not None
    assert primary.witness.get("done_0").cycle > 0
    assert "do_it" in primary.active_transformations


def test_coverage_input_contract_rejects_private_path_injection(tmp_path: Path) -> None:
    with pytest.raises(CoverageError, match="outside input_event_types: Test.Done"):
        run_coverage(_fixture(tmp_path, inject_private_input=True), backend="z3")


def test_missing_event_producer_is_reported_unreachable(tmp_path: Path) -> None:
    suite = _fixture(tmp_path)
    suite.goals = (
        CoverageGoal(
            id="missing",
            model="worker",
            probes=(CoverageProbe("event", "Test.Never"),),
        ),
    )
    suite.auto_goals = ()

    report = run_coverage(suite, backend="z3")

    assert report.results[0].status is CoverageStatus.UNREACHABLE
    assert "no bounded producer/binding" in report.results[0].reason


def test_coverage_suite_roundtrip_and_cli(tmp_path: Path) -> None:
    from umcm.cli import main

    suite = _fixture(tmp_path)
    loaded = CoverageSuite.load(tmp_path / "suite.yaml")
    assert loaded.to_dict() == suite.to_dict()

    output = tmp_path / "report.yaml"
    witnesses = tmp_path / "witnesses"
    assert main(
        [
            "cover",
            "worker",
            "--suite",
            str(tmp_path / "suite.yaml"),
            "--backend",
            "z3",
            "--output",
            str(output),
            "--witness-dir",
            str(witnesses),
        ]
    ) == 0
    assert output.is_file()
    assert (witnesses / "do_it_path.yaml").is_file()
