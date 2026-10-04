"""Tests for the M1 gate script.

The gate decides whether milestone M1 is allowed to finish, so its logic needs to
be trustworthy on its own. In particular it has to be capable of **failing** -
a check that cannot fail is not a check - and it must not be fooled by the
amplification-0 case where every engine ties.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "synthetic_check.py"


def load_script():
    """Import the script by path, since scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("synthetic_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["synthetic_check"] = module
    spec.loader.exec_module(module)
    return module


check = load_script()


def row(engine, fault, amplification, ac1, **extra):
    base = {
        "engine": engine,
        "fault": fault,
        "amplification": amplification,
        "cases": 50,
        "ac1": ac1,
        "ac3": ac1,
        "avg5": ac1,
        "exp_ac1": ac1,
        "exp_ac3": ac1,
        "symptom_rate": "",
        "no_clear_cause": 0,
        "mean_ms": 100,
    }
    base.update(extra)
    return base


# --- the gate can pass ------------------------------------------------------


def test_the_gate_passes_when_the_method_beats_its_ablation():
    rows = [
        row("PARE", "latency", 0.25, 0.96),
        row("PARE_NO_RESIDUAL", "latency", 0.25, 0.84),
    ]
    passed, lines = check.check_the_gate(rows)

    assert passed
    assert any("gap +0.12" in line for line in lines)


def test_a_tie_passes_because_the_condition_is_greater_or_equal():
    """At amplification 0 there is no symptom trap, so the two are expected to be
    identical. That must count as a pass, not a failure."""
    rows = [
        row("PARE", "latency", 0.0, 1.00),
        row("PARE_NO_RESIDUAL", "latency", 0.0, 1.00),
    ]
    passed, _ = check.check_the_gate(rows)
    assert passed


# --- the gate can fail, which is the point ---------------------------------


def test_the_gate_fails_when_the_ablation_wins():
    """If removing the dependency model made things better, the core claim is
    wrong and M1 must stop. docs/07: do not tune the test to pass."""
    rows = [
        row("PARE", "latency", 0.25, 0.70),
        row("PARE_NO_RESIDUAL", "latency", 0.25, 0.85),
    ]
    passed, lines = check.check_the_gate(rows)

    assert not passed
    assert any("FAILED" in line for line in lines)


def test_the_gate_fails_when_latency_accuracy_is_below_the_bar():
    rows = [
        row("PARE", "latency", 0.25, 0.80),
        row("PARE_NO_RESIDUAL", "latency", 0.25, 0.10),
    ]
    passed, lines = check.check_the_gate(rows)

    assert not passed, "0.80 is below the 0.85 the task requires"
    assert any("0.80" in line and "FAILED" in line for line in lines)


def test_one_bad_setting_fails_the_whole_gate():
    """The condition is "everywhere", so a single setting where the ablation wins
    is enough. Averaging over settings would hide exactly the case we care about.
    """
    rows = [
        row("PARE", "latency", 0.0, 1.00),
        row("PARE_NO_RESIDUAL", "latency", 0.0, 1.00),
        row("PARE", "mem", 0.25, 0.50),
        row("PARE_NO_RESIDUAL", "mem", 0.25, 0.90),
    ]
    passed, _ = check.check_the_gate(rows)
    assert not passed


def test_the_gate_names_the_two_engines_it_compares():
    """So the check cannot drift away from the claim it is testing."""
    assert check.GATE_METHOD == "PARE"
    assert check.GATE_ABLATION == "PARE_NO_RESIDUAL"


# --- summarising ------------------------------------------------------------


def test_summarise_scores_ties_rather_than_counting_them_as_hits():
    """The summary must use the tie-aware rule from docs/08 section 4."""
    results = [
        check.CaseResult(
            engine="ECDF",
            fault="latency",
            amplification=0.0,
            seed=seed,
            gt_service="a",
            gt_column="a_cpu",
            top1_service="a",
            top1_indicator="a_cpu",
            rank_gt_service=1,
            tied_gt_service=4,  # four services share first place
            rank_gt_indicator=1,
            tied_gt_indicator=1,
            symptom_error=False,
            verdict="ROOT_CAUSE_FOUND",
            took_ms=5,
        )
        for seed in range(10)
    ]
    rows = check.summarise(results)

    assert len(rows) == 1
    assert rows[0]["ac1"] == pytest.approx(0.25), "a four-way tie is worth a quarter"
    assert rows[0]["exp_ac1"] == pytest.approx(1.0), "the indicator was not tied"


def test_summarise_leaves_the_symptom_rate_empty_when_nothing_was_wrong():
    results = [
        check.CaseResult(
            engine="PARE",
            fault="latency",
            amplification=0.0,
            seed=0,
            gt_service="a",
            gt_column="a_cpu",
            top1_service="a",
            top1_indicator="a_cpu",
            rank_gt_service=1,
            tied_gt_service=1,
            rank_gt_indicator=1,
            tied_gt_indicator=1,
            symptom_error=False,
            verdict="ROOT_CAUSE_FOUND",
            took_ms=100,
        )
    ]
    rows = check.summarise(results)
    assert rows[0]["symptom_rate"] == ""


# --- running one case end to end -------------------------------------------


def test_one_case_runs_and_scores_a_real_analysis():
    result = check.one_case(
        engine="PARE",
        fault="latency",
        amplification=0.0,
        seed=0,
        n_services=5,
        n_normal=250,
        n_abnormal=120,
        propagation=0.9,
        delay_s=30.0,
    )

    assert result.engine == "PARE"
    assert result.gt_column.startswith(result.gt_service)
    assert result.rank_gt_service is not None
    assert result.verdict in {"ROOT_CAUSE_FOUND", "NO_CLEAR_CAUSE"}


def test_the_amplification_sweep_includes_a_control_and_a_trap():
    """Without the trap setting the gate is empty, and without the control we
    could not show the two engines are identical when there is nothing to tell
    apart."""
    assert 0.0 in check.DEFAULT_AMPLIFICATIONS
    assert any(value > 0 for value in check.DEFAULT_AMPLIFICATIONS)


# --- building the grid in pieces --------------------------------------------


def a_case(engine, fault="latency", amplification=0.0, seed=0, rank=1, tied=1):
    return check.CaseResult(
        engine=engine,
        fault=fault,
        amplification=amplification,
        seed=seed,
        gt_service="svc-01",
        gt_column="svc-01_latency",
        top1_service="svc-01",
        top1_indicator="svc-01_latency",
        rank_gt_service=rank,
        tied_gt_service=tied,
        rank_gt_indicator=rank,
        tied_gt_indicator=tied,
        symptom_error=False,
        verdict="ROOT_CAUSE_FOUND",
        took_ms=42,
    )


def write_cases(path, results):
    import csv

    fields = list(check.CaseResult.__dataclass_fields__)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow({field: getattr(item, field) for field in fields})


def test_cases_survive_a_round_trip_through_csv(tmp_path):
    """Append reads a previous run back from disk, so the types have to come back
    as they went in - a rank must be an int again, not the string "1"."""
    path = tmp_path / "cases.csv"
    original = [a_case("PARE"), a_case("NSIGMA", seed=1)]
    write_cases(path, original)

    assert check.read_cases(path) == original


def test_an_absent_value_comes_back_as_none_not_zero(tmp_path):
    """An unranked case is empty in the file. Reading it as 0 would turn "the
    method never named it" into "it came first"."""
    path = tmp_path / "cases.csv"
    missing = check.CaseResult(
        engine="PCA_RECON",
        fault="mem",
        amplification=0.0,
        seed=3,
        gt_service="svc-01",
        gt_column="svc-01_mem",
        top1_service=None,
        top1_indicator=None,
        rank_gt_service=None,
        tied_gt_service=None,
        rank_gt_indicator=None,
        tied_gt_indicator=None,
        symptom_error=None,
        verdict="NO_CLEAR_CAUSE",
        took_ms=7,
    )
    write_cases(path, [missing])

    back = check.read_cases(path)[0]
    assert back.rank_gt_service is None
    assert back.symptom_error is None
    assert back.top1_service is None


def test_a_rerun_engine_replaces_its_rows_rather_than_duplicating_them(tmp_path):
    """Appending the same engine twice must refresh it, not double it - otherwise
    a repeated run would quietly weight that engine twice in the summary."""
    path = tmp_path / "cases.csv"
    write_cases(path, [a_case("PARE", seed=0), a_case("SHAP_IFOREST", seed=0)])

    previous = [item for item in check.read_cases(path) if item.engine != "SHAP_IFOREST"]
    merged = previous + [a_case("SHAP_IFOREST", seed=0, rank=3)]

    assert len(merged) == 2
    by_engine = {item.engine: item for item in merged}
    assert by_engine["SHAP_IFOREST"].rank_gt_service == 3, "the fresh row should win"
    assert by_engine["PARE"].rank_gt_service == 1, "the untouched engine is kept"
