"""E6: the controlled synthetic study - when does PARE help? (M6.1, docs/08 section 4).

On synthetic data the true cause and the true call graph are known exactly, so
each factor the paper cares about can be turned one at a time while everything
else stays at a base setting:

* graph size, propagation strength, amplification, noise, detection delay, and
* graph quality - the true graph, 20% of its edges removed, 20% wrong edges
  added, or no graph. Whatever the engine is told, the answer is always scored
  against the **true** graph.

``n_abnormal`` is held fixed across the whole grid (docs/08: a MEM fault's size
depends on it, so varying it would change the fault while appearing to change
only the run length).

The windows are cut the way the RCAEval adapter cuts them, so the synthetic and
real results answer the same question: the normal window ends ``normal_gap_s``
before the fault, and the recent window runs from ``recent_before_s`` before the
alarm to ``recent_after_s`` after it.

Rows use the ``cases.csv`` columns of docs/06 section 5 plus ``factor`` and
``level``, and are summarised by the same code as E1 and E2
(``experiment.summarise``), so AC@k and the symptom rate mean exactly the same
thing here as there - ties included.

    analyzer/.venv/Scripts/python.exe experiments/run_synthetic_study.py \\
        --config experiments/configs/e6_synthetic.yaml
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from joblib import Parallel, delayed, parallel_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare import eval_metrics  # noqa: E402
from pare.config import PareConfig  # noqa: E402
from pare.engine import ENGINES, AnalyzeRequest, Window, analyze  # noqa: E402
from pare.graph import CallGraph  # noqa: E402
from pare.synthetic import FAULTS, make_case  # noqa: E402

from experiments.experiment import summarise  # noqa: E402
from experiments.runner import CASES_CSV_COLUMNS, _best, _tied  # noqa: E402

GRAPH_QUALITIES = ("TRUE", "DROP_20", "ADD_20", "NONE")
FACTORS = ("n_services", "propagation", "amplification", "noise", "graph", "delay_rows")


def perturb_graph(
    edges: list[tuple[str, str]], services: list[str], quality: str, seed: int
) -> CallGraph:
    """The graph the engine is told, for one graph-quality level.

    DROP_20 removes 20% of the true edges (at least one); ADD_20 adds as many
    edges that do not exist in the true graph, in random directions. The random
    choice is seeded per case so a rerun gives the same graph.
    """
    if quality == "TRUE":
        return CallGraph.from_edges(edges, source="SYNTHETIC_TRUE")
    if quality == "NONE":
        return CallGraph.empty()
    rng = np.random.default_rng([seed, 2026])
    count = max(1, round(0.2 * len(edges)))
    if quality == "DROP_20":
        keep = sorted(rng.choice(len(edges), size=len(edges) - count, replace=False))
        return CallGraph.from_edges([edges[i] for i in keep], source="SYNTHETIC_TRUE")
    if quality == "ADD_20":
        existing = set(edges)
        candidates = [
            (a, b)
            for a in services
            for b in services
            if a != b and (a, b) not in existing and (b, a) not in existing
        ]
        picked = rng.choice(len(candidates), size=min(count, len(candidates)), replace=False)
        added = [candidates[i] for i in sorted(picked)]
        return CallGraph.from_edges(list(edges) + added, source="SYNTHETIC_TRUE")
    raise ValueError(f"graph quality must be one of {GRAPH_QUALITIES}, got {quality!r}")


def one_run(
    method: str,
    fault: str,
    seed: int,
    factor: str,
    level: object,
    settings: dict,
    windows: dict,
) -> dict[str, object]:
    """Build one case, run one engine, return one scored row.

    The ground truth (`case.gt_service`, `case.gt_column`) is read only after the
    engine has returned (hard rule 4).
    """
    case = make_case(
        n_services=int(settings["n_services"]),
        n_normal=int(windows["n_normal"]),
        n_abnormal=int(windows["n_abnormal"]),
        fault=fault,
        propagation=float(settings["propagation"]),
        noise=float(settings["noise"]),
        amplification=float(settings["amplification"]),
        seed=seed,
    )
    frame = case.to_frame()
    times = frame.index.to_numpy(dtype=float)
    alarm = case.inject_time_sec + float(settings["delay_rows"])
    normal = frame[times < case.inject_time_sec - float(windows["normal_gap_s"])]
    recent = frame[
        (times >= alarm - float(windows["recent_before_s"]))
        & (times <= alarm + float(windows["recent_after_s"]))
    ]
    true_graph = CallGraph.from_edges(case.edges, source="SYNTHETIC_TRUE")
    told = perturb_graph(case.edges, case.services, str(settings["graph"]), seed)

    started = time.perf_counter()
    result = analyze(
        AnalyzeRequest(
            engine=method,
            alarm_time_sec=alarm,
            columns=case.columns,
            normal=Window.of(normal.index.to_numpy(dtype=float), normal.to_numpy()),
            recent=Window.of(recent.index.to_numpy(dtype=float), recent.to_numpy()),
            graph=told,
            config=PareConfig(seed=seed, top_k=10_000),
        )
    )
    runtime_s = round(time.perf_counter() - started, 4)

    order = tuple(item.service for item in result.services)
    service_scores = {item.service: item.score for item in result.services}
    columns = tuple(item.column for item in result.indicators)
    column_scores = {item.column: item.self_score for item in result.indicators}
    rank_service = eval_metrics.rank_in_order(order, service_scores, case.gt_service)
    rank_column = eval_metrics.rank_in_order(columns, column_scores, case.gt_column)
    top1 = order[0] if order else ""
    group = eval_metrics.top_tie_group(order, service_scores)
    share = eval_metrics.symptom_share(group, case.gt_service, true_graph)
    chance = eval_metrics.symptom_chance(order, case.gt_service, true_graph)
    symptom = eval_metrics.symptom_error(top1 or None, case.gt_service, true_graph)

    row = {
        "run_id": "e6_synthetic",
        "dataset": "SYNTHETIC",
        "system": f"synthetic-{settings['n_services']}",
        "case_id": f"{fault}-{seed}",
        "fault_type": fault.upper(),
        "gt_service": case.gt_service,
        "gt_indicator": case.gt_column,
        "method": method,
        "delay_s": float(settings["delay_rows"]),
        "seed": seed,
        "rank_gt_service": _best(rank_service),
        "rank_gt_indicator": _best(rank_column),
        # Every synthetic fault has exactly one right column, so the loose score
        # is the strict one.
        "rank_gt_indicator_loose": _best(rank_column),
        "top1_service": top1,
        "top1_indicator": columns[0] if columns else "",
        "tied_gt_service": _tied(rank_service),
        "tied_gt_indicator": _tied(rank_column),
        "tied_gt_indicator_loose": _tied(rank_column),
        "symptom_error": "" if symptom is None else symptom,
        "tied_top1": len(group) if group else "",
        "symptom_share": "" if share is None else round(share, 6),
        "symptom_chance": "" if chance is None else round(chance, 6),
        "verdict": result.verdict,
        "runtime_s": runtime_s,
    }
    assert set(row) == set(CASES_CSV_COLUMNS)
    return {"factor": factor, "level": level, **row}


def grid(config: dict) -> list[tuple[str, object, dict]]:
    """Every (factor, level, settings) of the one-factor-at-a-time grid."""
    base = dict(config["base"])
    out = []
    for factor in FACTORS:
        for level in config["factors"][factor]:
            out.append((factor, level, {**base, factor: level}))
    return out


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, default=repo / "experiments" / "results")
    parser.add_argument("--seeds", type=int, help="override n_seeds, for a smoke run")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.seeds:
        config["n_seeds"] = args.seeds
    unknown = [m for m in config["methods"] if m not in ENGINES]
    if unknown:
        print(f"unknown methods: {unknown}", file=sys.stderr)
        return 2
    if set(config["factors"]) != set(FACTORS):
        print(f"factors must be exactly {FACTORS}", file=sys.stderr)
        return 2

    first_seed = int(config.get("seed", 42))
    seeds = range(first_seed, first_seed + int(config["n_seeds"]))
    jobs = [
        (method, fault, seed, factor, level, settings)
        for factor, level, settings in grid(config)
        for fault in FAULTS
        for method in config["methods"]
        for seed in seeds
    ]
    print(f"E6: {len(jobs)} runs ({len(grid(config))} settings x {len(FAULTS)} faults "
          f"x {len(config['methods'])} methods x {len(seeds)} seeds)")

    started = time.perf_counter()
    with parallel_config(backend="loky", inner_max_num_threads=1):
        rows = Parallel(n_jobs=int(config.get("n_jobs", -2)), verbose=2)(
            delayed(one_run)(m, f, s, factor, level, settings, config["windows"])
            for m, f, s, factor, level, settings in jobs
        )
    elapsed = time.perf_counter() - started
    print(f"finished in {elapsed:.0f} s")

    frame = pd.DataFrame(rows)
    frame["level"] = frame["level"].astype(str)
    frame["runtime_s"] = pd.to_numeric(frame["runtime_s"])
    out = args.results_root / str(config["run_id"])
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "cases.csv", index=False)

    # delay_s varies inside the delay factor only; summarise would split on it
    # anyway, so it is dropped and the level column carries it.
    plain = frame.drop(columns=["delay_s"])
    parts = []
    for factor in FACTORS:
        part = plain[plain["factor"] == factor]
        parts.append(summarise(part, by=["factor", "level"]))
        by_fault = summarise(part, by=["factor", "level", "fault_type"])
        parts.append(by_fault)
    summary = pd.concat(parts, ignore_index=True)
    summary["fault_type"] = summary["fault_type"].fillna("ALL")
    summary.to_csv(out / "summary.csv", index=False)

    saved = dict(config, elapsed_s=round(elapsed, 1), runs=len(jobs))
    (out / "config.yaml").write_text(yaml.safe_dump(saved, sort_keys=False), encoding="utf-8")
    print(f"written to {out}")
    headline = summary[(summary["fault_type"] == "ALL")]
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(headline[["factor", "level", "method", "ac1", "symptom_rate",
                        "symptom_chance", "no_clear_cause"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

