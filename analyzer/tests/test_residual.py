"""Tests for the dependency model - the core idea of the method.

docs/05 section 6 names the test this module has to pass:

    if a parent's latency is exactly a linear function of a child's latency, the
    parent's self-score is near 0 when only the child is faulty

That is the whole claim in one sentence, so it comes first. The rest guards the
properties the ranking depends on, and the rule that the model must never see the
service's own past.
"""

import numpy as np
import pytest

from pare.columns import ColumnInfo
from pare.config import PareConfig
from pare.graph import CallGraph
from pare.residual import DependencyModel
from pare.synthetic import make_case

N_NORMAL = 400
N_ABNORMAL = 120


def parent_child_case(fault_size=6.0, slope=2.0, parent_noise=1.0, seed=0):
    """A parent whose latency is `slope` times its child's, plus noise of its own.
    Only the child is faulty.

    `parent_noise` is the parent's own jitter, as a real service has. It is set
    well below the child's spread of 5.0 but not to nothing: with a near-zero
    value the residual's normal spread also goes to near zero, and then any tiny
    slope error in the fitted model is divided by almost nothing and looks huge.
    That is a property of the ratio, not of the method, and
    `test_a_symptoms_self_score_grows_with_how_far_the_fault_extrapolates`
    measures it deliberately instead.

    Returns (normal, abnormal, columns, graph).
    """
    rng = np.random.default_rng(seed)
    total = N_NORMAL + N_ABNORMAL

    child = rng.normal(100.0, 5.0, total)
    fault = np.concatenate([np.zeros(N_NORMAL), np.full(N_ABNORMAL, fault_size * 5.0)])
    child = child + fault

    parent = slope * child + rng.normal(0.0, parent_noise, total)

    values = np.column_stack([parent, child])
    columns = [
        ColumnInfo("parent_latency", "parent", "latency"),
        ColumnInfo("child_latency", "child", "latency"),
    ]
    graph = CallGraph.from_edges([("parent", "child")])
    return values[:N_NORMAL], values[N_NORMAL:], columns, graph


# --- the test the spec names ------------------------------------------------


def test_a_parent_that_is_a_linear_function_of_its_child_has_a_self_score_near_zero():
    """docs/05 section 6, word for word.

    The parent moves a long way - it is twice the child, so it moves twice as far -
    but none of that movement is its own. This is the difference between the method
    and every scorer that only measures movement.
    """
    normal, abnormal, columns, graph = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph).by_column()

    parent = model["parent_latency"]
    child = model["child_latency"]

    # the parent really did move a long way - about as far as the child did
    assert parent.marginal_score > 5.0
    assert parent.marginal_score == pytest.approx(child.marginal_score, rel=0.25)
    assert parent.self_score < 1.0, (
        f"the parent's self-score is {parent.self_score:.2f}; its movement is fully "
        "explained by its child, so this should be near zero"
    )
    assert child.self_score > parent.self_score * 5, (
        "the child, which actually broke, must rank far above the parent"
    )


def test_the_naive_score_would_have_blamed_the_parent():
    """Why the method exists. By movement alone the parent looks worse."""
    normal, abnormal, columns, graph = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph).by_column()

    parent, child = model["parent_latency"], model["child_latency"]

    assert parent.marginal_score > child.marginal_score, (
        "this setup is meant to be one where movement alone points at the parent"
    )
    assert child.self_score > parent.self_score, (
        "after removing what the child explains, the child must come out on top"
    )


def test_the_inherited_fraction_tells_the_story_in_plain_numbers():
    normal, abnormal, columns, graph = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph).by_column()

    assert model["parent_latency"].inherited_fraction > 0.9, "almost all inherited"
    assert model["child_latency"].inherited_fraction == 0.0, "the child inherits nothing"


def test_explained_by_names_the_child():
    normal, abnormal, columns, graph = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph).by_column()

    assert model["parent_latency"].explained_by == "child"
    assert model["child_latency"].explained_by is None


# --- the rule that the model must not see its own past ---------------------


