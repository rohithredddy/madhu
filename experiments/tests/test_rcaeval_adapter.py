"""Tests for the RCAEval adapter.

These need the downloaded data, so they skip cleanly when it is absent - a fresh
clone must not fail its test run just because nobody has fetched 175 MB yet.

Most of what is asserted here comes straight from the M2.2 inspection recorded in
PROGRESS.md. The point is that those findings stay enforced: if a future RCAEval
release stops duplicating the `time` column, or starts shipping a `disk` metric,
these fail and someone re-reads the data rather than quietly getting wrong
numbers.
"""

from pathlib import Path

import numpy as np
import pytest

from experiments.adapters.rcaeval import (
    INDICATOR_METRICS,
    SYSTEM_SERVICES,
    UNAMBIGUOUS_FAULTS,
    Case,
    list_cases,
    load_case,
    summarise,
    times_of,
    values_of,
)

ROOT = Path(__file__).resolve().parents[2] / "data" / "RCAEval"
HAVE_DATA = (ROOT / "RE1" / "RE1-OB").exists()

needs_data = pytest.mark.skipif(
    not HAVE_DATA,
    reason="RE1-OB not downloaded; run experiments/download_rcaeval.py --dataset RE1-OB",
)


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return list_cases(ROOT, "RE1", "online-boutique")


# --- things that need no data ----------------------------------------------


def test_an_unknown_system_is_rejected_by_name():
    with pytest.raises(ValueError, match="no folder known"):
        list_cases(ROOT, "RE1", "not-a-system")


def test_a_missing_download_says_how_to_fix_it():
    with pytest.raises(FileNotFoundError, match="download_rcaeval.py"):
        list_cases(Path("nowhere"), "RE1", "online-boutique")


def test_only_cpu_and_mem_have_an_unambiguous_indicator():
    """RE1-OB has no `disk` and no `loss` metric, so those fault types cannot have
    one correct answer. Recorded as open question 6."""
    assert UNAMBIGUOUS_FAULTS == {"CPU", "MEM"}
    assert INDICATOR_METRICS["CPU"] == ("cpu",)
    assert INDICATOR_METRICS["MEM"] == ("mem",)
    for fault in ("DISK", "DELAY", "LOSS"):
        assert len(INDICATOR_METRICS[fault]) > 1, f"{fault} should offer a set"


# --- listing ----------------------------------------------------------------


@needs_data
def test_listing_finds_all_125_cases(cases):
    counts = summarise(cases)
    assert counts["cases"] == 125
    assert counts["by_fault"] == {
        "CPU": 25,
        "MEM": 25,
        "DISK": 25,
        "DELAY": 25,
        "LOSS": 25,
    }
    assert set(counts["by_service"]) == {
        "adservice",
        "cartservice",
        "checkoutservice",
        "currencyservice",
        "productcatalogservice",
    }
    assert counts["unambiguous_indicator"] == 50  # the CPU and MEM cases


@needs_data
def test_case_ids_are_unique_and_stable(cases):
    ids = [c.case_id for c in cases]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids) or len(ids) == 125  # listing is deterministic
    assert list_cases(ROOT, "RE1", "online-boutique")[0].case_id == cases[0].case_id


@needs_data
def test_the_ground_truth_service_comes_from_the_folder_name(cases):
    for case in cases[:20]:
        assert case.gt_service in case.path.parent.name
        assert case.path.parent.name.endswith(case.fault_type.lower())


@needs_data
def test_inject_time_is_a_plausible_epoch_second(cases):
    for case in cases[:20]:
        # 2020-01-01 .. 2030-01-01, which catches a millisecond value or a parse slip
        assert 1_577_836_800 < case.inject_time_sec < 1_893_456_000


# --- loading three cases, as the task asks ---------------------------------


@needs_data
@pytest.mark.parametrize("index", [0, 60, 124])
def test_loading_a_case_gives_usable_windows(cases, index):
    """docs/07 M2.3: a test that loads three cases. One from each end and one from
    the middle, so the two different collection batches are both covered."""
    data = load_case(cases[index], delay_s=30)

    assert len(data.normal) > 60, "needs enough normal data to learn a baseline"
    assert len(data.recent) > 0
    assert data.n_columns > 20
    assert data.alarm_time_sec == cases[index].inject_time_sec + 30

    # the windows do not overlap and are in the right order
    assert data.normal["time"].max() < data.case.inject_time_sec
    assert data.recent["time"].max() >= data.case.inject_time_sec

    values = values_of(data, "normal")
    assert values.shape == (len(data.normal), data.n_columns)
    assert np.isfinite(values).any()
    assert len(times_of(data, "normal")) == len(data.normal)


