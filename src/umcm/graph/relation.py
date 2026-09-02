"""Finite binary relations and small relation-algebra operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from umcm.errors import GraphError


Edge = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Relation:
    """A named finite binary relation over execution-graph node identifiers."""

    name: str
    edges: frozenset[Edge] = frozenset()

    def __post_init__(self) -> None:
        if not self.name:
            raise GraphError("relation name must be non-empty")
        for edge in self.edges:
            if len(edge) != 2 or not edge[0] or not edge[1]:
                raise GraphError(f"invalid edge in relation {self.name!r}: {edge!r}")

    @classmethod
    def from_edges(cls, name: str, edges: Iterable[Edge]) -> "Relation":
        return cls(name=name, edges=frozenset((str(a), str(b)) for a, b in edges))

    def contains(self, source: str, target: str) -> bool:
        return (source, target) in self.edges

    def sorted_edges(self) -> tuple[Edge, ...]:
        return tuple(sorted(self.edges))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "edges": [
                {"from": source, "to": target}
                for source, target in self.sorted_edges()
            ],
        }

    def inverse(self, name: str | None = None) -> "Relation":
        return Relation.from_edges(
            name or f"{self.name}^-1",
            ((target, source) for source, target in self.edges),
        )

    def union(self, *others: "Relation", name: str | None = None) -> "Relation":
        edges = set(self.edges)
        for relation in others:
            edges.update(relation.edges)
        return Relation.from_edges(name or self.name, edges)

    def intersection(self, other: "Relation", *, name: str | None = None) -> "Relation":
        return Relation.from_edges(name or self.name, self.edges & other.edges)

    def difference(self, other: "Relation", *, name: str | None = None) -> "Relation":
        return Relation.from_edges(name or self.name, self.edges - other.edges)

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


@dataclass(frozen=True, slots=True)
class LabeledEdge:
    source: str
    relation: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"from": self.source, "relation": self.relation, "to": self.target}


def union_relations(name: str, relations: Iterable[Relation]) -> Relation:
    edges: set[Edge] = set()
    for relation in relations:
        edges.update(relation.edges)
    return Relation.from_edges(name, edges)


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


def relation_map(relations: Iterable[Relation]) -> Mapping[str, Relation]:
    result: dict[str, Relation] = {}
    for relation in relations:
        if relation.name in result:
            raise GraphError(f"duplicate relation: {relation.name}")
        result[relation.name] = relation
    return result
