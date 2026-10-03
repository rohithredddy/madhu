"""Tests for the explainer baselines.

These are the methods contribution C1 measures, so the tests check that each one
is a faithful, working version of itself - not that it gets the right answer.
Where a baseline has a known weakness it is pinned here deliberately, because
that weakness is a finding the paper reports rather than a defect to patch.
"""

import numpy as np
import pytest

from pare.config import PareConfig
from pare.explainers import (
    KERNEL_SHAP_PCA_IMPLEMENTED,
    ecdf_explainer,
    kernel_shap_pca,
    pca_reconstruction,
    shap_iforest,
)

EXPLAINERS = [shap_iforest, ecdf_explainer, pca_reconstruction]
NAMES = ["shap_iforest", "ecdf_explainer", "pca_reconstruction"]


def planted(n_columns=8, culprit=3, n_normal=300, n_abnormal=100, size=8.0, seed=0):
    """Independent columns, one of which shifts during the abnormal window.

    Deliberately uncorrelated, so every method has a fair chance: with correlated
    columns PCA in particular cannot tell neighbours apart, which is tested
    separately.
    """
    rng = np.random.default_rng(seed)
    normal = rng.normal(0.0, 1.0, (n_normal, n_columns))
    abnormal = rng.normal(0.0, 1.0, (n_abnormal, n_columns))
    abnormal[:, culprit] += size
    return normal, abnormal


# --- each one works ---------------------------------------------------------


@pytest.mark.parametrize("explainer", EXPLAINERS, ids=NAMES)
def test_an_explainer_returns_one_finite_score_per_column(explainer):
    normal, abnormal = planted()
    scores = explainer(normal, abnormal, PareConfig())

    assert scores.shape == (normal.shape[1],)
    assert np.isfinite(scores).all()
    assert (scores >= 0).all(), "these are magnitudes; none should be negative"


@pytest.mark.parametrize(
    "explainer", [shap_iforest, ecdf_explainer], ids=["shap_iforest", "ecdf_explainer"]
)
def test_a_per_column_explainer_finds_a_single_planted_anomaly(explainer):
    """With one obvious culprit among independent columns, a method that scores
    each column on its own should find it. If it cannot, it is broken rather than
    merely limited.

    PCA reconstruction is excluded on purpose and tested separately: it is not a
    per-column method, and on independent columns it has no signal at all - see
    test_pca_reconstruction_is_blind_without_correlation.
    """
    normal, abnormal = planted(culprit=3)
    scores = explainer(normal, abnormal, PareConfig())
    assert int(np.argmax(scores)) == 3


@pytest.mark.parametrize(
    "explainer", [shap_iforest, ecdf_explainer], ids=["shap_iforest", "ecdf_explainer"]
)
def test_an_explainer_is_quiet_when_nothing_happened(explainer):
    """A window that looks like normal should not produce a confident accusation.
    Checked as a ratio, since the three use quite different units."""
    rng = np.random.default_rng(1)
    normal = rng.normal(0.0, 1.0, (300, 8))
    quiet = rng.normal(0.0, 1.0, (100, 8))

    calm = explainer(normal, quiet, PareConfig())
    broken = explainer(*planted(), PareConfig())

    assert calm.max() < broken.max()


@pytest.mark.parametrize("explainer", EXPLAINERS, ids=NAMES)
def test_an_explainer_copes_with_missing_values(explainer):
    """Isolation Forest and PCA both refuse NaN outright, so the gaps that step 0
    deliberately leaves behind have to be filled before they are reached."""
    normal, abnormal = planted()
    normal[5:30, 1] = np.nan
    normal[:, 6] = np.nan
    abnormal[0:10, 2] = np.nan

    scores = explainer(normal, abnormal, PareConfig())
    assert np.isfinite(scores).all()


@pytest.mark.parametrize("explainer", EXPLAINERS, ids=NAMES)
def test_an_explainer_accuses_nobody_when_there_is_too_little_history(explainer):
    normal, abnormal = planted(n_normal=5, n_abnormal=5)
    scores = explainer(normal, abnormal, PareConfig())
    assert np.isfinite(scores).all()


