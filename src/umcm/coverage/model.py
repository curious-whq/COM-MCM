"""Serialization model for µMCM path-coverage suites."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from umcm.errors import CoverageError, SerializationError
from umcm.serialization import dump_data, load_data


COVERAGE_SCHEMA_VERSION = "umcm.coverage.v0.19.0"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SerializationError(f"{label} must be a mapping")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SerializationError(f"{label} must be a list")
    return tuple(str(item) for item in value)


@dataclass(frozen=True, slots=True)
class CoverageInput:
    name: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageInput":
        data = _mapping(data, "coverage input")
        try:
            return cls(name=str(data["name"]), path=str(data["path"]))
        except KeyError as exc:
            raise SerializationError(
                f"coverage input is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class CoverageModel:
    name: str
    composition: str
    inputs: tuple[CoverageInput, ...]
    input_event_types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "composition": self.composition,
            "input_event_types": list(self.input_event_types),
            "inputs": [item.to_dict() for item in self.inputs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageModel":
        data = _mapping(data, "coverage model")
        raw_inputs = data.get("inputs", [])
        if not isinstance(raw_inputs, list):
            raise SerializationError("coverage model inputs must be a list")
        try:
            result = cls(
                name=str(data["name"]),
                composition=str(data["composition"]),
                inputs=tuple(CoverageInput.from_dict(item) for item in raw_inputs),
                input_event_types=_strings(
                    data.get("input_event_types", []),
                    "coverage model input_event_types",
                ),
            )
        except KeyError as exc:
            raise SerializationError(
                f"coverage model is missing {exc.args[0]!r}"
            ) from exc
        if not result.inputs:
            raise CoverageError(f"coverage model {result.name!r} has no inputs")
        if not result.input_event_types:
            raise CoverageError(
                f"coverage model {result.name!r} must declare input_event_types"
            )
        return result


@dataclass(frozen=True, slots=True)
class CoverageProbe:
    kind: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {self.kind: self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageProbe":
        data = _mapping(data, "coverage probe")
        known = [
            key
            for key in ("event", "transformation", "state_transition", "interface")
            if key in data
        ]
        if len(known) != 1:
            raise SerializationError(
                "coverage probe must contain exactly one of event, transformation, "
                "state_transition, interface"
            )
        return cls(kind=known[0], value=data[known[0]])


@dataclass(frozen=True, slots=True)
class CoverageGoal:
    id: str
    model: str
    probes: tuple[CoverageProbe, ...]
    description: str = ""
    category: str = "uncategorized"
    required: bool = True
    inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "model": self.model,
            "category": self.category,
            "required": self.required,
            "require": [item.to_dict() for item in self.probes],
        }
        if self.description:
            data["description"] = self.description
        if self.inputs:
            data["inputs"] = list(self.inputs)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageGoal":
        data = _mapping(data, "coverage goal")
        raw_probes = data.get("require", [])
        if not isinstance(raw_probes, list) or not raw_probes:
            raise SerializationError("coverage goal require must be a non-empty list")
        try:
            return cls(
                id=str(data["id"]),
                model=str(data["model"]),
                probes=tuple(CoverageProbe.from_dict(item) for item in raw_probes),
                description=str(data.get("description", "")),
                category=str(data.get("category", "uncategorized")),
                required=bool(data.get("required", True)),
                inputs=_strings(data.get("inputs", []), "coverage goal inputs"),
            )
        except KeyError as exc:
            raise SerializationError(
                f"coverage goal is missing {exc.args[0]!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class AutoGoalSelector:
    model: str
    kind: str
    include: tuple[str, ...] = ("*",)
    exclude: tuple[str, ...] = ()
    category: str = "auto"
    required: bool = False
    inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "model": self.model,
            "kind": self.kind,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "category": self.category,
            "required": self.required,
        }
        if self.inputs:
            data["inputs"] = list(self.inputs)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AutoGoalSelector":
        data = _mapping(data, "auto goal selector")
        try:
            kind = str(data["kind"])
            if kind not in {"transformation", "public_interface", "private_event"}:
                raise CoverageError(f"unsupported auto goal kind {kind!r}")
            return cls(
                model=str(data["model"]),
                kind=kind,
                include=_strings(data.get("include", ["*"]), "auto goal include"),
                exclude=_strings(data.get("exclude", []), "auto goal exclude"),
                category=str(data.get("category", "auto")),
                required=bool(data.get("required", False)),
                inputs=_strings(data.get("inputs", []), "auto goal inputs"),
            )
        except KeyError as exc:
            raise SerializationError(
                f"auto goal selector is missing {exc.args[0]!r}"
            ) from exc


@dataclass(slots=True)
class CoverageSuite:
    name: str
    catalog: str
    models: tuple[CoverageModel, ...]
    goals: tuple[CoverageGoal, ...]
    auto_goals: tuple[AutoGoalSelector, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    schema_version: str = COVERAGE_SCHEMA_VERSION

    @property
    def model_map(self) -> dict[str, CoverageModel]:
        return {item.name: item for item in self.models}

    def resolve(self, value: str) -> Path:
        if self.source_path is None:
            return Path(value)
        return (self.source_path.parent / value).resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "catalog": self.catalog,
            "metadata": dict(self.metadata),
            "models": [item.to_dict() for item in self.models],
            "goals": [item.to_dict() for item in self.goals],
            "auto_goals": [item.to_dict() for item in self.auto_goals],
        }

    def dump(self, path: str | Path) -> None:
        dump_data(self.to_dict(), path)

    def validate(self) -> None:
        names = [item.name for item in self.models]
        if len(names) != len(set(names)):
            raise CoverageError("coverage suite contains duplicate model names")
        goal_ids = [item.id for item in self.goals]
        if len(goal_ids) != len(set(goal_ids)):
            raise CoverageError("coverage suite contains duplicate goal ids")
        known = set(names)
        for goal in self.goals:
            if goal.model not in known:
                raise CoverageError(
                    f"coverage goal {goal.id!r} references unknown model {goal.model!r}"
                )
            available_inputs = {
                item.name for item in self.model_map[goal.model].inputs
            }
            missing_inputs = set(goal.inputs) - available_inputs
            if missing_inputs:
                raise CoverageError(
                    f"coverage goal {goal.id!r} references unknown input(s): "
                    + ", ".join(sorted(missing_inputs))
                )
        for selector in self.auto_goals:
            if selector.model not in known:
                raise CoverageError(
                    f"auto goal references unknown model {selector.model!r}"
                )
            available_inputs = {
                item.name for item in self.model_map[selector.model].inputs
            }
            missing_inputs = set(selector.inputs) - available_inputs
            if missing_inputs:
                raise CoverageError(
                    "auto goal references unknown input(s): "
                    + ", ".join(sorted(missing_inputs))
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageSuite":
        data = _mapping(data, "coverage suite")
        raw_models = data.get("models", [])
        raw_goals = data.get("goals", [])
        raw_auto = data.get("auto_goals", [])
        for label, value in (
            ("models", raw_models), ("goals", raw_goals), ("auto_goals", raw_auto)
        ):
            if not isinstance(value, list):
                raise SerializationError(f"coverage suite {label} must be a list")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise SerializationError("coverage suite metadata must be a mapping")
        try:
            result = cls(
                name=str(data["name"]),
                catalog=str(data["catalog"]),
                models=tuple(CoverageModel.from_dict(item) for item in raw_models),
                goals=tuple(CoverageGoal.from_dict(item) for item in raw_goals),
                auto_goals=tuple(AutoGoalSelector.from_dict(item) for item in raw_auto),
                metadata=dict(metadata),
                schema_version=str(data.get("schema_version", COVERAGE_SCHEMA_VERSION)),
            )
        except KeyError as exc:
            raise SerializationError(
                f"coverage suite is missing {exc.args[0]!r}"
            ) from exc
        result.validate()
        return result

    @classmethod
    def load(cls, path: str | Path) -> "CoverageSuite":
        source = Path(path).resolve()
        result = cls.from_dict(load_data(source))
        result.source_path = source
        return result
