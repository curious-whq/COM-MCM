# BOOM v4 configuration → v0.18 coherence source map

v0.18 does not treat “an L2” as a generic environment. It follows the configuration chain used by the pinned BOOM v4 repository:

| Link | Pinned revision / evidence |
|---|---|
| BOOM | `58ef2720eae13be26b3008c02b5a74ce29c61c44` |
| BOOM → Chipyard | BOOM `CHIPYARD.hash` = `4180463d52bc0a6b4c004530601ccdabebf0ab7d` |
| Chipyard config | `generators/boom/src/main/scala/common/AbstractConfig.scala:57` selects `freechips.rocketchip.subsystem.WithInclusiveCache` |
| Rocket Chip submodule | `114325b27cfe5312c86a8a325b187be9455a62af` |
| SiFive InclusiveCache submodule | `e3a3000cc1fd4cdf3a4e638e4d081b8aae94ebf0` |

The earlier v0.17 documents contained a mistyped, non-existent BOOM commit string ending in `...7eed605b9a`. v0.18 corrects it to the actual checked-out commit above. The recorded `tlb.scala`, `lsu.scala`, `dcache.scala`, and `mshrs.scala` hashes already corresponded to the real checkout.

## BOOM L1 client mapping

| µMCM behavior | BOOM v4 source |
|---|---|
| Probe reception and clean `ProbeAck` | `src/main/scala/v4/lsu/dcache.scala:145-212` |
| Dirty `ProbeAckData` and voluntary `ReleaseData` | `dcache.scala:24-142` |
| A/B/C/D/E wiring | `dcache.scala:818-865` |
| Client permission grow and grant transition | `src/main/scala/v4/lsu/mshrs.scala:115-126,164-170,241-265` |
| GrantAck lifetime | `mshrs.scala:138-148,254-265,361-365` |
| Primary/secondary admission and TileLink ports | `mshrs.scala:513-533,598-669,717-718` |

Pinned SHA-256:

```text
dcache.scala  82d5562b6d6220be5714716c6b935a001ed6fc54747b4fc925603cabbde9aac4
mshrs.scala   7e70d1a095f9543ecb20c2983e925205ef473376fe7e6112173d7e8079069fcf
```

## Inclusive L2 mapping

| µMCM behavior | SiFive InclusiveCache source |
|---|---|
| Per-line dirty/state/clients/tag directory entry | `Directory.scala:27-52` |
| Directory hit/miss | `Directory.scala:76-139` |
| `INVALID/BRANCH/TRUNK/TIP` meanings and permission predicates | `Parameters.scala:255-283` |
| Last-level requirement and client bitmap | `Parameters.scala:151-177` |
| Directory invariants | `MSHR.scala:99-115` |
| Serialized per-line request and schedule/wait state | `MSHR.scala:117-208` |
| Resulting directory metadata | `MSHR.scala:211-307` |
| Need-probe / need-outer-acquire / need-GrantAck plan | `MSHR.scala:500-641` |
| Inner B probes | `SourceB.scala:24-80` |
| C-channel ProbeAck versus Release handling | `SinkC.scala:24-32,40-160` |
| E-channel GrantAck | `SinkE.scala:23-46` |
| D-channel Grant/GrantData/ReleaseAck | `SourceD.scala:70-140,185-241` |

Pinned SHA-256 values are embedded in `examples/boom/model/coherence/inclusive_l2.yaml` and asserted by tests.

## Version abstraction

The RTL stores bytes and coherence metadata; it has no literal integer “version” signal. The model adds a ghost version solely for memory-model search:

- a completed store under T permission creates exactly the next version in its private L1;
- L2 learns that version only from data-bearing C traffic (`ProbeAckData` or `ReleaseData`);
- a GrantData carries the L2's current value/version/source tuple;
- clean acknowledgements cannot manufacture a newer version.

This is a verification abstraction tied to the RTL data-flow points, not a claimed hardware field.

## Deliberate bounded scope

The executable model is line-granular and has two inner caching clients. It collapses SRAM sets/ways, replacement choice, banked data beats, ready/valid stalls, and arbitration latency. It serializes transactions per line and does not yet model concurrent secondary L2 MSHRs, outer writeback/flush/control traffic, prefetches, or a unified adapter to the older detailed LSQ/L1/MSHR bug composition. These are explicit omissions, not environment-selected hit/miss outcomes.
