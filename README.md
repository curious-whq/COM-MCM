# µMCM Foundation v0.4.0

这是第四轮底层基础设施。项目仍然与 FM-Agent 完全无关：当前目标是先用手写的 `Event + Transformation + State + Trace`，构造并检查 BOOM Load–Load 错误所需的微架构可行路径。

v0.4.0 在 v0.3.1 的 `L0 TLB miss → retry queue → DCache request accepted` 路径上，加入了年轻 Load `L1` 的旧值命中、ProbeUnit release 以及 LDQ `observed` 状态：

```text
L0: TLBMiss
    → RetryEnqueue

L1: DCacheReqFire
    → LDQ.executed := true
    → DCacheHit(value=0)
    → DCacheResponse(value=0)
    → LDQ.succeeded := true
    → LDQ.value := 0

W1: store x=1
    → ProbeReceive(x)
    → ProbeRelease(x)
    → LDQ[L1].observed := true

L0: RetryIssue
    → DCacheReqFire
```

当前版本尚未执行最终的 LD–LD search，也尚未生成 `rf/co/fr/ppo/hb` Execution Graph。下一轮将把 `L0 retry` 与源码中的 `assert(false.B)` 分支连接起来。

## 1. 本轮新增的 Event

```text
DCache.LoadHit
DCache.LoadNack
DCache.ProbeReceive
LSU.LoadExecuted
LSU.LoadSucceeded
```

同时细化了已有事件：

```text
DCache.LoadResponse
DCache.ProbeRelease
LSU.LoadObserved
```

所有跨模块事件都保存必要身份：

```text
op_id / ldq_idx / address / port / source_op_id
```

## 2. 本轮新增的持久状态

### L1 的 LDQ 摘要

```text
LSU.ldq.L1.valid
LSU.ldq.L1.addr_valid
LSU.ldq.L1.addr_is_virtual
LSU.ldq.L1.address
LSU.ldq.L1.executed
LSU.ldq.L1.succeeded
LSU.ldq.L1.observed
LSU.ldq.L1.value
```

状态更新为：

```text
DCacheReqFire(L1)
→ executed := true

DCacheResponse(L1, 0)
→ succeeded := true
→ value := 0

ProbeRelease(x) 且 same_block(L1.address, x)
→ observed := true

DCacheNack(L1)
→ executed := false
→ succeeded 保持 false
```

### ProbeUnit 摘要

```text
DCache.probe.pending
DCache.probe.address
DCache.probe.source_op_id
```

它保留：

```text
ProbeReceive(W1, x)
→ 捕获 source_op_id/address
→ pending := true

ProbeRelease(W1, x)
→ 必须匹配已捕获的 Probe
→ pending := false
```

ProbeUnit 的 metadata read、MSHR interaction、writeback 等中间 FSM 状态在本轮被隐藏；这里只保留组合所需的边界身份和先后关系。

## 3. Transformation 仍是唯一操作语义

本轮没有增加独立“握手语义”。请求接受仍由普通 Transformation 表示：

```text
ReqValid ∧ ReqReady
→ DCacheReqFire
```

其余路径同样由 Transformation 表示：

```text
DCacheReqFire(L1)
→ LoadExecuted(L1)

LoadHit(L1, 0)
→ LoadResponse(L1, 0)

LoadResponse(L1, 0)
→ LoadSucceeded(L1, 0)

ProbeReceive(W1, x)
→ ProbeRelease(W1, x)

LoadObserved(L1, x)
→ 必须存在同 cache block 的 ProbeRelease
```

其中一部分规则用于正向状态转换，一部分规则用于给 query goal 寻找因果支撑事件。它们都使用同一个 `Transformation` IR。

## 4. 层次抽象方式

本轮没有完整展开 Store Queue、L2、TileLink 和 ProbeUnit 全部状态，而是采用可行路径摘要：

```text
Store 侧：
Arch.Store(W1, x=1)
→ feasible ProbeReceive(W1, x)

DCache 命中侧：
accepted request
→ response-eligible hit
→ response(value=0)

ProbeUnit：
ProbeReceive
→ capture pending probe state
→ ProbeRelease
```

抽象隐藏内部事件，但保留：

```text
请求身份
地址
返回值
Probe 来源
必要顺序
持久状态更新
```

## 5. 正向 witness

运行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage4_trace.yaml \
  --model examples/boom_load_load/young_load_probe_completion.yaml \
  --output completed_stage4.yaml
```

预期核心输出：

```text
FEASIBLE finite completion

cycle 4:  L1 DCacheReqFire
cycle 5:  L1 LoadExecuted
cycle 6:  L1 DCacheHit(value=0)
cycle 7:  L1 DCacheResponse / LoadSucceeded(value=0)
cycle 9:  ProbeReceive(W1, x)
cycle 10: ProbeRelease(W1, x)
cycle 11: L1 LoadObserved
cycle 12: L0 RetryIssue / DCacheReqFire
```

状态结果：

```text
LSU.ldq.L1.executed  = true
LSU.ldq.L1.succeeded = true
LSU.ldq.L1.value     = 0
LSU.ldq.L1.observed  = true
DCache.probe.pending = false
```

## 6. 两类负向检查

### 6.1 release 地址不同

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage4_trace.yaml \
  --model examples/boom_load_load/young_load_probe_address_mismatch.yaml
```

模型提供一条真实可支撑的 `W2: store y → probe y → release y` 路径，但仍要求：

```text
LoadObserved(L1, x)
```

结果：

```text
INFEASIBLE
```

因为 `release(y)` 不能把 `load(x)` 标记为 observed。

### 6.2 DCache nack

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage4_trace.yaml \
  --model examples/boom_load_load/young_load_nack_completion.yaml \
  --output completed_nack.yaml
```

结果可行，但最终状态为：

```text
executed  = false
succeeded = false
observed  = false
value      = UNSET_VALUE
```

强制同一次 attempt 同时 `nack` 和 `succeeded`：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage4_trace.yaml \
  --model examples/boom_load_load/young_load_nack_plus_success.yaml
```

结果：

```text
INFEASIBLE
```

## 7. 安装与测试

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

也可以不安装：

```bash
PYTHONPATH=src pytest -q
```

v0.4.0 基线：

```text
42 passed
```

## 8. 当前边界

当前版本尚未实现：

- `L0 retry → LD–LD search → assert(false.B)`；
- L0 在 Probe 后 miss、MSHR refill 并返回 `1`；
- `Commit(L0,1)` 与 `Commit(L1,0)`；
- Execution Graph；
- `rf/co/fr/ppo/hb`；
- RVWMO 合法性检查；
- 通用 `Hierarchy/Abstraction` IR；
- 从 Chisel 自动提取模型；
- FM-Agent 接入。

## 9. 下一阶段

Iteration 5 将连接：

```text
L1.executed = true
L1.succeeded = true
L1.observed = true

L0 RetryIssue
→ do_ld_search
→ Older(L0,L1)
→ SameAddress(L0,L1)
→ LLConflict(L0,L1)
```

并区分：

```text
buggy：LLConflict → AssertFailure，但不设置 order_fail
fixed：LLConflict → order_fail → memory-ordering exception
```
