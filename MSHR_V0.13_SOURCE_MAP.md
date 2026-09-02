# BOOM MSHR/RPQ µMCM source map — v0.13

Source used for this iteration: supplied BOOM v4 `BoomMSHR`, `BoomMSHRFile`, and `BoomIOMSHR` Chisel.
SHA-256: `7e70d1a095f9543ecb20c2983e925205ef473376fe7e6112173d7e8079069fcf`.

The model is intentionally memory-order semantic rather than signal-for-signal RTL duplication.

| Model surface | Chisel source | µMCM representation |
|---|---|---|
| Primary/secondary request interface | lines 39–54, 120–135 | `DCache.MSHRRequest`, `MSHR.PrimaryAccept`, `MSHR.SecondaryMissAccept` |
| 18-state MSHR controller | lines 96–107, 234–384 | persistent `MSHR[id].state` with abstract state names |
| RPQ admission and branch/exception kill | lines 128–135 | per-request `rpq_valid/killed`, `RPQInsert/RPQKill` |
| AcquireBlock | lines 164–170, 241–245 | `MSHR.AcquireBlock` |
| Grant/refill into line buffer | lines 124, 196–199, 246–263 | `GrantData/GrantNoData`, `LineBufferWrite`, `RefillComplete` |
| Direct load drain | lines 266–300 | `DirectLoadResponse`, `RPQDequeue(disposition=direct)` |
| Metadata / eviction / refill commit | lines 302–337 | `MetaRead*`, `MetaClear`, `Writeback*`, `CommitLine`, `RefillWrite` |
| Replay path | lines 338–349 | `MSHR.Replay`, `RPQDequeue(disposition=replay)` |
| Meta write / GrantAck finish | lines 351–368 | `MetaWrite`, `MemFinish` |
| Probe readiness | lines 144–154 | persistent abstract `probe_rdy`, query event `ProbeBlocked` |
| IOMSHR | lines 389–469 | `IOMSHR.Request → MemAccess → MemAck → Response` |
| SDQ | lines 550–559, 734–741 | `SDQAllocate/SDQFree` + per-store validity |
| MSHR matching / primary vs secondary | lines 571–620 | shared `mshr_id`, primary/secondary request roles |
| Per-MSHR arbiters | lines 581–586, 638–661 | event-level arbitration is abstracted; outputs retain MSHR identity |
| MSHR allocation policy | lines 598–678 | bounded trace supplies chosen `mshr_id`; allocation algorithm itself remains abstract |
| Response queue | lines 720–724 | `ResponseEnqueue → ResponseDequeue` |
| `fence_rdy` / `probe_rdy` aggregation | lines 594–668 | `FenceBlocked` / `ProbeBlocked` observations |

## Important abstractions

1. Refill beats are summarized by one `RefillComplete` event. The line-buffer value/source are preserved.
2. The RPQ is represented per bounded dynamic request rather than as a concrete circular queue implementation.
3. The transition from `s_drain_rpq_loads` to metadata processing is exposed as an explicit `MetaReadRequest` boundary. It is only taken when the query/path chooses the RPQ-empty case; this avoids incorrectly leaving the drain state after the first of several merged loads.
4. `mshr_id` is supplied/observed by the bounded Trace in v0.13. The concrete round-robin allocator is not yet solved symbolically.
5. `BoomIOMSHR` is modeled separately from cacheable MSHRs.
6. Prefetch-specific states are outside the v0.13 memory-order surface.
