"""Load the static call graphs in `experiments/graphs/` into a `CallGraph`.

The YAML files are the deliverable of M2.5 and are written to be read by a person
as much as by this loader: each records where its edges came from, which service
names were changed to match the benchmark data, and what was deliberately left
out. This module turns one of them into the object the engines take, and - just as
importantly - can check it against real data.

That check is the part worth having. A graph whose service names do not match the
data's column names is worse than no graph at all: `CallGraph.children()` returns
nothing for every service, so PARE has nothing to subtract and silently degrades
into a robust-z method while appearing to use a graph. `validate_against_cases`
exists so that failure is loud.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pare.graph import CallGraph

GRAPHS_DIR = Path(__file__).resolve().parents[1] / "graphs"

# The systems that have a hand-written graph, and the file holding it.
KNOWN_SYSTEMS = {
    "online-boutique": "online-boutique.yaml",
    "sock-shop": "sock-shop.yaml",
}


@dataclass(frozen=True)
class GraphFile:
    """One graph file, as written, before it becomes a `CallGraph`.

    Keeps the provenance fields as well as the edges, so a script can print where
    a graph came from rather than leaving the reader to open the YAML.
    """

    system: str
    source: str
    edges: tuple[tuple[str, str], ...]
    origin: dict = field(default_factory=dict)
    renamed: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)
    no_edges: dict = field(default_factory=dict)
    path: Path | None = None

    @property
    def services(self) -> tuple[str, ...]:
        """Every service named by an edge, sorted. Services listed only under
        `no_edges` are deliberately not here: they are part of the data, not of
        the graph."""
        return tuple(sorted({name for edge in self.edges for name in edge}))

    def to_call_graph(self) -> CallGraph:
        return CallGraph.from_edges(list(self.edges), source=self.source)


def read_graph_file(system: str, graphs_dir: Path | None = None) -> GraphFile:
    """Read and validate one graph file. Raises rather than guessing."""
    directory = graphs_dir or GRAPHS_DIR
    filename = KNOWN_SYSTEMS.get(system)
    if filename is None:
        raise ValueError(
            f"no graph known for system {system!r}; known: {sorted(KNOWN_SYSTEMS)}"
        )

    path = directory / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{path} should hold a mapping, got {type(data).__name__}")
    if data.get("system") != system:
        raise ValueError(
            f"{path} says system {data.get('system')!r} but was asked for {system!r}"
        )

    raw_edges = data.get("edges")
    if not raw_edges:
        raise ValueError(f"{path} declares no edges")

    edges: list[tuple[str, str]] = []
    for position, item in enumerate(raw_edges, start=1):
        if not isinstance(item, dict) or "from" not in item or "to" not in item:
            raise ValueError(
                f"{path} edge {position} must be a mapping with 'from' and 'to', "
                f"got {item!r}"
            )
        caller, callee = str(item["from"]), str(item["to"])
        if caller == callee:
            raise ValueError(f"{path} edge {position} is a self-loop on {caller!r}")
        if (caller, callee) in edges:
            raise ValueError(f"{path} lists {caller} -> {callee} twice")
        edges.append((caller, callee))

    return GraphFile(
        system=system,
        source=str(data.get("source", "STATIC_ARCHITECTURE")),
        edges=tuple(edges),
        origin=data.get("origin") or {},
        renamed=data.get("renamed") or {},
        excluded=data.get("excluded") or {},
        no_edges=data.get("no_edges") or {},
        path=path,
    )


def load_graph(system: str, graphs_dir: Path | None = None) -> CallGraph:
    """The graph for one system, ready to hand to an engine."""
    return read_graph_file(system, graphs_dir).to_call_graph()


@dataclass(frozen=True)
class GraphCheck:
    """What a graph does and does not cover, measured against real data."""

    system: str
    graph_services: tuple[str, ...]
    data_services: tuple[str, ...]
    missing_from_data: tuple[str, ...]
    """In the graph but never seen in a column name. Each one is a mistake: an
    edge pointing at a service that does not exist does nothing at all."""

    missing_from_graph: tuple[str, ...]
    """Seen in the data but named by no edge. Not necessarily a mistake - the
    graph file's `no_edges` section says which of these are deliberate - but any
    name not listed there is an oversight worth knowing about."""

    undeclared_isolated: tuple[str, ...]
    """In the data, named by no edge, and not explained by `no_edges`. These are
    the ones to look at."""

    @property
    def is_usable(self) -> bool:
        """Whether the graph can do its job on this data at all.

        Deliberately not "is perfect": a graph is usable when every service it
        names exists in the data and nothing is silently isolated. Services the
        file explains under `no_edges` do not count against it.
        """
        return not self.missing_from_data and not self.undeclared_isolated

    def report(self) -> str:
        lines = [
            f"graph for {self.system}: {len(self.graph_services)} services in "
            f"{len(self.data_services)} seen in the data",
        ]
        if self.missing_from_data:
            lines.append(
                "  NAMED BY THE GRAPH BUT ABSENT FROM THE DATA (these edges do "
                f"nothing): {', '.join(self.missing_from_data)}"
            )
        if self.undeclared_isolated:
            lines.append(
                "  in the data, no edges, and not explained by `no_edges`: "
                f"{', '.join(self.undeclared_isolated)}"
            )
        explained = tuple(
            name for name in self.missing_from_graph if name not in self.undeclared_isolated
        )
        if explained:
            lines.append(
                f"  isolated on purpose, see the file: {', '.join(explained)}"
            )
        if self.is_usable:
            lines.append("  usable: every service the graph names exists in the data")
        return "\n".join(lines)


def validate_against_cases(
    system: str,
    services_in_data: Iterable[str],
    graphs_dir: Path | None = None,
) -> GraphCheck:
    """Compare a graph's service names with the ones the data actually uses.

    The single most valuable check in M2.5. A benchmark renames things - RE1-OB
    calls the `redis-cart` Deployment `redis` - and a graph that keeps the
    manifest's spelling loads without complaint, matches nothing and quietly
    removes the one ingredient PARE needs.
    """
    graph_file = read_graph_file(system, graphs_dir)
    graph_services = set(graph_file.services)
    data_services = set(services_in_data)

    missing_from_graph = data_services - graph_services
    explained = set(graph_file.no_edges) | set(graph_file.excluded)

    return GraphCheck(
        system=system,
        graph_services=tuple(sorted(graph_services)),
        data_services=tuple(sorted(data_services)),
        missing_from_data=tuple(sorted(graph_services - data_services)),
        missing_from_graph=tuple(sorted(missing_from_graph)),
        undeclared_isolated=tuple(sorted(missing_from_graph - explained)),
    )


def services_of(columns: Sequence) -> tuple[str, ...]:
    """The distinct services named by a list of `ColumnInfo`, sorted.

    A one-line helper, but it keeps callers from splitting column names
    themselves, which is the thing the adapter exists to prevent.
    """
    return tuple(sorted({column.service for column in columns}))
