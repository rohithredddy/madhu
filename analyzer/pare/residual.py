"""The core idea: how much of a service's trouble is actually its own?

Every other scorer in this project asks "how far did this number move". That
question has a built-in flaw in a microservice system, because when a service
breaks, everything waiting on it moves too - often further, and more visibly.
Rank by movement and you rank the victims.

So for each metric of each service, this module asks a different question. Learn
from the normal period how that metric usually relates to the services it calls.
Then, during the incident, predict it from those callees and look at what is left
over:

* **small residual** - the callees fully account for it. The service is waiting on
  someone else. It is a symptom.
* **large residual** - nothing it depends on explains this. The trouble starts
  here.

Two details matter more than they look:

* **The model never sees the service's own past.** An autoregressive term would
  learn the anomaly a row after it starts and then predict it away, hiding exactly
  what we are looking for. Features are the callees' columns only, at time t and
  t-1.
* **The model is fitted on normal rows only.** It must describe how things relate
  when nothing is wrong; the incident is what it is then tested against.

A known limit, measured rather than assumed: when propagation is strongly
non-linear - heavy queueing or retry storms - the relationship during the incident
is one the normal period never showed, so a model fitted on normal data cannot
reproduce it and the caller gets a large residual too. The synthetic study
measures where that starts (``docs/05_PYTHON_ANALYZER_SPEC.md`` section 5), and
it is a limit of metric-only analysis rather than of this implementation.

Spec: ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3, step 3.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pare.columns import ColumnInfo, group_by_service
from pare.config import PareConfig
from pare.graph import CallGraph
from pare.scores import robust_baseline, window_score

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ColumnResidual:
    """What we learned about one column.

    ``self_score`` is the ranking number; ``inherited_fraction`` is the reporting
    number, and the two are deliberately on different scales. The score is in
    residual-spread units so that columns can be compared with each other; the
    fraction is in the metric's own raw units so that "about 80 percent of this
    was explained by cartservice" is a true statement about the metric.
    """

    column: str
    service: str
    self_score: float
    """How unusual the unexplained part is, in robust deviations. The ranking."""

    marginal_score: float
    """How unusual the raw column is, ignoring dependencies. What a naive method
    would have used."""

    inherited_fraction: float
    """Between 0 and 1: how much of the movement the callees account for."""

    explained_by: str | None
    """The callee that accounts for most of it, if any."""

    modelled: bool
    """True if a dependency model was fitted. False means the service has no
    usable callees, so the self-score is simply the marginal score."""


@dataclass(frozen=True)
class DependencyModel:
    """Fitted models for every column, and the scores that come out of them.

    Build with :meth:`fit`, which does the work; the object is mostly a record of
    what happened, so a result can be explained after the fact.
    """

    residuals: tuple[ColumnResidual, ...]
    warnings: tuple[str, ...] = ()

    def by_column(self) -> dict[str, ColumnResidual]:
        return {item.column: item for item in self.residuals}

    @classmethod
    def fit(
        cls,
        normal: npt.ArrayLike,
        abnormal: npt.ArrayLike,
        columns: Sequence[ColumnInfo],
        graph: CallGraph | None = None,
        config: PareConfig | None = None,
    ) -> DependencyModel:
        """Fit on the normal rows, then score the abnormal window.

        Args:
            normal: Rows from before the incident, rows by columns.
            abnormal: The analysis window, same columns in the same order.
            columns: The column map.
            graph: Who calls whom. Without one, nothing can be explained away and
                every self-score equals its marginal score.
            config: Parameters; defaults are used when not given.
        """
        settings = config or PareConfig()
        call_graph = graph or CallGraph.empty()

        normal_values = _as_block(normal, len(columns), "normal")
        abnormal_values = _as_block(abnormal, len(columns), "abnormal")

        index_of = {column.name: position for position, column in enumerate(columns)}
        results: list[ColumnResidual] = []
        warnings: list[str] = []

        for service, own_columns in group_by_service(columns).items():
            feature_names = [
                column.name
                for callee in call_graph.children(service)
                for column in columns
                if column.service == callee
            ]
            feature_indexes = [index_of[name] for name in feature_names]

            for column in own_columns:
                target = index_of[column.name]
                result, problem = _score_one_column(
                    column=column,
                    target=target,
                    feature_indexes=feature_indexes,
                    feature_names=feature_names,
                    callees=call_graph.children(service),
                    columns=columns,
                    normal_values=normal_values,
                    abnormal_values=abnormal_values,
                    settings=settings,
                )
                results.append(result)
                if problem:
                    warnings.append(problem)

        return cls(residuals=tuple(results), warnings=tuple(warnings))


# --- one column -------------------------------------------------------------


def _score_one_column(
    column: ColumnInfo,
    target: int,
    feature_indexes: Sequence[int],
    feature_names: Sequence[str],
    callees: Sequence[str],
    columns: Sequence[ColumnInfo],
    normal_values: FloatArray,
    abnormal_values: FloatArray,
    settings: PareConfig,
) -> tuple[ColumnResidual, str | None]:
    """Score one column, with a dependency model if there is one to build."""
    normal_column = normal_values[:, target]
    abnormal_column = abnormal_values[:, target]

    marginal = float(
        window_score(normal_values[:, [target]], abnormal_values[:, [target]])[0]
    )
    with warnings.catch_warnings():
        # A column with no readings at all is an expected input, not a mistake.
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        marginal_dev = abs(
            float(np.nanmedian(abnormal_column)) - float(np.nanmedian(normal_column))
        )
    if not np.isfinite(marginal_dev):
        marginal_dev = 0.0

    fitted = None
    if feature_indexes:
        fitted = _fit_dependency(
            normal_values, abnormal_values, target, feature_indexes, settings
        )

    if fitted is None:
        # No callees, or nothing usable to learn from. The residual is then just
        # the deviation from normal, so the self-score is the marginal score and
        # nothing is inherited. Saying "0 percent explained" is the honest answer
        # here: we had nothing to explain it with.
        return (
            ColumnResidual(
                column=column.name,
                service=column.service,
                self_score=marginal,
                marginal_score=marginal,
                inherited_fraction=0.0,
                explained_by=None,
                modelled=False,
            ),
            None,
        )

    normal_residual, abnormal_residual, contributions = fitted

    baseline = robust_baseline(normal_residual.reshape(-1, 1))
    residual_median = float(baseline.median[0])
    abnormal_residual_median = float(np.nanmedian(abnormal_residual))

    self_score = abs(abnormal_residual_median - residual_median) / float(baseline.scale[0])
    self_dev = abs(abnormal_residual_median - residual_median)

    # Both deviations are in the metric's raw units, so this really is a fraction.
    inherited = 0.0 if marginal_dev == 0 else 1.0 - (self_dev / marginal_dev)
    inherited = float(min(max(inherited, 0.0), 1.0))

    explained_by = _largest_contributor(contributions, feature_names, callees, columns)

    return (
        ColumnResidual(
            column=column.name,
            service=column.service,
            self_score=float(self_score),
            marginal_score=marginal,
            inherited_fraction=inherited,
            explained_by=explained_by,
            modelled=True,
        ),
        None,
    )


def _fit_dependency(
    normal_values: FloatArray,
    abnormal_values: FloatArray,
    target: int,
    feature_indexes: Sequence[int],
    settings: PareConfig,
) -> tuple[FloatArray, FloatArray, FloatArray] | None:
    """Fit one column from its callees and return the residuals it leaves.

    Returns ``(normal residuals, abnormal residuals, per-feature contributions)``
    or None when there is nothing usable to fit, in which case the caller falls
    back to the marginal score.
    """
    normal_x, normal_y = _design(normal_values, target, feature_indexes)
    abnormal_x, abnormal_y = _design(abnormal_values, target, feature_indexes)
    if normal_x is None or abnormal_x is None:
        return None

    usable = np.isfinite(normal_x).all(axis=1) & np.isfinite(normal_y)
    if int(usable.sum()) < max(10, normal_x.shape[1] + 2):
        # Too little clean history to learn a relationship worth trusting.
        return None

    train_x = normal_x[usable]
    train_y = normal_y[usable]

    # Standardise the features on the normal period, as the spec says. The target
    # stays in its raw units, because the inherited fraction is defined there.
    centre = train_x.mean(axis=0)
    spread = train_x.std(axis=0)
    moving = spread > 0
    if not moving.any():
        return None  # every callee column is flat; nothing to explain anything with

    def standardise(matrix: FloatArray) -> FloatArray:
        scaled = (matrix[:, moving] - centre[moving]) / spread[moving]
        return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)

    model = _make_model(settings)
    model.fit(standardise(train_x), train_y)

    normal_residual = normal_y - model.predict(standardise(normal_x))
    abnormal_residual = abnormal_y - model.predict(standardise(abnormal_x))

    contributions = _contributions(model, standardise, normal_x, abnormal_x, moving)
    return normal_residual, abnormal_residual, contributions


def _make_model(settings: PareConfig):
    """Ridge by default; LightGBM when asked for, as the PARE_LGBM ablation."""
    if settings.dependency_model == "lgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=100,
            max_depth=3,
            random_state=settings.seed,
            verbose=-1,
        )

    from sklearn.linear_model import Ridge

    return Ridge(alpha=settings.ridge_alpha)


def _design(
    block: FloatArray, target: int, feature_indexes: Sequence[int]
) -> tuple[FloatArray | None, FloatArray | None]:
    """Build the features at t and t-1, and the matching target.

    The first row of each block is dropped, because it has no t-1. The service's
    own values never appear here - that is the point.
    """
    if block.shape[0] < 2:
        return None, None
    chosen = list(feature_indexes)
    current = block[1:, chosen]
    previous = block[:-1, chosen]
    return np.hstack([current, previous]), block[1:, target]


def _contributions(
    model,
    standardise,
    normal_x: FloatArray,
    abnormal_x: FloatArray,
    moving: npt.NDArray[np.bool_],
) -> FloatArray:
    """How much each feature pushed the prediction up during the incident.

    Measured by asking the fitted model a counterfactual: what would it have
    predicted if this feature had stayed at its normal level, everything else
    being as it actually was? For a linear model this is exactly the quantity the
    spec names - ``coef_j * (median(abnormal_j) - median(normal_j))`` in
    standardised units - but it is computed this way so the same code also works
    for the LightGBM variant, which has no coefficients to read.
    """
    normal_point = np.nanmedian(normal_x, axis=0, keepdims=True)
    abnormal_point = np.nanmedian(abnormal_x, axis=0, keepdims=True)
    normal_point = np.nan_to_num(normal_point, nan=0.0)
    abnormal_point = np.nan_to_num(abnormal_point, nan=0.0)

    actual = float(model.predict(standardise(abnormal_point))[0])

    contributions = np.zeros(normal_x.shape[1], dtype=np.float64)
    for feature in range(normal_x.shape[1]):
        if not moving[feature]:
            continue
        counterfactual = abnormal_point.copy()
        counterfactual[0, feature] = normal_point[0, feature]
        without = float(model.predict(standardise(counterfactual))[0])
        contributions[feature] = actual - without
    return contributions


def _largest_contributor(
    contributions: FloatArray,
    feature_names: Sequence[str],
    callees: Sequence[str],
    columns: Sequence[ColumnInfo],
) -> str | None:
    """Which callee accounts for most of the rise, if any does.

    Features come in two blocks - time t then time t-1 - over the same callee
    columns, so both halves are credited to the same service.
    """
    if contributions.size == 0 or not callees:
        return None

    service_of = {column.name: column.service for column in columns}
    width = len(feature_names)
    totals: dict[str, float] = {name: 0.0 for name in callees}

    for position, value in enumerate(contributions):
        name = feature_names[position % width] if width else None
        if name is None:
            continue
        service = service_of.get(name)
        if service in totals:
            totals[service] += float(value)

    best = max(totals, key=lambda service: totals[service])
    # Only a positive contribution counts as an explanation: a callee that pushed
    # the prediction down did not cause the rise.
    return best if totals[best] > 0 else None


def _as_block(values: npt.ArrayLike, n_columns: int, label: str) -> FloatArray:
    data = np.asarray(values, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"{label} must be rows by columns, got {data.ndim} dimensions")
    if data.shape[1] != n_columns:
        raise ValueError(
            f"{label} has {data.shape[1]} columns but {n_columns} were described"
        )
    if data.shape[0] == 0:
        raise ValueError(f"{label} has no rows")
    return data
