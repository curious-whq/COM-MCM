# BOOM Load–Load Modular Model

本目录是 v0.9 对 v0.8 单体 CompletionSpec 的模块化拆分。

```text
buggy_composition.yaml / fixed_composition.yaml
├── modules/lsu_*.yaml
├── modules/dcache.yaml
├── modules/mshr.yaml
├── modules/coherence.yaml
└── modules/rob_*.yaml
```

连接采用 `shared_event`：两端看到的是同一个 EventInstance，而不是复制后的两个
事件。模块 stateful Transformation 只能访问本模块声明的 StateVariable。

运行：

```bash
PYTHONPATH=src python3 -m umcm complete \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/stage6_trace.yaml \
  --composition examples/boom_load_load/modular/buggy_composition.yaml \
  --output completed_buggy.yaml
```

对应的 v0.8 单体文件仍保留，用于等价性回归测试。
