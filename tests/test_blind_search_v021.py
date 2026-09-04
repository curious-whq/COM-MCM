from __future__ import annotations

from pathlib import Path

from umcm.search import (
    HierarchicalSearchSpec,
    SearchStatus,
    StageStatus,
    run_hierarchical_search,
)


ROOT = Path(__file__).resolve().parents[1]
BOOM_SEARCH = ROOT / "examples/boom/search/v021.yaml"


def test_bounds_generate_the_forbidden_program_without_operation_slots():
    spec = HierarchicalSearchSpec.load(BOOM_SEARCH)
    assert spec.architecture.generation == "bounded"
    assert spec.architecture.operations == ()
    assert spec.architecture.init_writes == ()

    report = run_hierarchical_search(spec, backend="z3")

    assert report.status is SearchStatus.BLOCKED
    assert not report.end_to_end
    assert report.skeleton is not None
    rendered = str(report.skeleton.trace.to_dict())
    for forbidden in (
        "TLBMiss", "L1Hit", "MSHR", "Probe", "ldq_idx", "mshr_idx"
    ):
        assert forbidden not in rendered

    stage = report.stages[0]
    assert stage.status is StageStatus.BLOCKED
    assert "cacheable_path.yaml" in stage.reason
    assert any("post-nack store request" in item for item in stage.missing_interfaces)
    assert any("per-hart" in item for item in stage.missing_interfaces)
    assert any("ProbeAckData" in item for item in stage.missing_interfaces)
