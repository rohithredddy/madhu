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

    used_std: FloatArray | None = None
    """Which columns had no robust spread at all, so their scale is the ordinary
    standard deviation instead of the MAD. See :func:`robust_baseline`. ``None``
    means "none of them", which is what a hand-built baseline in a test will mean."""

    def __post_init__(self) -> None:
        if self.median.shape != self.scale.shape:
            raise ValueError(
                f"median and scale must have the same shape, got {self.median.shape} "
                f"and {self.scale.shape}"
            )
        if self.used_std is not None and self.used_std.shape != self.scale.shape:
            raise ValueError(
                f"used_std must have the same shape as scale, got "
                f"{self.used_std.shape} and {self.scale.shape}"
            )

    @property
    def n_used_std(self) -> int:
        """How many columns fell back to the standard deviation."""
        return 0 if self.used_std is None else int(np.count_nonzero(self.used_std))


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
        # The same empty column, reached through `np.nanstd`, which complains in
        # different words. Missed when this helper was written because no caller
        # had yet fed `nsigma_score` a column with no readings at all; M2.4 did,
        # by scoring our formula over RCAEval's candidate set, whose
        # `drop_constant` keeps an all-NaN column (NaN != NaN, so it never looks
        # constant). No score changes: the result was already mapped to 0.
        warnings.filterwarnings("ignore", message="Degrees of freedom <= 0")
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

    **When the MAD is zero but the column is not constant**, the scale is the
    ordinary standard deviation instead. This matters more than it sounds, and it
    is the settlement of open question 9 (decision 72).

    A MAD of zero says more than half the normal values are identical. The column
    can still move - it is simply flat in its middle half. Before this, such a
    column kept a scale of just the epsilon, about 1e-6, so the "robust z" became
    the raw deviation divided by a millionth and any movement at all scored in the
    millions. On RCAEval RE1-OB that happened to 2.7 columns per case, it decided
    first place in 34 of 125 cases, and one case ranked a column at 4,000,000.
    Measured, repairing it lifts PARE's AC@1 from 0.240 to 0.384.

    The epsilon's job was always to stop a division by zero, never to set the
    scale, so this restores the intent rather than adding a special case. The
    standard deviation is the only spread estimate such a column has; the cost is
    that those columns are no longer scored robustly, which `docs/05` section 3
    step 1 states and which :attr:`RobustBaseline.used_std` reports so a caller can
    warn about it.

    The alternative - dropping the column - scored marginally better on RE1-OB
    (AC@1 0.400) but was rejected: it can silently discard the right answer. A
    metric that is flat while nothing is wrong and then climbs is exactly what a
    memory leak looks like, and `mem` is the most common flat column in this data.
    A difference of two cases in 125 is not a reason to make the method blind to
    its own motivating example.
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

    scale = MAD_TO_SIGMA * spread
    # Columns with no robust spread. A truly constant column is left alone: its
    # standard deviation is zero too, so there is nothing to fall back to, and
    # step 0 has already dropped it.
    no_robust_spread = scale == 0.0
    used_std = np.zeros(scale.shape, dtype=bool)
    if no_robust_spread.any():
        with _quiet_all_nan():
            deviation = np.asarray(np.nanstd(data, axis=0), dtype=np.float64)
        deviation = np.nan_to_num(deviation, nan=0.0)
        used_std = no_robust_spread & (deviation > 0.0)
        scale = np.where(used_std, deviation, scale)

    eps = EPS_FACTOR * (np.abs(centre) + 1.0)
    return RobustBaseline(median=centre, scale=scale + eps, used_std=used_std)


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
