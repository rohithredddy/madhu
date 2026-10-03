"""PareConfig: every tunable number the method uses, in one place.

Why one dataclass instead of constants spread through the code: the parameters
are reported in the paper, sent over the API by the Java backend, and varied in
the ablations. Keeping them together means there is exactly one place to read
when you want to know what the method actually did.

The table in ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 1.1 is the spec for this
file. ``tests/test_config.py`` checks every default against it, so the two cannot
drift apart silently.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

# The two string parameters have a small closed set of valid values.
DEPENDENCY_MODELS = ("ridge", "lgbm")
SERVICE_AGGREGATIONS = ("max", "top2mean")


@dataclass(frozen=True)
class PareConfig:
    """Parameters for one analysis run.

    Frozen on purpose. An analysis should never change its own settings halfway
    through, and the ablation engines are simply variants of the default
    config - ``PARE_NO_CP`` is ``replace(cfg, use_change_point=False)``. Use
    :meth:`with_changes` to make a variant.
    """

    # --- reproducibility ---
    seed: int = 42
    """Random seed for every engine that uses randomness."""

    # --- step 0, preprocessing ---
    max_nan_fraction: float = 0.5
    """Drop a column with more than this fraction of NaN in the normal data."""

    fill_limit: int = 3
    """Forward-fill then back-fill gaps of at most this many rows."""

    # --- step 2, change-point re-anchoring ---
    use_change_point: bool = True
    """Re-anchor the analysis window on the estimated change point."""

    cp_top_k: int = 5
    """How many of the most unusual columns are used to estimate the change point."""

    cp_lookback_s: float = 300.0
    """How far before the alarm the change-point search starts, in seconds."""

    cp_lookahead_s: float = 60.0
    """How far after the alarm the search may look. Offline only; 0 in replay,
    because no later row has been played yet."""

    window_len_s: float = 120.0
    """Length of the analysis (abnormal) window, in seconds."""

    # --- step 3, dependency model ---
    dependency_model: str = "ridge"
    """Which model predicts a service's metric from the services it calls:
    ``"ridge"`` or ``"lgbm"``."""

    ridge_alpha: float = 1.0
    """Ridge regularisation strength."""

    # --- step 4, ranking and roles ---
    service_agg: str = "max"
    """How a service score is built from its columns: ``"max"`` or ``"top2mean"``."""

    traversal: bool = True
    """Use the call-graph traversal step when picking rank 1."""

    symptom_min_marginal: float = 3.0
    """A service must look at least this abnormal to be called SYMPTOM or
    ALSO_ABNORMAL."""

    symptom_min_inherited: float = 0.6
    """Inherited fraction needed to be called SYMPTOM rather than ALSO_ABNORMAL."""

    min_cause_score: float = 3.0
    """If the top service score is below this, the verdict is NO_CLEAR_CAUSE and
    no service is given the role CAUSE. This is what lets the method say "I see
    nothing clear" instead of always accusing whichever service ranks first."""

    # --- step 5, what comes back ---
    top_k: int = 10
    """How many indicators are returned in the response. Not the same thing as
    ``cp_top_k``, which is an internal detail of the change-point step."""

    def __post_init__(self) -> None:
        """Reject impossible settings straight away.

        A typo in a config file should fail here with a clear message, not
        produce a quietly strange result a hundred lines later.
        """
        if self.dependency_model not in DEPENDENCY_MODELS:
            raise ValueError(
                f"dependency_model must be one of {DEPENDENCY_MODELS}, "
                f"got {self.dependency_model!r}"
            )
        if self.service_agg not in SERVICE_AGGREGATIONS:
            raise ValueError(
                f"service_agg must be one of {SERVICE_AGGREGATIONS}, got {self.service_agg!r}"
            )

        # Fractions have to be fractions.
        for name in ("max_nan_fraction", "symptom_min_inherited"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")

        # Window lengths must be long enough to hold data.
        for name in ("window_len_s", "cp_lookback_s"):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0, got {value}")

        # These may be 0 (0 lookahead is exactly the replay case) but not negative.
        if self.cp_lookahead_s < 0:
            raise ValueError(f"cp_lookahead_s must be 0 or more, got {self.cp_lookahead_s}")
        if self.fill_limit < 0:
            raise ValueError(f"fill_limit must be 0 or more, got {self.fill_limit}")

        # Counts must be at least 1 to mean anything.
        for name in ("cp_top_k", "top_k"):
            value = getattr(self, name)
            if value < 1:
                raise ValueError(f"{name} must be at least 1, got {value}")

        if self.ridge_alpha < 0:
            raise ValueError(f"ridge_alpha must be 0 or more, got {self.ridge_alpha}")

        # A negative threshold would make every service a CAUSE.
        for name in ("symptom_min_marginal", "min_cause_score"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be 0 or more, got {value}")

    def with_changes(self, **changes: Any) -> PareConfig:
        """Return a copy with some parameters changed, re-validated.

        This is how the ablation engines are built, for example
        ``cfg.with_changes(use_change_point=False)`` for ``PARE_NO_CP``.
        """
        unknown = set(changes) - {f.name for f in fields(self)}
        if unknown:
            raise ValueError(f"unknown PareConfig parameters: {sorted(unknown)}")
        return replace(self, **changes)

    @classmethod
    def from_api_params(cls, params: dict[str, Any] | None) -> PareConfig:
        """Build a config from the ``params`` object of an AnalyzeRequest.

        The API uses camelCase (``docs/06_DATA_CONTRACTS.md`` section 3) while the
        fields here are snake_case, so the names are converted mechanically by
        :func:`api_param_name`. Missing keys keep their default, which is what the
        contract promises.

        An unknown key is an error rather than being ignored: a request that says
        ``topk`` instead of ``topK`` should be told so, not silently analysed with
        the default.
        """
        if not params:
            return cls()

        by_api_name = {api_param_name(f.name): f.name for f in fields(cls)}
        unknown = sorted(set(params) - set(by_api_name))
        if unknown:
            raise ValueError(
                f"unknown params: {unknown}. Valid keys are {sorted(by_api_name)}"
            )
        return cls(**{by_api_name[key]: value for key, value in params.items()})

    def to_api_params(self) -> dict[str, Any]:
        """The inverse of :meth:`from_api_params`, for logging and for saving the
        settings next to a result."""
        return {api_param_name(f.name): getattr(self, f.name) for f in fields(self)}


def api_param_name(field_name: str) -> str:
    """Convert a field name to its camelCase name on the API.

    ``use_change_point`` -> ``useChangePoint``, ``top_k`` -> ``topK``,
    ``cp_top_k`` -> ``cpTopK``, ``seed`` -> ``seed``.

    A mechanical rule rather than a hand-written table, so there is no second
    list of names to keep in step with the dataclass.
    """
    head, *rest = field_name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


def api_param_names() -> list[str]:
    """Every key an AnalyzeRequest may put in ``params``."""
    return [api_param_name(f.name) for f in fields(PareConfig)]
