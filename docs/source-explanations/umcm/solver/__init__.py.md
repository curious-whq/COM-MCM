# `umcm/solver/__init__.py` 源码讲解

文件职责：汇总轨迹补全求解器的公开 API。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–10 行）

```python
"""Trace-completion solver backends."""

from umcm.solver.completion import (
    CompletionResult,
    CompletionStatus,
    complete_trace,
)

from umcm.solver.state import StateCheckResult, StateStep, check_state_semantics

```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `__all__`（第 11–19 行）

```python
__all__ = [
    "CompletionResult",
    "CompletionStatus",
    "StateCheckResult",
    "StateStep",
    "check_state_semantics",
    "complete_trace",
]

```

这是模块级常量或公开导出声明：`__all__` 保存all，供该对象的校验、转换或序列化逻辑使用。

## 模块说明与依赖（第 20–20 行）

```python
from umcm.solver.state import StateCheckResult, StateStep, check_state_semantics
```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

