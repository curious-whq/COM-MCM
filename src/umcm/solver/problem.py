"""Instantiation of role-based transformations over a bounded event universe."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Iterator, Mapping

from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import (
    Binary,
    Symbol,
    EventField,
    Expr,
    Literal,
    conjunction,
    disjunction,
    substitute_event_ids,
)
from umcm.ir.sort import BOOL, INT
from umcm.ir.trace import Trace
from umcm.ir.transformation import EventRole, Transformation


@dataclass(frozen=True, slots=True)
class NamedConstraint:
    name: str
    expression: Expr
    origin: str


@dataclass(frozen=True, slots=True)
class StateRequirementInstance:
    name: str
    state: str
    cycle: Expr
    activation: Expr
    op: str
    expected: Expr
    origin: str


@dataclass(frozen=True, slots=True)
class StateUpdateInstance:
    name: str
    state: str
    cycle: Expr
    activation: Expr
    value: Expr
    origin: str


@dataclass(slots=True)
class BoundedProblem:
    catalog: EventCatalog
    source_trace: Trace
    spec: CompletionSpec
    events: list[EventInstance]
    constraints: list[NamedConstraint]
    state_requirements: list[StateRequirementInstance]
    state_updates: list[StateUpdateInstance]
    slot_ids: tuple[str, ...]

    @property
    def event_map(self) -> dict[str, EventInstance]:
        return {event.id: event for event in self.events}


@dataclass(frozen=True, slots=True)
class _TransformationInstantiation:
    constraints: tuple[NamedConstraint, ...]
    requirements: tuple[StateRequirementInstance, ...]
    updates: tuple[StateUpdateInstance, ...]


def build_problem(
    catalog: EventCatalog,
    trace: Trace,
    spec: CompletionSpec,
) -> BoundedProblem:
    trace.validate(catalog)
    spec.validate(catalog, trace)

    observed_events = [
        _materialize_partial_event(catalog, event) for event in trace.events
    ]
    slot_events = [slot.materialize(catalog) for slot in spec.slots]
    events = [*observed_events, *slot_events]
    constraints: list[NamedConstraint] = []
    state_requirements: list[StateRequirementInstance] = []
    state_updates: list[StateUpdateInstance] = []
    constraints.extend(
        NamedConstraint(
            name=f"trace.constraint.{index}",
            expression=expression,
            origin="trace",
        )
        for index, expression in enumerate(trace.constraints)
    )
    constraints.extend(
        NamedConstraint(
            name=f"completion.constraint.{index}",
            expression=expression,
            origin="completion",
        )
        for index, expression in enumerate(spec.constraints)
    )

    for event in events:
        if event.cycle is None:
            continue
        occurs = EventField(event.id, "occurs", BOOL)
        cycle = EventField(event.id, "cycle", INT)
        in_range = conjunction(
            (
                Binary("le", Literal(0, INT), cycle),
                Binary("le", cycle, Literal(spec.horizon, INT)),
            )
        )
        constraints.append(
            NamedConstraint(
                name=f"cycle.bound.{event.id}",
                expression=Binary("implies", occurs, in_range),
                origin="completion",
            )
        )

    for transformation in spec.transformations:
        instantiated = _instantiate_transformation(transformation, events)
        constraints.extend(instantiated.constraints)
        state_requirements.extend(instantiated.requirements)
        state_updates.extend(instantiated.updates)

    return BoundedProblem(
        catalog=catalog,
        source_trace=trace,
        spec=spec,
        events=events,
        constraints=constraints,
        state_requirements=state_requirements,
        state_updates=state_updates,
        slot_ids=tuple(slot.id for slot in spec.slots),
    )


def _instantiate_transformation(
    transformation: Transformation,
    events: list[EventInstance],
) -> _TransformationInstantiation:
    by_type: dict[str, list[EventInstance]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

    input_bindings = list(_role_bindings(transformation.inputs, by_type))
    constraints: list[NamedConstraint] = []
    requirements: list[StateRequirementInstance] = []
    updates: list[StateUpdateInstance] = []

    for index, input_binding in enumerate(input_bindings):
        input_ids = tuple(input_binding.values())
        if len(input_ids) != len(set(input_ids)):
            continue

        role_mapping = dict(input_binding)
        input_occurs = (
            EventField(event_id, "occurs", BOOL)
            for event_id in input_binding.values()
        )
        antecedent = conjunction(
            (
                *input_occurs,
                substitute_event_ids(transformation.when, role_mapping),
            )
        )

        alternatives: list[Expr] = []
        for output_binding in _role_bindings(transformation.outputs, by_type):
            all_ids = (*input_binding.values(), *output_binding.values())
            if len(all_ids) != len(set(all_ids)):
                continue
            complete_mapping = {**input_binding, **output_binding}
            output_occurs = (
                EventField(event_id, "occurs", BOOL)
                for event_id in output_binding.values()
            )
            ensured = (
                substitute_event_ids(expression, complete_mapping)
                for expression in transformation.ensure
            )
            alternatives.append(conjunction((*output_occurs, *ensured)))

        consequent = disjunction(alternatives)
        bound_inputs = ",".join(input_ids) if input_ids else "global"
        instance_name = (
            f"transformation.{transformation.name}.{index}.{bound_inputs}"
        )
        constraints.append(
            NamedConstraint(
                name=instance_name,
                expression=Binary("implies", antecedent, consequent),
                origin=f"transformation:{transformation.name}",
            )
        )

        if transformation.is_stateful:
            for effect_index, requirement in enumerate(
                transformation.state_requirements
            ):
                anchor_id = input_binding[requirement.at]
                requirements.append(
                    StateRequirementInstance(
                        name=f"{instance_name}.requirement.{effect_index}",
                        state=requirement.state,
                        cycle=EventField(anchor_id, "cycle", INT),
                        activation=antecedent,
                        op=requirement.op,
                        expected=substitute_event_ids(
                            requirement.value, role_mapping
                        ),
                        origin=f"transformation:{transformation.name}",
                    )
                )
            for effect_index, update in enumerate(transformation.state_updates):
                anchor_id = input_binding[update.at]
                updates.append(
                    StateUpdateInstance(
                        name=f"{instance_name}.update.{effect_index}",
                        state=update.state,
                        cycle=EventField(anchor_id, "cycle", INT),
                        activation=antecedent,
                        value=substitute_event_ids(update.value, role_mapping),
                        origin=f"transformation:{transformation.name}",
                    )
                )

    return _TransformationInstantiation(
        constraints=tuple(constraints),
        requirements=tuple(requirements),
        updates=tuple(updates),
    )


def _role_bindings(
    roles: tuple[EventRole, ...],
    by_type: Mapping[str, list[EventInstance]],
) -> Iterator[dict[str, str]]:
    if not roles:
        yield {}
        return
    candidate_lists = [by_type.get(role.event_type, []) for role in roles]
    if any(not candidates for candidates in candidate_lists):
        return
    for chosen in product(*candidate_lists):
        yield {role.name: event.id for role, event in zip(roles, chosen, strict=True)}


def _materialize_partial_event(
    catalog: EventCatalog,
    event: EventInstance,
) -> EventInstance:
    """Fill missing required fields of an observed partial event with symbols."""

    event_type = catalog.resolve(event.event_type)
    fields = deepcopy(event.fields)
    for field_spec in event_type.fields:
        if field_spec.required and field_spec.name not in fields:
            fields[field_spec.name] = Symbol(
                f"trace::{event.id}::field::{field_spec.name}",
                field_spec.sort,
            )
    return EventInstance(
        id=event.id,
        event_type=event.event_type,
        fields=fields,
        cycle=deepcopy(event.cycle),
        occurs=deepcopy(event.occurs),
        annotations=deepcopy(event.annotations),
    )
