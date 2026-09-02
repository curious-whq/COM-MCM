"""Trace-driven finite parameter binding for module templates.

Iteration 10 keeps the operational engine concrete and bounded, but removes
witness-specific operation identities from reusable module models.  A
composition can name semantic *roles* (older load, younger load, visible
store, ...).  Each role selects exactly one observed trace event and exports
selected fields/annotations into a typed template context.

Module YAML files may then contain placeholders such as::

    ${older_load.op_id}
    ${older_load.ldq_idx}
    LSU.ldq[${younger_load.ldq_idx}].valid

An exact placeholder preserves the original Python value type (for example an
integer LDQ index).  Embedded placeholders are rendered as strings, which is
useful for state-variable names and human-readable labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from umcm.errors import CompositionError, SchemaError, SerializationError
from umcm.ir.expression import Expr
from umcm.ir.trace import Trace
from umcm.serialization import decode_value, encode_value


_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
_EXACT_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}$")


@dataclass(frozen=True, slots=True)
class TraceRoleSpec:
    """Select one observed trace event and export values for templating."""

    name: str
    event_type: str
    where: Mapping[str, Any] = field(default_factory=dict)
    exports: Mapping[str, str] = field(default_factory=dict)
    event_id: str | None = None
    occurring_only: bool = True
    cardinality: str = "one"
    min_matches: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("trace role name must be non-empty")
        if not self.event_type:
            raise SchemaError("trace role event_type must be non-empty")
        object.__setattr__(self, "where", dict(self.where))
        if self.cardinality not in {"one", "many"}:
            raise SchemaError("trace role cardinality must be one or many")
        if self.min_matches < 0:
            raise SchemaError("trace role min_matches must be non-negative")
        object.__setattr__(self, "exports", dict(self.exports))
        for alias, path in self.exports.items():
            if not alias or not path:
                raise SchemaError(
                    f"trace role {self.name!r} exports must use non-empty names and paths"
                )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "event_type": self.event_type,
            "where": encode_value(dict(self.where)),
            "exports": dict(self.exports),
            "occurring_only": self.occurring_only,
            "cardinality": self.cardinality,
            "min_matches": self.min_matches,
        }
        if self.event_id is not None:
            data["event_id"] = self.event_id
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceRoleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("trace role must be a mapping")
        allowed = {
            "name", "event_type", "where", "exports", "event_id",
            "occurring_only", "cardinality", "min_matches", "description",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "trace role contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_where = decode_value(data.get("where", {}))
        raw_exports = data.get("exports", {})
        if not isinstance(raw_where, Mapping):
            raise SerializationError("trace role where must be a mapping")
        if not isinstance(raw_exports, Mapping):
            raise SerializationError("trace role exports must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                event_type=str(data["event_type"]),
                where=dict(raw_where),
                exports={str(k): str(v) for k, v in raw_exports.items()},
                event_id=(
                    None if data.get("event_id") is None else str(data["event_id"])
                ),
                occurring_only=bool(data.get("occurring_only", True)),
                cardinality=str(data.get("cardinality", "one")),
                min_matches=int(data.get("min_matches", 1)),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"trace role is missing {exc.args[0]!r}"
            ) from exc


def resolve_trace_roles(
    trace: Trace,
    roles: list[TraceRoleSpec] | tuple[TraceRoleSpec, ...],
) -> dict[str, Any]:
    """Resolve singular or collection roles in declaration order.

    ``cardinality: one`` preserves the v0.10 behavior. ``cardinality: many``
    exports every matching event, ordered deterministically by cycle then id.
    Collection roles are primarily used by v0.11 finite LDQ-family expansion.
    """

    context: dict[str, Any] = {}
    for role in roles:
        if role.name in context:
            raise CompositionError(f"duplicate trace role {role.name!r}")
        expected_where = render_template(dict(role.where), context)
        matches = []
        for event in trace.events:
            if event.event_type != role.event_type:
                continue
            if role.event_id is not None and event.id != role.event_id:
                continue
            if role.occurring_only and event.occurs is not True:
                continue
            if all(
                _resolve_event_path(event, path) == expected
                for path, expected in expected_where.items()
            ):
                matches.append(event)
        matches.sort(
            key=lambda event: (
                event.cycle if isinstance(event.cycle, int) else 10**18,
                event.id,
            )
        )
        if role.cardinality == "one":
            if len(matches) != 1:
                detail = (
                    "no event matched"
                    if not matches
                    else f"{len(matches)} events matched: "
                    + ", ".join(event.id for event in matches)
                )
                raise CompositionError(
                    f"trace role {role.name!r} must resolve to exactly one "
                    f"{role.event_type} event; {detail}"
                )
            context[role.name] = _export_role_event(role, matches[0])
            continue

        if len(matches) < role.min_matches:
            raise CompositionError(
                f"trace role {role.name!r} requires at least "
                f"{role.min_matches} {role.event_type} event(s); "
                f"only {len(matches)} matched"
            )
        context[role.name] = [
            _export_role_event(role, event) for event in matches
        ]
    return context


def _export_role_event(role: TraceRoleSpec, event) -> dict[str, Any]:
    exported: dict[str, Any] = {
        "event_id": event.id,
        "event_type": event.event_type,
    }
    for alias, path in role.exports.items():
        value = _resolve_event_path(event, path)
        if isinstance(value, Expr):
            raise CompositionError(
                f"trace role {role.name!r} export {alias!r} from {path!r} "
                "is symbolic; finite template instantiation requires a "
                "concrete observed value"
            )
        exported[alias] = value
    return exported


def render_template(value: Any, context: Mapping[str, Any]) -> Any:
    """Recursively replace ``${role.value}`` placeholders.

    Exact placeholders preserve the underlying type.  Placeholders embedded in
    a larger string are stringified.  Mapping keys may also contain embedded
    placeholders.
    """

    if isinstance(value, str):
        exact = _EXACT_PLACEHOLDER.fullmatch(value)
        if exact:
            return _resolve_context_path(context, exact.group(1))

        def replace(match: re.Match[str]) -> str:
            resolved = _resolve_context_path(context, match.group(1))
            return str(resolved)

        return _PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(render_template(item, context) for item in value)
    if isinstance(value, Mapping):
        rendered: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = render_template(key, context) if isinstance(key, str) else key
            if new_key in rendered:
                raise CompositionError(
                    f"template rendering produced duplicate mapping key {new_key!r}"
                )
            rendered[new_key] = render_template(item, context)
        return rendered
    return value


def expand_module_repeats(
    raw_module: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Expand declarative per-role fragments in a raw module template.

    Syntax::

        repeat:
          - over: loads
            as: load
            include:
              state_variables: [...]
              transformations: [...]

    The named ``over`` role must have ``cardinality: many``.  Each item is
    exposed through ``as`` plus a zero-based ``repeat_index`` field.  Only the
    standard module list sections may be repeated.
    """

    if not isinstance(raw_module, Mapping):
        raise CompositionError("module template must be a mapping")
    data = dict(raw_module)
    raw_repeats = data.pop("repeat", [])
    if not raw_repeats:
        return data
    if not isinstance(raw_repeats, list):
        raise CompositionError("module repeat must be a list")
    allowed_sections = {
        "ports", "slots", "state_variables", "transformations", "constraints"
    }
    for spec in raw_repeats:
        if not isinstance(spec, Mapping):
            raise CompositionError("module repeat item must be a mapping")
        unknown = set(spec) - {"over", "as", "include"}
        if unknown:
            raise CompositionError(
                "module repeat contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        try:
            over = str(spec["over"])
            alias = str(spec["as"])
            include = spec["include"]
        except KeyError as exc:
            raise CompositionError(
                f"module repeat is missing {exc.args[0]!r}"
            ) from exc
        if not alias:
            raise CompositionError("module repeat alias must be non-empty")
        try:
            collection = _resolve_context_path(context, over)
        except CompositionError as exc:
            raise CompositionError(
                f"module repeat over {over!r} could not be resolved"
            ) from exc
        if not isinstance(collection, list):
            raise CompositionError(
                f"module repeat over {over!r} requires a cardinality=many role"
            )
        if not isinstance(include, Mapping):
            raise CompositionError("module repeat include must be a mapping")
        bad_sections = set(include) - allowed_sections
        if bad_sections:
            raise CompositionError(
                "module repeat include contains unsupported section(s): "
                + ", ".join(sorted(str(item) for item in bad_sections))
            )
        for index, item in enumerate(collection):
            if not isinstance(item, Mapping):
                raise CompositionError(
                    f"module repeat role {over!r} item {index} is not a mapping"
                )
            local_context = dict(context)
            local_item = dict(item)
            local_item["repeat_index"] = index
            local_context[alias] = local_item
            rendered = render_template(dict(include), local_context)
            for section, values in rendered.items():
                if not isinstance(values, list):
                    raise CompositionError(
                        f"module repeat section {section!r} must render to a list"
                    )
                current = data.setdefault(section, [])
                if not isinstance(current, list):
                    raise CompositionError(
                        f"module section {section!r} must be a list before repeat expansion"
                    )
                current.extend(values)
    return data


def template_placeholders(value: Any) -> set[str]:
    """Return all placeholder paths occurring in a nested raw model."""

    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in _PLACEHOLDER.finditer(value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                found.update(match.group(1) for match in _PLACEHOLDER.finditer(key))
            found.update(template_placeholders(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(template_placeholders(item))
    return found


def _resolve_context_path(context: Mapping[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = context
    traversed: list[str] = []
    for part in parts:
        traversed.append(part)
        if not isinstance(current, Mapping) or part not in current:
            raise CompositionError(
                f"unresolved template parameter ${{{path}}}; missing "
                f"{'.'.join(traversed)!r}"
            )
        current = current[part]
    return current


def _resolve_event_path(event, path: str) -> Any:
    parts = path.split(".")
    if not parts:
        raise CompositionError("empty trace-event path")
    head = parts[0]
    if head == "id":
        current: Any = event.id
    elif head == "type" or head == "event_type":
        current = event.event_type
    elif head == "cycle":
        current = event.cycle
    elif head == "occurs":
        current = event.occurs
    elif head == "fields":
        current = event.fields
    elif head == "annotations":
        current = event.annotations
    else:
        # Convenience: bare field names mean fields.<name>.
        current = event.fields
        parts = [head, *parts[1:]]
    for part in parts[1:] if head in {"id", "type", "event_type", "cycle", "occurs", "fields", "annotations"} else parts:
        if not isinstance(current, Mapping) or part not in current:
            raise CompositionError(
                f"trace event {event.id!r} has no path {path!r}"
            )
        current = current[part]
    return current
