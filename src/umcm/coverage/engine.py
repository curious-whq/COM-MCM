"""Reachability-driven path coverage over bounded hierarchical models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from umcm.composition import CompositionSpec, compose_modules
from umcm.composition.engine import CompositionResult
from umcm.coverage.model import (
    AutoGoalSelector,
    CoverageGoal,
    CoverageModel,
    CoverageProbe,
    CoverageSuite,
)
from umcm.errors import CoverageError, UMCMError
from umcm.ir.event import EventCatalog
from umcm.ir.expression import Binary, EventField, Expr, Literal, conjunction, disjunction
from umcm.ir.sort import BOOL
from umcm.ir.trace import Trace
from umcm.solver.completion import CompletionResult, CompletionStatus, complete_problem
from umcm.solver.problem import (
    BoundedProblem,
    NamedConstraint,
    StateRequirementInstance,
    build_problem,
)


class CoverageStatus(str, Enum):
    COVERED = "covered"
    UNCOVERED = "uncovered"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PreparedCase:
    catalog: EventCatalog
    model: CoverageModel
    name: str
    trace_path: Path
    trace: Trace
    composed: CompositionResult
    problem: BoundedProblem


@dataclass(slots=True)
class GoalResult:
    goal: CoverageGoal
    status: CoverageStatus
    reason: str
    input_name: str | None = None
    witness: Trace | None = None
    hidden_event_count: int = 0
    active_transformations: tuple[str, ...] = ()
    explored_nodes: int = 0
    witness_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.goal.id,
            "model": self.goal.model,
            "category": self.goal.category,
            "required": self.goal.required,
            "status": self.status.value,
            "reason": self.reason,
        }
        if self.goal.description:
            data["description"] = self.goal.description
        if self.input_name is not None:
            data["input"] = self.input_name
        if self.witness is not None:
            data["witness"] = {
                "event_count": len(self.witness.events),
                "hidden_event_count": self.hidden_event_count,
                "active_transformations": list(self.active_transformations),
            }
        if self.witness_path is not None:
            data["witness"]["path"] = self.witness_path
        if self.explored_nodes:
            data["explored_nodes"] = self.explored_nodes
        return data


@dataclass(slots=True)
class CoverageReport:
    suite: str
    results: list[GoalResult]
    structural: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def required_complete(self) -> bool:
        return all(
            item.status is CoverageStatus.COVERED
            for item in self.results
            if item.goal.required
        )

    def to_dict(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in CoverageStatus}
        for item in self.results:
            counts[item.status.value] += 1
        required = [item for item in self.results if item.goal.required]
        return {
            "schema_version": "umcm.coverage-report.v0.19.0",
            "suite": self.suite,
            "status": "complete" if self.required_complete else "incomplete",
            "summary": {
                **counts,
                "total": len(self.results),
                "required": len(required),
                "required_covered": sum(
                    item.status is CoverageStatus.COVERED for item in required
                ),
            },
            "metadata": dict(self.metadata),
            "goals": [item.to_dict() for item in self.results],
            "structural": self.structural,
        }


def run_coverage(
    suite: CoverageSuite,
    *,
    backend: str = "z3",
    node_limit: int = 500_000,
    progress: Callable[[str], None] | None = None,
) -> CoverageReport:
    """Search a witness for every explicit or automatically generated goal."""

    catalog = EventCatalog.load(suite.resolve(suite.catalog))
    emit = progress or (lambda _message: None)
    prepared = _prepare_cases(suite, catalog, progress=emit)
    structural = _structural_inventory(prepared)
    goals = [*suite.goals, *_expand_auto_goals(suite.auto_goals, structural)]
    seen: set[str] = set()
    for goal in goals:
        if goal.id in seen:
            raise CoverageError(f"expanded coverage goal id collision: {goal.id}")
        seen.add(goal.id)

    results: list[GoalResult] = []
    for goal in goals:
        emit(f"goal {goal.id}: searching")
        result = _cover_goal(
            goal,
            [
                item
                for item in prepared
                if item.model.name == goal.model
                and (not goal.inputs or item.name in set(goal.inputs))
            ],
            backend=backend,
            node_limit=node_limit,
        )
        results.append(result)
        emit(f"goal {goal.id}: {result.status.value}")
    return CoverageReport(
        suite=suite.name,
        results=results,
        structural=structural,
        metadata={
            **suite.metadata,
            "backend": backend,
            "input_policy": "declared-public-events-only",
        },
    )


def _prepare_cases(
    suite: CoverageSuite,
    catalog: EventCatalog,
    *,
    progress: Callable[[str], None],
) -> list[PreparedCase]:
    prepared: list[PreparedCase] = []
    for model in suite.models:
        composition_path = suite.resolve(model.composition)
        manifest = CompositionSpec.load(composition_path)
        allowed = set(model.input_event_types)
        for candidate in model.inputs:
            progress(f"input {model.name}/{candidate.name}: instantiating")
            trace_path = suite.resolve(candidate.path)
            trace = Trace.load(trace_path)
            trace.validate(catalog)
            forbidden = sorted(
                {event.event_type for event in trace.events} - allowed
            )
            if forbidden:
                raise CoverageError(
                    f"coverage input {candidate.name!r} for model {model.name!r} "
                    "contains event type(s) outside input_event_types: "
                    + ", ".join(forbidden)
                )
            composed = compose_modules(catalog, manifest, trace)
            problem = build_problem(catalog, trace, composed.completion)
            prepared.append(
                PreparedCase(
                    catalog=catalog,
                    model=model,
                    name=candidate.name,
                    trace_path=trace_path,
                    trace=trace,
                    composed=composed,
                    problem=problem,
                )
            )
    return prepared


def _cover_goal(
    goal: CoverageGoal,
    cases: list[PreparedCase],
    *,
    backend: str,
    node_limit: int,
) -> GoalResult:
    if not cases:
        return GoalResult(
            goal, CoverageStatus.UNREACHABLE, "model has no bounded input cases"
        )

    feasible: list[tuple[tuple[int, int, int], PreparedCase, CompletionResult]] = []
    missing_reasons: list[str] = []
    solve_reasons: list[str] = []
    saw_unknown = False
    total_nodes = 0

    for case in cases:
        try:
            problem = _copy_problem(case.problem)
            compiled, reasons = _compile_goal(problem, case.composed, goal)
            if compiled is None:
                missing_reasons.append(f"{case.name}: " + "; ".join(reasons))
                continue
            problem.constraints.append(
                NamedConstraint(
                    name=f"coverage.goal.{goal.id}",
                    expression=compiled,
                    origin=f"coverage:{goal.id}",
                )
            )
            result = complete_problem(
                problem, backend=backend, node_limit=node_limit
            )
        except UMCMError as exc:
            solve_reasons.append(f"{case.name}: {exc}")
            continue

        total_nodes += result.explored_nodes
        if result.status is CompletionStatus.FEASIBLE:
            assert result.completed_trace is not None
            max_cycle = max(
                (event.cycle or 0 for event in result.completed_trace.events),
                default=0,
            )
            score = (
                len(result.added_event_ids),
                len(result.completed_trace.events),
                max_cycle,
            )
            feasible.append((score, case, result))
        elif result.status is CompletionStatus.UNKNOWN:
            saw_unknown = True
            solve_reasons.append(f"{case.name}: {result.reason}")
        else:
            solve_reasons.append(f"{case.name}: {result.reason}")

    if feasible:
        _, case, result = min(feasible, key=lambda item: item[0])
        assert result.completed_trace is not None
        names = tuple(
            sorted(
                {
                    str(item["transformation"])
                    for item in result.active_transformations
                }
            )
        )
        return GoalResult(
            goal=goal,
            status=CoverageStatus.COVERED,
            reason="bounded witness found",
            input_name=case.name,
            witness=result.completed_trace,
            hidden_event_count=len(result.added_event_ids),
            active_transformations=names,
            explored_nodes=total_nodes,
        )

    if missing_reasons and not solve_reasons:
        return GoalResult(
            goal,
            CoverageStatus.UNREACHABLE,
            "no bounded producer/binding: " + " | ".join(missing_reasons),
            explored_nodes=total_nodes,
        )
    if saw_unknown:
        return GoalResult(
            goal,
            CoverageStatus.UNKNOWN,
            "solver bound or backend was inconclusive: " + " | ".join(solve_reasons),
            explored_nodes=total_nodes,
        )
    reasons = [*missing_reasons, *solve_reasons]
    return GoalResult(
        goal,
        CoverageStatus.UNCOVERED,
        "bindings exist but guards/state/bounds reject them: " + " | ".join(reasons),
        explored_nodes=total_nodes,
    )


def _compile_goal(
    problem: BoundedProblem,
    composed: CompositionResult,
    goal: CoverageGoal,
) -> tuple[Expr | None, list[str]]:
    expressions: list[Expr] = []
    reasons: list[str] = []
    for index, probe in enumerate(goal.probes):
        expression, reason = _compile_probe(
            problem, composed, probe, f"coverage.{goal.id}.{index}"
        )
        if expression is None:
            reasons.append(reason)
        else:
            expressions.append(expression)
    if reasons:
        return None, reasons
    return conjunction(expressions), []


def _compile_probe(
    problem: BoundedProblem,
    composed: CompositionResult,
    probe: CoverageProbe,
    prefix: str,
) -> tuple[Expr | None, str]:
    if probe.kind == "event":
        return _event_probe(problem, probe.value)
    if probe.kind == "transformation":
        pattern = (
            str(probe.value.get("name", "*"))
            if isinstance(probe.value, Mapping)
            else str(probe.value)
        )
        candidates = [
            item
            for item in problem.transformation_activations
            if _matches(item.transformation, pattern)
        ]
        if not candidates:
            return None, f"transformation {pattern!r} has no bounded role binding"
        for candidate_index, candidate in enumerate(candidates):
            for predicate_index, predicate in enumerate(candidate.state_predicates):
                problem.state_requirements.append(
                    StateRequirementInstance(
                        name=(
                            f"{prefix}.activation.{candidate_index}."
                            f"state.{predicate_index}"
                        ),
                        state=predicate.state,
                        cycle=predicate.cycle,
                        activation=candidate.expression,
                        op=predicate.op,
                        expected=predicate.expected,
                        origin=prefix,
                    )
                )
        return disjunction(item.expression for item in candidates), ""
    if probe.kind == "interface":
        value = _require_mapping(probe.value, "interface probe")
        module_name = str(value.get("module", ""))
        port_name = str(value.get("port", ""))
        loaded = next(
            (item for item in composed.modules if item.reference_name == module_name),
            None,
        )
        if loaded is None or port_name not in loaded.spec.port_map:
            return None, f"unknown public interface {module_name}.{port_name}"
        return _event_probe(
            problem, {"type": loaded.spec.port_map[port_name].event_type}
        )
    if probe.kind == "state_transition":
        return _state_transition_probe(problem, probe.value, prefix)
    raise CoverageError(f"unsupported coverage probe kind {probe.kind!r}")


def _event_probe(
    problem: BoundedProblem, value: Any
) -> tuple[Expr | None, str]:
    if isinstance(value, Mapping):
        pattern = str(value.get("type", "*"))
        fields = value.get("fields", {})
        if not isinstance(fields, Mapping):
            raise CoverageError("event probe fields must be a mapping")
    else:
        pattern = str(value)
        fields = {}
    alternatives: list[Expr] = []
    for event in problem.events:
        if not _matches(event.event_type, pattern):
            continue
        event_type = problem.catalog.resolve(event.event_type)
        predicates: list[Expr] = [EventField(event.id, "occurs", BOOL)]
        valid = True
        for name, expected in fields.items():
            if name == "cycle":
                if event.cycle is None:
                    valid = False
                    break
                sort = event.cycle.sort if isinstance(event.cycle, Expr) else None
                if sort is None:
                    from umcm.ir.sort import INT

                    sort = INT
                actual = EventField(event.id, "cycle", sort)
            else:
                field = event_type.field_map.get(str(name))
                if field is None or name not in event.fields:
                    valid = False
                    break
                actual = EventField(event.id, str(name), field.sort)
                sort = field.sort
            predicates.append(Binary("eq", actual, Literal(expected, sort)))
        if valid:
            alternatives.append(conjunction(predicates))
    if not alternatives:
        return None, f"event {pattern!r} has no bounded slot/input"
    return disjunction(alternatives), ""


def _state_transition_probe(
    problem: BoundedProblem, value: Any, prefix: str
) -> tuple[Expr | None, str]:
    data = _require_mapping(value, "state_transition probe")
    if "state" not in data or "to" not in data:
        raise CoverageError("state_transition requires state and to")
    pattern = str(data["state"])
    state_map = {item.name: item for item in problem.spec.state_variables}
    alternatives: list[Expr] = []
    for index, update in enumerate(problem.state_updates):
        if not _matches(update.state, pattern):
            continue
        variable = state_map[update.state]
        reaches = conjunction(
            (
                update.activation,
                Binary("eq", update.value, Literal(data["to"], variable.sort)),
            )
        )
        if "from" in data:
            problem.state_requirements.append(
                StateRequirementInstance(
                    name=f"{prefix}.from.{index}",
                    state=update.state,
                    cycle=update.cycle,
                    activation=reaches,
                    op="eq",
                    expected=Literal(data["from"], variable.sort),
                    origin=prefix,
                )
            )
        alternatives.append(reaches)
    if not alternatives:
        return None, f"state {pattern!r} has no bounded writer to {data['to']!r}"
    return disjunction(alternatives), ""


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CoverageError(f"{label} must be a mapping")
    return value


def _matches(value: str, pattern: str) -> bool:
    # Exact qualified state names commonly contain square brackets. Treat an
    # exact spelling literally before interpreting wildcard syntax.
    return value == pattern or fnmatchcase(value, pattern)


def _copy_problem(problem: BoundedProblem) -> BoundedProblem:
    """Copy only mutable query lists; the instantiated IR objects are immutable."""

    return BoundedProblem(
        catalog=problem.catalog,
        source_trace=problem.source_trace,
        spec=problem.spec,
        events=problem.events,
        constraints=list(problem.constraints),
        state_requirements=list(problem.state_requirements),
        state_updates=list(problem.state_updates),
        guarded_forwards=problem.guarded_forwards,
        guarded_supports=problem.guarded_supports,
        transformation_activations=problem.transformation_activations,
        slot_ids=problem.slot_ids,
    )


def _structural_inventory(cases: list[PreparedCase]) -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    for case in cases:
        item = models.setdefault(
            case.model.name,
            {
                "inputs": [],
                "transformations": set(),
                "bound_transformations": set(),
                "state_variables": set(),
                "public_interfaces": set(),
                "private_events": set(),
                "event_producers": {},
            },
        )
        item["inputs"].append(case.name)
        completion = case.composed.completion
        item["transformations"].update(t.name for t in completion.transformations)
        item["state_variables"].update(s.name for s in completion.state_variables)
        item["bound_transformations"].update(
            activation.transformation
            for activation in case.problem.transformation_activations
        )
        for loaded in case.composed.modules:
            for port in loaded.spec.ports:
                item["public_interfaces"].add(
                    f"{loaded.reference_name}.{port.name}"
                )
            public_types = {port.event_type for port in loaded.spec.ports}
            item["private_events"].update(loaded.spec.internal_events)
            item["private_events"].update(
                slot.event_type
                for slot in loaded.spec.slots
                if slot.event_type not in public_types
            )
        producers = item["event_producers"]
        for transformation in completion.transformations:
            for output in transformation.outputs:
                producers.setdefault(output.event_type, set()).add(transformation.name)

    rendered: dict[str, Any] = {}
    for name, item in sorted(models.items()):
        producers = {
            event_type: sorted(names)
            for event_type, names in sorted(item["event_producers"].items())
        }
        orphan_private = sorted(
            event_type
            for event_type in item["private_events"]
            if event_type not in producers
        )
        rendered[name] = {
            "inputs": sorted(item["inputs"]),
            "transformations": sorted(item["transformations"]),
            "state_variables": sorted(item["state_variables"]),
            "public_interfaces": sorted(item["public_interfaces"]),
            "private_events": sorted(item["private_events"]),
            "event_producers": producers,
            "orphan_private_event_types": orphan_private,
            "no_bounded_transformation_binding": sorted(
                item["transformations"] - item["bound_transformations"]
            ),
        }
    return {"models": rendered}


def _expand_auto_goals(
    selectors: Iterable[AutoGoalSelector], structural: Mapping[str, Any]
) -> list[CoverageGoal]:
    goals: list[CoverageGoal] = []
    models = structural["models"]
    for selector in selectors:
        inventory = models[selector.model]
        key = {
            "transformation": "transformations",
            "public_interface": "public_interfaces",
            "private_event": "private_events",
        }[selector.kind]
        for value in inventory[key]:
            if not any(_matches(value, pattern) for pattern in selector.include):
                continue
            if any(_matches(value, pattern) for pattern in selector.exclude):
                continue
            safe = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
            probe_key = {
                "transformation": "transformation",
                "public_interface": "interface",
                "private_event": "event",
            }[selector.kind]
            probe_value: Any = value
            if selector.kind == "public_interface":
                module, port = value.split(".", 1)
                probe_value = {"module": module, "port": port}
            goals.append(
                CoverageGoal(
                    id=f"auto_{selector.model}_{selector.kind}_{safe}",
                    model=selector.model,
                    probes=(CoverageProbe(probe_key, probe_value),),
                    description=f"Automatically generated {selector.kind} reachability goal",
                    category=selector.category,
                    required=selector.required,
                    inputs=selector.inputs,
                )
            )
    return goals
