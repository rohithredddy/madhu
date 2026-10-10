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

import re
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
    # The 14 Deployments of experiments/graphs/sock-shop.yaml, plus the RabbitMQ
    # metrics exporter, which RE1-SS measures as a service of its own. Found in the
    # M3.2 inspection (PROGRESS.md). `istio-init` is deliberately absent: it is an
    # init container that exits before the run, appears in 1 of 125 cases with a
    # single memory column, and is a collection artefact rather than a candidate.
    "sock-shop": frozenset(
        {
            "carts",
            "carts-db",
            "catalogue",
            "catalogue-db",
            "front-end",
            "orders",
            "orders-db",
            "payment",
            "queue-master",
            "rabbitmq",
            "rabbitmq-exporter",
            "session-db",
            "shipping",
            "user",
            "user-db",
        }
    ),
    # Every service RE1-TT names, all 64 of them, read off all 125 cases in M3.2.
    # Each is a `ts-*` Deployment of Train Ticket (services and their MongoDB /
    # MySQL stores); unlike the other two systems no stray or telemetry entries
    # appear, so the list is exactly what the data contains. Kept explicit anyway,
    # so that a future release carrying a contaminated case is caught, not ranked.
    "train-ticket": frozenset(
        {
            "ts-admin-basic-info-service",
            "ts-admin-order-service",
            "ts-admin-route-service",
            "ts-admin-travel-service",
            "ts-admin-user-service",
            "ts-assurance-mongo",
            "ts-assurance-service",
            "ts-auth-mongo",
            "ts-auth-service",
            "ts-avatar-service",
            "ts-basic-service",
            "ts-cancel-service",
            "ts-config-mongo",
            "ts-config-service",
            "ts-consign-mongo",
            "ts-consign-price-mongo",
            "ts-consign-price-service",
            "ts-consign-service",
            "ts-contacts-mongo",
            "ts-contacts-service",
            "ts-execute-service",
            "ts-food-map-mongo",
            "ts-food-map-service",
            "ts-food-mongo",
            "ts-food-service",
            "ts-inside-payment-mongo",
            "ts-inside-payment-service",
            "ts-news-service",
            "ts-notification-service",
            "ts-order-mongo",
            "ts-order-other-mongo",
            "ts-order-other-service",
            "ts-order-service",
            "ts-payment-mongo",
            "ts-payment-service",
            "ts-preserve-other-service",
            "ts-preserve-service",
            "ts-price-mongo",
            "ts-price-service",
            "ts-rebook-service",
            "ts-route-mongo",
            "ts-route-plan-service",
            "ts-route-service",
            "ts-seat-service",
            "ts-security-mongo",
            "ts-security-service",
            "ts-station-mongo",
            "ts-station-service",
            "ts-ticket-office-mongo",
            "ts-ticket-office-service",
            "ts-ticketinfo-service",
            "ts-train-mongo",
            "ts-train-service",
            "ts-travel-mongo",
            "ts-travel-plan-service",
            "ts-travel-service",
            "ts-travel2-mongo",
            "ts-travel2-service",
            "ts-ui-dashboard",
            "ts-user-mongo",
            "ts-user-service",
            "ts-verification-code-service",
            "ts-voucher-mysql",
            "ts-voucher-service",
        }
    ),
}

# Where one dataset's deployment differs from its system's list above. RE3-TT
# carries four Train Ticket datastores that RE1-TT does not, in all 30 of its
# cases (M5.3). `istio-init` appears in 7 of them and stays out, as on RE1.
DATASET_SERVICES: dict[tuple[str, str], frozenset[str]] = {
    ("RE3", "train-ticket"): SYSTEM_SERVICES["train-ticket"]
    | {"ts-food-mysql", "ts-notification-mongo", "ts-preserve-mongo", "ts-preserve-other-mongo"},
}


def system_services(dataset: str, system: str) -> frozenset[str] | None:
    """The services one dataset's data of one system may contain."""
    return DATASET_SERVICES.get((dataset, system), SYSTEM_SERVICES.get(system))


# Which file in a run folder holds the metrics, per system.
#
# RE1-OB ships one file, `data.csv`. RE1-SS ships two: `data.csv` holds about 436
# raw Prometheus series (cumulative `*-total` counters, node-exporter series keyed
# by IP address), and `simple_data.csv` holds 57 to 63 derived per-service series
# in the same vocabulary as RE1-OB (`cpu`, `mem`, `workload`, `error`,
# `latency-50`, `latency-90`). RCAEval's own README gives RE1-SS as "57-63
# metrics", which is `simple_data.csv` and not `data.csv`, so the benchmark as
# published is defined on that file and so are we. Measured in M3.2.
METRICS_FILE: dict[str, str] = {
    "online-boutique": "data.csv",
    "sock-shop": "simple_data.csv",
    # The same two-file layout, and the README's "198-238 metrics" for RE1-TT is
    # simple_data.csv again (198 to 238 columns besides `time`, measured in M3.2).
    "train-ticket": "simple_data.csv",
}

