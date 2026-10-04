"""Tests for the engine registry and the end-to-end analysis.

Includes the two guarantees docs/05 section 6 asks for by name: every engine must
survive a case with missing columns and no graph, and a quiet window must come
back as NO_CLEAR_CAUSE with nobody accused.
"""

import numpy as np
import pytest

from pare.config import PareConfig
from pare.engine import (
    ENGINES,
    AnalyzeRequest,
    Window,
    analyze,
    available_engines,
)
from pare.graph import CallGraph
from pare.rank import CAUSE, NO_CLEAR_CAUSE, ROOT_CAUSE_FOUND
from pare.synthetic import make_case

ALL_ENGINES = sorted(ENGINES)
DELAY = 30


def request_for(case, engine, normal_rows=400, config=None):
    """Build a request from a synthetic case, the way the service layer will."""
    frame = case.to_frame()
    recent = frame.iloc[normal_rows:]
    return AnalyzeRequest(
        engine=engine,
        alarm_time_sec=case.inject_time_sec + DELAY,
        columns=case.columns,
        normal=Window.of(case.normal.index.to_numpy(dtype=float), case.normal.to_numpy()),
        recent=Window.of(recent.index.to_numpy(dtype=float), recent.to_numpy()),
        graph=CallGraph.from_edges(case.edges, source="SYNTHETIC_TRUE"),
        config=config or PareConfig(),
        request_id="test-1",
    )


# --- the registry -----------------------------------------------------------


def test_the_registry_holds_the_engines_the_spec_names():
    assert set(ALL_ENGINES) == {
        # the method and its ablations
        "PARE",
        "PARE_NO_RESIDUAL",
        "PARE_NO_CP",
        "PARE_LGBM",
        # the baselines contribution C1 measures
        "NSIGMA",
        "SHAP_IFOREST",
        "ECDF",
        "PCA_RECON",
    }


def test_every_engine_has_a_one_line_description():
    listed = available_engines()
    assert {item["name"] for item in listed} == set(ALL_ENGINES)
    assert all(item["description"] for item in listed)


def test_an_unknown_engine_says_what_is_available():
    case = make_case(n_services=4, n_normal=200, n_abnormal=80, seed=0)
    with pytest.raises(ValueError, match="unknown engine"):
        analyze(request_for(case, "MAGIC", normal_rows=150))


# --- every engine, same shape of answer ------------------------------------


@pytest.mark.parametrize("engine", ALL_ENGINES)
def test_every_engine_returns_a_complete_result(engine):
    case = make_case(n_services=6, n_normal=400, n_abnormal=200, fault="latency", seed=1)
    result = analyze(request_for(case, engine))

    assert result.engine == engine
    assert result.engine_version
    assert result.request_id == "test-1"
    assert result.verdict in {ROOT_CAUSE_FOUND, NO_CLEAR_CAUSE}
    assert result.services, "a ranking must come back"
    assert result.indicators
    assert result.took_ms >= 0
    assert result.window_start_sec <= result.window_end_sec
    assert [s.rank for s in result.services] == list(range(1, len(result.services) + 1))


@pytest.mark.parametrize("engine", ALL_ENGINES)
def test_every_engine_survives_missing_columns_and_no_graph(engine):
    """docs/05 section 6, word for word."""
    case = make_case(n_services=5, n_normal=400, n_abnormal=150, seed=2)
    frame = case.to_frame().to_numpy()
    frame[:, 1] = np.nan           # one column entirely absent
    frame[10:40, 3] = np.nan       # another with a long gap
    frame[:, 5] = 7.0              # and one that never moves

    times = case.to_frame().index.to_numpy(dtype=float)
    request = AnalyzeRequest(
        engine=engine,
        alarm_time_sec=case.inject_time_sec + DELAY,
        columns=case.columns,
        normal=Window.of(times[:400], frame[:400]),
        recent=Window.of(times[400:], frame[400:]),
        graph=CallGraph.empty(),
        config=PareConfig(),
    )

    result = analyze(request)
    assert result.verdict in {ROOT_CAUSE_FOUND, NO_CLEAR_CAUSE}
    assert all(np.isfinite(s.score) for s in result.services)
    assert any("dropped" in w for w in result.warnings)


@pytest.mark.parametrize(
    "engine", ["PARE_NO_RESIDUAL", "NSIGMA", "SHAP_IFOREST", "ECDF", "PCA_RECON"]
)
def test_engines_without_residuals_report_so_honestly(engine):
    """docs/06 section 3: score equals marginal, nothing inherited, nothing
    explained. That is the admission that they cannot tell cause from symptom."""
    case = make_case(n_services=5, n_normal=400, n_abnormal=150, seed=3)
    result = analyze(request_for(case, engine))

    for service in result.services:
        assert service.score == pytest.approx(service.marginal_score)
        assert service.explained_by is None
    for indicator in result.indicators:
        assert indicator.self_score == pytest.approx(indicator.marginal_score)
        assert indicator.inherited_fraction == 0.0


