"""Module-interface projection for hierarchical µMCM traces.

v0.15 makes hierarchy structural rather than bug-specific: module state and
implementation events stay private, while declared ports form the only public
surface.  The projection implemented here simply hides private implementation
events.  It does *not* synthesize witness-specific summary events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umcm.composition.engine import CompositionResult
from umcm.ir.event import EventInstance
from umcm.ir.expression import iter_event_fields
from umcm.ir.trace import Trace


@dataclass(frozen=True, slots=True)
class PortContract:
    name: str
    direction: str
    event_type: str
    required_connection: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "event_type": self.event_type,
            "required_connection": self.required_connection,
        }


@dataclass(frozen=True, slots=True)
class ModuleInterfaceContract:
    """Public surface plus hidden implementation inventory for one module."""

    module: str
    ports: tuple[PortContract, ...]
    public_event_types: tuple[str, ...]
    private_slot_ids: tuple[str, ...]
    private_event_types: tuple[str, ...]
    private_state_names: tuple[str, ...]
    private_transformation_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "ports": [item.to_dict() for item in self.ports],
            "public_event_types": list(self.public_event_types),
            "private_slot_ids": list(self.private_slot_ids),
            "private_event_types": list(self.private_event_types),
            "private_state_names": list(self.private_state_names),
            "private_transformation_names": list(self.private_transformation_names),
        }


@dataclass(frozen=True, slots=True)
class InterfaceProjectionCertificate:
    composition: str
    source_event_count: int
    projected_event_count: int
    retained_event_ids: tuple[str, ...]
    hidden_event_ids: tuple[str, ...]
    hidden_by_module: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition": self.composition,
            "source_event_count": self.source_event_count,
            "projected_event_count": self.projected_event_count,
            "retained_event_ids": list(self.retained_event_ids),
            "hidden_event_ids": list(self.hidden_event_ids),
            "hidden_by_module": {
                name: list(ids) for name, ids in sorted(self.hidden_by_module.items())
            },
        }


@dataclass(frozen=True, slots=True)
class InterfaceProjectionResult:
    trace: Trace
    certificate: InterfaceProjectionCertificate


def build_interface_contracts(
    composition: CompositionResult,
) -> tuple[ModuleInterfaceContract, ...]:
    """Return the public/private inventory implied by module declarations."""

    contracts: list[ModuleInterfaceContract] = []
    for loaded in composition.modules:
        module = loaded.spec
        public_types = {port.event_type for port in module.ports}
        private_slots = [
            slot for slot in module.slots if slot.event_type not in public_types
        ]
        contracts.append(
            ModuleInterfaceContract(
                module=loaded.reference_name,
                ports=tuple(
                    PortContract(
                        name=port.name,
                        direction=port.direction.value,
                        event_type=port.event_type,
                        required_connection=port.required_connection,
                    )
                    for port in module.ports
                ),
                public_event_types=tuple(sorted(public_types)),
                private_slot_ids=tuple(sorted(slot.id for slot in private_slots)),
                private_event_types=tuple(
                    sorted(set(module.internal_events) | {slot.event_type for slot in private_slots})
                ),
                private_state_names=tuple(
                    sorted(state.name for state in module.state_variables)
                ),
                private_transformation_names=tuple(
                    sorted(item.name for item in module.transformations)
                ),
            )
        )
    return tuple(contracts)


def project_interface_trace(
    trace: Trace,
    composition: CompositionResult,
) -> InterfaceProjectionResult:
    """Hide module-private events while preserving public boundary actions.

    Unowned events are external observations (for example architectural
    operations supplied by the query trace) and are retained.  Events emitted
    from completion slots carry ``module_visibility`` annotations inserted by
    the composition engine.  No new summary event is invented here.
    """

    contracts = build_interface_contracts(composition)
    public_types = {
        event_type
        for contract in contracts
        for event_type in contract.public_event_types
    }
    private_type_owners: dict[str, set[str]] = {}
    for contract in contracts:
        for event_type in contract.private_event_types:
            if event_type not in public_types:
                private_type_owners.setdefault(event_type, set()).add(contract.module)

    visibility_by_id: dict[str, tuple[str, str | None]] = {}
    for slot in composition.completion.slots:
        owner = slot.annotations.get("module_spec")
        visibility = str(slot.annotations.get("module_visibility", "private"))
        visibility_by_id[slot.id] = (
            visibility,
            None if owner is None else str(owner),
        )

    retained: list[EventInstance] = []
    retained_ids: set[str] = set()
    hidden: list[str] = []
    hidden_by_module: dict[str, list[str]] = {}

    for event in trace.events:
        visibility: str | None = None
        owner: str | None = None
        if event.id in visibility_by_id:
            visibility, owner = visibility_by_id[event.id]
        else:
            raw_visibility = event.annotations.get("module_visibility")
            raw_owner = event.annotations.get("module_spec")
            if raw_visibility is not None:
                visibility = str(raw_visibility)
            if raw_owner is not None:
                owner = str(raw_owner)

        # Root traces may contain diagnostic observations of child-private
        # events (for example a TLB miss supplied while debugging a witness).
        # Classify those by event type so interface projection still hides
        # them.  Truly external/architectural events are retained.
        if owner is None and event.event_type in private_type_owners:
            owners = sorted(private_type_owners[event.event_type])
            owner = owners[0] if len(owners) == 1 else "+".join(owners)
            visibility = "private"

        if owner is None or visibility == "public":
            retained.append(_copy_event(event))
            retained_ids.add(event.id)
            continue

        hidden.append(event.id)
        hidden_by_module.setdefault(owner, []).append(event.id)

    preserved_constraints = []
    dropped_constraints = 0
    for constraint in trace.constraints:
        references = {item.event_id for item in iter_event_fields(constraint)}
        if references <= retained_ids:
            preserved_constraints.append(constraint)
        else:
            dropped_constraints += 1

    metadata = dict(trace.metadata)
    metadata["interface_projection"] = {
        "composition": composition.spec.name,
        "source_event_count": len(trace.events),
        "projected_event_count": len(retained),
        "hidden_event_count": len(hidden),
        "dropped_constraint_count": dropped_constraints,
    }
    projected = Trace(
        events=retained,
        constraints=preserved_constraints,
        partial=trace.partial,
        metadata=metadata,
        schema_version=trace.schema_version,
    )
    certificate = InterfaceProjectionCertificate(
        composition=composition.spec.name,
        source_event_count=len(trace.events),
        projected_event_count=len(retained),
        retained_event_ids=tuple(event.id for event in retained),
        hidden_event_ids=tuple(hidden),
        hidden_by_module={
            name: tuple(ids) for name, ids in sorted(hidden_by_module.items())
        },
    )
    return InterfaceProjectionResult(projected, certificate)


def _copy_event(event: EventInstance) -> EventInstance:
    return EventInstance(
        id=event.id,
        event_type=event.event_type,
        fields=dict(event.fields),
        cycle=event.cycle,
        occurs=event.occurs,
        annotations=dict(event.annotations),
    )
