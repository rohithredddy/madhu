"""Tests for change-point re-anchoring.

docs/05 section 6 sets the bar: "a step series with a known change at index 100
is found within +/- 3 rows". That is the first test here. The rest cover the
thing this module exists for - that a late alarm still finds the real start - and
the ways it can fail, since a wrong change point would silently move the analysis
window and quietly corrupt every score downstream.
"""

import numpy as np
import pytest

from pare.changepoint import estimate_change_point
from pare.columns import ColumnInfo
from pare.config import PareConfig
from pare.scores import robust_baseline
from pare.synthetic import make_case

START = 1_700_000_000


def one_column(values, name="svc_latency"):
    """Wrap a single series as the (times, values, columns) the function takes."""
    values = np.asarray(values, dtype=np.float64)
    times = START + np.arange(values.size, dtype=np.float64)
    columns = [ColumnInfo(name, name.split("_")[0], name.split("_")[1])]
    return times, values.reshape(-1, 1), columns


def step_series(change_at=100, total=200, size=6.0, seed=0):
    """Quiet, then a sustained shift. The textbook case."""
    rng = np.random.default_rng(seed)
    before = rng.normal(0.0, 1.0, change_at)
    after = rng.normal(size, 1.0, total - change_at)
    return np.concatenate([before, after])


# --- the bar set by the spec ------------------------------------------------


def test_a_step_at_index_100_is_found_within_three_rows():
    """docs/05 section 6, word for word."""
    values = step_series(change_at=100)
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[:100].reshape(-1, 1))

    # the alarm comes late, at row 140, which is the situation this exists for
    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 140,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )

    assert found.estimated
    assert abs(found.time_sec - (START + 100)) <= 3


@pytest.mark.parametrize("change_at", [40, 77, 100, 102, 150])
def test_the_change_is_found_wherever_it_is(change_at):
    """Including positions that are not multiples of 5: ruptures' default jump
    would round those, which is why this module sets jump=1."""
    values = step_series(change_at=change_at, total=220)
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[: max(change_at - 5, 10)].reshape(-1, 1))

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 200,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )
    assert abs(found.time_sec - (START + change_at)) <= 3


# --- the point of the whole module -----------------------------------------


def test_a_late_alarm_still_points_back_to_the_real_start():
    """The reason this step exists: a detector that fires 60 rows late should not
    drag the analysis window 60 rows late with it."""
    values = step_series(change_at=100, total=260)
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[:100].reshape(-1, 1))

    late = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 160,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )

    assert late.estimated
    assert abs(late.time_sec - (START + 100)) <= 3
    assert late.seconds_before_alarm == pytest.approx(60.0, abs=3.0)


def test_switching_re_anchoring_off_returns_the_alarm_time():
    values = step_series()
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[:100].reshape(-1, 1))

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 140,
        config=PareConfig(use_change_point=False),
    )

    assert not found.estimated
    assert found.time_sec == START + 140
    assert found.seconds_before_alarm is None
    assert "switched off" in found.reason


# --- several columns --------------------------------------------------------


def test_the_median_of_several_columns_ignores_one_misleading_column():
    """One column fooled by a blip should not drag the answer with it."""
    rng = np.random.default_rng(1)
    agree = [step_series(change_at=100, seed=s) for s in range(4)]
    # a column whose only event is a single early spike
    odd = rng.normal(0.0, 1.0, 200)
    odd[20] = 40.0

    values = np.column_stack([*agree, odd])
    times = START + np.arange(200, dtype=np.float64)
    columns = [
        ColumnInfo(f"svc{i}_latency", f"svc{i}", "latency") for i in range(values.shape[1])
    ]
    baseline = robust_baseline(values[:100])

    found = estimate_change_point(
        times, values, columns, baseline, alarm_time_sec=START + 150,
        config=PareConfig(cp_top_k=5, cp_lookback_s=300, cp_lookahead_s=60),
    )

    assert abs(found.time_sec - (START + 100)) <= 3
    assert len(found.candidates) >= 3


def test_only_cp_top_k_columns_are_searched():
    values = np.column_stack([step_series(seed=s) for s in range(8)])
    times = START + np.arange(200, dtype=np.float64)
    columns = [ColumnInfo(f"svc{i}_latency", f"svc{i}", "latency") for i in range(8)]
    baseline = robust_baseline(values[:100])

    found = estimate_change_point(
        times, values, columns, baseline, alarm_time_sec=START + 150,
        config=PareConfig(cp_top_k=3, cp_lookback_s=300, cp_lookahead_s=60),
    )
    assert len(found.candidates) <= 3
    assert len(found.columns) == len(found.candidates)


# --- when it cannot find anything ------------------------------------------


def test_a_flat_column_does_not_produce_an_invented_change_point():
    """ruptures does not complain about a flat line, it returns a confident split
    in the middle of nothing. That would be pure invention, so it is filtered."""
    values = np.full(200, 7.0)
    times, data, columns = one_column(values)
    baseline = robust_baseline(data[:100])

    found = estimate_change_point(times, data, columns, baseline, alarm_time_sec=START + 150)

    assert not found.estimated
    assert found.time_sec == START + 150


