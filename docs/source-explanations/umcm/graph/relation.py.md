# `umcm/graph/relation.py` 源码讲解

文件职责：提供有限二元关系的关系代数与环检测。下列代码块按原始行号连续排列，拼接后与源文件完全一致。

## 模块说明与依赖（第 1–11 行）

```python
"""Finite binary relations and small relation-algebra operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from umcm.errors import GraphError


```

给出模块说明并导入本文件所需的标准库、项目类型和公开依赖；这里不执行核心业务流程。

## 模块变量 `Edge`（第 12–14 行）

```python
Edge = tuple[str, str]


```

这是模块级常量或公开导出声明：`Edge` 保存edge，供该对象的校验、转换或序列化逻辑使用。

## 类 `Relation` 及全部字段（第 15–21 行）

```python
@dataclass(frozen=True, slots=True)
class Relation:
    """A named finite binary relation over execution-graph node identifiers."""

    name: str
    edges: frozenset[Edge] = frozenset()

```

表示执行图节点标识符上的命名有限二元关系。

- `name`：对象或规则的稳定名称。
- `edges`：关系包含的有向边集合。

## 方法 `Relation.__post_init__`（第 22–28 行）

```python
    def __post_init__(self) -> None:
        if not self.name:
            raise GraphError("relation name must be non-empty")
        for edge in self.edges:
            if len(edge) != 2 or not edge[0] or not edge[1]:
                raise GraphError(f"invalid edge in relation {self.name!r}: {edge!r}")

```

在 `Relation` 构造后立即校验字段不变量，并把可规范化的数据转换成稳定表示。

## 方法 `Relation.from_edges`（第 29–32 行）

```python
    @classmethod
    def from_edges(cls, name: str, edges: Iterable[Edge]) -> "Relation":
        return cls(name=name, edges=frozenset((str(a), str(b)) for a, b in edges))

```

把任意边迭代器冻结成不可变集合并构造命名关系。

## 方法 `Relation.contains`（第 33–35 行）

```python
    def contains(self, source: str, target: str) -> bool:
        return (source, target) in self.edges

```

判断给定起点和终点是否构成当前关系中的边。

## 方法 `Relation.sorted_edges`（第 36–38 行）

```python
    def sorted_edges(self) -> tuple[Edge, ...]:
        return tuple(sorted(self.edges))

```

按起点、终点排序关系边，确保序列化和诊断结果可重现。

## 方法 `Relation.to_dict`（第 39–47 行）

```python
    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "edges": [
                {"from": source, "to": target}
                for source, target in self.sorted_edges()
            ],
        }

```

把 `Relation` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 方法 `Relation.inverse`（第 48–53 行）

```python
    def inverse(self, name: str | None = None) -> "Relation":
        return Relation.from_edges(
            name or f"{self.name}^-1",
            ((target, source) for source, target in self.edges),
        )

```

交换每条边的起点与终点，构造逆关系。

## 方法 `Relation.union`（第 54–59 行）

```python
    def union(self, *others: "Relation", name: str | None = None) -> "Relation":
        edges = set(self.edges)
        for relation in others:
            edges.update(relation.edges)
        return Relation.from_edges(name or self.name, edges)

```

合并两个关系的边集合。

## 方法 `Relation.intersection`（第 60–62 行）

```python
    def intersection(self, other: "Relation", *, name: str | None = None) -> "Relation":
        return Relation.from_edges(name or self.name, self.edges & other.edges)

```

保留两个关系共同包含的边。

## 方法 `Relation.difference`（第 63–65 行）

```python
    def difference(self, other: "Relation", *, name: str | None = None) -> "Relation":
        return Relation.from_edges(name or self.name, self.edges - other.edges)

```

删除另一个关系中出现的边。

## 方法 `Relation.compose`（第 66–77 行）

```python
    def compose(self, other: "Relation", *, name: str | None = None) -> "Relation":
        """Return relational composition ``self ; other``."""

        right_by_source: dict[str, set[str]] = defaultdict(set)
        for middle, target in other.edges:
            right_by_source[middle].add(target)
        edges: set[Edge] = set()
        for source, middle in self.edges:
            for target in right_by_source.get(middle, ()):
                edges.add((source, target))
        return Relation.from_edges(name or f"{self.name};{other.name}", edges)

```

