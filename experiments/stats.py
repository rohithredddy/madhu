"""The statistics behind every "A beats B" in the paper (`docs/08` section 5).

Task M4.4. Three tools, each a small pure function, and one script that applies
them to finished runs:

* **Paired comparison** of a reference method (PARE) against each other method on
  the same cases: the Wilcoxon signed-rank test on per-case reciprocal rank, with
  Cliff's delta as the effect size. Reciprocal rank rather than hit/miss because
  it uses the whole ranking: being second counts for more than being tenth.
* **Holm correction** across the comparisons, because testing PARE against ten
  methods and reporting the smallest p-value would overstate every one of them.
* **95% bootstrap confidence intervals** (1000 resamples of cases, seed 42) for
  AC@1, Avg@5 and ExpAC@1, so a table can say how much a number could move with a
  different draw of failures.

Ties are handled as everywhere else (`docs/08` section 4): a tie group's
reciprocal rank is the average over the positions it occupies, the expected value
if the tie were shuffled.

    analyzer/.venv/Scripts/python.exe experiments/stats.py \\
        --runs e2_re1 e2_rcaeval_re1 --reference PARE --out e2_re1
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare.eval_metrics import Rank  # noqa: E402

from experiments.runner import ranks_from  # noqa: E402

SEED = 42
RESAMPLES = 1000


# --- per-case quantities ----------------------------------------------------


def reciprocal_rank(rank: Rank | None) -> float:
    """1 / rank, averaged over a tie group's positions; 0 when never ranked."""
    if rank is None:
        return 0.0
    positions = np.arange(rank.best, rank.best + rank.tied, dtype=float)
    return float(np.mean(1.0 / positions))


def avg5_per_case(rank: Rank | None) -> float:
    """One case's contribution to Avg@5: the mean of its AC@1 .. AC@5 hits."""
    if rank is None:
        return 0.0
    return float(np.mean([rank.hit_fraction(k) for k in range(1, 6)]))


# --- the tests --------------------------------------------------------------


def cliffs_delta(x: Sequence[float], y: Sequence[float]) -> float:
    """P(x > y) - P(x < y) over all pairs. +1: x always larger; 0: no tendency.

    Conventional reading (Romano et al. 2006): |d| < 0.147 negligible, < 0.33
    small, < 0.474 medium, otherwise large.
    """
    a = np.asarray(x, dtype=float)[:, None]
    b = np.asarray(y, dtype=float)[None, :]
    if a.size == 0 or b.size == 0:
        return 0.0
    return float((np.sum(a > b) - np.sum(a < b)) / (a.size * b.size))


def effect_label(delta: float) -> str:
    size = abs(delta)
    if size < 0.147:
        return "negligible"
    if size < 0.33:
        return "small"
    if size < 0.474:
        return "medium"
    return "large"


