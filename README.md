# µMCM Foundation v0.6.0

这是第六轮底层基础设施。项目仍与 FM-Agent 无关：BOOM 模型继续由 YAML
中的 `Event + Transformation + State + Trace` 手工描述，Python 只提供通用加载、
实例化、有限补全和状态执行引擎。

v0.6 在 v0.5 的真实 LD–LD 冲突路径之后，补齐 older load `L0` 通过 MSHR
得到新值 `1` 并退休的路径：

```text
L0 DCache request
→ DCache miss
→ primary MSHR accept
→ RPQ retain L0 identity
→ AcquireBlock
→ GrantData(x=1, source=W1)
→ refill complete
→ s_drain_rpq_loads
→ long-latency response(L0,1)
→ L0.succeeded/value := true/1
→ CommitLoad(L0,1)
```

与既有路径组合后，buggy 模型现在能够补全完整架构结果：

```text
L0 = 1
L1 = 0
两条 load 均退休
```

fixed reference 模型仍会通过 `order_fail → exception → squash` 阻止 L1=0
退休，但不会阻止更老的 L0 经 MSHR 得到 1。

> v0.6 仍只检查微架构 Trace 可行性。`rf/co/fr/ppo` Execution Graph 和
> RVWMO 公理检查留到下一轮。

## 1. 新增事件

```text
DCache.LoadMiss
MSHR.PrimaryMissAccept
MSHR.RPQEnqueue
MSHR.AcquireBlock
MSHR.GrantData
MSHR.RefillComplete
MSHR.DrainRPQLoad
DCache.LongLatencyLoadResponse
```

关键身份始终保留：

```text
mshr_id
op_id
ldq_idx
address
source_op_id
value
```

## 2. 新增 MSHR 状态摘要

```text
MSHR.0.state
MSHR.0.req_op_id / req_ldq_idx / req_address
MSHR.0.rpq_valid / rpq_op_id / rpq_ldq_idx / rpq_address
MSHR.0.line_value / line_source_op_id
```

本轮只建模一个 primary miss 和一个 RPQ load entry，但状态转换是真实持久状态：

```text
INVALID
→ REFILL_REQ
→ REFILL_RESP
→ DRAIN_RPQ_LOADS
```

同时为 L0 加入：

```text
LSU.ldq.L0.valid
LSU.ldq.L0.executed
LSU.ldq.L0.succeeded
LSU.ldq.L0.value
```

## 3. scoped exact Transformation

v0.6 新增 `output_when`。它解决同一种输出事件由多条路径产生时的组合问题。
例如 L0 和 L1 都会产生 `LSU.LoadExecuted`，但分别由 retry-MSHR 路径和普通
hit 路径支持：

```yaml
exact: true
output_when:
  node: binary
  op: eq
  left:  executed.op_id
  right: L0
```

含义是：该 Transformation 只对满足 `executed.op_id == L0` 的输出承担
“必须存在输入支持”的 exact 义务；L1 输出由另一条 Transformation 负责。

## 4. 运行完整 buggy witness

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_trace.yaml \
  --model examples/boom_load_load/load_load_buggy_mshr_completion.yaml \
  --output completed_stage6_buggy.yaml
```

预期：

```text
FEASIBLE
36 total events
30 hidden events added

cycle 14: DCache.LoadMiss(L0)
cycle 14: MSHR.PrimaryMissAccept(L0)
cycle 14: MSHR.RPQEnqueue(L0)
cycle 15: MSHR.AcquireBlock(L0)
cycle 16: MSHR.GrantData(L0, source=W1, value=1)
cycle 16: MSHR.RefillComplete(L0, value=1)
cycle 17: MSHR.DrainRPQLoad(L0, value=1)
cycle 17: DCache.LongLatencyLoadResponse(L0, value=1)
cycle 17: LSU.LoadSucceeded(L0, value=1)
cycle 18: CommitLoad(L0,1)
cycle 19: CommitLoad(L1,0)
```

## 5. 运行 fixed differential

允许 L0 完成、但不要求 L1 退休：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_recovery_trace.yaml \
  --model examples/boom_load_load/load_load_fixed_mshr_completion.yaml \
  --output completed_stage6_fixed_recovery.yaml
```

预期 `FEASIBLE`：L0 仍通过 MSHR 得到 1，L1 被 squash。

再对要求两条 load 都退休的 `stage6_trace.yaml` 运行 fixed 模型，预期退出码 1：

```text
INFEASIBLE
L1 commit requires valid LDQ entry,
but order-fail recovery already made L1.valid = false.
```

## 6. 测试

```bash
PYTHONPATH=src pytest -q
```

预期：

```text
54 passed
```

测试额外覆盖：

- MSHR 请求/RPQ/response 始终保持 L0 身份；
- GrantData 必须与可见 store `W1` 的地址和值一致；
- RPQ 身份错配会阻断 long-latency response；
- L0/L1 两条 exact producer 可组合，不再互相错误约束；
- fixed 模型保留 L0=1 路径，同时阻止 L1=0 退休。
