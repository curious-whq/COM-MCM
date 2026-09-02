"""Persistent operational state for bounded microarchitectural traces.

A ``StateVariable`` declares one scalar state cell.  A stateful transformation
can attach ``StateRequirement`` objects, which inspect the pre-state at an
anchor event, and ``StateUpdate`` objects, which atomically write the post-state
of that event cycle.  Cells not written in a cycle stutter automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umcm.errors import SchemaError, SerializationError
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict
from umcm.ir.sort import Sort
from umcm.serialization import decode_value, encode_value


@dataclass(frozen=True, slots=True)
class StateVariable:
    """One persistent scalar state cell."""

    name: str
    sort: Sort
    initial: Any
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise SchemaError(
                "state variable name must be qualified, for example "
                "'LSU.retry_queue.valid'"
            )
        if isinstance(self.initial, Expr):
            if not self.initial.sort.compatible_with(self.sort):
                raise SchemaError(
                    f"state variable {self.name!r} initial expression has sort "
                    f"{self.initial.sort}, expected {self.sort}"
                )
        elif not self.sort.accepts_literal(self.initial):
            raise SchemaError(
                f"state variable {self.name!r} initial value "
                f"{self.initial!r} is invalid for {self.sort}"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "sort": self.sort.to_dict(),
            "initial": encode_value(self.initial),
        }
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateVariable":
        if not isinstance(data, Mapping):
            raise SerializationError("state variable must be a mapping")
        try:
            return cls(
                name=str(data["name"]),
                sort=Sort.from_dict(data["sort"]),
                initial=decode_value(data["initial"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state variable is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class StateRequirement:
    """A pre-state comparison anchored to an input event role."""

    state: str
    at: str
    op: str
    value: Expr
    description: str = ""

    def __post_init__(self) -> None:
        if not self.state:
            raise SchemaError("state requirement must name a state variable")
        if not self.at:
            raise SchemaError("state requirement must name an anchor role")
        if self.op not in {"eq", "ne", "lt", "le", "gt", "ge"}:
            raise SchemaError(
                f"unsupported state requirement operator {self.op!r}; "
                "available: eq, ne"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "state": self.state,
            "at": self.at,
            "op": self.op,
            "value": expr_to_dict(self.value),
        }
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateRequirement":
        if not isinstance(data, Mapping):
            raise SerializationError("state requirement must be a mapping")
        try:
            return cls(
                state=str(data["state"]),
                at=str(data["at"]),
                op=str(data.get("op", "eq")),
                value=expr_from_dict(data["value"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state requirement is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class StateUpdate:
    """An atomic post-state write anchored to an input event role."""

    state: str
    at: str
    value: Expr
    description: str = ""

    def __post_init__(self) -> None:
        if not self.state:
            raise SchemaError("state update must name a state variable")
        if not self.at:
            raise SchemaError("state update must name an anchor role")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "state": self.state,
            "at": self.at,
            "value": expr_to_dict(self.value),
        }
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateUpdate":
        if not isinstance(data, Mapping):
            raise SerializationError("state update must be a mapping")
        try:
            return cls(
                state=str(data["state"]),
                at=str(data["at"]),
                value=expr_from_dict(data["value"]),
                description=str(data.get("description", "")),
            )
        except KeyError as exc:
            raise SerializationError(
                f"state update is missing {exc.args[0]!r}"
            ) from exc
