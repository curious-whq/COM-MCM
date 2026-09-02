# µMCM Foundation v0.3.1

这是第三轮底层基础设施的语义修正版。项目仍然与 FM-Agent 完全无关：当前目标是先建立一套可手写、可执行、可测试的微架构 Trace 可行性语义，再逐步接入 Execution Graph 与内存模型公理。

v0.3.1 在 v0.2 的有界事件补全之上保留**持久状态语义**，并将 `valid/ready/fire` 明确归入普通的 **Transformation 状态转换语义**，不再把“握手”视为独立语义层。BOOM 示例推进到：

```text
TLBMiss(L0)
→ RetryEnqueue(L0)
→ RetryIssue(L0)
→ TLBHit(L0)
→ DCacheReqValid(L0)
∧ DCacheReqReady
→ DCacheReqFire(L0)
```

当前版本已经实现：

- `Sort` 与类型化 `Expression AST`；
- `EventType / EventInstance / EventCatalog`；
- 完整或部分观测的 `Trace`；
- 有界候选隐藏事件 `EventSlot`；
- 带输入/输出事件角色的 `Transformation`；
- `StateVariable / StateRequirement / StateUpdate`；
- 基于 pre-state / atomic post-state 的状态执行语义；
- 未更新状态自动 stutter；
- 同周期冲突写检测；
- 由普通 `Transformation` 表达的接口转换 guard 与接受事件；
- 依赖无关的有限域 Trace 补全器；
- 状态历史写入 completed Trace metadata；
- `validate` 与 `complete` 命令行工具；
- BOOM retry 到 DCache request fire 的正向 witness；
- branch kill / exception 清空 retry queue 的防御路径；
- v0.2 completion model 向后兼容。

当前版本尚未实现 Execution Graph、`rf/co/fr/ppo/hb`、RVWMO 检查和通用层次抽象。

## 1. 状态语义

### 1.1 StateVariable

一个状态变量表示在事件之间持久存在的标量状态。例如，当前 BOOM 单槽 retry queue 摘要使用：

```text
LSU.retry_queue.valid
LSU.retry_queue.op_id
LSU.retry_queue.ldq_idx
LSU.retry_queue.vaddr
```

这不是完整的八项硬件队列，而是针对当前 witness 的单槽抽象。它保留了判断该路径是否可行所需的身份字段。

### 1.2 StateRequirement

状态要求在锚定事件发生的**周期开始时**读取 pre-state。例如：

```text
RetryIssue(L0) requires:
  retry_queue.valid   == true
  retry_queue.op_id   == L0
  retry_queue.ldq_idx == L0.ldq_idx
  retry_queue.vaddr   == L0.vaddr
```

因此，只有先前真正 enqueue 过同一个动态请求，`RetryIssue` 才可行。

### 1.3 StateUpdate

状态更新在该周期所有 requirement 通过后原子写入 post-state：

```text
RetryEnqueue:
  valid   := true
  op_id   := enqueue.op_id
  ldq_idx := enqueue.ldq_idx
  vaddr   := enqueue.vaddr

RetryIssue:
  valid := false
```

同一周期没有写入的状态自动保持原值。若两个 active update 在同一周期向同一状态写入不同值，当前后端将该执行判为不可行。

v0.3.1 允许同一条 `Transformation` 同时具有输入 guard、输出事件和状态读写。状态 requirement/update 可以锚定到输入或输出角色；只有某个完整的输入—输出绑定实际发生并满足 `when/ensure` 时，相应状态效果才会激活。这样接口接受事件与后续 FSM 更新可以写在同一套状态转换语义中。

## 2. 接口状态转换中的 valid / ready / fire

`valid/ready/fire` 不是独立于状态转换系统的另一套语义。v0.3.1 将它们解释为同一条接口转换中的三个观测：

```text
LSU.DCacheReqValid
DCache.ReqReady
LSU.DCacheReqFire
```

其中 `valid` 和 `ready` 是当周期的组合 guard 观察，`fire` 是 guard 成立后发生的接受事件。它们全部通过普通 `Transformation` 约束：

```text
Fire(op, port, cycle)
→ Valid(op, port, cycle)
∧ Ready(port, cycle)
```

并且：

```text
Valid(op, port, cycle)
∧ Ready(port, cycle)
→ Fire(op, port, cycle)
```

同时保持：

```text
fire.op_id   = valid.op_id
fire.ldq_idx = valid.ldq_idx
fire.address = valid.address
fire.port    = valid.port = ready.port
```

`DCacheReqFire(L0)` 是本轮的 required query goal。这里的 `Fire` 只是沿用 Chisel 名称，语义上表示“请求被 DCache 接受”的转换事件；它不是独立的握手层，也不是活性公理。模型文件只包含 `transformations:`，不再包含单独的 `handshakes:` 段。

对应的抽象形式是：

```text
Transformation {
  guard: ReqValid(L0) ∧ ReqReady(port0)
  emit:  DCacheReqFire(L0, port0)
}
```

该转换使用 `exact: true`：正向表示 `valid ∧ ready → fire`，反向只要求每个已观测的 `fire` 必须由同周期、同端口的 `valid/ready` 支撑。它仍是一条普通 `Transformation` 的精确定义，而不是第二套语义。

## 3. BOOM 正向 witness

运行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml \
  --model examples/boom_load_load/retry_dcache_completion.yaml \
  --output completed_retry_dcache.yaml
