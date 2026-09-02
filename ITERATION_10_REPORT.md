# Iteration 10 — Trace-driven parameterized module instantiation

## Goal

Remove witness-specific operation identities and fixed queue-entry identities from the reusable BOOM module models while keeping the existing finite operational semantics unchanged.

The v0.9 module files were concrete instances of one witness: `L0`, `L1`, `W1`, `LDQ[0]`, `LDQ[1]`, and `MSHR[0]` appeared directly in slots, state names, and guards. v0.10 adds a trace-driven template layer before `ModuleSpec` parsing.

## New infrastructure

### Trace roles

A composition may declare ordered semantic roles. Each role selects exactly one observed trace event using `event_type` plus optional field predicates, then exports concrete values from event fields or annotations.

Example:

```yaml
roles:
  - name: older_load
    event_type: Arch.Load
    where:
      fields.hart: 0
      fields.program_index: 0
    exports:
      op_id: fields.op_id
      address: fields.address
      ldq_idx: annotations.microarch.ldq_idx
      mshr_id: annotations.microarch.mshr_id
```

Role predicates can refer to previously resolved roles, so a later event can be selected using `${older_load.op_id}`.

### Typed placeholders

Raw module YAML may use placeholders such as:

```yaml
op_id: ${older_load.op_id}
ldq_idx: ${older_load.ldq_idx}
state: LSU.ldq[${younger_load.ldq_idx}].observed
```

An exact placeholder preserves the Python type. Thus `${older_load.ldq_idx}` becomes integer `13`, not string `"13"`. Embedded placeholders are rendered into strings for state-variable names and labels.

### Composition behavior

`compose_modules(catalog, composition, trace)` now:

1. resolves trace roles;
2. loads each raw module YAML;
3. substitutes template parameters;
4. parses the concrete result as a normal `ModuleSpec`;
5. performs the same port/state/Transformation validation as v0.9;
6. merges modules into the existing `CompletionSpec`.

Concrete v0.9 compositions remain compatible and do not require a trace.

`umcm compose` now accepts `--trace` for parameterized compositions. `umcm complete --composition` automatically uses its input trace for instantiation.

## Parameterized BOOM templates

New reusable templates are under:

```text
examples/boom_load_load/modular/templates/
├── lsu_buggy.template.yaml
├── lsu_fixed.template.yaml
├── dcache.template.yaml
├── mshr.template.yaml
├── coherence.template.yaml
├── rob_buggy.template.yaml
└── rob_fixed.template.yaml
```

They no longer contain semantic literals `L0`, `L1`, `W1`, `LSU.ldq.L0`, `LSU.ldq.L1`, or `MSHR.0`.

For example, persistent state is instantiated as:

```text
LSU.ldq[${older_load.ldq_idx}].valid
LSU.ldq[${younger_load.ldq_idx}].observed
MSHR[${older_load.mshr_id}].state
```

## Reindexing/renaming regression

`stage10_parameterized_trace.yaml` intentionally changes every identity:

```text
older load    = LoadAlpha   LDQ[13]
younger load  = LoadBeta    LDQ[7]
visible store = StoreGamma
MSHR           = MSHR[3]
address        = data0
```

No Transformation template was edited for these values.

The composed buggy model produces:

```text
LSU.ldq[13].executed / succeeded
LSU.ldq[7].executed / succeeded / observed
MSHR[3].state
```

and the completed execution graph is still:

```text
InitData --rf--> LoadBeta
StoreGamma --rf--> LoadAlpha
InitData --co--> StoreGamma
LoadBeta --fr--> StoreGamma
LoadAlpha --ppo--> LoadBeta
```

with cycle:

```text
LoadBeta -fr-> StoreGamma -rfe/rf-> LoadAlpha -ppo-> LoadBeta
```

so the buggy result remains `FORBIDDEN`.

For the fixed template, the same bad architectural commit target is `INFEASIBLE`; with the younger commit marked `occurs=false`, the recovery trace is feasible and the execution graph is `ALLOWED`.

## Important boundary

v0.10 parameterizes **concrete finite observations**. The current example obtains `ldq_idx` and `mshr_id` from partial-trace annotations. It does not yet synthesize an unknown LDQ/MSHR allocation from the hardware allocator. That belongs to later general LSQ/MSHR modeling.

The key improvement is that the reusable module rules no longer contain the chosen operation names or physical entry numbers.

## Validation

```text
92 tests passed
compileall passed
buggy renamed/reindexed witness: FEASIBLE + FORBIDDEN
fixed same bad commit target: INFEASIBLE
fixed recovery witness: FEASIBLE + ALLOWED
```
