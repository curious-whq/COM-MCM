# `umcm/serialization.py` 源码讲解

文件职责：提供安全的 YAML/JSON 读写和表达式值编解码。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–14 行）

```python
"""Safe YAML/JSON helpers and expression-aware field-value codecs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from umcm.errors import SerializationError
from umcm.ir.expression import Expr, expr_from_dict, expr_to_dict


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `_EXPR_KEY`（第 15–17 行）

```python
_EXPR_KEY = "$expr"


```

这是模块级常量或公开导出声明：`_EXPR_KEY` 保存exprkey，供该对象的校验、转换或序列化逻辑使用。

## 函数 `encode_value`（第 18–29 行）

```python
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


```

把value递归编码为安全、可序列化的数据结构。

## 函数 `decode_value`（第 30–42 行）

```python
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


```

从序列化数据识别并还原value。

## 函数 `load_data`（第 43–59 行）

```python
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


```

按文件扩展名选择安全 YAML 或 JSON 解析器，并把解析错误包装为序列化错误。

## 函数 `dump_data`（第 60–78 行）

```python
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
```

按扩展名选择 YAML 或 JSON，以稳定格式把数据写入目标文件。

