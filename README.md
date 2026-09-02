# µMCM Foundation v0.14.0

v0.14 adds a reusable BOOM L1/DCache/ProbeUnit/WritebackUnit model on top of the formal LSQ (v0.12) and MSHR/RPQ (v0.13) models, all grounded in the supplied Chisel.

The project remains independent of FM-Agent.  Its job is to provide the deterministic infrastructure that later model-generation agents must target:

```text
partial microarchitectural Trace
        ↓
Event + State + Transformation semantics
        ↓
bounded feasibility / hidden-event completion
        ↓
module composition + hierarchy abstraction
        ↓
architectural Execution Graph
        ↓
rf / co / fr / po / ppo + axioms
        ↓
ALLOWED / FORBIDDEN
```

## BOOM layout

```text
examples/boom/
├── events.yaml
├── model/
│   ├── lsu/
│   │   ├── module.yaml
│   │   └── fixed_reference.yaml
│   ├── l1/module.yaml
│   ├── mshr/module.yaml
│   ├── coherence/module.yaml
│   └── rob/{buggy,fixed_reference}.yaml
├── composition/
│   ├── lsq.yaml
│   ├── lsq_fixed_reference.yaml
│   ├── memory_buggy.yaml
│   └── memory_fixed_reference.yaml
├── axioms/rvwmo_load_load_fragment.yaml
├── abstraction/hierarchy.yaml
└── traces/
```

Historical stage-by-stage examples from v0.11 and earlier live under:

```text
tests/regressions/boom/legacy_v0_11/
```

No new `stageXX` files should be added to `examples/boom/`.

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


## v0.14 L1 / DCache model

The current `model/l1/module.yaml` models the memory-order-relevant L1 pipeline and boundaries: request acceptance, s0/s1/s2, hit/miss/nack outcomes, MSHR replay/refill integration, ProbeUnit clean/miss/dirty paths, WritebackUnit release flow, store writes/bypass and minimal LR/SC reservation state.

The L1 model is **Trace-demand finite-instantiated**: the bounded Trace selects the request/outcome classes that can occur, so the solver does not eagerly instantiate every hit/miss/nack/probe branch for every operation. The transformations themselves remain reusable and parameterized.

Standalone inputs are under `examples/boom/traces/l1/`; generated witnesses are archived under `tests/regressions/boom/v0_14/l1/`. See `L1_V0.14_SOURCE_MAP.md` and `ITERATION_14_REPORT.md`.

## Quick validation

```bash
PYTHONPATH=src pytest -q
```

Expected total across the release regression groups: **136 passed**.

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

See `ITERATION_14_REPORT.md`, `L1_V0.14_SOURCE_MAP.md`, `MSHR_V0.13_SOURCE_MAP.md`, and `LSQ_V0.12_SOURCE_MAP.md` for implementation details and source grounding.
