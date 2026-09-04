# Changelog

## 0.21.0

- Withdrew the earlier blind-rediscovery claim because its realization used the
  witness-oriented `model/search/cacheable_path.yaml` summary rather than the
  detailed BOOM LSU/L1D/MSHR state machines.
- Pinned the BOOM, Chipyard, Rocket-Chip and SiFive InclusiveCache revisions
  and source-file SHA-256 values in `examples/boom/source/v021.yaml`.
- Added a machine-readable behavior/source/implementation ledger and an
  executable auditor that treats source mapping and executable coverage as
  separate facts.
- Added an admission gate that rejects `model/search/` modules and dynamic
  microarchitectural outcomes in a future default blind-search query.
- Added bounded source-derived LDQ/STQ allocation from decoded memory
  instructions; queue indices are no longer required in the input trace.
- Added the BOOM DCache/MSHR TileLink A/D/E adapter, including `source` routing,
  and connected the detailed MSHR primary path to the InclusiveCache model so
  the MSHR Grant is produced by L2 instead of supplied by the trace.
- Added a two-entry Small/Medium BOOM `BoomMSHRFile` allocator that derives
  primary/secondary choice and MSHR ID internally, including round-robin
  allocation, block/tag/index matching, all-busy/conflict backpressure,
  finish/reuse, Probe gating, and Rocket-Chip write-intent secondary rules.
- Replaced the witness-shaped L1 for new source-model work with a generalized
  four-way BOOM v4 L1D: per-set/per-way tag/permission/data state, s0/s1/s2,
  state-derived hit/tag miss/permission miss and replacement, five nack causes,
  MSHR refill/meta writes, store write/bypass timing, and generalized clean or
  dirty ProbeUnit downgrade/invalidation paths.
- Added the exact BOOM v4 LSU per-port scheduler: all twelve source-priority
  calls, TLB/DCache/LCAM resource consumption, fixed-port rules, fast/slow
  store drain, and incoming agen assertion.
- Connected selected scheduler grants through the source request mux into the
  generalized L1 and tested the state-derived hit/response path.
- Connected the two-entry MSHR-file allocator to fixed BOOM entry readiness,
  phase, primary/secondary acceptance, RPQ insertion and bounded SDQ lifetime;
  MSHR and SDQ IDs are derived rather than supplied by source traces.
- Replaced the legacy LSU-local TLB outcome slots in the integrated path with a
  source-derived LDQ runtime driven only by `Core.TranslatedMemory` and public
  DCache/ROB interfaces. It now covers dispatch allocation, translated address
  state, fire/executed, nack, hit/refill success, probe observation, commit
  deallocation, and BOOM's older-load/observed-younger assertion case.
- Added a strict instruction-to-retirement ordinary-load composition. A cold
  load now derives NBDTLB translation, scheduler selection, generalized L1
  miss, MSHR0 selection, TileLink A/D/E, InclusiveL2 refill, LSQ success, ROB
  commit and `Arch.Load` without supplied path or resource IDs.
- Fixed load-data continuity so refill data, rather than the decoded
  instruction placeholder, flows through `Core.MemoryComplete`, `ROB.Commit`,
  `Arch.Load`, and `Arch.CommitLoad`.
- Added a source-derived clean TileLink B/C ProbeUnit bridge and kept dirty
  ProbeAckData plus separate per-hart generalized L1 state as explicit
  remaining work.
- Added the source-derived ordinary STQ lifecycle: independent address/data
  readiness, delayed ROB-ready, in-order commit, post-commit scheduler drain,
  DCache acknowledgement and committed-head clearing.
- Integrated store hit, TLB retry and cold miss. The cold path derives MSHR/SDQ
  selection, acknowledges on accepted MSHR request, acquires T permission, and
  later replays retained SDQ data through the fixed-way DCache pipeline before
  dirty metadata and GrantAck.
- Added private exact-producer cause events so L1 can join hit/MSHR-accept
  acknowledgements and hit/replay data writes without weakening event
  provenance.
- Added a finite two-attempt scheduler role and source-derived store-nack
  recovery: execute-queue flush/head rewind, committed-store re-enqueue, and a
  second exact store-commit scheduler/drain decision. The second DCache/L1
  request pipeline remains explicitly blocked.
