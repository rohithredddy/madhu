"""Synthetic microservice data with a known root cause.

This is the ground on which everything else is tested. Because we build the data,
we know exactly which service is to blame and exactly how strongly a fault
spreads to its callers - which is the one thing real benchmark data cannot tell
us. Experiment E6 uses it to answer "when does PARE help, and when does it stop
helping", by turning one factor at a time.

The model, from ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 5:

* The call graph is a random tree with ``frontend`` at the top. An edge means
  caller -> callee.
* Every service has five metrics: ``latency``, ``error``, ``cpu``, ``mem``, ``rps``.
* ``latency`` and ``error`` flow **upward**: a service's value is its own baseline
  plus a weighted sum of the values of the services it calls. That weight is the
  ``propagation`` knob, and it is why a caller can look broken when it is fine.
* ``cpu`` follows the shared load, ``mem`` is a local random walk, and ``rps`` is
  the shared load scaled per service. None of those three propagate.
* A fault is injected into one service from the first abnormal row. Callers
  inherit it through the latency and error equations, with no extra code.

The faulted service's own latency term is added before propagation, so a cpu or
memory fault also makes its callers slow. See the spec for why a memory fault has
to work that way.

One more mechanism, controlled by ``amplification``, is what makes the symptom
trap possible at all. With purely linear propagation a caller can never look
*worse* than the service that broke: raising the propagation weight scales the
inherited signal and the inherited noise by the same factor, so they cancel, and
the caller's score stays below the culprit's for any weight. Real systems do not
behave that way - queueing, retries and timeouts make a caller degrade out of all
proportion once a callee passes a threshold, while leaving it calm below that
threshold. That asymmetry is exactly what inflates the caller's deviation without
inflating its normal spread. ``amplification=0`` keeps the old purely linear
model, so it is still available as a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pare.columns import ColumnInfo

# The five metrics every service has, in a fixed order so column order is stable.
METRICS = ("latency", "error", "cpu", "mem", "rps")

# The faults we can inject. Lowercase inside the library; the service layer
# uppercases them for the API (docs/06 section 2).
FAULTS = ("latency", "cpu", "mem", "error")

# An arbitrary but fixed epoch start, so a seed reproduces the same timestamps.
# 2024-01-01 00:00:00 UTC.
DEFAULT_START_TIME_SEC = 1_704_067_200

# One row per second. The E6 delay sweep is specified in rows, so rows and
# seconds being the same thing keeps that simple.
STEP_SEC = 1

# How slow a callee has to get, in units of its own normal spread, before its
# caller starts to suffer disproportionately. Below this the congestion term is
# exactly zero, which is the point: normal operation must stay untouched, or the
# caller's normal spread would widen and the effect would cancel itself out.
CONGESTION_ONSET_Z = 3.0

# Guards against dividing by a zero standard deviation on a column that happened
# to come out flat.
_TINY = 1e-12


@dataclass(frozen=True)
class SyntheticCase:
    """One generated failure, with the answer kept separate from the data.

    ``gt_service`` and ``gt_column`` are the ground truth. They live here and
    never appear as a column in ``normal`` or ``abnormal``, so an engine cannot
    see them even by accident (hard rule 4 in ``PROJECT_RULES.md``).
    """

    normal: pd.DataFrame
    """Rows before the fault. Time-indexed, epoch seconds."""

    abnormal: pd.DataFrame
    """Rows from the fault onward. Same columns as ``normal``."""

    columns: list[ColumnInfo]
    """The explicit column map. Same order as the DataFrame columns."""

    edges: list[tuple[str, str]]
    """Call graph as (caller, callee) pairs. ``CallGraph.from_edges`` takes this."""

    gt_service: str
    """The service the fault was injected into."""

    gt_column: str
    """The specific column that shows the fault, e.g. ``svc-03_mem``."""

    inject_time_sec: int
    """Time of the first abnormal row. An alarm time is this plus a delay."""

    fault: str
    """Which fault was injected: one of :data:`FAULTS`."""

    params: dict[str, object] = field(default_factory=dict)
    """The arguments this case was built from, so a result can be traced back."""

    def to_frame(self) -> pd.DataFrame:
        """The whole case as one continuous time series.

        This is the shape the case format on disk and ``/v1/synthetic`` need; the
        split into normal and abnormal is a convenience for tests.
        """
        return pd.concat([self.normal, self.abnormal])

    @property
    def services(self) -> list[str]:
        """Service names, ``frontend`` first."""
        seen: dict[str, None] = {}
        for column in self.columns:
            seen.setdefault(column.service, None)
        return list(seen)


def make_case(
    n_services: int = 8,
    n_normal: int = 600,
    n_abnormal: int = 120,
    fault: str = "latency",
    root: str | None = None,
    propagation: float = 0.8,
    noise: float = 1.0,
    amplification: float = 0.0,
    seed: int = 0,
    start_time_sec: int = DEFAULT_START_TIME_SEC,
) -> SyntheticCase:
    """Generate one failure case with a known root cause.

    Args:
        n_services: How many services, including ``frontend``. E6 uses 5 to 40.
        n_normal: Rows before the fault.
        n_abnormal: Rows from the fault onward.
        fault: Which fault to inject, one of :data:`FAULTS`.
        root: Which service to break. ``None`` picks a random non-frontend
            service. Passing ``"frontend"`` is allowed and gives a case with no
            propagation at all, which is a useful edge case to be able to make.
        propagation: How strongly a callee's latency and errors show up in its
            caller. 0 means a fault stays put; 1 means a caller feels it fully.
        noise: Multiplier on every noise standard deviation. The API's
            LOW/MEDIUM/HIGH map to 0.5/1.0/2.0.
        amplification: How much a caller degrades out of proportion once a callee
            passes :data:`CONGESTION_ONSET_Z`. 0 means purely linear propagation,
            where a caller can never outscore the service that broke. Raising it
            lets the caller look worse than the culprit, which is the mistake the
            whole project is about. Around 1.0 the caller is loud enough to fool a
            method that only looks at how far each service moved, while a method
            that subtracts what the callees explain still gets it right; much
            higher and nothing can tell them apart from metrics alone.
        seed: Random seed. The same seed reproduces the case bit for bit.
        start_time_sec: Epoch second of the first row.

    Returns:
        A :class:`SyntheticCase`.
    """
    _validate(n_services, n_normal, n_abnormal, fault, propagation, noise, amplification)

    rng = np.random.default_rng(seed)
    n_rows = n_normal + n_abnormal

    names = _service_names(n_services)
    parents, children = _random_tree(n_services, rng)

    # Everything random is drawn here, once, before either pass. The two passes
    # then differ only in whether the fault is applied, which is what makes a
    # seed reproducible.
    draws = _draw(n_services, n_rows, noise, rng)

    # Propagation weights, one per edge. Drawn here for the same reason.
    latency_weights = {
        i: propagation * rng.uniform(0.8, 1.2, size=len(children[i])) for i in range(n_services)
    }
    error_weights = {
        i: propagation * rng.uniform(0.8, 1.2, size=len(children[i])) for i in range(n_services)
    }

    culprit = _pick_culprit(names, root, rng)
    culprit_index = names.index(culprit)

    # Pass 1: no fault and no congestion, only to measure how each column behaves
    # normally. Both the fault sizes and the congestion threshold are expressed
    # relative to these numbers.
    unfaulted = _build_series(
        n_services, n_rows, children, draws, latency_weights, error_weights, fault_terms=None
    )
    normal_std = {
        name: max(float(np.std(values[:n_normal])), _TINY) for name, values in unfaulted.items()
    }
    normal_median = {
        name: float(np.median(values[:n_normal])) for name, values in unfaulted.items()
    }

    # Pass 2: the same draws, now with the fault injected.
    fault_terms = _fault_terms(
        fault=fault,
        culprit=culprit,
        culprit_index=culprit_index,
        n_normal=n_normal,
        n_abnormal=n_abnormal,
        normal_std=normal_std,
    )
    congestion = None
    if amplification > 0:
        congestion = _Congestion(
            amplification=amplification,
            latency_median=np.array(
                [normal_median[f"{name}_latency"] for name in names], dtype=np.float64
            ),
            latency_std=np.array(
                [normal_std[f"{name}_latency"] for name in names], dtype=np.float64
            ),
            own_scale=np.array(
                [float(np.std(draws["latency_noise"][i])) for i in range(n_services)],
                dtype=np.float64,
            ),
        )

    faulted = _build_series(
        n_services, n_rows, children, draws, latency_weights, error_weights, fault_terms,
        congestion=congestion,
    )

    columns = [
        ColumnInfo(name=f"{service}_{metric}", service=service, metric=metric)
        for service in names
        for metric in METRICS
    ]
    times = start_time_sec + np.arange(n_rows, dtype=np.int64) * STEP_SEC
    frame = pd.DataFrame(
        {column.name: faulted[column.name] for column in columns},
        index=pd.Index(times, name="time"),
    )

    edges = [(names[parents[i]], names[i]) for i in range(1, n_services)]

    return SyntheticCase(
        normal=frame.iloc[:n_normal].copy(),
        abnormal=frame.iloc[n_normal:].copy(),
        columns=columns,
        edges=edges,
        gt_service=culprit,
        gt_column=f"{culprit}_{_fault_metric(fault)}",
        inject_time_sec=int(times[n_normal]),
        fault=fault,
        params={
            "n_services": n_services,
            "n_normal": n_normal,
            "n_abnormal": n_abnormal,
            "fault": fault,
            "root": culprit,
            "propagation": propagation,
            "noise": noise,
            "amplification": amplification,
            "seed": seed,
            "start_time_sec": start_time_sec,
        },
    )


# --- the pieces -------------------------------------------------------------


def _validate(
    n_services: int,
    n_normal: int,
    n_abnormal: int,
    fault: str,
    propagation: float,
    noise: float,
    amplification: float,
) -> None:
    """Reject arguments that cannot produce a usable case."""
    if fault not in FAULTS:
        raise ValueError(f"fault must be one of {FAULTS}, got {fault!r}")
    if n_services < 2:
        raise ValueError(f"n_services must be at least 2, got {n_services}")
    if n_normal < 2:
        raise ValueError(f"n_normal must be at least 2, got {n_normal}")
    if n_abnormal < 1:
        raise ValueError(f"n_abnormal must be at least 1, got {n_abnormal}")
    if propagation < 0:
        raise ValueError(f"propagation must be 0 or more, got {propagation}")
    if amplification < 0:
        raise ValueError(f"amplification must be 0 or more, got {amplification}")
    if noise <= 0:
        # A zero noise level would give every column a zero standard deviation,
        # and the fault sizes are all multiples of that standard deviation.
        raise ValueError(f"noise must be greater than 0, got {noise}")


def _service_names(n_services: int) -> list[str]:
    """``frontend`` plus ``svc-01``, ``svc-02``, ... in order."""
    return ["frontend"] + [f"svc-{i:02d}" for i in range(1, n_services)]


def _random_tree(
    n_services: int, rng: np.random.Generator
) -> tuple[list[int], dict[int, list[int]]]:
    """A random tree rooted at service 0 (``frontend``).

    Service ``i`` picks its caller uniformly from ``0..i-1``. Because a parent's
    index is always smaller than its child's, walking the indices backwards
    visits every callee before its caller - which is exactly the order the
    latency and error equations need.
    """
    parents = [0] * n_services
    children: dict[int, list[int]] = {i: [] for i in range(n_services)}
    for i in range(1, n_services):
        parent = int(rng.integers(0, i))
        parents[i] = parent
        children[parent].append(i)
    return parents, children


def _draw(
    n_services: int, n_rows: int, noise: float, rng: np.random.Generator
) -> dict[str, object]:
    """Draw every random array once, up front.

    Both passes reuse these, so the only difference between the unfaulted and
    faulted runs is the fault itself.
    """
    # A slow sine plus noise: the load the whole system shares.
    t = np.arange(n_rows)
    load = 1.0 + 0.30 * np.sin(2.0 * np.pi * t / 300.0) + rng.normal(0.0, 0.05 * noise, n_rows)

    return {
        "load": load,
        # rps: the shared load, scaled per service
        "rps_scale": rng.uniform(50.0, 200.0, n_services),
        "rps_noise": rng.normal(0.0, 2.0 * noise, (n_services, n_rows)),
        # cpu: a_s * rps + noise
        "cpu_coef": rng.uniform(0.10, 0.40, n_services),
        "cpu_noise": rng.normal(0.0, 1.5 * noise, (n_services, n_rows)),
        # mem: a random walk pulled gently back to its own level
        "mem_level": rng.uniform(200.0, 800.0, n_services),
        "mem_steps": rng.normal(0.0, 1.5 * noise, (n_services, n_rows)),
        # latency: own baseline plus what its callees contribute
        "latency_base": rng.uniform(20.0, 60.0, n_services),
        "latency_noise": rng.normal(0.0, 3.0 * noise, (n_services, n_rows)),
        # error rate: same shape, much smaller numbers
        "error_base": rng.uniform(0.001, 0.010, n_services),
        "error_noise": rng.normal(0.0, 0.002 * noise, (n_services, n_rows)),
    }


def _pick_culprit(names: list[str], root: str | None, rng: np.random.Generator) -> str:
    """Decide which service breaks."""
    if root is None:
        # Prefer a service that has a caller, so there is something to propagate
        # to. With only one service there is no choice.
        candidates = names[1:] or names
        return str(candidates[int(rng.integers(0, len(candidates)))])
    if root not in names:
        raise ValueError(f"root {root!r} is not one of the services: {names}")
    return root


def _fault_metric(fault: str) -> str:
    """Which metric a fault shows up in.

    Matches the RCAEval indicator convention in ``docs/08`` section 3: CPU to the
    cpu metric, MEM to the memory metric, and so on.
    """
    return fault


def _fault_terms(
    fault: str,
    culprit: str,
    culprit_index: int,
    n_normal: int,
    n_abnormal: int,
    normal_std: dict[str, float],
) -> dict[str, np.ndarray]:
    """Build the extra signal the fault adds, per column, over all rows.

    Everything is a multiple of that column's normal standard deviation, so the
    fault is equally visible whatever the noise level.

    Returns a mapping from column name to an array that is zero on the normal
    rows. Latency terms are returned under the key ``own_latency`` so they can be
    added before propagation, letting callers inherit them.
    """
    step = np.concatenate([np.zeros(n_normal), np.ones(n_abnormal)])
    # A ramp reaching full size at the last abnormal row. The early rows are only
    # slightly off, which is what makes a late detector a realistic problem.
    ramp = np.concatenate([np.zeros(n_normal), np.linspace(0.0, 1.0, n_abnormal)])

    terms: dict[str, np.ndarray] = {}

    def add(key: str, shape: np.ndarray, size_in_stds: float, std_of: str) -> None:
        """Add ``size_in_stds`` times the normal spread of ``std_of`` to ``key``."""
        contribution = shape * size_in_stds * normal_std[std_of]
        existing = terms.get(key)
        terms[key] = contribution if existing is None else existing + contribution

    # The culprit's own latency contribution, added before propagation so that
    # callers inherit it. Keyed by service index, which is what the builder looks
    # for, and always scaled by the culprit's own latency spread.
    own_latency_key = f"own_latency::{culprit_index}"
    culprit_latency = f"{culprit}_latency"

    if fault == "latency":
        add(own_latency_key, step, 6.0, culprit_latency)
    elif fault == "cpu":
        add(f"{culprit}_cpu", step, 6.0, f"{culprit}_cpu")
        # Also slows the service down, so its callers feel it.
        add(own_latency_key, step, 2.0, culprit_latency)
    elif fault == "mem":
        add(f"{culprit}_mem", ramp, 8.0, f"{culprit}_mem")
        # A service short of memory gets slower, which is how a memory fault
        # reaches its callers at all. See the spec for why this matters.
        add(own_latency_key, ramp, 2.0, culprit_latency)
    elif fault == "error":
        add(f"{culprit}_error", step, 6.0, f"{culprit}_error")
    else:  # pragma: no cover - _validate has already rejected this
        raise ValueError(f"unknown fault {fault!r}")

    return terms


@dataclass(frozen=True)
class _Congestion:
    """The non-linear part of propagation: queueing, retries and timeouts.

    A caller waits on its callees. While they respond normally it is unaffected,
    but once one of them is badly slow the caller's own threads and connections
    stay held, work queues up, and its response time rises far faster than the
    delay it is waiting on. That is why a caller can end up looking worse than the
    service that actually broke.

    Modelled as ``amplification * own_scale * max(0, z_k - onset) ** 2`` summed
    over the callees, where ``z_k`` is how slow callee k is in units of its own
    normal spread. Squared rather than linear so the effect is negligible just
    past the threshold and severe well beyond it; zero below the threshold so that
    normal operation, and therefore the caller's normal spread, is untouched.
    """

    amplification: float
    latency_median: np.ndarray
    latency_std: np.ndarray
    own_scale: np.ndarray


def _build_series(
    n_services: int,
    n_rows: int,
    children: dict[int, list[int]],
    draws: dict[str, object],
    latency_weights: dict[int, np.ndarray],
    error_weights: dict[int, np.ndarray],
    fault_terms: dict[str, np.ndarray] | None,
    congestion: _Congestion | None = None,
) -> dict[str, np.ndarray]:
    """Compute every column, callees before callers.

    Called twice: once without a fault to measure normal spread, once with it.
    """
    terms = fault_terms or {}
    names = _service_names(n_services)

    load = draws["load"]
    rps_scale = draws["rps_scale"]
    rps_noise = draws["rps_noise"]
    cpu_coef = draws["cpu_coef"]
    cpu_noise = draws["cpu_noise"]
    mem_level = draws["mem_level"]
    mem_steps = draws["mem_steps"]
    latency_base = draws["latency_base"]
    latency_noise = draws["latency_noise"]
    error_base = draws["error_base"]
    error_noise = draws["error_noise"]

    zero = np.zeros(n_rows)
    out: dict[str, np.ndarray] = {}
    latency: dict[int, np.ndarray] = {}
    error: dict[int, np.ndarray] = {}

    for i in range(n_services):
        name = names[i]

        # rps: the shared load, scaled. Does not propagate.
        rps = rps_scale[i] * load + rps_noise[i]
        out[f"{name}_rps"] = rps

        # cpu: driven by the traffic this service handles.
        cpu = cpu_coef[i] * rps + cpu_noise[i]
        out[f"{name}_cpu"] = cpu + terms.get(f"{name}_cpu", zero)

        # mem: a random walk that drifts back towards its own level, so it wanders
        # without running away.
        mem = np.empty(n_rows)
        value = mem_level[i]
        for t in range(n_rows):
            value += 0.02 * (mem_level[i] - value) + mem_steps[i, t]
            mem[t] = value
        out[f"{name}_mem"] = mem + terms.get(f"{name}_mem", zero)

    # latency and error, callees first. A parent's index is always below its
    # children's, so counting down visits children before parents.
    for i in range(n_services - 1, -1, -1):
        name = names[i]
        kids = children[i]

        own_latency = latency_base[i] + latency_noise[i] + terms.get(f"own_latency::{i}", zero)
        inherited_latency = sum(
            weight * latency[kid] for weight, kid in zip(latency_weights[i], kids, strict=True)
        )
        latency[i] = own_latency + (inherited_latency if kids else 0.0)

        # Congestion, on top of the linear share. Added here, before this service
        # is used by its own caller, so the effect cascades up the graph the same
        # way the linear part does.
        if congestion is not None and kids:
            extra = np.zeros(n_rows)
            for kid in kids:
                z = (latency[kid] - congestion.latency_median[kid]) / congestion.latency_std[kid]
                extra += np.maximum(0.0, z - CONGESTION_ONSET_Z) ** 2
            latency[i] = latency[i] + congestion.amplification * congestion.own_scale[i] * extra

        own_error = error_base[i] + error_noise[i] + terms.get(f"{name}_error", zero)
        inherited_error = sum(
            weight * error[kid] for weight, kid in zip(error_weights[i], kids, strict=True)
        )
        # An error rate cannot be negative.
        error[i] = np.maximum(own_error + (inherited_error if kids else 0.0), 0.0)

    for i in range(n_services):
        out[f"{names[i]}_latency"] = latency[i]
        out[f"{names[i]}_error"] = error[i]

    return out
