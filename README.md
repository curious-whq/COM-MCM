# µMCM Foundation v0.15.0

v0.15 formalizes module hierarchy and private/public abstraction.  The concrete child µMCM remains stateful and executable; hierarchy controls what is visible across module boundaries.

```text
partial microarchitectural Trace
        ↓
Event + State + Transformation semantics
        ↓
bounded concrete feasibility
        ↓
ModuleSpec
  private state / private events / private transformations
  public ports only
        ↓
strict composition
        ↓
interface-only projection (hide private events)
        ↓
architectural Execution Graph + axioms
```

The project remains independent of FM-Agent. Later model-generation agents should target these deterministic IRs and interfaces rather than inventing unrestricted axioms.

## v0.15 hierarchy rule

- Every module state variable is private.
- `internal_events` are private implementation vocabulary.
- `ports` are the only public cross-module event surface.
- A strict composition cannot constrain a child-private slot.
- `umcm project-interface` hides private events but does not invent bug-specific summary events.

The canonical BOOM interface inventory is `examples/boom/hierarchy/interfaces.yaml`. See `HIERARCHY_V0.15.md` and `BOOM_MODEL_COVERAGE.md`.

## BOOM layout

```text
examples/boom/
├── events.yaml
├── model/{lsu,l1,mshr,coherence,rob}/
├── composition/
├── hierarchy/interfaces.yaml
├── abstraction/hierarchy.yaml   # legacy witness-summary regression
├── axioms/
└── traces/
```

Historical/generated traces belong under `tests/regressions/boom/`; `examples/boom/` is the current model, not a stage archive.

## Quick hierarchy check

```bash
PYTHONPATH=src python -m umcm interfaces \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --trace examples/boom/traces/load_load_bug.yaml
```

Complete the known witness and project it to module interfaces:

```bash
PYTHONPATH=src python -m umcm complete \
  --schema examples/boom/events.yaml \
  --trace examples/boom/traces/load_load_bug.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --backend z3 --output completed_buggy.yaml

PYTHONPATH=src python -m umcm project-interface \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --trace completed_buggy.yaml \
  --output interface_buggy.yaml
```

For the current regression, 45 concrete events project to 19 interface events while preserving the forbidden `fr → rfe → ppo` architecture cycle. The fixed reference projects from 46 to 20 events and remains allowed.

## Validation

A one-shot `pytest` can exceed the execution wrapper timeout, so CI/local validation may run the suite in groups. v0.15 has 126 passing tests across the base IR, completion/state, LSQ, MSHR, composition/parameterization, and hierarchy groups.

## v0.12 LSQ model

The current LSU/LSQ model is parameterized over all loads, stores and fences in the bounded Trace.  It models the memory-order-relevant behavior of:

- LDQ allocation and persistent state;
- load TLB miss, retry, hit, issue, nack, wakeup and response;
- release/observed state and generic pairwise LD-LD search;
- the BOOM buggy LD-LD assertion-only path and a corrected reference recovery path;
- STQ allocation, address/data arrival and store TLB miss/retry;
- Store→Load forwarding and older-AMO blocking;
- generic ST-LD ordering violations and `order_fail` provenance;
- `order_fail → MINI_EXCEPTION_MEM_ORDERING`;
- load/store branch/exception recovery;
- store commit, drain, DCache acknowledgement and clear;
- fence wait/release on `DCache.Ordered`.

The model deliberately abstracts queue pointer implementation, repeated arbitration/backpressure cycles, detailed TLB fault causes, HellaCache/debug/performance paths, and optional load-to-store register-data forwarding.  These omissions do not mean the corresponding RTL does not exist; they are outside the current memory-order semantic surface.


## v0.13 MSHR/RPQ model

The current `model/mshr/module.yaml` is parameterized over bounded MSHR requests and persistent MSHR identities. It models primary/secondary miss admission, RPQ kill/drain, Acquire/Grant, line-buffer refill, direct load response, replay, response queueing, SDQ lifetime, dirty-victim writeback/finish, fence/probe readiness and IOMSHR loads.

Standalone MSHR regression inputs live under `examples/boom/traces/mshr/`; generated witnesses live under `tests/regressions/boom/v0_13/mshr/`.

The full BOOM Load–Load bug still produces the forbidden `fr → rfe → ppo` cycle using this formal MSHR model.

## Quick validation

```bash
PYTHONPATH=src pytest -q
```

Expected when the suite is run in groups:

```text
126 passed
```

### LSQ-only examples

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom/events.yaml \
  --trace examples/boom/traces/store_load_forward.yaml \
  --composition examples/boom/composition/lsq.yaml \
  --backend z3
```

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom/events.yaml \
  --trace examples/boom/traces/store_tlb_retry.yaml \
  --composition examples/boom/composition/lsq.yaml \
  --backend z3
```

### Full BOOM Load–Load witness

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom/events.yaml \
  --trace examples/boom/traces/load_load_bug.yaml \
  --composition examples/boom/composition/memory_buggy.yaml \
  --backend z3 \
  --output completed_buggy.yaml

PYTHONPATH=src python3 -m umcm check \
  --schema examples/boom/events.yaml \
  --trace completed_buggy.yaml \
  --axioms examples/boom/axioms/rvwmo_load_load_fragment.yaml
```

The buggy model admits the architectural result `older=1, younger=0` and produces the cycle:

```text
LoadBeta -fr→ StoreGamma -rfe→ LoadAlpha -ppo→ LoadBeta
```

The fixed-reference composition instead generates:

```text
LDLDConflict → LoadOrderFail → MemoryOrderingException → SquashLoad
```

and rejects the same bad younger-load retirement.

See `ITERATION_15_REPORT.md`, `HIERARCHY_V0.15.md`, and `BOOM_MODEL_COVERAGE.md` for the current hierarchy and coverage boundary.
