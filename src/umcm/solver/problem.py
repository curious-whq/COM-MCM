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


@dataclass(frozen=True, slots=True)
class GuardPredicateInstance:
    state: str
    cycle: Expr
    op: str
    expected: Expr


@dataclass(frozen=True, slots=True)
class GuardedForwardInstance:
    name: str
    antecedent: Expr
    predicates: tuple[GuardPredicateInstance, ...]
    consequent: Expr
    origin: str


@dataclass(frozen=True, slots=True)
class GuardedSupportCandidate:
    expression: Expr
    predicates: tuple[GuardPredicateInstance, ...]


@dataclass(frozen=True, slots=True)
class GuardedSupportInstance:
    name: str
    antecedent: Expr
    supports: tuple[GuardedSupportCandidate, ...]
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
    guarded_forwards: list[GuardedForwardInstance]
    guarded_supports: list[GuardedSupportInstance]
    slot_ids: tuple[str, ...]

    @property
    def event_map(self) -> dict[str, EventInstance]:
        return {event.id: event for event in self.events}


@dataclass(frozen=True, slots=True)
class _TransformationInstantiation:
    constraints: tuple[NamedConstraint, ...]
    requirements: tuple[StateRequirementInstance, ...]
    updates: tuple[StateUpdateInstance, ...]
    guarded_forwards: tuple[GuardedForwardInstance, ...] = ()
    guarded_supports: tuple[GuardedSupportInstance, ...] = ()


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
    guarded_forwards: list[GuardedForwardInstance] = []
    guarded_supports: list[GuardedSupportInstance] = []
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
        guarded_forwards.extend(instantiated.guarded_forwards)
        guarded_supports.extend(instantiated.guarded_supports)

    return BoundedProblem(
        catalog=catalog,
        source_trace=trace,
        spec=spec,
        events=events,
        constraints=constraints,
        state_requirements=state_requirements,
        state_updates=state_updates,
        guarded_forwards=guarded_forwards,
        guarded_supports=guarded_supports,
        slot_ids=tuple(slot.id for slot in spec.slots),
    )


