"""Tests for the E6 synthetic study (experiments/run_synthetic_study.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from experiments.run_synthetic_study import FACTORS, grid, one_run, perturb_graph
from experiments.runner import CASES_CSV_COLUMNS

EDGES = [("a", "b"), ("a", "c"), ("b", "d"), ("b", "e"), ("c", "f")]
SERVICES = ["a", "b", "c", "d", "e", "f"]
CONFIG = Path(__file__).resolve().parents[1] / "configs" / "e6_synthetic.yaml"


def test_the_true_graph_is_passed_unchanged():
    assert set(perturb_graph(EDGES, SERVICES, "TRUE", 1).edges) == set(
        perturb_graph(EDGES, SERVICES, "TRUE", 2).edges
    )
    assert {(e.caller, e.callee) for e in perturb_graph(EDGES, SERVICES, "TRUE", 1).edges} == set(
        EDGES
    )


def test_dropping_removes_a_fifth_of_the_edges_and_adds_none():
    told = {(e.caller, e.callee) for e in perturb_graph(EDGES, SERVICES, "DROP_20", 7).edges}
    assert told < set(EDGES)
    assert len(told) == len(EDGES) - 1


def test_adding_keeps_every_true_edge_and_adds_only_edges_that_do_not_exist():
    told = {(e.caller, e.callee) for e in perturb_graph(EDGES, SERVICES, "ADD_20", 7).edges}
    assert set(EDGES) < told
    added = told - set(EDGES)
    assert len(added) == 1
    for a, b in added:
        assert (b, a) not in EDGES and a != b


def test_the_perturbation_is_reproducible_per_seed():
    first = perturb_graph(EDGES, SERVICES, "DROP_20", 3).edges
    assert perturb_graph(EDGES, SERVICES, "DROP_20", 3).edges == first


def test_no_graph_is_empty_and_an_unknown_level_is_refused():
    assert perturb_graph(EDGES, SERVICES, "NONE", 1).is_empty
    with pytest.raises(ValueError, match="graph quality"):
        perturb_graph(EDGES, SERVICES, "True", 1)


def test_the_committed_grid_changes_one_factor_at_a_time():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert set(config["factors"]) == set(FACTORS)
    # bare TRUE would be read as a boolean and refused at run time
    assert config["base"]["graph"] == "TRUE"
    assert "TRUE" in config["factors"]["graph"]
    for factor, level, settings in grid(config):
        changed = {k for k in settings if settings[k] != config["base"][k]}
        assert changed <= {factor}, (factor, level, changed)


def test_one_run_gives_a_contract_row_and_scores_against_the_true_graph():
    settings = {
        "n_services": 6, "propagation": 0.8, "amplification": 0.25,
        "noise": 1.0, "graph": "NONE", "delay_rows": 0,
    }
    windows = {
        "n_normal": 300, "n_abnormal": 120, "normal_gap_s": 30,
        "recent_before_s": 300, "recent_after_s": 120,
    }
    row = one_run("PARE", "latency", 42, "graph", "NONE", settings, windows)
    assert set(row) == set(CASES_CSV_COLUMNS) | {"factor", "level"}
    # The engine was told nothing, but the chance floor exists, because the
    # scoring used the true graph.
    assert row["symptom_chance"] != ""
