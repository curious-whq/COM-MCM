# Iteration 7 Report — Execution Graph and Axiom Checking

## 目标

v0.6 已经能够补全一个完整微架构 witness：

```text
L1 hit old x=0
→ Probe marks L1 observed
→ L0 retry finds LD–LD conflict
→ buggy path only fires assertion
→ L0 miss/refill gets x=1
→ Commit(L0,1) and Commit(L1,0)
```

v0.7 的目标是回答第二个基础问题：

> 对一个已经判定为微架构可行的 Trace，它投影出的架构执行是否满足所加载的内存模型公理？

## 实现

### 1. Architectural projection

`ProjectionSpec` 从 YAML 加载事件类型和字段映射。当前 BOOM 模型将：

```text
Arch.InitWrite
Arch.Store
Arch.Load + Arch.CommitLoad
```

投影为 `MemoryOperation`。只有 committed load 才进入完整架构图；已被 squash、没有退休的推测 load 被隐藏。

### 2. Candidate graph construction

`rf` 和 `co` 不是从微架构周期顺序直接猜测：

- `rf` 根据 read 的 committed value 与同地址 write 候选生成；
- 微架构 provenance 事件可收紧 `rf`，本例用 `MSHR.GrantData.source_op_id`；
- `co` 对每个地址枚举 write total order；
- 初始写固定在 ordinary write 之前；
- 如果有多个候选，检查器遍历全部候选。

### 3. Relations

生成：

```text
po
rf
rfe
co
fr = rf^-1 ; co
ppo(load-load-different-write)
```

加载派生：

```text
hb = ppo ∪ rfe
ar = hb ∪ fr ∪ co
```

### 4. Axioms

Axiom 由 YAML 加载。当前 Load–Load fragment 使用：

```text
acyclic(ppo ∪ rfe ∪ fr ∪ co)
```

这只是为当前 BOOM witness 实现的最小片段，不声称覆盖完整 RVWMO 的 fence、
dependency、LR/SC、I/O 或逐字节语义。

## BOOM 结果

投影节点：

```text
InitX: init write x=0
W1:    Hart1 write x=1
L0:    Hart0 older read x=1
L1:    Hart0 younger read x=0
```

关系：

```text
rf  = { InitX→L1, W1→L0 }
co  = { InitX→W1 }
fr  = { L1→W1 }
po  = { L0→L1 }
ppo = { L0→L1 }
rfe = { InitX→L1, W1→L0 }
```

违反环：

```text
L1 -fr-> W1 -rfe/rf-> L0 -ppo-> L1
```

因此所有候选图都违反当前公理，结果为 `FORBIDDEN`。

## Fixed recovery 对照

恢复模型补全出：

```text
LDLDConflict(L0,L1)
→ LoadOrderFail(L1)
→ MemoryOrderingException(L1)
→ SquashLoad(L1)
```

由于 `L1` 没有退休，架构投影只包含 `InitX / W1 / L0`，关系图无环，
结果为 `ALLOWED`。这验证了图层不会把被 squash 的推测执行误当成架构事件。

## 其他对照

```text
L0=0, L1=1
```

对应：

```text
rf = {InitX→L0, W1→L1}
fr = {L0→W1}
ppo = {L0→L1}
```

没有环，结果为 `ALLOWED`。

如果两条 load 都读 `InitX`，它们的 `rf` 来源相同，当前 RVWMO Load–Load
规则不生成 `ppo(L0,L1)`。

## 验证

```text
pytest:     67 passed
compileall: passed
editable install: passed (--no-build-isolation)
```

## 下一步

v0.8 应加入 `Hierarchy/Abstraction`：

- 将详细 MSHR 路径隐藏为 `DCache.LongLatencyLoadResponse` 摘要；
- 将 ProbeUnit 内部状态隐藏为 `DCache.ProbeRelease`；
- 检查具体 Trace 与抽象 Trace 投影出的架构图一致；
- 在相同公理模型下分别检查 concrete/abstract Trace，建立第一条 refinement 回归。
