# v0.21 status: previous blind-rediscovery claim withdrawn

The earlier v0.21 package reported an end-to-end BOOM/RVWMO witness. That
claim was not valid for the intended milestone: its core realization used
`examples/boom/model/search/cacheable_path.yaml`, a small path summary, instead
of composing the detailed BOOM LSU, L1D and MSHR models.

The generated architectural skeleton and the RVWMO result were real, but they
only showed that the summary admitted the path. They did **not** show that the
path was reachable in the source-derived BOOM memory model. The checked-in
search profile is therefore deliberately `BLOCKED`, and the old summary
composition is retained only as a rejected prototype for regression/audit.

## Rebuild admission gate

`examples/boom/source/v021.yaml` is now the normative source ledger. It pins:

- BOOM v4 LSU, DCache, MSHR, NBDTLB and ROB files by commit and SHA-256;
- the Chipyard revision selected by BOOM's `CHIPYARD.hash`;
- the corresponding Rocket-Chip `ClientMetadata` and memory-command
  classification used by BOOM's MSHR secondary-ready logic;
- the matching SiFive InclusiveCache directory/MSHR/B/C/D/E sources;
- a source range and a separate implementation status for every admitted
  memory-relevant behavior.

The milestone cannot be marked complete while any ledger item is `missing` or
`needs-rework`. The future default composition must also satisfy all of the
following:

1. no module under `examples/boom/model/search/` is referenced;
2. LDQ/STQ/MSHR allocation is internal model behavior (the local two-entry
   MSHR allocator now satisfies this rule; its detailed-entry integration is
   still pending);
3. L1 hit/miss/nack follows tag, permission, conflict and MSHR-ready state;
4. MSHR Acquire/Grant/GrantAck uses the public TileLink A/D/E interface;
5. the input contains instructions and finite reset/configuration state only,
   never dynamic TLB/cache/MSHR/coherence outcomes.

Only after the detailed source-derived composition passes this gate will blind
rediscovery be re-enabled.
