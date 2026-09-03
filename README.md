# µMCM Foundation v0.18.0

v0.18 adds a source-grounded, searchable BOOM-L1/SiFive-InclusiveCache coherence µMCM on top of the v0.15 hierarchy, v0.16 RVWMO checker, and v0.17 core-side slice. It models bounded directory state, owner/sharer permissions, TileLink A/B/C/D/E flows, dirty data handoff, and ghost coherence versions without asking the input trace to choose hit/miss or protocol outcomes.

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
        ↓
built-in RVWMO PPO / GMO / load-value / atomicity checks
```

The project remains independent of FM-Agent. Later model-generation agents should target these deterministic IRs and interfaces rather than inventing unrestricted axioms.

## v0.18 L2 / coherence composition

`examples/boom/composition/coherence_v018.yaml` connects two modules through seven public TileLink ports:

- `boom_l1_coherence_client`: BOOM v4 N/B/T permission, dirty data, Acquire, ProbeAck/Data, GrantAck, and Release/Data behavior;
- `sifive_inclusive_l2`: the matching Chipyard SiFive InclusiveCache directory/MSHR abstraction with INVALID/BRANCH/TRUNK/TIP state, owner/sharers, inner A/B/C/D/E, and a private last-level backing-memory refill.

BOOM's pinned `CHIPYARD.hash` resolves to Chipyard `4180463d52bc0a6b4c004530601ccdabebf0ab7d`, whose BOOM `AbstractConfig` selects `WithInclusiveCache`; the cache source is pinned to `e3a3000cc1fd4cdf3a4e638e4d081b8aae94ebf0`. See `BOOM_L2_SOURCE_MAP.md`.

Run the dirty-owner handoff witness:

```bash
PYTHONPATH=src python3 -m umcm complete \
  --backend z3 \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/coherence_v018.yaml \
  --trace examples/boom/traces/coherence/dirty_owner_handoff.yaml
```

The input contains only line initialization and two high-level accesses. Completion derives the cold store refill, later Probe/ProbeAckData, L2 version publication, and the second hart's GrantData/load result.

## v0.17 BOOM core-side slice

`examples/boom/composition/core_side_v017.yaml` composes nine modules using public events only:

- `boom_v4_lsu_translation`: LSU-side translation issue, miss retry queue, translated address, and fault delivery;
- `boom_v4_nbdtlb`: source-pinned finite entry state, hit/miss, walker FSM, refill, miss-ready, and SFENCE invalidation;
- `bounded_ptw_environment`: external page-table response abstraction, explicitly not a BOOM/Rocket Chip PTW implementation;
- `atomic_core`: AMO read/write serialization and per-hart-line LR/SC reservation state;
- `reservation_bridge`: `DCache.ProbeRelease` to reservation invalidation;
- `mmio_core`: one-outstanding IOMSHR load/store paths;
- `fence_core`: waits for the public `DCache.Ordered` observation;
- `rob_core`: allocation, completion, in-order commit, precise exception, squash, and branch kill;
- `retire_core`: architectural Load/Store/AMO/LR/SC and commit projection.

The TLB input contract never contains `TLB.Miss`, `TLB.Refill`, or `TLB.Retry`. The trace supplies a decoded `Core.MemoryInstruction` plus finite `Core.PageMap` configuration; private NBDTLB state determines the hit/miss path and LSU owns retry. The source map is in `BOOM_V4_TLB_SOURCE_MAP.md`.

Run the end-to-end miss/retry/MMIO/commit example:

```bash
PYTHONPATH=src python3 -m umcm complete \
  --backend z3 \
  --schema examples/boom/events.yaml \
  --composition examples/boom/composition/core_side_v017.yaml \
  --trace examples/boom/traces/core/tlb_retry_mmio_load.yaml
```

The existing detailed LSQ/L1/MSHR compositions remain the owner of ordinary cacheable load/store execution. v0.18 adds its coherence model as a separate strict composition; the adapter that unifies the two event vocabularies is deliberately deferred.

## v0.15 hierarchy rule

- Every module state variable is private.
- `internal_events` are private implementation vocabulary.
- `ports` are the only public cross-module event surface.
- A strict composition cannot constrain a child-private slot.
- `umcm project-interface` hides private events but does not invent bug-specific summary events.

The canonical BOOM interface inventory is `examples/boom/hierarchy/interfaces.yaml`. See `HIERARCHY_V0.15.md` and `BOOM_MODEL_COVERAGE.md`.

## v0.16 architectural RVWMO checker

The built-in `rvwmo` model constructs `po`, `rf/rfi/rfe`, `co`, `fr/fri/fre`, all thirteen RVWMO PPO rule relations, and one total `gmo` witness when the ordering constraints are acyclic. It checks:

- global-memory-order existence consistent with `ppo ∪ rfe ∪ co ∪ fr`;
- load-value legality against program order and the chosen GMO;
- AMO read-modify-write atomicity;
- successful aligned same-location LR/SC atomicity;
- finite-execution progress (vacuous for every bounded candidate).

Fence order, LR/SC pairing, address/data/control dependencies, and dependencies through non-memory instructions are explicit architectural input facts. This keeps the checker independent from an ISA decoder while still implementing PPO rules 4 and 8--13.

Run the minimal forbidden example:

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/rvwmo/events.yaml \
  --trace examples/rvwmo/load_load_forbidden.yaml \
  --axioms examples/rvwmo/model.yaml
```

See `RVWMO_V0.16.md` for the exact rule mapping and honest scope boundary.

## BOOM layout

```text
examples/boom/
├── events.yaml
├── model/{lsu,l1,mshr,coherence,rob,core}/
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

v0.18 has 168 passing tests: the v0.17 suite plus nine focused coherence tests and one Z3 atomic-state encoding regression.

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

Expected:

```text
168 passed
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
  --axioms examples/boom/axioms/rvwmo.yaml
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

See `ITERATION_18_REPORT.md`, `COHERENCE_V0.18.md`, `BOOM_L2_SOURCE_MAP.md`, `CORE_SIDE_V0.17.md`, `RVWMO_V0.16.md`, `HIERARCHY_V0.15.md`, and `BOOM_MODEL_COVERAGE.md` for the current architecture and hierarchy boundaries.
