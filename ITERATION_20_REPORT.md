# Iteration 20 report

## Delivered

- Added `umcm search` plus `umcm.search.v0.20.0` specification and report IRs.
- Added bounded architecture-only operation-slot enumeration and reuse of the
  v0.16 built-in RVWMO checker.
- Added serializable read-value/read-from, write-value, `po`, `co`, `fr`, and
  `ppo` obligations.
- Added a public coherence adapter that derives candidate request schedules
  from architectural version relations without enforcing architectural `ppo`
  at the out-of-order cache-request boundary.
- Added constraints over public `Coherence.LoadResult` and
  `Coherence.StorePerformed` ports, with no observation of child-private state
  or events.
- Added strict adapter input allowlists, private-event rejection, and output-port
  verification.
- Added explicit required `interface_gap` stages and an end-to-end status bit.

## BOOM acceptance result

```text
ARCHITECTURE FORBIDDEN
  R0 = load x -> 1
  R1 = load x -> 0
  W  = store x, 1

  rf:  InitX->R1, W->R0
  fr:  R1->W
  ppo: R0->R1

COHERENCE REALIZABLE
  R1 -> W -> R0
  R1 reads InitX version 0
  W creates version 1
  R0 reads W version 1

HIERARCHICAL SEARCH PARTIAL
  end-to-end=no
```

Layer one finds the forbidden outcome after three architectural value
assignments. Layer two realizes the version flow on the actual v0.18
BOOM-L1/SiFive-InclusiveCache composition on its first obligation-ranked
schedule. The input contains only `Coherence.LineInit` and `Coherence.Access`.

## Deliberate blocker

This iteration does not claim the final BOOM bug witness. The detailed
LSQ/L1/MSHR composition still binds `ldq_idx`, `mshr_id`, and cache routing from
`Arch.Load` annotations before solving, and its memory-side vocabulary has no
public adapter to the v0.18 TileLink composition. The report lists these missing
interfaces and keeps `end_to_end: false`.

v0.21 must move finite allocation/routing choices into the model and close the
public LSQ/L1/MSHR/coherence/ROB path. Only then may `umcm search boom --rvwmo`
report an end-to-end blind witness.

## Regression result

```text
177 passed
```

The four v0.20 tests cover architecture skeleton discovery without µarch hints,
real v0.18 coherence realization, private-event rejection, and persistent
interface-gap reporting.
