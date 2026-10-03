"""Tests for ranking, the verdict and the roles.

The roles are what the explanation text and the call-graph colours are built
from, so a wrong role is a wrong answer shown confidently to a user. The
precedence rule is tested directly rather than through an engine.
"""

import pytest

from pare.config import PareConfig
from pare.graph import CallGraph
from pare.rank import (
    ALSO_ABNORMAL,
    CAUSE,
    NO_CLEAR_CAUSE,
    NORMAL,
    ROOT_CAUSE_FOUND,
    SYMPTOM,
    rank_all,
    rank_indicators,
    traversal_rank,
)
from pare.residual import ColumnResidual


def residual(service, metric, self_score, marginal=None, inherited=0.0, explained_by=None):
    return ColumnResidual(
        column=f"{service}_{metric}",
        service=service,
        metric=metric,
        self_score=self_score,
        marginal_score=marginal if marginal is not None else self_score,
        inherited_fraction=inherited,
        explained_by=explained_by,
        modelled=explained_by is not None,
    )


# --- service scores ---------------------------------------------------------


def test_a_service_is_as_bad_as_its_worst_metric():
    ranking = rank_all([residual("a", "cpu", 1.0), residual("a", "mem", 7.0)])
    assert ranking.services[0].score == pytest.approx(7.0)


def test_top2mean_averages_the_worst_two():
    items = [residual("a", "cpu", 8.0), residual("a", "mem", 6.0), residual("a", "net", 1.0)]
    ranking = rank_all(items, config=PareConfig(service_agg="top2mean", traversal=False))
    assert ranking.services[0].score == pytest.approx(7.0)


def test_services_come_back_worst_first():
    ranking = rank_all(
        [residual("quiet", "cpu", 1.0), residual("loud", "cpu", 9.0), residual("mid", "cpu", 5.0)],
        config=PareConfig(traversal=False),
    )
    assert [s.service for s in ranking.services] == ["loud", "mid", "quiet"]
    assert [s.rank for s in ranking.services] == [1, 2, 3]


def test_the_top_indicator_is_the_services_worst_column():
    ranking = rank_all([residual("a", "cpu", 2.0), residual("a", "mem", 9.0)])
    assert ranking.services[0].top_indicator == "a_mem"
    assert ranking.top_indicator == "a_mem"


# --- the verdict ------------------------------------------------------------


def test_a_clear_leader_gives_root_cause_found():
    ranking = rank_all([residual("a", "cpu", 9.0), residual("b", "cpu", 1.0)])
    assert ranking.verdict == ROOT_CAUSE_FOUND
    assert ranking.services[0].role == CAUSE


def test_a_quiet_window_gives_no_clear_cause_and_nobody_is_accused():
    """The method must be able to say "I see nothing" instead of always accusing
    whoever came first."""
    ranking = rank_all([residual("a", "cpu", 1.2), residual("b", "cpu", 0.4)])

    assert ranking.verdict == NO_CLEAR_CAUSE
    assert all(s.role != CAUSE for s in ranking.services)
    # the ranking is still returned, as the best guess available
    assert ranking.services[0].service == "a"


def test_the_threshold_is_configurable():
    items = [residual("a", "cpu", 2.0)]
    assert rank_all(items, config=PareConfig(min_cause_score=1.0)).verdict == ROOT_CAUSE_FOUND
    assert rank_all(items, config=PareConfig(min_cause_score=5.0)).verdict == NO_CLEAR_CAUSE


# --- roles, in strict precedence -------------------------------------------


def test_a_service_whose_trouble_its_callees_explain_is_a_symptom():
    ranking = rank_all(
        [
            residual("cause", "mem", 9.0),
            residual("victim", "latency", 1.0, marginal=6.0, inherited=0.9, explained_by="cause"),
        ],
        config=PareConfig(traversal=False),
    )
    by_name = {s.service: s for s in ranking.services}

    assert by_name["cause"].role == CAUSE
    assert by_name["victim"].role == SYMPTOM
    assert by_name["victim"].explained_by == "cause"


def test_an_abnormal_service_its_callees_do_not_explain_is_also_abnormal():
    """Not a symptom: it moved, and nothing downstream accounts for it. Possibly a
    second, separate problem."""
    ranking = rank_all(
        [
            residual("cause", "mem", 9.0),
            residual("other", "cpu", 5.0, marginal=6.0, inherited=0.1),
        ],
        config=PareConfig(traversal=False),
    )
    by_name = {s.service: s for s in ranking.services}
    assert by_name["other"].role == ALSO_ABNORMAL


def test_a_quiet_service_is_normal():
    ranking = rank_all(
        [residual("cause", "mem", 9.0), residual("calm", "cpu", 0.2, marginal=0.3)],
        config=PareConfig(traversal=False),
    )
    by_name = {s.service: s for s in ranking.services}
    assert by_name["calm"].role == NORMAL


