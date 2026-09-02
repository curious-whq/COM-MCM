# Iteration 11 — Generic BOOM Load-Side LDQ Model

## Goal

Move from a two-load witness-specific LSU model to a finite, trace-driven load-side LDQ model grounded in the supplied BOOM v4 `LSU` Chisel source.

The supplied source snapshot has SHA-256:

```text
81d738e8c8967f0fad72a2406a623a384fac229e10c20ffa37a6907aece9b7b5
```

## Infrastructure additions

### Collection trace roles

`TraceRoleSpec` now supports:

```yaml
cardinality: many
min_matches: 1
```

so a role such as `loads` resolves to every observed `Arch.Load`, ordered by cycle and event id.

### Declarative module repeat

Raw module templates can now declare:

```yaml
repeat:
  - over: loads
    as: load
    include:
      state_variables: ...
      transformations: ...
```

The operational engine remains concrete and bounded. The repeat is expanded before `ModuleSpec` parsing, so the solver still sees ordinary finite states and transformations.

## Generic LDQ state per observed load

For every load in the input trace, the LSU template now creates:

```text
valid
addr_valid
addr_is_virtual
addr_is_uncacheable
address
executed
succeeded
order_fail
observed
forward_std_val
forward_stq_idx
ld_byte_mask
value
squashed
executing_now
```

The existing Load–Load bug-specific pairwise search/recovery rules remain as a separate witness layer; the per-entry lifecycle is now generic.

## Source-grounded transformations added

The generic load-side model covers:

1. LDQ allocation/reset of per-load state.
2. TLB miss records a virtual address.
3. Retry enqueue clears the LDQ address-valid bit while the request identity moves into the retry path.
4. TLB hit / accepted DCache request records a physical address.
5. `LoadExecuted` sets the LDQ executed bit.
6. DCache nack clears executed.
7. Successful load response sets `succeeded` and captures the value.
8. `LoadObserved` sets the observed bit.
9. `LoadOrderFail` sets the order-fail bit.
10. Load wakeup requires valid address, non-virtual, not executed, not succeeded, and no order failure.
11. Branch kill / recovery squash / core exception invalidate the entry.
12. Non-forwarded load commit requires valid + executed + succeeded + matching value and then deallocates the entry.

Store-to-load forwarding is intentionally left for a later LSQ iteration, so the generic commit rule currently models the non-forwarded load path.

## Independent regression beyond the known bug

A new standalone load-side trace exercises:

```text
LoadA allocated in LDQ[5]
→ DCache request accepted
→ executed
→ DCache nack
→ executed cleared
→ load wakeup becomes legal
→ reexecute
→ response value 42
→ commit
```

This trace is FEASIBLE.

Moving the wakeup before the nack is INFEASIBLE because the pre-state still has:

```text
LSU.ldq[5].executed == true
```

while BOOM's wakeup selection requires `!ldq_executed`.

## Three-load finite-instantiation regression

The real Load–Load bug trace was extended with an unrelated third load:

```text
LoadExtra → LDQ[21]
```

without changing the LSU transformation template. v0.11 automatically creates the LDQ[21] state family. Since no execution events are supplied for it, it remains allocated but unexecuted/unsucceeded. The original `LoadAlpha/LoadBeta` RVWMO violation is still found.

## Bug regression

Buggy parameterized composition:

```text
FEASIBLE
→ execution graph remains FORBIDDEN
```

Fixed parameterized composition with the same bad commit:

```text
INFEASIBLE
```

Fixed recovery trace:

```text
FEASIBLE
LoadBeta.order_fail = true
LoadBeta.squashed = true
LoadBeta.valid = false
→ architectural execution graph ALLOWED
```

## Validation

```text
98 passed
```

This includes all previous tests plus collection-role, repeat-expansion, generic nack/wakeup, illegal wakeup, three-load expansion, and fixed-recovery regressions.

## Remaining load-side gaps

v0.11 is not a complete LSU model. Not yet generalized:

- STQ and Store→Load forwarding;
- store-generated Load ordering failures;
- pairwise LD–LD search generation for arbitrary load pairs (the current real-bug pair remains explicitly selected);
- byte-mask computation from instruction size for arbitrary loads;
- queue head/tail allocation/reuse semantics;
- store/fence/AMO/LR-SC behavior;
- resource-arbitration completeness.
