# µMCM Foundation v0.1

这是第一轮基础设施代码。当前版本只实现与 FM-Agent 无关的底层 IR：

- `Sort`：事件字段和表达式的轻量类型；
- `Expr`：后续 `Transformation` / `Axiom` 共用的类型化表达式 AST；
- `FieldSpec` / `EventType` / `EventCatalog`：事件 schema；
- `EventInstance`：完整或部分观测的动态事件；
- `Trace`：事件、约束和元数据组成的部分 Trace；
- YAML / JSON 往返序列化；
- schema/trace 验证 CLI。

当前版本**不包含**状态转移求解、Z3、Execution Graph 或 RVWMO 检查；这些属于后续迭代。

## 安装与测试

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

无需安装也可在仓库根目录运行：

```bash
PYTHONPATH=src python -m umcm validate \
  --schema examples/boom_load_load/event_types.yaml \
  --trace examples/boom_load_load/partial_trace.yaml
```

预期输出：

```text
VALID partial trace: 6 event(s), 2 constraint(s), 9 event type(s)
```

## 设计约束

1. Trace 中缺失字段表示“尚未观测”，不是默认值。
2. 未知但需要跨事件共享的量用 `Symbol` 表示，而不是任意字符串约定。
3. 每个表达式节点携带 sort；明显的类型错误在构造或反序列化阶段立即失败。
4. Trace 只引用事件类型名称，事件 schema 独立存放，便于未来替换模块模型。
5. 所有文件都带有显式 `schema_version`，后续可以做兼容迁移。

## 当前目录

```text
src/umcm/ir/sort.py          轻量 sort
src/umcm/ir/expression.py    表达式 AST
src/umcm/ir/event.py         事件 schema 与动态事件
src/umcm/ir/trace.py         部分 Trace
src/umcm/serialization.py    YAML/JSON 编解码
src/umcm/cli.py              validate 命令
examples/boom_load_load/     BOOM Load–Load 案例的第一版输入
```

## 下一轮

下一轮将在此 IR 上加入：

- 状态变量与初始状态；
- `Transformation` 的 `when / update / ensure`；
- 有界候选事件槽；
- Trace 补全与可行性检查器的最小 Z3 后端。
