from umcm.graph.relation import Relation, find_labeled_cycle


def test_relation_algebra_inverse_compose_and_closure() -> None:
    rf = Relation.from_edges("rf", [("W0", "R0"), ("W1", "R1")])
    co = Relation.from_edges("co", [("W0", "W1")])

    fr = rf.inverse("rf_inv").compose(co, name="fr")
    assert fr.edges == frozenset({("R0", "W1")})

    chain = Relation.from_edges("chain", [("a", "b"), ("b", "c")])
    assert chain.transitive_closure().edges == frozenset(
        {("a", "b"), ("b", "c"), ("a", "c")}
    )


def test_labeled_cycle_preserves_relation_names() -> None:
    cycle = find_labeled_cycle(
        [
            Relation.from_edges("rf", [("W", "R0")]),
            Relation.from_edges("ppo", [("R0", "R1")]),
            Relation.from_edges("fr", [("R1", "W")]),
        ]
    )
    assert cycle is not None
    assert {(edge.source, edge.relation, edge.target) for edge in cycle} == {
        ("W", "rf", "R0"),
        ("R0", "ppo", "R1"),
        ("R1", "fr", "W"),
    }
