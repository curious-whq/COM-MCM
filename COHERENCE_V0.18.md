# v0.18 source-grounded L2 / coherence µMCM

## Result

`examples/boom/composition/coherence_v018.yaml` is an executable two-module hierarchy:

```text
Coherence.Access / Coherence.Evict
        ↓
BOOM L1 coherence client
        ↕ TileLink A/B/C/D/E
SiFive InclusiveCache L2
        ↓
Coherence.LoadResult / StorePerformed / VersionPublish
```

The input supplies only line initialization and high-level accesses/evictions. It does not supply cache hit/miss, permission, Acquire, Probe, ProbeAck, Grant, GrantAck, Release, ReleaseAck, L2 directory result, or outer refill outcome. Those are completion results derived from private state.

## Private state

For each bounded line and hart, the L1 client owns `perm ∈ {N,B,T}`, dirty, value, ghost version, and source operation. The L2 owns:

- `state ∈ {INVALID, BRANCH, TRUNK, TIP}`;
- dirty and per-client permission;
- the unique T owner when one exists;
- value/version/source;
- serialized MSHR control (`busy`, current transaction, directory checked, outer ready, grant pending).

The source-mapped invariants are:

- INVALID has no clients and is clean;
- BRANCH is clean;
- TRUNK has one T client at most and records that owner;
- TIP has no T owner and may have B sharers;
- only data-bearing C traffic can publish a newer L1 version into L2.

## Public interface

| Channel | Event | Direction at L2 |
|---|---|---|
| A | `TL.Acquire` | input |
| B | `TL.Probe` | output |
| C | `TL.ProbeAck`, `TL.Release` | input |
| D | `TL.Grant`, `TL.ReleaseAck` | output |
| E | `TL.GrantAck` | input |

`L2.DirectoryResult`, `L2.OuterAcquire`, and `L2.OuterGrant` are private. Strict composition connects exactly the seven public TileLink event ports and cannot read either child's private state.

## Directed state-derived paths

| Trace | Derived behavior |
|---|---|
| `cold_read.yaml` | N→Acquire(NtoB)→directory miss→outer refill→GrantData(T) |
| `shared_read.yaml` | second reader causes T→B Probe/ProbeAck, then GrantData(B), final TIP with two B clients |
| `write_upgrade.yaml` | BtoT upgrade probes the other sharer to N, returns data-less Grant(T), store creates version 1 |
| `dirty_owner_handoff.yaml` | dirty T owner returns ProbeAckData(version 1), L2 publishes it, new reader receives version 1 |
| `dirty_release_reacquire.yaml` | voluntary ReleaseData publishes version 1, ReleaseAck completes, later read is an L2 hit without outer refill |

These traces are unit witnesses for protocol paths, not a litmus corpus.

## Solver change

The Z3 persistent-state encoding now expresses concurrent atomic writes linearly: every active write constrains the same next-state value, while no active write implies stutter. Disagreeing simultaneous writes remain unsatisfiable, but the encoding avoids the previous quadratic pairwise equality expansion. This was required for three coherence accesses within one bounded trace and is covered by a dedicated regression.

## Integration boundary

The legacy `model/coherence/module.yaml` remains only for reproducibility of the existing Load–Load bug composition. v0.18 adds the new source-grounded composition beside it; it does not pretend that the older LSQ/L1/MSHR event vocabulary has already been adapted to the new TileLink interface. That unification is work for the later hierarchical search milestone.

See `BOOM_L2_SOURCE_MAP.md` for the exact configuration chain, file hashes, RTL mapping, and omissions.
