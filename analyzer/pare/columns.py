"""ColumnInfo: what one column of the data actually means.

A column such as ``cartservice_mem`` is one metric of one service. The important
rule, from ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 2, is that the method never
works this out by splitting the column name:

    Never parse column names inside the algorithm; the adapter or the Java side
    gives this map.

The reason is that real benchmark column names are irregular, and a service
called ``front_end`` with a metric called ``cpu_usage`` cannot be split reliably.
A wrong split would quietly put a metric under the wrong service, which would
corrupt the dependency model and the ranking without raising anything. So the
mapping is always supplied, and this module only stores and looks it up.

There is deliberately no ``guess_from_name`` helper here. Guessing belongs to the
experiment adapters (M2.3) and to the Java upload helper, which both let a human
check the result before it is used.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnInfo:
    """One column: its name in the data, and the service and metric it belongs to.

    Matches the JSON object in ``docs/06_DATA_CONTRACTS.md`` section 1:
    ``{"name": "cartservice_mem", "service": "cartservice", "metric": "mem"}``.
    """

    name: str
    service: str
    metric: str

    def __post_init__(self) -> None:
        for field_name in ("name", "service", "metric"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"ColumnInfo.{field_name} must be a non-empty string, got {value!r}"
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ColumnInfo:
        """Build one ColumnInfo from its JSON form."""
        missing = {"name", "service", "metric"} - set(data)
        if missing:
            raise ValueError(f"column is missing {sorted(missing)}: {dict(data)!r}")
        return cls(name=data["name"], service=data["service"], metric=data["metric"])

    def to_dict(self) -> dict[str, str]:
        """The JSON form, for the service layer and for saving alongside results."""
        return {"name": self.name, "service": self.service, "metric": self.metric}


def columns_from_dicts(items: Iterable[Mapping[str, Any]]) -> list[ColumnInfo]:
    """Build a validated column list from the JSON form of an AnalyzeRequest."""
    columns = [ColumnInfo.from_dict(item) for item in items]
    validate_columns(columns)
    return columns


def validate_columns(columns: Iterable[ColumnInfo]) -> None:
    """Check a column list is usable, or raise ValueError saying why.

    Duplicate names are the dangerous case: the engines address data by column
    name, so two columns called the same thing would make one of them silently
    unreachable.
    """
    columns = list(columns)
    if not columns:
        raise ValueError("column list is empty")

    seen: set[str] = set()
    duplicates: list[str] = []
    for column in columns:
        if column.name in seen:
            duplicates.append(column.name)
        seen.add(column.name)
    if duplicates:
        raise ValueError(f"duplicate column names: {sorted(set(duplicates))}")


def services(columns: Iterable[ColumnInfo]) -> list[str]:
    """The distinct service names, in the order they first appear.

    Order is kept rather than sorted so that results are stable and reproducible
    for a given input, and so the first service in a case stays first in output
    that a human reads.
    """
    return list(OrderedDict.fromkeys(column.service for column in columns))


def group_by_service(columns: Iterable[ColumnInfo]) -> dict[str, list[ColumnInfo]]:
    """Columns grouped by their service, service order preserved.

    This is the shape step 3 and step 4 want: the dependency model fits one model
    per column of a service, and the service score aggregates over them.
    """
    grouped: dict[str, list[ColumnInfo]] = OrderedDict()
    for column in columns:
        grouped.setdefault(column.service, []).append(column)
    return grouped


def columns_of_service(columns: Iterable[ColumnInfo], service: str) -> list[ColumnInfo]:
    """The columns belonging to one service. Empty list if the service has none."""
    return [column for column in columns if column.service == service]


def name_to_index(columns: Iterable[ColumnInfo]) -> dict[str, int]:
    """Map each column name to its position.

    The engines receive values as a row-major array whose column order matches the
    column list, so turning a name into a position is needed almost everywhere.
    """
    return {column.name: index for index, column in enumerate(columns)}
