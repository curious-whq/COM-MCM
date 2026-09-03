# v0.15 Hierarchy and Encapsulation

v0.15 makes hierarchy a structural property of the µMCM rather than a witness-specific post-processing convention.

## Rule 1: ports are the public surface

A `ModuleSpec` now distinguishes:

- `ports`: event types visible across a module boundary;
- `internal_events`: private event vocabulary used by the module's own transformations;
- `state_variables`: always private to the owning module;
- `transformations`: always private implementation semantics.

A child module may use its internal events and state freely. A parent/composition may connect only declared ports. Under `metadata.encapsulation: strict`, a top-level composition constraint is rejected if it reaches through a child boundary to a private slot.

## Rule 2: hiding does not delete the concrete model

`umcm project-interface` takes an already feasible concrete trace and removes child-private implementation events. It does not remove the child's state machine from the feasibility model, and it does not invent a bug-specific summary event.

Thus the two views coexist:

```text
Concrete child µMCM                         Interface trace
-------------------                        ---------------
private state                               public port event
private transition        -- hide -->       public port event
private event                                ...
public port event
```

The concrete trace remains the witness used to justify feasibility. The interface trace is the boundary-visible projection used for hierarchical composition/explanation.

## Rule 3: no bug-specific hierarchy vocabulary

The canonical v0.15 hierarchy is `examples/boom/hierarchy/interfaces.yaml`. It contains no `l0_*`, `l1_*`, `buggy_*`, `LoadLoadResolution`, or other witness-specific summaries.

The older `examples/boom/abstraction/hierarchy.yaml` is retained only as a regression for the generic summary/refinement engine introduced in v0.8. It is not the canonical BOOM hierarchy.

## BOOM public/private boundary in v0.15

### LSU/LSQ

Public examples: DCache request/accept/response/nack/release, ROB exception/squash/commit, store drain, fence release.

Private examples: LDQ/STQ state, TLB miss/retry bookkeeping, `LoadExecuted`, `LoadObserved`, LD-LD/ST-LD searches, `order_fail`, forwarding selection.

### L1/DCache

Public examples: accepted request, response/nack, probe receive/release, MSHR request/response.

Private examples: hit/miss outcome events and local probe state.

### MSHR

Public examples: DCache miss request, Acquire/Grant-facing evidence, replay/response, refill/meta/writeback boundary events, probe/fence blocking.

Private examples: MSHR FSM state, RPQ/SDQ/line-buffer bookkeeping, primary/secondary admission, internal drain/finish events.

### Coherence and ROB

These remain boundary abstractions in v0.15. In particular, `coherence` is not yet a real L2 model; that is a later stage.

## Commands

Inspect the public/private contract:

```bash
PYTHONPATH=src python -m umcm interfaces \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --trace examples/boom/traces/load_load_bug.yaml
```

Project a completed trace to the interface surface:

```bash
PYTHONPATH=src python -m umcm project-interface \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --trace completed_buggy.yaml \
  --output interface_buggy.yaml
```

For the current BOOM witness, the concrete buggy trace has 45 events and the interface projection 19 events; 26 private events are hidden. The RVWMO-fragment verdict remains forbidden. The fixed trace projects from 46 to 20 events and remains allowed.
