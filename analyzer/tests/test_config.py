"""Tests for PareConfig.

The important one is test_defaults_match_spec_table: it copies the table from
docs/05_PYTHON_ANALYZER_SPEC.md section 1.1 so that changing a default without
updating the spec (or the other way round) fails the build instead of quietly
changing every result in the paper.
"""

import dataclasses

import pytest

from pare.config import (
    PareConfig,
    api_param_name,
    api_param_names,
)

# Copied by hand from docs/05_PYTHON_ANALYZER_SPEC.md section 1.1.
SPEC_DEFAULTS = {
    "seed": 42,
    "max_nan_fraction": 0.5,
    "fill_limit": 3,
    "use_change_point": True,
    "cp_top_k": 5,
    "cp_lookback_s": 300.0,
    "cp_lookahead_s": 60.0,
    "window_len_s": 120.0,
    "dependency_model": "ridge",
    "ridge_alpha": 1.0,
    "service_agg": "max",
    "traversal": True,
    "symptom_min_marginal": 3.0,
    "symptom_min_inherited": 0.6,
    "min_cause_score": 3.0,
    "top_k": 10,
}


def test_defaults_match_spec_table():
    cfg = PareConfig()
    for name, expected in SPEC_DEFAULTS.items():
        assert getattr(cfg, name) == expected, f"default for {name} does not match the spec"


def test_spec_table_covers_every_parameter():
    """No parameter may exist that the spec table does not list."""
    actual = {f.name for f in dataclasses.fields(PareConfig)}
    assert actual == set(SPEC_DEFAULTS), (
        "PareConfig and the spec table disagree about which parameters exist; "
        f"only in code: {sorted(actual - set(SPEC_DEFAULTS))}, "
        f"only in spec: {sorted(set(SPEC_DEFAULTS) - actual)}"
    )


def test_config_is_frozen():
    cfg = PareConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.seed = 7  # type: ignore[misc]


def test_with_changes_builds_the_ablation_variants():
    cfg = PareConfig()

    no_cp = cfg.with_changes(use_change_point=False)
    assert no_cp.use_change_point is False
    assert cfg.use_change_point is True, "the original must not be touched"

    lgbm = cfg.with_changes(dependency_model="lgbm")
    assert lgbm.dependency_model == "lgbm"
    # everything else is unchanged
    assert lgbm.with_changes(dependency_model="ridge") == cfg


def test_with_changes_rejects_an_unknown_parameter():
    with pytest.raises(ValueError, match="unknown PareConfig parameters"):
        PareConfig().with_changes(use_changepoint=False)


def test_with_changes_revalidates():
    with pytest.raises(ValueError, match="dependency_model"):
        PareConfig().with_changes(dependency_model="xgboost")


@pytest.mark.parametrize(
    "changes, expected_message",
    [
        ({"dependency_model": "xgboost"}, "dependency_model"),
        ({"service_agg": "mean"}, "service_agg"),
        ({"max_nan_fraction": 1.5}, "max_nan_fraction"),
        ({"max_nan_fraction": -0.1}, "max_nan_fraction"),
        ({"symptom_min_inherited": 2.0}, "symptom_min_inherited"),
        ({"window_len_s": 0}, "window_len_s"),
        ({"cp_lookback_s": -1}, "cp_lookback_s"),
        ({"cp_lookahead_s": -1}, "cp_lookahead_s"),
        ({"fill_limit": -1}, "fill_limit"),
        ({"cp_top_k": 0}, "cp_top_k"),
        ({"top_k": 0}, "top_k"),
        ({"ridge_alpha": -1.0}, "ridge_alpha"),
        ({"min_cause_score": -1.0}, "min_cause_score"),
        ({"symptom_min_marginal": -1.0}, "symptom_min_marginal"),
    ],
)
def test_validation_rejects_impossible_values(changes, expected_message):
    with pytest.raises(ValueError, match=expected_message):
        PareConfig(**changes)


def test_zero_lookahead_is_allowed_because_that_is_the_replay_case():
    cfg = PareConfig(cp_lookahead_s=0.0)
    assert cfg.cp_lookahead_s == 0.0


# --- the API boundary -------------------------------------------------------


def test_api_param_name_conversion():
    assert api_param_name("seed") == "seed"
    assert api_param_name("top_k") == "topK"
    assert api_param_name("cp_top_k") == "cpTopK"
    assert api_param_name("use_change_point") == "useChangePoint"
    assert api_param_name("cp_lookback_s") == "cpLookbackS"


def test_the_param_names_in_the_data_contract_are_all_valid():
    """The example params in docs/06_DATA_CONTRACTS.md section 3 must work."""
    documented = {"useChangePoint", "traversal", "topK", "seed", "cpTopK"}
    assert documented <= set(api_param_names())


def test_from_api_params_with_nothing_gives_the_defaults():
    assert PareConfig.from_api_params(None) == PareConfig()
    assert PareConfig.from_api_params({}) == PareConfig()


def test_from_api_params_applies_only_the_keys_given():
    cfg = PareConfig.from_api_params({"useChangePoint": False, "topK": 3, "seed": 7})
    assert cfg.use_change_point is False
    assert cfg.top_k == 3
    assert cfg.seed == 7
    # untouched keys keep their defaults, as the contract promises
    assert cfg.cp_top_k == SPEC_DEFAULTS["cp_top_k"]
    assert cfg.dependency_model == SPEC_DEFAULTS["dependency_model"]


def test_from_api_params_rejects_an_unknown_key():
    """A request saying topk instead of topK should be told, not silently ignored."""
    with pytest.raises(ValueError, match="unknown params"):
        PareConfig.from_api_params({"topk": 3})


def test_from_api_params_still_validates():
    with pytest.raises(ValueError, match="top_k"):
        PareConfig.from_api_params({"topK": 0})


def test_api_params_round_trip():
    cfg = PareConfig(use_change_point=False, top_k=4, dependency_model="lgbm")
    assert PareConfig.from_api_params(cfg.to_api_params()) == cfg
