# BOOM current model

This directory contains the **current** BOOM model consumed by µMCM Foundation.  It is not a chronological archive.

- `model/` contains reusable module semantics.
- `composition/` connects those modules.
- `traces/` contains input/query traces only.
- `axioms/` contains architectural graph rules/checks.
- `abstraction/` contains hierarchy summaries.

Generated/completed traces and historical stage artifacts belong in `tests/regressions/boom/`, not here.

`model/lsu/module.yaml` reflects the supplied BOOM v4 LSU source (SHA-256 `81d738e8c8967f0fad72a2406a623a384fac229e10c20ffa37a6907aece9b7b5`).
