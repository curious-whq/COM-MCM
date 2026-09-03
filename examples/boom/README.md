# BOOM current model

This directory contains the current BOOM memory µMCM. It is not a chronological archive.

- `model/` contains executable module semantics.
- `composition/` connects only declared module ports.
- `hierarchy/interfaces.yaml` is the canonical v0.15 public/private interface inventory.
- `traces/` contains input/query traces.
- `axioms/` contains architectural execution-graph rules.
- `abstraction/hierarchy.yaml` is retained as a legacy witness-summary regression; it is not the canonical hierarchy.

Generated/completed traces and historical stage artifacts belong in `tests/regressions/boom/`. No new `stageXX` files should be added here.

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

The supplied BOOM v4 LSU, MSHR/MSHRFile, and L1/DCache Chisel remain the source basis for the current models. The coherence module is still an abstract environment, not a real L2/directory model.
