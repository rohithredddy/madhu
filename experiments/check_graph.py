"""Check a static call graph against real data, and measure what it buys.

Task M2.5's verification. Writing the YAML is not enough: a graph whose service
names do not match the benchmark's column names loads cleanly, matches nothing,
and leaves PARE quietly working without the one ingredient it exists to use. So
this script does two things.

1. **Validate.** Collect every service named in the data and compare it with the
   graph. A service the graph names but the data does not have is a mistake; a
   service the data has but the graph leaves isolated must be accounted for in the
   file's `no_edges` section or it is an oversight.
2. **Measure.** Run `PARE` with the graph and with an empty one on the same cases.
   Without a graph PARE has nothing to subtract, so every self-score equals its
   marginal score and the method is just a re-anchored robust-z. The difference
   between the two runs is therefore the first direct measurement of what the
   residual step contributes on real data, and it is also the sanity check that
   the graph is wired in at all: if the two runs agree exactly, it is not.

This also produces the first `symptom_rate` the project can compute. That metric
needs a graph to ask "is the service we wrongly blamed an ancestor of the real
cause", so until now it has been empty everywhere.

    analyzer/.venv/Scripts/python.exe experiments/check_graph.py

Results go to `experiments/results/m2_5/`. This is a verification run, not one of
the paper's experiments - E2 (M4.1) is where PARE is measured properly, with every
engine and the delay sweep.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare import eval_metrics  # noqa: E402
from pare.config import PareConfig  # noqa: E402
from pare.engine import AnalyzeRequest, Window, analyze  # noqa: E402
from pare.graph import CallGraph  # noqa: E402

from experiments.adapters.graphs import (  # noqa: E402
    load_graph,
    read_graph_file,
    validate_against_cases,
)
from experiments.adapters.rcaeval import (  # noqa: E402
    SYSTEM_SERVICES,
    Case,
    list_cases,
    load_case,
)

RUN_ID = "m2_5"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--data-root", type=Path, default=repo_root / "data" / "RCAEval")
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--system", default="online-boutique")
    parser.add_argument(
        "--results", type=Path, default=repo_root / "experiments" / "results" / RUN_ID
    )
    parser.add_argument("--engine", default="PARE")
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    graph_file = read_graph_file(args.system)
    print(f"--- {graph_file.path.name} ---")
    print(
        f"{len(graph_file.edges)} edges over {len(graph_file.services)} services, "
        f"source {graph_file.source}"
    )
    origin = graph_file.origin
    print(
        f"from {origin.get('repository', '?')} at {origin.get('version', '?')}, "
        f"retrieved {origin.get('retrieved', '?')}"
    )
    if graph_file.renamed:
        print(f"renamed to match the data: {graph_file.renamed}")
    if graph_file.excluded:
        print(f"excluded: {', '.join(graph_file.excluded)}")

    cases = list_cases(args.data_root, args.dataset, args.system)
    if args.limit is not None:
        cases = cases[: args.limit]
    print(f"\n{len(cases)} cases on disk")

    # --- 1. validate -------------------------------------------------------
    services_in_data = _services_in_data(cases, args.system)
    check = validate_against_cases(args.system, services_in_data)
    print("\n--- does the graph match the data? ---")
    print(check.report())
    if not check.is_usable:
        print(
            "\nSTOPPING: the graph does not match the data, so measuring it would "
            "measure nothing. Fix the names in the YAML first.",
            file=sys.stderr,
        )
        return 1

    # --- 2. measure --------------------------------------------------------
    graph = load_graph(args.system)
    print("\n--- what the graph buys: PARE with it against PARE without it ---")
    rows: list[dict[str, object]] = []
    for label, used_graph in (("with_graph", graph), ("no_graph", CallGraph.empty())):
        for position, case in enumerate(cases, start=1):
            rows.append(
                _run_one(
                    case=case,
                    graph=used_graph,
                    scoring_graph=graph,
                    variant=label,
                    engine=args.engine,
                    delay_s=args.delay_s,
                    seed=args.seed,
                )
            )
            if position % 25 == 0 or position == len(cases):
                print(f"  {label}: {position}/{len(cases)}")

    frame = pd.DataFrame(rows)
    summary = _summarise(frame)
    wiring = _wiring_check(frame)
    print("\n--- is the graph actually reaching the engine? ---")
    print(wiring)

    args.results.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.results / "cases.csv", index=False)
    summary.to_csv(args.results / "summary.csv", index=False)
    report = "\n".join(
        [
            f"--- {args.engine} on {args.dataset} {args.system}, "
            f"delay {args.delay_s} s ---",
            summary.to_string(index=False),
            "",
            "--- the graph check ---",
            check.report(),
            "",
            "--- is the graph reaching the engine? ---",
            wiring,
        ]
    )
    (args.results / "comparison.txt").write_text(report + "\n", encoding="utf-8")
    (args.results / "config.json").write_text(
        json.dumps(
            {
                "script": Path(__file__).name,
                "run_id": RUN_ID,
                "dataset": args.dataset,
                "system": args.system,
                "engine": args.engine,
                "delay_s": args.delay_s,
                "seed": args.seed,
                "limit": args.limit,
                "graph_file": graph_file.path.name,
                "graph_version": origin.get("version"),
                "graph_edges": len(graph_file.edges),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_env(args.results / "env.txt")

    print()
    print(summary.to_string(index=False))
    print(f"\nwrote {args.results}")
    return 0


def _services_in_data(cases: Sequence[Case], system: str) -> set[str]:
    """Every service the **engine** sees, over every case.

    Deliberately not every service named in a CSV header. The adapter drops columns
    whose service is not a known service of the system, which is how the one
    contaminated RE1-OB case that M2.2 found - it carries nine stray Sock Shop
    columns - is kept out of the ranking. Those names reach no engine, so a graph
    that does not mention them is not incomplete. Filtering by the same allowlist
    the adapter uses keeps this check asking the right question: do the graph's
    names match what the engine is actually given?

    Reads only the CSV headers, so it costs a second rather than loading 125 files.
    """
    known = SYSTEM_SERVICES.get(system)
    found: set[str] = set()
    for case in cases:
        columns = pd.read_csv(case.path / "data.csv", nrows=0).columns
        for name in columns:
            if name == "time" or name.split(".")[0] == "time":
                continue
            service, _, metric = name.rpartition("_")
            if not service or not metric:
                continue
            if known is not None and service not in known:
                continue
            found.add(service)
    return found


def _run_one(
    case: Case,
    graph: CallGraph,
    scoring_graph: CallGraph,
    variant: str,
    engine: str,
    delay_s: float,
    seed: int,
) -> dict[str, object]:
    """One case, one variant. Failures are recorded, not hidden."""
    started = time.perf_counter()
    try:
        data = load_case(case, delay_s=delay_s, graph=graph)
        names = [column.name for column in data.columns]
        result = analyze(
            AnalyzeRequest(
                engine=engine,
                alarm_time_sec=data.alarm_time_sec,
                columns=data.columns,
                normal=Window.of(
                    data.normal["time"].to_numpy(dtype=float),
                    data.normal[names].to_numpy(dtype=float),
                ),
                recent=Window.of(
                    data.recent["time"].to_numpy(dtype=float),
                    data.recent[names].to_numpy(dtype=float),
                ),
                graph=data.graph,
                config=PareConfig(seed=seed, top_k=10_000),
            )
        )
    except Exception as error:  # noqa: BLE001 - recorded, not hidden
        return {
            "variant": variant,
            "case_id": case.case_id,
            "fault_type": case.fault_type,
            "error": f"{type(error).__name__}: {error}",
            "runtime_s": round(time.perf_counter() - started, 4),
        }

    runtime_s = time.perf_counter() - started
    service_order = tuple(item.service for item in result.services)
    service_scores = {item.service: item.score for item in result.services}
    columns = tuple(item.column for item in result.indicators)
    column_scores = {item.column: item.self_score for item in result.indicators}

    rank_service = eval_metrics.rank_in_order(
        service_order, service_scores, case.gt_service
    )
    top1 = service_order[0] if service_order else None
    # The symptom test always uses the real graph, even for the no-graph variant:
    # the question "was the service we blamed an ancestor of the true cause" is
    # about the system, not about what the engine was told.
    symptom = eval_metrics.symptom_error(top1, case.gt_service, scoring_graph)

    top_service = result.services[0] if result.services else None
    return {
        "variant": variant,
        "case_id": case.case_id,
        "fault_type": case.fault_type,
        "gt_service": case.gt_service,
        "rank_gt_service": rank_service.best if rank_service else "",
        "tied_gt_service": rank_service.tied if rank_service else "",
        "rank_gt_indicator": _rank_of(columns, column_scores, case.gt_indicator),
        "rank_gt_indicator_loose": _best_of(
            columns, column_scores, case.acceptable_indicators
        ),
        "top1_service": top1 or "",
        # Two different things, and `docs/05` step 5 means the second by "the
        # fine-grained answer": the globally loudest column, and the loudest column
        # belonging to the service actually ranked first. They differ whenever the
        # traversal step promotes a service that is not the top scorer.
        "top_indicator_global": columns[0] if columns else "",
        "top_indicator_in_top1": next(
            (
                item.column
                for item in result.indicators
                if top1 is not None and item.service == top1
            ),
            "",
        ),
        "symptom_error": "" if symptom is None else symptom,
        "verdict": result.verdict,
        # The quantity the whole method rests on: how much of a service's deviation
        # its dependencies explain. Without a graph it is 0 everywhere by
        # construction, so these three columns are the cheapest check that the
        # graph is actually reaching the engine.
        "top1_inherited_fraction": (
            round(top_service.inherited_fraction, 4) if top_service else ""
        ),
        "n_symptom_roles": sum(1 for item in result.services if item.role == "SYMPTOM"),
        "max_inherited_fraction": round(
            max((item.inherited_fraction for item in result.services), default=0.0), 4
        ),
        "service_ranking": ";".join(service_order),
        "top1_score": round(top_service.score, 4) if top_service else "",
        "top1_marginal": round(top_service.marginal_score, 4) if top_service else "",
        "error": "",
        "runtime_s": round(runtime_s, 4),
    }


def _rank_of(columns, scores, target) -> object:
    if not target:
        return ""
    rank = eval_metrics.rank_in_order(columns, scores, target)
    return rank.best if rank else ""


def _best_of(columns, scores, acceptable) -> object:
    ranks = [
        rank
        for rank in (
            eval_metrics.rank_in_order(columns, scores, name) for name in acceptable
        )
        if rank is not None
    ]
    return min(rank.best for rank in ranks) if ranks else ""


def _wiring_check(frame: pd.DataFrame) -> str:
    """Did the graph change anything at all? The question accuracy cannot answer.

    Accuracy is a poor wiring check: two runs can score the same by coincidence,
    and a bad score invites the wrong conclusion that the graph is wrong. These
    three facts are not coincidences. Only a graph can produce a non-zero inherited
    fraction, only an inherited fraction of 0.6 or more produces a SYMPTOM role, and
    a changed ranking means the residual step moved something.
    """
    with_graph = frame[frame["variant"] == "with_graph"].set_index("case_id")
    no_graph = frame[frame["variant"] == "no_graph"].set_index("case_id")
    shared = sorted(set(with_graph.index) & set(no_graph.index))

    differing = [
        case_id
        for case_id in shared
        if with_graph.loc[case_id, "service_ranking"]
        != no_graph.loc[case_id, "service_ranking"]
    ]
    inherited = pd.to_numeric(with_graph["max_inherited_fraction"], errors="coerce")
    symptoms = pd.to_numeric(with_graph["n_symptom_roles"], errors="coerce")
    no_graph_inherited = pd.to_numeric(
        no_graph["max_inherited_fraction"], errors="coerce"
    )

    lines = [
        f"service ranking differs on {len(differing)}/{len(shared)} cases",
        f"cases where some service has an inherited fraction above 0: "
        f"{int((inherited > 0).sum())}/{len(shared)} with the graph, "
        f"{int((no_graph_inherited > 0).sum())}/{len(shared)} without it "
        f"(without must be 0)",
        f"cases with at least one SYMPTOM role: {int((symptoms > 0).sum())}/{len(shared)}",
    ]
    if not differing and int((inherited > 0).sum()) == 0:
        lines.append(
            "  FAILED: the graph changed nothing. It is not reaching the engine, or "
            "its service names do not match the data."
        )
    else:
        lines.append("  the graph is reaching the engine and changing its answer")
    return "\n".join(lines)


def _summarise(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per variant, plus one per variant and fault type."""
    out: list[dict[str, object]] = []
    for variant in frame["variant"].unique():
        group = frame[frame["variant"] == variant]
        for fault in [None, *sorted(group["fault_type"].dropna().unique())]:
            part = group if fault is None else group[group["fault_type"] == fault]
            out.append(_summary_row(variant, fault or "ALL", part))
    return pd.DataFrame(out)


