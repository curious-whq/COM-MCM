# Iteration 21 rebuild report

## Current outcome

The earlier blind-rediscovery result has been withdrawn. It used a
witness-oriented cacheable-path summary and therefore did not meet the stated
requirement of searching the detailed BOOM LSQ/L1/MSHR/L2 model.

The rebuilt v0.21 is currently in the **model-integration** phase,
not the search phase. The default `umcm search boom --rvwmo` profile returns a
blocked stage until the source ledger has no unresolved items.

## Completed in this rebuild

- pinned BOOM, Chipyard, Rocket-Chip and SiFive InclusiveCache revisions;
- pinned hashes for LSU, DCache, MSHR, TLB, ROB, Rocket-Chip client metadata
  and L2 protocol files;
- machine-readable behavior-to-source ranges;
- an executable provenance auditor that distinguishes mapped from implemented;
- an acceptance test that keeps the old `model/search/cacheable_path.yaml`
  prototype out of the default search path;
- bounded LDQ/STQ allocation derived from `Core.MemoryInstruction` dispatch
  order, with no queue-index annotations in the input trace;
- a source-derived DCache/MSHR TileLink adapter for A/D/E;
- a detailed-MSHR + InclusiveCache primary-miss trace in which L2, rather than
  the input, produces `TL.Grant`, and the matching source ID reaches MSHR
  refill/response and `TL.GrantAck`;
- a source-derived two-entry `BoomMSHRFile` allocator for Small/Medium BOOM:
  round-robin primary selection, same-block secondary matching, same-index
  conflict, all-busy backpressure, finish/reuse, Probe rejection, and
  Rocket-Chip `isWriteIntent`-derived second-Acquire rejection;
- focused tests for source hashes, the rejection gate, internal queue
  allocation, and MSHR/L2 Grant provenance.
- a generalized, source-pinned four-way L1D model: finite per-set/per-way tag,
  permission and data state; s0/s1/s2; state-derived hit/tag miss/permission
  miss; replacement metadata; five nack causes; MSHR meta/refill writes;
  store write/bypass timing; and the ProbeUnit clean/dirty/toN/toB paths;
- focused L1 tests whose inputs contain no dynamic hit/miss/nack/writeback
  outcome, including state-changing Probe and refill cases followed by a load.
- a source-derived LSU per-port scheduler that executes all twelve `lsu_sched`
  calls in source order over one TLB, DCache and LCAM token per port, including
  fixed-port guards, `lsuWidth <= 2`, fast/slow store-drain priority and the
  non-backpressured incoming-agen assertion;
- an executable selected-request mux and a strict LSU→L1 composition proving
  `can_load_agen → ScheduleGrant → DCacheReqValid → s0/s1/s2 → LoadHit` without
  reading L1-private state;
- a strict two-entry MSHR-file/entry composition in which allocator permits
  must be discharged by the selected entry's phase-dependent
  `PrimaryReady`/`SecondaryReady`; primary and secondary accepts populate the
  RPQ, store/SC/AMO requests allocate internally indexed SDQ entries, and an
  entry in meta-write/finish rejects a late secondary;
- a source-derived LDQ runtime that removes the old LSU-owned environment
  `TLBHit/TLBMiss` slots from the integrated path and consumes only the NBDTLB
  translation result plus public DCache/ROB events;
- a strict instruction-to-retirement ordinary-load path: hit, TLB retry and
  cold InclusiveL2 refill all reach LDQ success, ROB commit and architectural
  retirement with value continuity;
- an executable BOOM `assert(false.B)` case for an older retry search finding
  an already completed and coherence-observed younger same-address load;
- a source-derived clean TileLink B/C bridge through the detailed DCache
  ProbeUnit public boundary;
- a source-derived ordinary-store runtime: STQ allocation, independent address
  and data readiness, delayed ROB-ready, in-order commit, post-commit drain,
  DCache acknowledgement and committed-head clearing;
- integrated ordinary-store TLB-hit and TLB-miss/PTW/retry paths through the
  exact LSU scheduler and generalized L1 hit path;
- an integrated cold-store path in which MSHR selection and SDQ allocation are
  internal, L1 acknowledges the store when the MSHR request fires, TileLink
  acquires T permission, and RPQ replay later writes the SDQ value into L1 and
  marks the line dirty;
- private L1 cause-union events that retain exact producer checks while
  allowing both hit/MSHR-accept acknowledgement and hit/replay data writes;
- a bounded store-nack recovery segment matching BOOM's execute-queue flush
  and head rewind: the committed entry re-enqueues and receives a second
  `store-commit-fast/slow` decision from the same exact scheduler;
- complete regression: 238/238 tests pass, including the affected
  L1/MSHR/LSU/store and finite-attempt parameterization cases.

## Not yet complete

- ordinary load and store hit/retry/cold-miss paths are now part of the bounded
  instruction-to-retirement integration, but the post-nack second DCache/L1
  pipeline, per-hart generalized L1 instances, the dirty ProbeAckData bridge,
  and the search reset-state adapter are not yet complete;
- no revised blind-search claim is made.

The authoritative source ledger now has 33/34 executable entries. Its only
remaining blocker is the default detailed full-memory composition.
