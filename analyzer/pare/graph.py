"""The call graph: who calls whom, and the questions the method asks of it.

An edge runs **from the caller to the callee**. If the frontend calls the cart
service, the edge is ``frontend -> cartservice``. Everything else follows from
that one convention, so it is worth fixing firmly in mind:

* :meth:`CallGraph.children` - the services this one **calls**. These are the
  features the dependency model uses: to judge whether a service's own slowness
  is its fault, we first ask what the services it waits on were doing.
* :meth:`CallGraph.parents` - the services that **call** this one.
* :meth:`CallGraph.ancestors` - everyone that calls it, directly or through
  others. A fault travels *up* this way, so the ancestors of the real culprit are
  exactly the services that can look broken while being fine. That is the
  definition the symptom-rate metric uses.

The graph may be empty, may contain cycles (real trace graphs and inferred graphs
both do), and may name services that have no data. Every method copes rather than
raising, because a messy graph is a normal input, not a bug.

Spec: ``docs/05_PYTHON_ANALYZER_SPEC.md`` sections 1 and 3, and the ``graph``
object in ``docs/06_DATA_CONTRACTS.md`` section 2.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pare.columns import ColumnInfo

# Where a graph came from. Matches graph.source in docs/06 section 2, and is
# carried through to the result so a reader knows how much to trust the edges.
GRAPH_SOURCES = (
    "TRACES",
    "STATIC_ARCHITECTURE",
    "CORRELATION",
    "SYNTHETIC_TRUE",
    "USER",
    "NONE",
)


@dataclass(frozen=True)
class Edge:
    """One call: ``caller`` calls ``callee``.

    The JSON form in ``docs/06`` uses ``from`` and ``to``, which cannot be
    attribute names in Python, so the conversion happens in
    :meth:`from_dict` and :meth:`to_dict`.
    """

    caller: str
    callee: str

    def __post_init__(self) -> None:
        for name in ("caller", "callee"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Edge.{name} must be a non-empty string, got {value!r}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Edge:
        missing = {"from", "to"} - set(data)
        if missing:
            raise ValueError(f"edge is missing {sorted(missing)}: {dict(data)!r}")
        return cls(caller=data["from"], callee=data["to"])

    def to_dict(self) -> dict[str, str]:
        return {"from": self.caller, "to": self.callee}

    def as_tuple(self) -> tuple[str, str]:
        return (self.caller, self.callee)


@dataclass(frozen=True)
class CallGraph:
    """Who calls whom, with the lookups the method needs.

    Build one with :meth:`from_edges`; the constructor assumes its input is
    already clean. ``source`` records where the edges came from and is passed
    through to the result, because an inferred graph deserves less trust than one
    read from traces.
    """

    edges: tuple[Edge, ...] = ()
    source: str = "NONE"

    # Built once at construction; the graph is frozen, so these stay correct.
    _children: dict[str, tuple[str, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _parents: dict[str, tuple[str, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    # --- building ----------------------------------------------------------

    @classmethod
    def from_edges(
        cls,
        edges: Iterable[Edge | tuple[str, str] | Mapping[str, Any]],
        source: str = "NONE",
    ) -> CallGraph:
        """Build a graph from edges in any of the shapes we receive them.

        Accepts :class:`Edge` objects, ``(caller, callee)`` tuples (what
        ``pare.synthetic`` returns), or ``{"from": ..., "to": ...}`` mappings
        (what arrives over the API).

        Two kinds of mess are cleaned up quietly, because both turn up in real
        and inferred graphs:

        * **Duplicate edges** are collapsed. Trace data often records the same
          call thousands of times.
        * **Self-loops are dropped.** A service calling itself would make it its
          own child, and the dependency model would then predict a service from
          its own values - exactly the autoregressive leak that step 3 of the
          spec forbids, which would hide the anomaly it is meant to find.

        Edge order is otherwise preserved, so results stay reproducible.
        """
        if source not in GRAPH_SOURCES:
            raise ValueError(f"graph source must be one of {GRAPH_SOURCES}, got {source!r}")

        cleaned: OrderedDict[tuple[str, str], Edge] = OrderedDict()
        for raw in edges:
            edge = _as_edge(raw)
            if edge.caller == edge.callee:
                continue  # self-loop, see the docstring
            cleaned.setdefault(edge.as_tuple(), edge)

        ordered = tuple(cleaned.values())
        children: dict[str, list[str]] = OrderedDict()
        parents: dict[str, list[str]] = OrderedDict()
        for edge in ordered:
            children.setdefault(edge.caller, []).append(edge.callee)
            children.setdefault(edge.callee, [])
            parents.setdefault(edge.callee, []).append(edge.caller)
            parents.setdefault(edge.caller, [])

        return cls(
            edges=ordered,
            source=source,
            _children={name: tuple(values) for name, values in children.items()},
            _parents={name: tuple(values) for name, values in parents.items()},
        )

    @classmethod
    def empty(cls) -> CallGraph:
        """A graph with no edges. PARE still runs, it just has nothing to
        subtract, so every self-score equals its marginal score."""
        return cls.from_edges([], source="NONE")

    @classmethod
    def from_dicts(
        cls, items: Iterable[Mapping[str, Any]], source: str = "NONE"
    ) -> CallGraph:
        """Build from the JSON form: ``[{"from": "a", "to": "b"}, ...]``."""
        return cls.from_edges([Edge.from_dict(item) for item in items], source=source)

    def to_dicts(self) -> list[dict[str, str]]:
        """The JSON form, for the API and for saving next to a result."""
        return [edge.to_dict() for edge in self.edges]

    # --- asking questions --------------------------------------------------

    @property
    def services(self) -> tuple[str, ...]:
        """Every service mentioned by an edge, in the order first seen."""
        return tuple(self._children)

    @property
    def is_empty(self) -> bool:
        return not self.edges

    def has_edge(self, caller: str, callee: str) -> bool:
        return callee in self._children.get(caller, ())

    def children(self, service: str) -> tuple[str, ...]:
        """The services this one calls.

        These are the dependency model's features. An unknown service gives an
        empty tuple rather than an error: a case may well have data for services
        the graph does not mention, and that simply means we have nothing to
        explain it with.
        """
        return self._children.get(service, ())

    def parents(self, service: str) -> tuple[str, ...]:
        """The services that call this one."""
        return self._parents.get(service, ())

    def ancestors(self, service: str) -> tuple[str, ...]:
        """Everyone that calls this service, directly or through others.

        This is the set the symptom-rate metric is defined on: if the top-ranked
        service is wrong but is an ancestor of the true culprit, the method
        blamed something that was only feeling the effect.

        Breadth-first and cycle-safe, so a graph where ``a`` calls ``b`` calls
        ``a`` terminates instead of looping forever. The service itself is not
        included, even when a cycle leads back to it.
        """
        return self._walk(service, self._parents)

    def descendants(self, service: str) -> tuple[str, ...]:
        """Everything this service calls, directly or through others."""
        return self._walk(service, self._children)

    def _walk(self, start: str, step: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
        """Breadth-first walk from ``start``, never visiting a node twice."""
        seen: set[str] = set()
        order: list[str] = []
        queue = deque(step.get(start, ()))
        while queue:
            current = queue.popleft()
            if current in seen or current == start:
                continue
            seen.add(current)
            order.append(current)
            queue.extend(step.get(current, ()))
        return tuple(order)

    # --- inferring a graph when none was given -----------------------------

    @classmethod
    def infer_from_correlation(
        cls,
        normal: Any,
        columns: Sequence[ColumnInfo],
        metric: str = "latency",
        max_lag: int = 3,
        min_correlation: float = 0.5,
        max_children: int = 3,
    ) -> CallGraph:
        """Guess a call graph from normal data, when no real one is available.

        RE1 has metrics but no traces, so this is the fallback the graph ablation
        (experiment E4) compares against the real architecture. It is **a rough
        heuristic and is meant to be**: the point of E4 is to measure how much
        PARE degrades when the graph is wrong, so this needs to be a plausible
        wrong graph, not a good one.

        How it works, for one chosen metric (``latency`` by default, because that
        is the metric that actually flows between services):

        1. Build one series per service by averaging that service's columns for
           the metric, and standardise each.
        2. For every ordered pair, take the strongest correlation of one service
           against the other shifted back by 0 to ``max_lag`` rows. A caller's
           response time follows its callee's, so the callee leads.
        3. Link the pair if that correlation reaches ``min_correlation``.
        4. Decide the direction. Prefer the lag evidence: whichever ordering
           gives the stronger correlation is taken as caller-follows-callee. When
           the two orderings are within a whisker of each other - which happens
           whenever propagation is effectively instantaneous, as it is in our own
           synthetic data - fall back to variance: a caller's response time
           contains its callee's plus its own work, so it varies at least as
           much. The wider series is taken as the caller.
        5. Keep at most ``max_children`` strongest links per caller, so one
           heavily correlated service does not become everyone's callee.

        Returns a graph with ``source="CORRELATION"``.
        """
        series, names = _service_series(normal, columns, metric)
        if len(names) < 2:
            return cls.empty()

        variances = {name: float(np.var(series[name])) for name in names}

        # strength[(a, b)] = how well b leads a, i.e. evidence for "a calls b"
        strength: dict[tuple[str, str], float] = {}
        for a in names:
            for b in names:
                if a == b:
                    continue
                strength[(a, b)] = _best_lagged_correlation(series[a], series[b], max_lag)

        candidates: dict[str, list[tuple[float, str]]] = {}
        for index, a in enumerate(names):
            for b in names[index + 1 :]:
                forward = strength[(a, b)]  # a calls b
                backward = strength[(b, a)]  # b calls a
                best = max(forward, backward)
                if best < min_correlation:
                    continue

                # Direction: lag evidence first, variance as the tie-breaker.
                if abs(forward - backward) > 0.02:
                    caller, callee = (a, b) if forward > backward else (b, a)
                else:
                    caller, callee = (a, b) if variances[a] >= variances[b] else (b, a)
                candidates.setdefault(caller, []).append((best, callee))

        edges: list[Edge] = []
        for caller in names:  # fixed order, so the result is reproducible
            ranked = sorted(candidates.get(caller, []), key=lambda item: (-item[0], item[1]))
            for _, callee in ranked[:max_children]:
                edges.append(Edge(caller=caller, callee=callee))

        return cls.from_edges(edges, source="CORRELATION")


# --- helpers ----------------------------------------------------------------


def _as_edge(raw: Edge | tuple[str, str] | Mapping[str, Any]) -> Edge:
    """Accept an Edge, a (caller, callee) tuple, or a {"from", "to"} mapping."""
    if isinstance(raw, Edge):
        return raw
    if isinstance(raw, Mapping):
        return Edge.from_dict(raw)
    if isinstance(raw, (tuple, list)):
        if len(raw) != 2:
            raise ValueError(f"an edge tuple must have exactly 2 items, got {raw!r}")
        return Edge(caller=raw[0], callee=raw[1])
    raise TypeError(f"cannot read an edge from {raw!r}")


def _service_series(
    normal: Any, columns: Sequence[ColumnInfo], metric: str
) -> tuple[dict[str, np.ndarray], list[str]]:
    """One standardised series per service, for the chosen metric.

    Services whose series never moves are left out: a flat line correlates with
    nothing and would only produce noise.
    """
    data = np.asarray(normal, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"normal must be rows by columns, got {data.ndim} dimensions")
    if data.shape[1] != len(columns):
        raise ValueError(
            f"normal has {data.shape[1]} columns but {len(columns)} were described"
        )

    wanted: dict[str, list[int]] = OrderedDict()
    for index, column in enumerate(columns):
        if column.metric == metric:
            wanted.setdefault(column.service, []).append(index)

    series: dict[str, np.ndarray] = {}
    names: list[str] = []
    for service, indexes in wanted.items():
        values = np.nanmean(data[:, indexes], axis=1)
        spread = np.nanstd(values)
        if not np.isfinite(spread) or spread == 0:
            continue
        series[service] = (values - np.nanmean(values)) / spread
        names.append(service)
    return series, names


def _best_lagged_correlation(follower: np.ndarray, leader: np.ndarray, max_lag: int) -> float:
    """Strongest correlation of ``follower`` at time t with ``leader`` at t-lag.

    Lag 0 is included, because a call and its effect often land in the same
    sampling interval.
    """
    best = 0.0
    for lag in range(max_lag + 1):
        if lag == 0:
            a, b = follower, leader
        else:
            a, b = follower[lag:], leader[:-lag]
        if a.size < 3:
            continue
        with np.errstate(invalid="ignore"):
            matrix = np.corrcoef(a, b)
        value = float(matrix[0, 1])
        if np.isfinite(value):
            best = max(best, value)
    return best
