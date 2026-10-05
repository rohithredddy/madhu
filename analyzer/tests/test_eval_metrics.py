"""Tests for the evaluation metrics.

These produce every number in the paper, so a wrong metric is worse than a wrong
engine: it would make a bad method look good and nobody would notice. The
expected values here are worked out by hand.
"""

import numpy as np
import pytest

from pare.columns import ColumnInfo
from pare.eval_metrics import (
    Rank,
    ac_at_k,
    avg_at_5,
    compactness,
    deletion_faithfulness,
    exp_ac_at_k,
    kendall_tau,
    random_deletion_baseline,
    rank_of,
    symptom_error,
    symptom_rate,
    system_anomaly_score,
    topk_jaccard,
)
from pare.graph import CallGraph

TREE = CallGraph.from_edges(
    [("frontend", "checkout"), ("checkout", "cart"), ("frontend", "catalogue")]
)


# --- ranks and ties ---------------------------------------------------------


def test_a_plain_rank_behaves_exactly_as_before():
    rank = Rank(best=3)
    assert rank.hit_fraction(1) == 0.0
    assert rank.hit_fraction(2) == 0.0
    assert rank.hit_fraction(3) == 1.0
    assert rank.hit_fraction(5) == 1.0


def test_a_tie_is_scored_as_the_chance_of_landing_in_the_top_k():
    """Settles open question 4.

    Five columns share first place, so the truth is one of five equally likely
    orderings. AC@1 is 1/5, not 1 and not 0 - which is what breaking the tie by
    column name would have given, depending on the name.
    """
    tied = Rank(best=1, tied=5)
    assert tied.hit_fraction(1) == pytest.approx(0.2)
    assert tied.hit_fraction(3) == pytest.approx(0.6)
    assert tied.hit_fraction(5) == pytest.approx(1.0)
    assert tied.hit_fraction(10) == pytest.approx(1.0)


def test_a_tie_group_further_down_the_list():
    # three items tie for ranks 4, 5 and 6
    tied = Rank(best=4, tied=3)
    assert tied.hit_fraction(3) == 0.0
    assert tied.hit_fraction(4) == pytest.approx(1 / 3)
    assert tied.hit_fraction(5) == pytest.approx(2 / 3)
    assert tied.hit_fraction(6) == pytest.approx(1.0)


def test_rank_of_finds_the_position_and_the_tie_size():
    scores = {"a": 9.0, "b": 5.0, "c": 5.0, "d": 1.0}
    assert rank_of(scores, "a") == Rank(best=1, tied=1)
    assert rank_of(scores, "b") == Rank(best=2, tied=2)
    assert rank_of(scores, "c") == Rank(best=2, tied=2)
    assert rank_of(scores, "d") == Rank(best=4, tied=1)


def test_rank_of_returns_nothing_when_the_target_was_never_scored():
    """A service whose columns were all dropped in cleaning was never given the
    chance, so docs/06 records an empty rank rather than a miss."""
    assert rank_of({"a": 1.0}, "missing") is None


def test_a_rank_must_be_sensible():
    with pytest.raises(ValueError, match="1-based"):
        Rank(best=0)
    with pytest.raises(ValueError, match="at least one item"):
        Rank(best=1, tied=0)


# --- AC@k and Avg@5 ---------------------------------------------------------


def test_ac_at_k_by_hand():
    ranks = [1, 1, 2, 5, None]  # four ranked, one never named
    assert ac_at_k(ranks, 1) == pytest.approx(2 / 5)
    assert ac_at_k(ranks, 2) == pytest.approx(3 / 5)
    assert ac_at_k(ranks, 5) == pytest.approx(4 / 5)


def test_an_unranked_case_counts_as_a_miss():
    assert ac_at_k([None, None], 10) == 0.0


def test_ac_at_k_of_nothing_is_zero_rather_than_an_error():
    assert ac_at_k([], 1) == 0.0


def test_avg_at_5_is_the_mean_of_ac_at_1_through_5():
    ranks = [1, 3]
    # AC@1 = .5, AC@2 = .5, AC@3 = 1, AC@4 = 1, AC@5 = 1
    assert avg_at_5(ranks) == pytest.approx((0.5 + 0.5 + 1 + 1 + 1) / 5)