def test_symptom_needs_both_conditions():
    """High inherited fraction is not enough on its own: a service that barely
    moved is not a symptom of anything."""
    ranking = rank_all(
        [
            residual("cause", "mem", 9.0),
            residual("barely", "cpu", 0.1, marginal=0.5, inherited=0.99),
        ],
        config=PareConfig(traversal=False),
    )
    by_name = {s.service: s for s in ranking.services}
    assert by_name["barely"].role == NORMAL


def test_when_there_is_no_clear_cause_the_leader_falls_through_to_another_role():
    ranking = rank_all(
        [residual("a", "cpu", 1.0, marginal=4.0, inherited=0.9, explained_by="b")],
        config=PareConfig(traversal=False),
    )
    assert ranking.verdict == NO_CLEAR_CAUSE
    assert ranking.services[0].role == SYMPTOM


def test_every_service_has_exactly_one_role():
    ranking = rank_all(
        [
            residual("a", "cpu", 9.0),
            residual("b", "cpu", 1.0, marginal=6.0, inherited=0.9),
            residual("c", "cpu", 5.0, marginal=5.0),
            residual("d", "cpu", 0.1),
        ],
        config=PareConfig(traversal=False),
    )
    roles = [s.role for s in ranking.services]
    assert len(roles) == 4
    assert all(role in {CAUSE, SYMPTOM, ALSO_ABNORMAL, NORMAL} for role in roles)


# --- traversal --------------------------------------------------------------


def test_traversal_walks_from_the_loudest_service_down_to_the_real_source():
    """Start where the noise is - usually a symptom - and follow callees while
    their self-scores keep rising. Walking down the graph means walking back
    towards the source, because a fault travels up."""
    graph = CallGraph.from_edges([("frontend", "checkout"), ("checkout", "cart")])
    scores = {"frontend": 2.0, "checkout": 4.0, "cart": 7.0}
    marginals = {"frontend": 9.0, "checkout": 6.0, "cart": 7.0}

    order = traversal_rank(["cart", "checkout", "frontend"], scores, marginals, graph)
    assert order[0] == "cart"


def test_traversal_stops_when_no_callee_is_worse():
    graph = CallGraph.from_edges([("frontend", "checkout"), ("checkout", "cart")])
    scores = {"frontend": 9.0, "checkout": 2.0, "cart": 1.0}
    marginals = {"frontend": 9.0, "checkout": 2.0, "cart": 1.0}

    order = traversal_rank(["frontend", "checkout", "cart"], scores, marginals, graph)
    assert order[0] == "frontend"


def test_traversal_terminates_on_a_cycle():
    graph = CallGraph.from_edges([("a", "b"), ("b", "c"), ("c", "a")])
    scores = {"a": 1.0, "b": 2.0, "c": 3.0}
    order = traversal_rank(["c", "b", "a"], scores, dict(scores), graph)
    assert sorted(order) == ["a", "b", "c"]


def test_traversal_keeps_every_service_exactly_once():
    graph = CallGraph.from_edges([("a", "b"), ("b", "c")])
    scores = {"a": 1.0, "b": 5.0, "c": 9.0}
    order = traversal_rank(["c", "b", "a"], scores, dict(scores), graph)
    assert sorted(order) == ["a", "b", "c"]
    assert len(order) == len(set(order))


def test_traversal_can_be_switched_off():
    graph = CallGraph.from_edges([("frontend", "cart")])
    items = [
        residual("frontend", "latency", 2.0, marginal=9.0),
        residual("cart", "mem", 7.0, marginal=7.0),
    ]
    without = rank_all(items, graph, PareConfig(traversal=False))
    assert without.services[0].service == "cart"  # plain sort by self-score


# --- indicators -------------------------------------------------------------


def test_indicators_are_worst_first_and_cut_to_top_k():
    items = [residual("s", f"m{i}", float(i)) for i in range(20)]
    ranked = rank_indicators(items, top_k=5)

    assert len(ranked) == 5
    assert [i.self_score for i in ranked] == [19.0, 18.0, 17.0, 16.0, 15.0]
    assert [i.rank for i in ranked] == [1, 2, 3, 4, 5]


def test_indicator_order_is_stable_when_scores_tie():
    items = [residual("s", "z", 1.0), residual("s", "a", 1.0)]
    assert [i.column for i in rank_indicators(items, 10)] == ["s_a", "s_z"]


def test_the_metric_comes_from_the_column_map_not_from_the_name():
    """pare.columns forbids recovering meaning from a column name."""
    odd = ColumnResidual(
        column="col_17",
        service="payment",
        metric="memory_working_set_bytes",
        self_score=5.0,
        marginal_score=5.0,
        inherited_fraction=0.0,
        explained_by=None,
        modelled=False,
    )
    assert rank_indicators([odd], 10)[0].metric == "memory_working_set_bytes"


# --- nothing to rank --------------------------------------------------------


def test_an_empty_input_gives_no_clear_cause():
    ranking = rank_all([])
    assert ranking.verdict == NO_CLEAR_CAUSE
    assert ranking.services == ()
    assert ranking.indicators == ()
    assert ranking.top_service is None
