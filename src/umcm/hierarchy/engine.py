"""Deterministic trace abstraction, refinement, and graph-preservation checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from umcm.errors import AbstractionError
from umcm.graph.checker import MemoryModelCheck, check_trace_memory_model
from umcm.graph.execution import ExecutionGraph
from umcm.graph.model import GraphModelSpec
from umcm.hierarchy.model import (
    AbstractionSpec,
    EventRoleSpec,
    OutputValue,
    SummaryRuleSpec,
)
from umcm.ir.event import EventCatalog, EventInstance
from umcm.ir.expression import iter_event_fields
from umcm.ir.trace import Trace


@dataclass(frozen=True, slots=True)
class SummaryEvidence:
    rule: str
    output_event_id: str
    source_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "output_event_id": self.output_event_id,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True, slots=True)
class AbstractionCertificate:
    abstraction: str
    source_level: str
    target_level: str
    source_trace_sha256: str
    source_event_count: int
    output_event_count: int
    retained_event_ids: tuple[str, ...]
    hidden_event_ids: tuple[str, ...]
    summaries: tuple[SummaryEvidence, ...]
    preserved_constraint_count: int
    dropped_constraint_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstraction": self.abstraction,
            "source_level": self.source_level,
            "target_level": self.target_level,
            "source_trace_sha256": self.source_trace_sha256,
            "source_event_count": self.source_event_count,
            "output_event_count": self.output_event_count,
            "retained_event_ids": list(self.retained_event_ids),
            "hidden_event_ids": list(self.hidden_event_ids),
            "summaries": [item.to_dict() for item in self.summaries],
            "preserved_constraint_count": self.preserved_constraint_count,
            "dropped_constraint_count": self.dropped_constraint_count,
        }


@dataclass(frozen=True, slots=True)
class AbstractionResult:
    trace: Trace
    certificate: AbstractionCertificate


@dataclass(frozen=True, slots=True)
class RefinementCheck:
    valid: bool
    reason: str
    missing_event_ids: tuple[str, ...] = ()
    extra_event_ids: tuple[str, ...] = ()
    changed_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryModelPreservationCheck:
    preserved: bool
    concrete: MemoryModelCheck
    abstract: MemoryModelCheck
    concrete_candidate_signatures: tuple[str, ...]
    abstract_candidate_signatures: tuple[str, ...]
    reason: str


def _trace_digest(trace: Trace) -> str:
    payload = json.dumps(
        trace.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _copy_event(event: EventInstance) -> EventInstance:
    return EventInstance.from_dict(event.to_dict())


def _concrete_events(trace: Trace) -> list[EventInstance]:
    result: list[EventInstance] = []
    for event in trace.events:
        if event.occurs is not True:
            continue
        if not isinstance(event.cycle, (int, type(None))):
            raise AbstractionError(f"event {event.id!r} has symbolic cycle")
        if any(hasattr(value, "sort") for value in event.fields.values()):
            raise AbstractionError(f"event {event.id!r} has symbolic fields")
        result.append(event)
    return result


def _match_role(
    role: EventRoleSpec,
    event: EventInstance,
    bindings: Mapping[str, Any],
) -> dict[str, Any] | None:
    if event.event_type != role.event_type:
        return None
    updated = dict(bindings)
    for field_name, pattern in role.fields.items():
        if field_name not in event.fields:
            return None
        actual = event.fields[field_name]
        if pattern.variable is not None:
            existing = updated.get(pattern.variable, _MISSING)
            if existing is not _MISSING and existing != actual:
                return None
            updated[pattern.variable] = actual
        elif actual != pattern.literal:
            return None
    return updated


_MISSING = object()


def _cycles_ordered(
    previous: EventInstance,
    current: EventInstance,
    *,
    strict: bool,
) -> bool:
    if previous.cycle is None or current.cycle is None:
        return True
    if not isinstance(previous.cycle, int) or not isinstance(current.cycle, int):
        raise AbstractionError("abstraction requires concrete event cycles")
    return previous.cycle < current.cycle if strict else previous.cycle <= current.cycle


def _iter_rule_matches(
    events_by_type: Mapping[str, tuple[EventInstance, ...]],
    rule: SummaryRuleSpec,
) -> Iterator[tuple[dict[str, EventInstance], dict[str, Any]]]:
    roles = rule.roles

    def visit(
        index: int,
        selected: dict[str, EventInstance],
        bindings: dict[str, Any],
    ) -> Iterator[tuple[dict[str, EventInstance], dict[str, Any]]]:
        if index == len(roles):
            yield dict(selected), dict(bindings)
            return
        role = roles[index]
        candidates = events_by_type.get(role.event_type, ())
        for event in candidates:
            if rule.distinct_events and any(
                chosen.id == event.id for chosen in selected.values()
            ):
                continue
            if rule.ordered and selected:
                previous = selected[roles[index - 1].name]
                if not _cycles_ordered(previous, event, strict=rule.strict_order):
                    continue
            updated = _match_role(role, event, bindings)
            if updated is None:
                continue
            selected[role.name] = event
            yield from visit(index + 1, selected, updated)
            selected.pop(role.name)

    yield from visit(0, {}, {})


def _resolve_output_value(
    value: OutputValue,
    bindings: Mapping[str, Any],
    roles: Mapping[str, EventInstance],
) -> Any:
    if value.kind == "literal":
        return value.value
    if value.kind == "variable":
        try:
            return bindings[str(value.value)]
        except KeyError as exc:
            raise AbstractionError(
                f"summary output references unbound variable ${value.value}"
            ) from exc
    reference = str(value.value)
    if "." not in reference:
        raise AbstractionError(
            f"summary output field reference must be role.field, got {reference!r}"
        )
    role_name, field_name = reference.split(".", 1)
    try:
        event = roles[role_name]
    except KeyError as exc:
        raise AbstractionError(
            f"summary output references unknown role {role_name!r}"
        ) from exc
    if field_name == "cycle":
        return event.cycle
    if field_name == "id":
        return event.id
    try:
        return event.fields[field_name]
    except KeyError as exc:
        raise AbstractionError(
            f"summary output references missing field {reference!r}"
        ) from exc


def _summary_cycle(
    cycle_from: str,
    roles: Mapping[str, EventInstance],
) -> int | None:
    if cycle_from == "none":
        return None
    concrete_cycles = [
        event.cycle for event in roles.values() if isinstance(event.cycle, int)
    ]
    if cycle_from == "first":
        return min(concrete_cycles) if concrete_cycles else None
    if cycle_from == "last":
        return max(concrete_cycles) if concrete_cycles else None
    try:
        event = roles[cycle_from]
    except KeyError as exc:
        raise AbstractionError(
            f"summary cycle_from references unknown role {cycle_from!r}"
        ) from exc
    return event.cycle if isinstance(event.cycle, int) else None


def _render_id(template: str, bindings: Mapping[str, Any], rule_name: str) -> str:
    values = {name: str(value) for name, value in bindings.items()}
    values["rule"] = rule_name
    try:
        rendered = template.format(**values)
    except KeyError as exc:
        raise AbstractionError(
            f"summary id template references unbound variable {exc.args[0]!r}"
        ) from exc
    if not rendered:
        raise AbstractionError("summary id template produced an empty id")
    return rendered


def _event_sort_key(event: EventInstance) -> tuple[int, int, str]:
    if event.cycle is None:
        return (0, -1, event.id)
    assert isinstance(event.cycle, int)
    return (1, event.cycle, event.id)


def abstract_trace(
    trace: Trace,
    catalog: EventCatalog,
    spec: AbstractionSpec,
) -> AbstractionResult:
    """Apply a deterministic abstraction and return a replayable certificate."""

    trace.validate(catalog, partial=False)
    concrete_events = _concrete_events(trace)
    events_by_type: dict[str, tuple[EventInstance, ...]] = {}
    for event_type in {event.event_type for event in concrete_events}:
        events_by_type[event_type] = tuple(
            sorted(
                (event for event in concrete_events if event.event_type == event_type),
                key=_event_sort_key,
            )
        )

    generated: list[EventInstance] = []
    summary_evidence: list[SummaryEvidence] = []
    source_ids_to_hide: set[str] = set()
    output_ids: set[str] = set()

    for rule in spec.summaries:
        match_count = 0
        seen_sources: set[tuple[str, ...]] = set()
        for roles, bindings in _iter_rule_matches(events_by_type, rule):
            source_ids = tuple(roles[role.name].id for role in rule.roles)
            if source_ids in seen_sources:
                continue
            seen_sources.add(source_ids)
            match_count += 1
            if match_count > rule.max_matches:
                raise AbstractionError(
                    f"summary rule {rule.name!r} exceeds max_matches={rule.max_matches}"
                )
            event_id = _render_id(rule.output.id_template, bindings, rule.name)
            if event_id in output_ids:
                raise AbstractionError(f"duplicate abstract event id: {event_id}")
            fields = {
                name: _resolve_output_value(value, bindings, roles)
                for name, value in rule.output.fields.items()
            }
            annotations = dict(rule.output.annotations)
            annotations["abstraction"] = {
                "spec": spec.name,
                "rule": rule.name,
                "source_event_ids": list(source_ids),
                "source_event_types": [
                    roles[role.name].event_type for role in rule.roles
                ],
            }
            summary = EventInstance(
                id=event_id,
                event_type=rule.output.event_type,
                fields=fields,
                cycle=_summary_cycle(rule.output.cycle_from, roles),
                occurs=True,
                annotations=annotations,
            )
            summary.validate_against(catalog.resolve(summary.event_type), partial=False)
            generated.append(summary)
            output_ids.add(event_id)
            summary_evidence.append(
                SummaryEvidence(
                    rule=rule.name,
                    output_event_id=event_id,
                    source_event_ids=source_ids,
                )
            )
            if rule.hide_sources:
                source_ids_to_hide.update(source_ids)
        if match_count < rule.min_matches:
            raise AbstractionError(
                f"summary rule {rule.name!r} produced {match_count} match(es), "
                f"requires at least {rule.min_matches}"
            )

    retain_types = set(spec.retain.event_types)
    retain_ids = set(spec.retain.event_ids)
    retain_visibilities = set(spec.retain.visibilities)
    retained: list[EventInstance] = []
    retained_ids: set[str] = set()
    for event in concrete_events:
        event_type = catalog.resolve(event.event_type)
        explicitly_retained = (
            event.id in retain_ids
            or event.event_type in retain_types
            or event_type.visibility.value in retain_visibilities
        )
        keep = spec.default_action == "keep" or explicitly_retained
        if event.id in source_ids_to_hide and not explicitly_retained:
            keep = False
        if keep:
            if event.id in output_ids:
                raise AbstractionError(f"abstract event id collides with source: {event.id}")
            retained.append(_copy_event(event))
            retained_ids.add(event.id)
            output_ids.add(event.id)

    output_events = sorted(retained + generated, key=_event_sort_key)
    output_id_set = {event.id for event in output_events}
    preserved_constraints = []
    dropped_constraint_count = 0
    for constraint in trace.constraints:
        references = {item.event_id for item in iter_event_fields(constraint)}
        if references <= output_id_set:
            preserved_constraints.append(constraint)
        else:
            dropped_constraint_count += 1

    output_metadata = {
        key: trace.metadata[key]
        for key in spec.retain_metadata
        if key in trace.metadata
    }
    hidden_ids = tuple(
        sorted(event.id for event in concrete_events if event.id not in retained_ids)
    )
    certificate = AbstractionCertificate(
        abstraction=spec.name,
        source_level=spec.source_level,
        target_level=spec.target_level,
        source_trace_sha256=_trace_digest(trace),
        source_event_count=len(concrete_events),
        output_event_count=len(output_events),
        retained_event_ids=tuple(sorted(retained_ids)),
        hidden_event_ids=hidden_ids,
        summaries=tuple(sorted(summary_evidence, key=lambda item: item.output_event_id)),
        preserved_constraint_count=len(preserved_constraints),
        dropped_constraint_count=dropped_constraint_count,
    )
    output_metadata["abstraction"] = certificate.to_dict()
    output_metadata["abstraction_model"] = dict(spec.metadata)
    output_trace = Trace(
        events=output_events,
        constraints=preserved_constraints,
        partial=False,
        metadata=output_metadata,
    )
    output_trace.validate(catalog, partial=False)
    return AbstractionResult(trace=output_trace, certificate=certificate)


def _event_payloads(trace: Trace) -> dict[str, dict[str, Any]]:
    return {event.id: event.to_dict() for event in trace.events}


def check_refinement(
    concrete_trace: Trace,
    abstracted_trace: Trace,
    catalog: EventCatalog,
    spec: AbstractionSpec,
) -> RefinementCheck:
    """Check that ``abstracted_trace`` is exactly justified by ``concrete_trace``."""

    abstracted_trace.validate(catalog, partial=False)
    expected = abstract_trace(concrete_trace, catalog, spec).trace
    expected_events = _event_payloads(expected)
    actual_events = _event_payloads(abstracted_trace)
    missing = tuple(sorted(set(expected_events) - set(actual_events)))
    extra = tuple(sorted(set(actual_events) - set(expected_events)))
    changed = tuple(
        sorted(
            event_id
            for event_id in set(expected_events) & set(actual_events)
            if expected_events[event_id] != actual_events[event_id]
        )
    )
    if missing or extra or changed:
        return RefinementCheck(
            valid=False,
            reason="abstract event set or payload does not match the concrete witness",
            missing_event_ids=missing,
            extra_event_ids=extra,
            changed_event_ids=changed,
        )
    if expected.constraints != abstracted_trace.constraints:
        return RefinementCheck(
            valid=False,
            reason="abstract constraints do not match the deterministic abstraction",
        )
    expected_abs = expected.metadata.get("abstraction")
    actual_abs = abstracted_trace.metadata.get("abstraction")
    if expected_abs != actual_abs:
        return RefinementCheck(
            valid=False,
            reason="abstraction certificate does not match the concrete witness",
        )
    return RefinementCheck(valid=True, reason="every abstract event is backed by its rule sources")


def _graph_signature(graph: ExecutionGraph) -> str:
    operations = [
        {
            "id": operation.id,
            "kind": operation.kind.value,
            "address": operation.address,
            "value": operation.value,
            "hart": operation.hart,
            "program_index": operation.program_index,
        }
        for operation in sorted(graph.operations.values(), key=lambda item: item.id)
    ]
    relations = {
        name: [list(edge) for edge in relation.sorted_edges()]
        for name, relation in sorted(graph.relations.items())
    }
    return json.dumps(
        {"operations": operations, "relations": relations},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _check_signatures(check: MemoryModelCheck) -> tuple[str, ...]:
    return tuple(sorted({_graph_signature(item.graph) for item in check.candidates}))


def check_memory_model_preservation(
    concrete_trace: Trace,
    abstracted_trace: Trace,
    graph_spec: GraphModelSpec,
    *,
    max_candidates: int = 10_000,
) -> MemoryModelPreservationCheck:
    """Compare all architectural graph candidates before and after abstraction."""

    concrete = check_trace_memory_model(
        concrete_trace,
        graph_spec,
        max_candidates=max_candidates,
    )
    abstract = check_trace_memory_model(
        abstracted_trace,
        graph_spec,
        max_candidates=max_candidates,
    )
    concrete_signatures = _check_signatures(concrete)
    abstract_signatures = _check_signatures(abstract)
    if concrete.status != abstract.status:
        reason = (
            f"memory-model status changed from {concrete.status.value} "
            f"to {abstract.status.value}"
        )
        preserved = False
    elif concrete_signatures != abstract_signatures:
        reason = "architectural execution-graph candidate set changed"
        preserved = False
    else:
        reason = "architectural candidates and memory-model result are unchanged"
        preserved = True
    return MemoryModelPreservationCheck(
        preserved=preserved,
        concrete=concrete,
        abstract=abstract,
        concrete_candidate_signatures=concrete_signatures,
        abstract_candidate_signatures=abstract_signatures,
        reason=reason,
    )
