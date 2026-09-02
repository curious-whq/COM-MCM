# µMCM Foundation v0.7.0

这是第七轮底层基础设施，仍然与 FM-Agent 无关。BOOM 微架构行为继续由
YAML 中的 `Event + Transformation + State + Trace` 描述；Python 提供通用的
Trace 补全、架构投影、Execution Graph 构造、关系代数和公理检查引擎。

v0.7 在 v0.6 的完整微架构 Trace 之后加入：

```text
completed microarchitectural Trace
→ architectural projection
→ candidate Execution Graphs
→ po / rf / rfe / co / fr / ppo
→ hb / ar derived relations
→ loaded Axiom checks
```

对 BOOM buggy 模型，系统现在能够自动得到：

```text
W1  -rf/rfe-> L0
L0  -ppo----> L1
L1  -fr-----> W1
```

并报告该关系环违反当前实现的 RVWMO Load–Load 片段。

> `rvwmo_load_load_fragment.yaml` 只覆盖本案例需要的同地址 Load–Load
> preserved-order 规则及相应关系环检查，不是完整 RVWMO 实现。

## 1. 新增模块

```text
src/umcm/graph/
├── relation.py      # finite relation algebra and labeled cycle search
├── execution.py     # MemoryOperation and ExecutionGraph
├── model.py         # loadable Projection / DerivedRelation / Axiom model
├── builder.py       # Trace → candidate rf/co graphs
└── checker.py       # axiom checking across all candidates
```

### Execution Graph 节点

当前架构投影识别：

```text
Arch.InitWrite → init_write
Arch.Store     → write
Arch.Load + Arch.CommitLoad → read(value)
```

微架构内部事件不会直接成为架构图节点，但可提供投影证据。例如：

```text
MSHR.GrantData(op_id=L0, source_op_id=W1, value=1)
```

会把 `L0` 的 `rf` 候选约束到 `W1`。

## 2. 关系生成

基础引擎生成：

- `po`：同 hart 按 `program_index` 排序；
- `rf`：每个 committed read 从同地址、同值 write 中选择来源；
- `co`：枚举每个地址上的 write total order，初始写位于最前；
- `fr = rf^-1 ; co`；
- `rfe`：跨 hart 的 `rf`；
- `ppo`：当前加载的 `load_load_different_write` 规则。

`rvwmo_load_load_fragment.yaml` 再加载派生关系：

```text
hb = ppo ∪ rfe
ar = hb ∪ fr ∪ co
```

关系代数基础设施支持：

```text
union
intersection
difference
inverse
composition
transitive_closure
```

## 3. 公理模型

公理从 YAML 加载，而不是写在 BOOM Python 代码中：

```yaml
axioms:
- name: rvwmo_load_load_order_fragment
  kind: acyclic
  relations: [ppo, rfe, fr, co]
```

当前 checker 支持：

```text
acyclic
irreflexive
empty
```

如果 `rf` 或 `co` 存在多个候选，系统枚举所有候选图。只要至少一个图满足全部
公理，结果就是 `ALLOWED`；只有所有候选都违反公理，才报告 `FORBIDDEN`。

## 4. 运行 BOOM 完整闭环

先生成完整微架构 Trace：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_trace.yaml \
  --model examples/boom_load_load/load_load_buggy_mshr_completion.yaml \
  --output completed_stage7_buggy.yaml
```

再构造 Execution Graph 并检查公理：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace completed_stage7_buggy.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml \
  --output stage7_buggy_graph.yaml
```

预期输出：

```text
EXECUTION GRAPH: 4 operation(s), 1 candidate(s)

rf:  InitX->L1, W1->L0
co:  InitX->W1
fr:  L1->W1
ppo: L0->L1

MEMORY MODEL VIOLATION: rvwmo-load-load-fragment-v0.7
cycle:
  L1 -fr-> W1
  W1 -rfe/rf-> L0
  L0 -ppo-> L1
```

检测到违反时命令退出码为 `1`；允许时为 `0`。

### Fixed recovery 对照

恢复版本中，`L1` 产生 `order_fail → exception → squash`，因此没有
`Arch.CommitLoad(L1)`。架构投影只保留已退休的操作，并隐藏该推测执行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_recovery_trace.yaml \
  --model examples/boom_load_load/load_load_fixed_mshr_completion.yaml \
  --output completed_stage7_fixed.yaml

PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace completed_stage7_fixed.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

预期只投影 `InitX / W1 / L0`，结果为 `MEMORY MODEL ALLOWED`。

## 5. 对照样例

允许的值演化：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage7_allowed_trace.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

预期：

```text
L0=0, L1=1
MEMORY MODEL ALLOWED
```

两条 load 都读同一个初始写时：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage7_same_write_trace.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

此时两条 load 的 `rf` 来源相同，因此本片段不生成 Load–Load `ppo`。

## 6. 测试

```bash
PYTHONPATH=src pytest -q
```

预期：

```text
67 passed
```

测试覆盖：

- v0.1–v0.6 全部回归；
- `inverse / compose / closure` 关系代数；
- Trace 到四个架构操作的投影；
- `rf/co/fr/po/ppo/rfe/hb/ar` 精确边集合；
- BOOM forbidden cycle；
- fixed recovery 中被 squash、未退休的 L1 不进入架构图；
- allowed control；
- 相同 `rf` 来源时不生成 Load–Load `ppo`；
- 多个同值 write 时枚举多个 `rf/co` 候选；
- MSHR `source_op_id/address/value` 与架构 `rf` 不一致时拒绝；
- Execution Graph 与 graph-model YAML/JSON 往返序列化。
