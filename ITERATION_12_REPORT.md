# Iteration 12 — Formal BOOM LSQ model

## Goal

Turn the v0.11 load-only witness-oriented layout into a stable `examples/boom/` model tree and complete the memory-order-relevant LSQ semantic surface before moving to MSHR/L1.

## Structural change

`examples/boom_load_load/stageXX_*` is no longer the active model layout.  The active model is under `examples/boom/`; old stage artifacts were moved to `tests/regressions/boom/legacy_v0_11/`.

## Infrastructure changes

1. `state_mode: guard` distinguishes a conditional hardware transition from a state assertion.  If a guard is false the transition is disabled; it does not make the whole Trace infeasible.
2. The Z3 backend encodes persistent pre/post state directly, including atomic writes and stutter.  Large LSQ compositions no longer require hundreds of event-only models to be rejected by a separate state checker.
3. `repeat_product` instantiates pairwise LSQ rules and preserves collection position even when two exported role dictionaries are value-equal.
4. `LoadOrderFail` carries `source_op_id`, preventing pairwise exact-support aliasing and preserving whether an older load or store detected the violation.
5. The LSU owns `Core.MemoryOrderingException`; ROB consumes it and produces recovery/squash.

## LSQ semantic coverage

### LDQ

- allocation/reset;
- virtual/physical address state;
- load retry identity;
- DCache issue/executed window;
- nack clears executed and allows wakeup/reissue;
- DCache/MSHR responses set success/value;
- release marks matching load observed;
- generic all-pairs LD-LD search;
- buggy assertion-only path plus fixed-reference `order_fail`;
- branch, exception and squash invalidation;
- commit preconditions and deallocation.

### STQ / store data

- allocation;
- store address and data arrival;
- store TLB miss, shared retry-queue enqueue, retry issue and successful translation;
- Store→Load forwarding;
- generic Store→Load ordering violation and wrong-forward checks;
- older AMO blocks/replays a load;
- store commit / can-execute;
- drain request / DCache acknowledgement / clear;
- branch invalidation;
- exception flush of uncommitted, unsuccessful entries.

### Fence

A committed fence waits until the DCache reports ordered before its queue entry can release.

## BOOM bug regression

The current buggy composition completes a concrete microarchitectural witness in one Z3 solve and still projects to:

```text
InitData --rf--> LoadBeta
StoreGamma --rf--> LoadAlpha
InitData --co--> StoreGamma
LoadBeta --fr--> StoreGamma
LoadAlpha --ppo--> LoadBeta
```

Therefore:

```text
LoadBeta -fr→ StoreGamma -rfe→ LoadAlpha -ppo→ LoadBeta
```

is forbidden by the current RVWMO Load–Load fragment.

The fixed-reference model produces `LoadOrderFail(source_op_id=LoadAlpha)`, then `MemoryOrderingException`, then `SquashLoad(LoadBeta)`.  The same bad `CommitLoad(LoadBeta,0)` query is UNSAT.

## Regression suite

v0.12 adds current-model regressions for:

- nack → wakeup → reexecute;
- Store→Load forwarding;
- Store→Load order failure;
- store TLB miss/retry/drain;
- store exception flush;
- store commit/drain/ack/clear;
- committed-store exception guard;
- fence ordering;
- full buggy/fixed BOOM witness.

Current result: `111 passed`.

## Explicit abstractions

This is a microarchitectural memory model, not a cycle-for-cycle duplicate of the RTL.  Queue pointer arithmetic is represented by dynamic entry identity and same-hart program order; repeated backpressure cycles stutter; detailed TLB fault taxonomy, HellaCache/debug/performance behavior, and optional load-to-store register-data forwarding are outside the current memory-order surface.
