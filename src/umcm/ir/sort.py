"""Lightweight sorts used by event fields and expressions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umcm.errors import SchemaError


@dataclass(frozen=True, slots=True)
class Sort:
    """A lightweight, serializable value sort.

    The foundation deliberately keeps sorts small.  Built-ins are ``bool``,
    ``int`` and ``string``.  ``bv`` represents an unsigned fixed-width bit
    vector.  Domain-specific names such as ``address`` and ``op_id`` are legal
    custom sorts and can optionally carry a width.
    """

    name: str
    width: int | None = None
    signed: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise SchemaError("sort name must be a non-empty string")
        if self.width is not None and self.width <= 0:
            raise SchemaError("sort width must be positive")
        if self.name in {"bool", "string"} and self.width is not None:
            raise SchemaError(f"sort {self.name!r} cannot have a width")
        if self.name == "bv" and self.width is None:
            raise SchemaError("bit-vector sort requires a width")
        if self.signed is not None and self.name not in {"int", "bv"}:
            raise SchemaError("signed is only meaningful for int/bv sorts")

    @property
    def is_bool(self) -> bool:
        return self.name == "bool"

    @property
    def is_int(self) -> bool:
        return self.name == "int"

    @property
    def is_string(self) -> bool:
        return self.name == "string"

    @property
    def is_bitvector(self) -> bool:
        return self.name == "bv"

    def compatible_with(self, other: "Sort") -> bool:
        """Return whether two expressions can be compared/combined directly."""

        return self == other

    def accepts_literal(self, value: Any) -> bool:
        """Check whether a concrete Python value is a valid literal of this sort."""

        if self.is_bool:
            return isinstance(value, bool)
        if self.is_int:
            return isinstance(value, int) and not isinstance(value, bool)
        if self.is_string:
            return isinstance(value, str)
        if self.is_bitvector:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
            assert self.width is not None
            return value < (1 << self.width)

        # Domain sorts intentionally accept scalar symbolic names ("x") and
        # integer encodings.  A later backend may impose stronger constraints.
        return (
            value is None
            or isinstance(value, (str, int, bool, float))
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.width is not None:
            data["width"] = self.width
        if self.signed is not None:
            data["signed"] = self.signed
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | str) -> "Sort":
        if isinstance(data, str):
            return cls(data)
        if not isinstance(data, Mapping):
            raise SchemaError(f"sort must be a string or mapping, got {type(data).__name__}")
        try:
            return cls(
                name=str(data["name"]),
                width=data.get("width"),
                signed=data.get("signed"),
            )
        except KeyError as exc:
            raise SchemaError("sort mapping is missing 'name'") from exc


BOOL = Sort("bool")
INT = Sort("int")
STRING = Sort("string")


def bitvec(width: int, *, signed: bool = False) -> Sort:
    return Sort("bv", width=width, signed=signed)


def address(width: int = 64) -> Sort:
    return Sort("address", width=width)


def value(width: int = 64) -> Sort:
    return Sort("value", width=width)


def identifier(name: str = "op_id") -> Sort:
    return Sort(name)
