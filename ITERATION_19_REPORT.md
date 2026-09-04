# Iteration 19 report

## Delivered

- Added `umcm cover` and the `umcm.coverage` suite/goal/report IR.
- Added exact transformation-activation evidence to bounded problem instantiation and completed-trace metadata.
- Added conjunctive event, transformation, state-transition, and public-interface reachability probes.
- Added automatic goal expansion over instantiated public interfaces, private events, and transformations.
- Added structural producer/binding diagnostics and a strict per-model input-event allowlist.
- Added query reuse: every model/input bounded problem is instantiated once and copied with only mutable coverage constraints.
- Made `z3-solver` a declared runtime dependency and taught the ctypes backend to find the wheel-bundled shared library.
- Added the BOOM v0.19 suite, high-level coverage inputs, 27 witness files, and a checked-in machine-readable report.

## Acceptance result

```text
COVERAGE boom-path-coverage-v0.19: 27/28 goal(s) covered
required 27/27
```

All required LSQ, MSHR, v0.17 core-side, v0.18 coherence, and generated TileLink-interface goals have bounded witnesses. The source input allowlist prevents private path outcomes from being supplied as coverage answers.

## New model finding

`coherence_l1_hit` remains optional and uncovered. The v0.18 coherence model rejects a two-read, same-hart trace that should refill and then hit. The coverage engine finds a bounded `load_hit_h0_*` binding but the compound model is SMT-UNSAT. This remains visible in `BOOM_PATH_COVERAGE.yaml`; it is not counted as a required pass.

The structural report also lists private slot types without transformation producers and transformations without a role binding in the configured finite inputs. This distinguishes “a guard is consistent if the event is chosen” from “the model contains a producer that can reach the event.”

## Scope boundary

The coverage suite searches the existing standalone LSQ, MSHR, core-side, and coherence compositions. It does not claim an end-to-end adapter between those slices, exhaustive RTL path coverage, or RVWMO violation search. Hierarchical architectural-skeleton search remains v0.20.

## Regression result

```text
173 passed in 336.10s
```

This includes all 168 v0.18 tests plus five focused v0.19 tests for activation evidence, compound coverage goals, automatic interface goals, strict input contracts, unreachable diagnostics, suite round-tripping, and CLI witness/report output.