def paired_wilcoxon(x: Sequence[float], y: Sequence[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value for paired samples.

    Zero differences are dropped (scipy's default `zero_method="wilcox"`), so two
    methods that agree on most cases are compared on the cases where they differ.
    When they never differ there is nothing to test and the answer is p = 1,
    returned directly rather than through scipy's divide-by-zero warning.
    """
    difference = np.asarray(x, dtype=float) - np.asarray(y, dtype=float)
    if not np.any(difference != 0):
        return 1.0
    return float(wilcoxon(x, y).pvalue)


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order.

    Sort ascending, multiply the i-th smallest (0-based) by (m - i), keep the
    sequence non-decreasing, cap at 1.
    """
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for position, index in enumerate(order):
        running = max(running, min(1.0, (m - position) * p[index]))
        adjusted[index] = running
    return adjusted.tolist()


def bootstrap_ci(
    values: Sequence[float], seed: int = SEED, resamples: int = RESAMPLES
) -> tuple[float, float]:
    """95% percentile interval for the mean, resampling cases with replacement."""
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, data.size, size=(resamples, data.size))].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return (float(low), float(high))


# --- applying them to runs --------------------------------------------------


def per_case_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """The per-case quantities the tests and intervals need, one row per case."""
    service = ranks_from(frame, "rank_gt_service", "tied_gt_service")
    strict = ranks_from(frame, "rank_gt_indicator", "tied_gt_indicator")
    has_strict = frame["gt_indicator"].astype(str) != ""
    return pd.DataFrame(
        {
            "method": frame["method"].to_numpy(),
            "delay_s": frame["delay_s"].astype(float).to_numpy(),
            "system": frame["system"].to_numpy(),
            "case_id": frame["case_id"].to_numpy(),
            "rr": [reciprocal_rank(rank) for rank in service],
            "ac1": [0.0 if r is None else r.hit_fraction(1) for r in service],
            "avg5": [avg5_per_case(rank) for rank in service],
            "exp_ac1": [
                (0.0 if r is None else r.hit_fraction(1)) if strict_case else np.nan
                for r, strict_case in zip(strict, has_strict, strict=True)
            ],
        }
    )


def compare(cases: pd.DataFrame, reference: str) -> pd.DataFrame:
    """The reference method against every other, per delay, Holm-corrected per delay."""
    rows: list[dict[str, object]] = []
    for delay, at_delay in cases.groupby("delay_s"):
        ref = at_delay[at_delay["method"] == reference].set_index("case_id")["rr"]
        if ref.empty:
            continue
        block: list[dict[str, object]] = []
        for method, part in at_delay.groupby("method"):
            if method == reference:
                continue
            other = part.set_index("case_id")["rr"]
            shared = ref.index.intersection(other.index)
            x, y = ref.loc[shared].to_numpy(), other.loc[shared].to_numpy()
            delta = cliffs_delta(x, y)
            block.append(
                {
                    "delay_s": delay,
                    "reference": reference,
                    "method": method,
                    "cases": len(shared),
                    "mrr_reference": round(float(x.mean()), 4),
                    "mrr_method": round(float(y.mean()), 4),
                    "reference_better": int(np.sum(x > y)),
                    "method_better": int(np.sum(x < y)),
                    "p_wilcoxon": paired_wilcoxon(x, y),
                    "cliffs_delta": round(delta, 4),
                    "effect": effect_label(delta),
                }
            )
        for row, adjusted in zip(block, holm([r["p_wilcoxon"] for r in block]), strict=True):
            row["p_holm"] = adjusted
            row["significant_0_05"] = adjusted < 0.05
        rows.extend(block)
    return pd.DataFrame(rows)


def intervals(cases: pd.DataFrame) -> pd.DataFrame:
    """Point estimates and 95% bootstrap intervals per method and delay."""
    rows: list[dict[str, object]] = []
    for (method, delay), part in cases.groupby(["method", "delay_s"]):
        row: dict[str, object] = {"method": method, "delay_s": delay, "cases": len(part)}
        for metric in ("ac1", "avg5", "exp_ac1"):
            values = part[metric].dropna().to_numpy()
            low, high = bootstrap_ci(values)
            row[metric] = round(float(values.mean()), 4) if values.size else np.nan
            row[f"{metric}_low"] = round(low, 4)
            row[f"{metric}_high"] = round(high, 4)
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv: Sequence[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True,
                        help="run folders under experiments/results whose cases.csv to join")
    parser.add_argument("--reference", default="PARE")
    parser.add_argument("--out", required=True, help="run folder to write stats into")
    parser.add_argument("--results-root", type=Path, default=repo / "experiments" / "results")
    args = parser.parse_args(argv)

    frames = [
        pd.read_csv(args.results_root / run / "cases.csv", keep_default_na=False)
        for run in args.runs
    ]
    frame = pd.concat(frames, ignore_index=True)
    cases = per_case_frame(frame)

    comparison = compare(cases, args.reference)
    cis = intervals(cases)
    out = args.results_root / args.out
    out.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out / "stats_comparison.csv", index=False)
    cis.to_csv(out / "stats_intervals.csv", index=False)
    print(comparison.to_string(index=False))
    print()
    print(cis.to_string(index=False))
    print(f"\nwrote {out / 'stats_comparison.csv'} and {out / 'stats_intervals.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
