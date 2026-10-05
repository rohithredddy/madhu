"""Read RCAEval failure cases into the shapes the engines expect.

This is the only place that knows what an RCAEval folder looks like. Everything
downstream - the experiment runners, the engines, the metrics - sees a `Case` and
a `CaseData` and never a CSV.

It deliberately does **not** import RCAEval. The data is plain CSV on disk, so
reading it needs nothing but pandas, and keeping the dependency out means the
experiments run in the analyzer environment alongside `pare` rather than in the
separate RCAEval one (they cannot share, since RCAEval pins numpy 1.x). Only the
download script and the baseline comparison in M2.4 need RCAEval itself.

What the data actually looks like was established in M2.2 and is recorded in
`PROGRESS.md`. The three findings that shape this file:

* **`time` appears twice** in every CSV, with identical values. pandas renames the
  second to `time.1`. Dropped here, because treating it as a metric would put a
  monotonically rising column into the ranking.
* **Column sets are not uniform** - 15 distinct sets across the 125 Online
  Boutique cases, only 25 columns common to all. Nothing may assume a schema.
* **One case carries five stray Sock Shop columns.** Columns whose service is not
  a known service of the system are dropped and reported, so that a collection
  artefact cannot be ranked as a candidate root cause.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pare.columns import ColumnInfo
from pare.graph import CallGraph

# The services that belong to each system. An explicit list, not whatever the
# file happens to contain: it is what lets a contaminated case be spotted rather
# than silently ranked. Includes the infrastructure components (`main`, `redis`)
# and the Istio telemetry entries, because those are genuinely part of the
# deployment being measured and excluding them would make the task easier than it
# is.
SYSTEM_SERVICES: dict[str, frozenset[str]] = {
    "online-boutique": frozenset(
        {
            "adservice",
            "cartservice",
            "checkoutservice",
            "currencyservice",
            "emailservice",
            "frontend",
            "paymentservice",
            "productcatalogservice",
            "recommendationservice",
            "shippingservice",
            # infrastructure and telemetry, present in the data
            "main",
            "redis",
            "frontend-external",
            "frontend-check",
            "PassthroughCluster",
        }
    ),
}

# Folder name suffix -> the fault type recorded on a Case. Uppercase, as
# docs/06 section 2 requires of every enum-like value.
FAULT_TYPES = {
    "cpu": "CPU",
    "mem": "MEM",
    "disk": "DISK",
    "delay": "DELAY",
    "loss": "LOSS",
}

# Which of a service's metrics counts as the ground-truth indicator.
#
# docs/08 section 3 says to take this from RCAEval's own fine-grained evaluation
# code. It is not in the installed package - the shipped Evaluator compares
# Node(entity, metric) objects, but the code that builds the answer node for a
# case is not in the wheel - so the mapping is ours and is declared here.
#
# CPU and MEM were settled by measurement: across 125 cases the broken service's
# `cpu` column moves most in 25 of 25 CPU cases, and `mem` in 18 of 25 MEM cases.
#
# DISK, DELAY and LOSS have **no matching metric at all** - RE1-OB contains no
# `disk` and no `loss` column - so they get a set of acceptable answers rather
# than one, and `gt_indicator` is left None. Open question 6 in PROGRESS.md
# records the choice still to be made about how to score them; until it is
# settled, an experiment should use `gt_indicator` (strict) or
# `acceptable_indicators` (loose) explicitly rather than guessing.
INDICATOR_METRICS: dict[str, tuple[str, ...]] = {
    "CPU": ("cpu",),
    "MEM": ("mem",),
    # measured: never plain `latency`, it splits between the two percentiles
    "DELAY": ("latency-90", "latency-50", "latency"),
    "LOSS": ("latency-90", "latency-50", "latency"),
    # measured: splits roughly evenly between cpu and the latency percentiles
    "DISK": ("cpu", "latency-90", "latency-50", "latency"),
}

# Fault types whose indicator is a single, unambiguous metric.
UNAMBIGUOUS_FAULTS = frozenset({"CPU", "MEM"})

DATASET_SYSTEM_FOLDER = {
    ("RE1", "online-boutique"): "RE1-OB",
    ("RE1", "sock-shop"): "RE1-SS",
    ("RE1", "train-ticket"): "RE1-TT",
    ("RE2", "online-boutique"): "RE2-OB",
    ("RE3", "online-boutique"): "RE3-OB",
}


@dataclass(frozen=True)
class Case:
    """One recorded failure, before any data is read."""

    case_id: str
    dataset: str
    system: str
    fault_type: str
    gt_service: str
    gt_indicator: str | None
    """The single correct indicator, or None when the fault type has no matching
    metric. Never guess one: use :attr:`acceptable_indicators` instead."""

    acceptable_indicators: tuple[str, ...]
    """Every column that could reasonably be called correct for this fault."""

    path: Path
    inject_time_sec: int
    run: str

    @property
    def indicator_is_unambiguous(self) -> bool:
        return self.gt_indicator is not None


@dataclass(frozen=True)
class CaseData:
    """One failure, loaded and split into the windows an engine takes."""

    case: Case
    normal: pd.DataFrame
    recent: pd.DataFrame
    alarm_time_sec: float
    columns: list[ColumnInfo]
    graph: CallGraph
    warnings: list[str] = field(default_factory=list)

    @property
    def n_columns(self) -> int:
        return len(self.columns)


def list_cases(
    root: Path | str,
    dataset: str = "RE1",
    system: str = "online-boutique",
) -> list[Case]:
    """Find every case of one system, without reading any data.

    Cheap enough to call before deciding what to run, and sorted so a run is
    reproducible.
    """
    folder = DATASET_SYSTEM_FOLDER.get((dataset, system))
    if folder is None:
        raise ValueError(
            f"no folder known for dataset {dataset!r} and system {system!r}; "
            f"known: {sorted(DATASET_SYSTEM_FOLDER)}"
        )

    base = Path(root) / dataset / folder
    if not base.exists():
        raise FileNotFoundError(
            f"{base} does not exist. Download it first:\n"
            f"  experiments/.venv-rcaeval/Scripts/python.exe "
            f"experiments/download_rcaeval.py --dataset {folder}"
        )

    cases: list[Case] = []
    for fault_folder in sorted(p for p in base.iterdir() if p.is_dir()):
        service, _, suffix = fault_folder.name.rpartition("_")
        fault_type = FAULT_TYPES.get(suffix)
        if fault_type is None or not service:
            continue  # not a case folder

        for run_folder in sorted(
            (p for p in fault_folder.iterdir() if p.is_dir()), key=_run_order
        ):
            inject_file = run_folder / "inject_time.txt"
            if not (run_folder / "data.csv").exists() or not inject_file.exists():
                continue

            metrics = INDICATOR_METRICS[fault_type]
            cases.append(
                Case(
                    case_id=f"{dataset.lower()}-{folder.split('-')[-1].lower()}-"
                    f"{fault_folder.name}-{run_folder.name}",
                    dataset=dataset,
                    system=system,
                    fault_type=fault_type,
                    gt_service=service,
                    gt_indicator=(
                        f"{service}_{metrics[0]}"
                        if fault_type in UNAMBIGUOUS_FAULTS
                        else None
                    ),
                    acceptable_indicators=tuple(f"{service}_{m}" for m in metrics),
                    path=run_folder,
                    inject_time_sec=int(inject_file.read_text().strip()),
                    run=run_folder.name,
                )
            )
    return cases


def load_case(
    case: Case,
    delay_s: float = 0.0,
    normal_minutes: float | None = None,
    normal_gap_s: float = 30.0,
    recent_before_s: float = 300.0,
    recent_after_s: float = 120.0,
    graph: CallGraph | None = None,
    normal_mode: str = "inject_gap",
) -> CaseData:
    """Read one case and split it into the normal and recent windows.

    Args:
        case: From :func:`list_cases`.
        delay_s: How late the detector is assumed to be. The alarm is
            ``inject_time + delay_s``; the engines are told only the alarm.
        normal_minutes: Keep at most this many minutes of normal data, measured
            back from its end. ``None`` keeps all of it.
        normal_gap_s: Safety gap between the end of normal and the injection.
        recent_before_s: How much before the alarm goes into ``recent``.
        recent_after_s: How much after. The windows follow the one table in
            ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3, step 2.
        graph: The call graph. None gives an empty one, which is a valid input -
            PARE then has nothing to subtract. M2.5 builds the real one.
        normal_mode: ``"inject_gap"`` ends the normal period at
            ``inject_time - normal_gap_s``, which is the standard RCAEval
            protocol. ``"alarm_lookback"`` ends it at ``alarm - recent_before_s``
            instead and never uses the injection time, which is the honest variant
            experiment E3 reports alongside (`docs/08` section 4).
    """
    frame = pd.read_csv(case.path / "data.csv")
    frame, columns, warnings = _clean(frame, case)

    alarm_time_sec = float(case.inject_time_sec + delay_s)
    times = frame["time"]

    if normal_mode == "inject_gap":
        normal_ends = case.inject_time_sec - normal_gap_s
    elif normal_mode == "alarm_lookback":
        normal_ends = alarm_time_sec - recent_before_s
    else:
        raise ValueError(
            f"normal_mode must be 'inject_gap' or 'alarm_lookback', got {normal_mode!r}"
        )

    normal = frame[times < normal_ends]
    if normal_minutes is not None:
        keep_from = normal_ends - normal_minutes * 60.0
        normal = normal[normal["time"] >= keep_from]

    recent = frame[
        (times >= alarm_time_sec - recent_before_s)
        & (times <= alarm_time_sec + recent_after_s)
    ]

    if normal.empty:
        warnings.append("the normal window is empty")
    if recent.empty:
        warnings.append("the recent window is empty")

    return CaseData(
        case=case,
        normal=normal.reset_index(drop=True),
        recent=recent.reset_index(drop=True),
        alarm_time_sec=alarm_time_sec,
        columns=columns,
        graph=graph if graph is not None else CallGraph.empty(),
        warnings=warnings,
    )


# --- reading one file -------------------------------------------------------


def _clean(
    frame: pd.DataFrame, case: Case
) -> tuple[pd.DataFrame, list[ColumnInfo], list[str]]:
    """Drop what should not be scored, and build the column map.

    Returns the frame with a single `time` column plus its metric columns, the
    explicit column map, and a note of anything removed.
    """
    warnings: list[str] = []
    known = SYSTEM_SERVICES.get(case.system)

    # The duplicate `time` column. pandas has already renamed it to `time.1`.
    duplicates = [c for c in frame.columns if c != "time" and c.split(".")[0] == "time"]
    if duplicates:
        frame = frame.drop(columns=duplicates)

    if "time" not in frame.columns:
        raise ValueError(f"{case.path / 'data.csv'} has no time column")

    columns: list[ColumnInfo] = []
    foreign: list[str] = []
    for name in frame.columns:
        if name == "time":
            continue
        service, _, metric = name.rpartition("_")
        if not service or not metric:
            foreign.append(name)
            continue
        if known is not None and service not in known:
            foreign.append(name)
            continue
        columns.append(ColumnInfo(name=name, service=service, metric=metric))

    if foreign:
        frame = frame.drop(columns=foreign)
        warnings.append(
            f"dropped {len(foreign)} column(s) not belonging to {case.system}: "
            f"{', '.join(sorted(foreign))}"
        )

    return frame, columns, warnings


def _run_order(path: Path) -> tuple[int, str]:
    """Sort run folders numerically where they are numbers, so 10 follows 9."""
    return (int(path.name), "") if path.name.isdigit() else (1 << 30, path.name)


# --- small helpers the runners will want ------------------------------------


def values_of(data: CaseData, window: str = "normal"):
    """The metric columns of one window as a plain array, in `columns` order."""
    frame = data.normal if window == "normal" else data.recent
    return frame[[column.name for column in data.columns]].to_numpy(dtype=float)


def times_of(data: CaseData, window: str = "normal"):
    frame = data.normal if window == "normal" else data.recent
    return frame["time"].to_numpy(dtype=float)


def summarise(cases: Sequence[Case]) -> dict[str, object]:
    """Counts worth printing before a long run, so a mistake in the filter is
    noticed before an hour is spent on it."""
    from collections import Counter

    return {
        "cases": len(cases),
        "by_fault": dict(Counter(c.fault_type for c in cases)),
        "by_service": dict(Counter(c.gt_service for c in cases)),
        "unambiguous_indicator": sum(1 for c in cases if c.indicator_is_unambiguous),
    }
