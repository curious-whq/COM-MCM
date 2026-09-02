# Iteration 14 — formal BOOM L1 / DCache model

## Goal

Replace the witness-era L1 bridge with a reusable L1/DCache/ProbeUnit/WritebackUnit operational model grounded in the supplied BOOM v4 Chisel, while preserving the existing LSQ + MSHR + execution-graph end-to-end bug witness.

## Result

`examples/boom/model/l1/module.yaml` is now the current formal L1 model. The model is finite-instantiated from Trace roles: a bounded Trace only materializes the request/outcome classes it can exercise instead of eagerly generating hit + miss + every nack + every probe/writeback branch for every operation.

### Covered L1 behavior

- LSU request acceptance and meta/data read launch;
- s0/s1/s2 request pipeline;
- load hit and response;
- load miss and MSHR request;
- nack causes (probe conflict, victim/secondary conflict, MSHR unavailable, data-bank conflict, WB-set conflict);
- store hit, initial miss acknowledgement, cache data write;
- MSHR replay injection, replayed-load response and replayed-store data write;
- MSHR refill/meta-write acceptance and long-latency response boundary;
- ProbeUnit clean, miss, and dirty-line paths;
- WritebackUnit fill → LSU release → TileLink release → done lifecycle;
- L1 Store→Load bypass timing;
- minimal LR/SC reservation state and successful SC result;
- local contribution to DCache ordered state.

## Bugs found in the model during construction

### Store replay acknowledgement

An early draft emitted a second `DCache.StoreAck` from a replayed store. The source only sends the architectural store acknowledgement on the initial hit/MSHR-accept path; the replay later performs the cache write. v0.14 therefore models replayed stores as `MSHRReplayS2 → StoreDataWrite` with no second ack.

### Store→Load bypass pair filtering

The first generic pair rule instantiated every store-hit × load-hit pair and only placed the timing relationship in the consequent. Under exact support this could force a younger SC store to bypass an earlier LR. The temporal relation is now part of the transformation guard: the store write must be available before or at the load S2 event.

### Recovery/retirement timing regression

The formal L1 pipeline increased the end-to-end witness length and exposed an old freedom in the fixed reference: LD-LD `LoadOrderFail` and the corresponding exception could be arbitrarily delayed until after an explicitly requested bad commit. The fixed LD-LD transition now records `LoadOrderFail` in the conflict cycle, the LSU exception abstraction reflects the two register boundaries to `io.core.lxcpt`, and the ROB boundary forbids retirement after the matching memory-order exception.

## Parameterization improvements

- A Trace role may now accept multiple event types, e.g. `[Arch.Load, Arch.Store]`, allowing common MSHR roles without duplicate models.
- A missing path in a `where` filter means “not a match” instead of a schema exception. This supports optional annotations such as `is_lr` / `is_sc`.

## Standalone L1 regressions

Inputs are under `examples/boom/traces/l1/`; completed witnesses are archived under `tests/regressions/boom/v0_14/l1/`.

1. `load_hit`
2. `load_nack_data_bank`
3. `load_miss_mshr`
4. `probe_clean`
5. `probe_dirty`
6. `probe_miss`
7. `store_hit`
8. `store_load_bypass`
9. `mshr_replay_store`
10. `mshr_eviction_writeback`
11. `lr_sc_success`

All are feasible with the formal L1 model.

## End-to-end BOOM result

The buggy composition still admits:

```text
LoadAlpha = 1
LoadBeta  = 0
```

through the formal LSQ, formal L1, and formal MSHR models. The architectural graph remains:

```text
LoadBeta -fr→ StoreGamma -rfe→ LoadAlpha -ppo→ LoadBeta
```

and is `FORBIDDEN` by the current RVWMO Load–Load fragment.

The fixed reference produces `LoadOrderFail → MemoryOrderingException → SquashLoad`; the younger bad load is absent from the architectural graph and the result is `ALLOWED`. Forcing the same bad younger retirement is `INFEASIBLE`.

Hierarchy abstraction was rechecked on the v0.14 concrete witness and preserves the `FORBIDDEN` result.

## Validation

The release regression is split into deterministic groups to avoid shell timeout artifacts:

- infrastructure/parameterization/non-BOOM group: 102 passed;
- BOOM LSQ: 11 passed;
- BOOM MSHR: 9 passed;
- BOOM L1: 14 passed.

Total: **136 passing tests**.
