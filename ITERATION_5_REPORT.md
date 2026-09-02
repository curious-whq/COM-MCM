# Iteration 5 Report — BOOM LD–LD Conflict and Recovery Differential

## 目标

将 v0.4 已建立的：

```text
L1=0 → executed/succeeded → Probe → observed → L0 retry
```

接入 BOOM LSU 的 LD–LD search，并对比当前 assertion-only 路径与参考修复路径。

## 完成内容

### 1. LD–LD 搜索

新增：

```text
L0 DCacheReqFire
→ LSU.LDLDSearch(L0)
```

搜索要求 L0 与架构 `Arch.Load(L0)` 身份一致，并保持地址和 LDQ index。

### 2. 冲突形成

新增：

```text
LDLDSearch(L0)
∧ po(L0,L1)
∧ same_address(L0,L1)
∧ L1.valid/address-valid/physical
∧ L1.executed/succeeded
∧ L1.observed
∧ !L1.executing_now
→ LDLDConflict(L0,L1)
```

这是一个具体 witness 条件，不宣称覆盖所有 byte-mask 组合。

### 3. Buggy 路径

```text
LDLDConflict
→ AssertViolation
```

`AssertViolation` 是非功能性监视事件：

```text
order_fail 保持 false
squashed 保持 false
```

因此 `CommitLoad(L1,0)` 仍满足本模型的退休前状态条件。

### 4. Fixed 路径

```text
LDLDConflict
→ LoadOrderFail
→ MemoryOrderingException
→ SquashLoad
```

状态更新：

```text
order_fail := true
squashed   := true
valid      := false
```

因此同一个 `CommitLoad(L1,0)` 查询不可行。

## 验收结果

### Buggy + forbidden retirement target

```text
FEASIBLE
26 events
20 hidden events
```

### Fixed + recovery-only trace

```text
FEASIBLE
26 events
22 hidden events
```

### Fixed + same forbidden retirement target

```text
INFEASIBLE
```

核心拒绝原因：恢复已使 `LSU.ldq.L1.valid = false`，而退休需要有效 LDQ entry。

## 测试

```text
47 passed
```

## 暂未完成

- L0 miss/refill 后读取 `1` 的 MSHR 路径尚未接入本轮模型；
- 尚未从 Trace 自动生成 `rf/co/fr/ppo`；
- 尚未执行 RVWMO Execution Graph 检查；
- fixed 模型是恢复被重新启用后的参考模型，不是对某个现有修复提交的声明。
