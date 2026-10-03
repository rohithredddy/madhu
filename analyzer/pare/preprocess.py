"""Step 0: tidy the data before anything tries to score it.

Real telemetry has holes and dead columns. Left alone they do not merely add
noise, they produce confident nonsense: a column that is constant in the normal
period has no spread, so any movement at all divides by almost nothing and scores
enormously. Dropping those columns is not tidiness, it is the difference between a
ranking that means something and one that is led by whichever metric was broken
at collection time.

What happens here, from ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3, step 0:

* drop a column that is missing for more than ``max_nan_fraction`` of the normal
  period - too little is known about it to say what normal means;
* fill short gaps, forward then backward, up to ``fill_limit`` rows;
* drop a column that never moves during the normal period;
* say so, in words, for every column dropped.

Nothing is standardised here. Each later step scales things its own way, and
doing it twice would quietly change what the scores mean.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pare.columns import ColumnInfo
from pare.config import PareConfig

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Preprocessed:
    """The data that survived, and an account of what did not."""

    columns: list[ColumnInfo]
    normal: FloatArray
    recent: FloatArray
    warnings: list[str]
    dropped: list[str]

    @property
    def is_empty(self) -> bool:
        return not self.columns


def preprocess(
    normal: npt.ArrayLike,
    recent: npt.ArrayLike,
    columns: Sequence[ColumnInfo],
    config: PareConfig | None = None,
) -> Preprocessed:
    """Clean both windows together, keeping their columns aligned.

    Both windows are filtered by the same decision, taken on the normal period
    only. The abnormal window must not get a say in which columns are worth
    looking at - that is the window containing the fault, and letting it choose
    would be letting the answer pick the question.
    """
    settings = config or PareConfig()

    normal_values = _as_block(normal, len(columns), "normal")
    recent_values = _as_block(recent, len(columns), "recent")

    keep: list[int] = []
    dropped: list[str] = []
    warnings: list[str] = []

    for index, column in enumerate(columns):
        series = normal_values[:, index]
        missing = float(np.mean(np.isnan(series)))

        if missing > settings.max_nan_fraction:
            dropped.append(column.name)
            warnings.append(
                f"dropped {column.name}: missing for {missing:.0%} of the normal period"
            )
            continue

        filled = _fill_short_gaps(series, settings.fill_limit)
        if _never_moves(filled):
            dropped.append(column.name)
            warnings.append(f"dropped {column.name}: never changes during the normal period")
            continue

        keep.append(index)

    if not keep:
        warnings.append("no column survived cleaning; there is nothing to analyse")
        return Preprocessed(
            columns=[],
            normal=np.empty((normal_values.shape[0], 0)),
            recent=np.empty((recent_values.shape[0], 0)),
            warnings=warnings,
            dropped=dropped,
        )

    clean_normal = np.column_stack(
        [_fill_short_gaps(normal_values[:, index], settings.fill_limit) for index in keep]
    )
    clean_recent = np.column_stack(
        [_fill_short_gaps(recent_values[:, index], settings.fill_limit) for index in keep]
    )

    return Preprocessed(
        columns=[columns[index] for index in keep],
        normal=clean_normal,
        recent=clean_recent,
        warnings=warnings,
        dropped=dropped,
    )


def _fill_short_gaps(series: FloatArray, limit: int) -> FloatArray:
    """Forward-fill then back-fill runs of missing values up to ``limit`` long.

    A longer run is left missing on purpose. Carrying a value across a long gap
    invents data, and the later steps all cope with NaN; pretending a metric held
    steady for two minutes because nobody was collecting it does not.
    """
    if limit <= 0 or series.size == 0:
        return series.astype(np.float64, copy=True)

    out = series.astype(np.float64, copy=True)
    missing = np.isnan(out)
    if not missing.any():
        return out

    for run_start, run_end in _runs_of(missing):
        if run_end - run_start > limit:
            continue
        if run_start > 0:
            out[run_start:run_end] = out[run_start - 1]
        elif run_end < out.size:
            out[run_start:run_end] = out[run_end]
    return out


def _runs_of(flags: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    """Start and end of each run of True, as half-open ranges."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for position, flag in enumerate(flags):
        if flag and start is None:
            start = position
        elif not flag and start is not None:
            runs.append((start, position))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _never_moves(series: FloatArray) -> bool:
    """True when a column is flat over the normal period.

    Both measures have to agree, as the spec says: the MAD can be zero for a
    column that is mostly one value but does occasionally jump, and that column
    still carries information.
    """
    usable = series[~np.isnan(series)]
    if usable.size == 0:
        return True
    spread = float(np.std(usable))
    deviation = float(np.median(np.abs(usable - np.median(usable))))
    return spread == 0.0 and deviation == 0.0


def _as_block(values: npt.ArrayLike, n_columns: int, label: str) -> FloatArray:
    data = np.asarray(values, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"{label} must be rows by columns, got {data.ndim} dimensions")
    if data.shape[1] != n_columns:
        raise ValueError(
            f"{label} has {data.shape[1]} columns but {n_columns} were described"
        )
    return data
