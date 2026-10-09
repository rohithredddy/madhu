"""Tests for the case folders the Java backend reads (M7.4, M7.5).

`docs/06` section 2 is the contract; `case_format.validate_case_folder` encodes it,
and these tests check both that valid folders pass and that each way of breaking
the contract is caught.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from experiments.case_format import validate_case_folder, write_case

REPO = Path(__file__).resolve().parents[2]
RCAEVAL = REPO / "data" / "RCAEval"


def _small_case(tmp_path: Path, **overrides) -> Path:
    frame = pd.DataFrame(
        {"time": [100, 101, 102, 103], "a_cpu": [1.0, 1.1, None, 5.0], "b_lat": [2, 2, 2, 9]}
    )
    settings = dict(
        source="UPLOAD", system="toy", fault_type="cpu", inject_time_sec=102,
        ground_truth={"service": "a", "indicator": "a_cpu"},
        columns=[{"name": "a_cpu", "service": "a", "metric": "cpu"},
                 {"name": "b_lat", "service": "b", "metric": "latency"}],
        graph_source="USER", edges=[("b", "a")], notes="test",
    )
    settings.update(overrides)
    return write_case(tmp_path, "toy-1", frame, **settings)


def test_a_written_case_is_valid_and_reads_back(tmp_path: Path):
    folder = _small_case(tmp_path)
    assert validate_case_folder(folder) == []
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["faultType"] == "CPU"  # uppercased on the way out
    assert meta["graph"]["edges"] == [{"from": "b", "to": "a"}]
    data = pd.read_csv(folder / "data.csv")
    assert list(data.columns) == ["time", "a_cpu", "b_lat"]
    # A missing reading is an empty cell, not 0 and not "NaN".
    assert (folder / "data.csv").read_text(encoding="utf-8").splitlines()[3].startswith("102,,")


def test_a_ground_truth_that_is_not_a_column_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="ground-truth indicator"):
        _small_case(tmp_path, ground_truth={"service": "a", "indicator": "a_mem"})


def test_an_injection_outside_the_data_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="outside the data"):
        _small_case(tmp_path, inject_time_sec=999)


def test_validation_catches_hand_edits(tmp_path: Path):
    folder = _small_case(tmp_path)
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["columns"].reverse()
    meta["source"] = "SOMEWHERE"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    problems = validate_case_folder(folder)
    assert any("order" in problem for problem in problems)
    assert any("source" in problem for problem in problems)


def test_time_must_increase(tmp_path: Path):
    folder = _small_case(tmp_path)
    data = pd.read_csv(folder / "data.csv")
    data.loc[2, "time"] = 100
    data.to_csv(folder / "data.csv", index=False)
    assert any("increasing" in problem for problem in validate_case_folder(folder))


def test_a_null_ground_truth_indicator_is_allowed(tmp_path: Path):
    """DISK, DELAY and LOSS have no single right metric; null says so."""
    folder = _small_case(tmp_path, ground_truth={"service": "a", "indicator": None})
    assert validate_case_folder(folder) == []


def test_the_synthetic_script_writes_twelve_valid_cases(tmp_path: Path):
    sys.path.insert(0, str(REPO / "scripts"))
    import make_synthetic_cases

    assert make_synthetic_cases.main(["--out", str(tmp_path)]) == 0
    folders = sorted(path for path in tmp_path.iterdir() if path.is_dir())
    assert len(folders) == 12
    faults = [json.loads((f / "meta.json").read_text(encoding="utf-8"))["faultType"]
              for f in folders]
    assert sorted(faults) == sorted(["LATENCY", "CPU", "MEM", "ERROR"] * 3)
    assert all(validate_case_folder(folder) == [] for folder in folders)


@pytest.mark.skipif(not (RCAEVAL / "RE1" / "RE1-OB").exists(), reason="RE1-OB not downloaded")
def test_an_exported_case_holds_exactly_what_the_experiments_see(tmp_path: Path):
    from experiments.adapters.rcaeval import list_cases, load_case
    from experiments.export_cases import export_case

    # The contaminated case: its foreign columns must not reach the application.
    case = next(c for c in list_cases(RCAEVAL, "RE1", "online-boutique")
                if c.case_id == "re1-ob-productcatalogservice_cpu-3")
    folder = export_case(case, tmp_path)
    assert validate_case_folder(folder) == []
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    loaded = load_case(case)
    assert [c["name"] for c in meta["columns"]] == [c.name for c in loaded.columns]
    assert "carts_cpu" not in pd.read_csv(folder / "data.csv", nrows=0).columns
    assert meta["graph"]["source"] == "STATIC_ARCHITECTURE"
    assert meta["groundTruth"] == {"service": case.gt_service, "indicator": case.gt_indicator}


@pytest.mark.skipif(not (RCAEVAL / "RE1" / "RE1-OB").exists(), reason="RE1-OB not downloaded")
def test_an_ambiguous_fault_exports_a_null_indicator_and_says_why(tmp_path: Path):
    from experiments.adapters.rcaeval import list_cases
    from experiments.export_cases import export_case

    case = next(c for c in list_cases(RCAEVAL, "RE1", "online-boutique")
                if c.fault_type == "DELAY")
    meta = json.loads((export_case(case, tmp_path) / "meta.json").read_text(encoding="utf-8"))
    assert meta["groundTruth"]["indicator"] is None
    assert "acceptable" in meta["notes"]
