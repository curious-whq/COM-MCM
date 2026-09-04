# XiangShan memory µMCM source map

## Pinned baseline

| Repository | Revision | Role |
|---|---|---|
| `tools/XiangShan` | `50cdcfc2c45d0631591310435835c0180c105489` | Core, MemBlock, MMU and L1D |
| `tools/XiangShan/XSCache` | `dfd3edcf42b772e2a21178579b93bafc956f99b8` | CoupledL2 and OpenLLC |
| `tools/XiangShan/rocket-chip` | `a2df1a42399cfe2b343eeb5293796268dc2bc211` | TileLink protocol definitions |
| `tools/XiangShan/utility` | `44f500cd2ddd95138d9402ae4b580fb84c3289ec` | Shared CHI and hardware utilities |

All paths and line ranges below refer to these revisions.  Later source changes require an explicit rebase of this document and affected model metadata.

## Default configuration

| Property | Value | Source |
|---|---:|---|
| XLEN / VLEN / ELEN | 64 / 128 / 64 | `src/main/scala/xiangshan/Parameters.scala:48-68` |
| Scalar load/store pipelines | 3 / 2 | `src/main/scala/xiangshan/Parameters.scala:165-170` |
| Virtual LQ / RAR / RAW / replay | 120 / 96 / 56 / 120 | `src/main/scala/xiangshan/Parameters.scala:101-108` |
| Physical SQ / virtual SQ / unaligned queue | 64 / 128 / 2 | `src/main/scala/xiangshan/Parameters.scala:109-113,794-798` |
| SBuffer entries / enqueue width | 16 / 2 | `src/main/scala/xiangshan/Parameters.scala:176-178` |
| L1D | 64 KiB, 4-way, 2 memory channels | `src/main/scala/top/Configs.scala:541-545` |
| L1D miss/probe/release entries | 16 / 8 / 18 | `src/main/scala/top/Configs.scala:282-300` |
| Per-core L2 | 2 MiB, 4 banks, inclusive | `src/main/scala/top/Configs.scala:304-360,541-545` |
| OpenLLC | 32 MiB, 16-way, 4 banks | `src/main/scala/top/Configs.scala:363-390,541-545` |

`DefaultConfig(n = 1)` is the elaboration default.  The µMCM remains hart-parameterized so the final composition can exercise coherence with two or more harts.

## Stage 1 structural anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/top/Configs.scala` | 630 | `a2f321b6d086287be6b6f658c3bd6429343bc68da0e12e9d1bea663d22d8007c` | Freezes the selected L1D/L2/OpenLLC hierarchy and capacities. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | Owns the core-memory boundary and instantiates DCache, Uncache, L2TLB, load/store units, LSQ, SBuffer and atomics. |
| `src/main/scala/xiangshan/cache/dcache/DCacheWrapper.scala` | 1899 | `243cb603d76cf2ae1ca0633c99010ef11a08a0eb4d03e4ec9c28396ffc3fe482` | Defines LSU/SBuffer/atomic ports and the L1D TileLink client boundary. |
| `XSCache/src/main/scala/coupledL2/CoupledL2.scala` | 1055 | `a72414f184e54622563e4fb33cfbadc703deac08614c9d5d747c484eddf9a9b0` | Binds banked TileLink inputs to a CHI request-node interface. |
| `XSCache/src/main/scala/coupledL2/Slice.scala` | 282 | `d315900bae2e2af0435b7abe6dfc59783ffd35cb6bc7dc1bd01b822edc346b26` | Exposes SinkA/SinkC, B/D/E handling, directory, MSHR control and CHI TX/RX channels. |
| `XSCache/src/main/scala/openLLC/OpenLLC.scala` | 95 | `53cb4e6751d0d69a8ab62e1ba92fd5ab3c38ae38c92ebaff69d5b17fde2631ab` | Connects multiple request nodes through RN/SN CHI crossbars. |
| `XSCache/src/main/scala/openLLC/Slice.scala` | 153 | `fed82cc3f1a0eb1d989ccb9e7b424eddf4d6a3c4cd18dec8ff3867212a8f149c` | Owns LLC directory, snoop, refill, response and downstream-memory units. |

Key line anchors:

- `MemBlock.scala:186-260`: backend commit/issue/redirect-related inputs and memory writeback/violation outputs.
- `MemBlock.scala:330-370`: DCache, Uncache and L2TLB LazyModule topology.
- `MemBlock.scala:504-569`: load/store/atomic units, LSQ and SBuffer instantiation.
- `MemBlock.scala:885-938`: load-unit connections to DTLB, DCache, forwarding and replay.
- `MemBlock.scala:1018-1220`: uncached arbitration, SBuffer and atomic override paths.
- `DCacheWrapper.scala:576-875`: word/line, LSU, SBuffer, atomic, CMO and prefetch interfaces.
- `DCacheWrapper.scala:1092-1096`: MainPipe, MissQueue, ProbeQueue and WritebackQueue ownership.
- `L2Top.scala:59-149`: L1 crossbar, CoupledL2 construction and TileLink attachment.
- `coupledL2/Slice.scala:43-64,248-262`: internal owners and external TL/CHI channel boundary.
- `openLLC/OpenLLC.scala:26-83`: RN/SN ports and crossbars.
- `openLLC/Slice.scala:27-139`: directory/main-pipe/refill/memory/response/snoop ownership.

