"""The shared machinery of every experiment that runs engines over RCAEval cases.

E1 (`run_c1_grounding.py`) and E2/E3 (`run_rca.py`) do the same four things: read a
YAML configuration, run engines over cases in parallel, summarise the per-case
rows into the metrics `docs/08` section 4 asks for, and pool finished per-system
runs into one population. They differ only in which engines, delays and windows a
configuration names, and in the title on the report. So the machinery lives here
once, and the scripts are a few lines each.

The per-case row itself is produced by `runner.py`; this module never scores a
case, it only summarises rows that the runner wrote. Moved here from
`run_c1_grounding.py` in M4.1 (decision 82) without changing any metric.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import yaml
from joblib import Parallel, delayed, parallel_config
from pare import eval_metrics
from pare.config import PareConfig
from pare.engine import ENGINES

from experiments.adapters.graphs import load_graph
from experiments.adapters.rcaeval import list_cases
from experiments.adapters.rcaeval import summarise as summarise_cases
from experiments.runner import (
    CaseRow,
    environment_report,
    ranks_from,
    run_case,
    symptom_rate,
    symptom_rate_chance,
    write_run,
    wrong_probabilities,
)

REQUIRED_KEYS = ("run_id", "dataset", "system", "methods", "delays_s")


def run_from_command_line(
    argv: Sequence[str] | None, title: str, description: str | None = None
) -> int:
    """The whole of an experiment script: read the config, run or pool, write."""
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=description)
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
    parser.add_argument(
        "--rerun-methods",
        nargs="+",
        default=None,
        help=(
            "re-run only these methods of an existing run and replace their rows, "
            "keeping every other method's rows as they were; for when a change to "
            "one engine leaves the others untouched (decision 84)"
        ),
    )
    args = parser.parse_args(argv)

    config = read_config(args.config)
    if "combine_runs" in config:
        return combine(config, args.results_root, title)
    if args.limit is not None:
        config["limit"] = args.limit

    cases = list_cases(args.data_root, config["dataset"], config["system"])
    if config.get("limit"):
        cases = cases[: int(config["limit"])]
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2

    graph = load_graph(config["graph"]) if config.get("graph") else None
    # E4 only: what the engine is told, when it differs from the scoring graph.
    # A graph file's name, or CORRELATION / NONE (runner.run_case).
    told = config.get("engine_graph")
    engine_graph = (
        load_graph(told) if told and told not in ("CORRELATION", "NONE") else told
    )
    log: list[str] = []

    def note(line: str) -> None:
        print(line)
        log.append(line)

    counts = summarise_cases(cases)
    note(f"{title}: {config['run_id']}")
    note(f"  {config['dataset']} {config['system']}, {counts['cases']} cases")
    note(f"  by fault type: {counts['by_fault']}")
    note(
        f"  {counts['unambiguous_indicator']} cases have an unambiguous "
        f"ground-truth indicator (CPU, MEM, and SOCKET on RE2); the strict "
        f"ExpAC@k uses those"
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
    if told:
        note(f"  graph given to the engines: {told} (scoring still uses the graph above)")
    note(f"  normal window: {config.get('normal_mode', 'inject_gap')}")

    methods = list(config["methods"])
    kept: list[CaseRow] = []
    if args.rerun_methods:
        unknown = [m for m in args.rerun_methods if m not in methods]
        if unknown:
            print(f"--rerun-methods names methods not in this run: {unknown}", file=sys.stderr)
            return 2
        kept = _rows_to_keep(args.results_root / str(config["run_id"]), args.rerun_methods)
        methods = list(args.rerun_methods)
        note(f"  re-running only {methods}; keeping {len(kept)} rows of the others")

    jobs = [
        (case, method, float(delay))
        for method in methods
        for delay in config["delays_s"]
        for case in cases
    ]
    note(f"\nrunning {len(jobs)} (case, method, delay) combinations")

    settings = PareConfig(seed=int(config.get("seed", 42)))
    started = time.perf_counter()
    # One native thread per worker. The cases already run in parallel, and a
    # library that also spreads itself over every core (LightGBM does, for
    # PARE_LGBM) multiplies the threads by the workers: measured at 20 s a case
    # that way. It changes how fast a case runs, not what it returns.
    with parallel_config(backend="loky", inner_max_num_threads=1):
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
                engine_graph=engine_graph,
            )
            for case, method, delay in jobs
        )
    elapsed = time.perf_counter() - started
    note(f"finished in {elapsed:.1f} s")
    rows = kept + list(rows)

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
    config_for_disk["pare_version"] = pare_version()
    if args.rerun_methods:
        # Say in the saved config which rows are newer than the rest.
        config_for_disk["rerun_methods"] = list(args.rerun_methods)
        config_for_disk["elapsed_s_of_rerun"] = config_for_disk.pop("elapsed_s")

    frame = pd.DataFrame([row.contract_row() for row in rows])
    frame["runtime_s"] = pd.to_numeric(frame["runtime_s"])
    overall = summarise(frame, by=None)
    by_fault = summarise(frame, by="fault_type")

    report = "\n".join(
        [
            f"--- {title}: {config['dataset']} {config['system']}, "
            f"delay {config['delays_s']} s ---",
            "",
            format_table(overall, "method"),
            "",
            "--- by fault type ---",
            format_table(by_fault, "method", "fault_type"),
            "",
            legend(),
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


def _rows_to_keep(results_dir: Path, rerun: Sequence[str]) -> list[CaseRow]:
    """The rows of an earlier run that a partial re-run leaves alone.

    Read back from its cases.csv (and failures.csv, so a kept failure stays a
    failure rather than turning into a silent gap). Values stay as written; the
    summaries parse what they need.
    """
    cases_file = results_dir / "cases.csv"
    if not cases_file.exists():
        raise FileNotFoundError(f"{cases_file} does not exist; run the whole configuration first")
    old = pd.read_csv(cases_file, keep_default_na=False)
    errors: dict[tuple[str, str, float], str] = {}
    failures_file = results_dir / "failures.csv"
    if failures_file.exists() and failures_file.stat().st_size > 2:
        for item in pd.read_csv(failures_file).to_dict("records"):
            key = (str(item["case_id"]), str(item["method"]), float(item["delay_s"]))
            errors[key] = str(item["error"])
    kept = []
    for record in old[~old["method"].isin(rerun)].to_dict("records"):
        key = (str(record["case_id"]), str(record["method"]), float(record["delay_s"]))
        record["error"] = errors.get(key, "")
        kept.append(CaseRow(**record))
    return kept


# --- pooling runs across systems --------------------------------------------


def combine(config: dict, results_root: Path, title: str = "pooled") -> int:
    """Pool finished per-system runs into one result, without re-running anything.

    E1 runs one system at a time - each needs its own call graph, and the data is
    downloaded one system at a time - but "all of RE1" is one population. This
    reads the `cases.csv` of each listed run, checks they are compatible, and
    summarises them together, adding a per-system breakdown. The numbers are
    computed by the same `summarise` as a single run, so pooling cannot change
    how any case is scored.
    """
    run_ids = [str(run) for run in config["combine_runs"]]
    log: list[str] = []

    def note(line: str) -> None:
        print(line)
        log.append(line)

    frames: list[pd.DataFrame] = []
    failures: list[pd.DataFrame] = []
    sources: dict[str, dict] = {}
    for run_id in run_ids:
        folder = results_root / run_id
        cases_file = folder / "cases.csv"
        if not cases_file.exists():
            raise FileNotFoundError(
                f"{cases_file} does not exist; run that configuration first"
            )
        # keep_default_na=False keeps empty cells as "" - the contract's spelling
        # of "missing" - rather than turning them into NaN.
        frame = pd.read_csv(cases_file, keep_default_na=False)
        frames.append(frame)
        failures_file = folder / "failures.csv"
        if failures_file.exists() and failures_file.stat().st_size > 2:
            failures.append(pd.read_csv(failures_file))
        with (folder / "config.yaml").open(encoding="utf-8") as handle:
            sources[run_id] = yaml.safe_load(handle)

    check_combinable(sources, frames)

    frame = pd.concat(frames, ignore_index=True)
    # Columns read back from disk are strings; the metrics only need the ranks
    # and flags, which `ranks_from` and `symptom_rate` parse themselves.
    frame["runtime_s"] = pd.to_numeric(frame["runtime_s"])

    note(f"{title}, pooled: {config['run_id']}")
    for run_id in run_ids:
        part = frame[frame["run_id"] == run_id]
        note(
            f"  {run_id}: {sources[run_id]['system']}, "
            f"{part['case_id'].nunique()} cases, graph "
            f"{sources[run_id].get('graph') or 'none'}"
        )
    note(f"  {frame['case_id'].nunique()} cases in total")

    overall = summarise(frame, by=None)
    by_system = summarise(frame, by="system")
    by_fault = summarise(frame, by="fault_type")
    by_system_fault = summarise(frame, by=["system", "fault_type"])

    report = "\n".join(
        [
            f"--- {title}, pooled over {', '.join(run_ids)} ---",
            "",
            format_table(overall, "method"),
            "",
            "--- by system ---",
            format_table(by_system, "method", "system"),
            "",
            "--- by fault type, pooled over systems ---",
            format_table(by_fault, "method", "fault_type"),
            "",
            "--- by system and fault type ---",
            format_table(by_system_fault, "method", "system", "fault_type"),
            "",
            legend(),
            pooling_note(sources),
        ]
    )
    note("")
    note(report)

    results_dir = results_root / str(config["run_id"])
    results_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(results_dir / "cases.csv", index=False)
    (pd.concat(failures, ignore_index=True) if failures else pd.DataFrame()).to_csv(
        results_dir / "failures.csv", index=False
    )
    overall.to_csv(results_dir / "summary.csv", index=False)
    by_system.to_csv(results_dir / "summary_by_system.csv", index=False)
    by_fault.to_csv(results_dir / "summary_by_fault.csv", index=False)
    by_system_fault.to_csv(results_dir / "summary_by_system_fault.csv", index=False)
    (results_dir / "report.txt").write_text(report + "\n", encoding="utf-8")
    saved = dict(config)
    saved["pare_version"] = pare_version()
    saved["source_configs"] = sources
    (results_dir / "config.yaml").write_text(
        yaml.safe_dump(saved, sort_keys=False), encoding="utf-8"
    )
    (results_dir / "env.txt").write_text(environment_report(), encoding="utf-8")
    (results_dir / "log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"\nwrote {results_dir}")
    return 0


def check_combinable(sources: dict[str, dict], frames: Sequence[pd.DataFrame]) -> None:
    """Refuse to pool runs that did not measure the same thing.

    Pooling runs with different methods, delays, seeds or normal windows would
    average unlike quantities and print them as one number, so each of those must
    match exactly. Overlapping cases would count a case twice.
    """
    keys = ("methods", "delays_s", "seed", "normal_mode", "dataset")
    first_id, first = next(iter(sources.items()))
    for run_id, config in sources.items():
        for key in keys:
            if config.get(key) != first.get(key):
                raise ValueError(
                    f"cannot pool {run_id} with {first_id}: {key} differs "
                    f"({config.get(key)!r} against {first.get(key)!r})"
                )
    seen: set[str] = set()
    for frame in frames:
        ids = set(frame["case_id"])
        overlap = seen & ids
        if overlap:
            raise ValueError(f"the runs share cases, e.g. {sorted(overlap)[:3]}")
        seen |= ids


def pooling_note(sources: dict[str, dict]) -> str:
    without_graph = [
        f"{run_id} ({config['system']})"
        for run_id, config in sources.items()
        if not config.get("graph")
    ]
    if not without_graph:
        return ""
    return (
        "\nNOTE: no call graph for "
        + ", ".join(without_graph)
        + ". symptom_error is empty for those cases, so the pooled symptom_rate\n"
        "covers only the systems that have a graph. Read the per-system table."
    )


# --- the metrics E1 reports -------------------------------------------------


def summarise(frame: pd.DataFrame, by: str | Sequence[str] | None) -> pd.DataFrame:
    """ExpAC@k for indicators, AC@k for services, and the symptom rate.

    `docs/08` section 4 asks for all three, broken down by system and fault type.
    `by` is one column name, several, or None for one row per method.
    """
    extra = [] if by is None else ([by] if isinstance(by, str) else list(by))
    # A delay sweep (E3) is summarised per delay: averaging a method's accuracy
    # over delays would blur exactly the effect the sweep measures. A run with one
    # delay keeps the old shape, so E1's summaries are unchanged.
    if "delay_s" in frame.columns and frame["delay_s"].nunique() > 1:
        extra = ["delay_s", *extra]
    keys = ["method"] + extra
    out: list[dict[str, object]] = []
    for values, group in frame.groupby(keys, sort=True):
        values = values if isinstance(values, tuple) else (values,)
        row: dict[str, object] = dict(zip(keys, values, strict=True))

        service = ranks_from(group, "rank_gt_service", "tied_gt_service")
        wrong = wrong_probabilities(group)
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
            exp_ac1=round_or_empty(eval_metrics.exp_ac_at_k(strict, 1)) if strict else "",
            exp_ac3=round_or_empty(eval_metrics.exp_ac_at_k(strict, 3)) if strict else "",
            exp_ac5=round_or_empty(eval_metrics.exp_ac_at_k(strict, 5)) if strict else "",
            strict_cases=len(strict_rows),
            # AC@1 on the same strict cases. E1's headline is the gap between
            # naming the right service and naming the right metric, and that gap
            # only means something when both are measured on the same cases - ac1
            # below covers every fault type, exp_ac1 only CPU and MEM.
            ac1_strict=(
                round_or_empty(
                    eval_metrics.ac_at_k(
                        ranks_from(strict_rows, "rank_gt_service", "tied_gt_service"), 1
                    )
                )
                if strict
                else ""
            ),
            # The looser reading, over every case. Only interpretable next to the
            # size of the acceptable set, which is why it is in the per-fault table.
            exp_ac1_loose=round_or_empty(eval_metrics.exp_ac_at_k(loose, 1)),
            exp_ac3_loose=round_or_empty(eval_metrics.exp_ac_at_k(loose, 3)),
            # The coarse question, for comparison: the right service, not the right
            # metric. The gap between this and exp_ac1 is one of E1's findings.
            ac1=round_or_empty(eval_metrics.ac_at_k(service, 1)),
            ac3=round_or_empty(eval_metrics.ac_at_k(service, 3)),
            avg5=round_or_empty(eval_metrics.avg_at_5(service)),
            # RQ2. `wrong_top1` is the expected number of wrong top-1 answers with
            # rank-1 ties broken at random - the same rule as AC@1, so it is
            # exactly (1 - AC@1) x cases and can be fractional. It replaced a
            # count of "the service listed first is not the culprit", which for a
            # method that ties is decided by the alphabetical order of the tied
            # services (M3.2, decision 77).
            wrong_top1=round(sum(wrong), 2),
            # The part of wrong_top1 that could be judged, i.e. had a call graph
            # to ask "does the blamed service call the culprit?". symptom_rate's
            # denominator. Equal to wrong_top1 for a system with a graph; smaller
            # when a graph-less system is pooled in.
            symptom_judged=round(
                sum(
                    w
                    for w, share in zip(wrong, group["symptom_share"], strict=True)
                    if str(share) not in ("", "nan", "None")
                ),
                2,
            ),
            symptom_rate=round_or_empty(symptom_rate(group)),
            # What random wrong answers would score on the same cases. A symptom
            # rate is evidence of being drawn to victims only when it is above this.
            symptom_chance=round_or_empty(symptom_rate_chance(group)),
            no_clear_cause=int((group["verdict"] == "NO_CLEAR_CAUSE").sum()),
            mean_ms=round(float(group["runtime_s"].mean() * 1000), 1),
        )
        if "fault_type" in extra:
            row["acceptable_indicators"] = acceptable_count(group)
        out.append(row)
    return pd.DataFrame(out)


def acceptable_count(group: pd.DataFrame) -> object:
    """How many metrics count as correct for this fault type.

    Printed beside the loose score because without it that score is not
    interpretable: 1 of 51 and 4 of 51 are different questions. Sock Shop has no
    plain `latency` metric, so the size depends on the system as well as the
    fault; pooled over systems where it differs, it is printed as a range such as
    "2-3" rather than one number that is true of neither.
    """
    from experiments.adapters.rcaeval import acceptable_metrics

    fault = str(group["fault_type"].iloc[0])
    # "dataset" is part of the cases.csv contract (docs/06 section 5) and every
    # real run has it; a minimal test fixture may not, and every case before
    # RE2/RE3 existed was RE1. Missing means RE1, never a crash.
    if "dataset" in group.columns:
        datasets = group["dataset"].astype(str)
    else:
        datasets = pd.Series(["RE1"] * len(group))
    if set(datasets) == {"SYNTHETIC"}:
        return 1  # every synthetic fault shows in exactly one column (E6)
    sizes = sorted(
        {
            len(acceptable_metrics(str(system), fault, str(dataset)))
            for system, dataset in zip(group["system"], datasets, strict=True)
        }
    )
    return sizes[0] if len(sizes) == 1 else f"{sizes[0]}-{sizes[-1]}"


def round_or_empty(value: float | None) -> object:
    return "" if value is None else round(float(value), 4)


def format_table(frame: pd.DataFrame, *first: str) -> str:
    """Put the identifying columns first, then the metrics, and print it plainly."""
    ordered = list(first) + [c for c in frame.columns if c not in first]
    return frame[ordered].to_string(index=False)


def legend() -> str:
    return "\n".join(
        [
            "ExpAC@k  : the ground-truth INDICATOR is in the top k explained "
            "features. RQ1.",
            "           Strict: only the CPU and MEM cases (and SOCKET on RE2), where "
            "the right",
            "           metric is not a judgement call. This is the headline "
            "(docs/08 section 4).",
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
            "           Rank-1 ties are scored as ties, like AC@k: a case counts by "
            "the share of",
            "           its tied top group that calls the culprit, not by whichever "
            "was listed first.",
            "wrong_top1 : expected wrong top-1 answers, ties broken at random; "
            "exactly",
            "           (1 - AC@1) x cases, so it can be fractional.",
            "symptom_judged : the part of wrong_top1 with a call graph to judge by; "
            "symptom_rate's",
            "           denominator.",
            "symptom_chance : the symptom rate random wrong answers would get on the "
            "same cases -",
            "           the share of non-culprit services that call the culprit. Read "
            "symptom_rate",
            "           against it: only the excess says a method is drawn to "
            "victims.",
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


def read_config(path: Path) -> dict:
    """Read the YAML and refuse anything that would produce a misleading run."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path} should hold a mapping, got {type(config).__name__}")

    # A pooling config names finished runs instead of describing a new one; what
    # those runs measured is checked against each other in `check_combinable`.
    if "combine_runs" in config:
        if "run_id" not in config:
            raise ValueError(f"{path} is missing ['run_id']")
        if len(config["combine_runs"] or []) < 2:
            raise ValueError(f"{path} combine_runs should list at least two runs")
        return config

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


def pare_version() -> str:
    from pare import __version__

    return __version__


