"""Tests for the re-implementation of RCAEval's two scoring formulas.

The re-implementation exists so that M2.4 can change one thing at a time between
their setup and ours (see `run_m24_compare.py`). It is only worth anything if it
really is their formula, so these tests pin the three things about it that are
easy to get wrong, plus the sort, which is where their method is at its most
surprising.

The strongest check is not here: `run_m24_compare.py` compares the
re-implementation against their package's actual output on all 125 cases and
prints the agreement. These tests cover the pieces that a case-level comparison
would only tell you about indirectly.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.preprocessing import RobustScaler, StandardScaler

from experiments.baseline_formulas import (
    count_non_finite,
    our_nsigma_scores,
    rcaeval_scores,
    their_sort,
)


def test_nsigma_is_the_largest_signed_z_of_any_row():
    """Their score is `max(zscores)`: one row is enough, and the sign matters."""
    normal = np.zeros((10, 1))
    normal[:, 0] = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]  # mean 0.5, population std 0.5
    # A window that sits at its normal level except for a single high row.
    abnormal = np.array([[0.5], [0.5], [0.5], [3.0]])

    score = rcaeval_scores(normal, abnormal, "NSIGMA")[0]
    assert score == pytest.approx((3.0 - 0.5) / 0.5)


def test_a_column_that_only_falls_scores_negative():
    """Not `max(|z|)`. A fault that reduces a metric is invisible to both methods.

    Worth a test of its own because it is a limitation of the baseline that the
    paper should state, and because an "improved" version that took the absolute
    value would quietly stop being the published method.
    """
    normal = np.linspace(0.0, 1.0, 20).reshape(-1, 1)
    abnormal = np.full((5, 1), -50.0)

    for method in ("NSIGMA", "BARO"):
        assert rcaeval_scores(normal, abnormal, method)[0] < 0


def test_baro_differs_from_nsigma_only_in_the_scaler():
    """BARO is their nsigma with median and IQR. Checked against sklearn itself."""
    rng = np.random.default_rng(42)
    normal = rng.normal(size=(200, 3))
    abnormal = rng.normal(size=(40, 3)) + np.array([0.0, 4.0, 8.0])

    for method, scaler_class in (("NSIGMA", StandardScaler), ("BARO", RobustScaler)):
        got = rcaeval_scores(normal, abnormal, method)
        for index in range(3):
            scaler = scaler_class().fit(normal[:, index].reshape(-1, 1))
            expected = scaler.transform(abnormal[:, index].reshape(-1, 1))[:, 0].max()
            assert got[index] == pytest.approx(expected)


def test_a_constant_column_does_not_divide_by_zero():
    """sklearn substitutes a scale of 1.0, so the score becomes a raw difference.

    Their `preprocess` drops most constant columns, but it runs on each window
    separately, so the guard still fires. Pinned because it is part of the method,
    not an accident of ours.
    """
    normal = np.full((30, 1), 7.0)
    abnormal = np.full((5, 1), 9.0)

    for method in ("NSIGMA", "BARO"):
        score = rcaeval_scores(normal, abnormal, method)[0]
        assert np.isfinite(score)
        assert score == pytest.approx(2.0)


def test_a_column_with_no_normal_readings_scores_nan():
    """And it is left as NaN, because that is what changes their ranking."""
    normal = np.full((30, 2), np.nan)
    normal[:, 1] = 1.0
    abnormal = np.array([[5.0, 1.0], [6.0, 1.0]])

    scores = rcaeval_scores(normal, abnormal, "NSIGMA")
    assert not np.isfinite(scores[0])
    assert count_non_finite(scores) == 1


def test_their_sort_is_wrong_when_a_score_is_nan():
    """The finding behind three of the four odd cases in the M2.4 run.

    Every comparison with NaN is False, so `sorted` has no valid ordering and
    returns a list in which even the real scores are out of place. Reproduced
    rather than fixed: it is how their published ranking is produced.
    """
    assert their_sort(["a", "b", "c"], [1.0, float("nan"), 5.0]) == ["a", "b", "c"]

    # Without the NaN the same call sorts properly, so the sort itself is fine.
    assert their_sort(["a", "b", "c"], [1.0, 2.0, 5.0]) == ["c", "b", "a"]


def test_their_sort_breaks_ties_by_the_order_columns_arrive_in():
    """Which is the artefact `docs/08` section 4 warns about.

    It is why the ranks these scripts record carry a tie-group size: the metrics
    then score a tie as a shuffle rather than letting the column order decide.
    """
    assert their_sort(["z", "a"], [1.0, 1.0]) == ["z", "a"]
    assert their_sort(["a", "z"], [1.0, 1.0]) == ["a", "z"]


def test_our_formula_and_theirs_disagree_on_a_single_spike():
    """The difference the ladder's A-to-B step measures, in one case.

    A column with one extreme row and an otherwise normal window: their maximum
    ranks it loudly, our window mean barely moves.
    """
    rng = np.random.default_rng(0)
    normal = rng.normal(size=(300, 2))
    abnormal = rng.normal(size=(60, 2))
    abnormal[0, 0] += 40.0  # column 0: one spike
    abnormal[:, 1] += 3.0  # column 1: a sustained shift

    theirs = rcaeval_scores(normal, abnormal, "NSIGMA")
    ours = our_nsigma_scores(normal, abnormal)

    assert theirs[0] > theirs[1], "their max puts the single spike first"
    assert ours[1] > ours[0], "our mean shift puts the sustained change first"


def test_bad_arguments_are_rejected():
    normal = np.zeros((10, 2))
    with pytest.raises(ValueError, match="method must be one of"):
        rcaeval_scores(normal, normal, "NOT_A_METHOD")
    with pytest.raises(ValueError, match="columns"):
        rcaeval_scores(normal, np.zeros((10, 3)), "NSIGMA")
    with pytest.raises(ValueError, match="zero normal rows"):
        rcaeval_scores(np.zeros((0, 2)), normal, "NSIGMA")
    with pytest.raises(ValueError, match="empty abnormal window"):
        rcaeval_scores(normal, np.zeros((0, 2)), "NSIGMA")
    with pytest.raises(ValueError, match="rows by columns"):
        rcaeval_scores(np.zeros(10), np.zeros(10), "NSIGMA")
