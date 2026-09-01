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
