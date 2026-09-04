from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.hierarchy import build_interface_contracts
from umcm.ir import EventCatalog
from umcm.ir.event import Visibility
from umcm.serialization import load_data


ROOT = Path(__file__).resolve().parents[1]
XIANGSHAN = ROOT / "examples" / "xiangshan"


def _catalog() -> EventCatalog:
    return EventCatalog.load(XIANGSHAN / "events.yaml")


def _composition():
    catalog = _catalog()
    manifest = CompositionSpec.load(XIANGSHAN / "composition" / "baseline.yaml")
    return catalog, manifest, compose_modules(catalog, manifest)


def test_stage1_source_pin_and_catalog_load() -> None:
    catalog = _catalog()

    assert catalog.metadata["source_commit"] == (
        "50cdcfc2c45d0631591310435835c0180c105489"
    )
    assert catalog.metadata["xscache_commit"] == (
        "dfd3edcf42b772e2a21178579b93bafc956f99b8"
    )
    # The Stage 1 baseline remains loadable as later stages extend the catalog.
    assert len(catalog.event_types) == 138
    assert catalog.resolve("Arch.Load").visibility is Visibility.ARCHITECTURAL
    assert catalog.resolve("TL.A").visibility is Visibility.PUBLIC
    assert catalog.resolve("CHI.RXSNP").visibility is Visibility.PUBLIC
    assert catalog.resolve("L1.MSHRAllocate").visibility is Visibility.INTERNAL


def test_stage1_composition_is_connected_but_behavior_free() -> None:
    _, manifest, composed = _composition()

    assert len(composed.modules) == 15
    assert len(manifest.connections) == 73
    assert composed.completion.slots == []
    assert composed.completion.state_variables == []
    assert composed.completion.transformations == []
    assert composed.completion.constraints == []
    assert manifest.metadata["encapsulation"] == "strict"


def test_stage1_ports_never_expose_private_event_types() -> None:
    catalog, _, composed = _composition()

    for loaded in composed.modules:
        for port in loaded.spec.ports:
            assert catalog.resolve(port.event_type).visibility is not Visibility.INTERNAL
        for event_type in loaded.spec.internal_events:
            assert catalog.resolve(event_type).visibility is Visibility.INTERNAL


def test_stage1_canonical_interface_inventory_matches_composition() -> None:
    _, manifest, composed = _composition()
    expected = {
        "schema_version": "umcm.interfaces.v0.15.0",
        "composition": manifest.name,
        "policy": "ports-only-public-surface",
        "modules": [
            contract.to_dict() for contract in build_interface_contracts(composed)
        ],
    }

    assert load_data(XIANGSHAN / "hierarchy" / "interfaces.yaml") == expected