def _summary_row(variant: str, fault: str, part: pd.DataFrame) -> dict[str, object]:
    ranks = [
        eval_metrics.Rank(best=int(best), tied=int(tied))
        for best, tied in zip(part["rank_gt_service"], part["tied_gt_service"], strict=True)
        if str(best) not in ("", "nan")
    ]
    # A case whose truth was never ranked is a miss, not an omission, so pad the
    # list back to the full case count rather than averaging over fewer cases.
    padded = ranks + [None] * (len(part) - len(ranks))
    symptoms = [
        value
        for value in part["symptom_error"]
        if isinstance(value, bool) or str(value) in ("True", "False")
    ]
    symptom_flags = [str(value) == "True" for value in symptoms]
    inherited = pd.to_numeric(part["top1_inherited_fraction"], errors="coerce").dropna()

    return {
        "variant": variant,
        "fault_type": fault,
        "cases": len(part),
        "failed": int((part["error"].astype(str) != "").sum()),
        "ac1": round(eval_metrics.ac_at_k(padded, 1), 4),
        "ac3": round(eval_metrics.ac_at_k(padded, 3), 4),
        "avg5": round(eval_metrics.avg_at_5(padded), 4),
        "symptom_rate": (
            round(float(np.mean(symptom_flags)), 4) if symptom_flags else ""
        ),
        "wrong_top1": int(sum(1 for rank in padded if rank is None or rank.best != 1)),
        "no_clear_cause": int((part["verdict"] == "NO_CLEAR_CAUSE").sum()),
        "mean_top1_inherited": round(float(inherited.mean()), 4) if len(inherited) else "",
        # The graph's fingerprint. A SYMPTOM role needs an inherited fraction of at
        # least 0.6, which is unreachable without residuals, so this is 0 for the
        # no-graph variant by construction and anything above 0 proves the graph
        # reached the engine.
        "cases_with_a_symptom": int((pd.to_numeric(part["n_symptom_roles"]) > 0).sum()),
        "mean_ms": round(float(part["runtime_s"].mean() * 1000), 1),
    }


def _write_env(path: Path) -> None:
    from importlib.metadata import PackageNotFoundError, version

    lines = [f"python: {sys.version}", f"platform: {platform.platform()}"]
    for package in ("pare", "numpy", "pandas", "scikit-learn", "scipy", "ruptures"):
        try:
            lines.append(f"{package}: {version(package)}")
        except PackageNotFoundError:
            lines.append(f"{package}: not installed")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
