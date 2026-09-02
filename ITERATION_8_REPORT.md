# Iteration 8 Report — Hierarchy / Abstraction

## 目标

在不改变现有 Transformation、Trace completion 和 Execution Graph 引擎的前提下，
把 BOOM witness 的周期级内部事件压缩为少量可组合边界事件，同时保持：

```text
architectural operations
rf provenance
co evidence
memory-model result
```

## 实现

### 1. 可加载抽象语言

`AbstractionSpec` 支持：

```text
roles + field unification
ordered path matching
summary-event emission
retain / hide
metadata retention
match cardinality checks
```

规则中的 `$name` 表示跨事件统一的值。例如，MSHR 路径中的 request、grant、
response 和 success 必须具有同一个 `$read / $address / $value / $mshr`。

### 2. 摘要事件和 provenance

当前 BOOM 模型生成：

```text
2 × ReadFromEvidence
1 × CoherenceOrderEvidence
1 × CoherenceObservation
1 × LoadLoadResolution
```

每个摘要事件在 annotations 中保存规则名和所有 source event IDs。
Trace metadata 保存 source SHA-256 和完整 abstraction certificate。

### 3. Coherence-order hint

新增 `COHintSpec`。它不会凭周期猜测 `co`，而是只消费模型明确指定的
coherence-order evidence；多个 hint 会共同过滤每地址 write total order，矛盾时
返回 `GraphError`。

### 4. Preservation / refinement

- `check_refinement`：从具体 Trace 重算抽象，检查事件、字段、约束和证书。
- `check_memory_model_preservation`：比较抽象前后的全部 architectural candidate graphs
  及最终 ALLOWED/FORBIDDEN 结论。

## BOOM 结果

### Buggy

```text
36 concrete events
→ 6 retained architectural events + 5 summaries
→ 11 abstract events
→ 1 candidate graph
→ FORBIDDEN
```

保留关系：

```text
rf  = { InitX→L1, W1→L0 }
co  = { InitX→W1 }
fr  = { L1→W1 }
ppo = { L0→L1 }
```

### Fixed

```text
37 concrete events
→ 5 retained architectural events + 5 summaries
→ 10 abstract events
→ 1 candidate graph
→ ALLOWED
```

L1 的内部执行仍可在摘要中表示为 `outcome=squash`，但由于没有退休，它不会被
投影为架构 read。

## 验证

```text
pytest: 76 passed
compileall: passed
buggy abstraction preservation: passed
fixed abstraction preservation: passed
refinement check: passed
co-hint ambiguity/conflict tests: passed
```

## 当前边界

本轮没有证明任意具体模块实现都 refinement 一个抽象契约。它证明的是：对于给定
完整 witness Trace，抽象事件可由指定具体事件链确定性重建，并且本案例需要的
Execution Graph 信息不会因隐藏内部事件而丢失。
