# BOOM µMCM path coverage at v0.19

v0.19 adds bounded *transition reachability* queries. It does not ask whether a known litmus result is allowed. It asks whether a declared memory-relevant event, operational rule, state transition, or public interface action has at least one model-consistent witness.

## Command

```bash
umcm cover boom \
  --backend z3 \
  --output examples/boom/coverage/BOOM_PATH_COVERAGE.yaml \
  --witness-dir examples/boom/coverage/witnesses
```

The built-in `boom` profile resolves `examples/boom/coverage/v019.yaml` when run from the project root. `--suite` accepts another coverage suite.

## Query semantics

A goal contains one or more conjunctive probes:

```yaml
- id: core_lr_probe_sc_fail
  model: core
  inputs: [lr-probe-sc-fail]
  require:
  - {transformation: "lr_sets_reservation_*"}
  - {transformation: "probe_invalidates_reservation_*"}
  - {transformation: "failed_sc_completes_without_write_*"}
```

Supported probes are:

| Probe | Meaning |
|---|---|
| `event` | At least one matching bounded event occurs; optional field predicates may be supplied. |
| `transformation` | At least one fully bound rule activation satisfies input/output occurrence, `when`, `output_when`, `ensure`, and state guards. |
| `state_transition` | A matching state update fires with the requested pre-state and post-state value. |
| `interface` | The event type exported by the named module port occurs. |

The activation inventory is produced while transformations are instantiated. Consequently, transformation coverage is not inferred from an event name and cannot report a rule as covered merely because a same-typed event occurs through another producer.

Z3 minimizes selected completion slots. Across the goal's declared input domain, the report retains the witness with the fewest hidden events, then the fewest total events and shortest maximum cycle.

## Input boundary

Each coverage model declares `input_event_types`. Every source trace is rejected if it contains another event type. This makes the boundary auditable:

- core-side witnesses contain decoded instructions, page-map environment state, and selected public control/cache boundary actions;
- coherence witnesses contain only line initialization, architectural accesses, and optional eviction requests;
- standalone MSHR witnesses enter through its public request ports;
- standalone LSQ nack coverage may enter through the public DCache response boundary.

Private outcomes such as TLB decisions, MSHR internal actions, TileLink grants/probes, and state transitions are solver-selected. v0.19 does not yet unify the four compositions; that adapter and cross-module search remain v0.20 work.

## Automatic goals and structural diagnostics

`auto_goals` expands glob selectors over the instantiated transformation, private-event, or public-interface inventory. The BOOM suite automatically creates required reachability goals for L2 Probe/Grant and L1 Release/L2 ReleaseAck ports.

The report also records, per bounded model:

- all instantiated transformations and state variables;
- public module interfaces;
- private event types and their transformation producers;
- private event types with no transformation producer;
- transformations with no role binding in any configured input.

`no_bounded_transformation_binding` is relative to this suite's finite input domain; it is not a proof of global RTL unreachability. A private event with no producer is a stronger model-structure warning: the event may still be selected as a free bounded slot, but the report does not hide the missing producer.

## v0.19 BOOM result

The checked-in report has 28 goals:

```text
27 covered
 1 uncovered
 0 unreachable
 0 unknown

required: 27 / 27 covered
```

Covered paths include LDQ allocation, LSQ retry/forward/nack-wakeup, primary and secondary MSHRs, dirty writeback, replay, IOMSHR, TLB miss/refill/retry, SFENCE, AMO, both LR/SC outcomes, MMIO, fence, precise exception, branch recovery, cold coherence refill, dirty handoff, B→T upgrade, dirty release, and four generated TileLink interface goals.

The optional `coherence_l1_hit` goal is deliberately retained as uncovered. A new high-level trace consisting of line initialization and two same-hart reads is UNSAT in the v0.18 coherence composition, even though the second read has a bounded `load_hit_h0_*` activation candidate. This is a concrete v0.18 model hole found by coverage, not relabeled as success. It should be repaired before v0.20 relies on repeated same-client cache hits.

The structural inventory also exposes producer gaps in the standalone slices. Examples include LSQ-private `LoadWakeup`, `RetryIssue`, `StoreDataReady`, and `StoreLoadForward`, plus MSHR-private metadata request/response events. Their current witnesses prove guarded transition consistency, while the producer warnings show where later composition/adapters must replace free internal choices.

## Status meanings

| Status | Meaning |
|---|---|
| `covered` | A bounded model-consistent witness was found. |
| `uncovered` | Matching bindings exist, but guards, state, or finite bounds make the compound goal UNSAT. |
| `unreachable` | No matching event slot, producer, state writer, interface, or transformation binding exists in the bounded universe. |
| `unknown` | The selected solver/backend could not decide within its limit. |

The suite succeeds only when every `required: true` goal is covered. Optional red items remain visible in the report and CLI output.