## Interface decisions

| RTL boundary | Public µMCM vocabulary | Private owner |
|---|---|---|
| Backend ↔ MemBlock | `Core.MemoryIssue/Commit/Redirect/MemoryWriteback/MemoryFault/MemoryViolation` | ROB selection and redirect application remain `core_control` private. |
| Load/store/atomic ↔ DTLB/PTW | `MMU.TranslateRequest/Response`, `MMU.PTWRequest/Response`, `Core.SFence` | TLB hit/miss/refill and PTW/protection decisions remain MMU-private. |
| Load pipeline ↔ queues/forwarding | `Load.PipelineUpdate/ReplayIssue`, `Store.ForwardQuery/Response` | RAR/RAW searches, replay selection and forward selection remain private. |
| SQ ↔ SBuffer ↔ L1D | `Store.Drain`, `L1.Request/Response`, `Core.MemoryOrdered` | Queue selection, SBuffer merge and L1 hit decisions remain private. |
| LSU ↔ uncached path | `Uncache.Request/Response` | Cached/uncached arbitration state remains `uncache` private. |
| L1D ↔ CoupledL2 | `TL.A/B/C/D/E` | Arrays, MSHRs, probes, writeback queues, directory and arbitration remain child-private. |
| CoupledL2 ↔ OpenLLC | `CHI.TXREQ/TXDAT/TXRSP/RXSNP/RXDAT/RXRSP` | L2/L3 directory, MSHR, snoop and response-unit states remain private. |
| OpenLLC/Uncache ↔ memory | `Memory.Request/Response/WriteVisible` | DRAM timing is a bounded environment rather than hardware-internal state. |
| Prefetch training/requests | `Prefetch.Train/Request` | Predictor tables, filters and arbitration remain `prefetch` private. |

The event catalog uses 64-bit address containers even when the selected physical address implementation is narrower.  Canonical-address and physical-width constraints belong to the MMU stages, not the interface schema.

## Stage 1 abstraction boundary

- Included now: source identity, selected parameters, module ownership, typed public ports and reserved private event families.
- Deliberately absent now: event slots, state variables, transformations, timing constraints and architectural completion behavior.
- Performance/debug/ECC details are source-adjacent but remain outside the correctness surface unless a later stage shows that they change reachable ordering or visibility.

## Stage 2 core-lifecycle anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/backend/dispatch/Dispatch.scala` | 1291 | `699d64a86166af8d3b2ffc500e44def4b0a13059e60eb705414b4e55d1f26cfc` | `662-748` classifies load/store/AMO, checks LSQ capacity and allocates queue entries only on accepted dispatch. |
| `src/main/scala/xiangshan/backend/rob/Rob.scala` | 1936 | `a8fdf5730634b31fd7097f615fc19335c2f95e1820e9ac76742f63f97b7da130` | `464-493` allocates ROB entries; `1031-1085,1131-1150` consumes writebacks; `599-724,792-855,881-929` performs precise flush, commit and redirect walk; `1198-1269` feeds ExceptionGen. |
| `src/main/scala/xiangshan/backend/rob/RobBundles.scala` | 369 | `73a4db55525ce72c27249b204a64885a2aa167ea46fc04b405783b0303906d64` | `208-212` defines `commit_v` from entry validity and `commit_w` from the zero remaining-uop count. |
| `src/main/scala/xiangshan/backend/rob/ExceptionGen.scala` | 182 | `db2da076556663fb06465833f95fcf62e475a8b920c2d6cf742c4866958e6291` | `34-180` tracks the oldest exception and removes candidates killed by redirect/flush. |
| `src/main/scala/xiangshan/backend/ctrlblock/MemCtrl.scala` | 43 | `cfc356aca5c8e31826974cd980401ecb26b5347c5d81b20286c58e8151bb3a5e` | Reviewed in Stage 2; its SSIT/LFST dependency-prediction state belongs to Stage 7, not ROB retirement. |

### Implemented correspondence

- `Core.MemoryInstruction → Core.DispatchAllocate → Core.MemoryIssue` represents an accepted memory uop entering the ROB and reaching the memory subsystem.
- A successful `Core.MemoryWriteback` is captured privately before `Core.ROBCommitSelect`; `Core.MemoryCommit` is impossible without that chain and waits for older same-hart operations.
- `Core.MemoryFault → Core.ExceptionRecord → Core.Redirect` is precise: the redirect waits until older operations have committed, then private `Core.RedirectApply` squashes the faulting operation and its younger same-hart tail.
- A writeback or commit observed after its applicable redirect is rejected, preventing ghost completion from a killed operation.

### Bounded abstraction

