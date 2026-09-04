from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from umcm.errors import SearchError
from umcm.search import (
    HierarchicalSearchSpec,
    SearchStatus,
    StageStatus,
    run_hierarchical_search,
)


ROOT = Path(__file__).resolve().parents[1]
BOOM_SEARCH = ROOT / "examples/boom/search/v020.yaml"


def test_architecture_layer_finds_load_load_rvwmo_skeleton_without_uarch_hints():
    spec = HierarchicalSearchSpec.load(BOOM_SEARCH)
    architecture_only = replace(
        spec,
        stages=(spec.stages[1],),
        source_path=spec.source_path,
    )

    report = run_hierarchical_search(architecture_only, backend="z3")

    assert report.status is SearchStatus.BLOCKED
    assert report.assignments_examined == 3
    assert report.skeleton is not None
    graph = report.skeleton.graph
    assert graph.operations["R0"].read_value == 1
    assert graph.operations["R1"].read_value == 0
    assert graph.relation("rf").edges == {
        ("W", "R0"),
        ("InitX", "R1"),
    }
    assert graph.relation("fr").edges == {("R1", "W")}
    assert graph.relation("ppo").edges == {("R0", "R1")}

    generated = report.skeleton.trace.to_dict()
    rendered = str(generated)
    for forbidden in ("TLBMiss", "MSHR", "Probe", "ldq_idx", "mshr_idx"):
        assert forbidden not in rendered


def test_real_coherence_slice_realizes_obligations_via_public_events():
    spec = HierarchicalSearchSpec.load(BOOM_SEARCH)
    report = run_hierarchical_search(spec, backend="z3")

    assert report.status is SearchStatus.PARTIAL
    assert not report.end_to_end
    coherence, gap = report.stages
    assert coherence.status is StageStatus.REALIZABLE
    assert coherence.schedule == ("R1", "W", "R0")
    assert coherence.attempts == 1
    assert gap.status is StageStatus.BLOCKED

    observations = list(coherence.public_observations)
    types = {str(item["type"]) for item in observations}
    assert types <= {
        "Coherence.LineInit",
        "Coherence.Access",
        "Coherence.LoadResult",
        "Coherence.StorePerformed",
    }
    results = {
        item["fields"]["op_id"]: item["fields"]
        for item in observations
        if item["type"] == "Coherence.LoadResult"
    }
    assert results["R1"]["value"] == 0
    assert results["R1"]["source_op_id"] == "InitX"
    assert results["R0"]["value"] == 1
    assert results["R0"]["source_op_id"] == "W"


def test_realization_adapter_rejects_private_event_vocabulary():
    spec = HierarchicalSearchSpec.load(BOOM_SEARCH)
    coherence = spec.stages[0]
    private_stage = replace(
        coherence,
        input_event_types=("Coherence.LineInit", "LSU.TLBMiss"),
        event_types={**coherence.event_types, "access": "LSU.TLBMiss"},
    )
    invalid = replace(
        spec,
        stages=(private_stage,),
        source_path=spec.source_path,
    )

    with pytest.raises(SearchError, match="private event type 'LSU.TLBMiss'"):
        run_hierarchical_search(invalid, backend="z3")


def test_search_report_keeps_interface_gap_explicit():
    spec = HierarchicalSearchSpec.load(BOOM_SEARCH)
    report = run_hierarchical_search(
        replace(spec, stages=(spec.stages[1],), source_path=spec.source_path),
        backend="z3",
    )
    payload = report.to_dict()

    assert payload["status"] == "blocked"
    assert payload["end_to_end"] is False
    stage = payload["realization"]["stages"][0]
    assert stage["status"] == "blocked"
    assert "DCache/MSHR Acquire-Grant adapter" in stage["missing_interfaces"][1]