# Where one dataset differs from its system's entry above. RE2-OB ships
# `metrics.csv` (418 raw series) and `simple_metrics.csv` (70 to 78 derived
# per-service series, measured over all 90 cases in M5.1). The simple file uses
# the RE1 vocabulary (`cpu`, `mem`, `workload`, `error`, `latency-50`,
# `latency-90`) plus `socket` and `diskio`, so it is the one comparable with RE1
# and the one used here, as RE1-SS's `simple_data.csv` is (decision 85).
DATASET_METRICS_FILE: dict[tuple[str, str], str] = {
    ("RE2", "online-boutique"): "simple_metrics.csv",
    # The same layout in RE3-TT: simple_metrics.csv has 294 to 322 columns in the
    # RE1 vocabulary plus socket and diskio (M5.3).
    ("RE3", "train-ticket"): "simple_metrics.csv",
}


def metrics_file(dataset: str, system: str) -> str:
    """The file in a run folder that holds one dataset's metrics for one system."""
    return DATASET_METRICS_FILE.get((dataset, system), METRICS_FILE.get(system, "data.csv"))


# The metric names each system's data actually uses, read off every case in the
# M2.2 (Online Boutique) and M3.2 (Sock Shop, Train Ticket) inspections. Used only to say how
# many metrics are acceptable for a fault type *on this system*: Sock Shop has no
# plain `latency`, so a DELAY case there has two acceptable latency metrics where
# Online Boutique has three, and the loose score must be read against the right
# number.
SYSTEM_METRICS: dict[str, frozenset[str]] = {
    "online-boutique": frozenset(
        {"cpu", "mem", "load", "latency", "latency-50", "latency-90", "workload", "error"}
    ),
    "sock-shop": frozenset({"cpu", "mem", "workload", "error", "latency-50", "latency-90"}),
    "train-ticket": frozenset(
        {"cpu", "mem", "workload", "error", "latency-50", "latency-90"}
    ),
}

