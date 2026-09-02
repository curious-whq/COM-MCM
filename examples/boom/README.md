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

The supplied MSHR source SHA-256 is `7e70d1a095f9543ecb20c2983e925205ef473376fe7e6112173d7e8079069fcf`.

## L1 model (v0.14)

`model/l1/module.yaml` is the current reusable L1/DCache/ProbeUnit/WritebackUnit model. `composition/l1.yaml` provides a standalone bounded L1 composition. Input traces are under `traces/l1/`; generated witnesses are archived under `tests/regressions/boom/v0_14/l1/`.

The model covers request acceptance, s0/s1/s2 pipeline, hit/miss/nack, MSHR replay/refill boundaries, ProbeUnit, WritebackUnit, store write/bypass and minimal LR/SC state. It is demand-instantiated from the bounded Trace to avoid eagerly materializing every alternative L1 path.

The supplied L1 source SHA-256 is `82d5562b6d6220be5714716c6b935a001ed6fc54747b4fc925603cabbde9aac4`.
