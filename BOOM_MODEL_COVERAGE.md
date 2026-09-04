# BOOM memory µMCM coverage at v0.21

This file is an inventory, not a claim that the entire BOOM RTL is modeled signal-for-signal. `covered` means the current µMCM contains the memory-order-relevant behavior needed to expose that path at a module boundary. `partial (source-grounded)` means an executable subset is tied to named RTL regions and its omissions are listed. `abstracted` means a deliberate boundary model exists. `future` means the behavior is not yet represented adequately for blind bug discovery.

The retained v0.19 executable coverage report is
`examples/boom/coverage/BOOM_PATH_COVERAGE.yaml`, but its path witnesses do not
establish an integrated source-complete BOOM model. The former v0.21 blind
result used a cacheable-path summary and has been withdrawn. The authoritative
rebuild status and source mapping now live in
`examples/boom/source/v021.yaml`.

| Area | Status | Current semantic surface |
|---|---|---|
| LDQ allocation/lifetime | partial (source-grounded) | empty-tail bounded LDQ/STQ allocation is derived from dispatch order; wraparound, simultaneous multiport allocation and redirect interaction still need integration |
| Load TLB retry | covered | miss, retry queue, retry issue, translated request |
| Load nack/wakeup | covered | nack clears executed, sleep/wakeup, re-execution |
| LD-LD ordering | covered | generic pair search, observed-younger conflict, buggy/fixed recovery |
| STQ/SDQ abstraction | covered for ordinary stores (source-derived bounded) | STQ allocate, independent physical-address/data ready, delayed ROB-ready, commit, drain, hit-or-MSHR-accept ack and head clear; a DCache nack rewinds/re-enqueues the execute queue and reaches a second exact scheduler/drain decision; MSHR SDQ data is retained until store replay |
| Store→Load forwarding | covered | overlap/age-based forwarding surface |
| ST-LD violation | covered | generic order-fail path |
| Fence | covered | wait for DCache ordered and release |
| Branch/exception recovery | covered | load/store kill/flush, retry-queue effects, ROB younger squash, branch-kill broadcast |
| LSU per-port scheduling | covered (source-derived) | all twelve source-ordered `lsu_sched` classes share exact per-port TLB/DCache/LCAM tokens; fixed-port guards, fast/slow store drain and incoming-agen assertion are executable; the selected DCache payload is connected to the generalized L1 |
| LSU LDQ runtime in detailed composition | covered for ordinary loads (source-derived bounded) | dispatch allocation, translated physical address, DCache fire/executed, nack, hit/refill success, Probe observed, ROB deallocation, and the source `assert(false.B)` older-load/observed-younger case are generated without LSU-local TLB outcome inputs |
| L1 request/response boundary | covered (source-derived bounded) | finite requests traverse s0/s1/s2; per-set/per-way tag and permission state derives read/write hit, tag miss, permission miss, replacement metadata, load response, store hit/MSHR-accept acknowledgement and all five source nack classes |
| L1 data/refill/bypass | covered (source-derived bounded) | runtime MSHR meta/refill interfaces update selected ways; store hits and fixed-way MSHR replays produce the timed s3 write and next-cycle ghost-word availability for the source s3/s4/s5 bypass |
| L1 Probe boundary | covered (source-derived bounded) | generalized ProbeUnit metadata lookup, MSHR retry, clean ProbeAck, dirty writeback/ProbeAckData, toN invalidation and toB downgrade; subsequent accesses observe the updated line state |
| L1 TileLink probe integration | partial | clean `TL.Probe → ProbeReceive → ProbeRelease → TL.ProbeAck` is connected through public interfaces; dirty ProbeAckData and separate per-hart generalized L1 instances remain |
| MSHR primary/secondary/RPQ | covered (source-derived bounded) | a fixed two-entry Small/Medium BOOM pool derives round-robin primary IDs, same-block secondary IDs, conflict/all-busy blocking, finish reuse, Probe gating, and Rocket-Chip write-intent checks; allocator permits are connected to phase-dependent entry ready, primary/secondary acceptance, and explicit RPQ lifetime |
| MSHR SDQ/IOMSHR | covered | bounded store-data lifetime, internally allocated SDQ entry, RPQ fixed-way replay/free, and MMIO-MSHR path |
| MSHR writeback/meta/finish | partial (source-grounded) | memory-order-relevant state-machine path plus A/D/E closure are executable in a bounded primary-path integration trace |
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

The historical directed compositions remain independently executable:
`memory_buggy.yaml` / `memory_fixed_reference.yaml` own the detailed ordinary
LSQ/L1/MSHR slice, `core_side_v017.yaml` owns the core-side extensions, and
`coherence_v018.yaml` owns the BOOM-L1/SiFive-L2 protocol.

The rebuild also contains deliberately narrow source-integration
compositions: `lsq_source_v021.yaml` derives empty-tail queue allocation,
`l1_source_v021.yaml` derives generalized four-way L1 decisions and Probe/refill state changes,
`lsu_port_scheduler_source_v021.yaml` derives the exact per-port arbitration result,
`lsu_l1_source_v021.yaml` connects the selected DCache request into that generalized L1,
`mshr_allocator_source_v021.yaml` derives MSHR primary/secondary selection and
IDs, `mshr_entry_frontend_source_v021.yaml` connects that selection to fixed
entry phase, RPQ and bounded SDQ readiness, and `mshr_tilelink_source_v021.yaml`
closes the detailed MSHR primary path through InclusiveCache TileLink A/D/E.
The integrated `tlb_lsu_l1_source_v021.yaml` now carries ordinary load and
store hit, TLB-retry and cold-miss paths through retirement, including the
store MSHR-accept acknowledgement and later RPQ/SDQ replay. It is still not the
default blind-search composition until the remaining source-ledger blocker is
closed.

The old `coherence_blind_v021.yaml` / `core_blind_v021.yaml` join is retained
only as a rejected prototype: the latter includes
`model/search/cacheable_path.yaml` and is not an admissible detailed BOOM
realization. `umcm search boom --rvwmo` is deliberately blocked until the
default detailed full-memory composition passes the v0.21 source ledger gate.

## Hierarchy status

The v0.15 enforceable hierarchy boundary remains mandatory in v0.21:

- state is private to its module;
- internal event vocabulary is separate from ports;
- only ports can be connected across modules;
- strict compositions cannot constrain private child slots;
- `project-interface` hides private events without synthesizing witness-specific summaries.

This inventory should be updated whenever a new BOOM memory-relevant path is added.