- `rob_idx` remains the public hardware identity. `program_index` is an unwrapped, trace-local age used instead of encoding circular pointer wrap arithmetic.
- Stage 2 models one scalar memory instruction as one completion unit. Multi-uop vector completion, `vstart` and fault-only-first selection remain in Stage 12.
- Dispatch width, exact pipeline latency and redirect walk duration are nondeterministic within the finite horizon; only causal order and persistent lifecycle state are preserved.
- LSQ entry capacity/index reclamation starts in Stages 6 and 8. SSIT/LFST prediction from `MemCtrl.scala` starts in Stage 7.

## Stage 3 L1 DTLB anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/cache/mmu/TLB.scala` | 836 | `f738d715bbc7a7ea4c3d12ea264813367bf8208560e81bed799be97ac0c98409` | `251-300,303-411` define lookup/refill; `556-601` is the selected nonblocking miss/replay path; `701-733` handles PTW responses. |
| `src/main/scala/xiangshan/cache/mmu/TLBStorage.scala` | 486 | `2f1c7257022d4f18bc7f809e011f5ab10d247f87bdb5b8ff14539c5aca70284b` | `86-200` owns valid bits, matching and refill; `203-230` performs address/ASID-selective SFENCE invalidation. |
| `src/main/scala/xiangshan/cache/mmu/Repeater.scala` | 744 | `685dc6e01bc98ef18e95a6dbc854df42b35aa6e6825f70136d5c8ef80242a8cd` | `163-390` tracks sent/live PTW-filter entries, merges responses and clears pending work on flush. |
| `src/main/scala/xiangshan/cache/mmu/MMUConst.scala` | 437 | `11d97513b92ee5498a1bf1493c7bf0230ea7981ea35f06ae2d6809222ea42c41` | `27-42` fixes `TLBParameters` defaults, including the two-cycle fence delay and fully-associative organization. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | `582-590,602-652,681-724` instantiate separate nonblocking load/store/prefetch DTLBs and connect SFENCE, redirect and PTW filter traffic. |
| `src/main/scala/top/Configs.scala` | 630 | `a2f321b6d086287be6b6f658c3bd6429343bc68da0e12e9d1bea663d22d8007c` | `199-240` selects four-way fully-associative L1 load/store/prefetch DTLBs for `DefaultConfig`. |

### Implemented correspondence

- A public `MMU.TranslateRequest` reads private entry-valid state and derives exactly one private hit or miss. A hit returns `paddr` at `hit_level: l1`; a miss returns `replay: true` and emits an identity-preserving `MMU.PTWRequest`.
- A matching, non-faulting `MMU.PTWResponse` passes through the private PTW-filter decision, refills the entry, and must precede a later explicit LSU retry. The model does not fabricate retry requests on behalf of the LSU.
- A matching `Core.SFence` clears the selected entry before any later lookup. If it falls between PTW request and response, it clears the pending filter state, derives `MMU.L1TLBPTWDrop`, and forbids stale refill.
- Load, store and atomic translation use the same DTLB event contract; `tlb_instance` preserves the separate `ldtlb`/`sttlb` state domains (`atomic` uses `ldtlb`), while request identity and VPN/ASID/VMID/stage prevent cross-context aliasing.

### Bounded abstraction

- `MMU.PageMap` instantiates only entries relevant to the finite trace instead of reproducing arrays and replacement policy. The selected hardware organization remains recorded as four-way fully associative.
- Exact pipeline latency, request-port arbitration and PTW merge capacity are nondeterministic within the horizon; causal order, valid state, retry identity and flush cancellation are preserved.
- Stage 3 treats PTW results as public environment input. L2TLB traversal, page/access faults, PMP/PMA/MPT checks, canonical-address checks and VS/G-stage translation begin in Stage 4.
- The current finite slice supports at most one applicable SFENCE per instantiated page entry; larger flush sequences require additional bounded entry epochs.

## Stage 4 translation-backend anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/cache/mmu/L2TLB.scala` | 1256 | `d00238f5e7cf6bb2b91089f1f73601545c4120009c3aba5b37d2b86326957d80` | `61-180,220-241,320-459` define topology, request tracking and hit/miss routing; `476-620,758-864` cover walker refill, response merge and protection. |
| `src/main/scala/xiangshan/cache/mmu/L2TLBMissQueue.scala` | 45 | `779b58cf2d869dd46cb8c7bbe6f462f4f85d5f7e3f03b5e600159533261f923b` | `30-45` bounds miss allocation and response identity. |
| `src/main/scala/xiangshan/cache/mmu/PageTableWalker.scala` | 1729 | `5f7decad0c69204be030a4657d665d74ce535e2e485fba4842d3728a5732265f` | `104-802` owns PTW, `804-1389` lower-level PTW, and `1391-1729` HPTW/G-stage traversal. |
| `src/main/scala/xiangshan/cache/mmu/PageTableCache.scala` | 1421 | `c6fa7efc7d15d64d6e33e405ea151bfcc848b00870c688708417665a361b6edc` | `120-389,588-874,1068-1284` define cached page-table hits, invalidation and refill. |
| `src/main/scala/xiangshan/cache/mmu/MMUBundle.scala` | 1575 | `a8bb218da906e3567294842981babb340c3747c0770d4b286662ff08ca5da585` | `780-900,920-1005` classify PTE validity/faults; `1163-1235,1405-1501` carry normal and two-stage responses. |
| `src/main/scala/xiangshan/cache/mmu/BitmapCheck.scala` | 519 | `9d79cf64c4a5123d0accfff8249d4e881ac6ba72667eae21a4c9281bb4e89be4` | `31-104,124-358,364-517` define the enabled-by-default bitmap permission engine and cache. |
| `src/main/scala/xiangshan/cache/mmu/MptChecker.scala` | 1347 | `98f0aaf18ddcecaa83a93258e92659c5e0012fcc74f5168587a4f8eb7ba354dc` | `31-151,758-947,1175-1347` define the optional, mutually-exclusive MPT permission path. |
| `src/main/scala/xiangshan/backend/fu/PMP.scala` | 662 | `166550129fe421ed970d2876eb229a9db9710ed299ed0e3317c1bfc59c808f19` | `190-289,368-520` select matching PMP entries and compute permissions. |
| `src/main/scala/xiangshan/backend/fu/PMA.scala` | 265 | `0d39d319d8c9f51d922d061fa111771513df390d63824b91d927775ddbc75f8f` | `201-265` classifies physical-region access and cacheability. |

