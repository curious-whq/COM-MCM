# Iteration 13 — formal BOOM MSHR/RPQ model

## Goal

Replace the previous single-witness MSHR path with a reusable, trace-parameterized model grounded in the supplied `BoomMSHR/BoomMSHRFile/BoomIOMSHR` Chisel.

## Infrastructure changes

- `TraceRoleSpec.distinct_by`: several requests may share one persistent MSHR instance.
- `state_mode: guard` may anchor state predicates at an output event. This is needed for paths whose legality depends on state at the eventual response/replay cycle; the guard does not create a liveness obligation.
- Exact-output rules are scoped by `op_id`, `mshr_id`, admission class, or kill reason so multiple dynamic requests do not incorrectly constrain each other.

## Modeled behavior

- primary miss admission;
- secondary miss merge;
- RPQ insert, branch/exception kill, direct drain and replay drain;
- AcquireBlock and data/no-data grants;
- line-buffer refill and direct load response;
- MSHRFile response queue;
- SDQ allocation/free for stores;
- metadata read, dirty victim clear/writeback, refill commit, metadata write and mem finish;
- fence/probe readiness observations;
- IOMSHR load path.

## Regression cases

`examples/boom/traces/mshr/` contains current input/query traces for:

1. `primary_load_refill.yaml`
2. `secondary_merge.yaml`
3. `branch_kill_secondary.yaml`
4. `store_no_data_replay.yaml`
5. `dirty_writeback_finish.yaml`
6. `probe_and_fence_blocked.yaml`
7. `iomshr_load.yaml`

Completed witnesses are stored under `tests/regressions/boom/v0_13/mshr/`.

The full BOOM Load–Load bug still completes through the formal MSHR model and remains RVWMO-forbidden. The fixed reference recovery remains allowed, and forcing the bad younger-load commit remains infeasible.

## Deliberate boundaries

- refill beat count is abstracted;
- MSHR allocation choice is an observed bounded identity, not yet synthesized from round-robin state;
- prefetch-specific behavior is excluded;
- exact L1 metadata/data-array/arbitration semantics are deferred to v0.14, for which the exact L1 source has already been supplied.

## Validation

- 120 pytest cases pass (split across deterministic infrastructure and BOOM semantic regressions).
- `python -m compileall src` passes.
- v0.13 hierarchy abstraction preserves the full buggy witness as `FORBIDDEN` after replacing the legacy MSHR summary vocabulary.
