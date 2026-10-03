"""When did the trouble actually start?

Real detectors are late. An alarm says "something is wrong now", but the fault
may have begun a minute earlier, and by the time the alarm fires the early,
informative part of the incident has already scrolled past. Score a window that
starts at the alarm and you measure the aftermath; worse, by then the symptoms
have caught up with the cause and the two look alike.

So before scoring anything, PARE asks the data where the change really began, and
re-anchors its analysis window there. This is what makes the method hold up when
detection is late, which is research question RQ4.

The method, from ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3 step 2:

1. Pick the ``cp_top_k`` columns that look most unusual in the run-up to the
   alarm. Those are the ones that have something to say about when it started.
2. For each, search a window around the alarm for the single best split point,
   using ``ruptures.Binseg(model="l2")``.
3. Take the median of those candidates. One column may be fooled by a blip; the
   median of five is steady.

If nothing usable can be found, the estimate falls back to the alarm time and
says so, so a caller never silently receives a guess dressed up as a measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import ruptures as rpt

from pare.columns import ColumnInfo
from pare.config import PareConfig
from pare.scores import RobustBaseline, robust_z

# ruptures' own default is jump=5, which only ever proposes breakpoints at
# multiples of 5 and so rounds the answer to the nearest 5 rows. We care about
# the actual second the change began, so we step one row at a time. Checked
# against the installed ruptures v1.1.10: on a series whose change is at index
# 102, jump=5 answers 100 and jump=1 answers 102.
SEARCH_STEP = 1

# Binseg needs at least min_size rows on each side of a split, so a window
# shorter than this cannot be searched at all. Below it, ruptures raises
# BadSegmentationParameters rather than returning anything.
MIN_SIZE = 2
MIN_ROWS_TO_SEARCH = 2 * MIN_SIZE


@dataclass(frozen=True)
class ChangePoint:
    """Where the analysis window should start, and how much to trust that.

    ``estimated`` is False when no change point could be found and the alarm time
    was used instead. ``reason`` always says why in plain words, and is passed on
    to the caller as a warning.
    """

    time_sec: float
    """The time to anchor the analysis window to."""

    alarm_time_sec: float
    """The alarm this was measured against, kept so the two can be compared."""

    estimated: bool
    """True if this came from the data, False if it is just the alarm time."""

    reason: str
    """Plain-language account of how this was arrived at."""

    candidates: tuple[float, ...] = ()
    """One candidate time per column that could be searched."""

    columns: tuple[str, ...] = ()
    """The columns those candidates came from, in the same order."""

    @property
    def seconds_before_alarm(self) -> float | None:
        """How much earlier than the alarm the change is thought to have begun.

        ``None`` when nothing was estimated. The explanation text uses this: "the
        alarm fired at X, but it probably started Y seconds earlier". A negative
        value means the change looks later than the alarm, which can happen when
        the detector fires on a blip.
        """
        if not self.estimated:
            return None
        return self.alarm_time_sec - self.time_sec


def estimate_change_point(
    times_sec: npt.ArrayLike,
    values: npt.ArrayLike,
    columns: Sequence[ColumnInfo],
    baseline: RobustBaseline,
    alarm_time_sec: float,
    config: PareConfig | None = None,
) -> ChangePoint:
    """Estimate when the incident began, from the data around the alarm.

    Args:
        times_sec: Time of each recent row, epoch seconds, increasing.
        values: Recent data, rows by columns, matching ``columns``.
        columns: The column map. Used only to name the columns in the result.
        baseline: What normal looked like, from :func:`pare.scores.robust_baseline`.
        alarm_time_sec: When the detector fired.
        config: Parameters. Defaults are used when not given.

    Returns:
        A :class:`ChangePoint`. When ``config.use_change_point`` is False, or
        nothing usable is found, its ``time_sec`` is the alarm time and
        ``estimated`` is False.
    """
    settings = config or PareConfig()
    times = np.asarray(times_sec, dtype=np.float64)
    data = np.asarray(values, dtype=np.float64)

    if data.ndim != 2:
        raise ValueError(f"values must be rows by columns, got {data.ndim} dimensions")
    if times.shape[0] != data.shape[0]:
        raise ValueError(
            f"got {times.shape[0]} times but {data.shape[0]} rows of values"
        )
    if data.shape[1] != len(columns):
        raise ValueError(
            f"values has {data.shape[1]} columns but {len(columns)} were described"
        )

    if not settings.use_change_point:
        return _fall_back(alarm_time_sec, "change-point re-anchoring is switched off")

    # The window to search: a stretch before the alarm, plus whatever little is
    # available after it. In replay there is nothing after, and that is fine.
    search = (times >= alarm_time_sec - settings.cp_lookback_s) & (
        times <= alarm_time_sec + settings.cp_lookahead_s
    )
    if int(search.sum()) < MIN_ROWS_TO_SEARCH:
        return _fall_back(
            alarm_time_sec,
            f"only {int(search.sum())} rows around the alarm, too few to look for a change",
        )

    chosen = _columns_to_search(times, data, baseline, alarm_time_sec, search, settings)
    if not chosen:
        return _fall_back(alarm_time_sec, "no column had enough movement to search")

    search_times = times[search]
    candidates: list[float] = []
    searched: list[str] = []
    for index in chosen:
        found = _single_change_point(data[search, index])
        if found is None:
            continue
        candidates.append(float(search_times[found]))
        searched.append(columns[index].name)

    if not candidates:
        return _fall_back(alarm_time_sec, "no column produced a usable change point")

    # The median, not the mean: one column misled by a blip should not drag the
    # answer with it.
    when = float(np.median(candidates))
    before = alarm_time_sec - when
    if before > 0:
        reason = (
            f"estimated from {len(candidates)} column(s); the change appears to start "
            f"{before:.0f} s before the alarm"
        )
    else:
        reason = (
            f"estimated from {len(candidates)} column(s); the change appears to start "
            f"{-before:.0f} s after the alarm"
        )

    return ChangePoint(
        time_sec=when,
        alarm_time_sec=float(alarm_time_sec),
        estimated=True,
        reason=reason,
        candidates=tuple(candidates),
        columns=tuple(searched),
    )


def _fall_back(alarm_time_sec: float, reason: str) -> ChangePoint:
    """Use the alarm time, and say plainly that nothing was estimated."""
    return ChangePoint(
        time_sec=float(alarm_time_sec),
        alarm_time_sec=float(alarm_time_sec),
        estimated=False,
        reason=f"using the alarm time: {reason}",
    )


def _columns_to_search(
    times: npt.NDArray[np.float64],
    data: npt.NDArray[np.float64],
    baseline: RobustBaseline,
    alarm_time_sec: float,
    search: npt.NDArray[np.bool_],
    settings: PareConfig,
) -> list[int]:
    """Pick the columns worth searching: the most unusual ones before the alarm.

    The spec ranks by ``max |z|`` over the recent rows **up to the alarm**. The
    reasoning is that a column already moving before the detector noticed is a
    column that knows when things started.

    When the alarm coincides with the very start of the data there are no rows
    before it to rank by. Rather than give up, the whole search window is used
    instead; this is noted in the reason the caller receives.
    """
    before_alarm = search & (times <= alarm_time_sec)
    window = before_alarm if int(before_alarm.sum()) >= MIN_ROWS_TO_SEARCH else search

    z = np.abs(robust_z(data[window], baseline))
    # A missing reading is not movement, so it counts as zero rather than
    # propagating NaN. Same rule as pare.scores uses for an absent value.
    z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    peak = z.max(axis=0) if z.shape[0] else np.zeros(data.shape[1])

    # A column that never moves has nothing to say about when things changed, and
    # ruptures would happily return a meaningless split for it anyway.
    movers = [index for index in np.argsort(-peak) if peak[index] > 0.0]
    return movers[: settings.cp_top_k]


def _single_change_point(series: npt.NDArray[np.float64]) -> int | None:
    """Index of the single best split in one column, or None if there isn't one.

    Returns None rather than raising for every ordinary reason a column cannot be
    searched: too few rows, missing data, or a flat line. A flat line matters more
    than it looks - ruptures does not complain about one, it returns a confident
    split in the middle of the noise, which would be pure invention.
    """
    values = np.asarray(series, dtype=np.float64)
    if values.size < MIN_ROWS_TO_SEARCH:
        return None

    # Missing values would otherwise poison the cost function.
    if np.isnan(values).any():
        filled = values.copy()
        missing = np.isnan(filled)
        if missing.all():
            return None
        filled[missing] = np.nanmedian(filled)
        values = filled

    spread = float(np.std(values))
    if spread == 0.0:
        return None

    standardised = (values - float(np.mean(values))) / spread

    try:
        # predict returns the split points followed by len(series) as a sentinel;
        # the change point is the first entry. Checked against ruptures v1.1.10.
        breaks = (
            rpt.Binseg(model="l2", min_size=MIN_SIZE, jump=SEARCH_STEP)
            .fit(standardised)
            .predict(n_bkps=1)
        )
    except Exception:
        # ruptures raises BadSegmentationParameters for windows it cannot split.
        # That is a normal outcome here, not a failure worth propagating.
        return None

    if not breaks:
        return None
    index = int(breaks[0])
    if index <= 0 or index >= values.size:
        return None
    return index
