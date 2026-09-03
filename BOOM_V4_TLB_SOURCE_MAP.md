# BOOM v4 NBDTLB → v0.17 source map

The v0.17 DTLB slice is grounded in the official `riscv-boom/riscv-boom` repository at commit:

```text
58ef2720eae13be26b3008c02b5a74ce29c61c44
```

The repository contains both [`src/main/scala/v4/lsu/tlb.scala`](https://github.com/riscv-boom/riscv-boom/blob/58ef2720eae13be26b3008c02b5a74ce29c61c44/src/main/scala/v4/lsu/tlb.scala) and the LSU integration in [`src/main/scala/v4/lsu/lsu.scala`](https://github.com/riscv-boom/riscv-boom/blob/58ef2720eae13be26b3008c02b5a74ce29c61c44/src/main/scala/v4/lsu/lsu.scala). The TLB is therefore not inferred from generic behavior: BOOM's LSU instantiates `NBDTLB`, while the LSU separately owns translation retry.

Upstream file SHA-256 digests at that commit:

```text
tlb.scala  7475aac154e066826a04394c7806af73b58dca7c6b5ed5c819c610096ca8e4a9
lsu.scala  405dffe86cca0d5632ee75f481b6a64202691e2e169e6a5961363d20ca33a40e
```

| Model behavior | Official BOOM v4 source |
|---|---|
| `NBDTLB` ports (`req`, `resp`, `miss_rdy`, `sfence`, `ptw`, `kill`) | `tlb.scala:18-27` |
| Entry tag/data/valid and VPN invalidation | `tlb.scala:29-118` |
| Sectored/superpage entry banks and walker FSM registers | `tlb.scala:120-146` |
| Hit/PPN lookup | `tlb.scala:174-180`, `276-277` |
| Permission, cacheability, AMO/LR-SC checks | `tlb.scala:181-274` |
| Duplicate-hit miss/flush behavior | `tlb.scala:288-293`, `362-364` |
| TLB response fields and `miss_rdy` | `tlb.scala:295-319` |
| PTW request/refill FSM | `tlb.scala:321-350` |
| SFENCE invalidation | `tlb.scala:352-364` |
| LSU instantiates and connects `NBDTLB` | `lsu.scala:313-317` |
| LSU retry queue enqueue/dequeue | `lsu.scala:506-547` |
| Load/store translation retry eligibility | `lsu.scala:595-606` |
| LSU resource priority and retry issue | `lsu.scala:644-679` |
| LSU constructs TLB requests | `lsu.scala:711-774` |
| LSU consumes translation exceptions and miss | `lsu.scala:776-830` |
| TLB miss kills cache issue; retry uses translated address | `lsu.scala:890-905`, `960-984` |

## v0.17 semantic boundary

Implemented as source-grounded, bounded behavior:

- per-hart NBDTLB walker state (`READY → REQUEST → WAIT → READY`);
- finite entry-valid state that determines hit versus miss;
- a miss captures one walk, emits a PTW request, refills the entry, and reasserts miss-ready;
- the LSU, not the TLB, owns the retry event and reissues the translation;
- page faults are observed on a post-refill TLB response and then delivered by the LSU;
- all-entry and VPN-scoped SFENCE invalidation;
- independent state for different harts.

Deliberately abstracted or deferred:

- `Core.PageMap` and `bounded_ptw_environment` stand in for the external Rocket Chip PTW/page-table subsystem;
- sectored and superpage bank geometry, PLRU replacement, and fragmented-superpage matching;
- full R/W/X, SUM/MXR, PMP/PMA, cacheability, and AMO permission calculations;
- canonical-address and misalignment faults;
- duplicate-hit flushing, passthrough, kill, and same-cycle two-port arbitration.

These items are marked partial/abstracted in `BOOM_MODEL_COVERAGE.md`; they are not reported as completed BOOM behavior.
