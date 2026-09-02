# µMCM Foundation v0.10.0

这是第十轮底层基础设施，仍然与 FM-Agent 无关。

当前主链路：

```text
Partial Trace
   ↓ trace roles / finite parameter binding
Parameterized LSU / DCache / MSHR / Coherence / ROB templates
   ↓ explicit module composition
Transformation + State feasibility
   ↓
Completed microarchitectural Trace
   ↓ architectural projection
rf / co / fr / po / ppo Execution Graph
   ↓ axioms
ALLOWED / FORBIDDEN
```

## v0.10 的核心变化

v0.9 虽然已经把模型拆成 LSU、DCache、MSHR、Coherence、ROB，但模块 YAML 仍然是这一条 witness 的具体实例，例如：

```text
L0 / L1 / W1
LSU.ldq.L0 / LSU.ldq.L1
MSHR.0
```

v0.10 增加了 Trace-driven parameterization。模块模板现在写成：

```text
${older_load.op_id}
${older_load.ldq_idx}
${younger_load.op_id}
${younger_load.ldq_idx}
${older_load.mshr_id}
${visible_store.op_id}
```

组合器从输入 Trace 中解析 semantic roles，再生成具体 `ModuleSpec`。

## Trace role 示例

```yaml
roles:
  - name: older_load
    event_type: Arch.Load
    where:
      fields.hart: 0
      fields.program_index: 0
    exports:
      op_id: fields.op_id
      address: fields.address
      ldq_idx: annotations.microarch.ldq_idx
      mshr_id: annotations.microarch.mshr_id
```

精确占位符保留类型：

```yaml
ldq_idx: ${older_load.ldq_idx}
```

若 Trace 中该值为 `13`，实例化结果仍是整数 `13`。

嵌入式占位符用于状态名：

```text
LSU.ldq[${older_load.ldq_idx}].valid
MSHR[${older_load.mshr_id}].state
```

## 参数化 BOOM 模板

```text
examples/boom_load_load/modular/templates/
├── lsu_buggy.template.yaml
├── lsu_fixed.template.yaml
├── dcache.template.yaml
├── mshr.template.yaml
├── coherence.template.yaml
├── rob_buggy.template.yaml
└── rob_fixed.template.yaml
```

对应组合：

```text
modular/buggy_parameterized_composition.yaml
modular/fixed_parameterized_composition.yaml
```

## 证明没有写死 witness identity

`stage10_parameterized_trace.yaml` 故意使用：

```text
older load    = LoadAlpha, LDQ[13]
younger load  = LoadBeta,  LDQ[7]
visible store = StoreGamma
MSHR           = MSHR[3]
address        = data0
```

而模板无需任何修改。

Buggy completion 自动得到：

```text
LSU.ldq[13].executed = true
LSU.ldq[7].observed = true
MSHR[3].state = DRAIN_RPQ_LOADS
```

并生成：

```text
StoreGamma --rf--> LoadAlpha
LoadAlpha  --ppo-> LoadBeta
LoadBeta   --fr--> StoreGamma
```

因此仍然 `FORBIDDEN`。

Fixed 模型对相同 `LoadBeta=0` 退休目标返回 `INFEASIBLE`；恢复 Trace 则 `ALLOWED`。

## 运行

测试：

```bash
PYTHONPATH=src pytest -q
```

参数化组合：

```bash
PYTHONPATH=src python3 -m umcm compose \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage10_parameterized_trace.yaml \
  --composition examples/boom_load_load/modular/buggy_parameterized_composition.yaml \
  --output composed_buggy.yaml
```

补全：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage10_parameterized_trace.yaml \
  --composition examples/boom_load_load/modular/buggy_parameterized_composition.yaml \
  --output completed_buggy.yaml
```

检查执行图：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace completed_buggy.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

## 当前边界

v0.10 做的是**有限、Trace 驱动的具体实例化**：

- 操作名不再写死；
- LDQ/MSHR entry 编号不再写死在模板；
- 当前示例从 Trace annotation 得到 `ldq_idx/mshr_id`；
- 尚未让求解器自动选择未知的 LDQ/MSHR allocation；
- 尚未把两条 load 的专用 witness 规则扩展成任意数量 Load 的完整 Load Queue 模型。

下一轮 v0.11 将开始扩展通用 Load-side LSQ：allocation、地址翻译、retry/wakeup、response/nack、executed/succeeded、release/observed、LD–LD search、order failure 与 commit。
