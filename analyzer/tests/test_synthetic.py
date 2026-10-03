"""Tests for the synthetic generator.

The generator is the ground everything else is tested on, so these tests check
the properties the later milestones rely on: that a seed reproduces exactly, that
the fault really is where we say it is, and above all that propagation works and
responds to the ``propagation`` knob. If that last one broke, experiment E6 would
quietly measure nothing.
"""

import numpy as np
import pandas as pd
import pytest

from pare.synthetic import FAULTS, METRICS, make_case


def deviation_in_stds(case, column: str) -> float:
    """How far a column's abnormal median sits from its normal median, in units
    of its own normal spread. A rough stand-in for the real scorer, which does
    not exist until M1.3."""
    normal = case.normal[column]
    abnormal = case.abnormal[column]
    spread = normal.std()
    if spread <= 0:
        return 0.0
    return float(abs(abnormal.median() - normal.median()) / spread)


# --- shape and naming -------------------------------------------------------


def test_shape_and_columns():
    case = make_case(n_services=5, n_normal=200, n_abnormal=60, seed=1)

    assert len(case.normal) == 200
    assert len(case.abnormal) == 60
    assert len(case.columns) == 5 * len(METRICS)
    assert list(case.normal.columns) == [c.name for c in case.columns]
    assert list(case.abnormal.columns) == [c.name for c in case.columns]

    # the column map agrees with the names
    for column in case.columns:
        assert column.name == f"{column.service}_{column.metric}"
        assert column.metric in METRICS


def test_services_start_with_frontend():
    case = make_case(n_services=6, seed=2)
    assert case.services[0] == "frontend"
    assert len(case.services) == 6


def test_time_index_is_increasing_epoch_seconds():
    case = make_case(n_services=4, n_normal=50, n_abnormal=10, seed=3)
    frame = case.to_frame()

    assert frame.index.name == "time"
    assert frame.index.is_monotonic_increasing
    assert len(frame) == 60
    # one row per second
    assert int(frame.index[1] - frame.index[0]) == 1
    # the injection time is the first abnormal row
    assert case.inject_time_sec == int(case.abnormal.index[0])
    assert case.inject_time_sec > int(case.normal.index[-1])


def test_to_frame_is_the_two_halves_joined():
    case = make_case(n_services=4, n_normal=30, n_abnormal=10, seed=4)
    frame = case.to_frame()
    assert len(frame) == 40
    pd.testing.assert_frame_equal(frame.iloc[:30], case.normal)
    pd.testing.assert_frame_equal(frame.iloc[30:], case.abnormal)


def test_no_nan_and_no_negative_error_rates():
    case = make_case(n_services=8, fault="error", seed=5)
    frame = case.to_frame()
    assert not frame.isna().any().any()
    error_columns = [c.name for c in case.columns if c.metric == "error"]
    assert (frame[error_columns] >= 0).all().all()


# --- reproducibility --------------------------------------------------------


def test_same_seed_reproduces_exactly():
    a = make_case(n_services=7, seed=11)
    b = make_case(n_services=7, seed=11)

    pd.testing.assert_frame_equal(a.normal, b.normal)
    pd.testing.assert_frame_equal(a.abnormal, b.abnormal)
    assert a.gt_service == b.gt_service
    assert a.gt_column == b.gt_column
    assert a.edges == b.edges


def test_different_seeds_give_different_data():
    a = make_case(n_services=7, seed=11)
    b = make_case(n_services=7, seed=12)
    assert not a.normal.equals(b.normal)


# --- the call graph ---------------------------------------------------------


def test_graph_is_a_tree_rooted_at_frontend():
    case = make_case(n_services=12, seed=21)
    services = set(case.services)

    # a tree over n nodes has exactly n-1 edges
    assert len(case.edges) == 11

    callees = [callee for _, callee in case.edges]
    # every service except frontend is called exactly once, so there are no
    # cycles and nothing is unreachable
    assert sorted(callees) == sorted(services - {"frontend"})
    assert "frontend" not in callees

    for caller, callee in case.edges:
        assert caller in services
        assert callee in services
        assert caller != callee


# --- the fault --------------------------------------------------------------


@pytest.mark.parametrize("fault", FAULTS)
def test_ground_truth_points_at_the_metric_the_fault_uses(fault):
    case = make_case(n_services=6, fault=fault, seed=31)
    assert case.fault == fault
    assert case.gt_column == f"{case.gt_service}_{fault}"
    assert case.gt_column in case.normal.columns


@pytest.mark.parametrize("fault", FAULTS)
def test_the_fault_is_visible_in_the_ground_truth_column(fault):
    case = make_case(n_services=6, n_normal=400, n_abnormal=200, fault=fault, seed=32)
    assert deviation_in_stds(case, case.gt_column) > 2.0, (
        f"the {fault} fault is not visible in {case.gt_column}"
    )


@pytest.mark.parametrize("fault", FAULTS)
def test_the_normal_rows_are_clean(fault):
    """The first half of the normal rows must look like the second half. If the
    fault leaked backwards, splitting normal data for training would be unsafe."""
    case = make_case(n_services=6, n_normal=400, n_abnormal=100, fault=fault, seed=33)
    column = case.gt_column
    first_half = case.normal[column].iloc[:200]
    second_half = case.normal[column].iloc[200:]
    spread = case.normal[column].std()
    assert abs(first_half.median() - second_half.median()) < 1.5 * spread


