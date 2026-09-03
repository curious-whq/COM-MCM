from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from umcm.composition.engine import compose_modules
from umcm.composition.model import CompositionSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"
COHERENCE_TRACES = BOOM / "traces" / "coherence"


@lru_cache(maxsize=1)
def catalog() -> EventCatalog:
    return EventCatalog.load(BOOM / "events.yaml")


@lru_cache(maxsize=None)
def completed(case: str):
    source = Trace.load(COHERENCE_TRACES / f"{case}.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "coherence_v018.yaml")
    model = compose_modules(catalog(), composition, source).completion
    result = complete_trace(catalog(), source, model, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE, result.reason
    assert result.completed_trace is not None
    return result


def one(trace: Trace, event_type: str, txn_or_op: str):
    matches = [
        item
        for item in trace.events_of_type(event_type)
        if item.fields.get("txn_id", item.fields.get("op_id")) == txn_or_op
    ]
    assert len(matches) == 1, (event_type, txn_or_op, [item.id for item in matches])
    return matches[0]


def events(trace: Trace, event_type: str, txn_or_op: str):
    return [
        item
        for item in trace.events_of_type(event_type)
        if item.fields.get("txn_id", item.fields.get("op_id")) == txn_or_op
    ]


def test_v018_inputs_do_not_prescribe_protocol_outcomes() -> None:
    allowed = {"Coherence.LineInit", "Coherence.Access", "Coherence.Evict"}
    for path in sorted(COHERENCE_TRACES.glob("*.yaml")):
        trace = Trace.load(path)
        assert {item.event_type for item in trace.events} <= allowed


def test_v018_composition_has_only_public_tilelink_connections() -> None:
    source = Trace.load(COHERENCE_TRACES / "cold_read.yaml")
    result = compose_modules(
        catalog(),
        CompositionSpec.load(BOOM / "composition" / "coherence_v018.yaml"),
        source,
    )
    assert len(result.modules) == 2
    assert len(result.spec.connections) == 7
    assert {item.source.port for item in result.spec.connections} == {
        "acquire",
        "probe",
        "probe_ack",
        "grant",
        "grant_ack",
        "release",
        "release_ack",
    }
    hierarchy = result.completion.metadata["hierarchy"]["modules"]
    l2 = hierarchy["sifive_inclusive_l2"]
    assert "L2.DirectoryResult" in l2["private_event_types"]
    assert "L2.OuterAcquire" in l2["private_event_types"]
    assert "L2.line[x].state" in l2["private_state_names"]


def test_v018_source_metadata_pins_boom_chipyard_and_inclusivecache() -> None:
    source = Trace.load(COHERENCE_TRACES / "cold_read.yaml")
    result = compose_modules(
        catalog(),
        CompositionSpec.load(BOOM / "composition" / "coherence_v018.yaml"),
        source,
    )
    modules = {item.reference_name: item.spec for item in result.modules}
    l1 = modules["boom_l1_coherence_client"].metadata
    l2 = modules["sifive_inclusive_l2"].metadata
    assert l1["source_commit"] == "58ef2720eae13be26b3008c02b5a74ce29c61c44"
    assert l1["chipyard_commit"] == "4180463d52bc0a6b4c004530601ccdabebf0ab7d"
    assert l2["source_commit"] == "e3a3000cc1fd4cdf3a4e638e4d081b8aae94ebf0"
    assert l2["rocket_chip_commit"] == "114325b27cfe5312c86a8a325b187be9455a62af"
    assert l2["source_sha256"]["MSHR.scala"] == (
        "056c318d0fc4a5bd4b179179454915dfe7c3d7b81a81466831ab86bbd608f655"
    )


def test_cold_read_derives_directory_miss_outer_refill_and_trunk() -> None:
    result = completed("cold_read")
    trace = result.completed_trace
    acquire = one(trace, "TL.Acquire", "L0")
    directory = one(trace, "L2.DirectoryResult", "L0")
    outer_a = one(trace, "L2.OuterAcquire", "L0")
    outer_d = one(trace, "L2.OuterGrant", "L0")
    grant = one(trace, "TL.Grant", "L0")
    load = one(trace, "Coherence.LoadResult", "L0")
    assert acquire.fields == {
        "txn_id": "L0", "hart": 0, "line_id": "x", "address": "x",
        "grow": "NtoB", "need_data": True,
    }
    assert directory.fields["hit"] is False
    assert acquire.cycle < directory.cycle < outer_a.cycle < outer_d.cycle < grant.cycle
    assert grant.fields["cap"] == "T"
    assert grant.fields["has_data"] is True
    assert load.fields["path"] == "refill"
    assert (load.fields["value"], load.fields["version"], load.fields["source_op_id"]) == (
        0, 0, "InitX"
    )
    assert not list(trace.events_of_type("TL.Probe"))
    assert result.final_state["L2.line[x].state"] == "TRUNK"
    assert result.final_state["L2.line[x].owner"] == 0


def test_second_reader_derives_t_to_b_probe_and_shared_tip() -> None:
    result = completed("shared_read")
    trace = result.completed_trace
    directory = one(trace, "L2.DirectoryResult", "L1")
    probe = one(trace, "TL.Probe", "L1")
    ack = one(trace, "TL.ProbeAck", "L1")
    grant = one(trace, "TL.Grant", "L1")
    assert directory.fields["hit"] is True
    assert probe.fields["target_hart"] == 0 and probe.fields["cap"] == "B"
    assert ack.fields["hart"] == 0 and ack.fields["has_data"] is False
    assert grant.fields["hart"] == 1 and grant.fields["cap"] == "B"
    assert directory.cycle < probe.cycle < ack.cycle < grant.cycle
    assert not events(trace, "L2.OuterAcquire", "L1")
    assert result.final_state["L2.line[x].state"] == "TIP"
    assert result.final_state["L2.line[x].h0_perm"] == "B"
    assert result.final_state["L2.line[x].h1_perm"] == "B"


def test_write_upgrade_invalidates_other_sharer_and_creates_private_version() -> None:
    result = completed("write_upgrade")
    trace = result.completed_trace
    acquire = one(trace, "TL.Acquire", "W0")
    probe = one(trace, "TL.Probe", "W0")
    ack = one(trace, "TL.ProbeAck", "W0")
    grant = one(trace, "TL.Grant", "W0")
    store = one(trace, "Coherence.StorePerformed", "W0")
    assert acquire.fields["grow"] == "BtoT" and acquire.fields["need_data"] is False
    assert probe.fields["target_hart"] == 1 and probe.fields["cap"] == "N"
    assert ack.fields["has_data"] is False
    assert grant.fields["cap"] == "T" and grant.fields["has_data"] is False
    assert store.fields["value"] == 1 and store.fields["version"] == 1
    assert acquire.cycle < probe.cycle < ack.cycle < grant.cycle < store.cycle
    assert result.final_state["L1.h0.line[x].dirty"] is True
    assert result.final_state["L2.line[x].state"] == "TRUNK"
    assert result.final_state["L2.line[x].owner"] == 0
    assert result.final_state["L2.line[x].h1_perm"] == "N"


def test_dirty_owner_handoff_uses_probe_ack_data_as_new_version() -> None:
    result = completed("dirty_owner_handoff")
    trace = result.completed_trace
    ack = one(trace, "TL.ProbeAck", "L1")
    publish = one(trace, "Coherence.VersionPublish", "L1")
    grant = one(trace, "TL.Grant", "L1")
    load = one(trace, "Coherence.LoadResult", "L1")
    assert ack.fields["has_data"] is True
    assert (ack.fields["value"], ack.fields["version"], ack.fields["source_op_id"]) == (
        1, 1, "W0"
    )
    assert publish.fields["path"] == "ProbeAckData"
    assert ack.cycle < publish.cycle < grant.cycle < load.cycle
    assert (load.fields["value"], load.fields["version"], load.fields["source_op_id"]) == (
        1, 1, "W0"
    )
    assert result.final_state["L2.line[x].state"] == "TIP"
    assert result.final_state["L2.line[x].dirty"] is True


def test_dirty_release_publishes_data_and_later_hit_reuses_it() -> None:
    result = completed("dirty_release_reacquire")
    trace = result.completed_trace
    evict = trace.get("evict_h0")
    release = one(trace, "TL.Release", "E0")
    publish = one(trace, "Coherence.VersionPublish", "E0")
    release_ack = one(trace, "TL.ReleaseAck", "E0")
    directory = one(trace, "L2.DirectoryResult", "L1")
    load = one(trace, "Coherence.LoadResult", "L1")
    assert release.fields["shrink"] == "TtoN" and release.fields["has_data"] is True
    assert release.fields["version"] == 1 and release.fields["source_op_id"] == "W0"
    assert publish.fields["path"] == "ReleaseData"
    assert evict.cycle < release.cycle < publish.cycle < release_ack.cycle
    assert directory.fields["hit"] is True
    assert not events(trace, "L2.OuterAcquire", "L1")
    assert load.fields["version"] == 1 and load.fields["source_op_id"] == "W0"
    assert result.final_state["L2.line[x].state"] == "TRUNK"
    assert result.final_state["L2.line[x].owner"] == 1


def test_completed_cases_preserve_directory_state_invariants() -> None:
    for case in (
        "cold_read", "shared_read", "write_upgrade",
        "dirty_owner_handoff", "dirty_release_reacquire",
    ):
        state = completed(case).final_state
        directory_state = state["L2.line[x].state"]
        h0 = state["L2.line[x].h0_perm"]
        h1 = state["L2.line[x].h1_perm"]
        owner = state["L2.line[x].owner"]
        if directory_state == "INVALID":
            assert (h0, h1, owner, state["L2.line[x].dirty"]) == ("N", "N", -1, False)
        elif directory_state == "BRANCH":
            assert state["L2.line[x].dirty"] is False
        elif directory_state == "TRUNK":
            assert [(h0, 0), (h1, 1)].count(("T", owner)) == 1
            assert {h0, h1} <= {"N", "T"}
        elif directory_state == "TIP":
            assert owner == -1
            assert "T" not in {h0, h1}
        else:
            raise AssertionError(directory_state)
