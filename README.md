# µMCM Foundation v0.8.0

这是第八轮底层基础设施，仍然与 FM-Agent 无关。BOOM 微架构行为由 YAML
中的 `Event + Transformation + State + Trace` 描述；Python 提供通用的 Trace
补全、层次抽象、架构投影、Execution Graph 构造和公理检查引擎。

v0.8 在 v0.7 的完整错误闭环之上加入：

```text
concrete microarchitectural Trace
        ↓  hierarchy_abstraction.yaml
retain architectural events
+ summarize relevant internal paths
+ hide cycle-level implementation events
        ↓
certified abstract Trace
        ↓
rf / co / fr / po / ppo
        ↓
Memory-model result
```

对于当前 BOOM witness：

```text
buggy: 36 concrete events → 11 abstract events → FORBIDDEN
fixed: 37 concrete events → 10 abstract events → ALLOWED
```

抽象前后生成的架构操作、关系和候选执行图集合完全相同。

> 当前实现是**具体 witness 的确定性层次抽象与细化检查**，不是任意 RTL
> 实现对抽象模型的通用 refinement theorem prover。

## 1. 层次抽象模型

新增目录：

```text
src/umcm/hierarchy/
├── model.py      # 可加载的 AbstractionSpec
└── engine.py     # abstract / certificate / refine / preservation
```

抽象规则由 YAML 加载。每条规则：

1. 匹配若干具体事件角色；
2. 用 `$variable` 统一操作身份、地址和值；
3. 产生一个摘要事件；
4. 隐藏不再需要的内部事件。

例如，L0 的长延迟读值来源被压缩为：

```text
DCache.LoadMiss(L0)
→ MSHR.PrimaryMissAccept(L0)
→ MSHR.AcquireBlock(L0)
→ MSHR.GrantData(L0, source=W1, value=1)
→ MSHR.DrainRPQLoad(L0)
→ DCache.LongLatencyLoadResponse(L0, 1)
→ LSU.LoadSucceeded(L0, 1)
```

对应一个摘要事件：

```text
Hierarchy.ReadFromEvidence(
    read_op_id=L0,
    write_op_id=W1,
    address=x,
    value=1,
    path=mshr_refill
)
```

因此抽象可以隐藏 MSHR 状态和中间接口，但不能丢失 `rf` 所需的来源信息。

## 2. 当前 BOOM 摘要事件

`hierarchy_abstraction.yaml` 生成四类边界事件：

- `Hierarchy.ReadFromEvidence`：保留 load 的具体 source write；
- `Hierarchy.CoherenceOrderEvidence`：保留同地址写的 coherence 顺序证据；
- `Hierarchy.CoherenceObservation`：压缩 Store → Probe → Release → observed；
- `Hierarchy.LoadLoadResolution`：压缩 LD–LD conflict 的 assert-only 或 squash 结果。

架构事件保持不变：

```text
Arch.InitWrite
Arch.Load
Arch.Store
Arch.CommitLoad
```

内部的 TLB、retry queue、DCache pipeline、ProbeUnit 和 MSHR 事件默认隐藏。

## 3. `rf` 和 `co` 来源不会因抽象而自由化

v0.8 的 graph model 支持两类可加载 hint：

```yaml
projection:
  rf_hints:
  - event_type: Hierarchy.ReadFromEvidence
    read_id_field: read_op_id
    write_id_field: write_op_id
    address_field: address
    value_field: value

  co_hints:
  - event_type: Hierarchy.CoherenceOrderEvidence
    before_write_id_field: before_write_id
    after_write_id_field: after_write_id
    address_field: address
```

`rf` hint 会把某个 read 的来源限制为指定 write，并检查地址和值一致。
`co` hint 会过滤同地址写的候选全序；冲突的顺序证据会被拒绝。

因此：

```text
完整 Trace / 有 provenance 的抽象 Trace：rf、co 可以被固定
普通部分 Trace：仍可枚举所有与观测兼容的 rf、co 补全
```

## 4. 抽象证书与细化检查

每个生成的摘要事件携带：

```text
abstraction spec name
summary rule name
source event IDs
source event types
```

抽象 Trace 的 metadata 还记录：

```text
source Trace SHA-256
retained event IDs
hidden event IDs
all summary-to-source mappings
preserved/dropped constraint counts
```

`umcm refine` 会从具体 Trace 重新执行同一抽象，并比较：

- 摘要事件集合；
- 字段和值；
- 约束；
- 抽象证书。

篡改 `write_op_id`、地址、值或 source mapping 都会导致 refinement 失败。

## 5. 运行抽象

### Buggy witness

```bash
PYTHONPATH=src python3 -m umcm abstract \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage7_buggy_completed.yaml \
  --abstraction examples/boom_load_load/hierarchy_abstraction.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml \
  --output stage8_buggy_abstract.yaml
```

预期：

```text
ABSTRACTED boom-cycle-events -> composed-memory-events:
  36 concrete event(s)
  11 output event(s)
  30 hidden event(s)
  5 summary event(s)

MEMORY-MODEL PRESERVATION:
  concrete=forbidden, abstract=forbidden
  PRESERVED
```

再检查抽象 Trace：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace stage8_buggy_abstract.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

仍然得到：

```text
InitX -rf-> L1
W1    -rf-> L0
InitX -co-> W1
L1    -fr-> W1
L0    -ppo-> L1

L1 -fr-> W1 -rfe-> L0 -ppo-> L1
MEMORY MODEL VIOLATION
```

### Fixed recovery witness

```bash
PYTHONPATH=src python3 -m umcm abstract \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage7_fixed_recovery_completed.yaml \
  --abstraction examples/boom_load_load/hierarchy_abstraction.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml \
  --output stage8_fixed_abstract.yaml
```

预期：

```text
37 concrete events → 10 output events
concrete=allowed, abstract=allowed
PRESERVED
```

由于 `L1` 已被 `order_fail → exception → squash` 撤销，没有
`Arch.CommitLoad(L1)`，因此它不会成为架构执行图节点。

## 6. 验证细化证书

```bash
PYTHONPATH=src python3 -m umcm refine \
  --schema examples/boom_load_load/event_types.yaml \
  --concrete examples/boom_load_load/stage7_buggy_completed.yaml \
  --abstract-trace examples/boom_load_load/stage8_buggy_abstract.yaml \
  --abstraction examples/boom_load_load/hierarchy_abstraction.yaml
```

预期：

```text
REFINEMENT VALID: every abstract event is backed by its rule sources
```

## 7. 关键文件

```text
examples/boom_load_load/
├── hierarchy_abstraction.yaml
├── rvwmo_load_load_fragment.yaml
├── stage7_buggy_completed.yaml
├── stage7_fixed_recovery_completed.yaml
├── stage8_buggy_abstract.yaml
├── stage8_fixed_recovery_abstract.yaml
├── stage8_buggy_execution_graph.yaml
└── stage8_fixed_recovery_execution_graph.yaml
```

## 8. 测试

```bash
PYTHONPATH=src pytest -q
```

预期：

```text
76 passed
```

新增测试覆盖：

- 抽象规则 YAML/JSON 往返；
- 36→11 和 37→10 的具体压缩结果；
- `rf` provenance 保持；
- `co` hint 对候选全序的过滤；
- 相互冲突的 `co` hint 拒绝；
- buggy 抽象前后均为 `FORBIDDEN`；
- fixed 抽象前后均为 `ALLOWED`；
- 架构 candidate graph 集合精确相同；
- 摘要事件篡改检测；
- `umcm abstract` 与 `umcm refine` CLI。
