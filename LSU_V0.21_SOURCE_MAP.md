# BOOM v4 LSU scheduler source map (v0.21)

Pinned BOOM revision: `58ef2720eae13be26b3008c02b5a74ce29c61c44`  
Pinned `lsu.scala` SHA-256: `405dffe86cca0d5632ee75f481b6a64202691e2e169e6a5961363d20ca33a40e`

| BOOM source | Executable rule | Model surface |
|---|---|---|
| `lsu.scala:579-614` | per-port can-fire snapshot and fixed-port guards | `LSU.ArbitrationFrame`, `validate_source_port_guards_*` |
| `lsu.scala:616-632` | load-wakeup eligibility presented to scheduler | `can_load_wakeup`; detailed LDQ producer remains in `model/lsu/module.yaml` |
| `lsu.scala:644-659` | one TLB, DCache and LCAM token per port | `LSU.ArbitrationDecision.{tlb_used,dcache_used,lcam_used}` |
| `lsu.scala:668-679` | all twelve `lsu_sched` calls in exact source order | `evaluate_source_order_*`, twelve `grant_*` rules |
| `lsu.scala:682` | incoming agen cannot be backpressured | executable load/store agen assertions in `evaluate_source_order_*` |
| `lsu.scala:684-691` | selected load blocks same-entry wakeup and drives TLB-valid | selected grant class and resource-use fields |
| `lsu.scala:693-703` | global requests cannot run down both pipes; `lsuWidth <= 2` | fixed-port guards plus `lsu_width ∈ {1,2}` |
| `lsu.scala:872-960` | selected DCache request payload mux | `DCacheIssueIntent + ScheduleGrant → DCacheReqValid` |
| `lsu.scala:1535-1548` | a nacked store flushes the execute queue and rewinds its head to the older failed STQ entry | `DCache.RequestNack → StoreExecuteQueueFlush → StoreReenqueue →` second exact `ScheduleGrant/StoreDrainIssue` |

The scheduler model is in `examples/boom/model/lsu/port_scheduler_v021.yaml`.
`ArbitrationDecision` is private. The LSU/L1 boundary remains the existing
public `LSU.DCacheReqValid` event, so the L1 never reads scheduler or LDQ state.
The finite scheduler role supports two attempt identities per instruction;
attempt 1 is enabled only by a public store nack, not by an input path hint.

The targeted integration composition
`examples/boom/composition/lsu_l1_source_v021.yaml` proves the path
`can_load_agen → load-agen-exec grant → DCacheReqValid → L1 s0/s1/s2 → hit`.
The ordinary instruction path constructs its first arbitration frame, and the
bounded store-nack path constructs the second. Connecting that second drain
through another DCache/L1 request pipeline remains default-composition work.
