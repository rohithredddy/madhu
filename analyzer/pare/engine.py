"""The engines: one entry point, several methods, one shape of answer.

``analyze(request)`` runs whichever engine was asked for and always returns the
same object, so the experiments and the Java backend never have to care which one
ran. That uniformity is what makes the comparisons in the paper possible at all.

The engines differ along three axes, and nothing else:

===================  ============  =========  ================================
engine               change point  residuals  window
===================  ============  =========  ================================
``PARE``             yes           yes        re-anchored on the change point
``PARE_NO_RESIDUAL`` yes           no         re-anchored on the change point
``PARE_NO_CP``       no            yes        starts at the alarm
``PARE_LGBM``        yes           yes        re-anchored; LightGBM dependency
``NSIGMA``           no            no         alarm to the end of the data
``SHAP_IFOREST``     no            no         alarm to the end of the data
``ECDF``             no            no         alarm to the end of the data
``PCA_RECON``        no            no         alarm to the end of the data
===================  ============  =========  ================================

The two ablations exist to answer "which half does the work": ``PARE_NO_RESIDUAL``
keeps the re-anchoring but scores by raw movement, and ``PARE_NO_CP`` keeps the
residuals but takes the alarm at face value.

The last four are the baselines contribution C1 measures: ``NSIGMA`` and the
three explainer methods people normally reach for. None of them uses the call
graph or the change point, because the published versions do not, and scoring
them any other way would make the comparison flattering rather than fair.

Spec: ``docs/05_PYTHON_ANALYZER_SPEC.md`` sections 3 and 4; the result maps field
for field onto ``AnalyzeResponse`` in ``docs/06_DATA_CONTRACTS.md`` section 3.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from pare import __version__
from pare.changepoint import estimate_change_point
from pare.columns import ColumnInfo
from pare.config import PareConfig
from pare.explainers import ecdf_explainer, pca_reconstruction, shap_iforest
from pare.graph import CallGraph
from pare.preprocess import preprocess
from pare.rank import NO_CLEAR_CAUSE, IndicatorRanking, Ranking, ServiceRanking, rank_all
from pare.residual import ColumnResidual, DependencyModel
from pare.scores import nsigma_score, robust_baseline, window_score

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Window:
    """A block of rows and the time of each one."""

    times_sec: FloatArray
    values: FloatArray

    def __post_init__(self) -> None:
        if self.values.ndim != 2:
            raise ValueError(f"values must be rows by columns, got {self.values.ndim} dims")
        if self.times_sec.shape[0] != self.values.shape[0]:
            raise ValueError(
                f"got {self.times_sec.shape[0]} times for {self.values.shape[0]} rows"
            )

    @classmethod
    def of(cls, times_sec: npt.ArrayLike, values: npt.ArrayLike) -> Window:
        return cls(
            times_sec=np.asarray(times_sec, dtype=np.float64),
            values=np.asarray(values, dtype=np.float64),
        )

    @property
    def n_rows(self) -> int:
        return int(self.values.shape[0])


@dataclass(frozen=True)
class AnalyzeRequest:
    """Everything an engine needs. Ground truth is deliberately not among it."""

    engine: str
    alarm_time_sec: float
    columns: Sequence[ColumnInfo]
    normal: Window
    recent: Window
    graph: CallGraph = field(default_factory=CallGraph.empty)
    config: PareConfig = field(default_factory=PareConfig)
    request_id: str | None = None


@dataclass(frozen=True)
class AnalyzeResult:
    """The answer. Maps field for field onto AnalyzeResponse in docs/06."""

    engine: str
    engine_version: str
    verdict: str
    alarm_time_sec: float
    window_start_sec: float
    window_end_sec: float
    services: tuple[ServiceRanking, ...]
    indicators: tuple[IndicatorRanking, ...]
    took_ms: int
    change_point_sec: float | None = None
    warnings: tuple[str, ...] = ()
    request_id: str | None = None


@dataclass(frozen=True)
class EngineSpec:
    """What makes one engine different from another."""

    name: str
    description: str
    use_change_point: bool
    use_residuals: bool
    scorer: str = "robust"
    """Which per-column score to use when no dependency model is fitted:
    ``robust`` (median and MAD), ``nsigma`` (mean and standard deviation),
    ``ecdf``, ``shap_iforest`` or ``pca_recon``."""

    window_to_end: bool = False
    """True means score from the alarm to the end of the data, rather than a
    fixed-length window."""

    dependency_model: str | None = None

    service_agg: str | None = None
    """Overrides the configured aggregation. Only SHAP_IFOREST sets it, because
    the method it reproduces sums a service's columns."""

    use_graph: bool = True
    """May this engine see the call graph at all?

    False for every baseline. They do not take a graph as a feature, and they must
    not get one through the back door either: the ranking step can walk the graph
    to move a service up, and leaving that switched on for a baseline would be
    quietly handing it the one piece of information the proposed method is
    supposed to be contributing."""


