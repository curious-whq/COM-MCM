# Iteration 17 report

## Result

v0.17 adds an executable BOOM core-side memory model without changing the v0.16 RVWMO checker or pretending to implement v0.18 coherence.

The principal acceptance criterion is met: the input trace for `tlb_retry_mmio_load.yaml` contains no TLB outcome event, yet completion derives an LSU request, NBDTLB miss, PTW request/result, refill, miss-ready, LSU retry, uncacheable request/response, ROB commit, and architectural load retirement.

## Delivered

- Nine strict-hierarchy modules in `core_side_v017.yaml`, including separate LSU translation, NBDTLB, and bounded PTW environment boundaries.
- `examples/boom/composition/core_side_v017.yaml` with public-event connections only.
- BOOM v4 source-pinned NBDTLB valid/walker state, hit/miss, single outstanding walk, refill, miss-ready, and SFENCE invalidation.
- LSU-owned translation retry, matching the retry queue and `miss_rdy` split in BOOM v4 `lsu.scala`.
- Corrected page-fault path: PTW response refills, retry sees the permission fault, and LSU reports it to the ROB.
- Per-entry ROB state, ordered commit, precise memory exception, younger squash, and branch recovery.
- AMO serialization and state-derived LR/SC success or failure.
- DCache probe-to-reservation invalidation adapter.
- Fence and one-outstanding MMIO/uncacheable paths.
- BOOM RVWMO projection support for `Arch.AMO`, `Arch.LR`, successful `Arch.SC`, and `Arch.LRSCPair`.
- Ten directed core traces and 13 focused tests.

## Regression result

```text
158 passed in 129.43s
```

The 145 v0.16 tests pass unchanged, and all 13 focused v0.17 tests pass.

## Deferred deliberately

- Real L2/directory owner, sharer, permission, version, Acquire/Grant/Probe/Release semantics.
- A unified signal-level adapter combining the new decoded core request with the existing detailed cacheable LSQ/L1/MSHR composition.
- Rocket Chip PTW internals; the current PTW boundary is a finite environment.
- NBDTLB sectored/superpage replacement, PLRU, full privilege/PMP/PMA permissions, multiple-hit flush, passthrough/kill, and simultaneous two-port arbitration.
- MMIO ordering rules inside the architectural RVWMO checker; v0.16 continues to reject non-main-memory projection rather than approximate it.
- Exhaustive path coverage generation, which is the v0.19 milestone.
