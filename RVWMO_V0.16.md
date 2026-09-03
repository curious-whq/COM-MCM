# RVWMO v0.16 architecture checker

Normative reference: [RISC-V Unprivileged ISA, RVWMO Memory Consistency Model Version 2.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/rvwmo.html).

## Goal and semantic shape

v0.16 replaces the witness-specific Load--Load fragment as the primary architectural checker with a reusable built-in RVWMO model:

```text
committed architectural operations
        +
ISA-front-end facts (dependencies, fences, LR/SC pairs)
        ↓
rf/co candidate
        ↓
po, rfi/rfe, fri/fre, PPO rules 1--13
        ↓
GMO witness + load-value + atomicity
        ↓
ALLOWED / FORBIDDEN
```

The old YAML relation/axiom engine remains available for regressions and custom fragments. A graph model opts into the new checker with:

```yaml
builtin_model: rvwmo
```

`examples/boom/axioms/rvwmo.yaml` is the primary projection for the current BOOM model. The older `rvwmo_load_load_fragment.yaml` is retained only to keep historical regressions reproducible.

## PPO rule coverage

| RVWMO rule | v0.16 construction | Required input |
| --- | --- | --- |
| 1. older overlapping access before a store | `ppo_rule1` | operation kind and footprint |
| 2. same-byte Load--Load, no intervening store, different source writes | `ppo_rule2` | `po`, `rf`, footprint |
| 3. AMO/SC write read by a later load | `ppo_rule3` | atomic kind and `rf` |
| 4. FENCE ordering | `ppo_rule4` | `fence` relation hint |
| 5. acquire source | `ppo_rule5` | acquire metadata |
| 6. release target | `ppo_rule6` | release metadata |
| 7. two RCsc-annotated operations | `ppo_rule7` | RCsc metadata |
| 8. paired operations | `ppo_rule8` | `pair` relation hint |
| 9. syntactic address dependency | `ppo_rule9` | `addr` relation hint |
| 10. syntactic data dependency into a store | `ppo_rule10` | `data` relation hint |
| 11. syntactic control dependency into a store | `ppo_rule11` | `ctrl` relation hint |
| 12. dependency through a store read by a later load | `ppo_rule12` | `addr`/`data`, `po`, `rf` |
| 13. address dependency through an intermediate instruction into a store | `ppo_rule13` | represented intermediate operation or direct `pipeline` hint |

`ppo` is exactly the union of these thirteen inspectable relations. All input relation edges must also be in `po`; malformed front-end facts are rejected.

## Architectural operation contract

`MemoryOperation` supports:

- `init_write`, `read`, and `write` as before;
- `amo`, which is simultaneously a read and a write and therefore carries `value` (read result) plus `write_value`;
- `atomic_kind: lr` on a read and `atomic_kind: sc` on a successful SC write;
- `acquire`, `release`, `rcsc`, `ordering`, `size`, `byte_mask`, `byte_addresses`, and `memory_region` metadata.

An unsuccessful SC produces no memory operation. A successful LR/SC pair is connected with the `pair` relation.

The trace projection can populate metadata with `projection.metadata_fields` and arbitrary architectural relations with `projection.relation_hints`. This is the boundary between an ISA-aware decoder and the memory-model checker: register-level dependency tracking belongs before this boundary.

## Axioms and validation

For each finite `rf/co` candidate, v0.16 performs the following checks:

1. **Well-formed `rf`:** every read has exactly one same-location, same-value source write.
2. **Well-formed `co`:** writes to a location have one acyclic total order, with the initial write first.
3. **Global memory order:** `ppo ∪ rfe ∪ co ∪ fr` must be acyclic. A deterministic topological extension is emitted as the total `gmo` relation and `metadata.gmo_order`.
4. **Load value:** the `rf` source must be the latest in GMO among same-location writes that precede the read in GMO or program order.
5. **AMO atomicity:** an AMO reads from its immediate coherence predecessor.
6. **LR/SC atomicity:** the source observed by LR precedes the successful SC, with no other-hart overlapping store between them in coherence order.
7. **Progress:** every checked execution is finite, so the prohibition on an infinite predecessor chain holds vacuously.

The checker returns ALLOWED if at least one enumerated `rf/co` candidate satisfies every built-in and optional custom axiom.

## Deliberate boundary

This iteration is **complete-ish for bounded, aligned scalar, regular-main-memory executions**, not a claim of universal ISA conformance.

Explicitly outside v0.16:

- partially overlapping mixed-size accesses and per-byte value assembly;
- LR/SC pairs with mismatched footprints;
- I/O and uncacheable regions, page-table walks, SFENCE.VMA and FENCE.I;
- vector/SIMD memory operations and cache-block-management extensions;
- deriving syntactic dependencies directly from decoded non-memory instructions;
- the unbounded liveness content of the progress axiom;
- large-corpus or exhaustive litmus validation.

Unsupported overlap or memory-region cases are rejected with `GraphError`; they are not silently treated as legal. v0.17 will add BOOM-side AMO/LR-SC/Fence/TLB behavior, while v0.20 will replace the current factorial bounded candidate enumeration with hierarchical search.

## Focused tests

`tests/test_rvwmo_v016.py` covers:

- forbidden Load--Load coherence reversal;
- allowed Store--Load store buffering;
- overlapping Load--Store and Store--Store;
- FENCE, acquire, release and RCsc;
- address, data and control dependencies;
- pipeline dependency rules 12 and 13;
- AMO-to-load ordering and AMO atomicity failure;
- LR/SC pairing and external-store interference;
- malformed load values and mixed-size overlap rejection;
- trace projection of metadata and relation hints.