ENGINES: dict[str, EngineSpec] = {
    "PARE": EngineSpec(
        name="PARE",
        description="Propagation-aware residual explanations (proposed)",
        use_change_point=True,
        use_residuals=True,
    ),
    "PARE_NO_RESIDUAL": EngineSpec(
        name="PARE_NO_RESIDUAL",
        description="Ablation: change-point re-anchoring but no dependency model",
        use_change_point=True,
        use_residuals=False,
    ),
    "PARE_NO_CP": EngineSpec(
        name="PARE_NO_CP",
        description="Ablation: dependency model but the window starts at the alarm",
        use_change_point=False,
        use_residuals=True,
    ),
    "PARE_LGBM": EngineSpec(
        name="PARE_LGBM",
        description="Ablation: LightGBM instead of ridge as the dependency model",
        use_change_point=True,
        use_residuals=True,
        dependency_model="lgbm",
    ),
    "NSIGMA": EngineSpec(
        name="NSIGMA",
        description="Baseline: mean shift over normal standard deviation, no graph",
        use_change_point=False,
        use_residuals=False,
        scorer="nsigma",
        window_to_end=True,
        use_graph=False,
    ),
    "SHAP_IFOREST": EngineSpec(
        name="SHAP_IFOREST",
        description="Baseline: Isolation Forest with TreeSHAP attribution (GAL-MAD style)",
        use_change_point=False,
        use_residuals=False,
        scorer="shap_iforest",
        window_to_end=True,
        service_agg="sum",
        use_graph=False,
    ),
    "ECDF": EngineSpec(
        name="ECDF",
        description="Baseline: ECOD-style empirical tail probability per metric",
        use_change_point=False,
        use_residuals=False,
        scorer="ecdf",
        window_to_end=True,
        use_graph=False,
    ),
    "PCA_RECON": EngineSpec(
        name="PCA_RECON",
        description="Baseline: PCA reconstruction error per metric",
        use_change_point=False,
        use_residuals=False,
        scorer="pca_recon",
        window_to_end=True,
        use_graph=False,
    ),
}


def available_engines() -> list[dict[str, str]]:
    """Name and one-line description of each engine, for ``GET /v1/engines``."""
    return [
        {"name": spec.name, "description": spec.description} for spec in ENGINES.values()
    ]


def analyze(request: AnalyzeRequest) -> AnalyzeResult:
    """Run one engine over one incident."""
    started = time.perf_counter()

    spec = ENGINES.get(request.engine)
    if spec is None:
        raise ValueError(
            f"unknown engine {request.engine!r}; available: {sorted(ENGINES)}"
        )

    settings = request.config
    if spec.dependency_model is not None:
        settings = settings.with_changes(dependency_model=spec.dependency_model)
    if spec.service_agg is not None:
        settings = settings.with_changes(service_agg=spec.service_agg)
    if not spec.use_change_point:
        settings = settings.with_changes(use_change_point=False)

    warnings: list[str] = []
    clean = preprocess(
        request.normal.values, request.recent.values, request.columns, settings
    )
    warnings.extend(clean.warnings)

    if clean.is_empty:
        return _empty_result(request, spec, warnings, started)

    baseline = robust_baseline(clean.normal)

    change_point = None
    if spec.use_change_point:
        change_point = estimate_change_point(
            request.recent.times_sec,
            clean.recent,
            clean.columns,
            baseline,
            request.alarm_time_sec,
            settings,
        )
        if not change_point.estimated:
            warnings.append(change_point.reason)

    anchor = change_point.time_sec if change_point else request.alarm_time_sec
    window, start, end, problem = _analysis_window(
        request.recent, anchor, spec, settings, request.alarm_time_sec
    )
    if problem:
        warnings.append(problem)
    if window.size == 0:
        return _empty_result(request, spec, [*warnings, "the analysis window is empty"], started)

    abnormal = clean.recent[window]

    if spec.use_residuals:
        model = DependencyModel.fit(
            clean.normal, abnormal, clean.columns, request.graph, settings
        )
        residuals = list(model.residuals)
        warnings.extend(model.warnings)
    else:
        residuals = _scores_only(clean, abnormal, spec, settings)

    # A baseline is ranked without the graph, so the traversal step cannot move a
    # service for it. See EngineSpec.use_graph.
    ranking_graph = request.graph if spec.use_graph else CallGraph.empty()
    ranking = rank_all(residuals, ranking_graph, settings)
    took_ms = int(round((time.perf_counter() - started) * 1000))

    return AnalyzeResult(
        engine=spec.name,
        engine_version=__version__,
        verdict=ranking.verdict,
        alarm_time_sec=float(request.alarm_time_sec),
        change_point_sec=(
            float(change_point.time_sec) if change_point and change_point.estimated else None
        ),
        window_start_sec=float(start),
        window_end_sec=float(end),
        services=ranking.services,
        indicators=ranking.indicators,
        took_ms=took_ms,
        warnings=tuple(warnings),
        request_id=request.request_id,
    )


