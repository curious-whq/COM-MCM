from pathlib import Path

from umcm.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_validate_cli(capsys) -> None:
    code = main(
        [
            "validate",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/partial_trace.yaml"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "VALID partial trace" in captured.out


def test_complete_cli(capsys, tmp_path) -> None:
    output = tmp_path / "completed.yaml"
    code = main(
        [
            "complete",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/partial_trace.yaml"),
            "--model",
            str(ROOT / "examples/boom_load_load/retry_completion.yaml"),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "FEASIBLE finite completion" in captured.out
    assert "LSU.RetryIssue" in captured.out
    assert output.exists()


def test_complete_stage4_young_load_probe_cli(capsys, tmp_path) -> None:
    output = tmp_path / "stage4-completed.yaml"
    code = main(
        [
            "complete",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage4_trace.yaml"),
            "--model",
            str(ROOT / "examples/boom_load_load/young_load_probe_completion.yaml"),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "DCache.LoadResponse" in captured.out
    assert "LSU.LoadObserved" in captured.out
    assert output.exists()


def test_stage4_wrong_probe_address_cli_is_infeasible(capsys) -> None:
    code = main(
        [
            "complete",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage4_trace.yaml"),
            "--model",
            str(ROOT / "examples/boom_load_load/young_load_probe_address_mismatch.yaml"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "INFEASIBLE" in captured.out


def test_check_cli_reports_boom_violation(capsys, tmp_path) -> None:
    from umcm.ir.completion import CompletionSpec
    from umcm.ir.event import EventCatalog
    from umcm.ir.trace import Trace
    from umcm.solver.completion import CompletionStatus, complete_trace

    catalog = EventCatalog.load(ROOT / "examples/boom_load_load/event_types.yaml")
    trace = Trace.load(ROOT / "examples/boom_load_load/stage6_trace.yaml")
    model = CompletionSpec.load(
        ROOT / "examples/boom_load_load/load_load_buggy_mshr_completion.yaml"
    )
    completed = complete_trace(catalog, trace, model)
    assert completed.status is CompletionStatus.FEASIBLE
    assert completed.completed_trace is not None
    trace_path = tmp_path / "completed.yaml"
    completed.completed_trace.dump(trace_path)
    graph_path = tmp_path / "graph.yaml"

    code = main(
        [
            "check",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(trace_path),
            "--axioms",
            str(ROOT / "examples/boom_load_load/rvwmo_load_load_fragment.yaml"),
            "--output",
            str(graph_path),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "MEMORY MODEL VIOLATION" in captured.out
    assert "W1 -rfe/rf-> L0" in captured.out
    assert "L0 -ppo-> L1" in captured.out
    assert "L1 -fr-> W1" in captured.out
    assert graph_path.exists()


def test_check_cli_reports_allowed_control(capsys) -> None:
    code = main(
        [
            "check",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage7_allowed_trace.yaml"),
            "--axioms",
            str(ROOT / "examples/boom_load_load/rvwmo_load_load_fragment.yaml"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "MEMORY MODEL ALLOWED" in captured.out


def test_check_cli_reports_fixed_recovery_allowed(capsys, tmp_path) -> None:
    from umcm.ir.completion import CompletionSpec
    from umcm.ir.event import EventCatalog
    from umcm.ir.trace import Trace
    from umcm.solver.completion import CompletionStatus, complete_trace

    catalog = EventCatalog.load(ROOT / "examples/boom_load_load/event_types.yaml")
    trace = Trace.load(ROOT / "examples/boom_load_load/stage6_recovery_trace.yaml")
    model = CompletionSpec.load(
        ROOT / "examples/boom_load_load/load_load_fixed_mshr_completion.yaml"
    )
    completed = complete_trace(catalog, trace, model)
    assert completed.status is CompletionStatus.FEASIBLE
    assert completed.completed_trace is not None
    trace_path = tmp_path / "fixed-completed.yaml"
    completed.completed_trace.dump(trace_path)

    code = main(
        [
            "check",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(trace_path),
            "--axioms",
            str(ROOT / "examples/boom_load_load/rvwmo_load_load_fragment.yaml"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "MEMORY MODEL ALLOWED" in captured.out
    assert "L1: read" not in captured.out


def test_abstract_cli_preserves_boom_violation(capsys, tmp_path) -> None:
    output = tmp_path / "abstract.yaml"
    code = main(
        [
            "abstract",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage7_buggy_completed.yaml"),
            "--abstraction",
            str(ROOT / "examples/boom_load_load/hierarchy_abstraction.yaml"),
            "--axioms",
            str(ROOT / "examples/boom_load_load/rvwmo_load_load_fragment.yaml"),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "36 concrete event(s), 11 output event(s)" in captured.out
    assert "concrete=forbidden, abstract=forbidden" in captured.out
    assert "PRESERVED" in captured.out
    assert output.exists()


def test_refine_cli_accepts_generated_abstraction(capsys, tmp_path) -> None:
    abstract_path = tmp_path / "abstract.yaml"
    assert main(
        [
            "abstract",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage7_buggy_completed.yaml"),
            "--abstraction",
            str(ROOT / "examples/boom_load_load/hierarchy_abstraction.yaml"),
            "--output",
            str(abstract_path),
        ]
    ) == 0
    capsys.readouterr()

    code = main(
        [
            "refine",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--concrete",
            str(ROOT / "examples/boom_load_load/stage7_buggy_completed.yaml"),
            "--abstract-trace",
            str(abstract_path),
            "--abstraction",
            str(ROOT / "examples/boom_load_load/hierarchy_abstraction.yaml"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "REFINEMENT VALID" in captured.out


def test_compose_cli_writes_modular_boom_model(capsys, tmp_path) -> None:
    output = tmp_path / "composed.yaml"
    code = main(
        [
            "compose",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--composition",
            str(ROOT / "examples/boom_load_load/modular/buggy_composition.yaml"),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "5 module(s), 21 connection(s)" in captured.out
    assert "module lsu" in captured.out
    assert "module dcache" in captured.out
    assert output.exists()


def test_complete_cli_accepts_modular_composition(capsys, tmp_path) -> None:
    output = tmp_path / "modular-completed.yaml"
    code = main(
        [
            "complete",
            "--schema",
            str(ROOT / "examples/boom_load_load/event_types.yaml"),
            "--trace",
            str(ROOT / "examples/boom_load_load/stage6_trace.yaml"),
            "--composition",
            str(ROOT / "examples/boom_load_load/modular/buggy_composition.yaml"),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "COMPOSED boom-load-load-buggy-modular-v0.9" in captured.out
    assert "FEASIBLE finite completion" in captured.out
    assert output.exists()
