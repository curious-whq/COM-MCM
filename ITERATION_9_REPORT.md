# Iteration 9 Report — Module Composition

## 目标

把 v0.8 中针对 BOOM Load–Load witness 的单体 CompletionSpec 拆成可独立加载的
LSU、DCache、MSHR、Coherence、ROB 模型，并通过类型化接口组合；组合后的
Buggy/Fixed 结果必须与单体模型一致。

## 实现

新增：

```text
src/umcm/composition/
├── model.py
├── engine.py
└── __init__.py
```

核心类型：

```text
ModuleSpec
ModulePort
ModuleReference
PortEndpoint
ConnectionSpec
CompositionSpec
CompositionResult
```

### 模块所有权

模块拥有自己的 slots、state variables、Transformations 和 constraints。

两项强制限制：

1. Stateful Transformation 只能访问同一个 ModuleSpec 声明的状态；
2. Transformation 中使用的 Event type 必须由模块 slot 或 port 声明。

这防止模块绕过连接清单直接读取其他模块状态或隐式依赖其他模块事件。

### 连接模式

`shared_event`：两端看到同一边界事件，Event type 必须完全相同。

`event_map`：两端采用不同 Event type，组合器生成 exact Transformation，按照
`field_map` 复制字段，并可保持同周期。

### BOOM 模块

```text
modular/modules/
├── lsu_buggy.yaml
├── lsu_fixed.yaml
├── dcache.yaml
├── mshr.yaml
├── coherence.yaml
├── rob_buggy.yaml
└── rob_fixed.yaml
```

当前连接数为 21，覆盖：

```text
ROB ↔ LSU
LSU ↔ DCache
DCache ↔ MSHR
Store/Probe/Grant ↔ Coherence
```

## 结果

### Buggy composition

```text
5 modules
21 connections
36 slots
32 state variables
37 transformations
21 constraints
```

直接从 composition 完成：

```text
FEASIBLE
36 total events
30 hidden events added
```

架构图：

```text
rf  = {InitX→L1, W1→L0}
co  = {InitX→W1}
fr  = {L1→W1}
ppo = {L0→L1}
```

检测到：

```text
L1 -fr-> W1 -rfe/rf-> L0 -ppo-> L1
```

结论：`FORBIDDEN`。

### Fixed composition

```text
5 modules
21 connections
36 slots
32 state variables
40 transformations
19 constraints
```

Recovery Trace 可行：

```text
LoadOrderFail(L1)
→ MemoryOrderingException(L1)
→ SquashLoad(L1)
→ LSU.ldq.L1.valid := false
```

执行图只保留 InitX、W1、L0，结论为 `ALLOWED`。

对 fixed composition 强制要求 `CommitLoad(L1, 0)` 时为 `INFEASIBLE`，诊断指出
commit 需要 `LSU.ldq.L1.valid == true`，但 squash 已清除该状态。

## 等价性

回归测试逐事件比较模块化和单体模型：

```text
event type
cycle
occurs
fields
final state
rf/co/fr/ppo candidate graphs
memory-model verdict
```

Buggy 两者完全相同；Fixed 恢复和错误 commit 阻断也保持一致。

## 验证

```text
pytest: 86 passed
compileall: passed
Buggy modular completion: FEASIBLE
Buggy graph: FORBIDDEN
Fixed recovery completion: FEASIBLE
Fixed graph: ALLOWED
Fixed forbidden commit: INFEASIBLE
```

## 当前限制与下一步

当前模块仍包含特定 `L0/L1/W1` 槽位。`shared_event` 目前也以全局 Event type
表示同一物理接口动作，尚未提供多实例 channel 隔离。下一轮需要实现参数化
Module template、instance/channel identity，以及基于输入 Trace/配置的有限实例化，
消除操作名、LDQ index 和 MSHR index 的写死。
