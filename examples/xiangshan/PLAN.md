# XiangShan µMCM 建模计划

> 当前进度：第 10 阶段已完成（`v0.10.0`）；下一阶段是 Uncache/MMIO 有序路径。

## 结论

- 按 **22 个可独立验收的阶段**实施，不把 LSQ、L1D、L2 各自当成一个黑盒。
- 源码基线：XiangShan `50cdcfc2c45d0631591310435835c0180c105489`，XSCache `dfd3edcf42b772e2a21178579b93bafc956f99b8`，rocket-chip `a2df1a42399cfe2b343eeb5293796268dc2bc211`。
- `DefaultConfig`：64 KiB/4-way/双通道 L1D → 2 MiB/4-bank inclusive L2 → 32 MiB/16-way/4-bank OpenLLC。
- 第 20 阶段完成硬件正确性主体；第 21 阶段补充预取干扰；第 22 阶段完成多核组合、RVWMO 投影和搜索。

## 目录规划

```text
examples/xiangshan/
├── README.md
├── PLAN.md
├── SOURCE_MAP.md
├── events.yaml
├── hierarchy/interfaces.yaml
├── model/
│   ├── core/          # dispatch、retire、redirect、exception、fence
│   ├── mmu/           # dtlb、l2tlb、ptw、protection
│   ├── load/          # pipeline、vlq、rar_raw、replay、mdp
│   ├── store/         # pipeline、vsq、psq、forwarding、sbuffer
│   ├── special/       # uncache、mmio、atomic、lrsc、cmo
│   ├── vector/        # vector flow、vstart、segment/unaligned
│   ├── l1/            # arrays/hit、miss/refill、probe/writeback/TL
│   ├── l2/            # ingress/directory、mshr/coherence、CHI
│   ├── l3/            # directory、snoop、refill/response/memory
│   └── background/    # prefetch 及其容量/仲裁干扰
├── composition/            # core_memory、l1_path、coherent_hierarchy、full_system
├── traces/                 # 只提供 Arch/Env/公开接口输入
├── axioms/rvwmo.yaml
├── coverage/
└── search/
```

`model/` 按“持久状态归属 + 因果边界”拆分，不机械地一个 Chisel `class` 对应一个 YAML。内部命中、仲裁和队列状态保持私有，跨模块只连接已声明的请求/响应/提交/一致性端口。

## 实施阶段

