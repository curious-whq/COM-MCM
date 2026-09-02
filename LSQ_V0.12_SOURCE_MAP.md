# BOOM LSU → v0.12 LSQ source map

Source: user-supplied BOOM v4 LSU Chisel, 2183 lines.
SHA-256: `81d738e8c8967f0fad72a2406a623a384fac229e10c20ffa37a6907aece9b7b5`.

| Model area | Chisel lines | Modeled semantics |
|---|---:|---|
| LSU intent | 12–35 | LDQ/STQ/SDQ, optimistic loads, retry, forwarding, ordering failures |
| LDQ fields | 174–193, 221–250 | address, executed, succeeded, order_fail, observed, forwarding |
| STQ fields | 196–209, 255–278 | address/data, committed, succeeded, can_execute, cleared |
| Dispatch | 340–435 | LDQ/STQ allocation and initial state |
| Retry queue | 506–547 | load/store virtual-address retry identity and dequeue |
| Scheduling | 579–700 | eligibility/priority abstracted to feasible event selection |
| TLB / physical address | 711–855, 960–990 | load/store miss/hit/address state |
| DCache issue | 858–990 | load issue and committed store drain boundary |
| LD/ST search | 1112–1152 | generic search events and age/address/mask inputs |
| Release observed | 1207–1214 | matching release marks LDQ observed |
| ST-LD failure | 1216–1235 | younger executed load can receive order_fail |
| LD-LD bug | 1238–1255 | buggy assertion-only path; fixed-reference path restores order_fail |
| Additional ordering | 1274–1320 | nack/forwarding-related load ordering checks represented in shared order-fail surface |
| STQ forwarding masks | 1325–1404 | overlap/coverage, Store→Load forwarding, AMO blocking |
| Ordering exception | 1458–1475 | order_fail → MINI_EXCEPTION_MEM_ORDERING |
| Nack | 1542–1549 | load executed cleared |
| Response | 1557–1585 | response value and succeeded state |
| Store→Load forward | 1618–1654 | forwarded data, source STQ identity, load success |
| Branch recovery | 1692–1727 | speculative LDQ/STQ invalidation |
| Commit | 1745–1788 | store committed/can_execute; load retirement preconditions |
| Store/fence clear | 1790–1809 | successful store or ordered fence leaves queue |
| Exception/reset | 1925–1960 | LDQ reset; uncommitted unsuccessful stores invalidated |

## Deliberate abstractions

- Physical circular pointer/carry-bit implementation is replaced by bound LDQ/STQ identity plus `program_index` for relative dynamic age.
- Arbitration/backpressure can insert stutter cycles; only memory-order-relevant acceptance/search/response events are retained.
- Detailed TLB exception classes and uncacheable/HellaCache paths are not yet part of the memory-order semantic surface.
- Optional load-to-store register-data forwarding does not currently generate a separate event because the present execution graph does not consume register-data-dependency provenance.