### Implemented correspondence

- `MMU.PTWRequest` reads finite L2 entry state and derives exactly one hit or miss. A valid hit resolves directly; a miss performs S1 and, when requested, G-stage traversal before protection.
- Invalid/disallowed S1 and G-stage results become distinct page and guest-page faults. A resolved physical address passes PMP, PMA and the configured BitmapCheck/MPT path before a successful response or access fault.
- A successful miss refills L2 before response. Matching SFENCE/HFENCE invalidates the finite combined entry before a later lookup, forcing a new walk.
- XiangShan `DefaultConfig` enables BitmapCheck and disables MPT. The model exercises that default and retains MPT as an explicit optional configuration path.

### Bounded abstraction

- One `MMU.PageMap` summarizes a decoded PTE chain, including leaf validity, permissions, superpage alignment, canonicality and VS/G-stage outcome; exact page-table memory traffic and replacement are omitted.
- One `MMU.ProtectionMap` summarizes the selected PMP/PMA physical region and Bitmap/MPT result. Its `lower/upper` fields retain the public region description; finite instantiation binds one applicable region to each request.
- Arbitration, miss merging, TileLink beats, exact cache capacities and latency are nondeterministic within the horizon. Request identity, stage order, fault class, refill state and flush causality are preserved.

## Stage 5 aligned scalar-load anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala` | 2246 | `ac0909afe6704dbf4ed7905c50631e796a4e23dd98c9019a9f5cadd4234ce419` | `43-490,492-793,794-1234,1236-1769` define S0-S3; `1770-1895` separates the unaligned-only S4 and data-source merge; `1954-2110` wires the stages. |
| `src/main/scala/xiangshan/mem/pipeline/Bundles.scala` | 318 | `cb3832e24f1702809484d294f0a1b734844efbdb9e96bebb03f243958a5559f7` | `29-237` carries entrance, address, mask, replay, forwarding and writeback metadata between load stages. |
| `src/main/scala/xiangshan/mem/pipeline/package.scala` | 224 | `5e0dd5e8e3d6a2078eeb5bb769a275f8f89de891c312a997728290f21bddad7b` | `24-55` fixes the S0-S4 stage capabilities and confirms that ordinary aligned scalar completion is in S3. |
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueueReplay.scala` | 1058 | `de42b1f7efcbae87f6cd42c728b1338c1615e31b4a15f6fd6c4b2d050fd61b54` | `31-59` names the replay-cause classes preserved at the Stage 5 LQ boundary; replay scheduling remains Stage 7. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | `885-938` connects each load unit to its DTLB, DCache, store forwarding and replay interfaces. |

The pinned ranges above contain 2,332 non-overlapping Chisel source lines reviewed for this slice; the executable model intentionally retains only memory-correctness behavior.

### Implemented correspondence

- `Core.MemoryIssue` enters private S0 state and emits public `MMU.TranslateRequest`, `L1.Request` and `Store.ForwardQuery`. All three requests must precede the response that consumes them.
- A non-replay, non-fault translation enters S1. S2 selects either a valid full-mask store forward or a successful, non-denied, non-corrupt L1 response; the selected value is preserved through S3 to `Load.PipelineUpdate` and `Core.MemoryWriteback`.
- TLB miss, L1 nack, cache miss and invalid forwarding become distinct private replay decisions and failed public LQ updates. Translation, denied-response and corrupt-response faults set the LQ update's fault bit and become `Core.MemoryFault`; none can write back.
- `composition/load_translation.yaml` shares the load-generated translation request and DTLB-generated response across strict public ports, closing the already-modeled Stage 3 hit path.

### Bounded abstraction

- Exact cycle latency, port arbitration, bank conflicts, MSHR internals and partial-byte merge are nondeterministic or deferred. Identity, causal order, byte-mask coverage, selected value, replay cause and fault class are exact.
- Stage 5 covers first-attempt, aligned scalar cached loads. Replay selection/wakeup belongs to Stage 7; partial/youngest-store forwarding belongs to Stage 9; uncached/MMIO belongs to Stage 11.
- `LoadUnitS4` only returns an unaligned head to S3 for head/tail concatenation (`NewLoadUnit.scala:1327-1365,1638-1649,1770-1780`). It is forbidden for aligned witnesses and modeled with scalar-unaligned/vector splitting in Stage 12.

## Stage 6 load-queue lifetime and violation anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/lsqueue/VirtualLoadQueue.scala` | 288 | `5e4d32292eb57ec7d3b1919d162087349c3fbad149015d47138a1ca3b9c1fc7a` | `34-257` allocate at dispatch, retain replayed entries, mark completed loads, reclaim in queue order, and cancel by redirect. |
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueueRAR.scala` | 304 | `9f1832f828837d422b76b6a1b5221c2bfd69275894d770a2365e4609e7912feb` | `29-285` track younger loads behind unfinished loads, record matching releases, and detect load-load ordering violations. |
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueueRAW.scala` | 419 | `f74163d68a6312c0c13b970142cea7a71824a5a4301a5794424c6f06b49e3555` | `32-400` track loads behind unresolved stores, match physical address and byte mask, select a rollback load, and request `RedirectLevel.flush`. |
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueue.scala` | 347 | `351593ff68ea881183e3da9382a981e7abb16184ab7253fd17e92477e43b6dce` | `167-343` connects virtual LQ, RAR, RAW and replay subqueues and exports rollback candidates. |
| `src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala` | 2246 | `ac0909afe6704dbf4ed7905c50631e796a4e23dd98c9019a9f5cadd4234ce419` | `1409-1447` consumes RAR nuke responses and distinguishes RAR `flushAfter` from self-flushing forwarding mismatches. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | `1036-1047,1115-1119` arbitrates memory-violation redirects and carries L1 release notices into the LSQ. |

The pinned Stage 6 ranges contain 1,083 reviewed source lines; 1,044 are new relative to Stage 5 because the 39-line `NewLoadUnit` recovery window is shared with the earlier S3 audit.

### Implemented correspondence

- Every bounded scalar load issue allocates a private virtual-LQ entry. A successful or faulting address-valid update marks it complete; a replay leaves it live. Normal reclamation follows program order, while redirect cancellation reclaims affected entries directly.
- A younger load executing behind an unfinished older load creates a private RAR watch. A matching L1 release marks that watch; a later same-address query by the older load emits a public `Core.MemoryViolation` and a `flushAfter` redirect, preserving the older instruction and cancelling its younger tail.
- A load executing behind an unresolved older store creates a private RAW watch with physical address, byte mask and data-valid state. The store's later address-ready event triggers recovery only for the same address with an overlapping mask; its redirect flushes the violating load itself and younger operations.
- `composition/scalar_load_queue.yaml` shares Stage 5 `Load.OrderQuery` and `Load.PipelineUpdate` events with Stage 6, proving that a derived cache-hit path allocates and eventually reclaims the same `lq_idx` identity.

### Bounded abstraction

- `program_index` is the finite unwrapped age; circular ROB/LQ/SQ pointer arithmetic and the concrete 120/96/56 entry arrays are not reproduced. Queue identity and in-order reclamation remain explicit.
- One relevant older/younger pair is instantiated per witness. Multi-candidate oldest-selection trees are therefore outside this slice; their observable victim semantics are preserved for the selected pair.
- Release matching uses abstract cache-line address tokens. Exact beat timing, freelist banks, CAM implementation and performance counters are omitted.
- Replay scheduling/wakeup moves to Stage 7. Vector flow counts, scalar-unaligned duplicate RAR/RAW entries and revoke details move to Stage 12.

## Stage 7 load replay and memory-dependence prediction anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueueReplay.scala` | 1058 | `de42b1f7efcbae87f6cd42c728b1338c1615e31b4a15f6fd6c4b2d050fd61b54` | `31-72,197-318,337-463,493-725,742-890` fix the 13-cause priority, entry state, cause-specific wakeups, age selection, replay entrance, feedback reuse/free and redirect cancellation. |
| `src/main/scala/xiangshan/mem/mdp/StoreSet.scala` | 560 | `b5887e76a7a3ccb83170e665d0933da6e687681c529f6c65a5f7c0a4a40c7b15` | `39-420` implements SSIT allocate/attach/merge/strict training; `423-560` implements the two-entry-per-set LFST and pending-store wait/release. |
| `src/main/scala/xiangshan/mem/mdp/WaitTable.scala` | 71 | `a1d01ef503a3f2ed47bec2eb9977e1f795abaa1363f189f59ab97686d6e9cc3a` | Defines the alternative load-wait table, but it is not instantiated by the selected configuration. |
| `src/main/scala/xiangshan/backend/ctrlblock/MemCtrl.scala` | 43 | `cfc356aca5c8e31826974cd980401ecb26b5347c5d81b20286c58e8151bb3a5e` | `20-43` instantiate SSIT/LFST and leave `waitTable2Rename` as `DontCare`. |
| `src/main/scala/xiangshan/Parameters.scala` | 942 | `efe5471dcea75d4451a57532a65806b12bed68b66e95e69f905800010439f7c6` | `896-905` select SSIT 1024, LFST 64×2, and `StoreSetEnable/LFSTEnable = true`. |
| `src/main/scala/xiangshan/backend/dispatch/Dispatch.scala` | 1291 | `699d64a86166af8d3b2ffc500e44def4b0a13059e60eb705414b4e55d1f26cfc` | `778-792` lets the enabled LFST override the load wait bit and target ROB identity. |
| `src/main/scala/xiangshan/backend/CtrlBlock.scala` | 1069 | `2a4fcc7b97dd6451a778fdaba40bab134d04540abaeb280f8b3857d48f46a0bb` | `226-268` converts detected load/store violations and PC reads into predictor training. |
| `src/main/scala/xiangshan/mem/pipeline/NewLoadUnit.scala` | 2246 | `ac0909afe6704dbf4ed7905c50631e796a4e23dd98c9019a9f5cadd4234ce419` | `1029-1088,1494-1549` classify replay causes and return attempt feedback with the replay queue index. |
| `src/main/scala/xiangshan/mem/lsqueue/LoadQueue.scala` | 347 | `351593ff68ea881183e3da9382a981e7abb16184ab7253fd17e92477e43b6dce` | `227-317` connects replay enqueue, wakeup, RAR/RAW capacity and replay output. |

