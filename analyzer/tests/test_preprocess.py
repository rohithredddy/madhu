"""Tests for step 0, the cleaning that happens before anything is scored."""

import numpy as np
import pytest

from pare.columns import ColumnInfo
from pare.config import PareConfig
from pare.preprocess import preprocess

COLUMNS = [
    ColumnInfo("a_latency", "a", "latency"),
    ColumnInfo("b_latency", "b", "latency"),
]


def two_columns(first, second, rows=100):
    """Build a (rows, 2) block from two series or constants."""
    def expand(value):
        return np.full(rows, float(value)) if np.isscalar(value) else np.asarray(value, float)

    return np.column_stack([expand(first), expand(second)])


# --- dropping ---------------------------------------------------------------


def test_a_mostly_missing_column_is_dropped_and_explained():
    rng = np.random.default_rng(0)
    bad = rng.normal(0.0, 1.0, 100)
    bad[:70] = np.nan  # 70 percent missing

    clean = preprocess(two_columns(rng.normal(0, 1, 100), bad), two_columns(1.0, 2.0, 20), COLUMNS)

    assert [c.name for c in clean.columns] == ["a_latency"]
    assert clean.dropped == ["b_latency"]
    assert "missing for 70%" in clean.warnings[0]


def test_a_column_that_never_moves_is_dropped():
    """A flat column has no spread, so any movement at all would divide by almost
    nothing and score enormously. That is how a dead metric wins a ranking."""
    rng = np.random.default_rng(1)
    clean = preprocess(
        two_columns(rng.normal(0, 1, 100), 5.0),
        two_columns(1.0, 99.0, 20),
        COLUMNS,
    )

    assert [c.name for c in clean.columns] == ["a_latency"]
    assert "never changes" in clean.warnings[0]


def test_a_column_that_is_mostly_flat_but_does_jump_is_kept():
    """Its MAD is zero but its standard deviation is not, and the spec requires
    both to be zero. A metric that is usually idle still carries information."""
    series = np.full(100, 2.0)
    series[::20] = 50.0
    rng = np.random.default_rng(2)

    clean = preprocess(
        two_columns(rng.normal(0, 1, 100), series), two_columns(1.0, 2.0, 20), COLUMNS
    )
    assert len(clean.columns) == 2


def test_when_nothing_survives_it_says_so():
    clean = preprocess(two_columns(1.0, 2.0), two_columns(1.0, 2.0, 20), COLUMNS)
    assert clean.is_empty
    assert clean.columns == []
    assert any("nothing to analyse" in w for w in clean.warnings)


# --- the no-leakage property ------------------------------------------------


def test_which_columns_are_kept_is_decided_by_the_normal_window_alone():
    """The abnormal window contains the fault. If it had a say in which columns
    are worth looking at, the answer would be choosing the question."""
    rng = np.random.default_rng(3)
    normal = two_columns(rng.normal(0, 1, 100), rng.normal(0, 1, 100))

    quiet_recent = two_columns(0.0, 0.0, 20)
    wild_recent = two_columns(1e6, np.nan, 20)

    kept_quiet = preprocess(normal, quiet_recent, COLUMNS).columns
    kept_wild = preprocess(normal, wild_recent, COLUMNS).columns

    assert [c.name for c in kept_quiet] == [c.name for c in kept_wild]


def test_both_windows_keep_the_same_columns_in_the_same_order():
    rng = np.random.default_rng(4)
    normal = two_columns(rng.normal(0, 1, 100), 7.0)  # second is flat
    clean = preprocess(normal, two_columns(1.0, 2.0, 20), COLUMNS)

    assert clean.normal.shape[1] == clean.recent.shape[1] == len(clean.columns) == 1


# --- gap filling ------------------------------------------------------------


def test_a_short_gap_is_filled_forward():
    series = np.arange(50.0)
    series[10:12] = np.nan  # a gap of 2, within the limit of 3

    clean = preprocess(
        np.column_stack([series, np.arange(50.0)]),
        np.ones((5, 2)),
        COLUMNS,
        PareConfig(fill_limit=3),
    )
    assert not np.isnan(clean.normal[10:12, 0]).any()
    assert clean.normal[10, 0] == pytest.approx(9.0)


def test_a_long_gap_is_left_alone():
    """Carrying a value across a long gap invents data. Every later step copes
    with missing values; none of them cope with made-up ones."""
    series = np.arange(50.0)
    series[10:30] = np.nan  # a gap of 20, well over the limit

    clean = preprocess(
        np.column_stack([series, np.arange(50.0)]),
        np.ones((5, 2)),
        COLUMNS,
        PareConfig(fill_limit=3),
    )
    assert np.isnan(clean.normal[10:30, 0]).all()


def test_a_gap_at_the_very_start_is_filled_backwards():
    series = np.arange(50.0)
    series[:2] = np.nan

    clean = preprocess(
        np.column_stack([series, np.arange(50.0)]), np.ones((5, 2)), COLUMNS
    )
    assert not np.isnan(clean.normal[:2, 0]).any()
    assert clean.normal[0, 0] == pytest.approx(2.0)


def test_filling_can_be_switched_off():
    series = np.arange(50.0)
    series[10:12] = np.nan
    clean = preprocess(
        np.column_stack([series, np.arange(50.0)]),
        np.ones((5, 2)),
        COLUMNS,
        PareConfig(fill_limit=0),
    )
    assert np.isnan(clean.normal[10:12, 0]).all()


# --- input checking ---------------------------------------------------------


def test_shapes_are_checked():
    with pytest.raises(ValueError, match="normal must be rows by columns"):
        preprocess(np.zeros(10), np.zeros((5, 2)), COLUMNS)
    with pytest.raises(ValueError, match="recent has 3 columns"):
        preprocess(np.zeros((10, 2)), np.zeros((5, 3)), COLUMNS)
