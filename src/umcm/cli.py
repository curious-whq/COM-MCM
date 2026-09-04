"""Command-line entry points for composition, traces, completion and axioms."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from umcm.composition import CompositionSpec, compose_modules
from umcm.coverage import CoverageSuite, run_coverage
from umcm.errors import UMCMError
from umcm.graph.checker import (
    AxiomStatus,
    MemoryModelStatus,
    check_trace_memory_model,
)
from umcm.graph.model import GraphModelSpec
from umcm.hierarchy import (
    AbstractionSpec,
    abstract_trace,
    build_interface_contracts,
    check_memory_model_preservation,
    check_refinement,
    project_interface_trace,
)
from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
from umcm.serialization import dump_data
from umcm.search import (
    HierarchicalSearchSpec,
    SearchStatus,
    StageStatus,
    run_hierarchical_search,
)
from umcm.solver.completion import CompletionStatus, complete_trace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umcm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="validate a trace against an event catalog",
    )
    validate.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    validate.add_argument("--trace", required=True, help="trace YAML/JSON")
    validate.add_argument(
        "--complete",
        action="store_true",
        help="require every required event field even if trace.partial is true",
    )

    complete = subparsers.add_parser(
        "complete",
        help="complete a partial trace with bounded hidden-event slots",
    )
    complete.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    complete.add_argument("--trace", required=True, help="partial trace YAML/JSON")
    completion_source = complete.add_mutually_exclusive_group(required=True)
    completion_source.add_argument(
        "--model",
        help="monolithic completion model YAML/JSON",
    )
    completion_source.add_argument(
        "--composition",
        help="module/connector composition manifest YAML/JSON",
    )
    complete.add_argument(
        "--output",
        help="write the feasible completed trace to YAML/JSON",
    )
    complete.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "finite", "z3"),
        help="feasibility backend (default: auto)",
    )
    complete.add_argument(
        "--node-limit",
        type=int,
        default=500_000,
        help="maximum finite-search nodes",
    )

    compose = subparsers.add_parser(
        "compose",
        help="compose module and connector models into one completion model",
    )
    compose.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    compose.add_argument(
        "--composition",
        required=True,
        help="module/connector composition manifest YAML/JSON",
    )
    compose.add_argument(
        "--trace",
        help="partial trace used to instantiate parameterized module templates",
    )
    compose.add_argument(
        "--output",
        required=True,
        help="write the composed completion model to YAML/JSON",
    )

    check = subparsers.add_parser(
        "check",
        help="project a completed trace to execution graphs and check axioms",
    )
    check.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    check.add_argument("--trace", required=True, help="completed trace YAML/JSON")
    check.add_argument("--axioms", required=True, help="graph/axiom model YAML/JSON")
    check.add_argument(
        "--output",
        help="write a representative execution graph to YAML/JSON",
    )
    check.add_argument(
        "--max-candidates",
        type=int,
        default=10_000,
        help="maximum rf/co execution-graph candidates",
    )

    abstract = subparsers.add_parser(
        "abstract",
        help="hide concrete events and emit certified hierarchy summaries",
    )
    abstract.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    abstract.add_argument("--trace", required=True, help="completed concrete trace")
    abstract.add_argument(
        "--abstraction",
        required=True,
        help="hierarchy abstraction YAML/JSON",
    )
    abstract.add_argument("--output", help="write the abstract trace")
    abstract.add_argument(
        "--axioms",
        help="also check that architectural candidates are preserved",
    )
    abstract.add_argument(
        "--max-candidates",
        type=int,
        default=10_000,
        help="maximum rf/co candidates during preservation checking",
    )

    refine = subparsers.add_parser(
        "refine",
        help="verify that an abstract trace is justified by a concrete trace",
    )
    refine.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    refine.add_argument("--concrete", required=True, help="completed concrete trace")
    refine.add_argument(
        "--abstract-trace",
        required=True,
        help="abstract trace to validate",
    )
    refine.add_argument(
        "--abstraction",
        required=True,
        help="hierarchy abstraction YAML/JSON",
    )

    interfaces = subparsers.add_parser(
        "interfaces",
        help="inspect module public ports and private implementation inventory",
    )
    interfaces.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    interfaces.add_argument("--composition", required=True, help="composition manifest")
    interfaces.add_argument(
        "--trace",
        help="trace used to instantiate parameterized modules",
    )
    interfaces.add_argument("--output", help="write interface manifest YAML/JSON")

    project_interface = subparsers.add_parser(
        "project-interface",
        help="hide module-private events without synthesizing summary events",
    )
    project_interface.add_argument("--schema", required=True, help="event catalog YAML/JSON")
    project_interface.add_argument("--composition", required=True, help="composition manifest")
    project_interface.add_argument("--trace", required=True, help="completed concrete trace")
    project_interface.add_argument("--output", required=True, help="write interface-only trace")

    cover = subparsers.add_parser(
        "cover",
        help="search bounded witnesses for µMCM events, rules and state transitions",
    )
    cover.add_argument(
        "profile",
        help="coverage profile name (for example boom) or suite YAML/JSON path",
    )
    cover.add_argument("--suite", help="explicit coverage suite YAML/JSON")
    cover.add_argument(
        "--backend",
        default="z3",
        choices=("finite", "z3"),
        help="feasibility backend (default: z3)",
    )
    cover.add_argument(
        "--node-limit",
        type=int,
        default=500_000,
        help="maximum finite-search nodes per goal/input pair",
    )
    cover.add_argument("--output", help="write coverage report YAML/JSON")
    cover.add_argument(
        "--witness-dir",
        help="write one completed witness trace per covered goal",
    )

    search = subparsers.add_parser(
        "search",
        help="search architectural skeletons, then realize them through public interfaces",
    )
    search.add_argument(
        "profile",
        help="search profile name (for example boom) or search YAML/JSON path",
    )
    search.add_argument("--spec", help="explicit hierarchical search YAML/JSON")
    search.add_argument(
        "--rvwmo",
        action="store_true",
        help="use the RVWMO architectural layer (required)",
    )
    search.add_argument(
        "--backend",
        default="z3",
        choices=("finite", "z3"),
        help="µMCM realization backend (default: z3)",
    )
    search.add_argument(
        "--node-limit",
        type=int,
        default=500_000,
        help="maximum finite-search nodes per realization schedule",
    )
    search.add_argument("--output", help="write the hierarchical search report")
    search.add_argument(
        "--witness-dir",
        help="write the architectural skeleton and completed stage witnesses",
    )
    return parser


def _coverage_suite_path(profile: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    candidate = Path(profile)
    if candidate.suffix.lower() in {".yaml", ".yml", ".json"}:
        return candidate
    if profile != "boom":
        raise UMCMError(
            f"unknown coverage profile {profile!r}; pass --suite or a suite path"
        )
    relative = Path("examples/boom/coverage/v019.yaml")
    choices = (Path.cwd() / relative, Path(__file__).resolve().parents[2] / relative)
    for choice in choices:
        if choice.is_file():
            return choice
    raise UMCMError(
        "cannot locate the boom coverage suite; run from the project root or pass --suite"
    )


def _search_spec_path(profile: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    candidate = Path(profile)
    if candidate.suffix.lower() in {".yaml", ".yml", ".json"}:
        return candidate
    if profile != "boom":
        raise UMCMError(
            f"unknown search profile {profile!r}; pass --spec or a search-spec path"
        )
    relative = Path("examples/boom/search/v021.yaml")
    choices = (Path.cwd() / relative, Path(__file__).resolve().parents[2] / relative)
    for choice in choices:
        if choice.is_file():
            return choice
    raise UMCMError(
        "cannot locate the BOOM search spec; run from the project root or pass --spec"
    )


def _safe_filename(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in "-_" else "_" for char in value
    )


def _print_graph_summary(check_result) -> None:
    representative = check_result.representative
    graph = representative.graph
    print(
        f"EXECUTION GRAPH: {len(graph.operations)} operation(s), "
        f"{len(check_result.candidates)} candidate(s)"
    )
    for operation in sorted(graph.operations.values(), key=lambda item: item.id):
        hart = "init" if operation.hart is None else f"hart={operation.hart}"
        print(
            f"  {operation.id}: {operation.kind.value}, {hart}, "
            f"addr={operation.address!r}, value={operation.value!r}"
        )

    print("RELATIONS:")
    preferred = (
        "po", "rf", "rfi", "rfe", "co", "fr", "fri", "fre", "ppo", "gmo", "hb", "ar"
    )
    names = [name for name in preferred if name in graph.relations]
    names.extend(sorted(set(graph.relations) - set(names)))
    for name in names:
        relation = graph.relation(name)
        rendered = ", ".join(
            f"{source}->{target}" for source, target in relation.sorted_edges()
        )
        print(f"  {name}: {rendered or '(empty)'}")


def _check_metadata(check_result) -> dict[str, object]:
    representative = check_result.representative
    return {
        "status": check_result.status.value,
        "candidate_count": len(check_result.candidates),
        "representative_candidate": representative.graph.candidate_id,
        "axioms": [result.to_dict() for result in representative.axioms],
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
            trace.validate(catalog, partial=False if args.complete else None)
            mode = "partial" if trace.partial and not args.complete else "complete"
            print(
                f"VALID {mode} trace: {len(trace.events)} event(s), "
                f"{len(trace.constraints)} constraint(s), "
                f"{len(catalog.event_types)} event type(s)"
            )
            return 0

        if args.command == "compose":
            catalog = EventCatalog.load(args.schema)
            manifest = CompositionSpec.load(args.composition)
            instantiation_trace = Trace.load(args.trace) if args.trace else None
            composed = compose_modules(catalog, manifest, instantiation_trace)
            output = Path(args.output)
            composed.completion.dump(output)
            totals = composed.manifest["totals"]
            print(
                f"COMPOSED {manifest.name}: "
                f"{len(composed.modules)} module(s), "
                f"{len(manifest.connections)} connection(s), "
                f"{totals['slots']} slot(s), "
                f"{totals['state_variables']} state variable(s), "
                f"{totals['transformations']} transformation(s), "
                f"{totals['constraints']} constraint(s)"
            )
            for loaded in composed.modules:
                module = loaded.spec
                print(
                    f"  module {loaded.reference_name}: "
                    f"{len(module.ports)} port(s), "
                    f"{len(module.slots)} slot(s), "
                    f"{len(module.state_variables)} state(s), "
                    f"{len(module.transformations)} transformation(s)"
                )
            for role_name, values in composed.resolved_roles.items():
                if isinstance(values, list):
                    print(f"  role {role_name}: {len(values)} item(s)")
                    for index, item in enumerate(values):
                        rendered = ", ".join(
                            f"{key}={value!r}"
                            for key, value in sorted(item.items())
                        )
                        print(f"    [{index}] {rendered}")
                else:
                    rendered = ", ".join(
                        f"{key}={value!r}"
                        for key, value in sorted(values.items())
                    )
                    print(f"  role {role_name}: {rendered}")
            for connection in manifest.connections:
                print(
                    f"  connection {connection.name}: "
                    f"{connection.source.qualified_name} -> "
                    f"{connection.target.qualified_name} "
                    f"[{connection.mode.value}]"
                )
            print(f"WROTE {output}")
            return 0

        if args.command == "interfaces":
            catalog = EventCatalog.load(args.schema)
            manifest = CompositionSpec.load(args.composition)
            instantiation_trace = Trace.load(args.trace) if args.trace else None
            composed = compose_modules(catalog, manifest, instantiation_trace)
            contracts = build_interface_contracts(composed)
            payload = {
                "schema_version": "umcm.interfaces.v0.15.0",
                "composition": manifest.name,
                "policy": "ports-only-public-surface",
                "modules": [item.to_dict() for item in contracts],
            }
            for contract in contracts:
                print(
                    f"MODULE {contract.module}: {len(contract.ports)} public port(s), "
                    f"{len(contract.private_state_names)} private state(s), "
                    f"{len(contract.private_event_types)} private event type(s), "
                    f"{len(contract.private_transformation_names)} private transformation(s)"
                )
                for port in contract.ports:
                    print(
                        f"  {port.direction:6s} {port.name}: {port.event_type}"
                    )
            if args.output:
                output = Path(args.output)
                dump_data(payload, output)
                print(f"WROTE {output}")
            return 0

        if args.command == "project-interface":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
            manifest = CompositionSpec.load(args.composition)
            composed = compose_modules(catalog, manifest, trace)
            result = project_interface_trace(trace, composed)
            output = Path(args.output)
            result.trace.dump(output)
            cert = result.certificate
            print(
                f"INTERFACE PROJECTION {manifest.name}: "
                f"{cert.source_event_count} -> {cert.projected_event_count} event(s), "
                f"{len(cert.hidden_event_ids)} private event(s) hidden"
            )
            for module, ids in cert.hidden_by_module.items():
                print(f"  {module}: {len(ids)} hidden")
            print(f"WROTE {output}")
            return 0

        if args.command == "search":
            if not args.rvwmo:
                raise UMCMError("BOOM hierarchical search requires --rvwmo")
            spec_path = _search_spec_path(args.profile, args.spec)
            search_spec = HierarchicalSearchSpec.load(spec_path)
            report = run_hierarchical_search(
                search_spec,
                backend=args.backend,
                node_limit=args.node_limit,
                progress=lambda message: print(f"SEARCH {message}", flush=True),
            )

            if report.skeleton is None:
                print(
                    f"ARCHITECTURE TARGET NOT FOUND: examined "
                    f"{report.assignments_examined}/{report.estimated_assignments} "
                    "assignment(s)"
                )
            else:
                skeleton = report.skeleton
                graph = skeleton.graph
                print(
                    f"ARCHITECTURE {skeleton.target_status.upper()}: "
                    f"{len(graph.operations)} operation(s), "
                    f"{len(skeleton.obligations)} obligation(s)"
                )
                for operation in sorted(
                    graph.operations.values(), key=lambda item: item.id
                ):
                    if operation.kind.value == "init_write":
                        print(
                            f"  {operation.id}: init {operation.address!r}="
                            f"{operation.value!r}"
                        )
                    else:
                        value = (
                            operation.read_value
                            if operation.is_read
                            else operation.stored_value
                        )
                        print(
                            f"  {operation.id}: {operation.kind.value} "
                            f"hart={operation.hart} po={operation.program_index} "
                            f"addr={operation.address!r} value={value!r}"
                        )
                for name in ("po", "rf", "co", "fr", "ppo"):
                    if name not in graph.relations:
                        continue
                    rendered = ", ".join(
                        f"{source}->{target}"
                        for source, target in graph.relation(name).sorted_edges()
                    )
                    print(f"  {name}: {rendered or '(empty)'}")
                for violation in skeleton.violations:
                    print(f"  violated: {violation['axiom']}")

            marks = {
                StageStatus.REALIZABLE: "[+]",
                StageStatus.UNREALIZABLE: "[-]",
                StageStatus.BLOCKED: "[!]",
                StageStatus.UNKNOWN: "[?]",
            }
            print("REALIZATION STAGES:")
            for stage in report.stages:
                required = "required" if stage.required else "optional"
                print(
                    f"  {marks[stage.status]} {stage.name}: "
                    f"{stage.status.value} ({required}, {stage.attempts} attempt(s))"
                )
                if stage.schedule:
                    print("    schedule: " + " -> ".join(stage.schedule))
                if stage.reason:
                    print(f"    {stage.reason}")
                for missing in stage.missing_interfaces:
                    print(f"    missing: {missing}")

            if args.witness_dir:
                witness_dir = Path(args.witness_dir)
                witness_dir.mkdir(parents=True, exist_ok=True)
                if report.skeleton is not None:
                    architecture_trace = witness_dir / "architecture_input.yaml"
                    architecture_graph = witness_dir / "architecture_graph.yaml"
                    report.skeleton.trace.dump(architecture_trace)
                    report.skeleton.graph.dump(architecture_graph)
                for stage in report.stages:
                    if stage.witness is None:
                        continue
                    path = witness_dir / f"{_safe_filename(stage.name)}.yaml"
                    stage.witness.dump(path)
                    stage.witness_path = str(path)

            if args.output:
                output = Path(args.output)
                dump_data(report.to_dict(), output)
                print(f"WROTE {output}")
            print(
                f"HIERARCHICAL SEARCH {report.status.value.upper()}: "
                f"end-to-end={'yes' if report.end_to_end else 'no'}"
            )
            return 0 if report.status in {
                SearchStatus.WITNESS, SearchStatus.PARTIAL
            } else 1

        if args.command == "cover":
            suite_path = _coverage_suite_path(args.profile, args.suite)
            suite = CoverageSuite.load(suite_path)
            report = run_coverage(
                suite,
                backend=args.backend,
                node_limit=args.node_limit,
                progress=lambda message: print(f"COVER {message}", flush=True),
            )
            if args.witness_dir:
                witness_dir = Path(args.witness_dir)
                witness_dir.mkdir(parents=True, exist_ok=True)
                for item in report.results:
                    if item.witness is None:
                        continue
                    safe = "".join(
                        char if char.isalnum() or char in "-_" else "_"
                        for char in item.goal.id
                    )
                    path = witness_dir / f"{safe}.yaml"
                    item.witness.dump(path)
                    item.witness_path = str(path)

            payload = report.to_dict()
            summary = payload["summary"]
            print(
                f"COVERAGE {suite.name}: {summary['covered']}/{summary['total']} "
                f"goal(s) covered; required "
                f"{summary['required_covered']}/{summary['required']}"
            )
            marks = {
                "covered": "[+]",
                "uncovered": "[-]",
                "unreachable": "[!]",
                "unknown": "[?]",
            }
            for item in report.results:
                suffix = f" via {item.input_name}" if item.input_name else ""
                print(
                    f"  {marks[item.status.value]} {item.goal.id}: "
                    f"{item.status.value}{suffix}"
                )
                if item.status.value != "covered":
                    print(f"      {item.reason}")
            if args.output:
                output = Path(args.output)
                dump_data(payload, output)
                print(f"WROTE {output}")
            return 0 if report.required_complete else 1

        if args.command == "complete":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
            if args.composition:
                manifest = CompositionSpec.load(args.composition)
                composed = compose_modules(catalog, manifest, trace)
                model = composed.completion
                print(
                    f"COMPOSED {manifest.name}: "
                    f"{len(composed.modules)} module(s), "
                    f"{len(manifest.connections)} connection(s)"
                )
            else:
                model = CompletionSpec.load(args.model)
            result = complete_trace(
                catalog,
                trace,
                model,
                backend=args.backend,
                node_limit=args.node_limit,
            )
            if result.status is CompletionStatus.FEASIBLE:
                assert result.completed_trace is not None
                print(
                    f"FEASIBLE {result.backend} completion: "
                    f"{len(result.completed_trace.events)} event(s), "
                    f"{len(result.added_event_ids)} hidden event(s) added, "
                    f"{result.instantiated_constraint_count} instantiated constraint(s), "
                    f"{result.explored_nodes} search node(s)"
                )
                for event_id in result.added_event_ids:
                    event = result.completed_trace.get(event_id)
                    fields = ", ".join(
                        f"{name}={value!r}" for name, value in sorted(event.fields.items())
                    )
                    suffix = f", {fields}" if fields else ""
                    print(
                        f"  + cycle {event.cycle}: {event.id} "
                        f"[{event.event_type}{suffix}]"
                    )
                changed_steps = [
                    step for step in result.state_steps if step.get("changes")
                ]
                if changed_steps:
                    print("STATE transitions:")
                    for step in changed_steps:
                        rendered = ", ".join(
                            f"{change['state']}: {change['before']!r} -> "
                            f"{change['after']!r}"
                            for change in step["changes"]
                        )
                        print(f"  @ cycle {step['cycle']}: {rendered}")
                if args.output:
                    output = Path(args.output)
                    result.completed_trace.dump(output)
                    print(f"WROTE {output}")
                return 0
            if result.status is CompletionStatus.INFEASIBLE:
                print(
                    f"INFEASIBLE within bounded model: {result.reason} "
                    f"({result.explored_nodes} search node(s))"
                )
                return 1
            print(
                f"UNKNOWN: {result.reason} "
                f"({result.explored_nodes} search node(s))"
            )
            return 3

        if args.command == "check":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
            trace.validate(catalog, partial=False)
            model = GraphModelSpec.load(args.axioms)
            result = check_trace_memory_model(
                trace,
                model,
                max_candidates=args.max_candidates,
            )
            _print_graph_summary(result)
            representative = result.representative
            representative.graph.metadata["memory_model_check"] = _check_metadata(result)

            if result.status is MemoryModelStatus.FORBIDDEN:
                print(f"MEMORY MODEL VIOLATION: {model.model}")
                for axiom in representative.axioms:
                    if axiom.status is not AxiomStatus.VIOLATED:
                        continue
                    print(f"  violated axiom: {axiom.axiom} ({axiom.kind})")
                    if axiom.cycle:
                        print("  cycle:")
                        for edge in axiom.cycle:
                            relation = edge.relation
                            if relation == "rfe" and representative.graph.relation("rf").contains(
                                edge.source, edge.target
                            ):
                                relation = "rfe/rf"
                            print(
                                f"    {edge.source} -{relation}-> {edge.target}"
                            )
                    for source, target in axiom.offending_edges:
                        print(f"    offending edge: {source}->{target}")
                exit_code = 1
            else:
                print(f"MEMORY MODEL ALLOWED: {model.model}")
                exit_code = 0

            if args.output:
                output = Path(args.output)
                representative.graph.dump(output)
                print(f"WROTE {output}")
            return exit_code

        if args.command == "abstract":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
            abstraction = AbstractionSpec.load(args.abstraction)
            result = abstract_trace(trace, catalog, abstraction)
            certificate = result.certificate
            print(
                f"ABSTRACTED {certificate.source_level} -> "
                f"{certificate.target_level}: "
                f"{certificate.source_event_count} concrete event(s), "
                f"{certificate.output_event_count} output event(s), "
                f"{len(certificate.hidden_event_ids)} hidden event(s), "
                f"{len(certificate.summaries)} summary event(s)"
            )
            for summary in certificate.summaries:
                sources = ", ".join(summary.source_event_ids)
                print(
                    f"  + {summary.output_event_id} [{summary.rule}] <- {sources}"
                )

            exit_code = 0
            if args.axioms:
                graph_model = GraphModelSpec.load(args.axioms)
                preservation = check_memory_model_preservation(
                    trace,
                    result.trace,
                    graph_model,
                    max_candidates=args.max_candidates,
                )
                print(
                    "MEMORY-MODEL PRESERVATION: "
                    f"concrete={preservation.concrete.status.value}, "
                    f"abstract={preservation.abstract.status.value}"
                )
                print(
                    "  "
                    + ("PRESERVED: " if preservation.preserved else "CHANGED: ")
                    + preservation.reason
                )
                exit_code = 0 if preservation.preserved else 1

            if args.output:
                output = Path(args.output)
                result.trace.dump(output)
                print(f"WROTE {output}")
            return exit_code

        if args.command == "refine":
            catalog = EventCatalog.load(args.schema)
            concrete = Trace.load(args.concrete)
            abstracted = Trace.load(args.abstract_trace)
            abstraction = AbstractionSpec.load(args.abstraction)
            result = check_refinement(concrete, abstracted, catalog, abstraction)
            if result.valid:
                print(f"REFINEMENT VALID: {result.reason}")
                return 0
            print(f"REFINEMENT INVALID: {result.reason}")
            if result.missing_event_ids:
                print("  missing: " + ", ".join(result.missing_event_ids))
            if result.extra_event_ids:
                print("  extra: " + ", ".join(result.extra_event_ids))
            if result.changed_event_ids:
                print("  changed: " + ", ".join(result.changed_event_ids))
            return 1
    except UMCMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
