"""How unusual is a number, measured against what normal looked like.

These are the building blocks every engine shares. Nothing here knows about the
call graph: this is step 1 of the method, "how strange does this column look on
its own", before any of the propagation reasoning happens.

Two choices run through the whole module, and both are about not being fooled by
a handful of odd values:

* **Median and MAD instead of mean and standard deviation.** A few extreme rows
  in the normal period would inflate a standard deviation and then hide the real
  fault behind it. The median and the median absolute deviation barely move.
* **The median of the abnormal window, not its maximum.** One spike is not an
  incident. Taking the median asks "did this column move and stay moved", which
  is what a real fault looks like.

Every function takes either a single column, shaped ``(n_rows,)``, or a whole
window, shaped ``(n_rows, n_columns)``, and reduces down the rows. A column with
no usable data scores 0: missing data is not evidence of a fault.

Spec: ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3, steps 0 and 1, and the
``ECDF`` engine in section 4.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

# Scaling that makes the MAD comparable to a standard deviation, so a score of 3
# means roughly what "3 sigma" means for well-behaved data. 1/0.6745.
MAD_TO_SIGMA = 1.4826

# Keeps a perfectly flat column from dividing by zero. Scaled by the size of the
# values so it stays negligible for large numbers and still works for small ones:
# eps = 1e-6 * (|median| + 1), as the spec defines it.
EPS_FACTOR = 1e-6

ArrayLike = npt.ArrayLike
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class RobustBaseline:
    """What normal looked like, per column.

    ``scale`` is the MAD already multiplied by :data:`MAD_TO_SIGMA` and with the
    small epsilon added, so callers can divide by it without checking for zero.
    """

    median: FloatArray
    """Middle value of each column over the normal rows."""

    scale: FloatArray
    """Robust stand-in for the standard deviation of each column. Never zero."""

    def __post_init__(self) -> None:
        if self.median.shape != self.scale.shape:
            raise ValueError(
                f"median and scale must have the same shape, got {self.median.shape} "
                f"and {self.scale.shape}"
            )


@contextmanager
def _quiet_all_nan() -> Iterator[None]:
    """Silence numpy's "All-NaN slice" warning.

    A column with no readings at all is an expected input here, not a mistake:
    every function in this module turns it into a score of 0 on purpose. The
    warning would only train the reader to ignore warnings.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        yield


def mad(values: ArrayLike) -> FloatArray:
    """Median absolute deviation of each column, unscaled.

    The median of ``|x - median(x)|``. NaN values are ignored.
    """
    data = _as_float_array(values)
    with _quiet_all_nan():
        centre = np.nanmedian(data, axis=0)
        return np.asarray(np.nanmedian(np.abs(data - centre), axis=0), dtype=np.float64)


def robust_baseline(normal: ArrayLike) -> RobustBaseline:
    """Measure the middle and the spread of the normal period, per column.

    This is the only place the epsilon rule lives, so every score in the project
    treats a flat column the same way.
    """
    data = _as_float_array(normal)
    if data.shape[0] == 0:
        raise ValueError("cannot measure a baseline from zero rows")

    with _quiet_all_nan():
        centre = np.asarray(np.nanmedian(data, axis=0), dtype=np.float64)
        spread = np.asarray(np.nanmedian(np.abs(data - centre), axis=0), dtype=np.float64)

    # An all-NaN column gives NaN here. Treat it as flat: the epsilon below then
    # makes the scale positive, and window_score returns 0 for it anyway.
    centre = np.nan_to_num(centre, nan=0.0)
    spread = np.nan_to_num(spread, nan=0.0)

    eps = EPS_FACTOR * (np.abs(centre) + 1.0)
    return RobustBaseline(median=centre, scale=MAD_TO_SIGMA * spread + eps)


def robust_z(values: ArrayLike, baseline: RobustBaseline) -> FloatArray:
    """How far each value sits from normal, in robust standard deviations.

    Keeps the sign, so the caller can tell "went up" from "went down". Shape of
    the result matches ``values``. NaN in, NaN out.
    """
    data = _as_float_array(values)
    return np.asarray((data - baseline.median) / baseline.scale, dtype=np.float64)


