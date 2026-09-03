# Iteration 16 — bounded architectural RVWMO

## Result

v0.16 now has a reusable architectural RVWMO checker. It is no longer limited to the hard-coded BOOM Load--Load PPO fragment, and it does not attempt the postponed large litmus-corpus experiment.

## Implemented

- Built-in `rvwmo` graph-model mode with legacy-model compatibility.
- Architectural AMO nodes with distinct read/write values.
- LR and successful SC representation plus explicit pairing.
- Generic projection of operation metadata and dependency/synchronization relation hints.
- Individually visible PPO rules 1--13 and their union.
- `rfi/rfe`, `fri/fre`, coherence validation, initial-write ordering, deterministic total GMO witnesses, and finite progress.
- Separate outcomes for global-order existence, load value, AMO atomicity and LR/SC atomicity.
- A standalone architectural event catalog, model and forbidden example under `examples/rvwmo/`.

## Validation

- 19 new focused RVWMO tests pass, including the v0.15 BOOM buggy/fixed regression pair under the new checker.
- All 126 pre-v0.16 tests pass unchanged.
- Total: **145 passed**.
- The CLI example independently returns the expected `R1 -fr-> W -rfe-> R0 -ppo-> R1` violation.

## Honest non-goals

The checker currently targets aligned scalar regular-main-memory operations. It rejects partially overlapping mixed-size operations and does not model mismatched LR/SC footprints, I/O, page-table walks, vector operations or CMO behavior. Syntactic dependency discovery from decoded instruction streams is an ISA-front-end responsibility; the checker consumes explicit dependency facts.

No exhaustive litmus corpus was run. That remains intentionally outside the current milestone.

## Next boundary

v0.17 can now consume this architectural checker while adding BOOM core-side ROB/TLB/AMO/LR-SC/Fence/MMIO/branch-recovery behavior. It should not weaken module encapsulation or move ISA dependency inference into the microarchitectural checker.
