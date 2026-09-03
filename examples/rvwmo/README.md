# RVWMO v0.16 example

Run the built-in architectural checker on a minimal forbidden execution:

```bash
PYTHONPATH=src python3 -m umcm check \
  --schema examples/rvwmo/events.yaml \
  --trace examples/rvwmo/load_load_forbidden.yaml \
  --axioms examples/rvwmo/model.yaml
```

The command returns status 1 and reports the cycle
`R1 -fr-> W -rfe-> R0 -ppo-> R1`.

`Arch.AddressDependency`, `Arch.DataDependency`, `Arch.ControlDependency`,
`Arch.FenceOrder`, `Arch.LRSCPair`, and `Arch.PipelineDependency` are
architectural facts supplied by an ISA-aware front-end.  The RVWMO checker uses
them to instantiate PPO rules 4 and 8--13; it does not infer register-level
dependencies from microarchitectural events.
