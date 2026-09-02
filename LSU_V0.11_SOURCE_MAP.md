# BOOM LSU → v0.11 Load-Side Model Source Map

Source snapshot SHA-256:

```text
81d738e8c8967f0fad72a2406a623a384fac229e10c20ffa37a6907aece9b7b5
```

This map records the supplied Chisel regions used to build the v0.11 generic load-side model.

| Model behavior | Supplied LSU source lines |
|---|---:|
| LDQ fields (`executed`, `succeeded`, `order_fail`, `observed`, forwarding metadata) | 174–193, 221–250 |
| Dispatch / LDQ allocation and reset of per-load bits | 375–403 |
| Load wakeup candidate selection | 499–503 |
| TLB-miss retry enqueue and identity preservation | 506–547 |
| Retry/wakeup eligibility | 595–632 |
| LSU scheduling/resource priority | 644–679 |
| TLB request and miss detection | 711–830 |
| DCache request issue / retry issue | 872–905 |
| LDQ address write after translation | 960–970 |
| LD–LD / ST–LD search framework | 1112–1266 |
| Nack/forwarding interaction with ordering search | 1274–1320 |
| Executed-bit update | 1386–1388 |
| Load order-fail exception selection | 1458–1475 |
| DCache nack clears `ldq_executed` | 1542–1548 |
| DCache/long-latency response sets success and value | 1557–1585 |
| Branch recovery invalidates loads | 1718–1727 |
| Load commit guard and deallocation | 1749–1765 |
| Exception/reset invalidates LDQ | 1928–1960 |

## Deliberately not generalized in v0.11

- STQ lifecycle and store drain.
- Store→Load forwarding (`forward_std_val` is represented as state but not yet generated).
- General pairwise LD–LD/ST–LD search instantiation for arbitrary load/store sets.
- Full byte-mask semantics from `GenByteMask`.
- `ldq_head/ldq_tail` pointer and wrap-around allocation/reuse.
- Fence / AMO / LR-SC behavior.
