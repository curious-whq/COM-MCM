"""Bounded operational transformations over event roles.

A transformation is operational rather than architectural-axiomatic. For every
occurring tuple of input events satisfying ``when``, it requires some occurring
tuple of output events satisfying ``ensure``. Outputs are existential support
events; they are not inherently later than inputs. Timing direction is stated
explicitly in ``ensure``. This permits both forward consequences and backward
causal-support rules without introducing an accidental liveness claim.

The completion engine instantiates each rule over a finite universe formed from
observed trace events and explicit candidate event slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError
from umcm.ir.event import EventCatalog
from umcm.ir.expression import (
    Expr,
    Literal,
    expr_from_dict,
    expr_to_dict,
    iter_event_fields,
)
from umcm.ir.sort import BOOL, INT


@dataclass(frozen=True, slots=True)
class EventRole:
    """A named event variable used inside one transformation."""

    name: str
    event_type: str

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("event role name must be non-empty")
        if not self.event_type:
            raise SchemaError("event role type must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"role": self.name, "type": self.event_type}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRole":
        if not isinstance(data, Mapping):
            raise SerializationError("event role must be a mapping")
        try:
            return cls(name=str(data["role"]), event_type=str(data["type"]))
        except KeyError as exc:
            raise SerializationError(
                f"event role is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class Transformation:
    """A finite, role-based operational rule.

    Semantics for one concrete input binding ``i`` are::

        occurs(i...) and when(i...)
          -> exists output binding o.
               occurs(o...) and ensure(i..., o...)

    The rule itself does not impose temporal direction: an ``ensure`` clause may
    place an output before or after an input. A required slot may therefore be
    used as a witness query goal whose causal predecessors are completed by
    output roles. All role bindings are pairwise distinct in this first
    implementation.
    """

    name: str
    inputs: tuple[EventRole, ...]
    outputs: tuple[EventRole, ...] = ()
    when: Expr = field(default_factory=lambda: Literal(True, BOOL))
    ensure: tuple[Expr, ...] = ()
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SchemaError("transformation name must be non-empty")
        role_names = [role.name for role in (*self.inputs, *self.outputs)]
        if len(role_names) != len(set(role_names)):
            raise SchemaError(
                f"transformation {self.name!r} has duplicate role names"
            )
        if not self.when.sort.is_bool:
            raise SchemaError(
                f"transformation {self.name!r} guard must be bool"
            )
        for expression in self.ensure:
            if not expression.sort.is_bool:
                raise SchemaError(
                    f"transformation {self.name!r} ensure expressions must be bool"
                )

    @property
    def role_map(self) -> dict[str, EventRole]:
        return {role.name: role for role in (*self.inputs, *self.outputs)}

    def validate(self, catalog: EventCatalog) -> None:
        roles = self.role_map
        input_names = {role.name for role in self.inputs}

        for role in roles.values():
            catalog.resolve(role.event_type)

        guard_refs = {field.event_id for field in iter_event_fields(self.when)}
        illegal_guard_refs = guard_refs - input_names
        if illegal_guard_refs:
            raise SchemaError(
                f"transformation {self.name!r} guard references non-input role(s): "
                f"{', '.join(sorted(illegal_guard_refs))}"
            )

        for expression in (self.when, *self.ensure):
            for reference in iter_event_fields(expression):
                try:
                    role = roles[reference.event_id]
                except KeyError as exc:
                    raise SchemaError(
                        f"transformation {self.name!r} references unknown role "
                        f"{reference.event_id!r}"
                    ) from exc
                event_type = catalog.resolve(role.event_type)
                if reference.field == "occurs":
                    expected = BOOL
                elif reference.field == "cycle":
                    expected = INT
                else:
                    try:
                        expected = event_type.field_map[reference.field].sort
                    except KeyError as exc:
                        raise SchemaError(
                            f"transformation {self.name!r} references unknown field "
                            f"{role.name}.{reference.field}"
                        ) from exc
                if not reference.sort.compatible_with(expected):
                    raise SchemaError(
                        f"transformation {self.name!r} reference "
                        f"{role.name}.{reference.field} has sort {reference.sort}, "
                        f"expected {expected}"
                    )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "inputs": [role.to_dict() for role in self.inputs],
            "outputs": [role.to_dict() for role in self.outputs],
            "when": expr_to_dict(self.when),
            "ensure": [expr_to_dict(expression) for expression in self.ensure],
        }
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Transformation":
        if not isinstance(data, Mapping):
            raise SerializationError("transformation must be a mapping")
        raw_inputs = data.get("inputs", [])
        raw_outputs = data.get("outputs", [])
        raw_ensure = data.get("ensure", [])
        if not isinstance(raw_inputs, list):
            raise SerializationError("transformation inputs must be a list")
        if not isinstance(raw_outputs, list):
            raise SerializationError("transformation outputs must be a list")
        if not isinstance(raw_ensure, list):
            raise SerializationError("transformation ensure must be a list")
        try:
            return cls(
                name=str(data["name"]),
                inputs=tuple(EventRole.from_dict(item) for item in raw_inputs),
                outputs=tuple(EventRole.from_dict(item) for item in raw_outputs),
                when=expr_from_dict(
                    data.get("when", Literal(True, BOOL).to_dict())
                ),
                ensure=tuple(expr_from_dict(item) for item in raw_ensure),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SerializationError(
                f"transformation is missing {exc.args[0]!r}"
            ) from exc
