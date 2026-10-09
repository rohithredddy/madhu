"""Tests for the FastAPI engine service (M7.3), through FastAPI's TestClient.

The service must speak `docs/06` section 3 exactly, because the Java backend is
built against it and cannot notice a drift. So the most important tests compare
the service's answer with the committed sample responses the Java tests also use.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def sample_request() -> dict:
    return json.loads((SAMPLES / "analyze_request.json").read_text(encoding="utf-8"))


def test_health_reports_ok_and_the_library_version(client):
    from pare import __version__

    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_engines_lists_every_registered_engine(client):
    from pare.engine import ENGINES

    listed = client.get("/v1/engines").json()
    assert {item["name"] for item in listed} == set(ENGINES)
    assert all(item["description"] for item in listed)


@pytest.mark.parametrize("engine", ["PARE", "NSIGMA"])
def test_analyze_returns_exactly_the_committed_sample_response(client, sample_request, engine):
    """The Java FallbackRanker test is built on these files. If the service's
    answer and the stored answer ever differ, one of them is lying to Java."""
    request = dict(sample_request, engine=engine)
    response = client.post("/v1/analyze", json=request)
    assert response.status_code == 200
    expected = json.loads(
        (SAMPLES / f"analyze_response_{engine.lower()}.json").read_text(encoding="utf-8")
    )
    got = response.json()
    got["tookMs"] = expected["tookMs"] = None  # machine-dependent, not asserted
    assert got == pytest.approx(expected)


def test_a_typical_request_answers_in_under_two_seconds(client, sample_request):
    """docs/05 section 7. After the start-up warm-up, so the import is not timed."""
    started = time.perf_counter()
    assert client.post("/v1/analyze", json=sample_request).status_code == 200
    assert time.perf_counter() - started < 2.0


def _expect_422(client, path: str, body: dict, fragment: str) -> None:
    response = client.post(path, json=body)
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["error"] == "invalid request"
    assert fragment in payload["details"], payload["details"]


def test_a_row_with_the_wrong_number_of_values_is_refused(client, sample_request):
    bad = copy.deepcopy(sample_request)
    bad["recent"]["values"][3] = bad["recent"]["values"][3][:-1]
    _expect_422(client, "/v1/analyze", bad, "recent.values row 3")


def test_the_string_nan_is_not_a_number(client, sample_request):
    """docs/06: a missing number is null, never the string "NaN"."""
    bad = copy.deepcopy(sample_request)
    bad["normal"]["values"][0][0] = "NaN"
    _expect_422(client, "/v1/analyze", bad, "normal")


def test_null_is_accepted_as_a_missing_reading(client, sample_request):
    good = copy.deepcopy(sample_request)
    good["normal"]["values"][5][2] = None
    assert client.post("/v1/analyze", json=good).status_code == 200


def test_an_unknown_params_key_is_refused_by_name(client, sample_request):
    bad = dict(sample_request, params={"topk": 5})
    _expect_422(client, "/v1/analyze", bad, "topk")


def test_an_unknown_engine_is_refused(client, sample_request):
    _expect_422(client, "/v1/analyze", dict(sample_request, engine="MAGIC"), "MAGIC")


def test_ground_truth_cannot_be_smuggled_into_a_request(client, sample_request):
    """Hard rule 4. The request has no field for it, and an extra one is refused
    rather than ignored."""
    bad = dict(sample_request, groundTruth={"service": "svc-02"})
    _expect_422(client, "/v1/analyze", bad, "groundTruth")


def test_a_missing_graph_means_no_graph(client, sample_request):
    request = dict(sample_request)
    request.pop("graph")
    assert client.post("/v1/analyze", json=request).status_code == 200


def test_synthetic_returns_a_case_in_the_case_format(client):
    response = client.post(
        "/v1/synthetic",
        json={"nServices": 6, "faultType": "MEM", "noise": "LOW", "seed": 3,
              "nNormal": 300, "nAbnormal": 60},
    )
    assert response.status_code == 200
    case = response.json()
    meta = case["meta"]
    assert meta["source"] == "SYNTHETIC"
    assert meta["faultType"] == "MEM"
    assert meta["graph"]["source"] == "SYNTHETIC_TRUE"
    assert meta["groundTruth"]["indicator"].startswith(meta["groundTruth"]["service"])
    assert len(case["timeSec"]) == len(case["values"]) == 360
    assert all(len(row) == len(meta["columns"]) for row in case["values"])
    # The injection is the first abnormal row.
    assert case["timeSec"][300] == meta["injectTimeSec"]


def test_the_same_settings_give_the_same_case(client):
    body = {"nServices": 5, "faultType": "CPU", "seed": 11, "nNormal": 100, "nAbnormal": 30}
    first = client.post("/v1/synthetic", json=body).json()
    second = client.post("/v1/synthetic", json=body).json()
    assert first == second


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"faultType": "latency"}, "faultType"),
        ({"noise": "medium"}, "noise"),
        ({"nServices": 1}, "nServices"),
        ({"amplification": -1}, "amplification"),
    ],
)
def test_synthetic_refuses_bad_settings_clearly(client, body, fragment):
    _expect_422(client, "/v1/synthetic", body, fragment)