def window_score(
    normal: ArrayLike,
    abnormal: ArrayLike,
    baseline: RobustBaseline | None = None,
) -> FloatArray:
    """The marginal score of each column: how far the window moved from normal.

    ``|median(abnormal) - median(normal)| / scale``. This is the number the
    method calls the *marginal* score - how strange a column looks taken on its
    own, with no account of what it depends on. PARE's whole argument is that
    this number alone blames whoever is loudest.

    The result is never negative, and a column whose window is entirely missing
    scores 0 rather than NaN, so one empty column cannot poison a ranking.

    Pass ``baseline`` when it has already been measured, to avoid doing it twice.
    """
    base = robust_baseline(normal) if baseline is None else baseline
    window = _as_float_array(abnormal)
    if window.shape[0] == 0:
        raise ValueError("cannot score an empty window")

    with _quiet_all_nan():
        window_median = np.nanmedian(window, axis=0)

    score = np.abs(window_median - base.median) / base.scale
    # An all-NaN column has no evidence either way, so it is not an anomaly.
    return np.asarray(np.nan_to_num(score, nan=0.0), dtype=np.float64)


def ecdf_tail_score(
    normal: ArrayLike,
    abnormal: ArrayLike,
) -> FloatArray:
    """How far into the tail of normal the window's median falls, ECOD style.

    For each column: take the median of the abnormal window, ask what fraction of
    the normal values lie at or beyond it on the nearer side, double it to make
    the test two-sided, and report ``-log`` of that probability. Bigger means
    more surprising.

    This is a different question from :func:`window_score`. The marginal score
    asks "how many spreads away", which assumes the spread is meaningful; this
    asks "how often did normal ever get this far", which does not care about the
    shape of the distribution at all. That makes it a fair baseline for a column
    whose normal behaviour is lopsided or heavy-tailed.

    The probability is floored at ``1 / (n + 1)`` so a value beyond everything
    ever seen gives a large but finite score instead of infinity. With ``n``
    normal rows the largest possible score is therefore ``log(n + 1)``.
    """
    sample = _as_float_array(normal)
    window = _as_float_array(abnormal)
    if sample.shape[0] == 0:
        raise ValueError("cannot measure a tail probability from zero normal rows")
    if window.shape[0] == 0:
        raise ValueError("cannot score an empty window")

    with _quiet_all_nan():
        window_median = np.nanmedian(window, axis=0)

    # Count only real observations; NaN comparisons are False either way.
    observed = np.sum(~np.isnan(sample), axis=0).astype(np.float64)
    at_or_below = np.sum(sample <= window_median, axis=0).astype(np.float64)
    at_or_above = np.sum(sample >= window_median, axis=0).astype(np.float64)

    usable = observed > 0
    # np.where still evaluates both branches, so divide by a safe denominator.
    safe = np.where(usable, observed, 1.0)
    lower_tail = at_or_below / safe
    upper_tail = at_or_above / safe

    two_sided = 2.0 * np.minimum(lower_tail, upper_tail)
    floor = 1.0 / (safe + 1.0)
    probability = np.clip(two_sided, floor, 1.0)

    score = -np.log(probability)
    # No normal observations, or an all-NaN window, means no evidence of a fault.
    score = np.where(usable, score, 0.0)
    return np.asarray(np.nan_to_num(score, nan=0.0), dtype=np.float64)


def nsigma_score(normal: ArrayLike, abnormal: ArrayLike) -> FloatArray:
    """The classic NSigma baseline: mean and standard deviation, not median and MAD.

    ``|mean(abnormal) - mean(normal)| / (std(normal) + eps)``.

    Deliberately **not** robust, and deliberately not reusing
    :func:`window_score`. NSigma is the standard baseline this work is measured
    against, so it has to be the method as everyone else implements it, not an
    improved version of it - otherwise the comparison flatters us. Its weakness to
    outliers is part of what the results are supposed to show.

    The Java fallback ranker computes exactly this, so that the two agree on the
    shared sample file (``docs/03_JAVA_BACKEND_SPEC.md`` section 4.4). If this
    changes, that changes with it.
    """
    before = _as_float_array(normal)
    after = _as_float_array(abnormal)
    if before.shape[0] == 0:
        raise ValueError("cannot measure a baseline from zero rows")
    if after.shape[0] == 0:
        raise ValueError("cannot score an empty window")

    with _quiet_all_nan():
        centre = np.nanmean(before, axis=0)
        spread = np.nanstd(before, axis=0)
        moved = np.nanmean(after, axis=0)

    eps = EPS_FACTOR * (np.abs(np.nan_to_num(centre, nan=0.0)) + 1.0)
    score = np.abs(moved - centre) / (spread + eps)
    return np.asarray(np.nan_to_num(score, nan=0.0), dtype=np.float64)


def _as_float_array(values: ArrayLike) -> FloatArray:
    """Turn the input into a float array of rows, so NaN works and ints do not
    silently truncate. Accepts one column or a whole window."""
    data = np.asarray(values, dtype=np.float64)
    if data.ndim == 0:
        raise ValueError("expected a column or a window of rows, got a single number")
    if data.ndim > 2:
        raise ValueError(f"expected 1 or 2 dimensions, got {data.ndim}")
    return data
