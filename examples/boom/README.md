# BOOM current model

This directory contains the **current** BOOM model consumed by µMCM Foundation.  It is not a chronological archive.

- `model/` contains reusable module semantics.
- `composition/` connects those modules.
- `traces/` contains input/query traces only.
- `axioms/` contains architectural graph rules/checks.
- `abstraction/` contains hierarchy summaries.

Generated/completed traces and historical stage artifacts belong in `tests/regressions/boom/`, not here.

`model/lsu/module.yaml` reflects the supplied BOOM v4 LSU source (SHA-256 `81d738e8c8967f0fad72a2406a623a384fac229e10c20ffa37a6907aece9b7b5`).


## MSHR model (v0.13)

`model/mshr/module.yaml` is the current reusable MSHR/RPQ/SDQ/IOMSHR model. `composition/mshr.yaml` is a standalone bounded composition for MSHR tests. Input/query traces are under `traces/mshr/`; generated outputs remain under `tests/regressions/boom/v0_13/`.

The supplied MSHR source SHA-256 is `7e70d1a095f9543ecb20c2983e925205ef473376fe7e6112173d7e8079069fcf`. The supplied L1 source SHA-256 is `82d5562b6d6220be5714716c6b935a001ed6fc54747b4fc925603cabbde9aac4`; full L1 modeling is the next iteration.