The Stage 7 anchors contain 1,562 relevant Chisel lines. Shared Stage 5/6 windows are retained in the table because replay classification and queue wiring must be audited together with the new state machines.

### Implemented correspondence

- A failed attempt-0 `Load.PipelineUpdate` allocates one private replay entry and preserves the selected cause. Bank conflict, nuke, DCache replay/WPU fail and the Stage 5 `mshr_nack` alias may retry immediately; TLB, refill, forwarding, memory-address, RAR/RAW, SQ and uncached causes require their matching wake source.
- Readiness feeds private selection and exactly one public attempt-1 `Load.ReplayIssue`. `dcache_miss` and `uncache` select the hardware high-priority entrance; all remaining selected causes use the low-priority entrance. Successful/faulting feedback frees the entry, failed feedback reuses it, and redirect cancels it.
- SSIT training implements all source branches: allocate a common hashed candidate, attach the unassigned PC, merge to the lower SSID, or promote a repeatedly violating same-set load to strict. A valid store lookup allocates LFST state; a matching younger load receives `MDP.WaitPrediction` until store issue or redirect releases it.
- `MDP.WaitPrediction` carries ordering identity only. It enforces prediction → store issue → load issue and has no address/value field, so prediction can delay execution but cannot alter the memory result.

### Bounded abstraction

