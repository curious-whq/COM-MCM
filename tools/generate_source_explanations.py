#!/usr/bin/env python3
"""Generate line-complete Chinese explanations for every Python file in src/."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
OUTPUT_ROOT = ROOT / "docs" / "source-explanations"


FILE_DESCRIPTIONS = {
    "umcm/__init__.py": "定义 µMCM 顶层包的公开版本信息。",
    "umcm/__main__.py": "把 `python -m umcm` 转交给命令行入口。",
    "umcm/cli.py": "实现轨迹校验、补全、抽象和内存模型检查的命令行界面。",
    "umcm/errors.py": "集中定义项目可预期异常的类型层次。",
    "umcm/graph/__init__.py": "汇总执行图构造、关系运算和公理检查的公开接口。",
    "umcm/graph/builder.py": "把具体事件轨迹投影成候选架构执行图。",
    "umcm/graph/checker.py": "在有限候选执行图上检查关系公理并汇总判定。",
    "umcm/graph/execution.py": "定义内存操作、执行图及其序列化格式。",
    "umcm/graph/model.py": "定义可加载的投影规则、派生关系和公理模型。",
    "umcm/graph/relation.py": "提供有限二元关系的关系代数与环检测。",
    "umcm/hierarchy/__init__.py": "汇总层次化轨迹抽象与精化检查接口。",
    "umcm/hierarchy/engine.py": "执行确定性的轨迹抽象、精化验证和内存模型保持性检查。",
    "umcm/hierarchy/model.py": "定义层次抽象规则的可序列化配置模型。",
    "umcm/ir/__init__.py": "汇总 µMCM 中间表示的公开类型与构造器。",
    "umcm/ir/completion.py": "定义有限事件槽和补全模型。",
    "umcm/ir/event.py": "定义事件模式、事件目录和动态事件实例。",
    "umcm/ir/expression.py": "定义带类型表达式 AST、序列化和遍历工具。",
    "umcm/ir/sort.py": "定义事件字段与表达式使用的轻量值类型。",
    "umcm/ir/state.py": "定义有界微架构轨迹中的持久状态、前置条件和更新。",
    "umcm/ir/trace.py": "定义由动态事件、约束和部分观测组成的轨迹。",
    "umcm/ir/transformation.py": "定义基于事件角色的有界操作转换规则。",
    "umcm/serialization.py": "提供安全的 YAML/JSON 读写和表达式值编解码。",
    "umcm/solver/__init__.py": "汇总轨迹补全求解器的公开 API。",
    "umcm/solver/completion.py": "实现轨迹补全的公共入口和结果物化。",
    "umcm/solver/evaluator.py": "在部分赋值下对带类型表达式进行三值求值。",
    "umcm/solver/finite.py": "实现确定性的有限域可满足性搜索。",
    "umcm/solver/problem.py": "把角色转换规则实例化为有界求解问题。",
    "umcm/solver/state.py": "在完整赋值上模拟并检查持久状态语义。",
}


CLASS_DESCRIPTIONS = {
    "UMCMError": "项目所有可预期错误的基类，便于调用方统一捕获。",
    "SchemaError": "表示事件模式缺失、非法或内部不一致。",
    "TraceValidationError": "表示轨迹不符合事件目录或引用规则。",
    "ExpressionTypeError": "表示表达式操作数或结果类型不合法。",
    "SerializationError": "表示 YAML/JSON 数据无法安全转换为 IR。",
    "SolverError": "表示求解问题无法编码或求解。",
    "BackendUnavailableError": "表示请求的可选求解后端尚未安装。",
    "CompletionError": "表示补全模型无法实例化。",
    "GraphError": "表示轨迹无法投影或构造执行图。",
    "AxiomError": "表示公理或关系配置非法。",
    "AbstractionError": "表示层次抽象配置无法应用。",
    "CandidateSpace": "保存投影后的内存操作以及读源、相干序候选空间。",
    "_RFHintEvidence": "保存一条读源提示的规范化证据，并提供稳定去重键。",
    "_COHintEvidence": "保存一条相干序提示的规范化证据，并提供稳定去重键。",
    "AxiomStatus": "枚举单条公理满足或违反两种状态。",
    "AxiomResult": "记录单条公理的判定及用于诊断的环和边。",
    "CandidateCheck": "记录一个候选执行图及其全部公理检查结果。",
    "MemoryModelStatus": "枚举轨迹在内存模型下允许或禁止的状态。",
    "MemoryModelCheck": "汇总一个轨迹的全部候选图检查结果。",
    "OperationKind": "区分初始写、读和普通写三类内存操作。",
    "MemoryOperation": "表示执行图中的一个规范化内存访问节点。",
    "ExecutionGraph": "保存候选内存操作节点、命名关系及图元数据。",
    "RFHintSpec": "描述如何从具体事件中读取读源提示。",
    "COHintSpec": "描述如何从具体事件中读取一条相干序边提示。",
    "ProjectionSpec": "描述把具体事件投影成内存操作时使用的类型名和字段名。",
    "DerivedRelationSpec": "描述通过逆、并、交、差、复合或闭包生成命名关系的规则。",
    "AxiomSpec": "描述一条关系公理的名称、种类和参与关系。",
    "GraphModelSpec": "聚合投影配置、派生关系、PPO 规则和内存模型公理。",
    "Relation": "表示执行图节点标识符上的命名有限二元关系。",
    "LabeledEdge": "为诊断环中的一条边附加关系名称。",
    "MatchValue": "表示角色字段模式中的变量或字面量。",
    "OutputValue": "表示摘要字段从绑定、角色字段或字面量取值的方式。",
    "EventSlot": "表示补全求解器可选择并物化的一个有界候选事件。",
    "CompletionSpec": "聚合事件槽、转换、状态变量、约束和求解时域。",
    "Visibility": "枚举事件的内部、公开和架构可见级别。",
    "FieldSpec": "描述一个事件字段的名称、类型和模式属性。",
    "EventType": "描述一种事件的字段模式、层级、可见性和标签。",
    "EventInstance": "表示轨迹中的一个动态事件及其观测字段。",
    "EventCatalog": "管理事件类型并负责事件集合的模式校验。",
    "Expr": "所有不可变表达式节点的抽象基类。",
    "Literal": "表示一个已知类型的常量表达式。",
    "Symbol": "表示求解赋值中的一个带类型自由符号。",
    "EventField": "表示对指定事件属性或字段的带类型引用。",
    "Unary": "表示一元运算表达式。",
    "Binary": "表示二元运算表达式。",
    "Nary": "表示可变参数的合取、析取或全等表达式。",
    "Ite": "表示 if-then-else 条件表达式。",
    "Call": "表示对已登记纯函数的带类型调用。",
    "Sort": "表示可序列化的布尔、整数、字符串、位向量或领域类型。",
    "StateVariable": "描述一个带初值的持久标量状态单元。",
    "StateRequirement": "描述锚定到事件角色的前状态比较条件。",
    "StateUpdate": "描述锚定到事件角色的原子后状态写入。",
    "PartialObservation": "把一个事件属性的部分观测规范化为路径和值。",
    "Trace": "保存动态事件、类型约束、部分标记和轨迹元数据。",
    "EventRole": "表示一条转换内部使用的命名事件变量。",
    "Transformation": "表示输入、输出、守卫、约束和状态效果组成的有限转换。",
    "CompletionStatus": "枚举补全结果为可行、不可行或未知。",
    "CompletionResult": "汇总补全状态、见证轨迹、赋值和状态模拟信息。",
    "EvaluationContext": "为表达式求值提供事件、符号赋值和函数环境。",
    "FiniteStatus": "枚举有限域搜索结果为 SAT、UNSAT 或 UNKNOWN。",
    "FiniteVariable": "描述有限域搜索变量的名称、类型和值域。",
    "FiniteSolveResult": "保存有限域搜索结果、赋值、节点数和状态检查结果。",
    "NamedConstraint": "给表达式约束附加稳定名称和来源。",
    "StateRequirementInstance": "表示转换绑定后的一条具体状态前置条件。",
    "StateUpdateInstance": "表示转换绑定后的一条具体状态更新。",
    "BoundedProblem": "汇总补全求解所需的事件、约束和状态实例。",
    "StateChange": "记录一个状态单元在单步中的前值、后值和更新来源。",
    "StateStep": "记录一个周期的共享前状态、原子更新和变化。",
    "StateCheckResult": "汇总状态模拟是否可行以及首尾状态和逐步轨迹。",
    "SummaryEvidence": "记录一个摘要事件由哪条规则和哪些源事件产生。",
    "AbstractionCertificate": "保存可重放、可核验的轨迹抽象证书。",
    "AbstractionResult": "把抽象轨迹和对应证书组合为返回值。",
    "RefinementCheck": "记录抽象轨迹相对具体轨迹的精化检查差异。",
    "MemoryModelPreservationCheck": "记录抽象前后候选图集合及保持性判定。",
    "EventRoleSpec": "描述摘要规则中的一个事件角色及字段匹配模式。",
    "SummaryEventSpec": "描述摘要事件的类型、标识模板、字段和注解。",
    "SummaryRuleSpec": "描述多角色匹配、输出摘要和源事件隐藏策略。",
    "RetainSpec": "描述抽象时按类型、标识或可见性保留哪些事件。",
    "AbstractionSpec": "聚合一层到另一层的保留规则、摘要规则和元数据。",
    "_Unknown": "表示部分求值阶段尚不能确定的值。",
    "_TransformationInstantiation": "暂存一次转换实例化产生的普通约束和状态效果。",
}


FUNCTION_DESCRIPTIONS = {
    "_build_parser": "构造完整的命令行解析器，为各子命令登记输入文件、后端和输出选项。",
    "_print_graph_summary": "按候选图打印操作数、关系规模和公理结果，必要时输出诊断环。",
    "_check_metadata": "检查轨迹元数据中的模型名是否与命令行加载的图模型一致。",
    "main": "解析命令行并分派子命令；依次加载模型与轨迹，执行校验、补全、抽象或公理检查，再规范化输出和退出码。",
    "estimated_candidates": "将每个读的读源选择数与每个地址的写序排列数相乘，估算候选执行图总数。",
    "_concrete_event": "仅接收已确定发生的事件；对未发生或发生性仍为符号的事件返回空结果。",
    "_field": "从事件字段映射中读取必需值；字段缺失时用带事件上下文的图错误终止投影。",
    "semantic_key": "把提示的语义字段组成元组，供稳定排序、冲突检测和去重使用。",
    "_rf_hints": "扫描配置指定的提示事件，规范化读、写、地址和值并按读操作分组。",
    "_co_hints": "扫描相干序提示事件，规范化前后写和地址并按地址分组。",
    "project_operations": "遍历具体且发生的事件，按投影配置识别初始写、读和写，并规范化为内存操作。",
    "build_candidate_space": "结合显式提示和语义兼容性为每个读构造读源候选，并为各地址枚举合法写序。",
    "_po_relation": "按同一 hart 的程序索引排序操作，生成线程内程序序 `po` 边。",
    "_co_relation": "把每个地址选定的全序展开为写之间的 `co` 边。",
    "_rfe_relation": "从读源关系中筛出跨 hart 的边，生成外部读源关系 `rfe`。",
    "_ppo_relation": "按模型声明的操作种类对过滤 `po`，生成保留程序序 `ppo`。",
    "_derive_relation": "按配置对已有关系执行逆、并、交、差、复合或传递闭包，得到一个派生关系。",
    "iter_execution_graphs": "对读源选择与相干序排列做笛卡尔枚举，构造基础关系、派生关系及稳定编号的执行图。",
    "check_axiom": "合并公理引用的关系；按 acyclic、irreflexive 或 empty 语义检查，并构造违例诊断。",
    "check_execution_graph": "对一个候选执行图逐条检查模型公理。",
    "check_trace_memory_model": "枚举轨迹的全部候选执行图；只要存在全部公理满足的候选就判为允许。",
    "allowed": "仅当该候选的每条公理都处于满足状态时返回真。",
    "representative": "优先返回允许候选；若不存在则返回第一个候选，空集合返回空值。",
    "relation": "按名称取得执行图关系；未知名称返回同名空关系，简化派生和检查逻辑。",
    "relation_counts": "生成关系名到边数的稳定映射，供摘要输出和诊断使用。",
    "with_relations": "复制当前执行图并用给定映射替换命名关系，其余节点和元数据保持不变。",
    "from_edges": "把任意边迭代器冻结成不可变集合并构造命名关系。",
    "contains": "判断给定起点和终点是否构成当前关系中的边。",
    "sorted_edges": "按起点、终点排序关系边，确保序列化和诊断结果可重现。",
    "inverse": "交换每条边的起点与终点，构造逆关系。",
    "union": "合并两个关系的边集合。",
    "intersection": "保留两个关系共同包含的边。",
    "difference": "删除另一个关系中出现的边。",
    "compose": "连接当前关系的终点与另一关系的起点，计算关系复合。",
    "transitive_closure": "反复扩展可达边直至不再变化，计算有限关系的传递闭包。",
    "union_relations": "把一组关系的边合并成一个指定名称的关系。",
    "find_labeled_cycle": "按稳定节点和关系顺序做深度优先搜索，返回关系并集中的一条确定性标注环。",
    "relation_map": "检查关系名称不重复后构造名称到关系的映射。",
    "_trace_digest": "对轨迹的规范化字典 JSON 计算 SHA-256，作为抽象证书的源轨迹指纹。",
    "_copy_event": "深拷贝事件的可变映射字段，避免抽象结果与输入共享数据。",
    "_concrete_events": "筛出明确发生的事件，并拒绝抽象阶段无法判定的符号发生性。",
    "_match_role": "检查事件类型和字段模式；统一绑定变量，并拒绝字面量或已有绑定冲突。",
    "_cycles_ordered": "检查一组匹配事件的周期是否满足非降序或严格递增要求。",
    "_iter_rule_matches": "按角色递归回溯事件组合，应用互异、顺序和字段统一约束，产出稳定匹配。",
    "_resolve_output_value": "从变量绑定、角色字段或字面量解析摘要字段值，并校验引用存在。",
    "_summary_cycle": "按配置指定的源角色选择摘要周期；未指定时使用匹配事件的最大周期。",
    "_render_id": "用变量绑定和角色事件标识符填充摘要事件 ID 模板，并报告缺失占位符。",
    "_event_sort_key": "生成按周期、事件 ID 排列的稳定排序键；无周期事件放在最后。",
    "_event_payloads": "把轨迹事件转换为按 ID 索引的字典载荷，便于精化逐项比较。",
    "_graph_signature": "把一个候选图规范化为不含候选编号的结构签名。",
    "_check_signatures": "提取并排序全部候选图签名，同时保留内存模型允许性。",
    "abstract_trace": "匹配并生成摘要事件，按保留与隐藏策略选择事件和约束，最后生成可重放证书。",
    "check_refinement": "重新应用抽象并逐项比较事件集合、载荷和证书，确认给定抽象轨迹确由具体轨迹产生。",
    "check_memory_model_preservation": "分别检查具体与抽象轨迹的候选执行图签名，比较允许性和候选集合。",
    "complete_trace": "校验输入、实例化有界问题并调用有限域后端；成功后物化完整轨迹和状态见证。",
    "state_map": "构造状态变量名到声明的映射，供转换和求解问题快速解析引用。",
    "_reject_duplicates": "检查给定名称序列是否重复，发现重复时报告带上下文的模式错误。",
    "field_map": "构造字段名到字段模式的映射，供事件校验和类型查询使用。",
    "register": "校验名称未登记后把新事件类型加入目录。",
    "resolve": "按名称解析事件类型；未知类型抛出带名称的模式错误。",
    "validate_events": "逐个调用事件实例的模式校验，确保整个集合符合目录。",
    "literal": "根据 Python 常量推断或采用显式类型，构造字面量节点。",
    "symbol": "构造指定名称和类型的自由符号节点。",
    "event_field": "构造对事件字段或公共属性的带类型引用。",
    "unary": "构造一元表达式，并由节点初始化逻辑检查运算符与类型。",
    "binary": "构造二元表达式，并检查操作数兼容性和结果类型。",
    "nary": "把操作数冻结为元组后构造多元表达式并执行类型检查。",
    "call": "构造带函数名、参数和显式返回类型的调用表达式。",
    "expr_to_dict": "按表达式节点种类递归编码为带 `kind` 标签的字典。",
    "expr_from_dict": "读取 `kind` 标签并递归解析子表达式，重建带类型表达式 AST。",
    "_infer_literal_sort": "根据布尔、整数或字符串值推断字面量类型，拒绝其他 Python 类型。",
    "_require_bool": "要求表达式为布尔类型，否则抛出表达式类型错误。",
    "_require_numeric": "要求表达式为整数或位向量类型。",
    "_require_ordered": "要求表达式类型支持大小比较。",
    "_require_compatible": "要求两个表达式类型可直接比较或组合。",
    "iter_event_fields": "递归遍历表达式树并产出全部事件字段引用。",
    "iter_symbols": "递归遍历表达式树并产出全部自由符号。",
    "iter_literals": "递归遍历表达式树并产出全部字面量节点。",
    "substitute_event_ids": "递归重建表达式树，把角色形式的事件 ID 替换为具体事件 ID。",
    "conjunction": "用多元 `and` 组合表达式；空输入规范化为真。",
    "disjunction": "用多元 `or` 组合表达式；空输入规范化为假。",
    "compatible_with": "判断两个类型是否相同或是否属于允许直接组合的领域类型。",
    "accepts_literal": "按类型种类、位宽和符号规则检查 Python 字面量是否合法。",
    "bitvec": "构造指定宽度的无符号位向量类型。",
    "address": "构造指定宽度、名为 `address` 的领域位向量类型。",
    "value": "构造指定宽度、名为 `value` 的领域位向量类型。",
    "identifier": "构造字符串标识符类型。",
    "get": "按 ID 查找轨迹事件，未知 ID 时返回空值。",
    "events_of_type": "筛选并返回指定事件类型的全部轨迹事件。",
    "observations": "展开事件公共属性和字段，生成规范化的部分观测列表。",
    "_event_references": "递归遍历表达式，收集其中引用的事件 ID。",
    "role_map": "构造输入输出角色名到角色声明的映射。",
    "is_stateful": "判断转换是否声明了任何状态前置条件或状态更新。",
    "_validate_role_expression": "检查表达式中的事件引用只使用已声明角色，并核对字段存在且类型一致。",
    "_resolve_state": "按名称解析状态变量并校验声明存在。",
    "load_data": "按文件扩展名选择安全 YAML 或 JSON 解析器，并把解析错误包装为序列化错误。",
    "dump_data": "按扩展名选择 YAML 或 JSON，以稳定格式把数据写入目标文件。",
    "feasible": "判断公共补全结果是否为 `FEASIBLE`。",
    "_materialize_trace": "用求解赋值替换事件中的符号值，筛掉未发生事件，并附加补全元数据与状态见证。",
    "evaluate": "递归求值表达式；未知输入保留为 UNKNOWN，布尔运算使用可提前判定的三值短路语义。",
    "_all_equal": "判断序列内所有值是否相等；空序列和单元素序列视为相等。",
    "_same_block": "判断两个整数地址在给定块大小下是否属于同一块，并拒绝非法块大小。",
    "event_attribute": "解析事件公共属性或 `fields.<name>` 路径；缺失、未发生或未赋值时返回 UNKNOWN。",
    "_evaluate_binary": "实现二元比较、算术和布尔运算，并在未知操作数下遵循三值短路规则。",
    "_evaluate_nary": "实现多元合取、析取和全等，在部分未知时尽早得出可确定结果。",
    "solve_finite": "建立有限变量并按确定顺序深度优先搜索，利用部分求值剪枝，完整赋值时再检查状态语义。",
    "_build_variables": "收集事件和约束中的符号，合并类型要求并为每个符号构造有限候选域。",
    "_domain_for": "按符号类型和问题中出现的字面量生成确定、有限且包含必要值的搜索域。",
    "build_problem": "合并源轨迹与事件槽，物化部分事件，实例化全局约束和各转换绑定，形成统一有界问题。",
    "_instantiate_transformation": "枚举输入输出角色绑定并替换表达式；生成前向蕴含、exact 反向证明及状态条件和更新。",
    "event_map": "构造问题内事件 ID 到事件实例的映射。",
    "_role_bindings": "对每个角色筛选类型兼容事件，再计算无重复事件的笛卡尔绑定。",
    "_materialize_partial_event": "保留已观测字段，并为缺失的必填字段创建稳定命名、类型正确的符号。",
    "check_state_semantics": "按周期模拟共享前状态和原子更新，检查前置条件、写冲突和值类型并记录逐步变化。",
    "_valid_cycle": "把具体非负整数规范化为周期；其他值返回空结果。",
}


FIELD_LABELS = {
    "id": "对象的稳定标识符",
    "name": "对象或规则的稳定名称",
    "event_type": "关联的事件类型名称",
    "fields": "字段名到字段值或字段规则的映射",
    "metadata": "不参与核心语义的扩展元数据",
    "schema_version": "序列化模式版本",
    "description": "供人阅读的说明文本",
    "tags": "用于分类和筛选的标签集合",
    "sort": "值或表达式的静态类型",
    "status": "本次检查或求解的结果状态",
    "reason": "失败、未知或差异结果的原因",
    "events": "本对象管理的事件集合",
    "event_types": "事件类型定义或筛选集合",
    "constraints": "必须同时成立的表达式约束",
    "relations": "命名关系或参与运算的关系集合",
    "operations": "投影得到的内存操作序列",
    "assignment": "符号名到具体值的求解赋值",
    "cycle": "事件发生周期或诊断环",
    "occurs": "事件是否实际发生，未知时可由求解器决定",
    "annotations": "随对象保留的附加注解",
    "value": "该节点、字段或状态写入承载的值",
    "address": "内存访问地址",
    "hart": "执行该操作的硬件线程标识",
    "program_index": "操作在该硬件线程程序序中的位置",
    "initial": "持久状态单元的初始值",
    "width": "位向量的位宽",
    "signed": "位向量是否按有符号数解释",
    "required": "该候选或字段是否必须存在",
    "identity": "该字段是否参与事件身份判定",
    "partial": "轨迹是否允许包含未完全观测的信息",
    "backend": "实际使用的求解后端名称",
    "explored_nodes": "有限域搜索访问的节点数量",
    "initial_state": "状态模拟开始时的完整状态",
    "final_state": "状态模拟结束时的完整状态",
    "state_steps": "逐周期状态变化见证",
    "source_trace": "用于构造问题的原始部分轨迹",
    "catalog": "事件类型目录",
    "spec": "本次操作采用的模型配置",
    "graph": "当前被检查的候选执行图",
    "axioms": "逐条公理的检查结果或配置",
    "candidate_id": "候选执行图的稳定编号",
    "edges": "关系包含的有向边集合",
    "source": "有向边的起点",
    "target": "有向边的终点",
    "relation": "有向边所属的关系名",
    "abstract": "抽象轨迹的内存模型检查结果",
    "abstract_candidate_signatures": "抽象轨迹全部候选执行图的规范化签名",
    "abstraction": "采用的抽象规则名称或抽象配置",
    "activation": "决定该状态效果是否生效的布尔表达式",
    "active_requirements": "本周期实际生效的状态前置条件名称",
    "active_updates": "本周期实际生效的状态更新名称",
    "added_event_ids": "补全过程新增且最终发生的事件 ID",
    "at": "作为状态条件或更新时间锚点的事件角色",
    "axiom": "被检查公理的稳定名称",
    "before": "本周期更新执行前的完整状态",
    "after": "本周期原子更新后的完整状态",
    "before_write_id": "相干序边起点写操作的 ID",
    "after_write_id": "相干序边终点写操作的 ID",
    "candidates": "该轨迹枚举出的候选执行图检查结果",
    "certificate": "证明抽象结果来源的可重放证书",
    "changed_event_ids": "精化检查中载荷发生变化的事件 ID",
    "changes": "本周期真正发生值变化的状态单元记录",
    "co_hints": "从具体事件读取相干序提示的配置",
    "co_orders": "每个地址可采用的写操作全序候选",
    "commit_event_id": "证明读已经提交的源事件 ID",
    "completed_trace": "求解成功后物化出的完整轨迹",
    "concrete": "具体轨迹的内存模型检查结果",
    "concrete_candidate_signatures": "具体轨迹全部候选执行图的规范化签名",
    "condition": "条件表达式",
    "cycle_from": "提供摘要事件周期的源角色名",
    "default_action": "未被规则命中时对事件采取保留或丢弃的动作",
    "derived_relations": "按基础关系计算的命名派生关系规则",
    "distinct_events": "是否要求不同角色绑定到不同事件",
    "domain": "有限变量可枚举的具体值域",
    "dropped_constraint_count": "抽象过程中因引用隐藏事件而丢弃的约束数",
    "else_expr": "条件为假时选择的表达式",
    "ensure": "输入输出发生时必须满足的转换后置约束",
    "event_id": "关联事件的稳定 ID",
    "event_ids": "显式选择的事件 ID 集合",
    "expected": "状态比较条件右侧的期望表达式",
    "expression": "命名约束实际检查的表达式",
    "extra_event_ids": "给定抽象轨迹中不应出现的额外事件 ID",
    "field": "被事件字段表达式引用的字段或公共属性名",
    "field_sort": "被引用事件字段的静态类型",
    "functions": "表达式求值允许调用的纯函数映射",
    "hart_field": "投影时读取 hart 标识所用的事件字段名",
    "hidden_event_ids": "抽象过程中被摘要或规则隐藏的源事件 ID",
    "hide_sources": "生成摘要后是否隐藏参与匹配的源事件",
    "id_field": "投影时读取操作 ID 所用的事件字段名",
    "id_template": "使用绑定值生成摘要事件 ID 的格式模板",
    "init_write_event": "投影为初始写的事件类型名",
    "inputs": "转换的输入事件角色",
    "instantiated_constraint_count": "本次有界问题实例化出的约束总数",
    "is_literal": "当前匹配值是否应按字面量而非变量解释",
    "kind": "节点、操作、公理或输出值的类别",
    "left": "二元表达式的左操作数",
    "literal": "匹配模式直接要求的字面量",
    "literal_sort": "字面量表达式的静态类型",
    "load_commit_event": "用于确认读已提交的事件类型名",
    "load_event": "投影为读操作的事件类型名",
    "max_matches": "一条摘要规则最多允许采用的匹配数",
    "min_matches": "一条摘要规则至少必须找到的匹配数",
    "missing_event_ids": "期望抽象结果中缺失的事件 ID",
    "model": "内存模型的稳定名称",
    "offending_edges": "直接构成公理违例的关系边",
    "op": "表达式、关系或状态比较使用的运算符",
    "operand": "一元表达式的操作数",
    "operands": "多元表达式的操作数元组",
    "origin": "约束或状态效果的来源说明",
    "origins": "共同造成状态变化的更新来源集合",
    "output": "摘要规则生成的事件声明",
    "output_event_count": "抽象后输出轨迹的事件数量",
    "output_event_id": "该证据所证明的摘要事件 ID",
    "output_when": "控制各输出角色发生性的表达式映射",
    "outputs": "转换的输出事件角色",
    "path": "部分观测指向的公共属性或字段路径",
    "ppo_rules": "从程序序筛选保留程序序的操作种类规则",
    "preserved": "抽象是否保持候选图语义的最终判定",
    "preserved_constraint_count": "抽象后仍被保留的约束数量",
    "program_index_field": "投影时读取程序序位置所用的事件字段名",
    "projection": "具体事件到架构内存操作的投影配置",
    "read_id_field": "读源提示中保存读操作 ID 的字段名",
    "require_committed_loads": "是否只投影能够找到提交事件的读",
    "requirements": "一次转换实例化产生的状态前置条件",
    "retain": "抽象时显式保留事件的筛选配置",
    "retain_metadata": "是否把源轨迹元数据复制到抽象轨迹",
    "retained_event_ids": "抽象结果直接保留的源事件 ID",
    "return_sort": "函数调用表达式声明的返回类型",
    "rf_choices": "每个读操作允许选择的写操作 ID",
    "rf_hints": "从具体事件读取读源提示的配置",
    "right": "二元表达式的右操作数",
    "roles": "摘要规则需要共同匹配的事件角色",
    "rule": "生成摘要证据的规则名",
    "slot_ids": "由补全事件槽引入的问题事件 ID",
    "slots": "补全模型允许使用的有限候选事件槽",
    "source_event_count": "抽象输入轨迹的事件总数",
    "source_event_id": "该内存操作对应的源轨迹事件 ID",
    "source_event_ids": "生成一个摘要事件所使用的全部源事件 ID",
    "source_level": "抽象规则接受的源层级名称",
    "source_trace_sha256": "源轨迹规范化内容的 SHA-256 指纹",
    "state": "被条件或更新访问的状态变量名",
    "state_requirements": "转换声明的状态前置条件",
    "state_result": "完整赋值对应的状态语义检查结果",
    "state_updates": "转换声明的原子状态更新",
    "state_variables": "补全模型声明的持久状态单元",
    "steps": "按周期排列的状态模拟步骤",
    "store_event": "投影为普通写操作的事件类型名",
    "strict_order": "角色匹配周期是否必须严格递增",
    "summaries": "摘要规则或抽象证书中的摘要证据集合",
    "symbol_sort": "自由符号的静态类型",
    "target_level": "抽象规则产生的目标层级名称",
    "then_expr": "条件为真时选择的表达式",
    "trace": "抽象、补全或检查流程处理的轨迹",
    "transformations": "补全模型包含的操作转换规则",
    "updates": "一次转换实例化产生的状态更新",
    "variable": "字段统一匹配时绑定的变量名",
    "visibilities": "显式保留的事件可见性级别集合",
    "visibility": "事件类型的可见性级别",
    "when": "转换输入发生后需要满足的守卫表达式",
    "write_id": "读源提示指定的写操作 ID",
    "write_id_field": "读源提示中保存写操作 ID 的字段名",
}


ENUM_LABELS = {
    "ALLOWED": "内存模型允许该轨迹",
    "ARCHITECTURAL": "事件在架构层可见",
    "FEASIBLE": "补全问题存在可行见证",
    "FORBIDDEN": "内存模型禁止该轨迹",
    "INFEASIBLE": "补全问题不存在可行见证",
    "INIT_WRITE": "操作是初始内存写",
    "INTERNAL": "事件仅在模块内部可见",
    "PUBLIC": "事件可供模块外观察",
    "READ": "操作是内存读",
    "SAT": "有限问题可满足",
    "SATISFIED": "公理得到满足",
    "UNKNOWN": "后端未能确定结果",
    "UNSAT": "有限问题不可满足",
    "VIOLATED": "公理被违反",
    "WRITE": "操作是普通内存写",
}


TOKEN_LABELS = {
    "source": "源", "target": "目标", "event": "事件", "events": "事件集合",
    "field": "字段名", "fields": "字段集合", "write": "写操作", "read": "读操作",
    "before": "前置", "after": "后继", "initial": "初始", "final": "最终",
    "state": "状态", "requirements": "前置条件集合", "updates": "更新集合",
    "input": "输入", "inputs": "输入角色", "output": "输出", "outputs": "输出角色",
    "relation": "关系", "relations": "关系集合", "candidate": "候选", "candidates": "候选集合",
    "count": "数量", "ids": "标识符集合", "id": "标识符", "map": "映射",
    "rules": "规则集合", "rule": "规则", "model": "模型", "projection": "投影配置",
    "kind": "种类", "op": "运算符", "operands": "操作数集合", "operand": "操作数",
    "left": "左操作数", "right": "右操作数", "condition": "条件", "arguments": "参数集合",
    "function": "函数名", "return": "返回值", "literal": "字面量", "variable": "变量名",
    "roles": "角色集合", "role": "角色", "matches": "匹配数", "horizon": "求解周期上界",
    "module": "模块名", "layer": "层级名", "visibility": "可见性", "visibilities": "可见性集合",
    "ordered": "顺序匹配", "strict": "严格顺序", "distinct": "事件互异", "exact": "精确规则",
    "preserved": "保持性结果", "valid": "有效性结果", "feasible": "可行性结果",
}


@dataclass(frozen=True)
class Segment:
    title: str
    kind: str
    start: int
    end: int
    node: ast.AST | None = None
    owner: str | None = None
    names: tuple[str, ...] = ()


def node_start(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", ())
    return min([node.lineno, *(item.lineno for item in decorators)])


def assigned_names(node: ast.AST) -> list[str]:
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets.extend(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets.append(node.target)
    names: list[str] = []
    for target in targets:
        if isinstance(target, (ast.Name, ast.Attribute)):
            names.append(target.id if isinstance(target, ast.Name) else target.attr)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(item.id for item in target.elts if isinstance(item, ast.Name))
    return names


def class_segments(node: ast.ClassDef, start: int, end: int) -> list[Segment]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return [Segment(f"类 `{node.name}`", "class", start, end, node)]

    result: list[Segment] = []
    field_count = 0
    while field_count < len(body) and isinstance(body[field_count], (ast.Assign, ast.AnnAssign)):
        field_count += 1

    if field_count:
        field_nodes = body[:field_count]
        field_names = tuple(name for child in field_nodes for name in assigned_names(child))
        field_end = node_start(body[field_count]) - 1 if field_count < len(body) else end
        result.append(
            Segment(
                f"类 `{node.name}` 及全部字段",
                "class_fields",
                start,
                field_end,
                node,
                node.name,
                field_names,
            )
        )
    else:
        first = node_start(body[0])
        if start <= first - 1:
            result.append(Segment(f"类 `{node.name}` 定义", "class", start, first - 1, node))

    for index in range(field_count, len(body)):
        child = body[index]
        child_start = node_start(child)
        child_end = node_start(body[index + 1]) - 1 if index + 1 < len(body) else end
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            raise ValueError(f"{node.name} has a class field after a non-field statement")
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(Segment(f"方法 `{node.name}.{child.name}`", "method", child_start, child_end, child, node.name))
        else:
            result.append(Segment(f"类 `{node.name}` 的辅助声明", "class_body", child_start, child_end, child, node.name))
    return result


def module_segments(tree: ast.Module, line_count: int) -> list[Segment]:
    if not tree.body:
        return [Segment("空模块", "module", 1, line_count)] if line_count else []
    groups: list[tuple[list[ast.AST], str]] = []
    for node in tree.body:
        simple = isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if simple and groups and groups[-1][1] == "module":
            groups[-1][0].append(node)
        else:
            kind = "module" if simple else "node"
            groups.append(([node], kind))

    result: list[Segment] = []
    first_start = node_start(groups[0][0][0])
    if first_start > 1:
        result.append(Segment("模块前导内容", "module", 1, first_start - 1))
    for index, (nodes, kind) in enumerate(groups):
        start = node_start(nodes[0])
        end = node_start(groups[index + 1][0][0]) - 1 if index + 1 < len(groups) else line_count
        node = nodes[0]
        if kind == "module":
            result.append(Segment("模块说明与依赖", "module", start, end, node))
        elif isinstance(node, ast.ClassDef):
            result.extend(class_segments(node, start, end))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(Segment(f"函数 `{node.name}`", "function", start, end, node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = assigned_names(node)
            label = "、".join(f"`{name}`" for name in names) or "复杂赋值"
            result.append(Segment(f"模块变量 {label}", "module_field", start, end, node))
        else:
            result.append(Segment("模块执行逻辑", "module_code", start, end, node))
    return result


def field_description(name: str) -> str:
    if name in ENUM_LABELS:
        return f"定义枚举成员，表示{ENUM_LABELS[name]}"
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    if name.endswith("_field"):
        stem = name[:-6]
        return f"指定从事件中读取“{label_tokens(stem)}”时使用的字段名"
    if name.endswith("_count"):
        return f"记录{label_tokens(name[:-6])}的数量"
    if name.endswith("_ids"):
        return f"保存{label_tokens(name[:-4])}的稳定标识符集合"
    if name.startswith(("is_", "require_", "retain_", "hide_", "strict_", "distinct_")) or name in {
        "ordered", "exact", "signed", "valid", "feasible", "preserved",
    }:
        return f"控制或记录“{label_tokens(name)}”语义的布尔标志"
    return f"保存{label_tokens(name)}，供该对象的校验、转换或序列化逻辑使用"


def label_tokens(name: str) -> str:
    return "".join(TOKEN_LABELS.get(token, token) for token in name.lower().split("_"))


def generic_function_description(node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str | None) -> str:
    name = node.name
    subject = f"`{owner}` 实例" if owner else "当前模块"
    if name == "__post_init__":
        return f"在 `{owner}` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。"
    if name == "__repr__":
        return "返回该哨兵对象稳定且便于诊断的文本表示。"
    if name == "to_dict":
        return f"把 {subject} 的字段递归编码成可写入 YAML/JSON 的字典。"
    if name == "from_dict":
        return f"校验输入字典的键和值，并递归构造 `{owner}` 实例。"
    if name == "to_data":
        return f"把 `{owner}` 转回其紧凑配置表示，保留变量、引用和字面量的区别。"
    if name == "from_data":
        return f"识别紧凑配置值的形式并构造对应的 `{owner}`。"
    if name == "load":
        return f"从 YAML/JSON 路径读取数据并调用 `from_dict` 构造 `{owner}`。"
    if name == "dump":
        return f"调用 `to_dict` 后把 `{owner}` 安全写成 YAML/JSON。"
    if name == "sort":
        return "返回该表达式节点在构造时已经验证的静态类型。"
    if name.startswith("is_"):
        return f"检查 {subject} 是否满足“{label_tokens(name[3:])}”这一快速分类条件。"
    if name.startswith("validate") or name.startswith("_validate"):
        return f"检查 {subject} 的结构、引用与类型约束；发现不一致时抛出项目专用异常。"
    if name.startswith("check_"):
        return f"检查{label_tokens(name[6:])}，汇总布尔判定及必要的诊断信息。"
    if name.startswith("iter_"):
        return f"按确定顺序遍历并产出{label_tokens(name[5:])}，避免调用方复制中间集合。"
    if name.startswith("_build_") or name.startswith("build_"):
        stem = name.removeprefix("_").removeprefix("build_")
        return f"从输入配置和当前上下文构造{label_tokens(stem)}，同时执行必要校验。"
    if name.startswith("_materialize") or name.startswith("materialize"):
        return f"把声明式的{label_tokens(name.split('materialize', 1)[1].strip('_') or 'event')}转换成求解或输出使用的具体对象。"
    if name.startswith("_resolve") or name.startswith("resolve"):
        return f"根据名称、绑定或配置解析{label_tokens(name.split('resolve', 1)[1].strip('_') or 'value')}，非法引用会被拒绝。"
    if name.startswith("_concrete"):
        return "在值已经具体化时返回其 Python 值；仍是符号时拒绝或返回缺省结果。"
    if name.startswith("_unknown_keys"):
        return "计算输入映射中模式未声明的键，用于严格拒绝拼写错误和多余配置。"
    if name.startswith("encode_"):
        return f"把{label_tokens(name[7:])}递归编码为安全、可序列化的数据结构。"
    if name.startswith("decode_"):
        return f"从序列化数据识别并还原{label_tokens(name[7:])}。"
    if name.startswith("_infer_"):
        return f"根据具体 Python 值推断{label_tokens(name[7:])}，不支持的值会报类型错误。"
    if name.startswith("_require_"):
        return f"断言操作数满足{label_tokens(name[9:])}要求，否则报告表达式类型错误。"
    if name.startswith("to_"):
        return f"把 {subject} 转换为{label_tokens(name[3:])}表示。"
    if name.startswith("from_"):
        return f"校验输入并从{label_tokens(name[5:])}表示构造 {subject}。"
    if name.startswith("_"):
        return f"实现{label_tokens(name.strip('_'))}这一内部步骤，并为公开流程提供规范化结果。"
    return f"实现{label_tokens(name)}操作；按输入结构执行校验、转换并返回稳定结果。"


def explanation(segment: Segment) -> str:
    node = segment.node
    if segment.kind == "module":
        return "给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。"
    if segment.kind == "module_code":
        return "执行模块入口或少量装配逻辑，把控制权交给已定义的公共函数。"
    if segment.kind == "class_fields" and isinstance(node, ast.ClassDef):
        class_text = CLASS_DESCRIPTIONS.get(node.name, f"定义 `{node.name}` 数据类型，集中封装相关字段、不变量和操作。")
        details = "\n".join(f"- `{name}`：{field_description(name)}。" for name in segment.names)
        return f"{class_text}\n\n{details}"
    if segment.kind == "module_field" and node is not None:
        names = assigned_names(node)
        if not names:
            return "保存该声明对应的配置或运行期数据。"
        details = "；".join(f"`{name}` {field_description(name)}" for name in names)
        return f"这是模块级常量或公开导出声明：{details}。"
    if segment.kind == "class" and isinstance(node, ast.ClassDef):
        return CLASS_DESCRIPTIONS.get(node.name, f"定义 `{node.name}` 数据类型，集中封装相关字段、不变量和操作。")
    if segment.kind == "class_body":
        return f"这是 `{segment.owner}` 的辅助类体声明，用于表达文档、占位或嵌套定义。"
    if segment.kind in {"function", "method"} and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        exact = FUNCTION_DESCRIPTIONS.get(node.name)
        return exact or generic_function_description(node, segment.owner)
    return "保留该段模块结构，并为后续定义提供上下文。"


def render(source: Path) -> str:
    relative = source.relative_to(SOURCE_ROOT).as_posix()
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text, filename=str(source))
    segments = module_segments(tree, len(lines))

    output = [
        f"# `{relative}` 源码讲解\n\n",
        f"文件职责：{FILE_DESCRIPTIONS.get(relative, '实现 µMCM 的一个源码模块。')}下列代码块按原始行号连续排列，拼接后与源文件完全一致。\n\n",
    ]
    for segment in segments:
        output.append(f"## {segment.title}（第 {segment.start}–{segment.end} 行）\n\n")
        output.append("```python\n")
        code = "".join(lines[segment.start - 1 : segment.end])
        output.append(code)
        if code and not code.endswith("\n"):
            output.append("\n")
        output.append("```\n\n")
        output.append(explanation(segment) + "\n\n")
    return "".join(output)


def main() -> None:
    sources = sorted(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)
    expected: set[Path] = set()
    for source in sources:
        relative = source.relative_to(SOURCE_ROOT)
        destination = OUTPUT_ROOT / relative.with_suffix(relative.suffix + ".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render(source), encoding="utf-8")
        expected.add(destination)

    if OUTPUT_ROOT.exists():
        for stale in OUTPUT_ROOT.rglob("*.py.md"):
            if stale not in expected:
                stale.unlink()
    print(f"generated {len(sources)} explanation files in {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