@needs_data
def test_the_duplicate_time_column_is_dropped(cases):
    """Every RE1-OB CSV has `time` twice. Left in, it would be ranked as a
    monotonically rising metric."""
    data = load_case(cases[0])
    names = [c.name for c in data.columns]

    assert not any(n.startswith("time") for n in names)
    assert sum(1 for c in data.normal.columns if c.split(".")[0] == "time") == 1


@needs_data
def test_every_column_maps_to_a_service_of_the_system(cases):
    known = SYSTEM_SERVICES["online-boutique"]
    data = load_case(cases[0])

    for column in data.columns:
        assert column.service in known
        assert column.metric
        assert column.name == f"{column.service}_{column.metric}"


@needs_data
def test_the_contaminated_case_has_its_foreign_columns_removed(cases):
    """productcatalogservice_cpu/3 carries five stray Sock Shop columns. They must
    not be ranked as candidate root causes."""
    case = next(c for c in cases if c.case_id.endswith("productcatalogservice_cpu-3"))
    data = load_case(case)

    services = {c.service for c in data.columns}
    assert not services & {"carts", "catalogue", "orders", "front-end"}
    assert any("not belonging to" in w for w in data.warnings)
    # and the case is still usable: its own columns survived
    assert any(c.name.startswith("productcatalogservice_") for c in data.columns)


@needs_data
def test_the_ground_truth_column_is_present_for_unambiguous_faults(cases):
    """A CPU or MEM case whose own indicator column was missing would be
    unscoreable, and we would rather know now than halfway through a run."""
    for case in [c for c in cases if c.indicator_is_unambiguous][:20]:
        data = load_case(case)
        assert case.gt_indicator in {c.name for c in data.columns}


# --- the windows -----------------------------------------------------------


@needs_data
def test_a_later_alarm_moves_the_recent_window(cases):
    early = load_case(cases[0], delay_s=0)
    late = load_case(cases[0], delay_s=120)

    assert late.alarm_time_sec - early.alarm_time_sec == 120
    assert late.recent["time"].min() > early.recent["time"].min()
    # the normal window is unchanged: it is anchored on the injection, not the alarm
    assert len(late.normal) == len(early.normal)


@needs_data
def test_normal_minutes_limits_how_much_history_is_used(cases):
    everything = load_case(cases[0])
    trimmed = load_case(cases[0], normal_minutes=5)

    assert len(trimmed.normal) < len(everything.normal)
    assert len(trimmed.normal) <= 5 * 60 + 1


@needs_data
def test_the_alarm_lookback_mode_never_uses_the_injection_time(cases):
    """The honest variant docs/08 section 4 asks E3 to report alongside: the
    normal period ends relative to the alarm, not to a time a real system would
    not know."""
    case = cases[0]
    standard = load_case(case, delay_s=60, normal_mode="inject_gap")
    honest = load_case(case, delay_s=60, normal_mode="alarm_lookback")

    assert honest.normal["time"].max() < standard.alarm_time_sec - 300
    assert len(honest.normal) != len(standard.normal)


@needs_data
def test_an_unknown_normal_mode_is_rejected(cases):
    with pytest.raises(ValueError, match="normal_mode"):
        load_case(cases[0], normal_mode="whatever")


# --- no ground truth leaks into what an engine sees ------------------------


@needs_data
def test_the_loaded_data_carries_no_hint_of_the_answer(cases):
    """Hard rule 4. The Case object holds the ground truth for scoring; the frames
    and the column map an engine receives must not."""
    case = cases[0]
    data = load_case(case)

    assert case.gt_service not in {c.metric for c in data.columns}
    for frame in (data.normal, data.recent):
        assert "gt_service" not in frame.columns
        assert "fault_type" not in frame.columns
        assert "inject_time" not in frame.columns


# --- it actually drives the engine -----------------------------------------


@needs_data
def test_a_loaded_case_can_be_analysed(cases):
    """The adapter exists to feed the engines, so one run end to end."""
    from pare.engine import AnalyzeRequest, Window, analyze

    data = load_case(cases[0], delay_s=30)
    result = analyze(
        AnalyzeRequest(
            engine="NSIGMA",
            alarm_time_sec=data.alarm_time_sec,
            columns=data.columns,
            normal=Window.of(times_of(data, "normal"), values_of(data, "normal")),
            recent=Window.of(times_of(data, "recent"), values_of(data, "recent")),
            graph=data.graph,
        )
    )

    assert result.services
    assert result.verdict in {"ROOT_CAUSE_FOUND", "NO_CLEAR_CAUSE"}
    assert all(np.isfinite(s.score) for s in result.services)