- Kept the default BOOM/RVWMO search deliberately `BLOCKED` while full
  default detailed composition remains unresolved. No
  revised blind-rediscovery claim is made yet.
- Complete regression: 238/238 tests pass.

## 0.20.0

- Added `umcm search` and a serializable two-level hierarchical-search specification/report IR.
- Added bounded architecture-only operation-domain enumeration followed by the complete v0.16 RVWMO checker.
- Added explicit architectural obligations for values, `rf`, `co`, `fr`, `po`, and `ppo` rather than passing a microarchitectural path to layer two.
- Added a coherence realization adapter that enumerates out-of-order public access schedules and constrains only public request/result events.
- Enforced adapter input allowlists, rejected catalog-private event vocabulary, and verified that obligation outputs are child-module output ports.
- Added the BOOM v0.20 query: layer one discovers `R0=1, R1=0`; the v0.18 coherence slice realizes it as `R1 -> W -> R0` with source/version evidence.
- Added first-class `interface_gap` results. The detailed LSQ/L1/MSHR join remains explicitly blocked because its finite allocation/routing parameters are still supplied through trace annotations and it is not connected to v0.18 TileLink.
- Kept `end_to_end: false` for the BOOM result; blind detailed-path rediscovery remains the v0.21 milestone.
- Added four focused v0.20 tests. Test suite: 177 passing tests.

## 0.19.0

- Added `umcm cover`, a serializable coverage suite, compound coverage goals, machine-readable reports, and per-goal witness traces.
- Added exact fully-bound Transformation activation evidence; coverage does not infer rule firing from same-typed events.
- Added event, Transformation, state-transition, and public-interface reachability probes.
- Added automatic goal generation over model inventories plus structural no-producer and no-bounded-binding diagnostics.
- Enforced per-model coverage input allowlists so private outcome events cannot be supplied as answers.
- Added cached bounded-problem reuse and streamed per-input/per-goal CLI progress.
- Added 28 BOOM goals across LSQ, MSHR, core-side, coherence, and generated TileLink interfaces; 27/27 required goals are covered.
- Retained one optional uncovered same-hart refill→L1-hit goal, exposing a concrete v0.18 coherence model hole.
- Declared `z3-solver` as a runtime dependency and added wheel-library discovery to the ctypes backend.
- Test suite: 173 passing tests.

## 0.18.0

- Followed BOOM's pinned Chipyard configuration and modeled the selected SiFive InclusiveCache instead of inventing a generic L2.
- Added a strict two-module BOOM L1 coherence client / Inclusive L2 composition connected only through TileLink A/B/C/D/E public events.
- Added private per-line L1 N/B/T state and L2 INVALID/BRANCH/TRUNK/TIP directory, owner/sharer, dirty, value/version/source, and serialized MSHR control.
- Added state-derived cold miss/refill, shared-reader T→B probe, BtoT write upgrade, dirty ProbeAckData handoff, GrantAck, ReleaseData, and ReleaseAck behavior.
- Added ghost versions at RTL-grounded data-flow points; clean coherence messages cannot manufacture a new version.
- Added five high-level traces that contain no supplied hit/miss/Probe/Grant outcome and nine focused coherence tests.
- Replaced the Z3 backend's quadratic pairwise atomic-write agreement encoding with an equivalent linear next-state encoding and added a conflict regression.
- Corrected the mistyped BOOM source commit string inherited by v0.17 metadata and documentation.
- Test suite: 168 passing tests.

## 0.17.0

- Added the nine-module `core_side_v017.yaml` BOOM composition with strict public-event boundaries.
- Added a BOOM v4 source-pinned NBDTLB plus LSU translation/retry boundary; private valid/walker state derives hit/miss, PTW request, refill, miss-ready, and LSU-owned retry without a supplied TLB outcome.
- Kept the external PTW as an explicitly bounded environment rather than claiming an unavailable Rocket Chip PTW implementation.
- Added SFENCE all/VPN invalidation and corrected page-fault delivery so a PTW result refills first and the retried TLB response reports the fault to LSU.
- Added a memory ROB model with allocation, completion, in-order commit, precise page-fault delivery, younger squash, and branch recovery.
- Added serialized AMO read/write behavior and per-hart-line LR/SC reservation state.
- Added a public `DCache.ProbeRelease` adapter that invalidates matching LR reservations and forces SC failure without an `Atomic.SCWrite`.
- Added successful `Arch.LRSCPair` generation and extended the BOOM RVWMO projection to AMO, LR, and successful SC events.
- Added one-outstanding IOMSHR load/store behavior and fence completion after `DCache.Ordered`.
- Added ten directed core-side traces and 13 focused tests. Test suite: 158 passing tests.