- One replay retry epoch and one relevant replay entry per load are expanded. A failed attempt-1 records live requeue state without recursively creating an unbounded retry chain; cold-down counters and multi-port arbitration become causal order.
- `Load.ReplayWakeup` is a public summary of the concrete TLB hint, D-channel/refill, store address/data, RAR/RAW capacity, SQ dequeue and MMIO/NC signals. Cause/source compatibility is exact.
- `MDP.EntryConfig` instantiates relevant hashed PC entries. For an invalid entry, `initial_ssid` supplies its precomputed six-bit `XORFold` allocation candidate; this avoids adding bit-level hash machinery while preserving winner selection.
- The physical LFST has 64 sets and width 2. Stage 7 expands one relevant pending store; multi-store capacity and `strictShouldWait` counting remain a documented bound. `WaitTable.scala` behavior is deliberately absent because `MemCtrl` does not instantiate it under `StoreSetEnable=true`.

## Stage 8 aligned scalar-store and VSQ anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/pipeline/NewStoreUnit.scala` | 992 | `18d9f6b743caabb6e3d3c9d290e22d8cd03262f3c4f0f539bbf146fb0b63f5a3` | `37-247,248-537,538-700,701-827` define aligned scalar STA S0-S3; `844-975` wire the stage pipeline and redirect kills. |
| `src/main/scala/xiangshan/mem/pipeline/StdExeUnit.scala` | 83 | `a08a2138082eaa98a741e420883b7d20f2d950af32d261590427df27698c029f` | `28-83` independently validates the SQ window, writes scalar store data, and reports its ROB completion. |
| `src/main/scala/xiangshan/mem/pipeline/Bundles.scala` | 318 | `cb3832e24f1702809484d294f0a1b734844efbdb9e96bebb03f243958a5559f7` | `304-318` defines the S0-S4 store-stage payload capabilities. |
| `src/main/scala/xiangshan/mem/pipeline/package.scala` | 224 | `5e0dd5e8e3d6a2078eeb5bb769a275f8f89de891c312a997728290f21bddad7b` | `153-190` fixes the store S0-S4 enumeration and confirms S4 is the unaligned-only terminal stage. |
| `src/main/scala/xiangshan/mem/lsqueue/VirtualStoreQueue.scala` | 437 | `5f553bb421bc6efbc0e893581022fbb62bbc873b9068ba64df7792c231d92ca9` | `30-206` allocate virtual entries; `238-389` retire in order and recover enqueue/precommit/retire pointers; `413-417` assert walk/full/release invariants. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | `957-977` connects independent STA address and STD data outputs to the LSQ. |
| `src/main/scala/xiangshan/Parameters.scala` | 942 | `efe5471dcea75d4451a57532a65806b12bed68b66e95e69f905800010439f7c6` | `101-112,794-797` define the default physical size 64, virtual multiple 2, snapshot interval 1, and derived size 128. |
| `src/main/scala/top/Configs.scala` | 630 | `a2f321b6d086287be6b6f658c3bd6429343bc68da0e12e9d1bea663d22d8007c` | `541-546` select `BaseConfig` without a queue-size override, so the core-parameter defaults remain active. |