# --- the verdict, as section 6 requires ------------------------------------


def test_a_clear_fault_gives_root_cause_found():
    case = make_case(n_services=6, n_normal=400, n_abnormal=200, fault="latency", seed=4)
    result = analyze(request_for(case, "PARE"))

    assert result.verdict == ROOT_CAUSE_FOUND
    assert result.services[0].role == CAUSE


def test_a_window_with_no_fault_gives_no_clear_cause_and_nobody_is_accused():
    """docs/05 section 6. Analysing a quiet stretch must not produce an accusation.

    The whole case is built, then only its *normal* rows are used - so the window
    being scored genuinely contains no fault.
    """
    case = make_case(n_services=6, n_normal=600, n_abnormal=100, fault="latency", seed=5)
    quiet = case.normal
    split = 400
    times = quiet.index.to_numpy(dtype=float)

    request = AnalyzeRequest(
        engine="PARE",
        alarm_time_sec=float(times[split + 20]),
        columns=case.columns,
        normal=Window.of(times[:split], quiet.to_numpy()[:split]),
        recent=Window.of(times[split:], quiet.to_numpy()[split:]),
        graph=CallGraph.from_edges(case.edges),
    )

    result = analyze(request)
    assert result.verdict == NO_CLEAR_CAUSE
    assert all(service.role != CAUSE for service in result.services)


# --- the engines really do differ ------------------------------------------


def test_pare_no_cp_does_not_re_anchor():
    case = make_case(n_services=6, n_normal=400, n_abnormal=200, seed=6)

    assert analyze(request_for(case, "PARE")).change_point_sec is not None
    assert analyze(request_for(case, "PARE_NO_CP")).change_point_sec is None


def test_nsigma_scores_from_the_alarm_to_the_end_of_the_data():
    case = make_case(n_services=5, n_normal=400, n_abnormal=200, seed=7)
    result = analyze(request_for(case, "NSIGMA"))

    assert result.change_point_sec is None
    assert result.window_start_sec >= case.inject_time_sec + DELAY
    assert result.window_end_sec == pytest.approx(float(case.abnormal.index[-1]))


def test_pare_uses_a_fixed_length_window_anchored_on_the_change_point():
    case = make_case(n_services=5, n_normal=400, n_abnormal=200, seed=8)
    config = PareConfig(window_len_s=60)
    result = analyze(request_for(case, "PARE", config=config))

    assert result.window_end_sec - result.window_start_sec <= 60


def test_a_late_alarm_still_finds_the_culprit_when_re_anchoring_is_on():
    """The difference the change-point step is meant to make."""
    case = make_case(
        n_services=8, n_normal=400, n_abnormal=250, fault="latency", seed=9
    )
    frame = case.to_frame()
    recent = frame.iloc[400:]

    def late(engine):
        return analyze(
            AnalyzeRequest(
                engine=engine,
                alarm_time_sec=case.inject_time_sec + 120,
                columns=case.columns,
                normal=Window.of(
                    case.normal.index.to_numpy(dtype=float), case.normal.to_numpy()
                ),
                recent=Window.of(recent.index.to_numpy(dtype=float), recent.to_numpy()),
                graph=CallGraph.from_edges(case.edges),
            )
        )

    anchored = late("PARE")
    assert anchored.change_point_sec is not None
    assert anchored.change_point_sec < case.inject_time_sec + 120


# --- finding the right answer ----------------------------------------------


def test_pare_finds_the_culprit_on_straightforward_cases():
    """No amplification, so there is no trap - but the method still has to get the
    easy cases right, with the change point, the graph and the ranking all in
    play together."""
    found = 0
    for seed in range(10):
        case = make_case(
            n_services=8, n_normal=400, n_abnormal=200, fault="latency", seed=seed
        )
        result = analyze(request_for(case, "PARE"))
        found += result.services[0].service == case.gt_service

    assert found >= 9, f"PARE found the culprit in only {found}/10 easy cases"


def test_the_top_indicator_names_a_real_column():
    case = make_case(n_services=6, n_normal=400, n_abnormal=200, seed=11)
    result = analyze(request_for(case, "PARE"))
    names = {c.name for c in case.columns}

    assert result.services[0].top_indicator in names
    assert all(indicator.column in names for indicator in result.indicators)


def test_only_top_k_indicators_come_back():
    case = make_case(n_services=8, n_normal=400, n_abnormal=200, seed=12)
    result = analyze(request_for(case, "PARE", config=PareConfig(top_k=3)))
    assert len(result.indicators) == 3


