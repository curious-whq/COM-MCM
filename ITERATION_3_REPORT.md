> **v0.3.1 语义修正：** 本报告最初把 ready/valid/fire 单列为“握手语义”。修正版明确：它们只是 `Transformation` 状态转换中的 guard 与接受事件；不存在独立的 Handshake IR。

# Iteration 3 Report — Persistent State and DCache Interface Transition

## 目标

在 v0.2 的有界事件补全之上，加入最小但真实可执行的持久状态语义，并将 BOOM 路径推进为：

```text
RetryIssue(L0)
→ TLBHit(L0)
→ DCacheReqValid(L0)
∧ DCacheReqReady
→ DCacheReqFire(L0)
```

同时验证 branch kill / exception 可以作为组合进来的外部防御，阻断同一个 witness。

## 实现

### 1. 新增状态 IR

新增：

- `StateVariable`
- `StateRequirement`
- `StateUpdate`

语义：

```text
requirements 读取事件周期开始时的 pre-state
updates 在 requirement 通过后原子写入 post-state
未写状态自动 stutter
同周期冲突写导致该执行不可行
```

### 2. Transformation 扩展

`Transformation` 可携带：

```text
state_requirements
state_updates
```

v0.3.1 修正后允许 `Transformation` 同时包含 input guard、output event 与状态读写。状态效果按完整的输入—输出绑定实例化，并且只有该转换实例发生时才激活；requirement/update 可锚定输入或输出角色。

### 3. 有界问题实例化

`BoundedProblem` 新增：

- `StateRequirementInstance`
- `StateUpdateInstance`

每个发生的输入事件绑定会生成具体的状态读写实例，并保留 Transformation 与事件绑定来源，便于错误说明。

### 4. 状态执行器

新增 `solver/state.py`：

- 构造初始状态；
- 按 active event cycle 排序；
- 在每个周期检查 pre-state；
- 聚合同周期更新；
- 检测冲突写；
- 输出 `StateStep` 和 `StateChange`；
- 返回首个状态拒绝原因。

### 5. 接口状态转换中的 ready/valid/fire

事件目录新增：

```text
LSU.TLBHit
LSU.DCacheReqValid
DCache.ReqReady
LSU.DCacheReqFire
Core.BranchKill
Core.Exception
```

模型把 `valid`、`ready` 作为普通 `Transformation` 的当周期 guard 观察，把 `fire` 作为请求接受事件；三者同周期、同端口，并保持 request 的 `op_id/ldq_idx/address`。这不是独立的握手语义层。

### 6. BOOM retry queue 摘要

当前单槽摘要保存：

```text
valid
op_id
ldq_idx
vaddr
```

`RetryEnqueue` 写入身份，`RetryIssue` 必须从 pre-state 读回完全相同的身份并清空 valid。

### 7. 防御路径

- 匹配的 branch kill 将 `valid := false`；
- exception 将 `valid := false`；
- 若它们发生在 enqueue 与 issue 之间，则后续 required issue/fire witness 不可行。

## 验收结果

### 单元测试

```text
35 passed
```

覆盖：

- 状态 schema 与 sort 检查；
- completion model YAML/JSON round-trip；
- retry identity 保持；
- 状态 stutter 与 atomic update；
- branch kill 阻断 issue；
- DCache fire 必须有 ready；
- v0.2 模型向后兼容。

### 正向 CLI

```text
FEASIBLE finite completion:
  13 events
  7 hidden events
  27 instantiated constraints
  2142 search nodes
```

补全事件：

```text
cycle 1: TLBMiss(L0)
cycle 2: RetryEnqueue(L0)
cycle 4: RetryIssue(L0)
cycle 4: TLBHit(L0)
cycle 4: DCacheReqValid(L0)
cycle 4: DCacheReqReady(port=0)
cycle 4: DCacheReqFire(L0)
```

状态轨迹：

```text
cycle 2: retry_queue.valid false → true
         retry_queue.op_id EMPTY → L0
         retry_queue.ldq_idx 63 → 0
         retry_queue.vaddr EMPTY_ADDR → x

cycle 4: retry_queue.valid true → false
```

### 负向 CLI

强制 branch kill 位于 enqueue 与 issue 之间：

```text
INFEASIBLE
RetryIssue requires retry_queue.valid == true,
but pre-state is false
```

## 代码边界

本轮没有实现：

- 完整 BOOM retry queue；
- 多 entry 状态数组；
- 通用 ready/valid channel object；
- Z3 后端；
- Execution Graph；
- RVWMO 公理；
- DCache hit/miss/refill；
- Probe/observed；
- LD–LD violation search。

这些边界是有意保留的。v0.3.1 的目标仍仅是让“同一 retry 请求的状态保留和 DCache 接受”成为可执行语义，而不是继续使用纯事件顺序近似。
