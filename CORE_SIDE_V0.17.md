# BOOM core-side memory µMCM v0.17

## Scope

v0.17 formalizes memory behavior between decoded core operations and the architectural retirement boundary. It is a bounded, searchable µMCM, not a signal-for-signal copy of BOOM or Rocket Chip.

The executable composition is `examples/boom/composition/core_side_v017.yaml`. It preserves the v0.15 rule that a module may access only its own state and may communicate with children or siblings only through declared public event ports.

## Module contracts

| Module | Private state/events | Public inputs | Public outputs |
|---|---|---|---|
| `boom_v4_lsu_translation` | LSU retry-queue round trip | memory instruction, TLB response, miss-ready | TLB request, translated memory, memory fault |
| `boom_v4_nbdtlb` | per-hart walker state, entry valid, decision, refill, invalidate | TLB request, PTW result, SFENCE | TLB response/miss, PTW request, miss-ready |
| `bounded_ptw_environment` | none | PTW request, finite page map | PTW result |
| `atomic_core` | line busy, reservation valid, AMO/LR/SC steps | translated memory, reservation invalidate | memory completion |
| `reservation_bridge` | none | DCache probe release | reservation invalidate |
| `mmio_core` | one global busy bit | translated memory | IOMSHR request/access/ack/response, memory completion |
| `fence_core` | none | memory instruction, DCache ordered | architectural fence, memory completion |
| `rob_core` | per-entry allocated/completed/faulted/squashed/committed | instruction, completion, fault, branch mispredict | commit, precise exception, squash, branch kill |
| `retire_core` | none | ROB commit | architectural memory events and commit markers |

## Autonomous TLB path choice

Dynamic TLB outcomes are never input facts. A finite per-hart/VPN `Core.PageMap` supplies only bounded page-table/environment configuration:

- `initial_valid` initializes the private entry valid bit;
- `accessible` determines whether a PTW result is a refill or a page fault;
- `paddr` supplies the translated address.

For an invalid accessible entry, the model derives the BOOM source-grounded module boundary:

```text
MemoryInstruction → TLBRequest(attempt=0)
  → Decision(hit=false) → TLBResponse(miss=true) → Miss
  → PTWRequest → PTWResult(fault=false)
  → Refill(valid=true) → MissReady
  → LSU Retry → TLBRequest(attempt=1)
  → Decision(hit=true) → TLBResponse → TranslatedMemory
```

For an invalid inaccessible entry, the PTW result still refills the NBDTLB permission metadata. The LSU retry then receives a non-miss response with `page_fault=true`, which produces `Core.MemoryFault`. The PTW environment does not bypass the TLB/LSU boundary to signal the ROB directly.

The implementation is pinned to official BOOM commit `58ef2720eae13be26b3008c02b5a74ce29c61c44`. See `BOOM_V4_TLB_SOURCE_MAP.md` for exact source regions and deliberate abstractions. v0.18 corrects the previously mistyped commit string; the source-file digests were already those of this real commit.

## ROB and precise exceptions

Each bounded memory instruction allocates a private ROB entry. `Core.MemoryComplete` sets the completed bit and permits a public `ROB.Commit`; pairwise state requirements require all older same-hart entries to be committed first.

A memory fault records the exception privately. `ROB.PreciseException` is enabled only after all older same-hart operations have committed, after which the faulting and younger operations receive `Core.SquashMemory`. A branch mispredict independently squashes younger memory operations and emits the existing `Core.BranchKill` interface event.

## AMO and LR/SC

AMO completion requires an ordered private `AMORead → AMOWrite` sequence while the line busy state is held.

LR sets one reservation bit per bounded `reservation_id`, which represents a hart+cache-line identity. A matching public `DCache.ProbeRelease` is converted to `Core.ReservationInvalidate`; SC success is equated to the reservation pre-state and consumes the reservation. Therefore:

- valid reservation: `SCDecision(success=true) → SCWrite → completion`;
- absent or invalidated reservation: `SCDecision(success=false) → completion`, with no write event;
- only successful SC produces architectural `Arch.SC` and `Arch.LRSCPair`.

## Fence and MMIO

A fence is decoded to `Arch.Fence` but cannot complete until a same-hart public `DCache.Ordered` event is observed. ROB retirement occurs after that completion.

Uncacheable loads and stores route through a one-outstanding IOMSHR state machine. Loads require `Request → MemAccess → MemAck → Response → completion`; stores complete after `MemAck` and do not generate a load response.

## Validation traces

The `examples/boom/traces/core/` directory contains directed witnesses for:

- autonomous TLB miss/refill/retry followed by MMIO load retirement;
- independent same-VPN TLB state on two harts;
- SFENCE invalidation forcing a later miss/refill/retry;
- initial TLB hit plus AMO read/write retirement;
- LR/SC success;
- LR, probe invalidation, and SC failure;
- precise page fault with older commit and younger squash;
- fence waiting for DCache ordered;
- branch recovery;
- uncacheable store acknowledgement.

Use `--backend z3` for these stateful multi-module traces. The finite backend remains a small reference evaluator and is not intended for this candidate count.

## Honest boundary

The existing detailed LSQ/L1/MSHR compositions still own ordinary cacheable load/store execution. v0.17 does not claim a single signal-level composition between that legacy request vocabulary and `Core.MemoryInstruction`. The external Rocket Chip PTW is a bounded environment, while NBDTLB replacement, full permission/PMP/PMA logic, multiple-hit recovery, passthrough/kill, and simultaneous two-port arbitration remain partial. A real L2 directory, ownership/sharer state, permission acquisition, and coherence versioning are v0.18 work.