```

当前确定性后端输出：

```text
FEASIBLE finite completion: 13 event(s), 7 hidden event(s) added, 27 instantiated constraint(s), 2142 search node(s)
  + cycle 1: l0_tlb_miss [LSU.TLBMiss, ldq_idx=0, op_id='L0', vaddr='x']
  + cycle 2: retry_enqueue_0 [LSU.RetryEnqueue, ldq_idx=0, op_id='L0', vaddr='x']
  + cycle 4: retry_issue_0 [LSU.RetryIssue, ldq_idx=0, op_id='L0', vaddr='x']
  + cycle 4: l0_tlb_hit [LSU.TLBHit, ldq_idx=0, op_id='L0', paddr='x', vaddr='x']
  + cycle 4: dcache_req_valid_0 [LSU.DCacheReqValid, address='x', ldq_idx=0, op_id='L0', port=0]
  + cycle 4: dcache_req_ready_0 [DCache.ReqReady, port=0]
  + cycle 4: dcache_req_fire_0 [LSU.DCacheReqFire, address='x', ldq_idx=0, op_id='L0', port=0]
STATE transitions:
  @ cycle 2: LSU.retry_queue.op_id: 'EMPTY' -> 'L0', LSU.retry_queue.ldq_idx: 63 -> 0, LSU.retry_queue.vaddr: 'EMPTY_ADDR' -> 'x', LSU.retry_queue.valid: False -> True
  @ cycle 4: LSU.retry_queue.valid: True -> False
```

关键点不是事件名字按顺序出现，而是：

```text
enqueue 写入的 op_id / ldq_idx / vaddr
=
issue 从 pre-state 中读取的 op_id / ldq_idx / vaddr
=
TLB hit 与 DCache request 携带的身份
```

## 4. 外部防御路径

`retry_dcache_branch_kill.yaml` 强制在 enqueue 与 issue 之间出现匹配的 branch kill：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml \
  --model examples/boom_load_load/retry_dcache_branch_kill.yaml
```

结果应为：

```text
INFEASIBLE ...
retry_issue ... requires LSU.retry_queue.valid == True,
but pre-state is False
```

原因是：

```text
RetryEnqueue(L0) 使 valid := true
BranchKill(L0)    使 valid := false
RetryIssue(L0)    要求 valid == true
```

这正是组合语义需要表达的效果：局部 retry 路径并不预设“外面没有防御”；一旦外部 kill 被组合进同一 Trace，该 witness 会自然变为不可行。

模型中也提供了 `Core.Exception`，它会清空 retry queue。默认正向查询中 kill 和 exception 都是可选事件，求解器为构造目标 witness 会选择它们不发生。

## 5. 安装与测试

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

无需安装也可以运行：

```bash
PYTHONPATH=src pytest -q
```

本版本基线：

```text
35 passed
```

验证输入 Trace：

```bash
PYTHONPATH=src python3 -m umcm validate \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml
```

预期输出：

```text
VALID partial trace: 6 event(s), 2 constraint(s), 16 event type(s)
```

## 6. v0.2 向后兼容

原来的事件关系模型仍可运行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml \
  --model examples/boom_load_load/retry_completion.yaml \
  --output completed_retry_v02_compat.yaml
```

它仍补全三个隐藏事件：

```text
TLBMiss(L0)
→ RetryEnqueue(L0)
→ RetryIssue(L0)
```

## 7. 有限域后端的边界

当前 `finite` 后端是确定性的有界搜索器，不是通用 SMT 求解器：

- `bool` 枚举 `false/true`；
- `int` 与小 bit-vector 在有限域内搜索；
- `op_id/address/value` 等领域 sort 使用问题中已经出现的具体值；
- 每次部分赋值后用三值求值提前剪枝；
- 状态语义目前在完整候选 assignment 上执行；
- `INFEASIBLE` 只表示在当前事件槽、字段域和 cycle horizon 内不可行。

当前 retry queue 是单槽摘要；它不声称精确模拟 BOOM 的八项 `BranchKillableQueue`，也没有覆盖同时 enqueue/dequeue、多 entry 仲裁和所有 branch-mask 细节。

## 8. 目录结构

```text
src/umcm/ir/state.py             状态变量、pre-state requirement、post-state update
src/umcm/ir/transformation.py    事件规则与状态副作用
src/umcm/ir/completion.py        EventSlot、CompletionSpec、状态声明
src/umcm/solver/problem.py       有界规则与状态规则实例化
src/umcm/solver/state.py         具体状态轨迹执行器
src/umcm/solver/finite.py        有限域可行性后端
src/umcm/solver/completion.py    witness 物化与状态 metadata
src/umcm/cli.py                  validate / complete
examples/boom_load_load/         BOOM 正向与防御路径模型
```

## 9. 下一轮建议

下一轮继续沿 BOOM bug 路径扩展，而不是立即接入 FM-Agent：

```text
L1 DCache hit → Response(L1, 0) → LDQ[L1].executed/succeeded
Probe → LSU Release → LDQ[L1].observed
```

届时需要加入：

- 每个 `op_id`/`ldq_idx` 的参数化 LDQ 状态；
- DCache hit-response 摘要；
- ProbeUnit 到 LSU release 的跨模块事件映射；
- release 对同 cache block load 的 `observed := true` 更新。

完成这一步后，再连接 L0 retry 的 LD–LD search 和被删除的 `order_fail` 恢复路径。
