# Changelog

## 0.11.0

- `TraceRoleSpec` adds `cardinality: many` for finite collection roles.
- Module templates add declarative `repeat` expansion over collection roles.
- BOOM LSU templates now instantiate generic per-load LDQ state for every observed load.
- Added source-grounded load-side lifecycle rules: allocation, TLB/retry, execute, nack/wakeup, response, observed, order-fail, recovery, and non-forwarded commit.
- Added standalone nack→wakeup→reexecute regression and three-load finite-instantiation regression.
- Event catalog adds `LSU.LDQAllocate` and `LSU.LoadWakeup`.

## 0.10.0

- 新增 Trace role 解析与有限参数绑定。
- 新增类型保持的 `${role.field}` 模板替换；嵌入占位符可参数化状态名。
- `CompositionSpec` 新增 `roles`，schema 更新为 `umcm.composition.v0.10.0`。
- `compose_modules()` 可使用输入 Trace 实例化参数化模块；v0.9 concrete composition 保持兼容。
- `umcm compose` 新增可选 `--trace`。
- 新增参数化 LSU/DCache/MSHR/Coherence/ROB 模板。
- 使用 LoadAlpha/LoadBeta/StoreGamma、LDQ[13]/LDQ[7]、MSHR[3] 重新发现相同 BOOM Load–Load violation。
- fixed 参数化模型仍阻断错误退休并允许 recovery trace。
- 测试增至 92 项。

## 0.9.0

- 新增 `ModuleSpec / ModulePort`，可独立加载模块 slots、state、Transformation 与局部约束。
- 新增 `CompositionSpec / ConnectionSpec`，支持相对路径模块引用和显式接口连接。
- 新增 `shared_event` 与 `event_map` 两种连接模式。
- 新增组合器，检查端口方向、事件类型、字段 Sort、required port、重复驱动和跨模块名称冲突。
- 强制模块 Transformation 只能访问本模块状态。
- 强制 Transformation 使用的事件类型必须由本模块 slot 或 port 显式声明。
- 新增 `umcm compose`，可生成普通 CompletionSpec。
- `umcm complete` 新增 `--composition`，可直接加载模块组合。
- 将 BOOM witness 拆成 LSU、DCache、MSHR、Coherence、ROB 五个模块和 21 条连接。
- 模块化 Buggy 模型与 v0.8 单体模型产生完全相同的 36-event Trace、状态和 forbidden graph。
- Fixed 模型把 LSU exception、ROB squash 和 LSU invalidation 拆为跨模块事件链。
- Package version 更新为 0.9.0，测试增至 86 项。

## 0.9.0

- 新增 `ModuleSpec / ModulePort / CompositionSpec / ConnectionSpec`。
- 新增 `shared_event` 与 `event_map` 两类模块连接。
- 新增 required-port、方向、事件类型、field-map 和单输入连接检查。
- 新增 `umcm compose` 与 `umcm complete --composition`。
- 将 BOOM witness 拆成 LSU、L1 DCache、MSHR、coherence、ROB/recovery 五个独立模型。
- stateful Transformation 只能访问所属模块声明的持久状态。
- fixed recovery 被拆为 LSU order-fail、ROB exception→squash、LSU squash-state update。
- 建立 21 条显式共享事件连接，支持 DCache miss 等输出扇出。
- 模块化 Buggy/Fixed 与 v0.8 单体模型的事件、状态和执行图结果完全一致。
- 新增模块 schema/接口错误、event-map、组合等价性和 CLI 回归测试。
- Package version 更新为 0.9.0，测试增至 86 项。

## 0.8.0

- 新增可加载 `AbstractionSpec`，支持角色匹配、字段统一、摘要事件、retain 与 hide。
- 新增 `Hierarchy.ReadFromEvidence / CoherenceOrderEvidence / CoherenceObservation / LoadLoadResolution`。
- 新增确定性抽象证书，记录 source trace digest、保留/隐藏事件及摘要来源。
- 新增 `umcm abstract` 与 `umcm refine` CLI。
- 新增 witness-level refinement 检查和抽象前后 memory-model preservation 检查。
- graph projection 新增 `co_hints`，可由 trace evidence 收紧 coherence-order 候选。
- 重复且语义相同的 `rf` hint 可共存；冲突 hint 会被拒绝。
- BOOM buggy trace 从 36 个事件压缩到 11 个，仍产生同一 forbidden graph。
- BOOM fixed trace 从 37 个事件压缩到 10 个，仍保持 allowed。
- Package version 更新为 0.8.0，测试增至 76 项。

## 0.7.0

- 新增 `MemoryOperation / ExecutionGraph / Relation`。
- 新增有限关系代数：union、intersection、difference、inverse、composition、transitive closure。
- 新增 Trace 架构投影和 committed-load value 合并。
- 新增 `rf/co` 候选枚举、`fr = rf^-1 ; co`、`rfe` 和 Load–Load `ppo`。
- 新增可加载 `ProjectionSpec / DerivedRelationSpec / AxiomSpec`。
- 新增 `acyclic / irreflexive / empty` 公理检查。
- 新增 MSHR GrantData provenance 对架构 `rf` 的收紧与一致性检查。
- 新增 `umcm check` CLI 和 Execution Graph YAML/JSON 输出。
- BOOM buggy Trace 自动生成 `W1-rf-L0-ppo-L1-fr-W1` 关系环。
- 新增 allowed、same-write 与 fixed-recovery 对照样例。
- 架构投影会隐藏被 squash 且未退休的推测 load。
- Package version 更新为 0.7.0，测试增至 67 项。

