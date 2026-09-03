# BOOM current model

This directory contains the current BOOM memory µMCM. It is not a chronological archive.

- `model/` contains executable module semantics.
- `composition/` connects only declared module ports.
- `hierarchy/interfaces.yaml` is the canonical v0.15 public/private interface inventory.
- `traces/` contains input/query traces.
- `axioms/` contains architectural execution-graph rules.
- `abstraction/hierarchy.yaml` is retained as a legacy witness-summary regression; it is not the canonical hierarchy.

Generated/completed traces and historical stage artifacts belong in `tests/regressions/boom/`. No new `stageXX` files should be added here.

## v0.18 coherence composition

`composition/coherence_v018.yaml` connects the source-pinned BOOM L1 coherence client to the SiFive InclusiveCache selected by the corresponding Chipyard BOOM configuration. Inputs under `traces/coherence/` provide only line initialization plus high-level accesses/evictions; TileLink and directory outcomes are derived from private state.

```bash
PYTHONPATH=src python3 -m umcm complete \
  --backend z3 \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/coherence_v018.yaml \
  --trace examples/boom/traces/coherence/write_upgrade.yaml
```

See `../../COHERENCE_V0.18.md` and `../../BOOM_L2_SOURCE_MAP.md`.

## v0.17 core-side composition

`composition/core_side_v017.yaml` adds the ROB, BOOM v4 NBDTLB/LSU retry slice, bounded PTW environment, AMO/LR-SC, IOMSHR, fence, and branch-recovery slice. Its directed inputs are under `traces/core/`. A trace supplies `Core.MemoryInstruction` and `Core.PageMap`; it does not supply TLB hit/miss events.

Use the Z3 backend for this stateful composition:

```bash
PYTHONPATH=src python3 -m umcm complete \
  --backend z3 \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/core_side_v017.yaml \
  --trace examples/boom/traces/core/lr_probe_sc_fail.yaml
```

## v0.15 hierarchy

The concrete LSU/L1/MSHR models retain internal state and transformations, but those internals do not become cross-module interfaces. `ModuleSpec.internal_events` declares private vocabulary; declared `ports` are the only public surface. The full memory compositions use `metadata.encapsulation: strict`.

Use:

```bash
PYTHONPATH=src python -m umcm interfaces \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --trace examples/boom/traces/load_load_bug.yaml
```

See `../../HIERARCHY_V0.15.md` and `../../BOOM_MODEL_COVERAGE.md` for the boundary and coverage inventory.

## Source grounding

The supplied BOOM v4 LSU, MSHR/MSHRFile, and L1/DCache Chisel remain the source basis for the current models. The NBDTLB slice is pinned to official BOOM commit `58ef2720eae13be26b3008c02b5a74ce29c61c44`; see `../../BOOM_V4_TLB_SOURCE_MAP.md`. The external PTW remains abstract. The v0.18 coherence composition is instead pinned through BOOM's `CHIPYARD.hash` to Chipyard's `WithInclusiveCache` configuration and the corresponding SiFive InclusiveCache source; see `../../BOOM_L2_SOURCE_MAP.md`.
