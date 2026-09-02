from pathlib import Path

from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace


ROOT = Path(__file__).resolve().parents[1]


def test_boom_example_validates_and_roundtrips(tmp_path: Path) -> None:
    catalog = EventCatalog.load(ROOT / "tests/regressions/boom/legacy_v0_11/event_types.yaml")
    trace = Trace.load(ROOT / "tests/regressions/boom/legacy_v0_11/partial_trace.yaml")
    trace.validate(catalog)

    assert len(catalog.event_types) == 41
    assert len(trace.events) == 6
    assert len(trace.constraints) == 2
    assert trace.get("commit_l0").fields["value"] == 1
    assert trace.get("commit_l1").fields["value"] == 0

    out = tmp_path / "trace.json"
    trace.dump(out)
    reloaded = Trace.load(out)
    reloaded.validate(catalog)
    assert reloaded.to_dict() == trace.to_dict()