The Stage 8 anchors contain 1,409 non-overlapping relevant Chisel lines: 1,053 for the scalar STA/STD slice and 356 for the VSQ/configuration slice.

### Implemented correspondence

- One scalar store identity expands into independent private STA and STD progress. STA requests store-DTLB translation and publishes the returned physical address and mask; STD publishes the original write value and the same `sq_idx`/mask.
- A successful aligned cached store reaches S3, but the abstract store completion is enabled only after both `Store.AddressReady` and `Store.DataReady` match the operation and SQ index. Observed address/data events are checked against the translation and issue payload, so a wrong value cannot hide beside a solver-derived correct event.
- TLB miss becomes a private replay decision and cannot publish a usable physical address or write back. A translation fault becomes a private fault decision and public `Core.MemoryFault`; redirect kills any affected live STA pipeline before completion.
- Each bounded scalar store allocates one private VSQ entry. Normal `Core.MemoryCommit` retires it in program order; redirect walks and cancels affected entries, publishing the modeled two-cycle physical recover-pointer boundary.
- `composition/store_translation.yaml` proves the generated request uses the separate `sttlb` state, and `composition/scalar_store_queue.yaml` closes pipeline completion through VSQ retirement.

### Bounded abstraction

- The public `Core.MemoryIssue` is the finite proxy for both accepted VSQ dispatch allocation and the two independently scheduled STA/STD micro-ops. Their relative readiness is unconstrained; exact issue-port arbitration and feedback timing are omitted.
- `Core.MemoryWriteback` is one operation-level completion after both micro-op payloads. RTL reports STA and STD ROB progress separately, but Stage 2 deliberately models a scalar memory instruction as one completion unit.
- On an S1 TLB miss, RTL writes an SQ address record whose `tlbMiss` bit makes it unusable. `Store.AddressReady` means usable physical address, so the replay record stays private.
- VSQ owns allocation, ROB-age retirement, snapshots and recovery pointers—not physical address/data valid bits. PSQ pairing storage, youngest byte forwarding, unaligned splitting and drain are intentionally deferred to Stage 9; precommit-to-SBuffer visibility is Stage 10.
- Vector stores, scalar unaligned S4, MMIO/NC, CBO, AMO and LR/SC remain in Stages 11, 12 and 16 as planned.

## Stage 9 physical StoreQueue, forwarding, split and drain anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/lsqueue/NewStoreQueue.scala` | 2161 | `9860fb5e5dc3a9b4891d8ffc4d5332dd3339a8014256601dd3f07488e5ecd20c` | `34-178,180-246` define SQ pointers/entries and base helpers; `247-662` implements two-cycle byte forwarding and youngest selection; `664-807` buffers ordered SBuffer requests; `809-1389` normalizes/splits committed entries; `1392-1471` stores cross-page tails; `1473-1581,1584-2081` connect and update the physical queue. |
| `src/main/scala/xiangshan/mem/lsqueue/LSQBundle.scala` | 331 | `2f6ba41196ef5e5f640ad58ddd3b93134f3004347adc584539f9edaa5ef3cd37` | `71-93,170-203,207-282` define store-address, forwarding, virtual/physical queue, and SBuffer-facing payloads. |

The Stage 9 anchors contain 2,173 newly reviewed Chisel lines. Together with Stages 1-8, the executable source-range union is approximately 14,407 lines.

### Implemented correspondence

- Each scalar store opens a private physical entry. Independent `Store.AddressReady` and `Store.DataReady` writes set separate valid bits; only their all-valid join can cross the bounded precommit boundary. Redirect cancels an affected uncommitted entry and makes late payload writes infeasible.
- An older same-word store with an overlapping byte mask becomes a private forwarding candidate. Candidates are folded in program order, so the final public response names only the youngest match; its mask is the exact store/load intersection. An address match without data reports `data_invalid`, while a disjoint mask reports a miss.
- `aligned` and `within16` layouts emit one normalized `Store.Drain`. `cross16` emits low/high beats through the two modeled EnterSbuffer ports; `cross_page` additionally requires the matching `Store.UnalignedTailReady` value before either beat exists. The bounded tail role admits at most two distinct outstanding identities, matching `SQUnalignQueueSize = 2`.
- Final drain credit is attached to the single beat or high split beat, and a younger drain selection requires every older modeled entry to have drained or been cancelled.
- `composition/scalar_store_physical_queue.yaml` shares the Stage 8-derived address/data events with this PSQ and closes one store through physical commit and SBuffer handoff.

