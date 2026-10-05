"""Tests for the M2.4 comparison's own scoring and window logic.

Most of this file is about the parts that turn a ranking into a number, because
that is where a comparison between two methods goes wrong quietly: a window
boundary off by one row, or a service-level convention applied to one method and
not the other, moves the headline accuracy without anything looking broken.

The pure logic is tested without data. The few tests that need RE1-OB skip when
it is absent, like the adapter's.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.adapters.rcaeval import (
    INDICATOR_METRICS,
    UNAMBIGUOUS_FAULTS,
    Case,
)
from experiments.run_m24_compare import (
    LADDER,
    NORMAL_GAP_S,
    RECENT_AFTER_S,
    _best_rank,
    _masks,
    _raw_service_rank,
    _score_ranking,
    _service_of,
    _their_preprocess,
)

ROOT = Path(__file__).resolve().parents[2] / "data" / "RCAEval"
HAVE_DATA = (ROOT / "RE1" / "RE1-OB").exists()

needs_data = pytest.mark.skipif(
    not HAVE_DATA,
    reason="RE1-OB not downloaded; run experiments/download_rcaeval.py --dataset RE1-OB",
)

INJECT = 1_000_000


def make_case(fault_type: str = "MEM", gt_service: str = "cartservice") -> Case:
    """A Case with no files behind it, for the scoring tests."""
    indicator = f"{gt_service}_mem" if fault_type in ("CPU", "MEM") else None
    return Case(
        case_id=f"test-{gt_service}-{fault_type}",
        dataset="RE1",
        system="online-boutique",
        fault_type=fault_type,
        gt_service=gt_service,
        gt_indicator=indicator,
        acceptable_indicators=(f"{gt_service}_mem", f"{gt_service}_latency-90"),
        path=Path("nowhere") / f"{gt_service}_{fault_type.lower()}" / "1",
        inject_time_sec=INJECT,
        run="1",
    )


# --- the ladder -------------------------------------------------------------


def test_the_ladder_changes_exactly_one_thing_per_step():
    """Otherwise it cannot attribute a difference to anything, which is its job."""
    assert LADDER[0][1:] == ("theirs", "theirs", "theirs")
    assert LADDER[-1][1:] == ("ours", "ours", "ours")
    for (_, *before), (_, *after) in zip(LADDER, LADDER[1:], strict=False):
        differences = sum(1 for a, b in zip(before, after, strict=True) if a != b)
        assert differences == 1, f"{before} -> {after} moves {differences} things"


# --- windows ----------------------------------------------------------------


def test_their_windows_split_the_file_at_the_time_they_are_given():
    """Everything before is normal, everything after is abnormal, to the end."""
    times = pd.Series([INJECT - 100, INJECT - 1, INJECT, INJECT + 10_000])
    normal, abnormal = _masks(times, make_case(), delay_s=0.0, window="theirs")

    assert normal.tolist() == [True, True, False, False]
    # No gap before the injection, and no limit after it: their protocol keeps a
    # row 10 000 s later, which ours does not.
    assert abnormal.tolist() == [False, False, True, True]


def test_our_windows_keep_a_gap_before_the_injection_and_an_end_after_the_alarm():
    times = pd.Series(
        [
            INJECT - 100,  # normal
            INJECT - 1,  # inside the 30 s gap: neither window
            INJECT,  # abnormal
            INJECT + RECENT_AFTER_S + 1,  # past the end of our window
        ]
    )
    normal, abnormal = _masks(times, make_case(), delay_s=0.0, window="ours")

    assert normal.tolist() == [True, False, False, False]
    assert abnormal.tolist() == [False, False, True, False]


def test_a_delay_moves_the_alarm_but_not_our_normal_window():
    """Our normal period is anchored to the injection, the alarm is not.

    This is the stated assumption in `docs/05` and `docs/08`: the protocol gives
    every method the same normal data however late the alarm is. Their split
    moves both at once, which is why a delay sweep through their function is a
    different experiment - recorded in `run_rcaeval_baselines.py`.
    """
    times = pd.Series([INJECT - 100, INJECT + 10, INJECT + 50])
    ours_normal, ours_abnormal = _masks(times, make_case(), delay_s=60.0, window="ours")
    theirs_normal, _ = _masks(times, make_case(), delay_s=60.0, window="theirs")

    assert ours_normal.tolist() == [True, False, False]
    assert not ours_abnormal.any(), "nothing yet at alarm = inject + 60"
    # Theirs has absorbed the two post-injection rows into its normal period.
    assert theirs_normal.tolist() == [True, True, True]

    assert NORMAL_GAP_S == 30.0, "the gap in `docs/05`; change both or neither"


# --- their preprocessing ----------------------------------------------------


def test_their_preprocess_drops_both_time_columns_and_constants():
    frame = pd.DataFrame(
        {
            "time": [1, 2, 3],
            "time.1": [1, 2, 3],
            "a_cpu": [1.0, 1.0, 1.0],  # constant: dropped
            "a_latency": [1.0, 2.0, 3.0],
        }
    )
    out = _their_preprocess(frame)
    assert list(out.columns) == ["a_latency"]


def test_their_preprocess_keeps_an_all_nan_column():
    """Because `NaN != NaN`, so it never looks constant to them.

    This is why their NSigma can rank a column with no normal data at all first,
    and it is the reason four of the 125 cases produce a NaN score.
    """
    frame = pd.DataFrame({"time": [1, 2, 3], "a_error": [np.nan] * 3})
    assert list(_their_preprocess(frame).columns) == ["a_error"]


def test_their_preprocess_converts_memory_to_megabytes():
    frame = pd.DataFrame({"time": [1, 2], "a_mem": [2e6, 4e6], "a_cpu": [1.0, 2.0]})
    out = _their_preprocess(frame)
    assert out["a_mem"].tolist() == [2.0, 4.0]
    assert out["a_cpu"].tolist() == [1.0, 2.0], "only _mem is converted"


# --- service-level scoring --------------------------------------------------


def test_our_service_order_is_first_appearance_in_the_column_ranking():
    """Which is the same as sorting services by their best column's score.

    Worth pinning, because the whole service-level comparison rests on the two
    being the same thing: it is what lets their column ranking be scored under our
    convention without re-running anything.
    """
    case = make_case(gt_service="cartservice")
    row = _score_ranking(
        method="T",
        case=case,
        delay_s=0.0,
        runtime_s=0.0,
        ranked_columns=("frontend_latency", "frontend_cpu", "cartservice_mem"),
        scores={"frontend_latency": 9.0, "frontend_cpu": 8.0, "cartservice_mem": 7.0},
        n_candidates=3,
        error=None,
    )
    assert row.service_order == ("frontend", "cartservice")
    assert row.rank_service_distinct.best == 2


def test_the_two_service_conventions_differ_above_rank_one():
    """Theirs reads the top k columns; ours reads the top k distinct services.

    With one service owning the first two columns, the truth is the 2nd distinct
    service but the 3rd column. At k=1 both agree; at k=2 they do not. Reporting
    only one of the two would move the numbers for a reason unrelated to method
    quality, so both are kept.
    """
    case = make_case(gt_service="cartservice")
    columns = ("frontend_latency", "frontend_cpu", "cartservice_mem")
    row = _score_ranking(
        method="T",
        case=case,
        delay_s=0.0,
        runtime_s=0.0,
        ranked_columns=columns,
        scores=dict(zip(columns, [9.0, 8.0, 7.0], strict=True)),
        n_candidates=3,
        error=None,
    )
    assert row.rank_service_distinct.best == 2  # ours
    assert row.rank_service_raw.best == 3  # theirs


def test_raw_service_rank_is_none_when_the_truth_never_appears():
    assert _raw_service_rank(["frontend", "adservice"], "cartservice") is None


def test_service_of_recovers_the_service_from_a_column_name():
    assert _service_of("cartservice_latency-90") == "cartservice"
    assert _service_of("frontend_mem") == "frontend"
    # No separator at all: the whole name, rather than an empty service that
    # would silently group unrelated columns together.
    assert _service_of("weird") == "weird"


# --- indicator scoring ------------------------------------------------------


def test_strict_indicator_rank_is_empty_when_the_fault_has_no_matching_metric():
    """Open question 6: DISK, DELAY and LOSS have no unambiguous indicator.

    The strict number must therefore skip those cases rather than score them
    against a guess.
    """
    case = make_case(fault_type="DISK")
    assert case.gt_indicator is None

    columns = ("cartservice_mem", "cartservice_latency-90")
    row = _score_ranking(
        method="T",
        case=case,
        delay_s=0.0,
        runtime_s=0.0,
        ranked_columns=columns,
        scores=dict(zip(columns, [9.0, 8.0], strict=True)),
        n_candidates=2,
        error=None,
    )
    assert row.rank_indicator_strict is None
    assert row.rank_indicator_loose is not None, "the loose number still applies"


def test_the_loose_rank_is_the_best_any_acceptable_indicator_reached():
    scores = {"other_cpu": 9.0, "cartservice_latency-90": 8.0, "cartservice_mem": 1.0}
    ordered = ("other_cpu", "cartservice_latency-90", "cartservice_mem")
    rank = _best_rank(ordered, scores, ("cartservice_mem", "cartservice_latency-90"))
    assert rank.best == 2, "the better-placed of the two acceptable answers"


def test_the_loose_rank_is_none_when_no_acceptable_indicator_was_ranked():
    assert _best_rank(("a_cpu",), {"a_cpu": 1.0}, ("b_mem",)) is None


def test_an_unambiguous_fault_has_exactly_one_acceptable_indicator():
    """The whole settlement of open question 6 rests on this.

    The headline ExpAC@k is strict and covers only CPU and MEM; a secondary table
    reports the loose score per fault type. That split is only honest if the loose
    definition changes nothing on the cases the strict one covers - otherwise the
    two headline numbers would differ partly because the scoring was loosened, and
    the higher one would be a choice rather than a measurement.

    It holds because an unambiguous fault's acceptable set has one member, so the
    loose rank is forced to equal the strict one. Asserted against the adapter's
    real mapping, so adding a metric to CPU or MEM breaks this test rather than
    quietly invalidating the paper's claim.
    """
    for fault in sorted(UNAMBIGUOUS_FAULTS):
        assert len(INDICATOR_METRICS[fault]) == 1, (
            f"{fault} is listed as unambiguous but accepts "
            f"{INDICATOR_METRICS[fault]}; either the fault is not unambiguous or "
            f"docs/08 section 4 no longer holds"
        )
    for fault, metrics in INDICATOR_METRICS.items():
        if fault not in UNAMBIGUOUS_FAULTS:
            assert len(metrics) > 1, (
                f"{fault} accepts one metric but is not listed as unambiguous"
            )


def test_strict_and_loose_ranks_agree_on_an_unambiguous_case():
    """The same claim, exercised through the scoring path rather than the mapping."""
    case = make_case(fault_type="CPU", gt_service="cartservice")
    # The real adapter would give a one-member acceptable set here; `make_case`
    # deliberately gives two, so this test fails if the scoring path stops
    # deriving the strict answer from the first acceptable metric.
    columns = ("cartservice_mem", "frontend_latency")
    row = _score_ranking(
        method="T",
        case=case,
        delay_s=0.0,
        runtime_s=0.0,
        ranked_columns=columns,
        scores=dict(zip(columns, [9.0, 1.0], strict=True)),
        n_candidates=2,
        error=None,
    )
    assert case.gt_indicator == "cartservice_mem"
    assert row.rank_indicator_strict.best == 1
    assert row.rank_indicator_loose.best == 1


@needs_data
def test_the_written_results_keep_strict_and_loose_equal_where_both_apply():
    """The claim again, on the 125-case run's actual output.

    The two unit tests above constrain the mapping and the scoring helper. This one
    checks the file the paper's numbers come from, which is the thing that would
    actually be wrong.
    """
    path = Path(__file__).resolve().parents[1] / "results" / "m2_4" / "cases.csv"
    if not path.exists():
        pytest.skip("M2.4 has not been run; see run_m24_compare.py")

    frame = pd.read_csv(path)
    both = frame[frame["rank_gt_indicator"].notna()]
    assert len(both) > 0, "no case had an unambiguous indicator"
    assert (both["rank_gt_indicator"] == both["rank_gt_indicator_loose"]).all()
    assert (both["tied_gt_indicator"] == both["tied_gt_indicator_loose"]).all()

    # And the loose column is filled in everywhere, which is what lets the
    # secondary table cover all 125 cases.
    assert frame["rank_gt_indicator_loose"].notna().all()


# --- ground truth never reaches a method ------------------------------------


@needs_data
def test_their_half_records_no_ground_truth():
    """Hard rule 4, checked on the file their script actually wrote.

    `run_rcaeval_baselines.py` never reads the answer, so the JSONL it produces
    cannot carry one. Asserted on the keys rather than trusted to the docstring.
    """
    import json

    path = Path(__file__).resolve().parents[1] / "results" / "m2_4" / "rcaeval_rankings.jsonl"
    if not path.exists():
        pytest.skip("their half has not been run; see run_rcaeval_baselines.py")

    with path.open(encoding="utf-8") as handle:
        record = json.loads(handle.readline())

    forbidden = {"gt_service", "gt_indicator", "ground_truth", "answer", "root_cause"}
    assert forbidden.isdisjoint(record), f"ground truth leaked into {path.name}"
