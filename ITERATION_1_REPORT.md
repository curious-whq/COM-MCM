# Iteration 1 Report

## Delivered

- Typed `Sort` layer with built-ins, bit-vectors, and custom domain sorts.
- Typed expression AST: literal, symbol, event field, unary, binary, n-ary,
  conditional, and uninterpreted/domain call.
- Event schema: `FieldSpec`, `EventType`, `EventCatalog`, visibility, identity fields.
- Dynamic `EventInstance` with concrete or symbolic cycle/field observations.
- Partial `Trace` with boolean constraints and normalized observation enumeration.
- Safe YAML/JSON serialization and round-trip support.
- CLI validation against an event catalog.
- Initial BOOM Load–Load event catalog and architectural partial Trace.

## Verification

```text
pytest: 16 passed
compileall: passed
editable installation with --no-build-isolation: passed
CLI validation before and after installation: passed
```

The ordinary isolated `pip install -e .` path was not used in the build
container because it has no network access to download build dependencies.
The installed setuptools version is sufficient, so `--no-build-isolation`
verifies the package itself without network access.

## Deliberately deferred

- State variables and state histories.
- Transformation semantics.
- Candidate hidden-event generation.
- Z3 lowering and Trace completion.
- Execution-graph construction.
- RVWMO relation/axiom checking.
- Hierarchical event hiding/refinement.

## Next implementation boundary

Iteration 2 should introduce a small operational core without changing the
current serialized Event/Trace format:

1. `StateVar` and `InitialState`.
2. `Transformation(name, inputs, when, updates, emits, invariants)`.
3. Finite event slots and bounded cycles.
4. Z3 encoding for concrete/symbolic event fields and cycles.
5. First completion test: infer `LSU.TLBMiss(L0) -> LSU.RetryEnqueue(L0)` from
   a partial BOOM trace.
