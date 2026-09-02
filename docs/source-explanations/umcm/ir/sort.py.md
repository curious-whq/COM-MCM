# `umcm/ir/sort.py` 源码讲解

文件职责：定义事件字段与表达式使用的轻量值类型。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–10 行）

```python
"""Lightweight sorts used by event fields and expressions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umcm.errors import SchemaError


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `Sort` 及全部字段（第 11–24 行）

```python
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

```

表示可序列化的布尔、整数、字符串、位向量或领域类型。

- `name`：对象或规则的稳定名称。
- `width`：位向量的位宽。
- `signed`：位向量是否按有符号数解释。

## 方法 `Sort.__post_init__`（第 25–36 行）

```python
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

```

在 `Sort` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Sort.is_bool`（第 37–40 行）

```python
    @property
    def is_bool(self) -> bool:
        return self.name == "bool"

```

检查 `Sort` 实例 是否满足“bool”这一快速分类条件。

## 方法 `Sort.is_int`（第 41–44 行）

```python
    @property
    def is_int(self) -> bool:
        return self.name == "int"

```

检查 `Sort` 实例 是否满足“int”这一快速分类条件。

## 方法 `Sort.is_string`（第 45–48 行）

```python
    @property
    def is_string(self) -> bool:
        return self.name == "string"

```

检查 `Sort` 实例 是否满足“string”这一快速分类条件。

## 方法 `Sort.is_bitvector`（第 49–52 行）

```python
    @property
    def is_bitvector(self) -> bool:
        return self.name == "bv"

```

检查 `Sort` 实例 是否满足“bitvector”这一快速分类条件。

## 方法 `Sort.compatible_with`（第 53–57 行）

```python
    def compatible_with(self, other: "Sort") -> bool:
        """Return whether two expressions can be compared/combined directly."""

        return self == other

```

判断两个类型是否相同或是否属于允许直接组合的领域类型。

## 方法 `Sort.accepts_literal`（第 58–79 行）

```python
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

```

按类型种类、位宽和符号规则检查 Python 字面量是否合法。

## 方法 `Sort.to_dict`（第 80–87 行）

```python
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.width is not None:
            data["width"] = self.width
        if self.signed is not None:
            data["signed"] = self.signed
        return data

```

把 `Sort` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `Sort.from_dict`（第 88–103 行）

```python
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


```

校验输入字典的键和值，并递归构造 `Sort` 实例。

## 模块变量 `BOOL`（第 104–104 行）

```python
BOOL = Sort("bool")
```

这是模块级常量或公开导出声明：`BOOL` 保存bool，供该对象的校验、转换或序列化逻辑使用。

## 模块变量 `INT`（第 105–105 行）

```python
INT = Sort("int")
```

这是模块级常量或公开导出声明：`INT` 保存int，供该对象的校验、转换或序列化逻辑使用。

## 模块变量 `STRING`（第 106–108 行）

```python
STRING = Sort("string")


```

这是模块级常量或公开导出声明：`STRING` 保存string，供该对象的校验、转换或序列化逻辑使用。

## 函数 `bitvec`（第 109–112 行）

```python
def bitvec(width: int, *, signed: bool = False) -> Sort:
    return Sort("bv", width=width, signed=signed)


```

构造指定宽度的无符号位向量类型。

## 函数 `address`（第 113–116 行）

```python
def address(width: int = 64) -> Sort:
    return Sort("address", width=width)


```

构造指定宽度、名为 `address` 的领域位向量类型。

## 函数 `value`（第 117–120 行）

```python
def value(width: int = 64) -> Sort:
    return Sort("value", width=width)


```

构造指定宽度、名为 `value` 的领域位向量类型。

## 函数 `identifier`（第 121–122 行）

```python
def identifier(name: str = "op_id") -> Sort:
    return Sort(name)
```

构造字符串标识符类型。

