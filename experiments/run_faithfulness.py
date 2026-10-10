"""E5: is an explanation faithful, compact and stable? (M11.1, docs/08 section 4).

For every case and method, at delay 0:

* **Faithfulness (deletion test).** Replace the method's top k columns (k = 0..10)
  with their normal medians and recompute the system anomaly score (mean over the
  window of the largest robust z). A faithful explanation makes the anomaly vanish
  fast: small normalised area under the curve. Compared with the average of 10
  random column orders on the same case.
* **Compactness.** How many indicators carry 80% of the method's positive score.
* **Stability.** The same case with the alarm moved 10 s earlier and 10 s later:
  Jaccard overlap of the top-5 indicators with the unshifted answer, and Kendall
  tau of the service ranking. docs/08 also asks for 5 seeds x 3 normal-window
  subsamples; that is 45 runs per case and method, so this run keeps only the
  window shifts, which are what a late or early detector actually changes.

The deletion window is the same for every method - the alarm to ``window_len_s``
after it - so the areas are comparable.

    analyzer/.venv/Scripts/python.exe experiments/run_faithfulness.py --out e5_re1
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
from pare.engine import analyze  # noqa: E402

from experiments.adapters.graphs import load_graph  # noqa: E402
from experiments.adapters.rcaeval import list_cases, load_case  # noqa: E402
from experiments.runner import _request_for  # noqa: E402

METHODS = ["PARE", "PARE_NO_RESIDUAL", "NSIGMA", "SHAP_IFOREST", "PCA_RECON", "ECDF"]
SYSTEMS = ["online-boutique", "sock-shop"]
SHIFTS_S = (-10.0, 10.0)
MAX_K = 10


def one_case(case, method: str, graph) -> tuple[list[dict], dict]:
    """Deletion curve rows and one summary row for one case and method."""
    settings = PareConfig(top_k=10_000)
    data = load_case(case, delay_s=0.0, graph=graph)
    result = analyze(_request_for(data, method, settings))
    names = [c.name for c in data.columns]
    ranking = [item.column for item in result.indicators]

    times = data.recent["time"].to_numpy(dtype=float)
    window = (times >= data.alarm_time_sec) & (times <= data.alarm_time_sec + settings.window_len_s)
    normal = data.normal[names].to_numpy(dtype=float)
    abnormal = data.recent[names].to_numpy(dtype=float)[window]

    curve = eval_metrics.deletion_faithfulness(normal, abnormal, data.columns, ranking, MAX_K)
    chance = eval_metrics.random_deletion_baseline(normal, abnormal, data.columns, MAX_K)
    scores = {item.column: max(item.self_score, 0.0) for item in result.indicators}

    jaccards, taus = [], []
    top5 = ranking[:5]
    services = [item.service for item in result.services]
    for shift in SHIFTS_S:
        moved = analyze(_request_for(load_case(case, delay_s=shift, graph=graph), method,
                                     settings))
        jaccards.append(eval_metrics.topk_jaccard(top5, [i.column for i in moved.indicators], 5))
        tau = eval_metrics.kendall_tau(services, [i.service for i in moved.services])
        if tau is not None:
            taus.append(tau)

    curve_rows = [
        {"case_id": case.case_id, "system": case.system, "method": method, "k": k,
         "normalised_score": round(value, 6)}
        for k, value in enumerate(curve.normalised)
    ]
    summary = {
        "case_id": case.case_id, "system": case.system, "fault_type": case.fault_type,
        "method": method, "deletion_auc": round(curve.auc, 6),
        "random_auc": round(chance, 6),
        "compactness": eval_metrics.compactness(scores) if any(scores.values()) else "",
        "jaccard_top5": round(float(np.mean(jaccards)), 6),
        "kendall_tau": round(float(np.mean(taus)), 6) if taus else "",
    }
    return curve_rows, summary


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="e5_re1")
    parser.add_argument("--limit", type=int, help="cases per system, for a smoke run")
    parser.add_argument("--results-root", type=Path, default=repo / "experiments" / "results")
    args = parser.parse_args()

    jobs = []
    for system in SYSTEMS:
        graph = load_graph(system)
        cases = list_cases(repo / "data" / "RCAEval", "RE1", system)[: args.limit]
        jobs += [(case, method, graph) for case in cases for method in METHODS]
    print(f"E5: {len(jobs)} (case, method) pairs, each run 3 times (shifts -10, 0, +10 s)")

    started = time.perf_counter()
    with parallel_config(backend="loky", inner_max_num_threads=1):
        results = Parallel(n_jobs=-2, verbose=2)(delayed(one_case)(*job) for job in jobs)
    elapsed = time.perf_counter() - started

    curves = pd.DataFrame([row for rows, _ in results for row in rows])
    per_case = pd.DataFrame([summary for _, summary in results])
    for column in ("compactness", "kendall_tau"):
        per_case[column] = pd.to_numeric(per_case[column], errors="coerce")
    summary = per_case.groupby("method").agg(
        cases=("case_id", "size"),
        deletion_auc=("deletion_auc", "mean"),
        random_auc=("random_auc", "mean"),
        beats_random=("deletion_auc", lambda s: float(
            (s < per_case.loc[s.index, "random_auc"]).mean())),
        compactness_median=("compactness", "median"),
        jaccard_top5=("jaccard_top5", "mean"),
        kendall_tau=("kendall_tau", "mean"),
    ).round(4).reset_index()

    out = args.results_root / args.out
    out.mkdir(parents=True, exist_ok=True)
    curves.to_csv(out / "faithfulness.csv", index=False)
    per_case.to_csv(out / "stability.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    config = {"methods": METHODS, "systems": SYSTEMS, "dataset": "RE1", "delay_s": 0.0,
              "shifts_s": list(SHIFTS_S), "max_k": MAX_K, "random_orders": 10, "seed": 42,
              "limit": args.limit, "elapsed_s": round(elapsed, 1)}
    (out / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"written to {out} in {elapsed:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