### Bounded abstraction

- µMCM address tokens do not expose byte-offset arithmetic. `Store.Layout` therefore carries the 16-byte-normalized low/high geometry at the StorePipeline→StoreQueue boundary; Stage 12 will derive that descriptor from scalar-unaligned/vector StoreUnit execution. Stage 9 validates and consumes the descriptor rather than inventing a private split decision in the input trace.
- The forwarding priority tree is represented as an age-ordered state fold. Its private candidate cycles are solver serialization points, not additional RTL latency; address/data availability and the final selected value/mask remain exact.
- `Core.MemoryCommit` is the finite proxy for the VSQ precommit/retired pointer crossing the entry. Four-wide commit and two-wide drain capacities are recorded, while exact same-cycle port packing is abstracted to causal order.
- This slice covers cacheable scalar stores. SBuffer merge/visibility is Stage 10, MMIO/NC is Stage 11, scalar-unaligned descriptor production and vector flow are Stage 12, and CBO/atomics are Stage 16.

## Stage 10 SBuffer merge, drain and L1D-acceptance anchors

| File | Lines | SHA-256 | Model consequence |
|---|---:|---|---|
| `src/main/scala/xiangshan/mem/sbuffer/Sbuffer.scala` | 1028 | `56c6e5d5fb5395f2e6c988f6b9fb88b19eec999d5b5354dbea616cf9f526152d` | `32-188` define request/entry/data structures; `191-768` allocate, merge, select, timeout/flush, write and replay entries; `784-860` provide the audited SBuffer load-forwarding path. |
| `src/main/scala/xiangshan/mem/Bundles.scala` | 454 | `653e51763b1a548d64c3fdc8f9aa1e8a1385987ad4703bef38a356e71ca7c53e` | `105-112,151-160` carry SBuffer emptiness, flush, replay and DCache write-port request/response state. |
| `src/main/scala/xiangshan/mem/lsqueue/LSQBundle.scala` | 331 | `2f6ba41196ef5e5f640ad58ddd3b93134f3004347adc584539f9edaa5ef3cd37` | `181-184` define the committed SQ-to-SBuffer address, data, mask and vector metadata. |
| `src/main/scala/xiangshan/mem/MemBlock.scala` | 1604 | `ad445bf2dd4601aff9f8f1d1624af050537e18ca4a1f8cc70d24c4201896cd52` | `896-910,1143-1164,1217` connect SBuffer forwarding, SQ enqueue, DCache write/replay and fence-flush emptiness. |
| `src/main/scala/xiangshan/Parameters.scala` | 942 | `efe5471dcea75d4451a57532a65806b12bed68b66e95e69f905800010439f7c6` | `176-178,821-823` select 16 entries, threshold 9, two enqueue ports and one DCache write port. |

The Stage 10 anchors contain 878 relevant Chisel lines. Of these, 19 overlap the Stage 5/9 connection and payload ranges, so this stage adds approximately 859 lines to an executable source-range union of approximately 15,266 lines.

### Implemented correspondence

- The first committed `Store.Drain` beat allocates a private entry and installs its 64-byte-aligned line data/mask. A second active-entry beat for the same line derives a private `SBuffer.Merge`; `masked_merge` gives every enabled byte to the later beat and `mask_union` preserves all written bytes.
- Threshold, timeout, force-write, microarchitectural flush, and fence flush select an active entry for the single DCache write port. Selection changes it to inflight, preventing a later same-block entry from bypassing it.
- A replay response retains the inflight entry and produces the same line/mask on attempt 1. A successful `L1.Response` derives private `SBuffer.WriteAccepted` and releases the entry; request identity, payload and retry epoch cannot change.
- `Core.MemoryOrdered` for a modeled fence requires every older modeled SBuffer entry of that hart to have been accepted. `composition/scalar_store_sbuffer.yaml` closes Stage 8/9 address/data/commit state through PSQ drain and into the Stage 10 L1 request.

### Bounded abstraction

- `SBuffer.LineLayout` expands one finite physical-entry episode with one or two 16-byte contributors placed into a 64-byte line. Real entries may absorb more contributors before drain; arbitrary-depth merge chains are represented by composing additional bounded episodes rather than reproducing the full 16-entry array and PLRU implementation.
- Drain counters, replacement arbitration and port handshakes are stutter-compressed into causal ordering. The selected trigger remains explicit as `threshold`, `timeout`, `force`, `uarch_flush`, or `fence`.
- One DCache replay/resend epoch is expanded. Further replay preserves the same inflight invariant but is outside the current finite witness.
- A successful Stage 10 response means the committed store was accepted by L1D, not that it is globally observable. L1 hit/miss/coherence and the ultimate memory-visible point belong to Stages 13-20.
- The SBuffer load-forwarding RTL was audited, but combining it with SQ/MSHR/TLD sources is deferred to the Stage 12/13 load-data composition. Full fence completion also depends on SQ and MSHR emptiness and is finalized in Stage 16.