def test_avg_at_5_rewards_being_close():
    assert avg_at_5([1]) == 1.0
    assert avg_at_5([5]) == pytest.approx(0.2)
    assert avg_at_5([6]) == 0.0


def test_exp_ac_at_k_is_the_same_arithmetic_on_indicator_ranks():
    ranks = [1, 4, None]
    assert exp_ac_at_k(ranks, 3) == ac_at_k(ranks, 3)


def test_ties_change_ac_at_k_in_the_way_the_decision_intends():
    """A method that cannot separate ten columns should not be credited as if it
    had put the right one first."""
    confident = [Rank(best=1, tied=1)]
    saturated = [Rank(best=1, tied=10)]

    assert ac_at_k(confident, 1) == 1.0
    assert ac_at_k(saturated, 1) == pytest.approx(0.1)
    # but both are certain to have it inside the top ten
    assert ac_at_k(saturated, 10) == pytest.approx(1.0)


# --- symptom error ----------------------------------------------------------


def test_blaming_a_caller_of_the_culprit_is_a_symptom_error():
    # cart is the culprit; checkout and frontend both call it
    assert symptom_error("checkout", "cart", TREE) is True
    assert symptom_error("frontend", "cart", TREE) is True


def test_being_right_is_not_an_error():
    assert symptom_error("cart", "cart", TREE) is False


def test_blaming_something_unrelated_is_wrong_but_not_a_symptom_error():
    """catalogue does not call cart, so getting it wrong this way is a different
    kind of mistake and must not inflate the symptom rate."""
    assert symptom_error("catalogue", "cart", TREE) is False


def test_without_a_graph_we_cannot_tell():
    """docs/06 section 5 records this as empty, not as False. Saying False would
    understate the problem."""
    assert symptom_error("checkout", "cart", None) is None
    assert symptom_error("checkout", "cart", CallGraph.empty()) is None


def test_symptom_rate_counts_only_the_wrong_answers():
    """`docs/08` section 4: symptom errors divided by wrong top-1 answers.

    This test previously asserted 1.0 here, which was wrong, and its own comment
    admitted why: `symptom_error` returns False both for "right" and for "wrong in
    an unrelated way", and the old implementation treated "not False" as wrong,
    which left only the True values and made the rate 1.0 whenever any symptom
    error existed. The test had been written to match the code rather than the
    spec. Both are fixed; the rate now needs the correctness of each answer.
    """
    # Five cases: two symptom errors, one wrong in an unrelated way, two right.
    errors = [True, True, False, False, False]
    correct = [False, False, False, True, True]
    assert symptom_rate(errors, correct) == pytest.approx(2 / 3)


def test_symptom_rate_ignores_cases_with_no_graph():
    errors = [True, None, False]
    correct = [False, False, False]
    # The None case is dropped from both parts of the fraction, leaving one symptom
    # error out of two judged wrong answers.
    assert symptom_rate(errors, correct) == pytest.approx(0.5)


def test_symptom_rate_is_undefined_when_nothing_was_wrong():
    """Reporting 0 would suggest the method had been tested against the problem
    and passed. It has not been tested at all."""
    assert symptom_rate([False, False], [True, True]) is None
    assert symptom_rate([], []) is None
    assert symptom_rate([None, None], [False, False]) is None


def test_symptom_rate_refuses_mismatched_inputs():
    """A silent zip would pair the wrong flags with the wrong cases."""
    with pytest.raises(ValueError):
        symptom_rate([True, False], [False])


# --- the deletion test ------------------------------------------------------


def deletion_fixture(seed=0):
    """Three columns; only the second is really anomalous."""
    rng = np.random.default_rng(seed)
    normal = rng.normal(0.0, 1.0, (300, 3))
    abnormal = rng.normal(0.0, 1.0, (100, 3))
    abnormal[:, 1] += 12.0
    columns = [
        ColumnInfo("a_cpu", "a", "cpu"),
        ColumnInfo("b_cpu", "b", "cpu"),
        ColumnInfo("c_cpu", "c", "cpu"),
    ]
    return normal, abnormal, columns


