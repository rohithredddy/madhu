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

from experiments.run_c1_grounding import _combine, _read_config, _summarise
from experiments.runner import (
    CASES_CSV_COLUMNS,
    CaseRow,
    ranks_from,
    run_case,
    symptom_rate,
    symptom_rate_chance,
    write_run,
    wrong_probabilities,
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
        symptom_error=False, tied_top1=1, symptom_share=0.0, symptom_chance=0.2,
        verdict="ROOT_CAUSE_FOUND", runtime_s=0.1,
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


def _symptom_frame(shares, ranks, ties=None, chances=None) -> pd.DataFrame:
    """The columns the symptom rate reads, one case per entry.

    `ranks` is the culprit's service rank (1 = right, "" = never ranked) and
    `shares` the share of the rank-1 tie group calling the culprit, as the runner
    writes them; "" means no graph.
    """
    n = len(shares)
    if ties is None:
        ties = [1 if rank != "" else "" for rank in ranks]
    return pd.DataFrame(
        {
            "symptom_share": shares,
            "symptom_chance": chances if chances is not None else [""] * n,
            "rank_gt_service": ranks,
            "tied_gt_service": ties,
        }
    )


def test_symptom_rate_divides_by_the_wrong_answers_only():
    """`docs/08` section 4: "symptom errors / wrong top-1", not / all cases.

    The first version of this test used only the `symptom_error` column and so
    could not tell a right answer from one wrong in an unrelated way - both are
    False. It passed against an implementation that divided by all 125 cases, which
    understated every symptom rate in the project by a factor of two or three. The
    correctness of the top-1 is therefore part of the input - since M3.2 as the
    culprit's service rank, which is what lets ties be scored as ties.
    """
    # two right, two wrong in an unrelated way, one wrong by blaming a caller, and
    # one with no graph to judge by
    frame = _symptom_frame(shares=[0.0, 0.0, 0.0, 0.0, 1.0, ""], ranks=[1, 1, 3, 4, 2, 5])
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
    many_right = _symptom_frame(
        shares=[0.0] * 100 + [0.0, 0.0, 0.0, 1.0], ranks=[1] * 100 + [2, 3, 4, 5]
    )
    assert symptom_rate(many_right) == pytest.approx(0.25)


def test_symptom_rate_is_none_when_every_answer_was_right():
    assert symptom_rate(_symptom_frame(shares=[0.0, 0.0], ranks=[1, 1])) is None


def test_symptom_rate_is_none_rather_than_zero_when_there_was_no_graph():
    """A rate over an empty denominator is not 0, and printing 0 would read as
    "this method never blamed a victim" when it never had the chance."""
    assert symptom_rate(_symptom_frame(shares=["", ""], ranks=[3, 2])) is None


def test_symptom_rate_scores_a_tie_at_rank_1_as_a_tie():
    """M3.2. A case whose top two services tie, one of them a caller of the culprit
    and the other unrelated, is half a symptom error - whichever the engine
    happened to list first. Before this, ECDF's symptom rate on RE1-SS was 0.0
    only because `carts` sorts first among the services it tied."""
    frame = _symptom_frame(shares=[0.5, 0.5], ranks=[4, 4])
    assert symptom_rate(frame) == pytest.approx(0.5)


def test_an_unranked_culprit_counts_as_wrong():
    """A culprit the method never ranked is a wrong answer with certainty, not a
    case to leave out of the denominator."""
    frame = _symptom_frame(shares=[1.0, 0.0], ranks=["", 2])
    assert wrong_probabilities(frame) == [1.0, 1.0]
    assert symptom_rate(frame) == pytest.approx(0.5)


def test_the_chance_rate_is_weighted_like_the_symptom_rate():
    """Both are over the same wrong answers: a right answer's chance value must
    not enter the floor, or the two would be computed over different cases."""
    frame = _symptom_frame(shares=[0.0, 1.0, 0.0], ranks=[1, 2, 3], chances=[0.9, 0.2, 0.4])
    assert symptom_rate_chance(frame) == pytest.approx((0.2 + 0.4) / 2)


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

    The first version derived `wrong_top1` from the tie-aware rank and printed
    "0 wrong" beside an AC@1 of 0.46; the second counted "the service listed first
    is not the culprit", which for a tie is decided by naming. Since M3.2 it is the
    expected count under the same tie rule as AC@1, so it is exactly
    (1 - AC@1) x cases.
    """
    frame = _summary_frame(
        # A tie of three at rank 1 that holds the culprit, one clean hit, and one
        # clean miss on a case with no graph to judge it by.
        rank_gt_service=[1, 1, 4],
        tied_gt_service=[3, 1, 1],
        symptom_share=[1 / 3, 0.0, ""],
    )
    summary = _summarise(frame, by=None)
    ac1 = (1 / 3 + 1 + 0) / 3
    assert summary["ac1"].iloc[0] == pytest.approx(ac1, abs=1e-4)
    assert summary["wrong_top1"].iloc[0] == pytest.approx((1 - ac1) * 3, abs=0.01)
    # Only the first case can be judged: wrong 2/3 of the time, a caller blamed
    # 1/3 of the time.
    assert summary["symptom_judged"].iloc[0] == pytest.approx(2 / 3, abs=0.01)
    assert summary["symptom_rate"].iloc[0] == pytest.approx(0.5)


def _summary_frame(**columns) -> pd.DataFrame:
    """A minimal cases.csv for `_summarise`, with harmless defaults."""
    n = len(next(iter(columns.values())))
    frame = {
        "method": ["ECDF"] * n,
        "system": ["online-boutique"] * n,
        "fault_type": ["CPU"] * n,
        "gt_service": [f"s{i}" for i in range(n)],
        "gt_indicator": [f"s{i}_cpu" for i in range(n)],
        "top1_service": [f"s{i}" for i in range(n)],
        "rank_gt_service": [1] * n,
        "tied_gt_service": [1] * n,
        "rank_gt_indicator": [1] * n,
        "tied_gt_indicator": [1] * n,
        "rank_gt_indicator_loose": [1] * n,
        "tied_gt_indicator_loose": [1] * n,
        "symptom_share": [""] * n,
        "symptom_chance": [""] * n,
        "verdict": ["ROOT_CAUSE_FOUND"] * n,
        "runtime_s": [0.1] * n,
    }
    frame.update(columns)
    return pd.DataFrame(frame)


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
            "symptom_share": ["", ""],
            "symptom_chance": ["", ""],
            "verdict": ["ROOT_CAUSE_FOUND"] * 2,
            "runtime_s": [0.1] * 2,
        }
    )
    summary = _summarise(frame, by=None)
    assert int(summary["strict_cases"].iloc[0]) == 1
    assert summary["exp_ac1"].iloc[0] == pytest.approx(1.0)
    # The loose score covers both, and the second case ranked 2nd.
    assert summary["exp_ac1_loose"].iloc[0] == pytest.approx(0.5)


# --- pooling runs (M3.2) ----------------------------------------------------


def _finished_run(root: Path, run_id: str, system: str, frame: pd.DataFrame, **config):
    """Lay out a run folder the way `run_c1_grounding.py` leaves one."""
    folder = root / run_id
    folder.mkdir(parents=True)
    frame.assign(run_id=run_id, system=system).to_csv(folder / "cases.csv", index=False)
    settings = {
        "run_id": run_id,
        "dataset": "RE1",
        "system": system,
        "methods": ["ECDF"],
        "delays_s": [0.0],
        "seed": 42,
        "normal_mode": "inject_gap",
        "graph": system,
    }
    settings.update(config)
    (folder / "config.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")


def test_pooling_scores_every_case_exactly_as_its_own_run_did(tmp_path: Path):
    """Pooling must not change how any case is scored, only which cases are
    summarised together. So the pooled per-system rows equal each run's own
    summary."""
    first = _summary_frame(rank_gt_service=[1, 2], symptom_share=[0.0, 1.0])
    first = first.assign(case_id=["a", "b"])
    second = _summary_frame(rank_gt_service=[3, 1, 1], symptom_share=[0.0, 0.0, 0.0])
    second = second.assign(case_id=["c", "d", "e"], gt_service=["t0", "t1", "t2"])
    _finished_run(tmp_path, "one", "online-boutique", first)
    _finished_run(tmp_path, "two", "sock-shop", second)

    assert _combine({"run_id": "both", "combine_runs": ["one", "two"]}, tmp_path) == 0

    by_system = pd.read_csv(tmp_path / "both" / "summary_by_system.csv")
    for system, own in (("online-boutique", first), ("sock-shop", second)):
        pooled_row = by_system[by_system["system"] == system].iloc[0]
        alone = _summarise(own.assign(system=system), by=None).iloc[0]
        assert pooled_row["ac1"] == pytest.approx(alone["ac1"])
        assert pooled_row["symptom_rate"] == pytest.approx(alone["symptom_rate"])
        assert pooled_row["cases"] == alone["cases"]
    overall = pd.read_csv(tmp_path / "both" / "summary.csv").iloc[0]
    assert overall["cases"] == 5
    for name in ("cases.csv", "config.yaml", "env.txt", "log.txt", "report.txt"):
        assert (tmp_path / "both" / name).exists()


@pytest.mark.parametrize(
    "difference",
    [
        {"methods": ["PCA_RECON"]},
        {"delays_s": [30.0]},
        {"seed": 7},
        {"normal_mode": "alarm_lookback"},
    ],
)
def test_pooling_refuses_runs_that_measured_different_things(tmp_path: Path, difference):
    """Averaging a delay-30 run with a delay-0 run would print one number for two
    different questions."""
    frame = _summary_frame(rank_gt_service=[1]).assign(case_id=["a"])
    _finished_run(tmp_path, "one", "online-boutique", frame)
    _finished_run(
        tmp_path, "two", "sock-shop", frame.assign(case_id=["b"]), **difference
    )
    with pytest.raises(ValueError, match="cannot pool"):
        _combine({"run_id": "both", "combine_runs": ["one", "two"]}, tmp_path)


def test_pooling_refuses_runs_that_share_a_case(tmp_path: Path):
    frame = _summary_frame(rank_gt_service=[1]).assign(case_id=["same"])
    _finished_run(tmp_path, "one", "online-boutique", frame)
    _finished_run(tmp_path, "two", "online-boutique", frame)
    with pytest.raises(ValueError, match="share cases"):
        _combine({"run_id": "both", "combine_runs": ["one", "two"]}, tmp_path)


def test_a_pooling_config_needs_at_least_two_runs(tmp_path: Path):
    path = tmp_path / "c.yaml"
    path.write_text(
        yaml.safe_dump({"run_id": "x", "combine_runs": ["one"]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="at least two"):
        _read_config(path)


def test_the_committed_pooling_config_reads():
    path = Path(__file__).resolve().parents[1] / "configs" / "c1_re1.yaml"
    config = _read_config(path)
    assert config["combine_runs"] == ["e1_re1_ob", "e1_re1_ss", "e1_re1_tt"]


def test_the_three_system_configs_differ_only_in_system_graph_and_run_id():
    """What makes them poolable. A setting changed in one and not the others would
    be refused at pooling time; this catches it at review time instead."""
    configs_dir = Path(__file__).resolve().parents[1] / "configs"
    configs = [_read_config(configs_dir / f"c1_re1_{s}.yaml") for s in ("ob", "ss", "tt")]
    allowed = {"run_id", "system", "graph"}
    for other in configs[1:]:
        keys = set(configs[0]) | set(other)
        differing = {key for key in keys if configs[0].get(key) != other.get(key)}
        assert differing <= allowed
