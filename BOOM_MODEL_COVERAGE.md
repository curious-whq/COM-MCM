# BOOM memory µMCM coverage at v0.18

This file is an inventory, not a claim that the entire BOOM RTL is modeled signal-for-signal. `covered` means the current µMCM contains the memory-order-relevant behavior needed to expose that path at a module boundary. `partial (source-grounded)` means an executable subset is tied to named RTL regions and its omissions are listed. `abstracted` means a deliberate boundary model exists. `future` means the behavior is not yet represented adequately for blind bug discovery.

| Area | Status | Current semantic surface |
|---|---|---|
| LDQ allocation/lifetime | covered | allocate, address, executed, succeeded, observed, order-fail, squash, commit |
| Load TLB retry | covered | miss, retry queue, retry issue, translated request |
| Load nack/wakeup | covered | nack clears executed, sleep/wakeup, re-execution |
| LD-LD ordering | covered | generic pair search, observed-younger conflict, buggy/fixed recovery |
| STQ/SDQ abstraction | covered | allocate, address/data ready, commit/drain/ack/clear |
| Store→Load forwarding | covered | overlap/age-based forwarding surface |
| ST-LD violation | covered | generic order-fail path |
| Fence | covered | wait for DCache ordered and release |
| Branch/exception recovery | covered | load/store kill/flush, retry-queue effects, ROB younger squash, branch-kill broadcast |
| L1 request/response boundary | covered | request accept, hit/miss private outcome, response/nack |
| L1 Probe boundary | covered | source-pinned clean ProbeAck and dirty ProbeAckData, permission downgrade/invalidation, and data publication |
| MSHR primary/secondary/RPQ | covered | admission, RPQ, refill/direct response/replay |
| MSHR SDQ/IOMSHR | covered | bounded store-data lifetime and MMIO-MSHR path |
| MSHR writeback/meta/finish | covered | memory-order-relevant state-machine path |
| ROB | covered | bounded allocation, completion, in-order commit, fault record, precise exception, younger squash |
| BOOM v4 NBDTLB lookup/FSM | partial (source-grounded) | per-hart entry validity, hit/miss, one outstanding `READY→REQUEST→WAIT→READY` walk, refill, miss-ready, and all/VPN SFENCE invalidation |
| LSU translation retry | covered | TLB miss records a virtual address, round-trips through the LSU-owned retry queue, and reissues only after NBDTLB miss-ready |
| PTW/page table | abstracted | bounded external `Core.PageMap → TLB.PTWResult`; this is not claimed as Rocket Chip PTW implementation |
| TLB replacement/permissions | future | sectored/superpage arrays, PLRU, PMP/PMA, full R/W/X privilege rules, multiple-hit flush, passthrough/kill, and same-cycle two-port arbitration |
| AMO end-to-end | covered (core-side) | translated request, serialized read/write, ROB commit, architectural AMO; a dedicated L2 atomic path remains future work |
| LR/SC end-to-end | covered (core-side) | reservation set, DCache probe invalidation, state-derived SC success/failure, successful pair projection |
| MMIO/uncacheable end-to-end | covered (core-side) | translation, single-outstanding IOMSHR load/store, completion, ROB retirement |
| L2 directory and MSHR plan | partial (source-grounded) | pinned SiFive InclusiveCache INVALID/BRANCH/TRUNK/TIP metadata, hit/miss, serialized per-line request, private outer refill, grant retirement |
| Multi-hart coherence state | covered (bounded) | two inner clients, per-line N/B/T permissions, owner/sharers, probes, GrantAck, ReleaseAck, and state-derived transitions |
| Coherent data/version flow | covered (bounded) | stores create private L1 ghost versions; ProbeAckData/ReleaseData publish them; GrantData returns the current L2 tuple |
| L2 replacement/SRAM/timing | future | set/way victim selection, data-bank beats, hazards, ready/valid stalls, and arbitration latency |
| Concurrent L2 transactions | future | secondary MSHRs, scheduler queues, nested writeback/probe interactions, and cross-line resource contention |
| Prefetch | intentionally abstracted | excluded from current memory-order surface |
| HellaCache/debug/perf | intentionally abstracted | not currently treated as architectural memory-order behavior |

## Composition boundary

The detailed `memory_buggy.yaml` / `memory_fixed_reference.yaml` compositions continue to own ordinary cacheable LSQ/L1/MSHR behavior. `core_side_v017.yaml` owns ROB, NBDTLB/LSU retry, bounded PTW, atomic, fence, MMIO, and recovery behavior. `coherence_v018.yaml` independently owns the new BOOM-L1/SiFive-L2 permission and data protocol. All are executable strict compositions; a signal-level adapter unifying their three root request vocabularies is not claimed yet.

## Hierarchy status

The v0.15 enforceable hierarchy boundary remains mandatory in v0.18:

- state is private to its module;
- internal event vocabulary is separate from ports;
- only ports can be connected across modules;
- strict compositions cannot constrain private child slots;
- `project-interface` hides private events without synthesizing witness-specific summaries.

This inventory should be updated whenever a new BOOM memory-relevant path is added.