def test_the_system_score_notices_an_anomaly():
    normal, abnormal, _ = deletion_fixture()
    quiet = np.random.default_rng(1).normal(0.0, 1.0, (100, 3))

    assert system_anomaly_score(normal, abnormal) > 5.0
    assert system_anomaly_score(normal, quiet) < 5.0


def test_naming_the_real_column_first_makes_the_anomaly_vanish():
    normal, abnormal, columns = deletion_fixture()
    good = deletion_faithfulness(normal, abnormal, columns, ["b_cpu", "a_cpu", "c_cpu"])

    assert good.normalised[0] == pytest.approx(1.0)
    assert good.normalised[1] < 0.4, "removing the true column should collapse the score"
    assert good.auc < 0.5


def test_naming_the_wrong_columns_first_leaves_the_anomaly_in_place():
    """The kind of explanation this test exists to catch: plausible columns that
    had nothing to do with it."""
    normal, abnormal, columns = deletion_fixture()
    good = deletion_faithfulness(normal, abnormal, columns, ["b_cpu", "a_cpu", "c_cpu"])
    bad = deletion_faithfulness(normal, abnormal, columns, ["a_cpu", "c_cpu", "b_cpu"])

    assert bad.auc > good.auc, "a faithful explanation must have the smaller area"
    assert bad.normalised[1] == pytest.approx(1.0, abs=0.15)


def test_the_curve_has_one_point_per_k_and_stops_changing_when_the_list_runs_out():
    normal, abnormal, columns = deletion_fixture()
    curve = deletion_faithfulness(normal, abnormal, columns, ["b_cpu"], max_k=6)

    assert len(curve.scores) == 7
    # only one column was named, so nothing changes after the first removal
    assert curve.scores[1:] == pytest.approx([curve.scores[1]] * 6)


def test_the_random_baseline_sits_between_a_good_and_a_bad_explanation():
    """Without it the area means nothing: whether 0.4 is good depends on what
    chance would have scored."""
    normal, abnormal, columns = deletion_fixture()
    good = deletion_faithfulness(normal, abnormal, columns, ["b_cpu", "a_cpu", "c_cpu"]).auc
    chance = random_deletion_baseline(normal, abnormal, columns, repeats=10, seed=42)

    assert good < chance


def test_the_random_baseline_is_reproducible():
    normal, abnormal, columns = deletion_fixture()
    first = random_deletion_baseline(normal, abnormal, columns, seed=7)
    second = random_deletion_baseline(normal, abnormal, columns, seed=7)
    assert first == pytest.approx(second)


def test_an_unknown_column_in_a_ranking_is_ignored():
    normal, abnormal, columns = deletion_fixture()
    curve = deletion_faithfulness(
        normal, abnormal, columns, ["not_a_column", "b_cpu"], max_k=3
    )
    assert np.isfinite(curve.auc)


# --- stability --------------------------------------------------------------


def test_jaccard_by_hand():
    assert topk_jaccard(["a", "b", "c"], ["a", "b", "c"], 3) == pytest.approx(1.0)
    assert topk_jaccard(["a", "b"], ["c", "d"], 2) == pytest.approx(0.0)
    # {a,b,c} against {b,c,d}: two shared, four distinct
    assert topk_jaccard(["a", "b", "c"], ["b", "c", "d"], 3) == pytest.approx(0.5)


def test_jaccard_only_looks_at_the_top_k():
    assert topk_jaccard(["a", "x", "y"], ["a", "p", "q"], 1) == pytest.approx(1.0)


def test_jaccard_of_two_empty_lists_is_one():
    assert topk_jaccard([], [], 5) == 1.0


def test_jaccard_rejects_a_nonsense_k():
    with pytest.raises(ValueError, match="at least 1"):
        topk_jaccard(["a"], ["a"], 0)


def test_kendall_tau_on_identical_and_reversed_orders():
    order = ["a", "b", "c", "d"]
    assert kendall_tau(order, order) == pytest.approx(1.0)
    assert kendall_tau(order, list(reversed(order))) == pytest.approx(-1.0)


def test_kendall_tau_is_undefined_with_fewer_than_two_shared_services():
    assert kendall_tau(["a"], ["a"]) is None
    assert kendall_tau(["a", "b"], ["c", "d"]) is None