# Where one dataset's metric names differ from its system's entry above. RE2-OB
# has no `load` and no plain `latency`, and adds `socket` and `diskio` (M5.1).
DATASET_METRICS: dict[tuple[str, str], frozenset[str]] = {
    ("RE2", "online-boutique"): frozenset(
        {"cpu", "mem", "diskio", "socket", "workload", "error", "latency-50", "latency-90"}
    ),
    ("RE3", "train-ticket"): frozenset(
        {"cpu", "mem", "diskio", "socket", "workload", "error", "latency-50", "latency-90"}
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
    # RE2 only. Measured in M5.1: the broken service's `socket` column moves
    # (median robust z far above 3) in 15 of 15 SOCKET cases.
    "socket": "SOCKET",
    # RE3 only: code-level faults, kept under the dataset's own names (decision 5).
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
}

# RE3 folds a second batch of one fault into a folder with a numeric suffix:
# `ts-route-service_f3_1` holds more F3 runs of ts-route-service (M5.3).
_SECOND_BATCH = re.compile(r"^(?P<service>.+)_(?P<fault>[a-z0-9]+)_\d+$")


def parse_fault_folder(name: str) -> tuple[str, str] | None:
    """(service, fault type) from a fault folder's name, or None if it is not one."""
    service, _, suffix = name.rpartition("_")
    if service and suffix in FAULT_TYPES:
        return service, FAULT_TYPES[suffix]
    batch = _SECOND_BATCH.match(name)
    if batch and batch.group("fault") in FAULT_TYPES:
        return batch.group("service"), FAULT_TYPES[batch.group("fault")]
    return None

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
# than one, and `gt_indicator` is left None. How each is scored is settled in
# docs/08 section 4 (decision 64): `gt_indicator` is the strict headline,
# `acceptable_indicators` the loose secondary score.
INDICATOR_METRICS: dict[str, tuple[str, ...]] = {
    "CPU": ("cpu",),
    "MEM": ("mem",),
    # RE2 only, and like CPU and MEM a fault with a metric of its own (M5.1).
    "SOCKET": ("socket",),
    # RE3's code-level faults have no metric of their own. A defect in code is
    # expected to show in the requests it serves, so the loose set is the error
    # and latency columns. Fixed before any method was run on RE3. Measured in
    # M5.3, and stated as a limitation rather than used to redefine the set: in
    # RE3-TT the faulty service's `mem` (26 of 30 cases) or `cpu` moves most, by a
    # median robust z of about 60, while error and latency barely move - which
    # looks like the pod being redeployed with the faulty build, not the defect.
    **{f"F{n}": ("error", "latency-90", "latency-50", "latency") for n in range(1, 5)},
    # measured: never plain `latency`, it splits between the two percentiles
    "DELAY": ("latency-90", "latency-50", "latency"),
    "LOSS": ("latency-90", "latency-50", "latency"),
    # measured: splits roughly evenly between cpu and the latency percentiles.
    # Fixed on that RE1-OB evidence and deliberately not redefined after seeing the
    # other systems, although they disagree: on RE1-SS `cpu` moves most in 17 of
    # 25 DISK cases, but on RE1-TT `mem` does in 23 of 25, and `mem` is not in this
    # set. Open question 10 in PROGRESS.md. Affects only the loose (secondary)
    # score; DISK has no strict one.
    # `diskio` added in M5.1 for RE2, the first data to carry a disk metric (it
    # moves in all 15 RE2-OB DISK cases). No RE1 system has it, so on RE1
    # acceptable_metrics() drops it and nothing there changes. DISK stays loose
    # only, so the headline strict score is defined the same way on every dataset.
    "DISK": ("cpu", "latency-90", "latency-50", "latency", "diskio"),
}

# Fault types whose indicator is a single, unambiguous metric.
#
# On Sock Shop and Train Ticket the injected metric is often *not* the loudest of
# the broken service's own metrics - on Sock Shop `cpu` is in 6 of 25 CPU cases and
# `mem` in 4 of 25 MEM cases, latency outshouting both; on Train Ticket `cpu` is in
# 9 of 25 CPU cases, `mem` moving more - but it moves unmistakably in every one of
# them (median robust z: Sock Shop 408 for `cpu` and 2610 for `mem`, Train Ticket
# 149 and about 10,000; all 100 cases above 3). The fault label says which
# resource was stressed, so the answer is still not a judgement call; the
# measurement says only that naming it is harder there. M3.2.
UNAMBIGUOUS_FAULTS = frozenset({"CPU", "MEM", "SOCKET"})


def acceptable_metrics(
    system: str, fault_type: str, dataset: str = "RE1"
) -> tuple[str, ...]:
    """The metrics that count as a correct indicator for one fault on one system.

    `INDICATOR_METRICS` restricted to the metrics the dataset's data contains, so a
    loose score is never read against a set padded with columns that cannot exist.
    """
    present = DATASET_METRICS.get((dataset, system), SYSTEM_METRICS.get(system))
    metrics = INDICATOR_METRICS[fault_type]
    return metrics if present is None else tuple(m for m in metrics if m in present)

DATASET_SYSTEM_FOLDER = {
    ("RE1", "online-boutique"): "RE1-OB",
    ("RE1", "sock-shop"): "RE1-SS",
    ("RE1", "train-ticket"): "RE1-TT",
    ("RE2", "online-boutique"): "RE2-OB",
    ("RE3", "online-boutique"): "RE3-OB",
    ("RE3", "train-ticket"): "RE3-TT",
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

    file_name = metrics_file(dataset, system)
    cases: list[Case] = []
    for fault_folder in sorted(p for p in base.iterdir() if p.is_dir()):
        parsed = parse_fault_folder(fault_folder.name)
        if parsed is None:
            continue  # not a case folder
        service, fault_type = parsed

        for run_folder in sorted(
            (p for p in fault_folder.iterdir() if p.is_dir()), key=_run_order
        ):
            inject_file = run_folder / "inject_time.txt"
            if not (run_folder / file_name).exists() or not inject_file.exists():
                continue

            metrics = acceptable_metrics(system, fault_type, dataset)
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
    frame, columns, warnings = read_case_frame(case)

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


def read_case_frame(case: Case) -> tuple[pd.DataFrame, list[ColumnInfo], list[str]]:
    """The whole cleaned series of one case, before any window is cut.

    One `time` column plus the metric columns that belong to the system, the
    explicit column map, and a note of anything removed. `load_case` cuts its
    windows from this, and `export_cases.py` writes it to disk for the
    application, so both see exactly the same columns.
    """
    frame = pd.read_csv(case.path / metrics_file(case.dataset, case.system))
    return _clean(frame, case)



def _clean(
    frame: pd.DataFrame, case: Case
) -> tuple[pd.DataFrame, list[ColumnInfo], list[str]]:
    """Drop what should not be scored, and build the column map.

    Returns the frame with a single `time` column plus its metric columns, the
    explicit column map, and a note of anything removed.
    """
    warnings: list[str] = []
    known = system_services(case.dataset, case.system)

    # The duplicate `time` column. pandas has already renamed it to `time.1`.
    duplicates = [c for c in frame.columns if c != "time" and c.split(".")[0] == "time"]
    if duplicates:
        frame = frame.drop(columns=duplicates)

    if "time" not in frame.columns:
        raise ValueError(f"{case.path} has no time column")

    # Rows with no timestamp. Two RE1-SS cases end with a block of them
    # (`catalogue_disk/3` 74 rows, `user_mem/1` 114 rows, M3.2) whose metric values
    # are present but cannot be placed in time. Both blocks start well over 120 s
    # after the injection, so no window at delay 0 reaches them. A row that belongs
    # to no moment cannot be put in either window, so it is removed here, openly,
    # rather than left to fall out of the window comparisons.
    no_time = frame["time"].isna()
    if no_time.any():
        frame = frame[~no_time].reset_index(drop=True)
        warnings.append(f"dropped {int(no_time.sum())} row(s) with no time value")

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
