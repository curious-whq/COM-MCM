# BOOM memory µMCM coverage at v0.15

This file is an inventory, not a claim that the entire BOOM RTL is modeled signal-for-signal. `covered` means the current µMCM contains the memory-order-relevant behavior needed to expose that path at a module boundary. `abstracted` means a deliberate boundary model exists. `future` means the behavior is not yet represented adequately for blind bug discovery.

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
| Branch/exception recovery | covered | load/store kill/flush and retry-queue effects |
| L1 request/response boundary | covered | request accept, hit/miss private outcome, response/nack |
| L1 Probe boundary | covered | probe capture/release; detailed cold paths remain a lower-level modeling target |
| MSHR primary/secondary/RPQ | covered | admission, RPQ, refill/direct response/replay |
| MSHR SDQ/IOMSHR | covered | bounded store-data lifetime and MMIO-MSHR path |
| MSHR writeback/meta/finish | covered | memory-order-relevant state-machine path |
| ROB | abstracted | architectural operation, commit, exception, squash boundary |
| TLB internals/PTW | abstracted | hit/miss/retry is represented, TLB/PTW state machine is not |
| AMO end-to-end | partial | LSQ/L1 pieces exist; complete architectural/ROB/coherence path is future |
| LR/SC end-to-end | partial | L1 reservation behavior is not part of the current v0.15 hierarchy baseline |
| MMIO/uncacheable end-to-end | partial | IOMSHR exists; complete core-side serialization is future |
| L2/directory/coherence | future | current `coherence` module is only an existential environment |
| Multi-hart coherence state | future | no owner/sharer/version state machine yet |
| Prefetch | intentionally abstracted | excluded from current memory-order surface |
| HellaCache/debug/perf | intentionally abstracted | not currently treated as architectural memory-order behavior |

## Hierarchy status

v0.15 adds the first enforceable hierarchy boundary:

- state is private to its module;
- internal event vocabulary is separate from ports;
- only ports can be connected across modules;
- strict compositions cannot constrain private child slots;
- `project-interface` hides private events without synthesizing witness-specific summaries.

This inventory should be updated whenever a new BOOM memory-relevant path is added.
