"""Tests for `stats.py`. Every expected value is worked out by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pare.eval_metrics import Rank

from experiments import stats


def test_reciprocal_rank_of_a_plain_position():
    assert stats.reciprocal_rank(Rank(best=1)) == 1.0
    assert stats.reciprocal_rank(Rank(best=4)) == 0.25
    assert stats.reciprocal_rank(None) == 0.0


def test_reciprocal_rank_of_a_tie_is_its_expected_value():
    """A tie over ranks 1 and 2: half the time 1, half the time 1/2."""
    assert stats.reciprocal_rank(Rank(best=1, tied=2)) == pytest.approx(0.75)


def test_avg5_per_case():
    assert stats.avg5_per_case(Rank(best=1)) == 1.0
    assert stats.avg5_per_case(Rank(best=3)) == pytest.approx(3 / 5)
    assert stats.avg5_per_case(Rank(best=6)) == 0.0


def test_cliffs_delta_extremes_and_symmetry():
    assert stats.cliffs_delta([2, 3], [0, 1]) == 1.0
    assert stats.cliffs_delta([0, 1], [2, 3]) == -1.0
    assert stats.cliffs_delta([1, 1], [1, 1]) == 0.0
    # 2 of 4 pairs larger, 1 smaller: (2 - 1) / 4
    assert stats.cliffs_delta([1, 3], [2, 0.5]) == pytest.approx(
        (np.sum([1 > 2, 1 > 0.5, 3 > 2, 3 > 0.5]) - np.sum([1 < 2])) / 4
    )


def test_effect_labels_follow_the_published_thresholds():
    assert stats.effect_label(0.1) == "negligible"
    assert stats.effect_label(-0.2) == "small"
    assert stats.effect_label(0.4) == "medium"
    assert stats.effect_label(-0.9) == "large"


def test_identical_methods_are_not_significantly_different():
    assert stats.paired_wilcoxon([1, 0.5, 0.2], [1, 0.5, 0.2]) == 1.0


def test_a_consistent_difference_gives_a_small_p_value():
    x = np.linspace(0.5, 1.0, 20)
    assert stats.paired_wilcoxon(x, x - 0.3) < 0.001


def test_holm_by_hand():
    """p = (0.01, 0.04, 0.03): sorted 0.01, 0.03, 0.04 -> x3, x2, x1 =
    0.03, 0.06, 0.04, then made non-decreasing: 0.03, 0.06, 0.06."""
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert stats.holm([0.9, 0.8]) == pytest.approx([1.0, 1.0])


def test_bootstrap_interval_contains_the_mean_and_is_reproducible():
    values = np.r_[np.ones(30), np.zeros(70)]
    low, high = stats.bootstrap_ci(values)
    assert low < 0.3 < high
    assert stats.bootstrap_ci(values) == (low, high)
    assert stats.bootstrap_ci(np.ones(10)) == (1.0, 1.0)


def test_compare_pairs_cases_and_corrects_across_methods():
    rows = []
    for i in range(30):
        for method, rank in (("PARE", 1), ("A", 3), ("B", 1)):
            rows.append({"method": method, "delay_s": 0.0, "system": "s",
                         "case_id": f"c{i}", "rr": 1 / rank})
    result = stats.compare(pd.DataFrame(rows), "PARE").set_index("method")
    assert result.loc["A", "reference_better"] == 30
    assert result.loc["A", "significant_0_05"]
    assert result.loc["B", "p_wilcoxon"] == 1.0
    assert not result.loc["B", "significant_0_05"]
    assert result.loc["A", "p_holm"] >= result.loc["A", "p_wilcoxon"]
