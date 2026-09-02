# µMCM Foundation v0.5.0

这是第五轮底层基础设施。项目仍然与 FM-Agent 无关：当前使用手写的
`Event + Transformation + State + Trace`，逐步构造 BOOM Load–Load 顺序错误的
微架构可行执行。

v0.5.0 在 v0.4.0 已完成的路径上加入了真正的 LD–LD 搜索和恢复差分：

```text
L1 hit old value 0
→ L1.executed = true
→ L1.succeeded = true
→ Probe/Release
→ L1.observed = true

L0 TLB retry
→ DCache request accepted
→ LD–LD search
→ same-address observed-younger conflict
```

随后分别建立两个模型：

```text
buggy:
  conflict → assert monitor
  order_fail 保持 false
  L1=0 可以退休

fixed reference:
  conflict → order_fail
           → MINI_EXCEPTION_MEM_ORDERING
           → squash L1
  同一个 L1=0 退休目标不可行
```

这里的 `LSU.AssertViolation` 被明确建模为**非功能性监视事件**。它记录
`assert(false.B)` 被触发，但不会自动产生 `order_fail`、exception 或 squash。

当前版本仍未生成最终的 `rf/co/fr/ppo/hb` Execution Graph；下一轮将把本轮的
微架构 witness 投影到架构事件并检测 `rf → ppo → fr` 环。

## 1. 新增事件

```text
LSU.LDLDSearch
LSU.LDLDConflict
LSU.AssertViolation
LSU.LoadOrderFail
Core.MemoryOrderingException
Core.SquashLoad
```

关键字段保留：

```text
older/younger op_id
older/younger ldq_idx
address
exception cause
squash reason
```

## 2. 新增状态

```text
LSU.ldq.L1.order_fail
LSU.ldq.L1.squashed
LSU.ldq.L1.executing_now
```

其中 `executing_now = false` 对应源码中的：

```scala
!s1_executing_loads(i)
```

本轮路径使用更强但足够的 witness 条件：

```text
L1.valid
∧ L1.addr_valid
∧ !L1.addr_is_virtual
∧ L1.executed
∧ L1.succeeded
∧ L1.observed
∧ !L1.executing_now
∧ same_address(L0, L1)
∧ older(L0, L1)
```

## 3. Buggy 模型

运行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage5_trace.yaml \
  --model examples/boom_load_load/load_load_buggy_completion.yaml \
  --output completed_stage5_buggy.yaml
```

预期：

```text
FEASIBLE

cycle 13: LDLDSearch(L0)
cycle 13: LDLDConflict(L0,L1)
cycle 13: AssertViolation

order_fail = false
squashed   = false
CommitLoad(L1,0) 可发生
```

## 4. Fixed recovery 模型

先只检查恢复路径，不要求错误 load 退休：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage5_recovery_trace.yaml \
  --model examples/boom_load_load/load_load_fixed_completion.yaml \
  --output completed_stage5_fixed_recovery.yaml
```

预期：

```text
FEASIBLE

cycle 13: LDLDConflict
cycle 13: LoadOrderFail(L1)
cycle 14: MemoryOrderingException(L1)
cycle 15: SquashLoad(L1)

order_fail = true
squashed   = true
valid      = false
```

再对同一个错误退休目标运行 fixed 模型：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage5_trace.yaml \
  --model examples/boom_load_load/load_load_fixed_completion.yaml
```

预期退出码为 `1`：

```text
INFEASIBLE

CommitLoad(L1,0) requires LSU.ldq.L1.valid == true,
but recovery has already squashed L1 and made valid == false.
```

## 5. 源码对应关系

本轮模型依据给定 BOOM v4 LSU 源码：

```text
lsu.scala:1117–1120
  retry load 在翻译成功后触发 do_ld_search

lsu.scala:1238–1255
  older search + same address/mask + younger executed/succeeded
  + !s1_executing_loads + observed
  当前仅 assert(false.B)，order_fail/failed_load 赋值被注释

lsu.scala:1458–1475
  ldq_order_fail 会生成 MINI_EXCEPTION_MEM_ORDERING

lsu.scala:1749–1765
  load 退休要求 LDQ entry 有效、executed/forwarded 且 succeeded
```

`exception → squash` 是父级恢复逻辑的抽象边界摘要；本轮不展开整个 ROB。

## 6. 测试

```bash
PYTHONPATH=src pytest -q
```

预期：

```text
47 passed
```

测试覆盖：

- buggy conflict → assertion-only 路径可行；
- assertion 不更新 `order_fail`；
- buggy 路径允许 `CommitLoad(L1,0)`；
- fixed 路径产生 order-fail、exception 和 squash；
- fixed 模型阻止相同错误退休结果；
- 没有 `observed` 状态时不能形成本轮 LD–LD conflict；
- v0.1–v0.4 所有回归继续通过。
