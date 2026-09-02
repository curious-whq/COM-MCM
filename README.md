# µMCM Foundation v0.9.0

这是第九轮底层基础设施，仍然与 FM-Agent 无关。项目现在支持：

```text
独立模块模型
  LSU / DCache / MSHR / Coherence / ROB
          ↓ typed ports + explicit connections
组合后的微架构 Transformation 系统
          ↓ finite Trace completion
完整微架构 Trace
          ↓ architecture projection
rf / co / fr / po / ppo Execution Graph
          ↓ axioms
ALLOWED / FORBIDDEN
```

v0.9 的核心变化是：BOOM Load–Load witness 不再由一个大型 completion YAML
描述，而是由五个可独立加载的模块模型和一张显式连接清单组合得到。

## 1. 模块模型

每个模块使用 `umcm.module.v0.9.0`：

```yaml
schema_version: umcm.module.v0.9.0
name: lsu
ports: ...
slots: ...
state_variables: ...
transformations: ...
constraints: ...
```

模块只拥有自己的：

- 候选事件槽；
- 持久状态；
- Transformation；
- 局部约束；
- 类型化输入/输出端口。

当前 BOOM 示例位于：

```text
examples/boom_load_load/modular/modules/
├── lsu_buggy.yaml
├── lsu_fixed.yaml
├── dcache.yaml
├── mshr.yaml
├── coherence.yaml
├── rob_buggy.yaml
└── rob_fixed.yaml
```

状态所有权是严格局部的：一个模块的 Transformation 不能读取或修改另一个
模块声明的状态。跨模块行为必须通过端口事件传递。

此外，Transformation 中使用的每一种事件类型都必须由该模块的 slot 或 port
显式声明，不能绕过组合清单隐式依赖其他模块事件。

## 2. 接口和连接

端口声明包含：

```text
name
input / output
event_type
required_connection
```

组合文件使用 `umcm.composition.v0.9.0`，显式列出模块和连接：

```text
examples/boom_load_load/modular/
├── buggy_composition.yaml
└── fixed_composition.yaml
```

当前支持两种连接。

### `shared_event`

两侧观察同一个物理边界事件。例如：

```text
LSU.dcache_req_valid
    → DCache.lsu_req_valid

DCache.req_fire
    → LSU.dcache_req_fire

DCache.probe_release
    → LSU.dcache_probe_release

MSHR.drain_rpq_load
    → DCache.mshr_drain_rpq_load
```

两端必须声明完全相同的 Event type。

### `event_map`

两侧使用不同 Event type 时，组合器生成一条精确 Transformation：

```text
source event
→ target event
```

并按照 `field_map` 复制身份、地址、数据等字段；可选择要求同周期。该模式已经有
单元测试覆盖，供后续把子模块内部事件映射成父模块边界事件使用。

## 3. 组合器检查

`compose_modules()` 会检查：

- 模块文件存在且声明名称与引用名称一致；
- port 的 Event type 存在；
- source 必须是 output，target 必须是 input；
- `shared_event` 两端类型相同；
- `event_map` 字段存在且 Sort 兼容；
- required port 已连接；
- 一个 input port 不得有多个驱动；
- slot、state 和 Transformation 名称跨模块不冲突；
- Transformation 只能使用模块显式声明的 slot/port 事件；
- Transformation 只能访问本模块状态。

组合后仍生成普通 `CompletionSpec`，因此已有 finite completion 后端无需修改。

## 4. BOOM 模块划分

Buggy 组合包含：

| 模块 | 端口 | Slots | 状态 | Transformations |
|---|---:|---:|---:|---:|
| LSU | 17 | 15 | 19 | 21 |
| DCache | 12 | 11 | 3 | 8 |
| MSHR | 4 | 6 | 10 | 6 |
| Coherence | 3 | 0 | 0 | 2 |
| ROB | 7 | 4 | 0 | 0 |

合计：

```text
5 modules
21 connections
36 slots
32 state variables
37 transformations
21 composition constraints
```

Fixed 组合复用同一个 DCache、MSHR 和 Coherence 模型，只替换：

```text
lsu_buggy  → lsu_fixed
rob_buggy  → rob_fixed
```

Fixed 模型共 40 条 Transformation，其中恢复链被明确拆成：

```text
LSU.LoadOrderFail
→ LSU emits Core.MemoryOrderingException
→ ROB emits Core.SquashLoad
→ LSU consumes squash and invalidates L1
```

ROB 不会直接修改 LSU 的 LDQ 状态。

## 5. 生成组合模型

```bash
PYTHONPATH=src python3 -m umcm compose \
  --schema examples/boom_load_load/event_types.yaml \
  --composition examples/boom_load_load/modular/buggy_composition.yaml \
  --output composed_buggy.yaml
```

预期：

```text
COMPOSED ...: 5 module(s), 21 connection(s),
36 slot(s), 32 state variable(s),
37 transformation(s), 21 constraint(s)
```

## 6. 直接从模块组合补全 Trace

Buggy：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_trace.yaml \
  --composition examples/boom_load_load/modular/buggy_composition.yaml \
  --output completed_buggy.yaml
```

预期：

```text
FEASIBLE finite completion
36 events
L0 = 1 commits
L1 = 0 commits
L1.order_fail = false
```

检查执行图：

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom_load_load/event_types.yaml \
  --trace completed_buggy.yaml \
  --axioms examples/boom_load_load/rvwmo_load_load_fragment.yaml
```

得到：

```text
InitX --rf--> L1
W1    --rf--> L0
InitX --co--> W1
L1    --fr--> W1
L0    --ppo-> L1

L1 -fr-> W1 -rfe/rf-> L0 -ppo-> L1
MEMORY MODEL VIOLATION
```

Fixed recovery：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_recovery_trace.yaml \
  --composition examples/boom_load_load/modular/fixed_composition.yaml \
  --output completed_fixed.yaml
```

结果中 `L1` 被 `order_fail → exception → squash` 撤销，执行图为 `ALLOWED`。
若对 fixed composition 强制要求 `L1=0` 仍然退休，则 completion 为
`INFEASIBLE`。

## 7. 与 v0.8 的关系

v0.8 解决：

```text
如何把一条长的具体 Trace 抽象成较短的层次 Trace，
同时保留 rf/co provenance 和内存模型结论。
```

v0.9 解决：

```text
如何把生成这条 Trace 的操作模型拆成独立模块，
并通过显式接口重新组合。
```

两者正交：组合模型先生成具体 Trace，随后仍可使用 v0.8 的
`umcm abstract / refine`。

## 8. 当前边界

v0.9 完成的是**模块模型组合基础设施**，不是完整的 BOOM LSU/L1/MSHR 模型：

- 当前规则仍针对已知 Load–Load witness 的有限事件槽；
- `L0/L1/W1` 和队列索引仍是具体实例；
- `shared_event` 当前按全局 Event type 共享；多核、多 DCache 或多 MSHR 实例仍需在 v0.10 加入 instance/channel 身份，避免同类型接口串线；
- 还未实现参数化规则的按 Trace 实例化；
- 还未覆盖完整 STQ、secondary miss、所有 nack、writeback 冷路径等。

下一轮应将具体操作名和固定队列索引改为参数化模板。

## 9. 测试

```bash
PYTHONPATH=src pytest -q
```

预期：

```text
86 passed
```

测试覆盖模块/组合 YAML 往返、单体与模块模型等价、Buggy/Fix 差分、required
port、方向和类型检查、重复驱动、state ownership、未声明事件依赖，以及
`event_map` 自动 Transformation。