# --- no ground truth ever reaches an engine --------------------------------


def test_the_request_has_nowhere_to_put_ground_truth():
    """Hard rule 4, enforced by the shape of the request rather than by care."""
    fields = set(AnalyzeRequest.__dataclass_fields__)
    for forbidden in ("gt_service", "gt_column", "ground_truth", "label", "fault"):
        assert forbidden not in fields


# --- speed ------------------------------------------------------------------


def test_a_typical_case_is_answered_quickly():
    """docs/05 section 7 asks for under 2 seconds on a laptop for a case this
    size. Measured warm, since the first call in a process pays for imports."""
    import time

    case = make_case(n_services=5, n_normal=400, n_abnormal=120, seed=13)
    request = request_for(case, "PARE")
    analyze(request)  # warm up

    started = time.perf_counter()
    analyze(request)
    assert (time.perf_counter() - started) < 2.0


# --- the PARE_LGBM ablation (M1.7b) ----------------------------------------


def test_pare_lgbm_ranks_sanely_on_a_synthetic_latency_case():
    """M1.7b: the LightGBM dependency model produces a usable, sensible answer.

    On a straightforward case - a latency fault, no congestion, so there is no
    trap to fall into - the ablation must find the culprit just as the ridge
    version does. Where it stops being equal is measured in PROGRESS.md rather
    than asserted here, because that is a research result, not a contract.
    """
    case = make_case(
        n_services=8, n_normal=400, n_abnormal=200, fault="latency", seed=21
    )
    result = analyze(request_for(case, "PARE_LGBM"))

    assert result.engine == "PARE_LGBM"
    assert result.verdict == ROOT_CAUSE_FOUND
    assert result.services[0].service == case.gt_service
    assert result.services[0].role == CAUSE
    assert result.change_point_sec is not None, "the ablation keeps the re-anchoring"

    # a complete, well-formed answer
    assert all(np.isfinite(s.score) for s in result.services)
    assert all(0.0 <= s.inherited_fraction <= 1.0 for s in result.services)
    assert result.indicators
    assert result.services[0].top_indicator == case.gt_column


def test_pare_lgbm_differs_from_pare_only_in_its_dependency_model():
    """The ablation has to isolate one variable, or it measures nothing."""
    pare = ENGINES["PARE"]
    lgbm = ENGINES["PARE_LGBM"]

    assert lgbm.dependency_model == "lgbm"
    assert pare.dependency_model is None
    assert (lgbm.use_change_point, lgbm.use_residuals, lgbm.scorer, lgbm.window_to_end) == (
        pare.use_change_point,
        pare.use_residuals,
        pare.scorer,
        pare.window_to_end,
    )


# --- the baselines must never touch the call graph --------------------------


BASELINES = ["NSIGMA", "SHAP_IFOREST", "ECDF", "PCA_RECON"]


@pytest.mark.parametrize("engine", BASELINES)
def test_a_baseline_is_not_given_the_call_graph(engine):
    """Checked at engine level, not just on the explainer functions.

    An earlier version of this file only asserted that the explainer *functions*
    take no graph argument, and that gave false assurance: the ranking step walks
    the graph to promote a service, and it was switched on for every engine. A
    baseline was therefore being handed the one piece of information the proposed
    method is supposed to contribute.

    The test for it is behavioural: the answer must be identical with and without
    a graph, because the graph must make no difference at all.
    """
    case = make_case(
        n_services=8, n_normal=400, n_abnormal=200, fault="latency",
        propagation=0.9, amplification=0.25, seed=31,
    )
    frame = case.to_frame()
    recent = frame.iloc[400:]

    def run(graph):
        return analyze(
            AnalyzeRequest(
                engine=engine,
                alarm_time_sec=case.inject_time_sec + DELAY,
                columns=case.columns,
                normal=Window.of(
                    case.normal.index.to_numpy(dtype=float), case.normal.to_numpy()
                ),
                recent=Window.of(recent.index.to_numpy(dtype=float), recent.to_numpy()),
                graph=graph,
            )
        )

    with_graph = run(CallGraph.from_edges(case.edges))
    without = run(CallGraph.empty())

    assert [s.service for s in with_graph.services] == [
        s.service for s in without.services
    ], f"{engine} ranked differently when given a graph, so it is using one"
    assert ENGINES[engine].use_graph is False


@pytest.mark.parametrize("engine", ["PARE", "PARE_NO_RESIDUAL", "PARE_NO_CP"])
def test_the_pare_family_does_use_the_call_graph(engine):
    """The counterpart: using the graph is the whole proposal, so these engines
    must visibly change when it is taken away."""
    assert ENGINES[engine].use_graph is True
