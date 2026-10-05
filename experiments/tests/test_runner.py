"""Tests for the shared experiment runner and the E1 script's configuration.

`runner.py` is the single place that turns an engine's answer into a row of
`cases.csv`, so from M3 onward every paper number passes through it. These tests
cover the three things that would corrupt results silently rather than loudly: the
contract's column list drifting, ground truth reaching an engine, and a failed run
being written as if it were a bad score.

The tests that need the benchmark skip without it, as the adapter's do.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from experiments.run_c1_grounding import _read_config, _summarise
from experiments.runner import (
    CASES_CSV_COLUMNS,
    CaseRow,
    ranks_from,
    run_case,
    symptom_rate,
    write_run,
)

ROOT = Path(__file__).resolve().parents[2] / "data" / "RCAEval"
HAVE_DATA = (ROOT / "RE1" / "RE1-OB").exists()

needs_data = pytest.mark.skipif(
    not HAVE_DATA,
    reason="RE1-OB not downloaded; run experiments/download_rcaeval.py --dataset RE1-OB",
)


@pytest.fixture(scope="module")
def one_case():
    from experiments.adapters.rcaeval import list_cases

    return list_cases(ROOT, "RE1", "online-boutique")[0]


# --- the contract -----------------------------------------------------------


def test_the_column_list_matches_docs_06_section_5():
    """Pinned against the doc, in order, because the order is part of the format.

    If `docs/06` section 5 changes, this test fails and the two are brought back
    into step deliberately - which is what hard rule 6 asks for.
    """
    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "06_DATA_CONTRACTS.md"
    ).read_text(encoding="utf-8")
    block = doc.split("Per-case results `experiments/results/<run_id>/cases.csv`")[1]
    block = block.split("```")[1]
    declared = tuple(
        name.strip() for name in block.replace("\n", " ").split(",") if name.strip()
    )
    assert declared == CASES_CSV_COLUMNS


def test_a_written_run_has_exactly_the_contract_columns(tmp_path: Path):
    row = CaseRow(
        run_id="t", dataset="RE1", system="online-boutique", case_id="c",
        fault_type="CPU", gt_service="a", gt_indicator="a_cpu", method="ECDF",
        delay_s=0.0, seed=42, rank_gt_service=1, rank_gt_indicator=1,
        rank_gt_indicator_loose=1, top1_service="a", top1_indicator="a_cpu",
        tied_gt_service=1, tied_gt_indicator=1, tied_gt_indicator_loose=1,
        symptom_error=False, verdict="ROOT_CAUSE_FOUND", runtime_s=0.1,
    )
    write_run([row], tmp_path, {"run_id": "t"}, ["a line"])

    frame = pd.read_csv(tmp_path / "cases.csv")
    assert tuple(frame.columns) == CASES_CSV_COLUMNS
    # `error` is useful but is not in the contract, so it goes in its own file.
    assert "error" not in frame.columns
    assert (tmp_path / "failures.csv").exists()
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "env.txt").exists()
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "a line\n"


def test_the_saved_config_is_the_one_that_ran(tmp_path: Path):
    write_run([], tmp_path, {"run_id": "t", "methods": ["ECDF"], "elapsed_s": 1.5}, [])
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["methods"] == ["ECDF"]
    assert saved["elapsed_s"] == 1.5


# --- metrics helpers --------------------------------------------------------


def test_an_unranked_truth_becomes_none_and_counts_as_a_miss():
    """Not dropped, which would quietly shrink the denominator."""
    frame = pd.DataFrame({"best": [1, "", 3], "tied": [1, "", 2]})
    ranks = ranks_from(frame, "best", "tied")
    assert ranks[1] is None
    assert [rank.best if rank else None for rank in ranks] == [1, None, 3]
    assert ranks[2].tied == 2


def test_symptom_rate_divides_by_the_wrong_answers_only():
    """`docs/08` section 4: "symptom errors / wrong top-1", not / all cases.

    The first version of this test used only the `symptom_error` column and so
    could not tell a right answer from one wrong in an unrelated way - both are
    False. It passed against an implementation that divided by all 125 cases, which
    understated every symptom rate in the project by a factor of two or three. The
    correctness of the top-1 is therefore part of the input now.
    """
    frame = pd.DataFrame(
        {
            # two right, two wrong in an unrelated way, one wrong by blaming a
            # caller, and one with no graph to judge by
            "symptom_error": [False, False, False, False, True, ""],
            "top1_service": ["a", "b", "x", "y", "z", "w"],
            "gt_service": ["a", "b", "c", "d", "e", "f"],
        }
    )
    # Three wrong answers are judged - the sixth is excluded for having no graph,
    # not counted as a non-symptom - and one of them is a symptom error.
    assert symptom_rate(frame) == pytest.approx(1 / 3)


def test_symptom_rate_is_not_diluted_by_correct_answers():
    """The specific bug, stated as a property.

    A method that is right on 100 cases and wrong on 4, one of them by blaming a
    caller, has a symptom rate of 0.25 and not 0.01. Dividing by every case would
    make a method look better at this the more often it was right, which is
    precisely backwards.
    """
    many_right = pd.DataFrame(
        {
            "symptom_error": [False] * 100 + [False, False, False, True],
            "top1_service": ["a"] * 100 + ["x", "y", "z", "w"],
            "gt_service": ["a"] * 100 + ["b", "c", "d", "e"],
        }
    )
    assert symptom_rate(many_right) == pytest.approx(0.25)


def test_symptom_rate_is_none_when_every_answer_was_right():
    frame = pd.DataFrame(
        {
            "symptom_error": [False, False],
            "top1_service": ["a", "b"],
            "gt_service": ["a", "b"],
        }
    )
    assert symptom_rate(frame) is None


def test_symptom_rate_is_none_rather_than_zero_when_there_was_no_graph():
    """A rate over an empty denominator is not 0, and printing 0 would read as
    "this method never blamed a victim" when it never had the chance."""
    frame = pd.DataFrame(
        {
            "symptom_error": ["", ""],
            "top1_service": ["x", "y"],
            "gt_service": ["a", "b"],
        }
    )
    assert symptom_rate(frame) is None


# --- running a case ---------------------------------------------------------


@needs_data
def test_the_engine_is_never_given_the_ground_truth(one_case, monkeypatch):
    """Hard rule 4, checked at the boundary the rule is about.

    The request is intercepted on its way into the engine and searched for the
    answer: the broken service's name, its indicator, and any field that could
    carry them.
    """
    import experiments.runner as runner_module

    captured = {}
    real_analyze = runner_module.analyze

    def spy(request):
        captured["request"] = request
        return real_analyze(request)

    monkeypatch.setattr(runner_module, "analyze", spy)
    run_case(one_case, "ECDF", run_id="t")

    request = captured["request"]
    as_dict = request.to_api_dict()
    text = str(sorted(as_dict.keys())) + str(as_dict.get("params"))
    assert "gt" not in text and "groundTruth" not in text
    # The column map names services, which it must - but nothing marks which one
    # is the answer, and no field names the culprit on its own.
    assert not hasattr(request, "gt_service")
    assert not hasattr(request, "case")
    for key in ("groundTruth", "gtService", "gtIndicator", "answer"):
        assert key not in as_dict


@needs_data
def test_a_real_case_produces_a_complete_contract_row(one_case):
    row = run_case(one_case, "ECDF", run_id="t")
    assert row.error == ""
    assert row.verdict in ("ROOT_CAUSE_FOUND", "NO_CLEAR_CAUSE")
    assert row.method == "ECDF"
    assert row.case_id == one_case.case_id
    assert set(row.contract_row()) == set(CASES_CSV_COLUMNS)
    assert row.runtime_s > 0


@needs_data
def test_the_fine_grained_answer_belongs_to_the_service_ranked_first(one_case):
    """`docs/05` step 5. Not the globally loudest column, which can belong to
    another service once the traversal step has promoted someone."""
    row = run_case(one_case, "PARE", run_id="t", graph=_graph())
    if row.top1_service and row.top1_indicator:
        assert row.top1_indicator.startswith(row.top1_service)


@needs_data
def test_an_engine_that_raises_is_recorded_rather_than_lost(one_case, monkeypatch):
    """`docs/08` section 8. A method that crashes on 20 cases must not look like a
    method that scored badly on 105."""
    import experiments.runner as runner_module

    def explode(request):
        raise RuntimeError("engine fell over")

    monkeypatch.setattr(runner_module, "analyze", explode)
    row = run_case(one_case, "ECDF", run_id="t")

    assert "engine fell over" in row.error
    assert row.rank_gt_service == ""
    assert row.verdict == ""
    # Still a complete row, so the case is visible in cases.csv as an attempt.
    assert set(row.contract_row()) == set(CASES_CSV_COLUMNS)


@needs_data
def test_a_baseline_gets_the_same_answer_with_and_without_a_graph(one_case):
    """The engine enforces it, but the runner passes a graph in, so the guarantee
    has to hold through this path too. Handing a baseline the call graph would give
    it the one thing the proposed method is supposed to contribute."""
    with_graph = run_case(one_case, "ECDF", run_id="t", graph=_graph())
    without = run_case(one_case, "ECDF", run_id="t", graph=None)
    assert with_graph.top1_service == without.top1_service
    assert with_graph.rank_gt_service == without.rank_gt_service


def _graph():
    from experiments.adapters.graphs import load_graph

    return load_graph("online-boutique")


# --- the E1 configuration ---------------------------------------------------


def _write_config(tmp_path: Path, **overrides) -> Path:
    config = {
        "run_id": "t",
        "dataset": "RE1",
        "system": "online-boutique",
        "methods": ["ECDF"],
        "delays_s": [0.0],
    }
    config.update(overrides)
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_a_valid_config_reads():
    path = Path(__file__).resolve().parents[1] / "configs" / "c1_re1_ob.yaml"
    config = _read_config(path)
    assert config["run_id"] == "e1_re1_ob"
    # E1's main table is delay 0 only; the sweep is E3.
    assert config["delays_s"] == [0.0]
    # PARE must not be in E1: it measures common practice, not our method.
    assert "PARE" not in config["methods"]


def test_a_config_asking_for_an_engine_that_does_not_exist_is_refused(tmp_path: Path):
    """A typo in a method name would otherwise produce a table with a method
    silently missing from it."""
    path = _write_config(tmp_path, methods=["ECDF", "SHAP_IFORST"])
    with pytest.raises(ValueError, match="engines that do not exist"):
        _read_config(path)


@pytest.mark.parametrize("key", ["run_id", "dataset", "system", "methods", "delays_s"])
def test_a_config_missing_a_required_key_is_refused(tmp_path: Path, key):
    config = yaml.safe_load(_write_config(tmp_path).read_text(encoding="utf-8"))
    del config[key]
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="is missing"):
        _read_config(path)


def test_a_config_with_an_unknown_normal_mode_is_refused(tmp_path: Path):
    path = _write_config(tmp_path, normal_mode="whatever")
    with pytest.raises(ValueError, match="normal_mode must be"):
        _read_config(path)


def test_an_empty_method_or_delay_list_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="lists no methods"):
        _read_config(_write_config(tmp_path, methods=[]))
    with pytest.raises(ValueError, match="lists no delays"):
        _read_config(_write_config(tmp_path, delays_s=[]))


# --- the summary ------------------------------------------------------------


def test_wrong_top1_is_the_denominator_symptom_rate_uses():
    """They have to agree, or the printed table contradicts itself.

    Written because the first version derived `wrong_top1` from the tie-aware rank,
    which reported "0 wrong" beside an AC@1 of 0.46 for a method whose top scores
    were tied.
    """
    frame = pd.DataFrame(
        {
            "method": ["ECDF"] * 3,
            "fault_type": ["CPU"] * 3,
            "gt_service": ["a", "b", "c"],
            "gt_indicator": ["a_cpu", "b_cpu", "c_cpu"],
            # Two wrong, and a tie group at rank 1 on the first case.
            "top1_service": ["x", "b", "y"],
            "rank_gt_service": [1, 1, 4],
            "tied_gt_service": [3, 1, 1],
            "rank_gt_indicator": [1, 1, 4],
            "tied_gt_indicator": [3, 1, 1],
            "rank_gt_indicator_loose": [1, 1, 4],
            "tied_gt_indicator_loose": [3, 1, 1],
            "symptom_error": [True, "", False],
            "verdict": ["ROOT_CAUSE_FOUND"] * 3,
            "runtime_s": [0.1] * 3,
        }
    )
    summary = _summarise(frame, by=None)
    assert int(summary["wrong_top1"].iloc[0]) == 2
    # One symptom error among the two non-empty symptom flags.
    assert summary["symptom_rate"].iloc[0] == pytest.approx(0.5)
    # And AC@1 honours the tie rather than scoring it as a clean hit.
    assert summary["ac1"].iloc[0] == pytest.approx((1 / 3 + 1 + 0) / 3, abs=1e-4)


def test_the_strict_indicator_score_uses_only_cases_that_have_one():
    frame = pd.DataFrame(
        {
            "method": ["ECDF"] * 2,
            "fault_type": ["CPU", "DISK"],
            "gt_service": ["a", "b"],
            # DISK has no unambiguous indicator, so its strict rank is empty.
            "gt_indicator": ["a_cpu", ""],
            "top1_service": ["a", "b"],
            "rank_gt_service": [1, 1],
            "tied_gt_service": [1, 1],
            "rank_gt_indicator": [1, ""],
            "tied_gt_indicator": [1, ""],
            "rank_gt_indicator_loose": [1, 2],
            "tied_gt_indicator_loose": [1, 1],
            "symptom_error": ["", ""],
            "verdict": ["ROOT_CAUSE_FOUND"] * 2,
            "runtime_s": [0.1] * 2,
        }
    )
    summary = _summarise(frame, by=None)
    assert int(summary["strict_cases"].iloc[0]) == 1
    assert summary["exp_ac1"].iloc[0] == pytest.approx(1.0)
    # The loose score covers both, and the second case ranked 2nd.
    assert summary["exp_ac1_loose"].iloc[0] == pytest.approx(0.5)
