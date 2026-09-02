# `umcm/__init__.py` 源码讲解

文件职责：定义 µMCM 顶层包的公开版本信息。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–5 行）

```python
"""µMCM Foundation package."""

from umcm.ir import *  # noqa: F401,F403
from umcm.hierarchy import *  # noqa: F401,F403

```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `__version__`（第 6–6 行）

```python
__version__ = "0.8.0"
```

这是模块级常量或公开导出声明：`__version__` 保存version，供该对象的校验、转换或序列化逻辑使用。

