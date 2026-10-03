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

__all__ = [
    "__version__",
    "ColumnInfo",
    "PareConfig",
    "columns_from_dicts",
    "columns_of_service",
    "group_by_service",
    "name_to_index",
    "services",
    "validate_columns",
]
