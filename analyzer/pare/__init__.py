"""pare - Propagation-Aware Residual Explanations.

A CPU-only method that explains anomalies in a microservice system and ranks
root causes. The idea in one sentence: for every service, learn from normal data
how its metrics depend on the services it calls, and then judge a service by the
part of its deviation that those dependencies do *not* explain.

The package is used two ways:
  1. as a library by the offline experiments in ``experiments/``
  2. through the small FastAPI service in ``service/``, which the Java backend calls

See ``docs/05_PYTHON_ANALYZER_SPEC.md`` for the algorithm and
``docs/06_DATA_CONTRACTS.md`` for the shapes that cross a process boundary.
"""

# Single source of truth for the version. pyproject.toml reads it from here, the
# service returns it from /health, and every AnalyzeResponse carries it as
# "engineVersion", so a stored result can always be traced to the code that made it.
__version__ = "0.1.0"

from pare.changepoint import ChangePoint, estimate_change_point
from pare.columns import (
    ColumnInfo,
    columns_from_dicts,
    columns_of_service,
    group_by_service,
    name_to_index,
    services,
    validate_columns,
)
from pare.config import PareConfig
from pare.engine import (
    ENGINES,
    AnalyzeRequest,
    AnalyzeResult,
    Window,
    analyze,
    available_engines,
)
from pare.explainers import ecdf_explainer, pca_reconstruction, shap_iforest
from pare.graph import CallGraph, Edge
from pare.preprocess import preprocess
from pare.rank import IndicatorRanking, Ranking, ServiceRanking, rank_all
from pare.residual import ColumnResidual, DependencyModel
from pare.scores import (
    RobustBaseline,
    ecdf_tail_score,
    mad,
    robust_baseline,
    robust_z,
    window_score,
)

__all__ = [
    "__version__",
    "ENGINES",
    "AnalyzeRequest",
    "AnalyzeResult",
    "IndicatorRanking",
    "Ranking",
    "ServiceRanking",
    "Window",
    "analyze",
    "available_engines",
    "preprocess",
    "rank_all",
    "CallGraph",
    "ChangePoint",
    "ColumnInfo",
    "ColumnResidual",
    "DependencyModel",
    "Edge",
    "PareConfig",
    "RobustBaseline",
    "columns_from_dicts",
    "columns_of_service",
    "ecdf_explainer",
    "ecdf_tail_score",
    "estimate_change_point",
    "group_by_service",
    "mad",
    "name_to_index",
    "pca_reconstruction",
    "robust_baseline",
    "robust_z",
    "services",
    "shap_iforest",
    "validate_columns",
    "window_score",
]
