# Iteration 2 Report: Bounded Transformation and Trace Completion

## 本轮目标

在 v0.1 的 Event / Expression / Trace IR 上，加入第一套真正可运行的 Trace 可行性与隐藏事件补全机制，并跑通 BOOM TLB miss retry 路径的最小片段。

本轮只验证基础设施的三个能力：

1. 可以声明有限数量的隐藏微架构事件；
2. 可以用 Transformation 描述事件之间的身份和时序约束；
3. 可以从部分 Trace 补全一条满足这些约束的 witness。

本轮不声称已经验证完整 BOOM RTL。

## 已实现

### 1. `EventSlot`

Completion model 可以声明有限数量的候选隐藏事件。每个槽可以：

- 固定事件类型；
- 固定部分字段；
- 声明为查询中必须出现，或由求解器选择；
- 固定周期，或让求解器补全周期；
- 对缺失的必需字段自动创建类型化符号。

`required` 的精确定义是“当前 witness query 要求该事件出现”，而不是硬件的全局活性保证。

### 2. Role-based `Transformation`

Transformation 由：

```text
inputs
outputs
when
ensure
```

组成。输入角色按事件类型绑定，输出角色在有限候选事件中存在量化选择。规则会被确定性地展开为布尔约束：

```text
occurs(inputs) ∧ when
  ⇒ ∃ outputs. occurs(outputs) ∧ ensure
```

输出角色不隐含时间方向。`ensure` 可以规定输出比输入更晚，也可以规定输出是输入的更早因果前置事件。

### 3. Bounded Problem Builder

Problem builder 会：

- 合并部分 Trace 和隐藏事件槽；
- 给部分 Trace 中缺失的必需字段创建符号；
- 加入 Trace constraint；
- 加入 completion constraint；
- 加入每个发生事件的 cycle bound；
- 在所有类型匹配的事件绑定上实例化 Transformation。

### 4. Finite Feasibility Backend

当前后端不依赖 Z3，采用有界有限域搜索：

- 三值逻辑部分求值；
- 对确定为 false 的部分赋值立即剪枝；
- 优先选择 occurrence 与 identity 变量；
- 后选择周期变量；
- 返回具体字段和周期赋值。

### 5. Witness 物化

找到可行赋值后会生成完整 Trace：

- 未发生的可选槽被删除；
- 发生事件的符号字段被替换为具体值；
- 事件周期被具体化；
- 模型生成的事件带有 annotation；
- 输出 Trace 再次经过完整 schema 验证。

## BOOM 路径模型

最初的直接写法是：

```text
TLBMiss(L0) → RetryEnqueue(L0) → RetryIssue(L0)
```

若把这两条规则理解为全局 Transformation，它会不必要地暗示每次 TLB miss 或 enqueue 都最终产生 retry issue，混入一个错误的活性结论。

本轮最终采用 witness-goal 语义：

```text
required query goal: RetryIssue(L0)
```

然后反向补全因果支撑：

```text
RetryIssue(L0)
  → 存在更早的 RetryEnqueue(L0)

RetryEnqueue(L0)
  → 存在更早的 TLBMiss(L0)
```

同时限定选中的 bug 路径窗口：

```text
Arch.Load(L0)
  < TLBMiss(L0)
  < RetryEnqueue(L0)
  < Arch.Load(L1)
  < RetryIssue(L0)
```

求解结果：

```text
cycle 0: Arch.Load(L0)
cycle 1: TLBMiss(L0)
cycle 2: RetryEnqueue(L0)
cycle 3: Arch.Load(L1)
cycle 4: RetryIssue(L0)
```

这验证了：

- 隐藏事件选择；
- 反向因果补全；
- `op_id` 身份保持；
- 严格时序约束；
- 查询目标与硬件活性公理的分离。

额外回归测试取消 `RetryIssue` 的 required 标记，结果三个隐藏事件均不需要发生。这证明 causal-support 规则本身没有强迫所有 TLB miss 最终回放。

## 与 BOOM 源码的对应关系

模型中的事件来自以下实际路径结构：

```text
LDQ entry 因地址仍是虚拟地址而被 retry queue 选择
→ retry queue 保存 uop / ldq_idx
→ 调度器选择 load retry
→ retry 使用队列中的同一 uop 重新访问 TLB 和 DCache
```

本轮尚未逐周期编码这些 guard，而是把它们作为下一轮状态语义的目标。

## 测试

当前测试覆盖：

- v0.1 Event / Expression / Trace 行为；
- CompletionSpec YAML/JSON round-trip；
- Transformation 输出事件选择；
- `op_id` 保持；
- `L0 < miss < enqueue < L1 < issue` 严格周期顺序；
- required query goal annotation；
- 取消查询目标后不存在无条件活性；
- 时间界过小时返回 bounded infeasible；
- 固定 `cycle=0` 不被误判为缺失；
- 部分 Trace 中缺失的必需字段可被补全；
- 约束引用未知字段会被拒绝；
- `complete` CLI 输出和文件生成。

测试结果：

```text
24 passed
```

## 当前限制

- RetryIssue 是显式查询目标，不是由完整 BOOM bug 自动选择；
- 没有状态变量和状态更新；
- 没有 queue occupancy、ready/valid 或 enqueue/dequeue 状态；
- 没有 branch kill、exception 和 backpressure；
- 没有 DCache / Probe / MSHR 路径；
- 没有 Execution Graph 和 RVWMO checker；
- finite backend 的不可行结论仅相对于当前 bound。

## 下一轮

实现最小状态层：

```text
RetryIssue(L0)
→ TLB hit
→ DCacheReqFire(L0)
```

重点不是继续增加事件名称，而是让以下事实通过状态更新而非裸事件边表达：

```text
TLB miss 后 LDQ address_is_virtual = true
retry enqueue 后原 LDQ address.valid 被清除
queue entry 保留 op_id / ldq_idx / virtual address
retry issue 消费同一 queue entry
TLB hit 后重新写回 physical address
```