def test_kendall_tau_uses_only_the_services_both_lists_contain():
    assert kendall_tau(["a", "b", "zzz"], ["a", "b"]) == pytest.approx(1.0)


# --- compactness ------------------------------------------------------------


def test_compactness_by_hand():
    # one column holds 80 percent of the mass on its own
    assert compactness({"a": 8.0, "b": 1.0, "c": 1.0}) == 1
    # four equal columns need four to reach 80 percent (three give 75)
    assert compactness({"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}) == 4


def test_compactness_ignores_non_positive_scores():
    assert compactness({"a": 8.0, "b": 0.0, "c": -3.0, "d": 2.0}) == 1


def test_compactness_of_nothing_is_zero():
    assert compactness({}) == 0
    assert compactness({"a": 0.0}) == 0


def test_compactness_fraction_is_checked():
    with pytest.raises(ValueError, match="between 0 and 1"):
        compactness({"a": 1.0}, fraction=0.0)


# --- ground truth lives only here ------------------------------------------


def test_the_metrics_are_the_only_place_ground_truth_appears():
    """Hard rule 4. The engines take ground truth nowhere; the metrics take it as
    an argument. Keeping them in separate modules makes that checkable."""
    import inspect

    from pare import engine

    source = inspect.getsource(engine)
    for forbidden in ("gt_service", "gt_column", "ground_truth"):
        assert forbidden not in source, f"{forbidden} must not appear in engine.py"


# --- ranking by what the engine actually answered ---------------------------


def test_rank_in_order_respects_a_traversal_that_overrode_the_scores():
    """PARE's graph traversal promotes the service the walk ends at, even when a
    caller scores higher - that is the step working, not failing.

    Scoring from the raw numbers instead would mark the engine wrong exactly when
    it followed the graph past a loud symptom to the real source. This was a bug
    in the first version of the M1 gate script and it cost PARE 0.24 of accuracy
    on cpu faults.
    """
    from pare.eval_metrics import rank_in_order

    order = ["svc-07", "frontend", "svc-04"]
    scores = {"svc-07": 4.00, "frontend": 5.07, "svc-04": 1.32}

    assert rank_in_order(order, scores, "svc-07").best == 1
    # re-deriving from scores would have said 2
    assert rank_of(scores, "svc-07").best == 2


def test_rank_in_order_still_honours_a_genuine_tie():
    from pare.eval_metrics import rank_in_order

    order = ["a", "b", "c", "d"]
    scores = {"a": 6.0, "b": 6.0, "c": 6.0, "d": 1.0}

    rank = rank_in_order(order, scores, "b")
    assert (rank.best, rank.tied) == (1, 3)
    assert rank.hit_fraction(1) == pytest.approx(1 / 3)


def test_rank_in_order_counts_only_neighbours_that_share_a_score():
    """A tie the engine's ordering has already separated on other grounds is not
    a tie: only an unbroken run of equal scores counts."""
    from pare.eval_metrics import rank_in_order

    order = ["a", "b", "c"]
    scores = {"a": 5.0, "b": 3.0, "c": 5.0}  # a and c share, but b sits between

    assert rank_in_order(order, scores, "a").tied == 1
    assert rank_in_order(order, scores, "c").tied == 1


def test_rank_in_order_returns_nothing_for_a_service_that_was_not_ranked():
    from pare.eval_metrics import rank_in_order

    assert rank_in_order(["a"], {"a": 1.0}, "missing") is None


# --- rank-1 ties in the symptom rate (M3.2) ----------------------------------
#
# A chain a -> b -> c (a calls b, b calls c), plus an unrelated d. With c the
# culprit, a and b are its callers: blaming either is a symptom error, blaming d
# is a plain mistake.


def _chain() -> CallGraph:
    return CallGraph.from_edges([("a", "b"), ("b", "c")])


def test_top_tie_group_is_the_leading_run_of_equal_scores():
    from pare.eval_metrics import top_tie_group

    assert top_tie_group(["a", "b", "c"], {"a": 6.0, "b": 6.0, "c": 2.0}) == ("a", "b")
    assert top_tie_group(["a", "b"], {"a": 6.0, "b": 5.0}) == ("a",)
    assert top_tie_group([], {}) == ()


def test_top_tie_group_respects_an_order_the_engine_already_broke():
    """PARE's traversal can list a lower score first. Equal scores further down,
    separated by a different one, are not tied with the leader - the same rule as
    rank_in_order."""
    from pare.eval_metrics import top_tie_group

    assert top_tie_group(["c", "a", "b"], {"c": 4.0, "a": 6.0, "b": 4.0}) == ("c",)


def test_symptom_share_is_the_fraction_of_the_tie_that_calls_the_culprit():
    from pare.eval_metrics import symptom_share

    graph = _chain()
    assert symptom_share(("a", "d"), "c", graph) == pytest.approx(0.5)
    assert symptom_share(("a", "b", "c", "d"), "c", graph) == pytest.approx(0.5)
    # With no tie it is symptom_error as a number.
    assert symptom_share(("b",), "c", graph) == 1.0
    assert symptom_share(("d",), "c", graph) == 0.0
    # The culprit is never its own caller, so a right answer contributes nothing.
    assert symptom_share(("c",), "c", graph) == 0.0


def test_symptom_share_is_none_without_a_graph():
    from pare.eval_metrics import symptom_share

    assert symptom_share(("a",), "c", None) is None
    assert symptom_share(("a",), "c", CallGraph.empty()) is None


def test_expected_symptom_rate_equals_the_plain_rate_when_nothing_ties():
    """The tie rule must change nothing for a method whose scores are distinct,
    exactly as decision 47's rule changes nothing for AC@k."""
    from pare.eval_metrics import expected_symptom_rate

    errors = [False, False, True, False, True, None]
    correct = [True, False, False, False, False, False]
    shares = [None if e is None else (1.0 if e else 0.0) for e in errors]
    wrong = [0.0 if c else 1.0 for c in correct]
    assert expected_symptom_rate(shares, wrong) == pytest.approx(
        symptom_rate(errors, correct)
    )


def test_expected_symptom_rate_does_not_depend_on_how_tied_services_are_named():
    """The defect it exists to remove. Two cases, each a tie between a caller of
    the culprit and an unrelated service. Whichever is listed first, the plain rate
    swings between 0 and 1; the expected rate is 0.5 either way."""
    from pare.eval_metrics import expected_symptom_rate, symptom_error, symptom_share

    graph = _chain()
    for order in (("a", "d"), ("d", "a")):
        plain = symptom_rate(
            [symptom_error(order[0], "c", graph)] * 2, [False, False]
        )
        assert plain in (0.0, 1.0)
        share = symptom_share(order, "c", graph)
        assert expected_symptom_rate([share, share], [1.0, 1.0]) == pytest.approx(0.5)


def test_expected_symptom_rate_counts_a_tie_containing_the_culprit_as_part_wrong():
    """A tie of three with the culprit in it is wrong two times in three, and the
    one caller in it is blamed one time in three - a rate of 1/2, not 1/3."""
    from pare.eval_metrics import expected_symptom_rate, symptom_share

    share = symptom_share(("b", "c", "d"), "c", _chain())
    assert share == pytest.approx(1 / 3)
    assert expected_symptom_rate([share], [2 / 3]) == pytest.approx(0.5)


def test_expected_symptom_rate_is_none_over_nothing():
    from pare.eval_metrics import expected_symptom_rate

    assert expected_symptom_rate([0.0, 0.0], [0.0, 0.0]) is None
    assert expected_symptom_rate([None, None], [1.0, 1.0]) is None
    assert expected_symptom_rate([], []) is None


def test_symptom_chance_is_the_share_of_other_services_that_call_the_culprit():
    from pare.eval_metrics import symptom_chance

    graph = _chain()
    # Other than c: a and b call it, d does not.
    assert symptom_chance(["a", "b", "c", "d"], "c", graph) == pytest.approx(2 / 3)
    # Nothing calls a, the root.
    assert symptom_chance(["a", "b", "c", "d"], "a", graph) == 0.0
    assert symptom_chance(["c"], "c", graph) is None
    assert symptom_chance(["a", "c"], "c", None) is None