def test_the_model_never_uses_the_services_own_history():
    """An autoregressive term would learn the anomaly a row after it starts and
    then predict it away, hiding the very thing we are looking for.

    A strongly autocorrelated faulty service is where that would show: if its own
    past were a feature, its residual would collapse. It must not.
    """
    rng = np.random.default_rng(1)
    total = N_NORMAL + N_ABNORMAL

    # a slow random walk: each value is very close to the one before it
    own = np.cumsum(rng.normal(0.0, 0.3, total)) + 50.0
    own[N_NORMAL:] += 40.0  # and then it breaks
    unrelated = rng.normal(10.0, 1.0, total)

    values = np.column_stack([own, unrelated])
    columns = [
        ColumnInfo("broken_latency", "broken", "latency"),
        ColumnInfo("other_latency", "other", "latency"),
    ]
    graph = CallGraph.from_edges([("broken", "other")])

    model = DependencyModel.fit(
        values[:N_NORMAL], values[N_NORMAL:], columns, graph
    ).by_column()

    assert model["broken_latency"].self_score > 3.0, (
        "the broken service's own history must not be available to explain it away"
    )


# --- without a graph --------------------------------------------------------


def test_with_no_graph_the_self_score_is_the_marginal_score():
    """PARE still runs without a call graph; it simply has nothing to subtract."""
    normal, abnormal, columns, _ = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph=None).by_column()

    for result in model.values():
        assert result.self_score == pytest.approx(result.marginal_score)
        assert result.inherited_fraction == 0.0
        assert result.explained_by is None
        assert result.modelled is False


def test_a_service_with_no_callees_is_scored_on_its_own():
    normal, abnormal, columns, graph = parent_child_case()
    model = DependencyModel.fit(normal, abnormal, columns, graph).by_column()

    child = model["child_latency"]
    assert child.modelled is False
    assert child.self_score == pytest.approx(child.marginal_score)


def test_an_empty_graph_is_the_same_as_no_graph():
    normal, abnormal, columns, _ = parent_child_case()
    without = DependencyModel.fit(normal, abnormal, columns, None).by_column()
    empty = DependencyModel.fit(normal, abnormal, columns, CallGraph.empty()).by_column()

    for name in without:
        assert without[name].self_score == pytest.approx(empty[name].self_score)


# --- properties that must always hold --------------------------------------


@pytest.mark.parametrize("fault", ["latency", "cpu", "mem", "error"])
def test_the_inherited_fraction_is_always_between_zero_and_one(fault):
    """Required by docs/05 section 6, and the UI prints it as a percentage."""
    case = make_case(n_services=6, n_normal=400, n_abnormal=150, fault=fault, seed=3)
    graph = CallGraph.from_edges(case.edges)

    model = DependencyModel.fit(
        case.normal.to_numpy(), case.abnormal.to_numpy(), case.columns, graph
    )
    for result in model.residuals:
        assert 0.0 <= result.inherited_fraction <= 1.0, result


def test_every_column_gets_exactly_one_result():
    case = make_case(n_services=5, n_normal=300, n_abnormal=100, seed=4)
    graph = CallGraph.from_edges(case.edges)

    model = DependencyModel.fit(
        case.normal.to_numpy(), case.abnormal.to_numpy(), case.columns, graph
    )
    assert len(model.residuals) == len(case.columns)
    assert {r.column for r in model.residuals} == {c.name for c in case.columns}


def test_scores_are_finite_even_with_missing_and_flat_columns():
    rng = np.random.default_rng(5)
    total = N_NORMAL + N_ABNORMAL
    values = np.column_stack(
        [
            rng.normal(0.0, 1.0, total),
            np.full(total, 3.0),          # flat
            np.full(total, np.nan),       # entirely missing
        ]
    )
    values[10:20, 0] = np.nan             # scattered gaps
    columns = [
        ColumnInfo("a_latency", "a", "latency"),
        ColumnInfo("b_latency", "b", "latency"),
        ColumnInfo("c_latency", "c", "latency"),
    ]
    graph = CallGraph.from_edges([("a", "b"), ("a", "c")])

    model = DependencyModel.fit(values[:N_NORMAL], values[N_NORMAL:], columns, graph)
    for result in model.residuals:
        assert np.isfinite(result.self_score)
        assert np.isfinite(result.marginal_score)
        assert 0.0 <= result.inherited_fraction <= 1.0


def test_input_shapes_are_checked():
    normal, abnormal, columns, graph = parent_child_case()
    with pytest.raises(ValueError, match="normal must be rows by columns"):
        DependencyModel.fit(normal.ravel(), abnormal, columns, graph)
    with pytest.raises(ValueError, match="abnormal has 1 columns"):
        DependencyModel.fit(normal, abnormal[:, :1], columns, graph)
    with pytest.raises(ValueError, match="no rows"):
        DependencyModel.fit(normal[:0], abnormal, columns, graph)


