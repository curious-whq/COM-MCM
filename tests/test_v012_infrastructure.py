from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.composition.parameterization import expand_module_repeats
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionStatus, complete_trace

ROOT = Path(__file__).resolve().parents[1]
BOOM = ROOT / "examples" / "boom"


def test_repeat_product_preserves_duplicate_collection_positions() -> None:
    raw = {
        "schema_version": "umcm.module.v0.12.0",
        "name": "pair-test",
        "ports": [],
        "slots": [],
        "state_variables": [],
        "transformations": [],
        "constraints": [],
        "repeat_product": [
            {
                "axes": [
                    {"over": "loads", "as": "left"},
                    {"over": "loads", "as": "right"},
                ],
                "include": {
                    "slots": [
                        {
                            "id": "pair_${left.repeat_index}_${right.repeat_index}",
                            "type": "Dummy.Event",
                            "required": False,
                            "fields": {},
                        }
                    ]
                },
            }
        ],
    }
    # Exported values are intentionally identical.  Dynamic collection position,
    # not dict equality, must determine repeat_index.
    rendered = expand_module_repeats(raw, {"loads": [{"op_id": "L"}, {"op_id": "L"}]})
    assert [slot["id"] for slot in rendered["slots"]] == [
        "pair_0_0", "pair_0_1", "pair_1_0", "pair_1_1"
    ]


def test_state_guard_disables_exception_flush_for_committed_store() -> None:
    catalog = EventCatalog.load(BOOM / "events.yaml")
    trace = Trace.load(BOOM / "traces" / "committed_store_survives_exception.yaml")
    composition = CompositionSpec.load(BOOM / "composition" / "lsq.yaml")
    composed = compose_modules(catalog, composition, trace)
    result = complete_trace(catalog, trace, composed.completion, backend="z3")
    assert result.status is CompletionStatus.FEASIBLE
    assert result.completed_trace is not None
    assert not any(
        event.event_type == "LSU.StoreFlushed" for event in result.completed_trace.events
    )
    assert result.final_state["LSU.stq[2].committed"] is True
    assert result.final_state["LSU.stq[2].valid"] is True
