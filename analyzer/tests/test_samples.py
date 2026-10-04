"""Tests for the fixtures shared with the Java backend.

These files are a contract between two languages, and the Java side cannot notice
when the Python side changes. So this regenerates them from the current code and
fails if anything moved: a change to the response shape, a renamed field, a
different number. Without that, `docs/03_JAVA_BACKEND_SPEC.md` section 4.4 - the
Java fallback must rank exactly as Python NSIGMA - would be verified against a
stale file and mean nothing.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pare.engine import AnalyzeRequest, analyze

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_samples.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("make_samples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_samples"] = module
    spec.loader.exec_module(module)
    return module


def read(name: str):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


# --- the files exist and say what they should ------------------------------


def test_the_samples_are_committed():
    for name in (
        "analyze_request.json",
        "analyze_response_pare.json",
        "analyze_response_nsigma.json",
        "README.md",
    ):
        assert (SAMPLES / name).exists(), f"{name} is missing; run scripts/make_samples.py"


def test_the_request_matches_the_data_contract():
    """Field for field against docs/06 section 3."""
    request = read("analyze_request.json")

    assert set(request) == {
        "requestId",
        "engine",
        "alarmTimeSec",
        "columns",
        "normal",
        "recent",
        "graph",
        "params",
    }
    assert set(request["columns"][0]) == {"name", "service", "metric"}
    assert set(request["normal"]) == {"timeSec", "values"}
    assert set(request["graph"]) == {"source", "edges"}
    assert set(request["graph"]["edges"][0]) == {"from", "to"}

    # every row has one entry per column, as the contract requires
    width = len(request["columns"])
    for block in ("normal", "recent"):
        rows = request[block]["values"]
        assert len(rows) == len(request[block]["timeSec"])
        assert all(len(row) == width for row in rows)


@pytest.mark.parametrize("engine", ["pare", "nsigma"])
def test_a_response_matches_the_data_contract(engine):
    response = read(f"analyze_response_{engine}.json")

    assert set(response) == {
        "requestId",
        "engine",
        "engineVersion",
        "tookMs",
        "verdict",
        "alarmTimeSec",
        "changePointSec",
        "windowStartSec",
        "windowEndSec",
        "services",
        "indicators",
        "warnings",
    }
    assert set(response["services"][0]) == {
        "service",
        "rank",
        "score",
        "marginalScore",
        "inheritedFraction",
        "topIndicator",
        "role",
        "explainedBy",
    }
    assert set(response["indicators"][0]) == {
        "column",
        "service",
        "metric",
        "rank",
        "selfScore",
        "marginalScore",
        "inheritedFraction",
    }
    assert response["verdict"] in {"ROOT_CAUSE_FOUND", "NO_CLEAR_CAUSE"}
    assert [item["rank"] for item in response["services"]] == list(
        range(1, len(response["services"]) + 1)
    )


# --- missing numbers --------------------------------------------------------


def test_the_request_contains_nulls_for_missing_readings():
    """docs/06: a missing number is null, never 0 and never the string "NaN".
    Java has to cope with that, so the fixture has to contain some."""
    request = read("analyze_request.json")
    rows = request["normal"]["values"] + request["recent"]["values"]
    nulls = sum(1 for row in rows for value in row if value is None)

    assert nulls > 0, "the sample should exercise null handling"
    text = (SAMPLES / "analyze_request.json").read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text


# --- no ground truth --------------------------------------------------------


def test_the_request_carries_no_ground_truth():
    """Hard rule 4. The answer must not travel with the question."""
    text = (SAMPLES / "analyze_request.json").read_text(encoding="utf-8")
    for forbidden in ("groundTruth", "gtService", "gt_service", "rootCause", "faultType"):
        assert forbidden not in text


# --- what Java has to reproduce --------------------------------------------


def test_the_nsigma_response_is_what_the_java_fallback_must_match():
    """docs/03 section 4.4. An engine with no dependency model has to say so:
    equal scores, nothing inherited, nothing explained."""
    response = read("analyze_response_nsigma.json")

    assert response["engine"] == "NSIGMA"
    assert response["changePointSec"] is None, "NSIGMA never re-anchors"

    for service in response["services"]:
        assert service["score"] == pytest.approx(service["marginalScore"])
        assert service["explainedBy"] is None
    for indicator in response["indicators"]:
        assert indicator["inheritedFraction"] == 0.0


def test_the_pare_response_exercises_the_fields_java_has_to_render():
    """The Java side renders roles, an explained-by and a change point, so the
    sample it is built against needs to contain them."""
    response = read("analyze_response_pare.json")

    assert response["engine"] == "PARE"
    assert response["changePointSec"] is not None
    roles = {service["role"] for service in response["services"]}
    assert "CAUSE" in roles
    assert roles <= {"CAUSE", "SYMPTOM", "ALSO_ABNORMAL", "NORMAL"}


# --- the files cannot drift from the code ----------------------------------


@pytest.mark.parametrize("engine", ["PARE", "NSIGMA"])
def test_rerunning_the_engine_reproduces_the_stored_response(engine):
    """The point of this file.

    Reads the committed request, runs the engine now, and compares against the
    committed answer. If the response shape or any number changes, this fails
    here rather than silently breaking a Java test that cannot see Python.
    """
    stored = read(f"analyze_response_{engine.lower()}.json")

    request_json = read("analyze_request.json")
    request_json["engine"] = engine
    result = analyze(AnalyzeRequest.from_api_dict(request_json))

    fresh = result.to_api_dict()
    fresh["tookMs"] = None  # machine-dependent, stored as null on purpose

    assert fresh == stored, (
        f"the committed {engine} sample no longer matches what the code produces; "
        "rerun scripts/make_samples.py and check the difference is intended"
    )


def test_the_request_round_trips_through_the_contract():
    request_json = read("analyze_request.json")
    rebuilt = AnalyzeRequest.from_api_dict(request_json).to_api_dict()

    assert rebuilt["columns"] == request_json["columns"]
    assert rebuilt["graph"] == request_json["graph"]
    assert rebuilt["normal"]["timeSec"] == request_json["normal"]["timeSec"]
    assert rebuilt["normal"]["values"] == request_json["normal"]["values"]


def test_the_generator_is_deterministic(monkeypatch):
    """Regenerating must not churn the files, or every run would show a diff."""
    generator = load_generator()
    # main() reads sys.argv, which under pytest holds pytest's own arguments.
    monkeypatch.setattr(sys, "argv", ["make_samples.py"])
    before = {
        name: (SAMPLES / name).read_text(encoding="utf-8")
        for name in (
            "analyze_request.json",
            "analyze_response_pare.json",
            "analyze_response_nsigma.json",
        )
    }

    generator.main()

    for name, text in before.items():
        assert (SAMPLES / name).read_text(encoding="utf-8") == text, (
            f"{name} changed when regenerated, so the generator is not deterministic"
        )