def test_root_can_be_chosen():
    case = make_case(n_services=6, root="svc-03", fault="cpu", seed=34)
    assert case.gt_service == "svc-03"
    assert case.gt_column == "svc-03_cpu"


def test_an_unknown_root_is_rejected():
    with pytest.raises(ValueError, match="not one of the services"):
        make_case(n_services=5, root="cartservice", seed=35)


def test_ground_truth_is_never_a_column_in_the_data():
    """Hard rule 4: an engine must not be able to see the answer."""
    case = make_case(n_services=6, seed=36)
    names = set(case.normal.columns)
    for leak in ("gt_service", "gt_column", "ground_truth", "root_cause", "label", "fault"):
        assert leak not in names


# --- propagation, the property E6 depends on --------------------------------


def ancestors_of(case, service: str) -> list[str]:
    """The callers of a service, directly or indirectly."""
    caller_of = {callee: caller for caller, callee in case.edges}
    chain = []
    current = service
    while current in caller_of:
        current = caller_of[current]
        chain.append(current)
    return chain


def test_a_latency_fault_reaches_the_callers_and_not_everyone():
    """The core mechanism: callers of the culprit look abnormal, unrelated
    services do not. This is what makes the cause-versus-symptom problem real."""
    # frontend is always an ancestor of any non-frontend culprit, so this holds
    # for any seed; a fixed seed keeps the numbers stable.
    case = make_case(n_services=10, n_normal=500, n_abnormal=200, fault="latency", seed=41)
    culprit = case.gt_service
    chain = ancestors_of(case, culprit)
    assert chain, "a non-frontend culprit must have at least one caller"

    nearest_caller = chain[0]
    assert deviation_in_stds(case, f"{nearest_caller}_latency") > 1.0, (
        "the fault did not propagate to the caller"
    )

    # a service that is neither the culprit nor one of its callers, and that the
    # culprit does not call, should be untouched
    related = {culprit, *chain}
    descendants = {callee for caller, callee in case.edges if caller == culprit}
    unrelated = [s for s in case.services if s not in related | descendants]
    if unrelated:
        quiet = max(deviation_in_stds(case, f"{s}_latency") for s in unrelated)
        assert quiet < 1.0, "an unrelated service moved, so the fault is not localised"


@pytest.mark.parametrize("fault", ["latency", "cpu", "mem", "error"])
def test_every_fault_type_propagates_to_the_caller(fault):
    """Including mem and cpu, which reach callers through the latency term.

    If this ever fails for mem, experiment E6 can no longer say anything about
    symptoms for memory faults - see docs/05 section 5.
    """
    case = make_case(n_services=8, n_normal=500, n_abnormal=200, fault=fault, seed=42)
    chain = ancestors_of(case, case.gt_service)
    assert chain

    metric = "error" if fault == "error" else "latency"
    moved = max(deviation_in_stds(case, f"{s}_{metric}") for s in chain)
    assert moved > 0.5, f"a {fault} fault did not reach any caller through {metric}"


def test_stronger_propagation_moves_the_caller_more():
    """The knob E6 turns. Same seed, same culprit, only propagation differs."""
    weak = make_case(
        n_services=8, n_normal=500, n_abnormal=200, fault="latency", propagation=0.2, seed=43
    )
    strong = make_case(
        n_services=8, n_normal=500, n_abnormal=200, fault="latency", propagation=1.0, seed=43
    )
    assert weak.gt_service == strong.gt_service

    caller = ancestors_of(weak, weak.gt_service)[0]
    column = f"{caller}_latency"
    assert deviation_in_stds(strong, column) > deviation_in_stds(weak, column)


def test_zero_propagation_keeps_the_fault_where_it_started():
    case = make_case(
        n_services=8, n_normal=500, n_abnormal=200, fault="latency", propagation=0.0, seed=44
    )
    chain = ancestors_of(case, case.gt_service)
    moved = max(deviation_in_stds(case, f"{s}_latency") for s in chain)
    assert moved < 1.0
    # but the culprit itself is still clearly broken
    assert deviation_in_stds(case, case.gt_column) > 3.0


def test_frontend_as_the_culprit_has_nothing_to_propagate_to():
    case = make_case(n_services=6, fault="latency", root="frontend", seed=45)
    assert case.gt_service == "frontend"
    assert ancestors_of(case, "frontend") == []


# --- noise ------------------------------------------------------------------


def test_more_noise_means_a_wider_normal_spread():
    quiet = make_case(n_services=6, n_normal=400, noise=0.5, seed=51)
    loud = make_case(n_services=6, n_normal=400, noise=2.0, seed=51)

    column = "frontend_latency"
    assert loud.normal[column].std() > quiet.normal[column].std()


