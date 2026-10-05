"""Tests for the scoring building blocks.

docs/05 section 6 asks for "robust z and window score on hand-made arrays", so
the numbers below are worked out by hand and written in the test, not copied from
what the code happened to print.
"""

import math

import numpy as np
import pytest

from pare.scores import (
    EPS_FACTOR,
    MAD_TO_SIGMA,
    ecdf_tail_score,
    mad,
    robust_baseline,
    robust_z,
    window_score,
)

# --- MAD and the baseline, by hand ------------------------------------------


def test_mad_of_a_hand_made_array():
    # median of 1..5 is 3; |x-3| is 2,1,0,1,2; its median is 1
    assert mad([1, 2, 3, 4, 5]) == pytest.approx(1.0)


def test_baseline_median_and_scale_by_hand():
    base = robust_baseline([1, 2, 3, 4, 5])
    assert base.median == pytest.approx(3.0)
    # 1.4826 * 1 + 1e-6 * (|3| + 1)
    assert base.scale == pytest.approx(MAD_TO_SIGMA * 1.0 + EPS_FACTOR * 4.0)


def test_the_median_ignores_an_extreme_value_that_would_wreck_a_mean():
    """The reason for using median and MAD at all.

    A spread-out sample, not two tight clusters: with an even number of values
    split evenly between two levels the median sits in the gap between them, and
    adding any single value makes it jump a whole level. That would be an
    artefact of the toy data rather than anything about robustness.
    """
    rng = np.random.default_rng(7)
    clean = rng.normal(10.0, 1.0, 200)
    spiked = np.append(clean, 10_000.0)

    base_clean = robust_baseline(clean)
    base_spiked = robust_baseline(spiked)

    assert base_spiked.median == pytest.approx(base_clean.median, abs=0.1)
    assert base_spiked.scale == pytest.approx(base_clean.scale, rel=0.05)

    # for comparison, the mean and standard deviation move enormously
    assert np.mean(spiked) > 5 * np.mean(clean)
    assert np.std(spiked) > 100 * np.std(clean)


def test_a_flat_column_gets_a_positive_scale_instead_of_zero():
    base = robust_baseline([7.0] * 20)
    assert base.scale > 0
    assert base.scale == pytest.approx(EPS_FACTOR * 8.0)
    # and dividing by it does not blow up
    assert np.isfinite(robust_z([7.0], base)).all()


def test_baseline_needs_rows():
    with pytest.raises(ValueError, match="zero rows"):
        robust_baseline(np.empty((0, 3)))


# --- robust z ---------------------------------------------------------------


def test_robust_z_by_hand():
    base = robust_baseline([1, 2, 3, 4, 5])
    scale = MAD_TO_SIGMA * 1.0 + EPS_FACTOR * 4.0

    z = robust_z([3.0, 5.0, 1.0], base)
    assert z[0] == pytest.approx(0.0)
    assert z[1] == pytest.approx(2.0 / scale)
    assert z[2] == pytest.approx(-2.0 / scale)


def test_robust_z_keeps_the_sign():
    """Direction matters for the explanation text, so it is not absolute here."""
    base = robust_baseline([0.0, 1.0, -1.0, 0.0])
    assert robust_z([5.0], base)[0] > 0
    assert robust_z([-5.0], base)[0] < 0


def test_robust_z_keeps_the_shape_of_its_input():
    normal = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
    base = robust_baseline(normal)
    z = robust_z(normal, base)
    assert z.shape == normal.shape
    # the middle row is the median of both columns
    assert z[1] == pytest.approx([0.0, 0.0])


def test_robust_z_passes_nan_through():
    base = robust_baseline([1.0, 2.0, 3.0])
    z = robust_z([np.nan, 2.0], base)
    assert math.isnan(z[0])
    assert z[1] == pytest.approx(0.0)


# --- window score -----------------------------------------------------------


def test_window_score_by_hand():
    normal = [1, 2, 3, 4, 5]  # median 3, MAD 1
    abnormal = [8, 9, 10]  # median 9
    scale = MAD_TO_SIGMA * 1.0 + EPS_FACTOR * 4.0
    assert window_score(normal, abnormal) == pytest.approx(6.0 / scale)


def test_window_score_is_never_negative():
    """A column that drops is just as abnormal as one that rises."""
    normal = [10, 11, 12, 13, 14]
    up = window_score(normal, [20, 20, 20])
    down = window_score(normal, [4, 4, 4])
    assert up > 0 and down > 0
    assert up == pytest.approx(down, rel=0.2)


def test_an_unchanged_window_scores_about_zero():
    rng = np.random.default_rng(0)
    normal = rng.normal(100.0, 5.0, 500)
    quiet = rng.normal(100.0, 5.0, 120)
    assert window_score(normal, quiet) < 0.5


