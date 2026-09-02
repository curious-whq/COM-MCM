# `umcm/ir/__init__.py` 源码讲解

文件职责：汇总 µMCM 中间表示的公开类型与构造器。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–41 行）

```python
"""Public IR surface."""

from umcm.ir.completion import CompletionSpec, EventSlot
from umcm.ir.event import (
    EventCatalog,
    EventInstance,
    EventType,
    FieldSpec,
    Visibility,
)
from umcm.ir.expression import (
    Binary,
    Call,
    EventField,
    Expr,
    Ite,
    Literal,
    Nary,
    Symbol,
    Unary,
    binary,
    call,
    conjunction,
    disjunction,
    event_field,
    expr_from_dict,
    expr_to_dict,
    iter_event_fields,
    iter_literals,
    iter_symbols,
    literal,
    nary,
    substitute_event_ids,
    symbol,
    unary,
)
from umcm.ir.sort import BOOL, INT, STRING, Sort, address, bitvec, identifier, value
from umcm.ir.state import StateRequirement, StateUpdate, StateVariable
from umcm.ir.trace import PartialObservation, Trace
from umcm.ir.transformation import EventRole, Transformation

```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `__all__`（第 42–89 行）

```python
__all__ = [
    "BOOL",
    "INT",
    "STRING",
    "Binary",
    "Call",
    "CompletionSpec",
    "EventCatalog",
    "EventField",
    "EventInstance",
    "EventRole",
    "EventSlot",
    "EventType",
    "Expr",
    "FieldSpec",
    "Ite",
    "Literal",
    "Nary",
    "PartialObservation",
    "Sort",
    "StateRequirement",
    "StateUpdate",
    "StateVariable",
    "Symbol",
    "Trace",
    "Transformation",
    "Unary",
    "Visibility",
    "address",
    "binary",
    "bitvec",
    "call",
    "conjunction",
    "disjunction",
    "event_field",
    "expr_from_dict",
    "expr_to_dict",
    "identifier",
    "iter_event_fields",
    "iter_literals",
    "iter_symbols",
    "literal",
    "nary",
    "substitute_event_ids",
    "symbol",
    "unary",
    "value",
]
```

这是模块级常量或公开导出声明：`__all__` 保存all，供该对象的校验、转换或序列化逻辑使用。

