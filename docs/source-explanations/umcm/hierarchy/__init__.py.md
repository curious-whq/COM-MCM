# `umcm/hierarchy/__init__.py` 源码讲解

文件职责：汇总层次化轨迹抽象与精化检查接口。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–23 行）

```python
"""Hierarchical trace abstraction and refinement checks."""

from umcm.hierarchy.engine import (
    AbstractionCertificate,
    AbstractionResult,
    MemoryModelPreservationCheck,
    RefinementCheck,
    SummaryEvidence,
    abstract_trace,
    check_memory_model_preservation,
    check_refinement,
)
from umcm.hierarchy.model import (
    ABSTRACTION_SCHEMA_VERSION,
    AbstractionSpec,
    EventRoleSpec,
    MatchValue,
    OutputValue,
    RetainSpec,
    SummaryEventSpec,
    SummaryRuleSpec,
)

```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `__all__`（第 24–41 行）

```python
__all__ = [
    "ABSTRACTION_SCHEMA_VERSION",
    "AbstractionCertificate",
    "AbstractionResult",
    "AbstractionSpec",
    "EventRoleSpec",
    "MatchValue",
    "MemoryModelPreservationCheck",
    "OutputValue",
    "RefinementCheck",
    "RetainSpec",
    "SummaryEventSpec",
    "SummaryEvidence",
    "SummaryRuleSpec",
    "abstract_trace",
    "check_memory_model_preservation",
    "check_refinement",
]
```

这是模块级常量或公开导出声明：`__all__` 保存all，供该对象的校验、转换或序列化逻辑使用。