连接当前关系的终点与另一关系的起点，计算关系复合。

## 方法 `Relation.transitive_closure`（第 78–104 行）

```python
    def transitive_closure(
        self,
        *,
        nodes: Iterable[str] = (),
        name: str | None = None,
    ) -> "Relation":
        all_nodes = set(nodes)
        adjacency: dict[str, set[str]] = defaultdict(set)
        for source, target in self.edges:
            all_nodes.add(source)
            all_nodes.add(target)
            adjacency[source].add(target)

        closure: set[Edge] = set()
        for source in sorted(all_nodes):
            stack = list(adjacency.get(source, ()))
            seen: set[str] = set()
            while stack:
                target = stack.pop()
                if target in seen:
                    continue
                seen.add(target)
                closure.add((source, target))
                stack.extend(adjacency.get(target, ()))
        return Relation.from_edges(name or f"{self.name}+", closure)


```

反复扩展可达边直至不再变化，计算有限关系的传递闭包。

## 类 `LabeledEdge` 及全部字段（第 105–110 行）

```python
@dataclass(frozen=True, slots=True)
class LabeledEdge:
    source: str
    relation: str
    target: str

```

为诊断环中的一条边附加关系名称。

- `source`：有向边的起点。
- `relation`：有向边所属的关系名。
- `target`：有向边的终点。

## 方法 `LabeledEdge.to_dict`（第 111–114 行）

```python
    def to_dict(self) -> dict[str, str]:
        return {"from": self.source, "relation": self.relation, "to": self.target}


```

把 `LabeledEdge` 实例 的字段递归编码成可写入 YAML/JSON 的字典。

## 函数 `union_relations`（第 115–121 行）

```python
def union_relations(name: str, relations: Iterable[Relation]) -> Relation:
    edges: set[Edge] = set()
    for relation in relations:
        edges.update(relation.edges)
    return Relation.from_edges(name, edges)


```

把一组关系的边合并成一个指定名称的关系。

## 函数 `find_labeled_cycle`（第 122–175 行）

```python
def find_labeled_cycle(relations: Sequence[Relation]) -> tuple[LabeledEdge, ...] | None:
    """Find one deterministic directed cycle across a union of relations.

    Relations are ordered by caller preference.  If the same edge belongs to
    multiple relations, the first relation name is used in the diagnostic.
    """

    labels: dict[Edge, str] = {}
    adjacency: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for relation in relations:
        for source, target in sorted(relation.edges):
            labels.setdefault((source, target), relation.name)
            adjacency[source].add(target)
            nodes.add(source)
            nodes.add(target)

    color: dict[str, int] = {node: 0 for node in nodes}
    stack: list[str] = []
    position: dict[str, int] = {}

    def dfs(node: str) -> tuple[LabeledEdge, ...] | None:
        color[node] = 1
        position[node] = len(stack)
        stack.append(node)
        for target in sorted(adjacency.get(node, ())):
            if color[target] == 0:
                found = dfs(target)
                if found is not None:
                    return found
            elif color[target] == 1:
                start = position[target]
                cycle_nodes = stack[start:] + [target]
                return tuple(
                    LabeledEdge(
                        source=cycle_nodes[index],
                        relation=labels[(cycle_nodes[index], cycle_nodes[index + 1])],
                        target=cycle_nodes[index + 1],
                    )
                    for index in range(len(cycle_nodes) - 1)
                )
        stack.pop()
        position.pop(node, None)
        color[node] = 2
        return None

    for node in sorted(nodes):
        if color[node] == 0:
            found = dfs(node)
            if found is not None:
                return found
    return None


```

按稳定节点和关系顺序做深度优先搜索，返回关系并集中的一条确定性标注环。

## 函数 `relation_map`（第 176–182 行）

```python
def relation_map(relations: Iterable[Relation]) -> Mapping[str, Relation]:
    result: dict[str, Relation] = {}
    for relation in relations:
        if relation.name in result:
            raise GraphError(f"duplicate relation: {relation.name}")
        result[relation.name] = relation
    return result
```

检查关系名称不重复后构造名称到关系的映射。

