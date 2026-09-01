# µMCM Foundation v0.2

这是第二轮底层基础设施代码。它仍然与 FM-Agent 完全无关，目标是先建立一个可运行的微架构 Trace 可行性检查内核。

当前版本已经实现：

- `Sort` 与类型化 `Expression AST`；
- `EventType / EventInstance / EventCatalog`；
- 完整或部分观测的 `Trace`；
- 有界候选隐藏事件 `EventSlot`；
- 带输入/输出事件角色的 `Transformation`；
- Transformation 在有限事件宇宙上的实例化；
- 依赖无关的有限域 Trace 补全器；
- YAML / JSON 往返序列化；
- `validate` 与 `complete` 命令行工具；
- BOOM `TLBMiss → RetryEnqueue → RetryIssue` 的第一个可运行路径模型。

当前版本还没有实现 Execution Graph、`rf/co/fr/ppo/hb`、RVWMO 检查、层次抽象和完整状态机语义。

## 1. Transformation 语义

一个 Transformation 定义输入事件角色和输出事件角色。例如：

```text
input : issue   : LSU.RetryIssue
output: enqueue : LSU.RetryEnqueue
```

其语义是：

```text
对于每一个实际发生、且满足 when 的输入事件绑定，
必须存在一组实际发生的输出事件绑定，使 ensure 成立。
```

形式上：

```text
occurs(inputs) ∧ when(inputs)
  ⇒ ∃ outputs. occurs(outputs) ∧ ensure(inputs, outputs)
```

这里的 `output` 表示“存在量化的支撑事件”，**不天然表示时间上更晚**。时间方向必须由 `ensure` 中的 `< / <= / same_cycle` 等约束显式给出。因此同一套 IR 可以表达：

```text
前向结果：Request → Response
反向支撑：Response → 必须存在更早的 Request
```

当前实现将规则在显式给定的有限 `EventSlot` 上展开，因此不存在无限事件生成问题。

## 2. `required` 是查询目标，不是活性公理

`EventSlot.required: true` 的含义是：

> 当前这一次 witness 查询要求该事件出现。

它不表示所有硬件执行最终都必须出现该事件，也不表示每次 TLB miss 都必须最终 retry。这个区分对微架构建模很重要：flush、exception、branch kill 或长期 backpressure 都可能终止或延迟一条路径。

本轮将：

```text
RetryIssue(L0)
```

设为 required query goal，再由 causal-support Transformation 向前补全：

```text
RetryIssue(L0)
  → 必须存在更早的 RetryEnqueue(L0)

RetryEnqueue(L0)
  → 必须存在更早的 TLBMiss(L0)
```

这表达的是：

> 搜索一条确实走到 retry issue 的可行路径，并检查该目标所需的因果前置事件能否同时成立。

它没有错误地加入：

```text
TLBMiss(L) → 最终一定 RetryIssue(L)
```

对应回归测试会取消 `RetryIssue` 的 required 标记；此时三个隐藏事件都可以不发生，证明 Transformation 本身没有引入无条件活性。

## 3. BOOM 示例当前做了什么

`partial_trace.yaml` 固定架构观测：

```text
L0、L1 是同一 Hart 上的两条同地址 load；
最终观察 Commit(L0, 1) 和 Commit(L1, 0)。
```

`retry_completion.yaml` 声明三个有界隐藏事件槽：

```text
l0_tlb_miss      : 可选因果前置事件
retry_enqueue_0  : 可选因果前置事件
retry_issue_0    : required query goal，op_id 固定为 L0
```

并要求选中的 witness 满足：

```text
Arch.Load(L0)
  < TLBMiss(L0)
  < RetryEnqueue(L0)
  < Arch.Load(L1)
  < RetryIssue(L0)
```

其中 `op_id` 通过 Transformation 从查询目标向前传播，因此求解器会补全：

```text
TLBMiss.op_id = RetryEnqueue.op_id = RetryIssue.op_id = L0
```

这与 BOOM 源码中的局部机制对应：TLB miss 的 load 会按 LDQ age 被选择并写入 `retry_queue`，队列保留其 `uop` 和 `ldq_idx`；当调度条件成立时，同一 load 再次从队列发射。

需要明确：当前版本只证明这段**有界、抽象路径约束可满足**。它还没有建模真实 retry queue 容量、ready/valid、branch kill、exception、TLB 状态更新或 DCache 接受条件。

## 4. 安装与测试

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

无需安装也可以运行：

```bash
PYTHONPATH=src python3 -m umcm validate \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml
```

预期输出：

```text
VALID partial trace: 6 event(s), 2 constraint(s), 10 event type(s)
```

执行隐藏事件补全：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml \
  --model examples/boom_load_load/retry_completion.yaml \
  --output completed_retry.yaml
```

当前确定性后端的输出为：

```text
FEASIBLE finite completion: 9 event(s), 3 hidden event(s) added, 12 instantiated constraint(s), 128 search node(s)
  + cycle 1: l0_tlb_miss [LSU.TLBMiss, op_id='L0']
  + cycle 2: retry_enqueue_0 [LSU.RetryEnqueue, op_id='L0']
  + cycle 4: retry_issue_0 [LSU.RetryIssue, op_id='L0']
WROTE completed_retry.yaml
```

求解器还会具体化：

```text
cycle 0: Arch.Load(L0)
cycle 3: Arch.Load(L1)
```

因此完整顺序是：

```text
L0 < TLBMiss(L0) < RetryEnqueue(L0) < L1 < RetryIssue(L0)
```

## 5. 有限域后端的边界

当前 `finite` 后端是一个确定性的有界搜索器，而不是通用 SMT 求解器：

- `bool` 枚举 `false/true`；
- `int` 与较大的 bit-vector 在 `0..horizon` 中搜索；
- `op_id/address/value` 等领域 sort，只使用问题中已经出现的具体值作为有限域；
- 在每次部分赋值后进行三值表达式求值，尽早剪枝；
- `INFEASIBLE` 只表示在当前事件槽、字段域和时间界内不可行。

这种后端足以验证 IR、Transformation 和 witness query 的语义，并保持项目无需额外依赖。后续可以在不修改模型格式的情况下增加 Z3 后端。

## 6. 目录结构

```text
src/umcm/ir/sort.py              轻量 sort
src/umcm/ir/expression.py        类型化表达式 AST
src/umcm/ir/event.py             事件 schema 与动态事件
src/umcm/ir/trace.py             完整/部分 Trace
src/umcm/ir/transformation.py    输入/输出角色 Transformation
src/umcm/ir/completion.py        EventSlot 与 CompletionSpec
src/umcm/solver/problem.py       有界规则实例化
src/umcm/solver/evaluator.py     三值表达式求值
src/umcm/solver/finite.py        有限域可行性后端
src/umcm/solver/completion.py    补全 API 与 witness 物化
src/umcm/cli.py                  validate / complete
examples/boom_load_load/         BOOM 案例输入
```

## 7. 下一轮

下一轮在现有框架上加入最小状态语义，并把路径推进到：

```text
RetryIssue(L0)
→ TLB hit
→ DCache request accepted
```

具体包括：

- `StateVar` 与版本化状态快照；
- guarded state update；
- retry queue 中 `op_id/ldq_idx/address` 的保持；
- ready/valid fire 的最小语义；
- branch kill / exception 作为路径守卫；
- Transformation 同时产生事件约束和状态约束。