# --- the LightGBM variant ---------------------------------------------------


def test_the_lgbm_variant_blames_the_symptom_because_trees_cannot_extrapolate():
    """A real limitation of the PARE_LGBM ablation, pinned here so it is not
    mistaken for a bug later.

    A fault pushes the callee far outside anything seen in the normal period. A
    tree model cannot extrapolate: beyond the range it was trained on its
    prediction is flat, so it predicts the parent at its normal level and the
    parent's entire inherited rise lands in the residual. The ablation therefore
    ranks the symptom above the cause - the exact mistake the method exists to
    prevent.

    This is worth a test rather than a note, because it is a clean negative result
    for the paper: root-cause analysis needs a model that extrapolates, and that
    rules out tree ensembles however good they are at interpolating.
    """
    normal, abnormal, columns, graph = parent_child_case()

    ridge = DependencyModel.fit(
        normal, abnormal, columns, graph, PareConfig(dependency_model="ridge")
    ).by_column()
    lgbm = DependencyModel.fit(
        normal, abnormal, columns, graph, PareConfig(dependency_model="lgbm")
    ).by_column()

    # ridge explains the parent away and ranks the child first
    assert ridge["parent_latency"].self_score < ridge["child_latency"].self_score

    # lgbm does the opposite, and by a wide margin
    assert lgbm["parent_latency"].self_score > lgbm["child_latency"].self_score
    assert lgbm["parent_latency"].self_score > 10 * ridge["parent_latency"].self_score


# --- end to end on generated data ------------------------------------------


def test_on_a_trapped_synthetic_case_the_residual_finds_the_culprit():
    """The case the whole project is about: amplification set so that movement
    alone points at a caller, and the residual still finds the service that broke.
    """
    rescued = 0
    trapped = 0
    for seed in range(20):
        case = make_case(
            n_services=8, n_normal=500, n_abnormal=200, fault="latency",
            propagation=0.9, amplification=0.25, seed=seed,
        )
        graph = CallGraph.from_edges(case.edges)
        model = DependencyModel.fit(
            case.normal.to_numpy(), case.abnormal.to_numpy(), case.columns, graph
        )

        marginal: dict[str, float] = {}
        residual: dict[str, float] = {}
        for result in model.residuals:
            marginal[result.service] = max(
                marginal.get(result.service, 0.0), result.marginal_score
            )
            residual[result.service] = max(
                residual.get(result.service, 0.0), result.self_score
            )

        top_marginal = max(marginal, key=lambda s: marginal[s])
        top_residual = max(residual, key=lambda s: residual[s])
        if top_marginal != case.gt_service:
            trapped += 1
            if top_residual == case.gt_service:
                rescued += 1

    assert trapped >= 2, f"only {trapped}/20 cases trapped the naive score; check the setup"
    assert rescued == trapped, (
        f"the residual rescued only {rescued} of {trapped} cases where movement alone "
        "pointed at a caller"
    )


def test_a_symptoms_self_score_grows_with_how_far_the_fault_extrapolates():
    """A real property of the method, measured rather than assumed.

    A symptom's residual is not exactly zero. The model is fitted on the normal
    range and the incident pushes its inputs well outside that range, so any small
    error in the fitted slope - and ridge regularisation guarantees a small one,
    because it shrinks coefficients deliberately - is multiplied by how far the
    fault reaches. The leftover therefore grows in proportion to the size of the
    fault, even though the share explained stays essentially the same.

    The practical consequence, which belongs in the paper's limitations: for very
    large faults a symptom accumulates self-score, so the margin between cause and
    symptom narrows rather than staying constant.
    """
    scores = []
    for fault_size in (2.0, 6.0, 12.0, 24.0):
        normal, abnormal, columns, graph = parent_child_case(
            fault_size=fault_size, parent_noise=0.1
        )
        result = DependencyModel.fit(normal, abnormal, columns, graph).by_column()
        parent = result["parent_latency"]
        scores.append(parent.self_score)
        # the share explained barely moves, which is the point: the fraction is
        # stable even while the normalised score is not
        assert parent.inherited_fraction > 0.99

    assert scores == sorted(scores), f"expected a growing leftover, got {scores}"
    assert scores[-1] > 4 * scores[0], (
        "the leftover should grow roughly in proportion to the fault size"
    )
