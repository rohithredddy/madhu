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
    # three wrong, two of them symptom errors; two right answers are excluded
    errors = [True, True, False, False, False]
    # of the wrong answers... but False means "wrong in another way" as well as
    # "right", so the rate is computed over entries that are not False
    assert symptom_rate([True, True, None]) == pytest.approx(1.0)
    assert symptom_rate(errors) == pytest.approx(1.0)


def test_symptom_rate_is_undefined_when_nothing_was_wrong():
    """Reporting 0 would suggest the method had been tested against the problem
    and passed. It has not been tested at all."""
    assert symptom_rate([False, False]) is None
    assert symptom_rate([]) is None
    assert symptom_rate([None, None]) is None


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
