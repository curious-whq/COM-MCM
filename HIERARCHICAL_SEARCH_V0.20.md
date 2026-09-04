# Hierarchical search v0.20

v0.20 introduces a real two-level search boundary. It does **not** claim the
v0.21 blind BOOM bug rediscovery milestone.

## Layer 1: architectural skeleton

The search specification declares bounded architectural operation slots and
finite domains only. The engine materializes candidate architectural traces,
runs the v0.16 RVWMO checker, and retains an execution graph with the requested
status. The graph is converted to serializable obligations:

- initial and written values;
- `read_from` source/value pairs;
- `program_order`, `coherence_order`, `from_read`, and `preserved_order` edges.

For the checked-in BOOM query the engine enumerates four read-value outcomes
and discovers the forbidden outcome `R0=1, R1=0`. Its essential cycle is:

```text
R1 -fr-> W -rfe/rf-> R0 -ppo-> R1
```

No TLB, cache, MSHR, probe, queue index, or expected microarchitectural path is
present in this layer.

## Layer 2: public-interface realization

The v0.18 coherence adapter converts the architectural operations to public
`Coherence.LineInit` and `Coherence.Access` requests. It enumerates cache-access
schedules independently of architectural program order—BOOM may issue memory
operations out of order—and constrains only public `Coherence.LoadResult` and
`Coherence.StorePerformed` outputs with the layer-1 value/version obligations.

The solver derives the cache/coherence internals. For the forbidden skeleton it
finds the request order `R1 -> W -> R0`: the younger load sees the initial
version, the store creates the new version, and the older load sees that new
version. No hit/miss, Acquire, Grant, Probe, or MSHR event is injected.

Before solving, the adapter verifies that every input event is non-private and
allowlisted, and that every constrained result type is an output port of a
child module. This makes the v0.15 encapsulation rule executable in search.

## Honest end-to-end status

The report is `partial`, not an end-to-end witness. The detailed v0.15
LSQ/L1/MSHR composition still requires `ldq_idx`, `mshr_id`, and routing choices
as trace annotations during template instantiation. It also uses a pre-v0.18
memory-side vocabulary that has no public adapter to the TileLink coherence
composition. v0.20 represents this as a required `interface_gap` stage, so the
engine cannot silently reinterpret it as UNSAT or claim success.

Removing this blocker—making finite allocation/routing solver choices and
joining the detailed cache/MSHR ports to coherence—is the concrete v0.21 task.

## Run

```bash
PYTHONPATH=src python3 -m umcm search boom --rvwmo --backend z3 \
  --output examples/boom/search/BOOM_SEARCH_REPORT.yaml \
  --witness-dir examples/boom/search/witnesses
```

The machine-readable report contains the architectural graph, all obligations,
each realization stage, the discovered public schedule, and `end_to_end: false`.