## 0.16.0

- Added the built-in bounded `rvwmo` architectural checker based on RVWMO 2.0.
- Added explicit AMO operations with separate read and write values, plus LR/SC metadata.
- Added trace-to-graph relation hints for address, data, control, fence, LR/SC pair, and pipeline-dependency facts.
- Implemented all thirteen preserved-program-order rules as individually inspectable `ppo_rule1` through `ppo_rule13` relations.
- Added `rfi/rfe`, `fri/fre`, a deterministic total `gmo` witness, strict `rf/co` well-formedness, initialization ordering, load-value checks, AMO atomicity, and LR/SC atomicity.
- Added an explicit rejection boundary for partially overlapping mixed-size accesses and non-main-memory operations rather than silently approximating them.
- Kept legacy configurable graph models and the BOOM Load--Load fragment backward compatible.
- Added `examples/rvwmo/`, the BOOM `axioms/rvwmo.yaml` projection, `RVWMO_V0.16.md`, and 19 focused tests covering Load--Load, Store--Load, Store--Store, fences, dependencies, acquire/release, AMO, and LR/SC.
- Test suite: 145 passing tests.

## 0.15.0

- Added explicit `ModuleSpec.internal_events`; ports now represent only true cross-module event surfaces.
- Marked all module state and transformations as implementation-private in hierarchy contracts.
- Added strict composition encapsulation checks that reject parent constraints reaching into child-private slots.
- Added slot ownership/visibility annotations and hierarchy inventory metadata to composition results.
- Added `build_interface_contracts()` and pure hide-only `project_interface_trace()`; no witness-specific summary events are synthesized.
- Added `umcm interfaces` and `umcm project-interface`.
- Removed artificial LSU↔L1 connections through private `LoadExecuted`/`LoadHit`/`LoadMiss` events.
- Corrected coherence→DCache ProbeReceive direction.
- Added multi-event trace roles and missing-`where`-path-as-nonmatch behavior for heterogeneous memory-operation roles.
- Added `examples/boom/hierarchy/interfaces.yaml`, `HIERARCHY_V0.15.md`, and `BOOM_MODEL_COVERAGE.md`.
- Known buggy trace projects from 45 to 19 events and remains forbidden; fixed trace projects from 46 to 20 and remains allowed.
- Test suite: 126 passing tests when run in groups.

## 0.13.0

- Added reusable BOOM MSHR/RPQ/SDQ/IOMSHR semantics for primary/secondary misses, refill, direct response, replay, response queueing, writeback/finish, probe/fence readiness and MMIO.
- Added standalone MSHR regression traces and kept the BOOM Load–Load witness forbidden under the formal MSHR model.

## 0.12.0

- Reorganized the active BOOM model under `examples/boom/`; stage-by-stage artifacts moved to regression storage.
- Added generic pairwise `repeat_product` expansion for LD-LD and ST-LD rules.
- Added conditional `state_mode: guard` semantics and direct persistent-state encoding in the libz3 backend.
- Generalized the BOOM LSQ model across LDQ, STQ/SDQ abstraction, load/store retry, forwarding, ordering recovery, commit/drain and fence lifecycle.
- Added store TLB miss/retry, exception flush, and store commit→drain→ack→clear paths.
- `LSU.LoadOrderFail` now carries `source_op_id` provenance, eliminating pairwise exact-support aliasing.
- Corrected the LD-LD search timing/executing-window abstraction to match the one-cycle `s0_executing_loads → s1_executing_loads` path.
- The real BOOM Load-Load bug remains feasible/forbidden; the fixed reference produces order-fail→exception→squash and blocks the bad retirement.
- Test suite: 111 passing tests.

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