def _instantiate_transformation(
    transformation: Transformation,
    events: list[EventInstance],
) -> _TransformationInstantiation:
    """Instantiate one operational transition over the bounded event universe.

    Normal transformations add the forward rule ``inputs && guard -> outputs``.
    An ``exact`` transformation additionally requires every occurring output to
    be justified by some matching input binding.  This is a general derived-
    event facility; ready/valid/fire does not have a separate semantics layer.

    State effects are attached to complete transition instances.  Therefore a
    rule may read pre-state, emit output events, and update post-state as one
    operational transition.
    """

    by_type: dict[str, list[EventInstance]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

    input_bindings = list(_role_bindings(transformation.inputs, by_type))
    output_bindings = list(_role_bindings(transformation.outputs, by_type))
    constraints: list[NamedConstraint] = []
    requirements: list[StateRequirementInstance] = []
    updates: list[StateUpdateInstance] = []
    guarded_forwards: list[GuardedForwardInstance] = []
    guarded_supports: list[GuardedSupportInstance] = []

    for input_index, input_binding in enumerate(input_bindings):
        input_ids = tuple(input_binding.values())
        if len(input_ids) != len(set(input_ids)):
            continue

        input_mapping = dict(input_binding)
        input_occurs = tuple(
            EventField(event_id, "occurs", BOOL)
            for event_id in input_binding.values()
        )
        guard = substitute_event_ids(transformation.when, input_mapping)
        antecedent = conjunction((*input_occurs, guard))

        alternatives: list[Expr] = []
        complete_instances: list[tuple[dict[str, str], Expr, str]] = []
        for output_index, output_binding in enumerate(output_bindings):
            all_ids = (*input_binding.values(), *output_binding.values())
            if len(all_ids) != len(set(all_ids)):
                continue
            complete_mapping = {**input_binding, **output_binding}
            output_occurs = tuple(
                EventField(event_id, "occurs", BOOL)
                for event_id in output_binding.values()
            )
            output_guard = substitute_event_ids(
                transformation.output_when, complete_mapping
            )
            ensured = tuple(
                substitute_event_ids(expression, complete_mapping)
                for expression in transformation.ensure
            )
            output_alternative = conjunction(
                (*output_occurs, output_guard, *ensured)
            )
            alternatives.append(output_alternative)
            activation = conjunction(
                (*input_occurs, guard, *output_occurs, output_guard, *ensured)
            )
            bound_outputs = (
                ",".join(output_binding.values())
                if output_binding
                else "no-output"
            )
            complete_instances.append(
                (complete_mapping, activation, f"{output_index}.{bound_outputs}")
            )

        bound_inputs = ",".join(input_ids) if input_ids else "global"
        forward_name = (
            f"transformation.{transformation.name}.forward."
            f"{input_index}.{bound_inputs}"
        )
        if transformation.state_mode == "guard":
            input_names = set(input_mapping)
            if all(
                requirement.at in input_names
                for requirement in transformation.state_requirements
            ):
                predicates = tuple(
                    GuardPredicateInstance(
                        state=requirement.state,
                        cycle=EventField(input_mapping[requirement.at], "cycle", INT),
                        op=requirement.op,
                        expected=substitute_event_ids(requirement.value, input_mapping),
                    )
                    for requirement in transformation.state_requirements
                )
                guarded_forwards.append(
                    GuardedForwardInstance(
                        name=forward_name,
                        antecedent=antecedent,
                        predicates=predicates,
                        consequent=disjunction(alternatives),
                        origin=f"transformation:{transformation.name}",
                    )
                )
            # If a guard is anchored to an output candidate, forward generation
            # is not forced here.  For exact transformations the support rule
            # below still proves that any chosen output has a matching input and
            # that all state guards hold at the candidate output cycle.
        else:
            constraints.append(
                NamedConstraint(
                    name=forward_name,
                    expression=Binary(
                        "implies", antecedent, disjunction(alternatives)
                    ),
                    origin=f"transformation:{transformation.name}",
                )
            )

            if transformation.is_stateful:
                for complete_mapping, activation, instance_suffix in complete_instances:
                    effect_prefix = f"{forward_name}.instance.{instance_suffix}"
                    for effect_index, requirement in enumerate(
                        transformation.state_requirements
                    ):
                        anchor_id = complete_mapping[requirement.at]
                        requirements.append(
                            StateRequirementInstance(
                                name=(
                                    f"{effect_prefix}.requirement.{effect_index}"
                                ),
                                state=requirement.state,
                                cycle=EventField(anchor_id, "cycle", INT),
                                activation=activation,
                                op=requirement.op,
                                expected=substitute_event_ids(
                                    requirement.value, complete_mapping
                                ),
                                origin=f"transformation:{transformation.name}",
                            )
                        )
                    for effect_index, update in enumerate(
                        transformation.state_updates
                    ):
                        anchor_id = complete_mapping[update.at]
                        updates.append(
                            StateUpdateInstance(
                                name=f"{effect_prefix}.update.{effect_index}",
                                state=update.state,
                                cycle=EventField(anchor_id, "cycle", INT),
                                activation=activation,
                                value=substitute_event_ids(
                                    update.value, complete_mapping
                                ),
                                origin=f"transformation:{transformation.name}",
                            )
                        )

    if transformation.exact:
        for output_index, output_binding in enumerate(output_bindings):
            output_ids = tuple(output_binding.values())
            if len(output_ids) != len(set(output_ids)):
                continue
            output_occurs = conjunction(
                EventField(event_id, "occurs", BOOL)
                for event_id in output_binding.values()
            )
            output_scope = substitute_event_ids(
                transformation.output_when, output_binding
            )
            supports: list[Expr] = []
            for input_binding in input_bindings:
                all_ids = (*input_binding.values(), *output_binding.values())
                if len(all_ids) != len(set(all_ids)):
                    continue
                complete_mapping = {**input_binding, **output_binding}
                input_occurs = tuple(
                    EventField(event_id, "occurs", BOOL)
                    for event_id in input_binding.values()
                )
                guarded = substitute_event_ids(
                    transformation.when, complete_mapping
                )
                ensured = tuple(
                    substitute_event_ids(expression, complete_mapping)
                    for expression in transformation.ensure
                )
                supports.append(
                    conjunction((*input_occurs, guarded, *ensured))
                )

            bound_outputs = ",".join(output_ids) if output_ids else "global"
            support_name = (
                f"transformation.{transformation.name}.support."
                f"{output_index}.{bound_outputs}"
            )
            if transformation.state_mode == "guard":
                guarded_candidates: list[GuardedSupportCandidate] = []
                for input_binding in input_bindings:
                    all_ids = (*input_binding.values(), *output_binding.values())
                    if len(all_ids) != len(set(all_ids)):
                        continue
                    complete_mapping = {**input_binding, **output_binding}
                    input_occurs = tuple(
                        EventField(event_id, "occurs", BOOL)
                        for event_id in input_binding.values()
                    )
                    guarded = substitute_event_ids(
                        transformation.when, complete_mapping
                    )
                    ensured = tuple(
                        substitute_event_ids(expression, complete_mapping)
                        for expression in transformation.ensure
                    )
                    expression = conjunction((*input_occurs, guarded, *ensured))
                    predicates = tuple(
                        GuardPredicateInstance(
                            state=requirement.state,
                            cycle=EventField(complete_mapping[requirement.at], "cycle", INT),
                            op=requirement.op,
                            expected=substitute_event_ids(
                                requirement.value, complete_mapping
                            ),
                        )
                        for requirement in transformation.state_requirements
                    )
                    guarded_candidates.append(
                        GuardedSupportCandidate(expression=expression, predicates=predicates)
                    )
                guarded_supports.append(
                    GuardedSupportInstance(
                        name=support_name,
                        antecedent=conjunction((output_occurs, output_scope)),
                        supports=tuple(guarded_candidates),
                        origin=f"transformation:{transformation.name}",
                    )
                )
            else:
                constraints.append(
                    NamedConstraint(
                        name=support_name,
                        expression=Binary(
                            "implies",
                            conjunction((output_occurs, output_scope)),
                            disjunction(supports),
                        ),
                        origin=f"transformation:{transformation.name}",
                    )
                )

    return _TransformationInstantiation(
        constraints=tuple(constraints),
        requirements=tuple(requirements),
        updates=tuple(updates),
        guarded_forwards=tuple(guarded_forwards),
        guarded_supports=tuple(guarded_supports),
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
