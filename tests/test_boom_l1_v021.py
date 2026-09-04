from pathlib import Path

import pytest

from umcm.composition import CompositionSpec, compose_modules
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.serialization import load_data
from umcm.solver.completion import CompletionStatus, complete_trace


ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"
TRACE_DIR = BOOM / "traces" / "source_model"


def complete_l1(name: str):
    catalog = EventCatalog.load(BOOM / "events.yaml")
    source = Trace.load(TRACE_DIR / name)
    composition = CompositionSpec.load(BOOM / "composition" / "l1_source_v021.yaml")
    composed = compose_modules(catalog, composition, source)
    result = complete_trace(catalog, source, composed.completion, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE, result.reason
    assert result.completed_trace is not None
    return source, composed, result


def occurred(result, event_type: str):
    return [
        event
        for event in result.completed_trace.events
        if event.occurs is True and event.event_type == event_type
    ]


def test_l1_model_is_source_pinned_and_not_witness_shaped():
    raw = load_data(BOOM / "model" / "l1" / "generic_v021.yaml")
    assert raw["metadata"]["source"]["commit"] == (
        "58ef2720eae13be26b3008c02b5a74ce29c61c44"
    )
    assert raw["metadata"]["configuration"] == {
        "family": "BOOM-v4-four-way",
        "geometry": "SmallBoom/MediumBoom-compatible",
        "width_and_banks": "selected-by-DCache.ConfigInit",
    }
    text = (BOOM / "model" / "l1" / "generic_v021.yaml").read_text()
    assert "older_op_id" not in text
    assert "younger_op_id" not in text
    assert "expected" not in text
    assert "source:dcache.scala:" in text


@pytest.mark.parametrize(
    ("trace_name", "expected_type", "expected_value"),
    [
        ("l1_generic_hit.yaml", "DCache.LoadResponse", 42),
        ("l1_generic_refill_then_hit.yaml", "DCache.LoadResponse", 88),
        ("l1_generic_miss.yaml", "DCache.LoadMiss", None),
    ],
)
def test_l1_derives_hit_miss_and_refill_state(trace_name, expected_type, expected_value):
    source, _, result = complete_l1(trace_name)
    assert not source.events_of_type("DCache.LoadHit")
    assert not source.events_of_type("DCache.LoadMiss")
    events = occurred(result, expected_type)
    assert len(events) == 1
    if expected_value is not None:
        assert events[0].fields["value"] == expected_value


def test_l1_replacement_and_write_permission_are_state_derived():
    _, _, miss = complete_l1("l1_generic_miss.yaml")
    admission = occurred(miss, "DCache.MSHRAdmissionRequest")[0]
    assert admission.fields["way_id"] == 2
    assert admission.fields["cache_tag_match"] is False
    assert admission.fields["old_line_dirty"] is True

    _, _, permission = complete_l1("l1_generic_permission_miss.yaml")
    upgrade = occurred(permission, "DCache.MSHRAdmissionRequest")[0]
    assert upgrade.fields["way_id"] == 0
    assert upgrade.fields["cache_tag_match"] is True
    assert not occurred(permission, "DCache.StoreHit")


def test_l1_store_hit_writes_data_one_stage_later():
    _, _, result = complete_l1("l1_generic_store_hit.yaml")
    hit = occurred(result, "DCache.StoreHit")[0]
    write = occurred(result, "DCache.StoreDataWrite")[0]
    assert write.cycle == hit.cycle + 1
    assert write.fields["value"] == 55
    assert result.final_state["DCache.set[set0].way[0].value"] == 55


def test_l1_port_priority_derives_lower_port_bank_conflict_nack():
    source, _, result = complete_l1("l1_generic_bank_conflict.yaml")
    assert not source.events_of_type("DCache.LoadNack")
    conflict = occurred(result, "DCache.DataBankConflict")[0]
    assert conflict.fields["winner_op_id"] == "L0"
    assert conflict.fields["victim_op_id"] == "L1"
    nack = occurred(result, "DCache.RequestNack")[0]
    assert nack.fields["op_id"] == "L1"
    assert nack.fields["reason"] == "data-bank-conflict"
    assert {item.fields["op_id"] for item in occurred(result, "DCache.LoadResponse")} == {
        "L0"
    }


def test_l1_configuration_prevents_multiport_path_in_smallboom():
    raw = load_data(TRACE_DIR / "l1_generic_bank_conflict.yaml")
    raw["events"][0]["fields"].update(
        {"config_id": "small", "lsu_width": 1, "num_banks": 1}
    )
    source = Trace.from_dict(raw)
    catalog = EventCatalog.load(BOOM / "events.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "l1_source_v021.yaml")
    composed = compose_modules(catalog, composition, source)
    result = complete_trace(catalog, source, composed.completion, backend="z3")
    assert result.status is CompletionStatus.INFEASIBLE


def test_l1_clean_probe_invalidates_and_later_load_misses():
    source, _, result = complete_l1("l1_generic_probe_clean.yaml")
    assert not source.events_of_type("DCache.ProbeWriteback")
    assert not occurred(result, "DCache.ProbeWriteback")
    release = occurred(result, "DCache.ProbeRelease")[0]
    assert release.fields["tag_match"] is True
    assert release.fields["had_data"] is False
    assert occurred(result, "DCache.ProbeMetaWrite")[0].fields["new_permission"] == (
        "nothing"
    )
    assert result.final_state["DCache.set[set0].way[0].tag"] == -1
    assert result.final_state["DCache.set[set0].way[0].permission"] == "nothing"
    assert occurred(result, "DCache.LoadMiss")


def test_l1_dirty_probe_writes_back_then_downgrades_and_preserves_data():
    source, _, result = complete_l1("l1_generic_probe_dirty.yaml")
    assert not source.events_of_type("DCache.ProbeWriteback")
    writeback = occurred(result, "DCache.ProbeWriteback")[0]
    release = occurred(result, "DCache.ProbeRelease")[0]
    assert release.cycle == writeback.cycle + 1
    assert release.fields["had_data"] is True
    assert occurred(result, "DCache.ProbeMetaWrite")[0].fields["new_permission"] == (
        "branch"
    )
    assert result.final_state["DCache.set[set0].way[0].permission"] == "branch"
    assert occurred(result, "DCache.LoadResponse")[0].fields["value"] == 42


def test_l1_routes_two_sets_without_cross_set_tag_matches():
    _, _, result = complete_l1("l1_generic_two_sets.yaml")
    values = {
        event.fields["op_id"]: event.fields["value"]
        for event in occurred(result, "DCache.LoadResponse")
    }
    assert values == {"L0": 42, "L1": 77}
