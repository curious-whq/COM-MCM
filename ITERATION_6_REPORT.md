# Iteration 6 Report — L0 MSHR Refill and Full Architectural Outcome

## 目标

补齐 v0.5 尚未建模的 older load `L0=1` 路径，使微架构可行性模型不再把
`CommitLoad(L0,1)` 当作无来源的外部观察。

## 完成内容

### 1. Miss 与 MSHR 分配

```text
DCacheReqFire(L0)
→ LoadExecuted(L0)
→ DCache.LoadMiss(L0)
→ MSHR.PrimaryMissAccept(mshr=0,L0)
→ MSHR.RPQEnqueue(mshr=0,L0)
```

Primary accept 原子捕获 request identity，并把 MSHR FSM 从 `INVALID` 更新为
`REFILL_REQ`。RPQ 同周期保存 `op_id/ldq_idx/address`。

### 2. Acquire 与 refill

```text
REFILL_REQ
→ AcquireBlock
→ REFILL_RESP
→ GrantData(source=W1,value=1)
→ RefillComplete
→ DRAIN_RPQ_LOADS
```

Grant 通过 `source_op_id/address/value` 与架构 store `W1(x=1)` 连接。

### 3. RPQ direct response

```text
DRAIN_RPQ_LOADS
∧ RPQ contains L0
∧ line_value = 1
→ DrainRPQLoad(L0,1)
→ LongLatencyLoadResponse(L0,1)
→ LoadSucceeded(L0,1)
```

随后 `CommitLoad(L0,1)` 检查 L0 的 valid/executed/succeeded/value 状态。

### 4. Scoped exact composition

新增 `Transformation.output_when`：exact reverse obligation 只应用于符合输出侧
predicate 的输出。这样普通 hit 路径和 MSHR 路径可以共同产生
`LSU.LoadExecuted/LoadSucceeded`，而不会要求 L0 输出同时满足 L1 producer。

### 5. Buggy/fixed 差分

Buggy：

```text
FEASIBLE: Commit(L0,1) + Commit(L1,0)
```

Fixed recovery：

```text
FEASIBLE: Commit(L0,1) + Squash(L1)
```

Fixed + 同一 forbidden retirement target：

```text
INFEASIBLE: L1.valid 已被 recovery 清除
```

## 验收结果

```text
54 passed
compileall passed
buggy full witness FEASIBLE
fixed recovery witness FEASIBLE
fixed forbidden witness INFEASIBLE
```

## 暂未完成

- 尚未从已完成 Trace 生成 `rf/co/fr/ppo`；
- 尚未实现 Execution Graph relation algebra；
- 尚未运行 RVWMO 合法性检查；
- MSHR 当前是单 primary miss、单 RPQ entry 的 witness-oriented 摘要。