def test_one_spike_does_not_make_a_window_abnormal():
    """The spec's reason for using the window median rather than its maximum."""
    rng = np.random.default_rng(1)
    normal = rng.normal(100.0, 5.0, 500)
    window = rng.normal(100.0, 5.0, 120)
    window[60] = 10_000.0  # a single wild reading

    assert window_score(normal, window) < 0.5


def test_a_sustained_shift_does_make_a_window_abnormal():
    rng = np.random.default_rng(2)
    normal = rng.normal(100.0, 5.0, 500)
    shifted = rng.normal(130.0, 5.0, 120)
    assert window_score(normal, shifted) > 3.0


def test_window_score_handles_several_columns_at_once():
    normal = np.column_stack([np.full(100, 10.0), np.linspace(0.0, 100.0, 100)])
    abnormal = np.column_stack([np.full(20, 10.0), np.full(20, 500.0)])

    scores = window_score(normal, abnormal)
    assert scores.shape == (2,)
    assert scores[0] == pytest.approx(0.0, abs=1e-6)  # unchanged column
    assert scores[1] > 10.0  # column that moved a long way


def test_a_column_that_is_entirely_missing_scores_zero_not_nan():
    """So one dead column cannot poison a whole ranking."""
    normal = np.column_stack([np.full(50, 1.0), np.full(50, np.nan)])
    abnormal = np.column_stack([np.full(10, 9.0), np.full(10, np.nan)])

    scores = window_score(normal, abnormal)
    assert np.isfinite(scores).all()
    assert scores[1] == 0.0
    assert scores[0] > 0


def test_window_score_ignores_scattered_nan():
    normal = np.array([1.0, 2.0, np.nan, 3.0, 4.0, 5.0])
    abnormal = np.array([9.0, np.nan, 9.0])
    assert window_score(normal, abnormal) > 3.0


def test_window_score_rejects_an_empty_window():
    with pytest.raises(ValueError, match="empty window"):
        window_score([1.0, 2.0, 3.0], np.empty((0,)))


def test_passing_a_prepared_baseline_gives_the_same_answer():
    normal = [1, 2, 3, 4, 5]
    abnormal = [8, 9, 10]
    base = robust_baseline(normal)
    assert window_score(normal, abnormal, baseline=base) == pytest.approx(
        window_score(normal, abnormal)
    )


# --- ECDF tail score --------------------------------------------------------


def test_a_value_in_the_middle_of_normal_is_not_surprising():
    normal = np.arange(100.0)
    # the window median lands near the middle of the normal range
    assert ecdf_tail_score(normal, [49.0, 50.0, 51.0]) == pytest.approx(0.0, abs=0.05)


def test_a_value_beyond_everything_seen_hits_the_ceiling():
    normal = np.arange(100.0)
    score = ecdf_tail_score(normal, [1000.0])
    # floored at 1/(n+1), so the biggest possible score is log(n+1)
    assert score == pytest.approx(math.log(101.0))


def test_the_ceiling_grows_with_the_amount_of_normal_data():
    """More evidence of what normal looks like means more confidence that
    something outside it is genuinely strange."""
    small = ecdf_tail_score(np.arange(50.0), [1000.0])
    large = ecdf_tail_score(np.arange(500.0), [1000.0])
    assert large > small
    assert small == pytest.approx(math.log(51.0))
    assert large == pytest.approx(math.log(501.0))


def test_the_tail_score_is_two_sided():
    normal = np.arange(100.0)
    high = ecdf_tail_score(normal, [1000.0])
    low = ecdf_tail_score(normal, [-1000.0])
    assert high == pytest.approx(low)


def test_a_further_value_is_more_surprising():
    normal = np.arange(100.0)
    near_edge = ecdf_tail_score(normal, [90.0])
    past_edge = ecdf_tail_score(normal, [200.0])
    assert past_edge > near_edge > 0


def test_tail_score_handles_several_columns_and_nan():
    normal = np.column_stack([np.arange(100.0), np.full(100, np.nan)])
    abnormal = np.column_stack([np.full(5, 1000.0), np.full(5, np.nan)])

    scores = ecdf_tail_score(normal, abnormal)
    assert scores.shape == (2,)
    assert scores[0] == pytest.approx(math.log(101.0))
    assert scores[1] == 0.0  # nothing observed, so nothing surprising


def test_tail_score_rejects_empty_inputs():
    with pytest.raises(ValueError, match="zero normal rows"):
        ecdf_tail_score(np.empty((0,)), [1.0])
    with pytest.raises(ValueError, match="empty window"):
        ecdf_tail_score([1.0, 2.0], np.empty((0,)))


# --- input shapes -----------------------------------------------------------


@pytest.mark.parametrize("bad", [5.0, np.zeros((2, 2, 2))])
def test_inputs_must_be_a_column_or_a_window(bad):
    with pytest.raises(ValueError):
        robust_baseline(bad)