def test_pure_noise_with_no_change_falls_back_or_stays_vague():
    """There is no right answer in noise; what matters is that the window still
    starts somewhere sane rather than at a wild time."""
    rng = np.random.default_rng(2)
    values = rng.normal(0.0, 1.0, 200)
    times, data, columns = one_column(values)
    baseline = robust_baseline(data[:100])

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 150,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )
    assert START <= found.time_sec <= START + 200


def test_too_few_rows_around_the_alarm_falls_back():
    times, data, columns = one_column([1.0, 2.0])
    baseline = robust_baseline(data)

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 1,
        config=PareConfig(cp_lookback_s=0.5, cp_lookahead_s=0.0),
    )
    assert not found.estimated
    assert "too few" in found.reason


def test_an_all_missing_column_is_skipped_not_crashed_on():
    values = np.column_stack([np.full(200, np.nan), step_series()])
    times = START + np.arange(200, dtype=np.float64)
    columns = [
        ColumnInfo("dead_latency", "dead", "latency"),
        ColumnInfo("live_latency", "live", "latency"),
    ]
    baseline = robust_baseline(values[:100])

    found = estimate_change_point(
        times, values, columns, baseline, alarm_time_sec=START + 150,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )
    assert found.estimated
    assert "dead_latency" not in found.columns


def test_scattered_missing_values_are_tolerated():
    values = step_series(change_at=100)
    values[[10, 55, 130]] = np.nan
    times, data, columns = one_column(values)
    baseline = robust_baseline(data[:100])

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 150,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )
    assert abs(found.time_sec - (START + 100)) <= 5


# --- the search window ------------------------------------------------------


def test_the_lookback_limits_how_far_back_it_will_look():
    """A change well outside the lookback window cannot be found, and the result
    must not pretend otherwise."""
    values = step_series(change_at=20, total=400)
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[:20].reshape(-1, 1))

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 380,
        config=PareConfig(cp_lookback_s=30, cp_lookahead_s=0),
    )
    # the real change at row 20 is far outside [350, 380]
    assert found.time_sec >= START + 350


def test_zero_lookahead_is_the_replay_case():
    """In replay nothing after the alarm has been played, so the search must work
    with the lookback alone."""
    values = step_series(change_at=100, total=200)
    times, data, columns = one_column(values)
    baseline = robust_baseline(values[:100].reshape(-1, 1))

    found = estimate_change_point(
        times, data, columns, baseline, alarm_time_sec=START + 140,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=0.0),
    )
    assert found.estimated
    assert abs(found.time_sec - (START + 100)) <= 3


# --- input checking ---------------------------------------------------------


def test_input_shapes_are_checked():
    times, data, columns = one_column(step_series())
    baseline = robust_baseline(data[:100])

    with pytest.raises(ValueError, match="rows by columns"):
        estimate_change_point(times, data.ravel(), columns, baseline, START)
    with pytest.raises(ValueError, match="but 1 rows of values"):
        estimate_change_point(times, data[:1], columns, baseline, START)
    with pytest.raises(ValueError, match="were described"):
        estimate_change_point(times, data, columns * 2, baseline, START)


# --- against generated data we know the answer for -------------------------


def test_on_a_synthetic_case_it_finds_the_injection_time():
    """End to end on data where the true start is known exactly."""
    case = make_case(
        n_services=6, n_normal=400, n_abnormal=200, fault="latency", seed=11
    )
    frame = case.to_frame()
    baseline = robust_baseline(case.normal.to_numpy())

    # pretend the detector was 45 seconds late
    alarm = case.inject_time_sec + 45
    found = estimate_change_point(
        frame.index.to_numpy(dtype=np.float64),
        frame.to_numpy(),
        case.columns,
        baseline,
        alarm_time_sec=alarm,
        config=PareConfig(cp_lookback_s=300, cp_lookahead_s=60),
    )

    assert found.estimated
    assert abs(found.time_sec - case.inject_time_sec) <= 5, (
        f"estimated {found.time_sec - case.inject_time_sec:+.0f}s from the real injection"
    )


def test_an_on_time_alarm_still_finds_the_change_from_the_faulty_column():
    """Decision 84. With the alarm exactly at the change there is no fault data
    before it, so ranking columns by their movement *before the alarm* picked the
    noisiest normal columns and split them in noise - on RE1 the change point
    landed a median 73.5 s early. Columns are now ranked over the searched window,
    which includes the rows after the alarm.

    Five normal columns, one of which had a brief unrelated burst well before the
    alarm (real telemetry has these), plus one that steps at the alarm. The old rule
    ranked the burst column first and split it at the burst; the estimate must come
    from the column that actually changed.
    """
    rng = np.random.default_rng(3)
    total, change_at = 400, 340
    noisy = rng.normal(0.0, 1.0, (total, 5))
    noisy[150:160, 0] += 6.0  # a burst, 190 rows before the alarm
    faulty = step_series(change_at=change_at, total=total, size=8.0, seed=4).reshape(-1, 1)
    values = np.hstack([noisy, faulty])
    times = START + np.arange(total, dtype=np.float64)
    columns = [ColumnInfo(f"s{i}_x", f"s{i}", "x") for i in range(6)]
    baseline = robust_baseline(values[:250])
    settings = PareConfig(cp_top_k=1, cp_lookback_s=300, cp_lookahead_s=60)

    found = estimate_change_point(times, values, columns, baseline, START + change_at, settings)

    assert found.estimated
    assert found.columns == ("s5_x",)
    assert abs(found.time_sec - (START + change_at)) <= 3
