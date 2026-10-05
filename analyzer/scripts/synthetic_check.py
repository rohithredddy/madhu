"""The M1 gate: does the method actually beat its own ablation?

`docs/07_TASKS.md` M1 is allowed to finish only if this script shows

    PARE top-1 accuracy >= PARE_NO_RESIDUAL top-1 accuracy

and PARE's top-1 accuracy on latency faults is at least 0.85. The task says
plainly: if that fails, stop and report, do not tune the test to pass. So this
script reports; it does not decide anything for us.

One thing it does that the task line does not ask for, because without it the
gate is empty: **it sweeps amplification.** With purely linear propagation a
caller can never outscore the service that broke, so every engine finds the
culprit and PARE ties its own ablation at 1.00. The comparison only means
something where the symptom trap exists. The gate is therefore checked at every
amplification setting, and the run at 0 is kept as the control that shows the two
are identical when there is nothing to tell apart.

Run it from the analyzer directory:

    python scripts/synthetic_check.py                  # the full grid
    python scripts/synthetic_check.py --quick          # 10 seeds, fast engines
    python scripts/synthetic_check.py --engines PARE PARE_NO_RESIDUAL

Results are written under ``experiments/results/synthetic_check/`` together with
the settings that produced them, so a number can always be traced back (hard
rules 2 and 10).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pare import __version__
from pare.config import PareConfig
from pare.engine import ENGINES, AnalyzeRequest, Window, analyze
from pare.eval_metrics import (
    ac_at_k,
    avg_at_5,
    rank_in_order,
    symptom_error,
    symptom_rate,
)
from pare.graph import CallGraph
from pare.synthetic import FAULTS, make_case

# The two engines the gate compares. Named here so the check cannot drift from
# the claim it is testing.
GATE_METHOD = "PARE"
GATE_ABLATION = "PARE_NO_RESIDUAL"

# Amplification 0 is the control: no symptom trap, so nothing to tell apart.
# 0.25 is where the trap exists and the residual still recovers the culprit.
DEFAULT_AMPLIFICATIONS = (0.0, 0.25)

FAST_ENGINES = ("PARE", "PARE_NO_RESIDUAL", "PARE_NO_CP", "NSIGMA", "ECDF", "PCA_RECON")


@dataclass(frozen=True)
class CaseResult:
    """What one engine did on one case."""

    engine: str
    fault: str
    amplification: float
    seed: int
    gt_service: str
    gt_column: str
    top1_service: str | None
    top1_indicator: str | None
    rank_gt_service: int | None
    tied_gt_service: int | None
    rank_gt_indicator: int | None
    tied_gt_indicator: int | None
    symptom_error: bool | None
    verdict: str
    took_ms: int


def one_case(
    engine: str,
    fault: str,
    amplification: float,
    seed: int,
    n_services: int,
    n_normal: int,
    n_abnormal: int,
    propagation: float,
    delay_s: float,
) -> CaseResult:
    """Build a case, run one engine on it, and score the answer.

    Ground truth is used only after the engine has returned - it is never part of
    the request (hard rule 4).
    """
    case = make_case(
        n_services=n_services,
        n_normal=n_normal,
        n_abnormal=n_abnormal,
        fault=fault,
        propagation=propagation,
        amplification=amplification,
        seed=seed,
    )
    frame = case.to_frame()
    recent = frame.iloc[n_normal:]
    graph = CallGraph.from_edges(case.edges, source="SYNTHETIC_TRUE")

    result = analyze(
        AnalyzeRequest(
            engine=engine,
            alarm_time_sec=case.inject_time_sec + delay_s,
            columns=case.columns,
            normal=Window.of(
                case.normal.index.to_numpy(dtype=float), case.normal.to_numpy()
            ),
            recent=Window.of(recent.index.to_numpy(dtype=float), recent.to_numpy()),
            graph=graph,
            # top_k is raised so the indicator rank can be measured properly
            # rather than being cut off at the default ten.
            config=PareConfig(top_k=10_000),
        )
    )

    service_scores = {item.service: item.score for item in result.services}
    indicator_scores = {item.column: item.self_score for item in result.indicators}

    # Ranked by the order the engine returned, not by re-sorting its scores:
    # PARE's traversal promotes the service the graph walk ends at, and judging it
    # on scores alone would mark it wrong precisely when the traversal worked.
    service_rank = rank_in_order(
        [item.service for item in result.services], service_scores, case.gt_service
    )
    indicator_rank = rank_in_order(
        [item.column for item in result.indicators], indicator_scores, case.gt_column
    )
    top1 = result.services[0].service if result.services else None

    return CaseResult(
        engine=engine,
        fault=fault,
        amplification=amplification,
        seed=seed,
        gt_service=case.gt_service,
        gt_column=case.gt_column,
        top1_service=top1,
        top1_indicator=result.indicators[0].column if result.indicators else None,
        rank_gt_service=service_rank.best if service_rank else None,
        tied_gt_service=service_rank.tied if service_rank else None,
        rank_gt_indicator=indicator_rank.best if indicator_rank else None,
        tied_gt_indicator=indicator_rank.tied if indicator_rank else None,
        symptom_error=symptom_error(top1, case.gt_service, graph),
        verdict=result.verdict,
        took_ms=result.took_ms,
    )


def read_cases(path: Path) -> list[CaseResult]:
    """Load a previous run's per-case rows back from disk.

    Everything arrives from CSV as text, so each field is put back into the type
    the summary expects; an empty cell means the value was absent, not zero.
    """
    def number(value: str, cast):
        return None if value == "" else cast(value)

    def flag(value: str):
        return None if value == "" else value == "True"

    with open(path, newline="", encoding="utf-8") as handle:
        return [
            CaseResult(
                engine=row["engine"],
                fault=row["fault"],
                amplification=float(row["amplification"]),
                seed=int(row["seed"]),
                gt_service=row["gt_service"],
                gt_column=row["gt_column"],
                top1_service=row["top1_service"] or None,
                top1_indicator=row["top1_indicator"] or None,
                rank_gt_service=number(row["rank_gt_service"], int),
                tied_gt_service=number(row["tied_gt_service"], int),
                rank_gt_indicator=number(row["rank_gt_indicator"], int),
                tied_gt_indicator=number(row["tied_gt_indicator"], int),
                symptom_error=flag(row["symptom_error"]),
                verdict=row["verdict"],
                took_ms=int(row["took_ms"]),
            )
            for row in csv.DictReader(handle)
        ]


def summarise(results: list[CaseResult]) -> list[dict[str, object]]:
    """Accuracy per engine, fault type and amplification.

    Ranks carry their tie sizes, so a method that cannot separate its top columns
    is scored on the chance of being right rather than on alphabetical luck. See
    ``docs/08_EXPERIMENTS_SPEC.md`` section 4.
    """
    from pare.eval_metrics import Rank

    groups: dict[tuple[str, str, float], list[CaseResult]] = {}
    for item in results:
        groups.setdefault((item.engine, item.fault, item.amplification), []).append(item)

    rows: list[dict[str, object]] = []
    for (engine, fault, amplification), items in sorted(groups.items()):
        service_ranks = [
            None if item.rank_gt_service is None
            else Rank(item.rank_gt_service, item.tied_gt_service or 1)
            for item in items
        ]
        indicator_ranks = [
            None if item.rank_gt_indicator is None
            else Rank(item.rank_gt_indicator, item.tied_gt_indicator or 1)
            for item in items
        ]
        # The denominator is the wrong answers only, so the correctness of each
        # top-1 has to be supplied: `symptom_error` is False both for a right
        # answer and for one that is wrong in an unrelated way.
        rate = symptom_rate(
            [item.symptom_error for item in items],
            [item.top1_service == item.gt_service for item in items],
        )

        rows.append(
            {
                "engine": engine,
                "fault": fault,
                "amplification": amplification,
                "cases": len(items),
                "ac1": round(ac_at_k(service_ranks, 1), 4),
                "ac3": round(ac_at_k(service_ranks, 3), 4),
                "avg5": round(avg_at_5(service_ranks), 4),
                "exp_ac1": round(ac_at_k(indicator_ranks, 1), 4),
                "exp_ac3": round(ac_at_k(indicator_ranks, 3), 4),
                "symptom_rate": "" if rate is None else round(rate, 4),
                "no_clear_cause": sum(
                    1 for item in items if item.verdict == "NO_CLEAR_CAUSE"
                ),
                "mean_ms": int(round(float(np.mean([item.took_ms for item in items])))),
            }
        )
    return rows


def check_the_gate(rows: list[dict[str, object]]) -> tuple[bool, list[str]]:
    """Apply the two conditions M1 is allowed to finish on.

    Returns whether it passed and the lines to print either way. Deliberately
    says nothing about *why* a failure happened: that is for a human to look into,
    and a script that explains away its own failures is worse than useless.
    """
    lines: list[str] = []
    passed = True

    by_key = {(row["engine"], row["fault"], row["amplification"]): row for row in rows}
    faults = sorted({row["fault"] for row in rows})
    amplifications = sorted({row["amplification"] for row in rows})

    lines.append(f"Condition 1: {GATE_METHOD} top-1 >= {GATE_ABLATION} top-1, everywhere")
    for amplification in amplifications:
        for fault in faults:
            method = by_key.get((GATE_METHOD, fault, amplification))
            ablation = by_key.get((GATE_ABLATION, fault, amplification))
            if method is None or ablation is None:
                continue
            gap = float(method["ac1"]) - float(ablation["ac1"])
            ok = gap >= 0
            passed = passed and ok
            lines.append(
                f"  amp {amplification:<5} {fault:<8} "
                f"{GATE_METHOD} {method['ac1']:.2f} vs {ablation['ac1']:.2f}  "
                f"gap {gap:+.2f}  {'ok' if ok else 'FAILED'}"
            )

    lines.append("")
    lines.append(f"Condition 2: {GATE_METHOD} top-1 on latency faults >= 0.85")
    for amplification in amplifications:
        row = by_key.get((GATE_METHOD, "latency", amplification))
        if row is None:
            continue
        ok = float(row["ac1"]) >= 0.85
        passed = passed and ok
        lines.append(
            f"  amp {amplification:<5} latency  {row['ac1']:.2f}  {'ok' if ok else 'FAILED'}"
        )

    return passed, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=50)
    parser.add_argument("--n-services", type=int, default=8)
    parser.add_argument("--n-normal", type=int, default=400)
    parser.add_argument("--n-abnormal", type=int, default=200)
    parser.add_argument("--propagation", type=float, default=0.9)
    parser.add_argument("--delay-s", type=float, default=30.0)
    parser.add_argument(
        "--amplifications", type=float, nargs="+", default=list(DEFAULT_AMPLIFICATIONS)
    )
    parser.add_argument("--faults", nargs="+", default=list(FAULTS))
    parser.add_argument("--engines", nargs="+", default=sorted(ENGINES))
    parser.add_argument(
        "--quick",
        action="store_true",
        help="10 seeds and only the fast engines, for a sanity check during development",
    )
    parser.add_argument("--jobs", type=int, default=-2, help="joblib n_jobs; 1 to disable")
    parser.add_argument(
        "--append",
        action="store_true",
        help="keep the per-case rows already in --out for engines not being run now, "
        "and re-summarise everything together. Lets the grid be built in pieces, "
        "which matters because SHAP_IFOREST and PARE_LGBM take minutes per setting.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "experiments"
        / "results"
        / "synthetic_check",
    )
    args = parser.parse_args()

    if args.quick:
        args.seeds = 10
        args.engines = list(FAST_ENGINES)

    unknown = sorted(set(args.engines) - set(ENGINES))
    if unknown:
        parser.error(f"unknown engines {unknown}; available: {sorted(ENGINES)}")

    jobs = [
        (engine, fault, amplification, seed)
        for engine in args.engines
        for fault in args.faults
        for amplification in args.amplifications
        for seed in range(args.seeds)
    ]

    print(
        f"{len(jobs)} runs: {len(args.engines)} engines x {len(args.faults)} faults x "
        f"{len(args.amplifications)} amplifications x {args.seeds} seeds"
    )
    started = time.perf_counter()

    def work(job):
        engine, fault, amplification, seed = job
        return one_case(
            engine,
            fault,
            amplification,
            seed,
            args.n_services,
            args.n_normal,
            args.n_abnormal,
            args.propagation,
            args.delay_s,
        )

    if args.jobs == 1:
        results = [work(job) for job in jobs]
    else:
        from joblib import Parallel, delayed

        results = Parallel(n_jobs=args.jobs, verbose=1)(
            delayed(work)(job) for job in jobs
        )

    elapsed = time.perf_counter() - started
    results = list(results)

    carried = 0
    if args.append and (args.out / "cases.csv").exists():
        # Keep rows for engines this run did not touch; anything re-run is
        # replaced, so running the same engine twice refreshes rather than
        # duplicates it.
        just_run = set(args.engines)
        previous = [
            item for item in read_cases(args.out / "cases.csv")
            if item.engine not in just_run
        ]
        carried = len(previous)
        results = previous + results
        print(f"carried {carried} rows forward for "
              f"{len(sorted({item.engine for item in previous}))} other engine(s)")

    rows = summarise(results)

    # --- write everything down before printing anything ---
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "summary.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with open(args.out / "cases.csv", "w", newline="", encoding="utf-8") as handle:
        fields = list(CaseResult.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow({field: getattr(item, field) for field in fields})

    passed, lines = check_the_gate(rows)

    (args.out / "config.json").write_text(
        json.dumps(
            {
                "seeds": args.seeds,
                "n_services": args.n_services,
                "n_normal": args.n_normal,
                "n_abnormal": args.n_abnormal,
                "propagation": args.propagation,
                "delay_s": args.delay_s,
                "amplifications": args.amplifications,
                "faults": args.faults,
                "engines": args.engines,
                "pare_version": __version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "elapsed_s": round(elapsed, 1),
                "gate_passed": passed,
                "engines_run_this_time": args.engines,
                "rows_carried_forward": carried,
                "engines_in_file": sorted({item.engine for item in results}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- print ---
    print()
    print(f"{'engine':<17}{'fault':<9}{'amp':<6}{'AC@1':<7}{'Avg@5':<7}"
          f"{'ExpAC@1':<9}{'symptom':<9}{'ms':<7}")
    for row in rows:
        print(
            f"{row['engine']:<17}{row['fault']:<9}{row['amplification']:<6}"
            f"{row['ac1']:<7.2f}{row['avg5']:<7.2f}{row['exp_ac1']:<9.2f}"
            f"{str(row['symptom_rate']):<9}{row['mean_ms']:<7}"
        )

    print()
    print("=" * 72)
    for line in lines:
        print(line)
    print("=" * 72)
    print("M1 GATE: PASSED" if passed else "M1 GATE: FAILED - stop and report, do not tune")
    print(f"wrote {args.out}")
    print(f"took {elapsed:.0f} s")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
