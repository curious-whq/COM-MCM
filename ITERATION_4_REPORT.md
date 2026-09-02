# Iteration 4 Report

## 目标

在 v0.3.1 已完成的 L0 retry 路径上，补全年轻 Load L1 的旧值返回和 coherence exposure：

```text
L1 request accepted
→ DCache hit old x=0
→ LDQ.executed/succeeded
→ W1 store x=1
→ ProbeUnit release x
→ LDQ[L1].observed
→ L0 retry
```

本轮不检查 RVWMO，也不进入最终 LD–LD conflict 分支。

## 实现

### Event

新增：

```text
DCache.LoadHit
DCache.LoadNack
DCache.ProbeReceive
LSU.LoadExecuted
LSU.LoadSucceeded
```

细化：

```text
DCache.LoadResponse
DCache.ProbeRelease
LSU.LoadObserved
```

### State

新增 L1 LDQ 摘要状态和 ProbeUnit pending request 摘要。状态由统一 Transformation 读写。

### Abstraction

- DCache data/tag array 被摘要成 `accepted request → LoadHit → LoadResponse`。
- Store/L2/coherence 被摘要成 `Arch.Store → feasible ProbeReceive`。
- ProbeUnit 中间状态被隐藏，但 probe 的 address/source identity 通过持久状态保留到 release。

## 正向结果

```text
FEASIBLE
23 total events
17 hidden events
65 instantiated constraints
108 search nodes
```

关键状态：

```text
cycle 5:  L1.executed  false → true
cycle 7:  L1.succeeded false → true; value → 0
cycle 9:  Probe pending false → true; capture W1/x
cycle 10: Probe pending true → false
cycle 11: L1.observed false → true
cycle 12: L0 retry queue valid true → false
```

## 负向结果

```text
release(y) + required observed(L1,x) → INFEASIBLE
nack(L1) → FEASIBLE, executed=false, succeeded=false
nack(L1) + required succeeded(L1) → INFEASIBLE
```

## 回归

```text
42 passed
```

v0.1、v0.2、v0.3/v0.3.1 的示例与测试继续通过。

## 下一步

将 L0 retry 的 LCAM search 与 L1 的三个状态连接：

```text
executed/succeeded/observed
→ LD–LD conflict guard
→ buggy assert-only path
→ fixed order_fail path
```
