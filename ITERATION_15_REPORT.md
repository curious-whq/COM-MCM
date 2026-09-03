# Iteration 15 — Structural hierarchy / private-public abstraction

## Goal

Turn module hierarchy from a naming convention into an enforceable part of the IR. The canonical abstraction in v0.15 hides implementation-private state/events at module boundaries; it does not replace a real child state machine with a bug-specific shortcut.

## IR changes

- `ModuleSpec.internal_events` declares private event vocabulary independently of ports.
- Ports now mean only cross-module interface events.
- Composition slots are annotated with owning module and `module_visibility`.
- `CompositionResult` emits hierarchy inventory metadata.
- `metadata.encapsulation: strict` rejects top-level constraints that reference a child-private slot.
- Trace-role matching accepts multiple event types and treats a missing `where` path as a non-match, which is required for heterogeneous memory-operation roles.

## Hierarchy API/CLI

- `build_interface_contracts()` derives public ports plus private state/event/transition inventories.
- `project_interface_trace()` performs pure hiding: no summary event is synthesized.
- `umcm interfaces` prints/writes the module contract.
- `umcm project-interface` creates an interface-only trace plus a projection certificate.

## BOOM cleanup

The LSU and L1 no longer expose internal events merely so another module can mention them. In particular `LSU.LoadExecuted`, `LSU.TLBMiss`, `LSU.LDLDConflict`, `DCache.LoadHit`, and `DCache.LoadMiss` are private vocabulary. The old artificial `LSU.LoadExecuted -> L1` / `L1.LoadHit|Miss -> LSU` connections were removed. Coherence now drives `DCache.ProbeReceive`, matching the physical direction.

## Preservation result

Buggy composition:

- concrete trace: 45 events;
- interface trace: 19 events;
- hidden: 26 private events;
- execution-graph result: still **FORBIDDEN**.

Fixed reference:

- concrete trace: 46 events;
- interface trace: 20 events;
- hidden: 26 private events;
- execution-graph result: still **ALLOWED**.

The interface projection therefore demonstrates the intended notion of abstraction for the current witness: internal implementation detail is hidden while the externally relevant architectural outcome is preserved.

## Important non-goals

- v0.15 is not yet hierarchical *search*. Feasibility is still checked on the concrete composed µMCM before projection.
- The old v0.8 witness-summary abstraction remains as a regression mechanism but is no longer the canonical BOOM hierarchy.
- L2 is still not modeled; `coherence` is an abstract environment.
- This iteration does not claim a universal refinement proof from child implementation to its interface language.

## Regression

The test suite is run in groups because a single all-tests invocation can exceed the execution wrapper time limit. The groups cover base IR/graph, completion/state, LSQ, MSHR, parameterization/composition, and the new hierarchy interface tests.