def test_the_fault_stays_visible_at_high_noise():
    """Fault sizes are multiples of the column's own spread, so a louder case
    should still be solvable."""
    loud = make_case(
        n_services=6, n_normal=500, n_abnormal=200, fault="latency", noise=2.0, seed=52
    )
    assert deviation_in_stds(loud, loud.gt_column) > 2.0


# --- argument checking ------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"fault": "disk"}, "fault must be one of"),
        ({"n_services": 1}, "n_services"),
        ({"n_normal": 1}, "n_normal"),
        ({"n_abnormal": 0}, "n_abnormal"),
        ({"propagation": -0.1}, "propagation"),
        ({"noise": 0.0}, "noise"),
        ({"noise": -1.0}, "noise"),
    ],
)
def test_bad_arguments_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        make_case(**kwargs)


# --- the E6 grid ------------------------------------------------------------


@pytest.mark.parametrize("n_services", [5, 40])
@pytest.mark.parametrize("propagation", [0.2, 1.0])
@pytest.mark.parametrize("fault", FAULTS)
def test_the_e6_factor_grid_builds(n_services, propagation, fault):
    """Every corner of the E6 grid in docs/08 must produce a usable case."""
    case = make_case(
        n_services=n_services,
        n_normal=200,
        n_abnormal=60,
        fault=fault,
        propagation=propagation,
        seed=61,
    )
    assert len(case.columns) == n_services * len(METRICS)
    assert np.isfinite(case.to_frame().to_numpy()).all()
    assert case.gt_column in case.normal.columns


# --- amplification: the mechanism that makes the symptom trap possible ------


def test_amplification_defaults_to_off_so_the_model_stays_linear():
    """Every earlier test and every stored result assumes the linear model, so
    the default must not change what make_case produces."""
    import inspect

    assert inspect.signature(make_case).parameters["amplification"].default == 0.0


def test_zero_amplification_is_exactly_the_linear_model():
    plain = make_case(n_services=8, fault="latency", seed=71)
    explicit = make_case(n_services=8, fault="latency", amplification=0.0, seed=71)
    pd.testing.assert_frame_equal(plain.abnormal, explicit.abnormal)


def test_a_negative_amplification_is_rejected():
    with pytest.raises(ValueError, match="amplification"):
        make_case(amplification=-1.0)


def test_congestion_is_dormant_while_everything_is_healthy():
    """The whole trick depends on this. If congestion fired during normal
    operation it would widen the caller's normal spread, and the effect would
    cancel itself out instead of creating a trap."""
    calm = make_case(n_services=8, n_normal=500, fault="latency", amplification=0.0, seed=72)
    loud = make_case(n_services=8, n_normal=500, fault="latency", amplification=2.0, seed=72)

    for column in ("frontend_latency", "svc-01_latency"):
        assert loud.normal[column].std() == pytest.approx(
            calm.normal[column].std(), rel=0.10
        ), f"{column}'s normal spread changed, so congestion is not dormant"


def test_with_amplification_a_caller_can_look_worse_than_the_culprit():
    """The point of the parameter, and the thing the linear model cannot do.

    Under linear propagation a caller's deviation can never exceed the culprit's,
    because raising the propagation weight scales the inherited signal and the
    inherited noise together. Congestion breaks that tie.
    """
    trapped = 0
    for seed in range(20):
        case = make_case(
            n_services=10, n_normal=500, n_abnormal=200, fault="latency",
            propagation=0.9, amplification=1.0, seed=seed,
        )
        callers = ancestors_of(case, case.gt_service)
        if not callers:
            continue
        culprit = deviation_in_stds(case, case.gt_column)
        worst_caller = max(deviation_in_stds(case, f"{s}_latency") for s in callers)
        if worst_caller > culprit:
            trapped += 1

    assert trapped >= 10, (
        f"only {trapped}/20 cases put a caller above the culprit; "
        "amplification is not producing the symptom trap"
    )


def test_without_amplification_a_caller_never_looks_worse_than_the_culprit():
    """The counterpart, and the reason amplification had to be added at all."""
    for seed in range(20):
        case = make_case(
            n_services=10, n_normal=500, n_abnormal=200, fault="latency",
            propagation=1.0, amplification=0.0, seed=seed,
        )
        callers = ancestors_of(case, case.gt_service)
        if not callers:
            continue
        culprit = deviation_in_stds(case, case.gt_column)
        worst_caller = max(deviation_in_stds(case, f"{s}_latency") for s in callers)
        assert worst_caller < culprit, f"seed {seed} trapped under a purely linear model"


def test_more_amplification_means_a_louder_caller():
    mild = make_case(
        n_services=8, n_normal=500, n_abnormal=200, fault="latency",
        propagation=0.9, amplification=0.5, seed=73,
    )
    severe = make_case(
        n_services=8, n_normal=500, n_abnormal=200, fault="latency",
        propagation=0.9, amplification=4.0, seed=73,
    )
    caller = ancestors_of(mild, mild.gt_service)[0]
    column = f"{caller}_latency"
    assert deviation_in_stds(severe, column) > deviation_in_stds(mild, column)


def test_the_case_records_the_amplification_it_was_built_with():
    case = make_case(n_services=5, amplification=0.75, seed=74)
    assert case.params["amplification"] == 0.75
