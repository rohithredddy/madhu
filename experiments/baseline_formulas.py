"""RCAEval's NSigma and BARO scoring formulas, re-implemented for our environment.

Why this file exists at all. The reproduction in `run_rcaeval_baselines.py` calls
RCAEval's own functions, which is the only thing that can honestly be called a
reproduction. But RCAEval lives in its own virtual environment (numpy 1.x) and
cannot be imported next to `pare` (numpy 2.x), so there is no way to run their
formula and ours over the *same* window in one process. Without that, a
difference in the final accuracy cannot be attributed to anything: formula,
window and candidate set all moved at once.

So their two formulas are re-implemented here, in the analyzer environment, and
`run_m24_compare.py` changes one thing at a time from their setup to ours. The
re-implementation is checked against their real output on all 125 cases rather
than trusted: `run_m24_compare.py` reports the agreement, and
`tests/test_baseline_formulas.py` pins the pieces.

Read off the installed source on 2026-10-05, not guessed (hard rule 9):
`RCAEval/e2e/__init__.py` for `nsigma`, `RCAEval/e2e/baro.py` for `baro`, and
`RCAEval/io/time_series.py` for `preprocess`. Both methods are the same three
lines with a different scaler:

    scaler = StandardScaler().fit(normal_col.reshape(-1, 1))   # RobustScaler for BARO
    zscores = scaler.transform(abnormal_col.reshape(-1, 1))[:, 0]
    score = max(zscores)

Three properties of that are easy to miss and all three change the answer:

* **The maximum, not the average.** One unusual row is enough to rank a column
  first. Our `NSIGMA` compares the mean of the window with the mean of normal.
* **Signed, not absolute.** `max(zscores)`, not `max(|zscores|)`. A column that
  only ever drops below its normal level scores negative and sorts to the bottom,
  so a fault that *reduces* a metric is invisible to both methods.
* **sklearn's zero-variance rule.** A constant column would divide by zero, so
  sklearn's `_handle_zeros_in_scale` silently substitutes a scale of 1.0, which
  turns the score into a raw difference in the metric's own units. Their
  `preprocess` drops most such columns first, but it is applied to each window
  separately, so the guard still fires. This is why the scalers are used here
  rather than the arithmetic written out: the edge case is part of the method.

`BARO` here is RCAEval's `baro` function, which is the ranking half of the BARO
paper (median and IQR instead of mean and standard deviation). The paper's other
half, multivariate Bayesian online change-point detection, finds the incident
time; the benchmark hands every method the injection time instead, so that half
never runs. Say so in the paper rather than claiming to have evaluated all of
BARO.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from sklearn.preprocessing import RobustScaler, StandardScaler

FloatArray = npt.NDArray[np.float64]

# Their scaler per method name, so the two differ in one word and nothing else -
# which is exactly how the two differ in their source.
SCALERS = {
    "NSIGMA": StandardScaler,
    "BARO": RobustScaler,
}


def rcaeval_scores(
    normal: npt.ArrayLike,
    abnormal: npt.ArrayLike,
    method: str = "NSIGMA",
) -> FloatArray:
    """Score every column the way RCAEval's `nsigma` or `baro` does.

    Args:
        normal: Rows by columns, the normal window.
        abnormal: Rows by columns, same columns in the same order.
        method: ``"NSIGMA"`` (mean and standard deviation) or ``"BARO"``
            (median and inter-quartile range).

    Returns:
        One score per column: the largest signed z-score of any abnormal row,
        with the column's normal window as the reference. Higher ranks first.
    """
    try:
        scaler_class = SCALERS[method]
    except KeyError:
        raise ValueError(
            f"method must be one of {sorted(SCALERS)}, got {method!r}"
        ) from None

    before = np.asarray(normal, dtype=np.float64)
    after = np.asarray(abnormal, dtype=np.float64)
    if before.ndim != 2 or after.ndim != 2:
        raise ValueError("normal and abnormal must both be rows by columns")
    if before.shape[1] != after.shape[1]:
        raise ValueError(
            f"normal has {before.shape[1]} columns, abnormal has {after.shape[1]}"
        )
    if before.shape[0] == 0:
        raise ValueError("cannot fit a scaler on zero normal rows")
    if after.shape[0] == 0:
        raise ValueError("cannot score an empty abnormal window")

    # Column by column, fitting a one-column scaler each time. That is their
    # loop, kept rather than vectorised, so sklearn's zero-variance handling and
    # its exact quantile definition apply here as they do there.
    #
    # A column with no valid rows in one of the windows scores NaN, and that is
    # kept rather than repaired: it is what their method does, it changes their
    # ranking (see `their_sort`), and it is one of the findings of M2.4. numpy and
    # sklearn complain loudly and repeatedly about the all-NaN slices that cause
    # it, which buries everything else in a 125-case run, so the complaint is
    # silenced here and the condition is reported instead - by
    # :func:`count_non_finite`, which the runner prints.
    scores = np.empty(before.shape[1], dtype=np.float64)
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        for index in range(before.shape[1]):
            scaler = scaler_class().fit(before[:, index].reshape(-1, 1))
            z = scaler.transform(after[:, index].reshape(-1, 1))[:, 0]
            scores[index] = np.max(z)
    return scores


def their_sort(columns: Sequence[str], scores: npt.ArrayLike) -> list[str]:
    """Order columns exactly as their two functions do.

        ranks = sorted(ranks, key=lambda x: x[1], reverse=True)

    A plain stable sort on the score, over a list built in the column order of
    the normal window. Worth reproducing rather than replacing with an equivalent,
    because when any score is NaN it is **not** equivalent to anything: every
    comparison with NaN is False, so the sort has no valid ordering to work with
    and silently returns a list that is wrong even for the non-NaN entries.

        >>> their_sort(["a", "b", "c"], [1.0, float("nan"), 5.0])
        ['a', 'b', 'c']

    `c` scores 5 and belongs first. It comes last. On RE1 Online Boutique this
    happens on 4 of the 125 cases, and on two of them it puts a column with no
    normal data at all in first place. That is a property of the baseline, so the
    reproduction has to show it; replacing the sort would hide it.
    """
    pairs = list(zip(columns, np.asarray(scores, dtype=np.float64).tolist(), strict=True))
    return [column for column, _ in sorted(pairs, key=lambda pair: pair[1], reverse=True)]


def count_non_finite(scores: npt.ArrayLike) -> int:
    """How many columns scored NaN or infinity - the cases where the sort breaks."""
    values = np.asarray(scores, dtype=np.float64)
    return int(np.count_nonzero(~np.isfinite(values)))


def our_nsigma_scores(normal: npt.ArrayLike, abnormal: npt.ArrayLike) -> FloatArray:
    """Our `NSIGMA`: the shift of the window mean, in normal standard deviations.

    A thin pass-through to :func:`pare.scores.nsigma_score`, here only so that the
    comparison reads as one formula against another instead of one import against
    another. Whatever that function does is what our engine does, by definition.
    """
    from pare.scores import nsigma_score

    return nsigma_score(normal, abnormal)
