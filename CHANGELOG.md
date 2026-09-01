# Changelog

## 0.3.0

- 新增 `StateVariable / StateRequirement / StateUpdate`。
- 新增 pre-state 检查、atomic post-state update、自动 stutter 和同周期冲突写检测。
- 新增状态规则实例化及状态拒绝诊断。
- completed Trace metadata 中保存初始状态、最终状态和逐周期状态历史。
- 事件目录扩展到 16 种事件。
- 新增 `TLBHit / DCacheReqValid / DCacheReqReady / DCacheReqFire` 路径。
- 新增 ready/valid/fire 的双向约束及身份保持。
- 新增 BOOM retry queue 单槽摘要，保持 `op_id/ldq_idx/vaddr`。
- 新增 branch kill 与 exception 清空 retry queue 的防御路径。
- 新增正向 `retry_dcache_completion.yaml` 和负向 `retry_dcache_branch_kill.yaml`。
- 保持 v0.2 completion model 向后兼容。
- 测试增至 31 项。

## 0.2.0

- 新增有界候选隐藏事件 `EventSlot`。
- 新增带输入/输出事件角色的 `Transformation`。
- 新增 Transformation 有限实例化和 cycle bound。
- 新增三值表达式求值器与依赖无关的有限域可行性后端。
- 新增部分 Trace 必需字段补全和 witness 物化。
- 新增 `umcm complete` CLI。
- 新增 BOOM `TLBMiss → RetryEnqueue → RetryIssue` 示例模型。
- 将 `RetryIssue(L0)` 明确为 witness query goal，并用反向 causal-support Transformation 补全前置事件，避免把路径选择误写成无条件活性。
- 新增“取消 query goal 后隐藏 retry 事件均可不发生”的回归测试。
- 将事件目录扩展为 10 种事件，加入 `LSU.RetryIssue`。
- 测试增至 24 项。

## 0.1.0

- 建立 Python package 与测试骨架。
- 实现类型化表达式 AST。
- 实现 Event schema、动态事件和部分 Trace。
- 实现 YAML/JSON 往返序列化。
- 实现 schema-aware Trace 验证与 CLI。
- 加入 BOOM Load–Load 案例的部分 Trace 输入。
