"""Command-line entry points for the current foundation layer."""

from __future__ import annotations

import argparse
import sys

from umcm.errors import UMCMError
from umcm.ir.event import EventCatalog
from umcm.ir.trace import Trace


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
    except UMCMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
