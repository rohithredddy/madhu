"""Tests for the call graph.

The direction convention is the thing most worth protecting here: an edge runs
from caller to callee, so ``children`` are the services a node calls and
``ancestors`` are the services that call it. If those ever swapped, the
dependency model would use the wrong features and the symptom-rate metric would
measure the opposite of what it claims, both without any test failing - unless
these do.
"""

import numpy as np
import pytest

from pare.columns import ColumnInfo
from pare.graph import CallGraph, Edge
from pare.synthetic import make_case

#   frontend -> checkout -> cart
#   frontend -> catalogue
#   checkout -> payment
TREE = [
    ("frontend", "checkout"),
    ("frontend", "catalogue"),
    ("checkout", "cart"),
    ("checkout", "payment"),
]


@pytest.fixture
def tree() -> CallGraph:
    return CallGraph.from_edges(TREE, source="STATIC_ARCHITECTURE")


# --- building ---------------------------------------------------------------


def test_from_edges_accepts_tuples_dicts_and_edges():
    """Tuples come from pare.synthetic, dicts come from the API."""
    from_tuples = CallGraph.from_edges([("a", "b")])
    from_dicts = CallGraph.from_dicts([{"from": "a", "to": "b"}])
    from_objects = CallGraph.from_edges([Edge("a", "b")])

    assert from_tuples.edges == from_dicts.edges == from_objects.edges
    assert from_tuples.children("a") == ("b",)


def test_the_json_form_round_trips():
    graph = CallGraph.from_edges(TREE)
    assert CallGraph.from_dicts(graph.to_dicts()).edges == graph.edges
    assert graph.to_dicts()[0] == {"from": "frontend", "to": "checkout"}


def test_duplicate_edges_are_collapsed():
    """Trace data records the same call over and over."""
    graph = CallGraph.from_edges([("a", "b"), ("a", "b"), ("a", "b")])
    assert len(graph.edges) == 1
    assert graph.children("a") == ("b",)


def test_a_self_loop_is_dropped():
    """A service that is its own child would let the dependency model predict it
    from its own values, which is the autoregressive leak step 3 forbids."""
    graph = CallGraph.from_edges([("a", "a"), ("a", "b")])
    assert graph.children("a") == ("b",)
    assert not graph.has_edge("a", "a")


def test_edge_order_is_preserved():
    graph = CallGraph.from_edges([("a", "z"), ("a", "b")])
    assert graph.children("a") == ("z", "b")


def test_source_is_recorded_and_checked():
    assert CallGraph.from_edges(TREE, source="TRACES").source == "TRACES"
    assert CallGraph.from_edges(TREE).source == "NONE"
    with pytest.raises(ValueError, match="graph source must be one of"):
        CallGraph.from_edges(TREE, source="guesswork")


def test_an_edge_needs_two_real_names():
    with pytest.raises(ValueError, match="non-empty string"):
        Edge("a", "")
    with pytest.raises(ValueError, match="exactly 2 items"):
        CallGraph.from_edges([("a", "b", "c")])
    with pytest.raises(ValueError, match="missing"):
        CallGraph.from_dicts([{"from": "a"}])


# --- the direction convention ----------------------------------------------


def test_children_are_the_services_this_one_calls(tree):
    assert tree.children("frontend") == ("checkout", "catalogue")
    assert tree.children("checkout") == ("cart", "payment")
    assert tree.children("cart") == ()


def test_parents_are_the_services_that_call_this_one(tree):
    assert tree.parents("checkout") == ("frontend",)
    assert tree.parents("cart") == ("checkout",)
    assert tree.parents("frontend") == ()


def test_ancestors_are_every_caller_up_the_chain(tree):
    """The services that can look broken while being fine."""
    assert set(tree.ancestors("cart")) == {"checkout", "frontend"}
    assert set(tree.ancestors("payment")) == {"checkout", "frontend"}
    assert tree.ancestors("frontend") == ()


def test_descendants_are_everything_this_one_reaches(tree):
    assert set(tree.descendants("frontend")) == {"checkout", "catalogue", "cart", "payment"}
    assert tree.descendants("cart") == ()


def test_a_fault_in_a_callee_can_only_be_felt_by_its_ancestors(tree):
    """The property the symptom-rate metric rests on. cart is called by checkout
    which is called by frontend, so those two can look bad because of cart;
    catalogue cannot."""
    affected = set(tree.ancestors("cart"))
    assert "catalogue" not in affected
    assert affected == {"checkout", "frontend"}


# --- messy graphs -----------------------------------------------------------


def test_an_unknown_service_gives_empty_answers_not_an_error():
    """A case often has data for services the graph does not mention."""
    graph = CallGraph.from_edges(TREE)
    assert graph.children("emailservice") == ()
    assert graph.parents("emailservice") == ()
    assert graph.ancestors("emailservice") == ()


def test_the_empty_graph_works():
    graph = CallGraph.empty()
    assert graph.is_empty
    assert graph.services == ()
    assert graph.children("anything") == ()
    assert graph.ancestors("anything") == ()
    assert graph.to_dicts() == []


def test_a_cycle_terminates():
    """Inferred graphs and real trace graphs both contain cycles."""
    graph = CallGraph.from_edges([("a", "b"), ("b", "c"), ("c", "a")])
    assert set(graph.ancestors("a")) == {"c", "b"}
    assert set(graph.descendants("a")) == {"b", "c"}
    # the service itself is never reported as its own ancestor
    assert "a" not in graph.ancestors("a")


