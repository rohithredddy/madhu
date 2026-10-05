"""E1: do standard anomaly explanations point at root causes, or at symptoms?

Task M3.1. This is contribution C1 and, as `docs/08` section 4 puts it, a paper
section on its own. It answers two of the project's research questions on real
failure data with real ground truth:

* **RQ1, grounding.** How often does a common detector-plus-explainer pair rank the
  true root-cause indicator in its top k? Reported as ExpAC@1, @3 and @5.
* **RQ2, symptom versus cause.** When an explanation is wrong, is it wrong in the
  particular way this project is about - blaming a service that *calls* the real
  culprit, and is therefore a victim of it? Reported as the symptom rate, over the
  wrong answers rather than over all of them.

The methods are the ones a practitioner would actually reach for, not ours. PARE is
deliberately absent: E1 measures common practice, and E2 (M4.1) is where the
proposed method is measured against it. Mixing them would turn a study of the
field into an advertisement.

    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py \
        --config experiments/configs/c1_re1_ob.yaml

Everything about a run comes from the YAML and is saved beside the results, so a
number in the paper can be traced to the configuration and the environment that
produced it (hard rule 10, and `docs/08` section 8).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from joblib import Parallel, delayed  # noqa: E402
from pare import eval_metrics  # noqa: E402
from pare.config import PareConfig  # noqa: E402
from pare.engine import ENGINES  # noqa: E402

from experiments.adapters.graphs import load_graph  # noqa: E402
from experiments.adapters.rcaeval import list_cases, summarise  # noqa: E402
from experiments.runner import (  # noqa: E402
    CaseRow,
    ranks_from,
    run_case,
    symptom_rate,
    write_run,
)

REQUIRED_KEYS = ("run_id", "dataset", "system", "methods", "delays_s")


def main(argv: Sequence[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="the YAML describing the run; saved next to the results",
    )
    parser.add_argument("--data-root", type=Path, default=repo_root / "data" / "RCAEval")
    parser.add_argument(
        "--results-root", type=Path, default=repo_root / "experiments" / "results"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="overrides the config, for a smoke run"
    )
    args = parser.parse_args(argv)

    config = _read_config(args.config)
    if args.limit is not None:
        config["limit"] = args.limit

    cases = list_cases(args.data_root, config["dataset"], config["system"])
    if config.get("limit"):
        cases = cases[: int(config["limit"])]
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2

    graph = load_graph(config["graph"]) if config.get("graph") else None
    log: list[str] = []

    def note(line: str) -> None:
        print(line)
        log.append(line)

    counts = summarise(cases)
    note(f"E1 grounding: {config['run_id']}")
    note(f"  {config['dataset']} {config['system']}, {counts['cases']} cases")
    note(f"  by fault type: {counts['by_fault']}")
    note(
        f"  {counts['unambiguous_indicator']} cases have an unambiguous "
        f"ground-truth indicator (CPU and MEM); the strict ExpAC@k uses those"
    )
    note(f"  methods: {', '.join(config['methods'])}")
    note(f"  delays: {config['delays_s']} s")
    note(
        f"  graph: {config.get('graph') or 'none'}"
        + (
            f", {len(graph.services)} services - used for scoring symptom_error, "
            f"never given to a baseline engine"
            if graph is not None
            else ""
        )
    )
    note(f"  normal window: {config.get('normal_mode', 'inject_gap')}")

    jobs = [
        (case, method, float(delay))
        for method in config["methods"]
        for delay in config["delays_s"]
        for case in cases
    ]
    note(f"\nrunning {len(jobs)} (case, method, delay) combinations")

    settings = PareConfig(seed=int(config.get("seed", 42)))
    started = time.perf_counter()
    rows: list[CaseRow] = Parallel(
        n_jobs=int(config.get("n_jobs", -2)), verbose=5, prefer="processes"
    )(
        delayed(run_case)(
            case=case,
            engine=method,
            run_id=config["run_id"],
            delay_s=delay,
            graph=graph,
            config=settings,
            normal_mode=config.get("normal_mode", "inject_gap"),
        )
        for case, method, delay in jobs
    )
    elapsed = time.perf_counter() - started
    note(f"finished in {elapsed:.1f} s")

    failures = [row for row in rows if row.error]
    if failures:
        note(f"\n{len(failures)} of {len(rows)} runs failed. First few:")
        for row in failures[:5]:
            note(f"  {row.method} on {row.case_id}: {row.error}")
        note("  all of them are in failures.csv")
    else:
        note("\nno failures")

    results_dir = args.results_root / str(config["run_id"])
    config_for_disk = dict(config)
    config_for_disk["elapsed_s"] = round(elapsed, 1)
    config_for_disk["cases"] = len(cases)
    config_for_disk["pare_version"] = _pare_version()

    frame = pd.DataFrame([row.contract_row() for row in rows])
    overall = _summarise(frame, by=None)
    by_fault = _summarise(frame, by="fault_type")

    report = "\n".join(
        [
            f"--- E1 grounding: {config['dataset']} {config['system']}, "
            f"delay {config['delays_s']} s ---",
            "",
            _format(overall, "method"),
            "",
            "--- by fault type ---",
            _format(by_fault, "method", "fault_type"),
            "",
            _legend(),
        ]
    )
    note("")
    note(report)

    write_run(rows, results_dir, config_for_disk, log)
    overall.to_csv(results_dir / "summary.csv", index=False)
    by_fault.to_csv(results_dir / "summary_by_fault.csv", index=False)
    (results_dir / "report.txt").write_text(report + "\n", encoding="utf-8")
    print(f"\nwrote {results_dir}")
    return 0


# --- the metrics E1 reports -------------------------------------------------


def _summarise(frame: pd.DataFrame, by: str | None) -> pd.DataFrame:
    """ExpAC@k for indicators, AC@k for services, and the symptom rate.

    `docs/08` section 4 asks for all three, broken down by system and fault type.
    One system runs at a time, so `by` is the fault type.
    """
    keys = ["method"] + ([by] if by else [])
    out: list[dict[str, object]] = []
    for values, group in frame.groupby(keys, sort=True):
        values = values if isinstance(values, tuple) else (values,)
        row: dict[str, object] = dict(zip(keys, values, strict=True))

        service = ranks_from(group, "rank_gt_service", "tied_gt_service")
        # The strict indicator score covers only the cases where "the right
        # metric" is not a judgement call - CPU and MEM. docs/08 section 4.
        strict_rows = group[group["gt_indicator"].astype(str) != ""]
        strict = ranks_from(strict_rows, "rank_gt_indicator", "tied_gt_indicator")
        loose = ranks_from(
            group, "rank_gt_indicator_loose", "tied_gt_indicator_loose"
        )

        row.update(
            cases=len(group),
            failed=int((group["verdict"].astype(str) == "").sum()),
            # RQ1, the headline: does the explanation name the right metric?
            exp_ac1=_round(eval_metrics.exp_ac_at_k(strict, 1)) if strict else "",
            exp_ac3=_round(eval_metrics.exp_ac_at_k(strict, 3)) if strict else "",
            exp_ac5=_round(eval_metrics.exp_ac_at_k(strict, 5)) if strict else "",
            strict_cases=len(strict_rows),
            # The looser reading, over every case. Only interpretable next to the
            # size of the acceptable set, which is why it is in the per-fault table.
            exp_ac1_loose=_round(eval_metrics.exp_ac_at_k(loose, 1)),
            exp_ac3_loose=_round(eval_metrics.exp_ac_at_k(loose, 3)),
            # The coarse question, for comparison: the right service, not the right
            # metric. The gap between this and exp_ac1 is one of E1's findings.
            ac1=_round(eval_metrics.ac_at_k(service, 1)),
            ac3=_round(eval_metrics.ac_at_k(service, 3)),
            avg5=_round(eval_metrics.avg_at_5(service)),
            # RQ2. `wrong_top1` counts the cases where the service the method
            # actually returned first is not the culprit, which is exactly the
            # denominator `symptom_rate` divides by. Deliberately not derived from
            # the tie-aware rank: a tie group starting at rank 1 has `best == 1`
            # while only counting as a partial hit for AC@1, so counting ranks here
            # would print "0 wrong" beside an AC@1 of 0.46 - which is how this was
            # first written and it read as a contradiction.
            wrong_top1=int((group["top1_service"] != group["gt_service"]).sum()),
            symptom_rate=_round(symptom_rate(group)),
            no_clear_cause=int((group["verdict"] == "NO_CLEAR_CAUSE").sum()),
            mean_ms=round(float(group["runtime_s"].mean() * 1000), 1),
        )
        if by == "fault_type":
            row["acceptable_indicators"] = _acceptable_count(group)
        out.append(row)
    return pd.DataFrame(out)


def _acceptable_count(group: pd.DataFrame) -> int:
    """How many metrics count as correct for this fault type.

    Printed beside the loose score because without it that score is not
    interpretable: 1 of 51 and 4 of 51 are different questions.
    """
    from experiments.adapters.rcaeval import INDICATOR_METRICS

    fault = str(group["fault_type"].iloc[0])
    return len(INDICATOR_METRICS.get(fault, ()))


def _round(value: float | None) -> object:
    return "" if value is None else round(float(value), 4)


def _format(frame: pd.DataFrame, *first: str) -> str:
    """Put the identifying columns first, then the metrics, and print it plainly."""
    ordered = list(first) + [c for c in frame.columns if c not in first]
    return frame[ordered].to_string(index=False)


def _legend() -> str:
    return "\n".join(
        [
            "ExpAC@k  : the ground-truth INDICATOR is in the top k explained "
            "features. RQ1.",
            "           Strict: only the CPU and MEM cases, where the right metric "
            "is not a",
            "           judgement call. This is the headline (docs/08 section 4).",
            "exp_ac*_loose : every case, counting any plausible metric for the fault "
            "type as",
            "           correct. Read it only next to acceptable_indicators in the "
            "per-fault",
            "           table; pooled across fault types it means nothing.",
            "AC@k     : the ground-truth SERVICE is in the top k. The coarse "
            "question.",
            "symptom_rate : of the WRONG top-1 answers, the share that blamed a "
            "service which",
            "           calls the real culprit - so it was a victim, not the cause. "
            "RQ2.",
            "           Empty when nothing was wrong or no graph was available.",
            "wrong_top1 : cases where the service the method returned first is not "
            "the culprit.",
            "           This is symptom_rate's denominator. It can exceed "
            "(1 - AC@1) x cases",
            "           for a method that ties, since a tie at rank 1 is scored as a "
            "part hit.",
            "no_clear_cause : NOT comparable between methods. The rule is a fixed "
            "threshold on",
            "           the rank-1 score (min_cause_score, 3.0), and these methods "
            "do not share",
            "           a scale - SHAP_IFOREST reports mean absolute SHAP, which is "
            "almost never",
            "           above 3, so it reads NO_CLEAR_CAUSE on nearly every case "
            "while still",
            "           ranking well. Read it per method, never across them.",
        ]
    )


# --- configuration ----------------------------------------------------------


def _read_config(path: Path) -> dict:
    """Read the YAML and refuse anything that would produce a misleading run."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path} should hold a mapping, got {type(config).__name__}")

    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"{path} is missing {missing}")

    unknown = [method for method in config["methods"] if method not in ENGINES]
    if unknown:
        raise ValueError(
            f"{path} asks for engines that do not exist: {unknown}; "
            f"known: {sorted(ENGINES)}"
        )
    if not config["methods"]:
        raise ValueError(f"{path} lists no methods")
    if not config["delays_s"]:
        raise ValueError(f"{path} lists no delays")

    mode = config.get("normal_mode", "inject_gap")
    if mode not in ("inject_gap", "alarm_lookback"):
        raise ValueError(
            f"{path} normal_mode must be 'inject_gap' or 'alarm_lookback', got {mode!r}"
        )
    return config


def _pare_version() -> str:
    from pare import __version__

    return __version__


if __name__ == "__main__":
    raise SystemExit(main())
