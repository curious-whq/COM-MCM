# Iteration 18 report

## Delivered

- Followed BOOM's pinned `CHIPYARD.hash` and confirmed that the corresponding BOOM `AbstractConfig` selects SiFive `WithInclusiveCache`.
- Added a source-pinned BOOM L1 TileLink coherence client with private N/B/T permission, dirty data, and version state.
- Added a source-pinned SiFive InclusiveCache L2 with bounded Directory metadata, serialized per-line MSHR control, owner/sharer permissions, and A/B/C/D/E transactions.
- Added state-derived cold miss, shared read, BtoT upgrade, dirty ProbeAckData handoff, and dirty ReleaseData/reacquire witnesses.
- Added public version-observation events while keeping directory, outer refill, and all state private.
- Preserved strict ports-only composition across seven TileLink connections.
- Replaced quadratic atomic-write conflict constraints in the Z3 state encoder with an equivalent linear encoding.
- Corrected the mistyped BOOM commit string inherited from v0.17 and documented the correction.

## Acceptance evidence

Every v0.18 input trace contains only `Coherence.LineInit`, `Coherence.Access`, and optionally `Coherence.Evict`. Tests assert that:

- a cold line cannot masquerade as an L1 hit;
- second-reader sharing derives a T→B probe;
- BtoT store upgrade invalidates the other sharer;
- dirty ownership handoff carries version 1 through ProbeAckData;
- voluntary dirty eviction carries version 1 through ReleaseData and the later reader does not perform an outer refill;
- final directory metadata satisfies the represented INVALID/BRANCH/TRUNK/TIP invariants;
- module metadata pins BOOM, Chipyard, Rocket Chip, and InclusiveCache revisions.

## Regression result

```text
168 passed in 350.33s
```

The complete v0.17 suite passes together with nine focused v0.18 coherence tests and the new Z3 atomic-state encoding regression.

## Explicitly deferred

- Set/way replacement, SRAM and multi-beat timing, bank arbitration, backpressure, and concurrent L2 MSHR scheduling.
- Outer coherent managers (the pinned cache requires last-level operation); backing memory is a private bounded refill action.
- A public adapter unifying this coherence composition with the older detailed LSQ/L1/MSHR Load–Load witness.
- Automatic path-goal generation (v0.19) and hierarchical architectural-skeleton search (v0.20).
