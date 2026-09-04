"""Composition engine for independently loadable operational modules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from umcm.composition.model import (
    CompositionSpec,
    ConnectionMode,
    ConnectionSpec,
    ModulePort,
    ModuleSpec,
    PortDirection,
)
from umcm.errors import CompositionError
from umcm.composition.parameterization import (
    expand_module_repeats,
    render_template,
    resolve_trace_roles,
    template_placeholders,
)
from umcm.ir.completion import CompletionSpec, EventSlot
from umcm.ir.event import EventCatalog
from umcm.ir.expression import Binary, EventField, iter_event_fields
from umcm.ir.sort import INT
from umcm.ir.transformation import EventRole, Transformation
from umcm.ir.trace import Trace
from umcm.serialization import load_data


@dataclass(frozen=True, slots=True)
class LoadedModule:
    reference_name: str
    path: str
    spec: ModuleSpec


@dataclass(slots=True)
class CompositionResult:
    """Materialized completion model and a diagnostic composition manifest."""

    spec: CompositionSpec
    modules: tuple[LoadedModule, ...]
    completion: CompletionSpec
    generated_transformations: tuple[str, ...]
    resolved_roles: Mapping[str, Any]

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "composition": self.spec.name,
            "modules": [
                {
                    "name": item.reference_name,
                    "declared_name": item.spec.name,
                    "path": item.path,
                    "ports": len(item.spec.ports),
                    "internal_event_types": len(item.spec.internal_events),
                    "slots": len(item.spec.slots),
                    "state_variables": len(item.spec.state_variables),
                    "transformations": len(item.spec.transformations),
                    "constraints": len(item.spec.constraints),
                }
                for item in self.modules
            ],
            "connections": [connection.to_dict() for connection in self.spec.connections],
            "generated_transformations": list(self.generated_transformations),
            "resolved_roles": _copy_role_context(self.resolved_roles),
            "totals": {
                "slots": len(self.completion.slots),
                "state_variables": len(self.completion.state_variables),
                "transformations": len(self.completion.transformations),
                "constraints": len(self.completion.constraints),
                "horizon": self.completion.horizon,
            },
        }


def compose_modules(
    catalog: EventCatalog,
    composition: CompositionSpec,
    trace: Trace | None = None,
) -> CompositionResult:
    """Load, instantiate, validate, wire, and merge all modules.

    A trace is only required when the composition declares trace roles.  Old
    concrete v0.9 compositions therefore remain source-compatible.
    """

    if composition.roles and trace is None:
        raise CompositionError(
            f"composition {composition.name!r} declares trace roles; provide "
            "the partial trace used for finite instantiation"
        )
    resolved_roles = dict(composition.parameters)
    if composition.roles:
        resolved_roles = resolve_trace_roles(
            trace,
            composition.roles,
            initial_context=resolved_roles,
        )

    loaded: list[LoadedModule] = []
    modules: dict[str, ModuleSpec] = {}
    for reference in composition.modules:
        path = composition.resolve_module_path(reference).resolve()
        if not path.is_file():
            raise CompositionError(
                f"module {reference.name!r} file does not exist: {path}"
            )
        raw_module = load_data(path)
        if isinstance(raw_module, Mapping) and raw_module.get("repeat"):
            if not resolved_roles:
                raise CompositionError(
                    f"module {reference.name!r} declares repeat expansion but "
                    "no trace roles were resolved"
                )
            raw_module = expand_module_repeats(raw_module, resolved_roles)
        placeholders = template_placeholders(raw_module)
        if placeholders:
            if not resolved_roles:
                raise CompositionError(
                    f"module {reference.name!r} contains template parameters "
                    "but no trace roles were resolved: "
                    + ", ".join(sorted(placeholders))
                )
            raw_module = render_template(raw_module, resolved_roles)
            unresolved = template_placeholders(raw_module)
            if unresolved:
                raise CompositionError(
                    f"module {reference.name!r} still contains unresolved "
                    "template parameters: " + ", ".join(sorted(unresolved))
                )
        module = ModuleSpec.from_dict(raw_module)
        if module.name != reference.name:
            raise CompositionError(
                f"module reference {reference.name!r} loads module "
                f"named {module.name!r}: {path}"
            )
        module.validate(catalog)
        modules[reference.name] = module
        loaded.append(
            LoadedModule(
                reference_name=reference.name,
                path=str(path),
                spec=module,
            )
        )

    _validate_connections(modules, composition.connections, catalog)

    slots: list[EventSlot] = []
    states = []
    transformations: list[Transformation] = []
    constraints = []
    slot_owner: dict[str, str] = {}
    state_owner: dict[str, str] = {}
    transformation_owner: dict[str, str] = {}

    for loaded_module in loaded:
        module_name = loaded_module.reference_name
        module = loaded_module.spec
        for slot in module.slots:
            previous = slot_owner.get(slot.id)
            if previous is not None:
                raise CompositionError(
                    f"slot {slot.id!r} is declared by both {previous!r} "
                    f"and {module_name!r}"
                )
            slot_owner[slot.id] = module_name
            annotations = dict(slot.annotations)
            annotations.setdefault("module_spec", module_name)
            interface_ports = tuple(
                sorted(
                    port.name
                    for port in module.ports
                    if port.event_type == slot.event_type
                )
            )
            annotations.setdefault(
                "module_visibility", "public" if interface_ports else "private"
            )
            if interface_ports:
                annotations.setdefault("interface_ports", list(interface_ports))
            slots.append(replace(slot, annotations=annotations))

        for state in module.state_variables:
            previous = state_owner.get(state.name)
            if previous is not None:
                raise CompositionError(
                    f"state {state.name!r} is declared by both {previous!r} "
                    f"and {module_name!r}"
                )
            state_owner[state.name] = module_name
            states.append(state)

        for transformation in module.transformations:
            previous = transformation_owner.get(transformation.name)
            if previous is not None:
                raise CompositionError(
                    f"transformation {transformation.name!r} is declared by "
                    f"both {previous!r} and {module_name!r}"
                )
            transformation_owner[transformation.name] = module_name
            tags = tuple(dict.fromkeys((*transformation.tags, f"module:{module_name}")))
            transformations.append(replace(transformation, tags=tags))

        constraints.extend(module.constraints)

    generated: list[str] = []
    for connection in composition.connections:
        if connection.mode is not ConnectionMode.EVENT_MAP:
            continue
        generated_transformation = _mapped_connection_transformation(
            modules, connection, catalog
        )
        if generated_transformation.name in transformation_owner:
            raise CompositionError(
                f"generated connection transformation collides with "
                f"{generated_transformation.name!r}"
            )
        transformation_owner[generated_transformation.name] = (
            f"connection:{connection.name}"
        )
        transformations.append(generated_transformation)
        generated.append(generated_transformation.name)

    if str(composition.metadata.get("encapsulation", "legacy")) == "strict":
        _validate_composition_constraint_encapsulation(
            composition.constraints, slots
        )
    constraints.extend(composition.constraints)
    metadata = dict(composition.metadata)
    metadata["composition"] = {
        "name": composition.name,
        "resolved_roles": _copy_role_context(resolved_roles),
        "modules": [item.reference_name for item in loaded],
        "connections": [
            {
                "name": item.name,
                "mode": item.mode.value,
                "source": item.source.qualified_name,
                "target": item.target.qualified_name,
            }
            for item in composition.connections
        ],
        "generated_transformations": generated,
    }
    metadata["hierarchy"] = {
        "policy": "ports-only-public-surface",
        "modules": {
            item.reference_name: _module_boundary_metadata(item.spec)
            for item in loaded
        },
    }

    completion = CompletionSpec(
        slots=slots,
        transformations=transformations,
        state_variables=states,
        constraints=constraints,
        horizon=composition.horizon,
        metadata=metadata,
        schema_version="umcm.completion.v0.15.0",
    )
    return CompositionResult(
        spec=composition,
        modules=tuple(loaded),
        completion=completion,
        generated_transformations=tuple(generated),
        resolved_roles=resolved_roles,
    )


def _module_boundary_metadata(module: ModuleSpec) -> dict[str, Any]:
    public_types = {port.event_type for port in module.ports}
    private_slots = [slot for slot in module.slots if slot.event_type not in public_types]
    return {
        "public_ports": [port.to_dict() for port in module.ports],
        "public_event_types": sorted(public_types),
        "private_slot_ids": sorted(slot.id for slot in private_slots),
        "private_event_types": sorted(
            set(module.internal_events) | {slot.event_type for slot in private_slots}
        ),
        "private_state_names": sorted(state.name for state in module.state_variables),
        "private_transformation_names": sorted(
            transformation.name for transformation in module.transformations
        ),
    }


def _validate_composition_constraint_encapsulation(
    constraints, slots: list[EventSlot]
) -> None:
    """Prevent top-level constraints from reaching through child boundaries.

    A composition may constrain external/root events and public module port
    events, but may not name a child-private completion slot.  Local module
    constraints remain free to use that module's implementation events.
    """

    private = {
        slot.id: str(slot.annotations.get("module_spec", "<unknown>"))
        for slot in slots
        if slot.annotations.get("module_visibility") == "private"
    }
    for constraint in constraints:
        for reference in iter_event_fields(constraint):
            owner = private.get(reference.event_id)
            if owner is not None:
                raise CompositionError(
                    "composition constraint reaches through module boundary: "
                    f"{reference.event_id!r} is private to module {owner!r}"
                )


def _copy_role_context(context: Mapping[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for name, value in context.items():
        if isinstance(value, Mapping):
            copied[name] = dict(value)
        elif isinstance(value, list):
            copied[name] = [dict(item) if isinstance(item, Mapping) else item for item in value]
        else:
            copied[name] = value
    return copied


def _validate_connections(
    modules: dict[str, ModuleSpec],
    connections: Iterable[ConnectionSpec],
    catalog: EventCatalog,
) -> None:
    connected_endpoints: dict[tuple[str, str], list[str]] = {}
    target_endpoints: set[tuple[str, str]] = set()

    for connection in connections:
        source_port = _resolve_port(
            modules,
            connection.source.module,
            connection.source.port,
        )
        target_port = _resolve_port(
            modules,
            connection.target.module,
            connection.target.port,
        )
        if source_port.direction is not PortDirection.OUTPUT:
            raise CompositionError(
                f"connection {connection.name!r} source "
                f"{connection.source.qualified_name} is not an output port"
            )
        if target_port.direction is not PortDirection.INPUT:
            raise CompositionError(
                f"connection {connection.name!r} target "
                f"{connection.target.qualified_name} is not an input port"
            )
        target_key = (connection.target.module, connection.target.port)
        if target_key in target_endpoints:
            raise CompositionError(
                f"input port {connection.target.qualified_name!r} has more than "
                "one incoming connection"
            )
        target_endpoints.add(target_key)

        connected_endpoints.setdefault(
            (connection.source.module, connection.source.port), []
        ).append(connection.name)
        connected_endpoints.setdefault(target_key, []).append(connection.name)

        source_type = catalog.resolve(source_port.event_type)
        target_type = catalog.resolve(target_port.event_type)
        if connection.mode is ConnectionMode.SHARED_EVENT:
            if source_type.name != target_type.name:
                raise CompositionError(
                    f"shared_event connection {connection.name!r} requires "
                    f"the same event type, got {source_type.name!r} and "
                    f"{target_type.name!r}"
                )
        else:
            _validate_field_map(connection, source_type, target_type)

    for module_name, module in modules.items():
        for port in module.ports:
            if not port.required_connection:
                continue
            key = (module_name, port.name)
            if key not in connected_endpoints:
                raise CompositionError(
                    f"required port {module_name}.{port.name} is unconnected"
                )


def _resolve_port(
    modules: dict[str, ModuleSpec],
    module_name: str,
    port_name: str,
) -> ModulePort:
    try:
        module = modules[module_name]
    except KeyError as exc:
        raise CompositionError(f"unknown module in connection: {module_name}") from exc
    try:
        return module.port_map[port_name]
    except KeyError as exc:
        raise CompositionError(
            f"module {module_name!r} has no port {port_name!r}"
        ) from exc


def _validate_field_map(connection, source_type, target_type) -> None:
    mapping = dict(connection.field_map)
    if not mapping:
        common = set(source_type.field_map) & set(target_type.field_map)
        mapping = {name: name for name in common}
    for target_field, source_field in mapping.items():
        try:
            target_sort = target_type.field_map[target_field].sort
        except KeyError as exc:
            raise CompositionError(
                f"connection {connection.name!r} maps unknown target field "
                f"{target_field!r}"
            ) from exc
        try:
            source_sort = source_type.field_map[source_field].sort
        except KeyError as exc:
            raise CompositionError(
                f"connection {connection.name!r} maps unknown source field "
                f"{source_field!r}"
            ) from exc
        if not target_sort.compatible_with(source_sort):
            raise CompositionError(
                f"connection {connection.name!r} field mapping "
                f"{source_field!r}->{target_field!r} has incompatible sorts "
                f"{source_sort} and {target_sort}"
            )


def _mapped_connection_transformation(
    modules: dict[str, ModuleSpec],
    connection: ConnectionSpec,
    catalog: EventCatalog,
) -> Transformation:
    source_port = _resolve_port(
        modules, connection.source.module, connection.source.port
    )
    target_port = _resolve_port(
        modules, connection.target.module, connection.target.port
    )
    source_type = catalog.resolve(source_port.event_type)
    target_type = catalog.resolve(target_port.event_type)
    mapping = dict(connection.field_map)
    if not mapping:
        common = set(source_type.field_map) & set(target_type.field_map)
        mapping = {name: name for name in sorted(common)}

    ensure = []
    if connection.same_cycle:
        ensure.append(
            Binary(
                "eq",
                EventField("target", "cycle", INT),
                EventField("source", "cycle", INT),
            )
        )
    for target_field, source_field in sorted(mapping.items()):
        target_sort = target_type.field_map[target_field].sort
        source_sort = source_type.field_map[source_field].sort
        ensure.append(
            Binary(
                "eq",
                EventField("target", target_field, target_sort),
                EventField("source", source_field, source_sort),
            )
        )

    return Transformation(
        name=f"connection.{connection.name}",
        inputs=(EventRole("source", source_port.event_type),),
        outputs=(EventRole("target", target_port.event_type),),
        ensure=tuple(ensure),
        exact=connection.exact,
        description=(
            connection.description
            or f"Generated event mapping for {connection.name}."
        ),
        tags=(
            "connection",
            f"source:{connection.source.qualified_name}",
            f"target:{connection.target.qualified_name}",
        ),
    )