def test_a_diamond_reports_each_service_once():
    #   top -> left -> bottom
    #   top -> right -> bottom
    graph = CallGraph.from_edges(
        [("top", "left"), ("top", "right"), ("left", "bottom"), ("right", "bottom")]
    )
    ancestors = graph.ancestors("bottom")
    assert sorted(ancestors) == ["left", "right", "top"]
    assert len(ancestors) == len(set(ancestors))


def test_services_lists_everything_mentioned(tree):
    assert set(tree.services) == {"frontend", "checkout", "catalogue", "cart", "payment"}


# --- inferring a graph from data -------------------------------------------


def columns_for(services, metrics=("latency",)):
    return [
        ColumnInfo(name=f"{service}_{metric}", service=service, metric=metric)
        for service in services
        for metric in metrics
    ]


def test_inferring_from_unrelated_noise_finds_almost_nothing():
    """Services that have nothing to do with each other must not be linked."""
    rng = np.random.default_rng(0)
    services = ["a", "b", "c", "d"]
    data = rng.normal(0.0, 1.0, size=(500, len(services)))

    graph = CallGraph.infer_from_correlation(data, columns_for(services))
    assert graph.source == "CORRELATION"
    assert len(graph.edges) == 0


def test_inferring_links_services_that_move_together():
    rng = np.random.default_rng(1)
    shared = rng.normal(0.0, 1.0, 500)
    callee = shared
    caller = shared + rng.normal(0.0, 0.3, 500)  # callee plus its own work
    unrelated = rng.normal(0.0, 1.0, 500)

    data = np.column_stack([caller, callee, unrelated])
    graph = CallGraph.infer_from_correlation(data, columns_for(["caller", "callee", "other"]))

    assert graph.has_edge("caller", "callee"), "the correlated pair was not linked"
    assert "other" not in graph.services or graph.children("other") == ()


def test_the_direction_falls_back_to_variance_when_there_is_no_lag_signal():
    """A caller's response time contains its callee's plus its own work, so it
    varies more. That is the only clue left when propagation is instantaneous."""
    rng = np.random.default_rng(2)
    callee = rng.normal(0.0, 1.0, 400)
    caller = callee + rng.normal(0.0, 0.5, 400)

    data = np.column_stack([caller, callee])
    graph = CallGraph.infer_from_correlation(data, columns_for(["caller", "callee"]))

    assert graph.has_edge("caller", "callee")
    assert not graph.has_edge("callee", "caller")


def test_max_children_limits_the_fan_out():
    rng = np.random.default_rng(3)
    shared = rng.normal(0.0, 1.0, 400)
    # one wide series and five narrow ones that all follow it
    series = [shared * 3.0] + [shared + rng.normal(0.0, 0.2, 400) for _ in range(5)]
    data = np.column_stack(series)
    names = ["hub", "a", "b", "c", "d", "e"]

    graph = CallGraph.infer_from_correlation(data, columns_for(names), max_children=2)
    assert len(graph.children("hub")) <= 2


def test_inference_only_uses_the_chosen_metric():
    rng = np.random.default_rng(4)
    shared = rng.normal(0.0, 1.0, 300)
    columns = [
        ColumnInfo("a_latency", "a", "latency"),
        ColumnInfo("a_mem", "a", "mem"),
        ColumnInfo("b_latency", "b", "latency"),
        ColumnInfo("b_mem", "b", "mem"),
    ]
    # latency correlates, memory does not
    data = np.column_stack(
        [
            shared * 2.0,
            rng.normal(0.0, 1.0, 300),
            shared + rng.normal(0.0, 0.2, 300),
            rng.normal(0.0, 1.0, 300),
        ]
    )

    on_latency = CallGraph.infer_from_correlation(data, columns, metric="latency")
    on_memory = CallGraph.infer_from_correlation(data, columns, metric="mem")

    assert len(on_latency.edges) == 1
    assert len(on_memory.edges) == 0


def test_inference_needs_at_least_two_usable_services():
    columns = [ColumnInfo("a_latency", "a", "latency")]
    data = np.arange(100.0).reshape(100, 1)
    assert CallGraph.infer_from_correlation(data, columns).is_empty


def test_a_flat_service_is_skipped():
    """A constant series correlates with nothing and would only add noise."""
    data = np.column_stack([np.full(200, 5.0), np.arange(200.0)])
    graph = CallGraph.infer_from_correlation(data, columns_for(["flat", "moving"]))
    assert graph.is_empty


def test_inference_checks_its_input_shape():
    columns = columns_for(["a", "b"])
    with pytest.raises(ValueError, match="rows by columns"):
        CallGraph.infer_from_correlation(np.zeros(10), columns)
    with pytest.raises(ValueError, match="but 2 were described"):
        CallGraph.infer_from_correlation(np.zeros((10, 3)), columns)


def test_inference_on_synthetic_data_recovers_some_of_the_real_tree():
    """An honest check against a graph we actually know.

    This is a rough heuristic by design - experiment E4 exists to measure how
    much a wrong graph costs - so the bar is "better than nothing", not "right".
    What must hold is that it finds real pairs rather than inventing them.
    """
    case = make_case(n_services=6, n_normal=600, propagation=0.9, seed=5)
    truth = {(caller, callee) for caller, callee in case.edges}
    undirected_truth = {frozenset(pair) for pair in truth}

    inferred = CallGraph.infer_from_correlation(
        case.normal.to_numpy(), case.columns, metric="latency"
    )
    assert inferred.source == "CORRELATION"

    found = {frozenset(edge.as_tuple()) for edge in inferred.edges}
    real_pairs = found & undirected_truth
    assert real_pairs, "inference found no real call at all"
    # most of what it proposes should be a genuine pair, not an invention
    assert len(real_pairs) / len(found) >= 0.5
