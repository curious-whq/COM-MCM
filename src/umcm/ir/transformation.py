"""Bounded operational transformations over event roles.

A transformation is operational rather than architectural-axiomatic. For every
occurring tuple of input events satisfying ``when``, it requires some occurring
tuple of output events satisfying ``ensure``. Outputs are existential support
events; they are not inherently later than inputs. Timing direction is stated
explicitly in ``ensure``.

Iteration 3 additionally permits input-only transformations to carry structured
state requirements and atomic state updates. Requirements observe the pre-state
at an anchor event. Updates become visible after that event's cycle.
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
from umcm.ir.state import StateRequirement, StateUpdate, StateVariable


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

    When ``exact`` is true, the single output is a derived event: every
    occurring output must also be supported by a matching enabled input
    binding.  This expresses definitions such as ``fire iff valid && ready``
    without introducing a separate handshake language.

    State requirements and updates may be anchored to either input or output
    roles.  When outputs are present, state effects activate only for a complete
    input/output binding satisfying the guard and ``ensure`` relation.
    """

    name: str
    inputs: tuple[EventRole, ...]
    outputs: tuple[EventRole, ...] = ()
    when: Expr = field(default_factory=lambda: Literal(True, BOOL))
    ensure: tuple[Expr, ...] = ()
    state_requirements: tuple[StateRequirement, ...] = ()
    state_updates: tuple[StateUpdate, ...] = ()
    exact: bool = False
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
        if self.exact and len(self.outputs) != 1:
            raise SchemaError(
                f"exact transformation {self.name!r} must have exactly one output role"
            )

    @property
    def role_map(self) -> dict[str, EventRole]:
        return {role.name: role for role in (*self.inputs, *self.outputs)}

    @property
    def is_stateful(self) -> bool:
        return bool(self.state_requirements or self.state_updates)

    def validate(
        self,
        catalog: EventCatalog,
        state_variables: Mapping[str, StateVariable] | None = None,
    ) -> None:
        roles = self.role_map
        input_names = {role.name for role in self.inputs}
        all_role_names = set(roles)
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
            self._validate_role_expression(expression, roles, catalog)

        state_map = dict(state_variables or {})
        if self.is_stateful and not state_map:
            raise SchemaError(
                f"stateful transformation {self.name!r} requires declared state variables"
            )
        for requirement in self.state_requirements:
            if requirement.at not in all_role_names:
                raise SchemaError(
                    f"state requirement in {self.name!r} anchors to unknown role "
                    f"{requirement.at!r}"
                )
            variable = self._resolve_state(requirement.state, state_map)
            if not requirement.value.sort.compatible_with(variable.sort):
                raise SchemaError(
                    f"state requirement {requirement.state!r} in {self.name!r} "
                    f"expects {variable.sort}, got {requirement.value.sort}"
                )
            self._validate_role_expression(requirement.value, roles, catalog)

        for update in self.state_updates:
            if update.at not in all_role_names:
                raise SchemaError(
                    f"state update in {self.name!r} anchors to unknown role "
                    f"{update.at!r}"
                )
            variable = self._resolve_state(update.state, state_map)
            if not update.value.sort.compatible_with(variable.sort):
                raise SchemaError(
                    f"state update {update.state!r} in {self.name!r} expects "
                    f"{variable.sort}, got {update.value.sort}"
                )
            self._validate_role_expression(update.value, roles, catalog)

    def _validate_role_expression(
        self,
        expression: Expr,
        roles: Mapping[str, EventRole],
        catalog: EventCatalog,
    ) -> None:
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

    @staticmethod
    def _resolve_state(
        name: str,
        state_variables: Mapping[str, StateVariable],
    ) -> StateVariable:
        try:
            return state_variables[name]
        except KeyError as exc:
            raise SchemaError(f"unknown state variable: {name}") from exc

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "inputs": [role.to_dict() for role in self.inputs],
            "outputs": [role.to_dict() for role in self.outputs],
            "when": expr_to_dict(self.when),
            "ensure": [expr_to_dict(expression) for expression in self.ensure],
        }
        if self.state_requirements:
            data["state_requirements"] = [
                item.to_dict() for item in self.state_requirements
            ]
        if self.state_updates:
            data["state_updates"] = [item.to_dict() for item in self.state_updates]
        if self.exact:
            data["exact"] = True
        if self.description:
            data["description"] = self.description
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Transformation":
        if not isinstance(data, Mapping):
            raise SerializationError("transformation must be a mapping")
        allowed = {
            "name", "inputs", "outputs", "when", "ensure",
            "state_requirements", "state_updates", "exact",
            "description", "tags",
        }
        unknown = set(data) - allowed
        if unknown:
            raise SerializationError(
                "transformation contains unknown key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_inputs = data.get("inputs", [])
        raw_outputs = data.get("outputs", [])
        raw_ensure = data.get("ensure", [])
        raw_requirements = data.get("state_requirements", [])
        raw_updates = data.get("state_updates", [])
        for name, value in (
            ("inputs", raw_inputs),
            ("outputs", raw_outputs),
            ("ensure", raw_ensure),
            ("state_requirements", raw_requirements),
            ("state_updates", raw_updates),
        ):
            if not isinstance(value, list):
                raise SerializationError(f"transformation {name} must be a list")
        try:
            return cls(
                name=str(data["name"]),
                inputs=tuple(EventRole.from_dict(item) for item in raw_inputs),
                outputs=tuple(EventRole.from_dict(item) for item in raw_outputs),
                when=expr_from_dict(
                    data.get("when", Literal(True, BOOL).to_dict())
                ),
                ensure=tuple(expr_from_dict(item) for item in raw_ensure),
                state_requirements=tuple(
                    StateRequirement.from_dict(item) for item in raw_requirements
                ),
                state_updates=tuple(
                    StateUpdate.from_dict(item) for item in raw_updates
                ),
                exact=bool(data.get("exact", False)),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", [])),
            )
        except KeyError as exc:
            raise SerializationError(
                f"transformation is missing {exc.args[0]!r}"
            ) from exc
