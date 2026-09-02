# `umcm/errors.py` 源码讲解

文件职责：集中定义项目可预期异常的类型层次。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–3 行）

```python
"""Project-specific exception types."""


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 类 `UMCMError`（第 4–7 行）

```python
class UMCMError(Exception):
    """Base class for all expected µMCM errors."""


```

项目所有可预期错误的基类，便于调用方统一捕获。

## 类 `SchemaError`（第 8–11 行）

```python
class SchemaError(UMCMError):
    """Raised when an event schema is malformed or inconsistent."""


```

表示事件模式缺失、非法或内部不一致。

## 类 `TraceValidationError`（第 12–15 行）

```python
class TraceValidationError(UMCMError):
    """Raised when a trace does not conform to its event catalog."""


```

表示轨迹不符合事件目录或引用规则。

## 类 `ExpressionTypeError`（第 16–19 行）

```python
class ExpressionTypeError(UMCMError):
    """Raised when an expression is not well typed."""


```

表示表达式操作数或结果类型不合法。

## 类 `SerializationError`（第 20–23 行）

```python
class SerializationError(UMCMError):
    """Raised when YAML/JSON content cannot be decoded into the IR."""


```

表示 YAML/JSON 数据无法安全转换为 IR。

## 类 `SolverError`（第 24–27 行）

```python
class SolverError(UMCMError):
    """Raised when a feasibility backend cannot encode or solve a problem."""


```

表示求解问题无法编码或求解。

## 类 `BackendUnavailableError`（第 28–31 行）

```python
class BackendUnavailableError(SolverError):
    """Raised when a requested optional solver backend is not installed."""


```

表示请求的可选求解后端尚未安装。

## 类 `CompletionError`（第 32–35 行）

```python
class CompletionError(UMCMError):
    """Raised when a completion specification cannot be instantiated."""


```

表示补全模型无法实例化。

## 类 `GraphError`（第 36–39 行）

```python
class GraphError(UMCMError):
    """Raised when an execution graph cannot be projected or constructed."""


```

表示轨迹无法投影或构造执行图。

## 类 `AxiomError`（第 40–43 行）

```python
class AxiomError(UMCMError):
    """Raised when an axiom or relation specification is malformed."""


```

表示公理或关系配置非法。

## 类 `AbstractionError`（第 44–45 行）

```python
class AbstractionError(UMCMError):
    """Raised when a hierarchy/abstraction model cannot be applied."""
```

表示层次抽象配置无法应用。

