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
    event_type: str | tuple[str, ...]
    where: Mapping[str, Any] = field(default_factory=dict)
    exports: Mapping[str, str] = field(default_factory=dict)
    derived: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    event_id: str | None = None
    occurring_only: bool = True
    cardinality: str = "one"
    min_matches: int = 1
    copies: int = 1
    copy_exports: Mapping[str, str] = field(default_factory=dict)
    distinct_by: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("trace role name must be non-empty")
        if isinstance(self.event_type, str):
            if not self.event_type:
                raise SchemaError("trace role event_type must be non-empty")
        else:
            event_types = tuple(str(item) for item in self.event_type)
            if not event_types or any(not item for item in event_types):
                raise SchemaError("trace role event_type list must be non-empty")
            object.__setattr__(self, "event_type", event_types)
        object.__setattr__(self, "where", dict(self.where))
        if self.cardinality not in {"one", "many"}:
            raise SchemaError("trace role cardinality must be one or many")
        if self.min_matches < 0:
            raise SchemaError("trace role min_matches must be non-negative")
        if not isinstance(self.copies, int) or isinstance(self.copies, bool) or self.copies <= 0:
            raise SchemaError("trace role copies must be a positive integer")
        if self.cardinality != "many" and self.copies != 1:
            raise SchemaError("trace role copies requires cardinality=many")
        object.__setattr__(self, "copy_exports", dict(self.copy_exports))
        if self.copy_exports and self.copies == 1:
            raise SchemaError("trace role copy_exports requires copies greater than one")
        available = set(self.exports) | set(self.derived)
        for alias, template in self.copy_exports.items():
            if alias not in available or not isinstance(template, str) or not template:
                raise SchemaError(
                    f"trace role {self.name!r} copy_exports must replace an "
                    "exported name with a non-empty template"
                )
        object.__setattr__(self, "exports", dict(self.exports))
        object.__setattr__(
            self,
            "derived",
            {str(alias): dict(spec) for alias, spec in self.derived.items()},
        )
        overlap = set(self.exports) & set(self.derived)
        if overlap:
            raise SchemaError(
                f"trace role {self.name!r} exports and derived names overlap: "
                + ", ".join(sorted(overlap))
            )
        for alias, path in self.exports.items():
            if not alias or not path:
                raise SchemaError(
                    f"trace role {self.name!r} exports must use non-empty names and paths"
                )
        for alias, spec in self.derived.items():
            if not alias:
                raise SchemaError(
                    f"trace role {self.name!r} derived names must be non-empty"
                )
            kind = str(spec.get("kind", ""))
            if kind not in {"constant", "queue_index", "switch"}:
                raise SchemaError(
                    f"trace role {self.name!r} derived export {alias!r} has "
                    f"unsupported kind {kind!r}"
                )
            if kind == "constant":
                if "value" not in spec:
                    raise SchemaError(
                        f"trace role {self.name!r} constant {alias!r} "
                        "requires a value"
                    )
                continue
            if kind == "switch":
                path = spec.get("path")
                cases = spec.get("cases")
                if not isinstance(path, str) or not path:
                    raise SchemaError(
                        f"trace role {self.name!r} switch {alias!r} "
                        "requires a non-empty path"
                    )
                if not isinstance(cases, Mapping) or not cases:
                    raise SchemaError(
                        f"trace role {self.name!r} switch {alias!r} "
                        "requires a non-empty cases mapping"
                    )
                for choice in (*cases.values(), spec.get("default")):
                    if choice is None:
                        continue
                    if not isinstance(choice, Mapping):
                        raise SchemaError(
                            f"trace role {self.name!r} switch {alias!r} "
                            "choices must be mappings"
                        )
                    choice_keys = set(choice)
                    if choice_keys not in ({"value"}, {"path"}):
                        raise SchemaError(
                            f"trace role {self.name!r} switch {alias!r} "
                            "choices require exactly one of value or path"
                        )
                    if "path" in choice and (
                        not isinstance(choice["path"], str) or not choice["path"]
                    ):
                        raise SchemaError(
                            f"trace role {self.name!r} switch {alias!r} "
                            "choice path must be non-empty"
                        )
                continue
            capacity = spec.get("capacity")
            start = spec.get("start", 0)
            if not isinstance(capacity, int) or capacity <= 0:
                raise SchemaError(
                    f"trace role {self.name!r} queue_index {alias!r} requires "
                    "a positive integer capacity"
                )
            if not isinstance(start, int) or start < 0 or start >= capacity:
                raise SchemaError(
                    f"trace role {self.name!r} queue_index {alias!r} start "
                    "must be within the queue capacity"
                )
            group_by = spec.get("group_by", [])
            if isinstance(group_by, str):
                group_by = [group_by]
            if not isinstance(group_by, list) or any(
                not isinstance(path, str) or not path for path in group_by
            ):
                raise SchemaError(
                    f"trace role {self.name!r} queue_index {alias!r} group_by "
                    "must be a path or list of paths"
                )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "event_type": (
                list(self.event_type)
                if isinstance(self.event_type, tuple)
                else self.event_type
            ),
            "where": encode_value(dict(self.where)),
            "exports": dict(self.exports),
            "derived": {
                alias: dict(spec) for alias, spec in self.derived.items()
            },
            "occurring_only": self.occurring_only,
            "cardinality": self.cardinality,
            "min_matches": self.min_matches,
        }
        if self.copies != 1:
            data["copies"] = self.copies
        if self.copy_exports:
            data["copy_exports"] = dict(self.copy_exports)
        if self.event_id is not None:
            data["event_id"] = self.event_id
        if self.distinct_by is not None:
            data["distinct_by"] = self.distinct_by
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceRoleSpec":
        if not isinstance(data, Mapping):
            raise SerializationError("trace role must be a mapping")
        allowed = {
            "name", "event_type", "where", "exports", "derived", "event_id",
            "occurring_only", "cardinality", "min_matches", "copies", "copy_exports", "distinct_by", "description",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "trace role contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_where = decode_value(data.get("where", {}))
        raw_exports = data.get("exports", {})
        raw_derived = data.get("derived", {})
        if not isinstance(raw_where, Mapping):
            raise SerializationError("trace role where must be a mapping")
        if not isinstance(raw_exports, Mapping):
            raise SerializationError("trace role exports must be a mapping")
        if not isinstance(raw_derived, Mapping):
            raise SerializationError("trace role derived must be a mapping")
        raw_copy_exports = data.get("copy_exports", {})
        if not isinstance(raw_copy_exports, Mapping):
            raise SerializationError("trace role copy_exports must be a mapping")
        for alias, spec in raw_derived.items():
            if not isinstance(spec, Mapping):
                raise SerializationError(
                    f"trace role derived export {alias!r} must be a mapping"
                )
        try:
            return cls(
                name=str(data["name"]),
                event_type=(
                    tuple(str(item) for item in data["event_type"])
                    if isinstance(data["event_type"], list)
                    else str(data["event_type"])
                ),
                where=dict(raw_where),
                exports={str(k): str(v) for k, v in raw_exports.items()},
                derived={str(k): dict(v) for k, v in raw_derived.items()},
                event_id=(
                    None if data.get("event_id") is None else str(data["event_id"])
                ),
                occurring_only=bool(data.get("occurring_only", True)),
                cardinality=str(data.get("cardinality", "one")),
                min_matches=int(data.get("min_matches", 1)),
                copies=int(data.get("copies", 1)),
                copy_exports={str(k): str(v) for k, v in raw_copy_exports.items()},
                distinct_by=(None if data.get("distinct_by") is None else str(data.get("distinct_by"))),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"trace role is missing {exc.args[0]!r}"
            ) from exc


def resolve_trace_roles(
    trace: Trace,
    roles: list[TraceRoleSpec] | tuple[TraceRoleSpec, ...],
    *,
    initial_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve singular or collection roles in declaration order.

    ``cardinality: one`` preserves the v0.10 behavior. ``cardinality: many``
    exports every matching event, ordered deterministically by cycle then id.
    Collection roles are used by finite LSQ/MSHR-family expansion; distinct_by supports one persistent instance per shared resource id.
    """

    context: dict[str, Any] = dict(initial_context or {})
    for role in roles:
        if role.name in context:
            raise CompositionError(f"duplicate trace role {role.name!r}")
        expected_where = render_template(dict(role.where), context)
        matches = []
        accepted_types = (
            role.event_type
            if isinstance(role.event_type, tuple)
            else (role.event_type,)
        )
        for event in trace.events:
            if event.event_type not in accepted_types:
                continue
            if role.event_id is not None and event.id != role.event_id:
                continue
            if role.occurring_only and event.occurs is not True:
                continue
            matched = True
            for path, expected in expected_where.items():
                try:
                    actual = _resolve_event_path(event, path)
                except CompositionError:
                    # A missing optional annotation/field means this event is
                    # simply not a member of the role.  This is important for
                    # heterogeneous roles such as all memory operations.
                    matched = False
                    break
                if actual != expected:
                    matched = False
                    break
            if matched:
                matches.append(event)
        matches.sort(
            key=lambda event: (
                event.cycle if isinstance(event.cycle, int) else 10**18,
                event.id,
            )
        )
        if role.distinct_by is not None:
            deduped = []
            seen = set()
            for event in matches:
                key = _resolve_event_path(event, role.distinct_by)
                try:
                    marker = (type(key).__name__, key)
                    if marker in seen:
                        continue
                    seen.add(marker)
                except TypeError as exc:
                    raise CompositionError(
                        f"trace role {role.name!r} distinct_by path "
                        f"{role.distinct_by!r} did not resolve to a hashable value"
                    ) from exc
                deduped.append(event)
            matches = deduped
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
                    f"{_role_type_label(role)} event; {detail}"
                )
            derived = _derive_role_exports(role, matches)
            context[role.name] = _export_role_event(
                role, matches[0], derived[0]
            )
            continue

        if len(matches) < role.min_matches:
            raise CompositionError(
                f"trace role {role.name!r} requires at least "
                f"{role.min_matches} {_role_type_label(role)} event(s); "
                f"only {len(matches)} matched"
            )
        derived = _derive_role_exports(role, matches)
        exported = [
            _export_role_event(role, event, values)
            for event, values in zip(matches, derived)
        ]
        copies = []
        for item in exported:
            for copy_index in range(role.copies):
                copied = {**item, "copy_index": copy_index}
                for alias, template in role.copy_exports.items():
                    copied[alias] = render_template(template, {"copy": copied})
                copies.append(copied)
        context[role.name] = copies
    return context


def _role_type_label(role: TraceRoleSpec) -> str:
    if isinstance(role.event_type, tuple):
        return "[" + ", ".join(role.event_type) + "]"
    return role.event_type


def _derive_role_exports(
    role: TraceRoleSpec,
    matches: list[Any],
) -> list[dict[str, Any]]:
    result = [dict() for _ in matches]
    for alias, spec in role.derived.items():
        if spec["kind"] == "constant":
            for values in result:
                values[alias] = spec["value"]
            continue
        if spec["kind"] == "switch":
            cases = spec["cases"]
            default = spec.get("default")
            for index, event in enumerate(matches):
                selector = _resolve_event_path(event, spec["path"])
                choice = cases.get(selector, default)
                if choice is None:
                    raise CompositionError(
                        f"trace role {role.name!r} switch {alias!r} has no "
                        f"case for {selector!r} and no default"
                    )
                if "path" in choice:
                    result[index][alias] = _resolve_event_path(
                        event, str(choice["path"])
                    )
                else:
                    result[index][alias] = choice["value"]
            continue
        group_by = spec.get("group_by", [])
        if isinstance(group_by, str):
            group_by = [group_by]
        counters: dict[tuple[Any, ...], int] = {}
        start = int(spec.get("start", 0))
        capacity = int(spec["capacity"])
        for index, event in enumerate(matches):
            group = tuple(_resolve_event_path(event, path) for path in group_by)
            ordinal = counters.get(group, 0)
            counters[group] = ordinal + 1
            result[index][alias] = (start + ordinal) % capacity
    return result


def _export_role_event(
    role: TraceRoleSpec,
    event,
    derived: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
    exported.update(dict(derived or {}))
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
    raw_products = data.pop("repeat_product", [])
    if not raw_repeats and not raw_products:
        return data
    if not isinstance(raw_repeats, list):
        raise CompositionError("module repeat must be a list")
    if not isinstance(raw_products, list):
        raise CompositionError("module repeat_product must be a list")
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

    # Cartesian-product expansion for pairwise/triple LSQ rules.
    # Example:
    #   repeat_product:
    #     - axes:
    #         - {over: loads, as: older}
    #         - {over: loads, as: younger}
    #       include: {transformations: [...]}
    from itertools import product
    for spec in raw_products:
        if not isinstance(spec, Mapping):
            raise CompositionError("module repeat_product item must be a mapping")
        unknown = set(spec) - {"axes", "include"}
        if unknown:
            raise CompositionError(
                "module repeat_product contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        axes = spec.get("axes")
        include = spec.get("include")
        if not isinstance(axes, list) or not axes:
            raise CompositionError("module repeat_product axes must be a non-empty list")
        if not isinstance(include, Mapping):
            raise CompositionError("module repeat_product include must be a mapping")
        bad_sections = set(include) - allowed_sections
        if bad_sections:
            raise CompositionError(
                "module repeat_product include contains unsupported section(s): "
                + ", ".join(sorted(str(item) for item in bad_sections))
            )
        collections = []
        aliases = []
        for axis_index, axis in enumerate(axes):
            if not isinstance(axis, Mapping):
                raise CompositionError("module repeat_product axis must be a mapping")
            unknown_axis = set(axis) - {"over", "as"}
            if unknown_axis:
                raise CompositionError(
                    "module repeat_product axis contains unknown key(s): "
                    + ", ".join(sorted(str(item) for item in unknown_axis))
                )
            try:
                over = str(axis["over"])
                alias = str(axis["as"])
            except KeyError as exc:
                raise CompositionError(
                    f"module repeat_product axis is missing {exc.args[0]!r}"
                ) from exc
            if not alias or alias in aliases:
                raise CompositionError("module repeat_product aliases must be non-empty and unique")
            collection = _resolve_context_path(context, over)
            if not isinstance(collection, list):
                raise CompositionError(
                    f"module repeat_product over {over!r} requires a cardinality=many role"
                )
            collections.append(collection)
            aliases.append(alias)
        product_index = 0
        indexed_collections = [list(enumerate(collection)) for collection in collections]
        for tuple_items in product(*indexed_collections):
            local_context = dict(context)
            for alias, (item_index, item) in zip(aliases, tuple_items):
                if not isinstance(item, Mapping):
                    raise CompositionError(
                        f"module repeat_product alias {alias!r} item is not a mapping"
                    )
                local_item = dict(item)
                # Preserve the collection position even when two role bindings
                # happen to contain identical exported values.  list.index()
                # would collapse those distinct dynamic entries onto the same
                # repeat_index and produce colliding state/event names.
                local_item["repeat_index"] = item_index
                local_item["product_index"] = product_index
                local_context[alias] = local_item
            local_context["product"] = {"repeat_index": product_index}
            rendered = render_template(dict(include), local_context)
            for section, values in rendered.items():
                if not isinstance(values, list):
                    raise CompositionError(
                        f"module repeat_product section {section!r} must render to a list"
                    )
                current = data.setdefault(section, [])
                if not isinstance(current, list):
                    raise CompositionError(
                        f"module section {section!r} must be a list before repeat_product expansion"
                    )
                current.extend(values)
            product_index += 1
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
