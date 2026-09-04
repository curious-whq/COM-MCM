"""Source-provenance checks for source-derived hardware models.

The checker intentionally separates *source mapping* from *implementation
status*.  A pinned line range is evidence for a rule, not evidence that the
rule has already been encoded correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import SchemaError
from umcm.serialization import load_data


_IMPLEMENTED = {"executable-source-derived", "executable-bounded"}
_KNOWN_STATUS = _IMPLEMENTED | {"missing", "needs-rework"}


@dataclass(frozen=True, slots=True)
class SourceLedgerReport:
    complete: bool
    behavior_count: int
    implemented_count: int
    blockers: tuple[str, ...]


def audit_source_ledger(path: str | Path) -> SourceLedgerReport:
    """Validate a v0.21 ledger and return its honest completion state."""

    ledger_path = Path(path)
    data = load_data(ledger_path)
    if not isinstance(data, Mapping):
        raise SchemaError("source ledger must be a mapping")
    repositories = _mapping(data.get("repositories"), "repositories")
    files = _mapping(data.get("files"), "files")
    behaviors = data.get("behaviors")
    acceptance = _mapping(data.get("acceptance"), "acceptance")
    if not isinstance(behaviors, list) or not behaviors:
        raise SchemaError("source ledger behaviors must be a non-empty list")

    for name, repository in repositories.items():
        repository = _mapping(repository, f"repository {name}")
        commit = str(repository.get("commit", ""))
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise SchemaError(f"repository {name!r} must pin a 40-digit commit")
        if not str(repository.get("url", "")).startswith("https://"):
            raise SchemaError(f"repository {name!r} must use an https URL")

    for name, source_file in files.items():
        source_file = _mapping(source_file, f"source file {name}")
        repository = str(source_file.get("repository", ""))
        if repository not in repositories:
            raise SchemaError(
                f"source file {name!r} names unknown repository {repository!r}"
            )
        digest = str(source_file.get("sha256", ""))
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise SchemaError(f"source file {name!r} must pin a SHA-256 digest")
        if not str(source_file.get("path", "")):
            raise SchemaError(f"source file {name!r} must have a path")

    ids: set[str] = set()
    blockers: list[str] = []
    implemented = 0
    components: set[str] = set()
    for raw_behavior in behaviors:
        behavior = _mapping(raw_behavior, "behavior")
        behavior_id = str(behavior.get("id", ""))
        if not behavior_id or behavior_id in ids:
            raise SchemaError(f"duplicate or empty behavior id {behavior_id!r}")
        ids.add(behavior_id)
        component = str(behavior.get("component", ""))
        if not component:
            raise SchemaError(f"behavior {behavior_id!r} has no component")
        components.add(component)
        _validate_source_reference(behavior_id, behavior.get("source"), files)
        status = str(behavior.get("status", ""))
        if status not in _KNOWN_STATUS:
            raise SchemaError(
                f"behavior {behavior_id!r} has unknown status {status!r}"
            )
        if status in _IMPLEMENTED:
            implemented += 1
            implementation = behavior.get("implementation")
            if not implementation:
                raise SchemaError(
                    f"implemented behavior {behavior_id!r} has no model path"
                )
            _validate_implementation_path(
                behavior_id, str(implementation), ledger_path
            )
        else:
            blockers.append(f"{behavior_id}: {status}")

    required = acceptance.get("required_components", [])
    if not isinstance(required, list):
        raise SchemaError("acceptance.required_components must be a list")
    missing_components = sorted(set(map(str, required)) - components)
    blockers.extend(f"component {name}: absent" for name in missing_components)
    declared_complete = str(data.get("status", "")) == "complete"
    actual_complete = not blockers
    if declared_complete != actual_complete:
        blockers.append(
            "ledger status disagrees with behavior statuses"
            if declared_complete
            else "all behaviors implemented but ledger status is not complete"
        )
    return SourceLedgerReport(
        complete=actual_complete and declared_complete,
        behavior_count=len(behaviors),
        implemented_count=implemented,
        blockers=tuple(blockers),
    )


def verify_source_checkout(
    ledger_path: str | Path,
    roots: Mapping[str, str | Path],
) -> None:
    """Verify file digests against explicitly supplied repository checkouts."""

    data = load_data(ledger_path)
    files = _mapping(data.get("files"), "files")
    for name, raw_source in files.items():
        source = _mapping(raw_source, f"source file {name}")
        repository = str(source["repository"])
        if repository not in roots:
            raise SchemaError(f"no checkout root supplied for {repository!r}")
        candidate = Path(roots[repository]) / str(source["path"])
        if not candidate.is_file():
            raise SchemaError(f"source file is missing: {candidate}")
        digest = sha256(candidate.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise SchemaError(
                f"source digest mismatch for {name!r}: {digest} != {source['sha256']}"
            )


def _validate_source_reference(
    behavior_id: str,
    reference: Any,
    files: Mapping[str, Any],
) -> None:
    references = reference if isinstance(reference, list) else [reference]
    if not references or references == [None]:
        raise SchemaError(f"behavior {behavior_id!r} has no source reference")
    for raw_item in references:
        item = _mapping(raw_item, f"behavior {behavior_id} source")
        file_name = str(item.get("file", ""))
        if file_name not in files:
            raise SchemaError(
                f"behavior {behavior_id!r} names unknown source file {file_name!r}"
            )
        lines = item.get("lines")
        if (
            not isinstance(lines, list)
            or len(lines) != 2
            or not all(isinstance(value, int) for value in lines)
            or lines[0] <= 0
            or lines[1] < lines[0]
        ):
            raise SchemaError(
                f"behavior {behavior_id!r} source lines must be [start, end]"
            )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{label} must be a mapping")
    return value


def _validate_implementation_path(
    behavior_id: str, implementation: str, ledger_path: Path
) -> None:
    """Reject executable ledger entries whose claimed model does not exist."""

    root = next(
        (
            parent
            for parent in ledger_path.resolve().parents
            if (parent / "pyproject.toml").is_file()
        ),
        None,
    )
    if root is None:
        raise SchemaError("cannot locate project root for source ledger")
    candidate = root / implementation
    if not candidate.is_file():
        raise SchemaError(
            f"implemented behavior {behavior_id!r} names missing model {implementation!r}"
        )