# --- the individual methods -------------------------------------------------


def test_shap_iforest_is_reproducible():
    """It is the only explainer with randomness in it, and every number in the
    paper has to be reproducible."""
    normal, abnormal = planted()
    first = shap_iforest(normal, abnormal, PareConfig(seed=42))
    second = shap_iforest(normal, abnormal, PareConfig(seed=42))
    different = shap_iforest(normal, abnormal, PareConfig(seed=7))

    assert np.allclose(first, second)
    assert not np.allclose(first, different)


def test_ecdf_explainer_is_the_tail_score_from_scores_py():
    from pare.scores import ecdf_tail_score

    normal, abnormal = planted()
    assert np.allclose(
        ecdf_explainer(normal, abnormal), ecdf_tail_score(normal, abnormal)
    )


def test_pca_reconstruction_smears_error_across_correlated_columns():
    """A known weakness, pinned on purpose.

    PCA rebuilds every column from shared components, so when one column breaks,
    the columns correlated with it fail to rebuild too. The method then often
    points at a neighbour of the culprit rather than the culprit. Measuring how
    often that happens on real failures is the point of experiment E1, so this
    must not be quietly "fixed".
    """
    rng = np.random.default_rng(2)
    shared = rng.normal(0.0, 1.0, 400)
    # columns 0, 1 and 2 move together; 3 and 4 are independent
    normal = np.column_stack(
        [
            shared,
            shared + rng.normal(0.0, 0.1, 400),
            shared + rng.normal(0.0, 0.1, 400),
            rng.normal(0.0, 1.0, 400),
            rng.normal(0.0, 1.0, 400),
        ]
    )
    abnormal = normal[:100].copy()
    abnormal[:, 0] += 10.0  # only column 0 actually breaks

    scores = pca_reconstruction(normal, abnormal, PareConfig())
    blamed = int(np.argmax(scores))

    # the blame lands somewhere in the correlated group, not necessarily on 0
    assert blamed in {0, 1, 2}
    assert scores[1] > scores[3], "the innocent neighbour outscores an unrelated column"


def test_kernel_shap_pca_is_honestly_absent():
    """Optional in the spec and not implemented. It raises with the reason rather
    than silently returning something that looks like an answer."""
    assert KERNEL_SHAP_PCA_IMPLEMENTED is False
    with pytest.raises(NotImplementedError, match="optional"):
        kernel_shap_pca(*planted())


# --- they are deliberately not improved ------------------------------------


def test_the_explainers_take_no_call_graph():
    """The published versions do not use one. Giving ours a graph would make the
    comparison in the paper flattering rather than fair, so there is nowhere to
    put it."""
    import inspect

    for explainer in EXPLAINERS:
        parameters = set(inspect.signature(explainer).parameters)
        assert "graph" not in parameters
        assert parameters <= {"normal", "abnormal", "config"}


def test_pca_reconstruction_is_blind_without_correlation():
    """A structural limitation, found while testing and worth reporting.

    Keeping 95 percent of the variance of independent columns means keeping
    essentially all the components, and a full-rank model rebuilds everything
    perfectly - the anomaly included. Every score then comes back at around
    1e-30, so a near-zero reconstruction error must never be read as "nothing is
    wrong"; it can equally mean "this method cannot see anything here".

    It does not bite on realistic telemetry, where metrics are heavily
    correlated, which the next test checks.
    """
    normal, abnormal = planted(n_columns=8, culprit=3, size=8.0)
    scores = pca_reconstruction(normal, abnormal, PareConfig())

    assert scores.max() < 1e-20, "independent columns should leave no signal at all"


def test_pca_reconstruction_does_have_signal_on_realistic_data():
    """The counterpart: on a generated case, where metrics really are related,
    the model is lossy and the errors are meaningful numbers."""
    from pare.synthetic import make_case

    case = make_case(
        n_services=8, n_normal=400, n_abnormal=200, fault="latency", propagation=0.9, seed=0
    )
    scores = pca_reconstruction(
        case.normal.to_numpy(), case.abnormal.to_numpy(), PareConfig()
    )

    assert scores.max() > 0.01
    assert np.isfinite(scores).all()