## 0.6.0

- 补齐 L0 的 DCache miss → MSHR → AcquireBlock → GrantData → RPQ direct response 路径。
- 新增 8 类 DCache/MSHR 事件及 14 个 L0/MSHR 持久状态。
- GrantData 通过 source/address/value 与 Hart1 的 W1(x=1) 连接。
- L0 long-latency response 现在真实更新 executed/succeeded/value 并约束退休。
- 新增 `Transformation.output_when`，支持同一输出事件类型的 scoped exact producers。
- buggy 模型可补全 L0=1、L1=0 且均退休的完整微架构 Trace。
- fixed 模型保留 L0=1 路径，同时通过 order-fail recovery 阻止 L1=0 退休。
- Completion schema 与 package version 更新为 0.6.0。
- 测试增至 54 项。

## 0.5.0

- 新增 `LSU.LDLDSearch / LSU.LDLDConflict`。
- 新增 `LSU.AssertViolation`，明确 assertion 是非功能性监视事件。
- 新增 `LSU.LoadOrderFail / Core.MemoryOrderingException / Core.SquashLoad`。
- 新增 `order_fail/squashed/executing_now` 三个 L1 状态。
- 将 L0 retry 接入 BOOM 的 same-address observed-younger LD–LD guard。
- 新增 buggy assertion-only 模型，允许 L1=0 继续退休。
- 新增 fixed reference 模型，生成 order-fail→exception→squash。
- 同一错误退休 Trace 在 fixed 模型下不可行。
- Completion schema 与 package version 更新为 0.5.0。
- 测试增至 47 项。

## 0.4.0

- 新增年轻 Load L1 的 DCache hit/response 路径。
- 新增 `DCache.LoadHit / DCache.LoadNack / DCache.ProbeReceive`。
- 新增 `LSU.LoadExecuted / LSU.LoadSucceeded`，并细化 response/release/observed 事件身份字段。
- 新增 L1 LDQ `executed/succeeded/observed/value` 持久状态。
- 新增 ProbeUnit pending probe 的 address/source identity 状态。
- 新增 store→probe 与 ProbeReceive→ProbeRelease 的可行路径摘要。
- 正向模型完成 `L1=0 → Probe → observed → L0 retry`。
- 新增 release 地址不匹配、DCache nack、nack+success 三类负向回归。
- Completion schema 与 package version 更新为 0.4.0。
- 测试增至 42 项。

## 0.3.1

- 修正概念划分：`valid/ready/fire` 统一归入普通 `Transformation` 状态转换语义，不再称为独立“握手语义”。
- 删除示例模型中未被解析器消费的顶层 `handshakes:` 段。
- 将相关 transformation/tag/annotation 重命名为 interface-state-transition。
- CompletionSpec 与 Transformation 反序列化新增未知字段拒绝，防止模型段被静默忽略。
- `Transformation` 现在可在同一规则中组合 input guard、output event、state requirement 与 state update；状态效果只在完整转换实例发生时激活。
- 保留 v0.3 的 witness 行为和状态执行结果。
- 测试增至 35 项。

## 0.3.0

- 新增 `StateVariable / StateRequirement / StateUpdate`。
- 新增 pre-state 检查、atomic post-state update、自动 stutter 和同周期冲突写检测。
- 新增状态规则实例化及状态拒绝诊断。
- completed Trace metadata 中保存初始状态、最终状态和逐周期状态历史。
- 事件目录扩展到 16 种事件。
- 新增 `TLBHit / DCacheReqValid / DCacheReqReady / DCacheReqFire` 路径。
- 新增 ready/valid/fire 的双向约束及身份保持。
- 新增 BOOM retry queue 单槽摘要，保持 `op_id/ldq_idx/vaddr`。
- 新增 branch kill 与 exception 清空 retry queue 的防御路径。
- 新增正向 `retry_dcache_completion.yaml` 和负向 `retry_dcache_branch_kill.yaml`。
- 保持 v0.2 completion model 向后兼容。
- 测试增至 31 项。

## 0.2.0

- 新增有界候选隐藏事件 `EventSlot`。
- 新增带输入/输出事件角色的 `Transformation`。
- 新增 Transformation 有限实例化和 cycle bound。
- 新增三值表达式求值器与依赖无关的有限域可行性后端。
- 新增部分 Trace 必需字段补全和 witness 物化。
- 新增 `umcm complete` CLI。
- 新增 BOOM `TLBMiss → RetryEnqueue → RetryIssue` 示例模型。
- 将 `RetryIssue(L0)` 明确为 witness query goal，并用反向 causal-support Transformation 补全前置事件，避免把路径选择误写成无条件活性。
- 新增“取消 query goal 后隐藏 retry 事件均可不发生”的回归测试。
- 将事件目录扩展为 10 种事件，加入 `LSU.RetryIssue`。
- 测试增至 24 项。

## 0.1.0

- 建立 Python package 与测试骨架。
- 实现类型化表达式 AST。
- 实现 Event schema、动态事件和部分 Trace。
- 实现 YAML/JSON 往返序列化。
- 实现 schema-aware Trace 验证与 CLI。
- 加入 BOOM Load–Load 案例的部分 Trace 输入。
