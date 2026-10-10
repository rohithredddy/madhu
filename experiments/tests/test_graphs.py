"""Tests for the static call graphs and their loader.

Two kinds of test here. The first kind checks the loader: that it rejects a
malformed file rather than loading half of it, because a graph that silently loses
edges degrades PARE into a robust-z method while still looking like PARE.

The second kind checks the **content** of the two YAML files against facts that
can be stated independently - the shape of the topology, the direction of the
edges, and, where the data exists, that every service the graph names is a service
the engine will actually see. Those are the tests that would catch the mistake
that matters: a graph whose names do not match the benchmark's.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from experiments.adapters.graphs import (
    KNOWN_SYSTEMS,
    load_graph,
    read_graph_file,
    validate_against_cases,
)
from experiments.adapters.rcaeval import SYSTEM_SERVICES, list_cases

ROOT = Path(__file__).resolve().parents[2] / "data" / "RCAEval"
HAVE_OB = (ROOT / "RE1" / "RE1-OB").exists()
HAVE_SS = (ROOT / "RE1" / "RE1-SS").exists()

needs_ob = pytest.mark.skipif(
    not HAVE_OB,
    reason="RE1-OB not downloaded; run experiments/download_rcaeval.py --dataset RE1-OB",
)


# --- the loader -------------------------------------------------------------


def test_both_known_systems_load():
    for system in KNOWN_SYSTEMS:
        graph = load_graph(system)
        assert not graph.is_empty
        assert graph.source == "STATIC_ARCHITECTURE"


def test_an_unknown_system_is_refused():
    with pytest.raises(ValueError, match="no graph known for system"):
        read_graph_file("not-a-system")


def test_the_file_must_agree_about_which_system_it_describes(tmp_path: Path):
    """Guards against a copy-paste that would silently give one system another's
    topology."""
    (tmp_path / "online-boutique.yaml").write_text(
        yaml.safe_dump({"system": "sock-shop", "edges": [{"from": "a", "to": "b"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="says system"):
        read_graph_file("online-boutique", graphs_dir=tmp_path)


@pytest.mark.parametrize(
    ("edges", "message"),
    [
        ([], "declares no edges"),
        ([{"from": "a"}], "must be a mapping with 'from' and 'to'"),
        (["a -> b"], "must be a mapping with 'from' and 'to'"),
        ([{"from": "a", "to": "a"}], "self-loop"),
        ([{"from": "a", "to": "b"}, {"from": "a", "to": "b"}], "twice"),
    ],
)
def test_a_malformed_edge_list_is_refused(tmp_path: Path, edges, message):
    (tmp_path / "sock-shop.yaml").write_text(
        yaml.safe_dump({"system": "sock-shop", "edges": edges}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=message):
        read_graph_file("sock-shop", graphs_dir=tmp_path)


# --- what the Online Boutique graph says ------------------------------------


def test_online_boutique_has_the_topology_its_architecture_implies():
    graph = load_graph("online-boutique")

    # frontend is the entry point: it calls, and nothing in the graph calls it.
    # (loadgenerator would, but it appears in no column of the data and is
    # excluded; the file records that.)
    assert graph.parents("frontend") == ()
    assert len(graph.children("frontend")) == 7

    # redis is the only datastore and the only leaf under cartservice.
    assert graph.children("redis") == ()
    assert graph.parents("redis") == ("cartservice",)

    # checkoutservice is the fan-out of the purchase path, and it is the only
    # caller of emailservice and paymentservice.
    assert graph.parents("emailservice") == ("checkoutservice",)
    assert graph.parents("paymentservice") == ("checkoutservice",)

    # Two services call cartservice, which is what makes it a good example of the
    # cause-versus-symptom problem: a fault in it shows up in both callers.
    assert set(graph.parents("cartservice")) == {"frontend", "checkoutservice"}


def test_edges_point_from_caller_to_callee():
    """The direction the whole method depends on.

    PARE subtracts what a service's *callees* explain, and `symptom_error` asks
    whether a wrongly blamed service is an *ancestor* of the real cause. Both
    invert if the direction is reversed, so it is asserted against a fact nobody
    can argue with: a database calls nothing.
    """
    graph = load_graph("online-boutique")
    assert graph.children("redis") == ()
    assert "cartservice" in graph.ancestors("redis")
    assert "frontend" in graph.ancestors("redis")

    sock_shop = load_graph("sock-shop")
    for database in ("carts-db", "orders-db", "catalogue-db", "user-db", "session-db"):
        assert sock_shop.children(database) == (), f"{database} should call nothing"


def test_online_boutique_names_only_services_the_adapter_keeps():
    """A graph service the adapter drops would be an edge to nowhere.

    Checked against the allowlist rather than the data, so it runs without the
    download; the data-backed version of this check is below.
    """
    allowed = SYSTEM_SERVICES["online-boutique"]
    for service in read_graph_file("online-boutique").services:
        assert service in allowed, f"{service} is not a known Online Boutique service"


# --- what the Sock Shop graph says ------------------------------------------


def test_sock_shop_has_the_topology_its_architecture_implies():
    graph = load_graph("sock-shop")

    assert graph.parents("front-end") == ()
    assert set(graph.children("front-end")) == {
        "catalogue",
        "carts",
        "orders",
        "user",
        "session-db",
    }
    # orders is the other fan-out, and the two edges that are easy to miss -
    # orders calls user and carts through URLs it is handed, not hostnames it
    # hard-codes - are the ones worth pinning.
    assert set(graph.children("orders")) == {
        "payment",
        "shipping",
        "user",
        "carts",
        "orders-db",
    }
    # shipping and queue-master both talk to the broker and not to each other.
    assert graph.children("shipping") == ("rabbitmq",)
    assert graph.children("queue-master") == ("rabbitmq",)
    assert "queue-master" not in graph.children("shipping")
    assert "shipping" not in graph.children("queue-master")


def test_every_sock_shop_service_is_connected():
    """All 14 Deployments appear, so nothing was forgotten.

    Written before RE1-SS was downloaded, when this structural check was the only
    guard the file had. The data check below now backs it up.
    """
    expected = {
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
        "session-db",
        "shipping",
        "user",
        "user-db",
    }
    assert set(read_graph_file("sock-shop").services) == expected


def test_every_edge_records_where_it_came_from_for_sock_shop():
    """Sock Shop declares no dependencies in its manifests, so each edge was read
    out of a different source file. Without the evidence field the file would be
    unverifiable, which defeats its being on the human-check list."""
    with (read_graph_file("sock-shop").path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    for edge in data["edges"]:
        assert edge.get("evidence"), f"{edge['from']} -> {edge['to']} has no evidence"


# --- against the real data --------------------------------------------------


@needs_ob
def test_the_online_boutique_graph_matches_the_data():
    """The check that matters, and the reason `validate_against_cases` exists.

    RE1-OB calls the `redis-cart` Deployment `redis`. A graph that kept the
    manifest's spelling would load fine, match nothing, and leave PARE running
    without the one input it exists to use.
    """
    import pandas as pd

    allowed = SYSTEM_SERVICES["online-boutique"]
    seen: set[str] = set()
    for case in list_cases(ROOT, "RE1", "online-boutique"):
        for name in pd.read_csv(case.path / "data.csv", nrows=0).columns:
            if name == "time" or name.split(".")[0] == "time":
                continue
            service, _, metric = name.rpartition("_")
            if service and metric and service in allowed:
                seen.add(service)

    check = validate_against_cases("online-boutique", seen)
    assert check.missing_from_data == (), (
        f"the graph names services the data does not have: {check.missing_from_data}"
    )
    assert check.undeclared_isolated == (), (
        f"services in the data with no edges and no explanation: "
        f"{check.undeclared_isolated}"
    )
    assert check.is_usable
    # redis specifically, because it is the one renamed service.
    assert "redis" in check.graph_services
    assert "redis" in check.data_services


@pytest.mark.skipif(not HAVE_SS, reason="RE1-SS not downloaded")
def test_the_sock_shop_graph_matches_the_data():
    """M3.2. Every one of the 14 services the file names exists in RE1-SS under
    the same spelling, and the one extra service in the data, the RabbitMQ
    exporter, is declared under `no_edges` rather than silently isolated."""
    import pandas as pd

    from experiments.adapters.rcaeval import METRICS_FILE

    allowed = SYSTEM_SERVICES["sock-shop"]
    seen: set[str] = set()
    for case in list_cases(ROOT, "RE1", "sock-shop"):
        header = pd.read_csv(case.path / METRICS_FILE["sock-shop"], nrows=0).columns
        for name in header:
            service, _, metric = name.rpartition("_")
            if service and metric and service in allowed:
                seen.add(service)

    check = validate_against_cases("sock-shop", seen)
    assert check.missing_from_data == ()
    assert check.undeclared_isolated == ()
    assert check.is_usable
    assert check.missing_from_graph == ("rabbitmq-exporter",)


# --- graphs built from traces (M5.2) -------------------------------------------


def test_the_online_boutique_trace_graph_loads_by_name_and_says_where_it_came_from():
    from experiments.adapters.graphs import EXTRA_GRAPHS, graph_names

    assert "online-boutique-traces" in graph_names()
    assert EXTRA_GRAPHS["online-boutique-traces"][1] == "online-boutique"
    graph = load_graph("online-boutique-traces")
    assert graph.source == "TRACES"
    assert not graph.is_empty


def test_every_traced_edge_is_also_in_the_static_graph():
    """The measured graph confirms the hand-written one: RE2-OB's traces produced
    9 edges and every one of them is an edge of the static graph, same direction.
    What the traces lack are the services no span mentions (adservice, cartservice,
    shippingservice, redis), and the file says so under no_edges."""
    traced = set(read_graph_file("online-boutique-traces").edges)
    static = set(read_graph_file("online-boutique").edges)
    assert traced <= static
    missing = {name for edge in static - traced for name in edge}
    untraced = set(read_graph_file("online-boutique-traces").no_edges)
    # every static edge the traces lack touches a service the traces never saw
    assert all(a in untraced or b in untraced for a, b in static - traced)
    assert {"adservice", "cartservice", "shippingservice", "redis"} <= missing