# --- the pieces -------------------------------------------------------------


def _analysis_window(
    recent: Window,
    anchor: float,
    spec: EngineSpec,
    settings: PareConfig,
    alarm_time_sec: float,
) -> tuple[npt.NDArray[np.bool_], float, float, str | None]:
    """Which rows of ``recent`` get scored.

    The single definition of these is the table in ``docs/05`` section 3, step 2.
    """
    times = recent.times_sec
    if spec.window_to_end:
        chosen = times >= alarm_time_sec
        label = "from the alarm to the end of the data"
    else:
        chosen = (times >= anchor) & (times <= anchor + settings.window_len_s)
        label = "the fixed-length window"

    if not chosen.any():
        # Nothing matched. Rather than give up, score whatever sits at or after
        # the alarm, and say that is what happened.
        fallback = times >= alarm_time_sec
        if fallback.any():
            return (
                fallback,
                float(times[fallback][0]),
                float(times[fallback][-1]),
                f"{label} contained no rows; scored from the alarm onwards instead",
            )
        return chosen, float(anchor), float(anchor), None

    picked = times[chosen]
    return chosen, float(picked[0]), float(picked[-1]), None


def _scores_only(
    clean, abnormal: FloatArray, spec: EngineSpec, settings: PareConfig
) -> list[ColumnResidual]:
    """Score every column on its own, with no dependency model.

    Used by every engine that is not PARE or one of its residual ablations. Per
    ``docs/06`` section 3 these engines report ``score == marginalScore``, nothing
    inherited and nothing explained - which is exactly the admission that they
    cannot tell a cause from a symptom. Reporting it that way rather than hiding
    it is what makes the comparison in the paper legible.
    """
    scorers = {
        "robust": lambda: window_score(clean.normal, abnormal),
        "nsigma": lambda: nsigma_score(clean.normal, abnormal),
        "ecdf": lambda: ecdf_explainer(clean.normal, abnormal, settings),
        "shap_iforest": lambda: shap_iforest(clean.normal, abnormal, settings),
        "pca_recon": lambda: pca_reconstruction(clean.normal, abnormal, settings),
    }
    if spec.scorer not in scorers:
        raise ValueError(f"unknown scorer {spec.scorer!r} on engine {spec.name}")
    scores = scorers[spec.scorer]()

    return [
        ColumnResidual(
            column=column.name,
            service=column.service,
            metric=column.metric,
            self_score=float(scores[index]),
            marginal_score=float(scores[index]),
            inherited_fraction=0.0,
            explained_by=None,
            modelled=False,
        )
        for index, column in enumerate(clean.columns)
    ]


def _empty_result(
    request: AnalyzeRequest,
    spec: EngineSpec,
    warnings: Sequence[str],
    started: float,
) -> AnalyzeResult:
    """Nothing could be scored. Say so rather than returning an empty ranking that
    looks like a confident "everything is fine"."""
    return AnalyzeResult(
        engine=spec.name,
        engine_version=__version__,
        verdict=NO_CLEAR_CAUSE,
        alarm_time_sec=float(request.alarm_time_sec),
        window_start_sec=float(request.alarm_time_sec),
        window_end_sec=float(request.alarm_time_sec),
        services=(),
        indicators=(),
        took_ms=int(round((time.perf_counter() - started) * 1000)),
        warnings=tuple(warnings),
        request_id=request.request_id,
    )


# Re-exported so callers can build a result without importing three modules.
__all__ = [
    "ENGINES",
    "AnalyzeRequest",
    "AnalyzeResult",
    "EngineSpec",
    "Ranking",
    "Window",
    "analyze",
    "available_engines",
]
