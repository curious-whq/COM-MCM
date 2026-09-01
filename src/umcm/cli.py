"""Command-line entry points for validation and bounded trace completion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from umcm.errors import UMCMError
from umcm.ir.completion import CompletionSpec
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace
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
    complete.add_argument("--model", required=True, help="completion model YAML/JSON")
    complete.add_argument(
        "--output",
        help="write the feasible completed trace to YAML/JSON",
    )
    complete.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "finite"),
        help="feasibility backend (default: auto)",
    )
    complete.add_argument(
        "--node-limit",
        type=int,
        default=500_000,
        help="maximum finite-search nodes",
    )
    return parser


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

        if args.command == "complete":
            catalog = EventCatalog.load(args.schema)
            trace = Trace.load(args.trace)
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
    except UMCMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
