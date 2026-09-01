"""Safe YAML/JSON helpers and expression-aware field-value codecs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from umcm.errors import SerializationError
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict


_EXPR_KEY = "$expr"


def encode_value(value: Any) -> Any:
    if isinstance(value, Expr):
        return {_EXPR_KEY: expr_to_dict(value)}
    if isinstance(value, Mapping):
        return {str(key): encode_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [encode_value(item) for item in value]
    if isinstance(value, list):
        return [encode_value(item) for item in value]
    return value


def decode_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if set(value.keys()) == {_EXPR_KEY}:
            payload = value[_EXPR_KEY]
            if not isinstance(payload, Mapping):
                raise SerializationError("$expr payload must be a mapping")
            return expr_from_dict(payload)
        return {str(key): decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    return value


def load_data(path: str | Path) -> Any:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SerializationError(f"cannot read {file_path}: {exc}") from exc

    try:
        if file_path.suffix.lower() == ".json":
            return json.loads(text)
        if file_path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SerializationError(f"cannot parse {file_path}: {exc}") from exc
    raise SerializationError(f"unsupported file extension for {file_path}")


def dump_data(data: Any, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if file_path.suffix.lower() == ".json":
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            return
        if file_path.suffix.lower() in {".yaml", ".yml"}:
            file_path.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            return
    except OSError as exc:
        raise SerializationError(f"cannot write {file_path}: {exc}") from exc
    raise SerializationError(f"unsupported file extension for {file_path}")