def test_integers_are_not_truncated():
    base = robust_baseline(np.array([1, 2, 3, 4, 5], dtype=int))
    assert isinstance(base.median.item(), float)
    assert base.median == pytest.approx(3.0)


# --- the two scorers answer different questions -----------------------------


def test_the_two_scorers_disagree_on_a_lopsided_column():
    """Why both exist. On a heavy-tailed column the marginal score stays small
    because the spread is wide, while the tail score still says the value is
    outside anything normal ever did."""
    rng = np.random.default_rng(3)
    # mostly small values with occasional large ones: a wide MAD
    normal = np.abs(rng.standard_cauchy(2000)) * 10.0
    window = np.full(50, float(np.max(normal) * 2.0))

    assert window_score(normal, window) > 0
    assert ecdf_tail_score(normal, window) == pytest.approx(math.log(2001.0))


# --- a column with no robust spread -----------------------------------------
#
# Settles open question 9 (decision 72). A MAD of zero means more than half the
# normal values are identical, which is not the same as the column being constant.
# Before this, such a column kept a scale of only the epsilon, so its "robust z"
# was the raw deviation divided by about a millionth and any movement scored in
# the millions. These tests pin the repair and, just as importantly, pin that
# nothing else moved.


def test_a_flat_but_not_constant_column_is_scored_on_its_standard_deviation():
    """The repair. Half the rows identical, the other half not."""
    normal = np.array([5.0] * 60 + [5.0, 6.0, 7.0, 4.0, 3.0] * 4)
    baseline = robust_baseline(normal.reshape(-1, 1))

    assert mad(normal.reshape(-1, 1))[0] == 0.0, "the premise: no robust spread"
    assert baseline.used_std is not None
    assert bool(baseline.used_std[0]) is True
    assert baseline.n_used_std == 1
    # The scale is the standard deviation, not a millionth of anything. The
    # epsilon is still added on top, exactly as it is for every other column, so
    # the "scale is never zero" guarantee holds without a second rule.
    expected = float(np.std(normal)) + EPS_FACTOR * (abs(float(np.median(normal))) + 1.0)
    assert baseline.scale[0] == pytest.approx(expected)


def test_the_repair_keeps_the_score_of_such_a_column_sane():
    """The symptom that started this: a score in the millions.

    Measured on RE1-OB, one case ranked a column at 4,000,000 because of it.
    """
    normal = np.array([5.0] * 60 + [5.0, 6.0, 7.0, 4.0, 3.0] * 4)
    window = np.full(20, 9.0)

    score = window_score(normal.reshape(-1, 1), window.reshape(-1, 1))[0]
    # Roughly "a few standard deviations", which is what a z-score should mean.
    assert 1.0 < score < 10.0, score


def test_a_truly_constant_column_is_left_exactly_as_it_was():
    """There is nothing to fall back to, and step 0 has already dropped it.

    Pinned because the guarantee "scale is never zero" has to survive the change.
    """
    normal = np.full((40, 1), 7.0)
    baseline = robust_baseline(normal)

    assert baseline.n_used_std == 0
    assert baseline.scale[0] > 0.0
    assert baseline.scale[0] == pytest.approx(EPS_FACTOR * (7.0 + 1.0))


def test_an_all_nan_column_is_unchanged_by_the_repair():
    normal = np.full((30, 1), np.nan)
    baseline = robust_baseline(normal)

    assert baseline.n_used_std == 0
    assert baseline.median[0] == 0.0
    assert baseline.scale[0] > 0.0


def test_an_ordinary_column_is_untouched_to_the_last_bit():
    """The reason this change is safe to make after M1 was measured.

    Every column with a non-zero MAD keeps exactly the scale it had, so no result
    produced before this moves. Asserted against the formula rather than a
    recorded number, so it cannot drift.
    """
    rng = np.random.default_rng(11)
    normal = rng.normal(100.0, 5.0, size=(400, 6))
    baseline = robust_baseline(normal)

    assert baseline.n_used_std == 0
    expected = MAD_TO_SIGMA * mad(normal) + EPS_FACTOR * (
        np.abs(np.median(normal, axis=0)) + 1.0
    )
    assert baseline.scale == pytest.approx(expected)


def test_mixed_columns_fall_back_one_by_one():
    """Only the degenerate column changes; its neighbours do not."""
    rng = np.random.default_rng(12)
    ordinary = rng.normal(0.0, 2.0, size=200)
    flat = np.array([1.0] * 150 + list(rng.normal(1.0, 0.5, size=50)))
    constant = np.full(200, 3.0)
    normal = np.column_stack([ordinary, flat, constant])

    baseline = robust_baseline(normal)
    assert list(baseline.used_std) == [False, True, False]
    assert baseline.scale[0] == pytest.approx(
        MAD_TO_SIGMA * mad(ordinary.reshape(-1, 1))[0]
        + EPS_FACTOR * (abs(float(np.median(ordinary))) + 1.0)
    )