| # | 语义切片 | 主要源码 | 阶段验收 |
|---:|---|---|---|
| 1 ✓ | 基线、事件词汇、公私边界 | `Configs.scala`、`MemBlock.scala`、XSCache 顶层 | 源码哈希/行号可追溯；`events.yaml` 和空组合通过 lint |
| 2 ✓ | 访存指令生命周期 | `Dispatch.scala`、`Rob.scala`、`RobBundles.scala`、`ExceptionGen.scala`；`MemCtrl.scala` 已审阅并留给阶段 7 | allocate/commit/redirect/exception 无幽灵完成 |
| 3 ✓ | L1 DTLB 命中、miss、refill、flush/retry | `TLB.scala`、`TLBStorage.scala`、`Repeater.scala` | TLB hit/miss/retry/SFENCE 身份不丢失 |
| 4 ✓ | L2TLB、PTW、两阶段翻译与保护 | `L2TLB*.scala`、`PageTable*.scala`、`PMP/PMA.scala`、`BitmapCheck.scala`、`MptChecker.scala` | refill、page/access fault、虚拟化和 flush 用例通过 |
| 5 ✓ | 对齐标量 load S0–S3 数据路径 | `NewLoadUnit.scala`、`Bundles.scala` | issue→translate→forward/cache→writeback，nack 不能完成；确认 S4 只服务非对齐回环 |
| 6 ✓ | Load 生命期与违例检测 | `VirtualLoadQueue.scala`、`LoadQueueRAR.scala`、`LoadQueueRAW.scala` | redirect 回收；RAR/RAW 违例精确恢复 |
| 7 ✓ | Load replay 与内存依赖预测 | `LoadQueueReplay.scala`、`StoreSet.scala`、`WaitTable.scala`（当前配置未实例化） | replay cause/wakeup 不丢不重；预测只延迟不改值 |
| 8 ✓ | Store 地址/数据管线与 VSQ | `NewStoreUnit.scala`、`StdExeUnit.scala`、`VirtualStoreQueue.scala` | addr/data 配对；commit/redirect 后生命期正确 |
| 9 ✓ | PSQ、转发、非对齐拆分和 drain | `NewStoreQueue.scala` 中 `PhysicalStoreQueue/ForwardModule/UnalignQueue/DeqModule` | 字节 mask、youngest-match 转发、拆分/异常边界通过 |
| 10 ✓ | SBuffer 合并、排空与已提交 store 可见性 | `sbuffer/Sbuffer.scala` | 未提交 store 不外泄；fence 等待需要的 drain |
| 11 | Uncache/MMIO 有序路径 | `LoadQueueUncache.scala`、`dcache/Uncache.scala`、`MemBlock.scala` | cached/uncached 互斥；MMIO 请求、响应和提交顺序可证 |
| 12 | 向量访存与标量非对齐扩展 | `NewLoadUnit/NewStoreUnit`、LSQ/SBuffer 向量分支、`Rob.scala` | 标量 S4 头尾拼接、unit/stride/index/segment、`vstart`、fault-only-first 和精确异常 |
| 13 | L1D arrays 与 hit 管线 | `DCacheWrapper.scala`、`LoadPipe.scala`、`StorePipe.scala`、`MainPipe.scala`、data/meta | load/store hit、bank conflict、bypass/nack 通过 |
| 14 | L1D non-blocking miss/refill | `MissQueue.scala`、`DCacheWrapper.scala` 中 `MissReadyGen`、replacement 逻辑 | primary/secondary miss、merge、refill、replay、victim 通过 |
| 15 | L1D probe/writeback/TileLink 客户端 | `Probe.scala`、`WritebackQueue.scala`、`DCacheWrapper.scala` A–E 通道 | clean/dirty probe、release/ack、grant/finish 权限迁移正确 |
| 16 | AMO、LR/SC、CMO 与 fence 完成 | `AtomicsUnit.scala`、`AtomicsReplayUnit.scala`、`Fence.scala`、L1 main pipe | AMO 串行化；probe 破坏 reservation；SC 成败；CMO/fence 排空 |
| 17 | L2 入口、目录、数据与主管线 | `SinkA/SinkC/RequestBuffer/Directory/DataStorage/MainPipe.scala` | hit/miss/evict 的 directory state/data version 一致 |
| 18 | L2 MSHR、probe/grant 和外侧 CHI | `MSHR*.scala`、`SourceB.scala`、`GrantBuffer.scala`、`RX*/TX*.scala` | 冲突/合并、snoop、grant 和 CHI 事务唯一配对 |
| 19 | OpenLLC 入口、目录、数据与主管线 | `openLLC/{OpenLLC,Slice,RequestBuffer,Directory,DataStorage,MainPipe}.scala` | 多 RN 所有者/共享者和最新数据版本唯一 |
| 20 | OpenLLC snoop、refill、response、memory 与 CHI | `SnoopUnit/RefillUnit/ResponseUnit/MemUnit.scala`、`openLLC/chi` | snoop 闭环；回写/内存可见点可证 |
| 21 | 预取与背景干扰 | `mem/prefetch`、`coupledL2/prefetch` | 预取可竞争/驱逐，但不创造架构操作或新数据值 |
| 22 | 全层次组合、RVWMO 投影、coverage 与搜索 | 上述全部公开接口 | 多 hart litmus 完成后投影符合 RVWMO；接口/路径覆盖审计通过，再启动 blind search |

## 每阶段的固定交付门槛

1. `SOURCE_MAP.md` 补充精确文件、行号、commit 和抽象说明。
2. 新事件先进 `events.yaml`；内部事件必须归属唯一模块，跨层只走 public port。
3. 至少提供正向 witness、关键负向/UNSAT 用例和与已完成子系统的 composition。
4. 输入 trace 不注入内部 hit/miss/replay/仲裁结果；这些必须由私有状态和 transformation 推导。
5. 通过 schema/lint、completion、projection、interface audit 和本阶段 coverage 后才进入下一阶段。

## 抽象界限

- 精确保留：操作身份、年龄/顺序、字节 mask、提交/回滚、retry cause、权限/所有者、脏数据与数据版本、响应来源。
- 有界抽象：精确周期数、替换算法、SRAM 实现、ECC 位级细节、性能计数器和 debug 逻辑；若它们改变可达顺序，改为有界非确定干扰。
- ICache/前端不进入数据一致性主模型，仅保留 `FENCE.I` 所需的公开完成边界。
- 历史 completion 和阶段回归产物放入 `tests/regressions/xiangshan/`，不在当前模型目录堆叠 `stageXX` 副本。
