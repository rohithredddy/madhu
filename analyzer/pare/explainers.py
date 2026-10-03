"""The explainer baselines: how people usually explain an anomaly.

These are the methods contribution C1 is about. The common recipe in the
literature is to train an anomaly detector on normal data, run an attribution
method over the incident, and present the highest-scoring features as the
explanation. The question this project asks is whether those features are the
root cause or merely the loudest symptom, so the baselines have to be here, and
they have to be the ordinary versions of themselves.

That last point matters more than it sounds. Every one of these could be improved
- given the call graph, given a better window, given robust statistics. Improving
them would make our own method look worse *and* make the comparison dishonest,
because the claim is about what current practice does. So:

* none of them uses the call graph, because the published methods do not;
* none of them uses change-point re-anchoring, so they feel the full cost of a
  late alarm (``docs/05_PYTHON_ANALYZER_SPEC.md`` section 4);
* their quirks are left in. PCA reconstruction error smears across correlated
  columns and often points at a neighbour of the real one; that is a finding, not
  a bug to patch.

Each function returns one score per column, higher meaning more suspicious. The
engine wraps them, so they do not know about services, roles or verdicts.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest

from pare.config import PareConfig
from pare.scores import ecdf_tail_score

FloatArray = npt.NDArray[np.float64]

# Below this many clean rows, fitting a detector is not worth trusting and the
# caller is told to fall back to a simple score instead.
MIN_ROWS_TO_FIT = 20

# KernelSHAP on the PCA detector is listed as optional in the spec and is not
# implemented. It would need ~50 background rows times every column times every
# abnormal row of model evaluations, which is minutes per case against
# milliseconds for the rest, and it would answer the same question as PCA_RECON
# already answers. Recorded here so the omission is a decision, not an oversight.
KERNEL_SHAP_PCA_IMPLEMENTED = False


def shap_iforest(
    normal: FloatArray, abnormal: FloatArray, config: PareConfig | None = None
) -> FloatArray:
    """Isolation Forest plus TreeSHAP: the GAL-MAD style of explanation.

    Fit the detector on normal rows, attribute its score on the abnormal rows, and
    report the mean absolute SHAP value per column. The engine then sums those
    within a service, which is what the GAL-MAD paper does.

    Checked against the installed shap 0.49.1 during M0: ``TreeExplainer`` does
    support ``IsolationForest``, returns an array shaped like the input, and needs
    no ``check_additivity=False``.
    """
    settings = config or PareConfig()
    train, score_on = _impute(normal, abnormal)
    if train.shape[0] < MIN_ROWS_TO_FIT:
        return _no_opinion(normal.shape[1])

    import shap  # imported here: it costs about a second and only this engine needs it

    forest = IsolationForest(
        n_estimators=200, random_state=settings.seed
    ).fit(train)
    values = np.asarray(shap.TreeExplainer(forest).shap_values(score_on))

    if values.ndim != 2 or values.shape[1] != normal.shape[1]:
        return _no_opinion(normal.shape[1])
    return np.asarray(np.abs(values).mean(axis=0), dtype=np.float64)


def ecdf_explainer(
    normal: FloatArray, abnormal: FloatArray, config: PareConfig | None = None
) -> FloatArray:
    """ECOD-style tail probability, per column.

    Thin wrapper over :func:`pare.scores.ecdf_tail_score`, which is where the
    arithmetic lives because the same quantity is useful elsewhere. Kept as a
    named function so the engine registry reads the same way for every baseline.
    """
    return ecdf_tail_score(normal, abnormal)


def pca_reconstruction(
    normal: FloatArray, abnormal: FloatArray, config: PareConfig | None = None
) -> FloatArray:
    """PCA reconstruction error, per column.

    Keep enough components to explain 95 percent of the variance of the normal
    period, then ask how badly each column of the incident fails to be rebuilt
    from them. A column the model cannot reproduce is one behaving unlike normal.

    Two known weaknesses are left in place, because measuring them is the point of
    experiment E1:

    * **It smears blame.** The components are shared, so the error of one broken
      column spreads over every column correlated with it, and the method often
      points at a neighbour rather than the culprit.
    * **It is blind without correlation.** Keeping 95 percent of the variance of
      largely independent columns means keeping nearly all the components, and a
      full-rank model reconstructs everything perfectly - including the anomaly.
      Reconstruction error is then about 1e-30 for every column and the method has
      no opinion at all. On realistic telemetry this does not bite (a generated
      case with 40 columns keeps 17 components), but on a handful of unrelated
      metrics it does, and that is worth knowing before trusting a near-zero
      score as "nothing is wrong".
    """
    train, score_on = _impute(normal, abnormal)
    if train.shape[0] < MIN_ROWS_TO_FIT or train.shape[1] == 0:
        return _no_opinion(normal.shape[1])

    centre = train.mean(axis=0)
    spread = train.std(axis=0)
    spread = np.where(spread > 0, spread, 1.0)

    standard_train = (train - centre) / spread
    standard_score = (score_on - centre) / spread

    # Never ask for more components than the data can supply.
    limit = min(standard_train.shape)
    if limit < 1:
        return _no_opinion(normal.shape[1])

    model = PCA(n_components=0.95, svd_solver="full").fit(standard_train)
    rebuilt = model.inverse_transform(model.transform(standard_score))
    error = np.asarray(((standard_score - rebuilt) ** 2).mean(axis=0), dtype=np.float64)
    return np.nan_to_num(error, nan=0.0, posinf=0.0, neginf=0.0)


def kernel_shap_pca(
    normal: FloatArray, abnormal: FloatArray, config: PareConfig | None = None
) -> FloatArray:
    """Not implemented. See :data:`KERNEL_SHAP_PCA_IMPLEMENTED`."""
    raise NotImplementedError(
        "KERNEL_SHAP_PCA is optional in docs/05 section 4 and is not implemented: it would "
        "cost minutes per case where the other explainers cost milliseconds, and it answers "
        "the same question as PCA_RECON. Use PCA_RECON."
    )


# --- shared helpers ---------------------------------------------------------


def _impute(normal: FloatArray, abnormal: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Fill what is left of the missing values, using normal-period medians.

    Isolation Forest and PCA both refuse NaN outright, and step 0 only fills short
    gaps - a long outage is deliberately left missing. Filling with the normal
    median here is the least opinionated choice available: it says "assume this
    column was behaving normally while we could not see it", which understates an
    anomaly rather than inventing one.
    """
    import warnings

    with warnings.catch_warnings():
        # A column with no readings at all is an expected input, not a mistake.
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        reference = np.nanmedian(normal, axis=0)
    reference = np.nan_to_num(reference, nan=0.0)

    def fill(block: FloatArray) -> FloatArray:
        out = np.array(block, dtype=np.float64, copy=True)
        missing = ~np.isfinite(out)
        if missing.any():
            out[missing] = np.broadcast_to(reference, out.shape)[missing]
        return out

    return fill(normal), fill(abnormal)


def _no_opinion(n_columns: int) -> FloatArray:
    """All zeros: this explainer could not be fitted, so it accuses nobody."""
    return np.zeros(n_columns, dtype=np.float64)
