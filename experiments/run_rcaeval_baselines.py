"""Run RCAEval's own baselines on a dataset and record what they ranked.

Tasks M2.4 (NSigma and BARO, reproduced) and M4.2 (the full baseline set for E2
and E3). It calls the functions from the installed RCAEval package, with their
arguments and their preprocessing, and writes down the ranking each one produced.
Scoring happens elsewhere: `run_m24_compare.py` for M2.4, `score_rcaeval.py` for
E2 and E3.

**Run it with the RCAEval environment, not the analyzer one.** The two cannot
share: RCAEval pins numpy 1.x and the analyzer uses 2.x.

    experiments/.venv-rcaeval/Scripts/python.exe experiments/run_rcaeval_baselines.py \\
        --system online-boutique --methods NSIGMA BARO E_DIAGNOSIS CIRCA RCD PC_PAGERANK \\
        --delay-s 0 30 60 120 --results experiments/results/e2_rcaeval_re1_ob

What it guarantees, because `docs/08` section 4 asks for each:

* **The same alarm time as ours.** Each function is given `inject_time + delay_s`,
  which is the only time any of them takes. Their normal window is everything
  before it, which is their protocol, not ours; the difference is stated in the
  paper rather than adjusted away.
* **A time limit, 300 s per case by default.** The slow methods run in a child
  process that is killed when the limit passes, and the kill is recorded.
* **Failures are recorded, not hidden** - including the quiet kind. CIRCA, RCD and
  PC-PageRank are wrapped in RCAEval's `@rca` decorator, which catches any
  exception, prints one line to stderr and returns the *unranked column order*
  as if it were an answer. Scored naively that would look like a method doing
  badly rather than a method that did not run. So stderr is captured and a call
  that printed the fallback line is recorded as a failure, with the message.

Two things this script deliberately does not do.

* **It never reads the ground truth.** The folder name holds the broken service,
  and this script does not look at it. Scoring happens in the other scripts,
  which share the project's one ground-truth mapping. A file that never reads the
  answer cannot leak it (hard rule 4).
* **It does not import our code**, neither `pare` nor `adapters/rcaeval.py`,
  which would pull numpy 2.x into this environment. The folder walk and the
  per-system file choice are small duplicates of the adapter's.

Output is one JSON object per line in `<results>/rcaeval_rankings.jsonl`. A run
that is stopped can be started again with the same arguments: (case, method,
delay) combinations already in the file are skipped.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import multiprocessing as mp
import os
import platform
import queue
import re
import sys
import time
from pathlib import Path

# The fault-type folder suffixes of RE1. Used only to recognise a case folder,
# never to decide anything about the answer.
FAULT_SUFFIXES = ("cpu", "mem", "disk", "delay", "loss")

# Which folder holds which system, the `dataset` string to hand their functions,
# and the metrics file. Their `preprocess` branches on `dataset` only to tell None
# (do nothing) from "causalrca-sock-shop", and RCD additionally special-cases
# "sock-shop"; the strings below are the ones their own code uses. The file is
# the one the benchmark's published metric counts describe - the same choice as
# `METRICS_FILE` in adapters/rcaeval.py (decision 78).
SYSTEMS = {
    ("RE1", "online-boutique"): ("RE1-OB", "ob", "data.csv"),
    ("RE1", "sock-shop"): ("RE1-SS", "sock-shop", "simple_data.csv"),
    ("RE1", "train-ticket"): ("RE1-TT", "train-ticket", "simple_data.csv"),
}

# Our name for each method -> the function in RCAEval.e2e. The names are prefixed
# when scored (RCAEVAL_NSIGMA and so on), so their NSigma is never confused with
# ours.
METHODS = {
    "NSIGMA": "nsigma",
    "BARO": "baro",
    "E_DIAGNOSIS": "e_diagnosis",
    "CIRCA": "circa",
    "RCD": "rcd",
    "PC_PAGERANK": "pc_pagerank",
}

# Methods that finish in about a second run in this process; the rest each get a
# child process so a hung call can be killed at the time limit.
FAST = {"NSIGMA", "BARO"}

FALLBACK_MARK = "returning the unranked column order"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--data-root", type=Path, default=repo_root / "data" / "RCAEval")
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--system", default="online-boutique")
    parser.add_argument(
        "--results",
        type=Path,
        default=repo_root / "experiments" / "results" / "m2_4",
        help="run folder; rankings are appended, never replaced",
    )
    parser.add_argument(
        "--methods", nargs="+", default=["NSIGMA", "BARO"], choices=list(METHODS)
    )
    parser.add_argument(
        "--delay-s",
        type=float,
        nargs="+",
        default=[0.0],
        help=(
            "how late the alarm is assumed to be. Their normal window is everything "
            "before the time they are given, so a delay moves both ends of their "
            "protocol at once."
        ),
    )
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    parser.add_argument("--limit", type=int, default=None, help="first N cases only")
    parser.add_argument(
        "--retry-timeouts",
        action="store_true",
        help=(
            "drop the timed-out records from an earlier run and run those calls "
            "again; for a run whose time limits were hit because something else was "
            "using the machine"
        ),
    )
    args = parser.parse_args()

    try:
        import pandas as pd  # noqa: F401
        import RCAEval.e2e  # noqa: F401
    except ImportError as error:
        print(
            f"cannot import RCAEval ({error}).\n"
            "This script needs the RCAEval environment; see docs/08 section 2.",
            file=sys.stderr,
        )
        return 2

    key = (args.dataset, args.system)
    if key not in SYSTEMS:
        print(f"no folder known for {key}; known: {sorted(SYSTEMS)}", file=sys.stderr)
        return 2
    folder_name, dataset_arg, metrics_file = SYSTEMS[key]

    base = args.data_root / args.dataset / folder_name
    if not base.exists():
        print(
            f"{base} does not exist. Download it first:\n"
            f"  experiments/.venv-rcaeval/Scripts/python.exe "
            f"experiments/download_rcaeval.py --dataset {folder_name}",
            file=sys.stderr,
        )
        return 2

    cases = _find_cases(base, metrics_file)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print(f"no case folders found under {base}", file=sys.stderr)
        return 2

    args.results.mkdir(parents=True, exist_ok=True)
    out_path = args.results / "rcaeval_rankings.jsonl"
    if args.retry_timeouts:
        dropped = _drop_timeouts(out_path)
        print(f"dropped {dropped} timed-out record(s) from {out_path.name} to retry them")
    done = _already_done(out_path)

    # Delay-major order, so that if the run is stopped early the delay-0 results,
    # which E2's main table needs, are the ones that exist.
    tasks = [
        {
            "method": method,
            "delay_s": delay_s,
            "fault_folder": fault_folder.name,
            "run": run_folder.name,
            "path": str(run_folder / metrics_file),
            "inject_file": str(run_folder / "inject_time.txt"),
            "dataset_arg": dataset_arg,
        }
        for delay_s in args.delay_s
        for method in args.methods
        for fault_folder, run_folder in cases
        if (fault_folder.name, run_folder.name, method, float(delay_s)) not in done
    ]
    print(
        f"{len(cases)} cases x {len(args.methods)} methods x {len(args.delay_s)} "
        f"delays; {len(tasks)} still to run ({len(done)} already in {out_path.name}); "
        f"{args.workers} workers, {args.timeout_s:.0f} s limit"
    )

    _write_config(args, folder_name, dataset_arg, metrics_file, len(cases))
    _write_env(args.results / "env-rcaeval.txt")

    counts = {"written": 0, "failed": 0}
    started = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as out:

        def record(task: dict, result: dict) -> None:
            result.update(
                dataset=args.dataset,
                system=args.system,
                case_folder=task["fault_folder"],
                run=task["run"],
                metrics_file=metrics_file,
            )
            out.write(json.dumps(result) + "\n")
            out.flush()
            counts["written"] += 1
            counts["failed"] += result["error"] is not None
            if counts["written"] % 50 == 0 or counts["written"] == len(tasks):
                elapsed = time.perf_counter() - started
                print(
                    f"  {counts['written']}/{len(tasks)} done, {counts['failed']} failed, "
                    f"{elapsed / 60:.1f} min",
                    flush=True,
                )

        fast = [task for task in tasks if task["method"] in FAST]
        slow = [task for task in tasks if task["method"] not in FAST]
        for task in fast:
            record(task, _run_task(task))
        _run_isolated(slow, args.workers, args.timeout_s, record)

    print(f"wrote {counts['written']} rankings ({counts['failed']} failed) to {out_path}")
    return 0


# --- running one call -------------------------------------------------------


def _run_task(task: dict) -> dict:
    """Read one case, call one of their functions, and describe what happened."""
    import pandas as pd
    from RCAEval import e2e

    function = getattr(e2e, METHODS[task["method"]], None)
    base = {"method": task["method"], "delay_s": task["delay_s"]}
    if function is None:
        return {**base, "runtime_s": 0.0, "ranked_columns": [], "ranked_scores": None,
                "n_candidates": 0, "error": "not available in this RCAEval install"}

    frame = pd.read_csv(task["path"])
    inject_time = int(Path(task["inject_file"]).read_text().strip())
    captured = io.StringIO()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stderr(captured):
            output = function(
                frame, inject_time=inject_time + task["delay_s"], dataset=task["dataset_arg"]
            )
    except Exception as error:  # noqa: BLE001 - recorded, not hidden
        return {**base, "runtime_s": round(time.perf_counter() - started, 4),
                "ranked_columns": [], "ranked_scores": None, "n_candidates": 0,
                "n_rows": int(len(frame)), "inject_time_sec": inject_time,
                "error": f"{type(error).__name__}: {error}"}

    runtime_s = round(time.perf_counter() - started, 4)
    # The fallback line can share a line with a progress bar (causal-learn draws
    # one on stderr), so pick out just "<name> failed (...); returning ...".
    found = re.search(r"\w+ failed \(.*?\); " + FALLBACK_MARK, captured.getvalue())
    fallback = found.group(0) if found else None
    ranked = [str(name) for name in output["ranks"]]
    return {
        **base,
        "runtime_s": runtime_s,
        # Their functions return the order but not the scores; the scoring script
        # treats a ranking without scores as having no detectable ties.
        "ranked_columns": [] if fallback else ranked,
        "ranked_scores": None,
        "n_candidates": len(output.get("node_names", ranked)),
        "n_rows": int(len(frame)),
        "inject_time_sec": inject_time,
        "error": f"fell back to column order: {fallback.strip()}" if fallback else None,
    }


def _child(task: dict, results: mp.Queue) -> None:
    """Entry point of a child process: run one task, hand back the result."""
    import warnings

    warnings.filterwarnings("ignore")
    try:
        results.put(_run_task(task))
    except BaseException as error:  # noqa: BLE001 - the parent must always hear back
        results.put({"method": task["method"], "delay_s": task["delay_s"], "runtime_s": 0.0,
                     "ranked_columns": [], "ranked_scores": None, "n_candidates": 0,
                     "error": f"{type(error).__name__}: {error}"})


def _run_isolated(tasks: list[dict], workers: int, timeout_s: float, record) -> None:
    """Run each task in its own process, at most `workers` at a time.

    A process that is still running at the time limit is killed and recorded as
    timed out. A fresh process per task costs a second or two of imports, which is
    small next to methods that take tens of seconds, and it is the only way to be
    able to stop one that never returns.
    """
    # One native thread per child. Several children run at once, and numpy's
    # BLAS would otherwise give each of them every core; the oversubscription made
    # epsilon-Diagnosis, about 8 s alone, hit the 300 s limit (M4.2). A child
    # inherits these when it starts, before it imports numpy.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    context = mp.get_context("spawn")
    pending = list(tasks)
    running: list[tuple[mp.Process, mp.Queue, dict, float]] = []
    while pending or running:
        while pending and len(running) < workers:
            task = pending.pop(0)
            results: mp.Queue = context.Queue()
            process = context.Process(target=_child, args=(task, results), daemon=True)
            process.start()
            running.append((process, results, task, time.perf_counter()))

        still: list[tuple[mp.Process, mp.Queue, dict, float]] = []
        for process, results, task, began in running:
            try:
                result = results.get_nowait()
            except queue.Empty:
                result = None
            elapsed = time.perf_counter() - began
            if result is not None:
                process.join(timeout=5)
                record(task, result)
            elif not process.is_alive():
                record(task, _failure(task, elapsed, f"process exited ({process.exitcode})"))
            elif elapsed > timeout_s:
                process.kill()
                process.join(timeout=5)
                record(task, _failure(task, elapsed, f"timed out after {timeout_s:.0f} s"))
            else:
                still.append((process, results, task, began))
        running = still
        time.sleep(0.2)


def _failure(task: dict, elapsed: float, message: str) -> dict:
    return {"method": task["method"], "delay_s": task["delay_s"],
            "runtime_s": round(elapsed, 1), "ranked_columns": [], "ranked_scores": None,
            "n_candidates": 0, "error": message}


# --- bookkeeping ------------------------------------------------------------


def _find_cases(base: Path, metrics_file: str) -> list[tuple[Path, Path]]:
    """Every `(fault_folder, run_folder)` pair under one system, sorted."""
    found: list[tuple[Path, Path]] = []
    for fault_folder in sorted(p for p in base.iterdir() if p.is_dir()):
        if fault_folder.name.rpartition("_")[2] not in FAULT_SUFFIXES:
            continue
        runs = [p for p in fault_folder.iterdir() if p.is_dir()]
        for run_folder in sorted(
            runs, key=lambda p: (int(p.name), "") if p.name.isdigit() else (1 << 30, p.name)
        ):
            if (run_folder / metrics_file).exists() and (run_folder / "inject_time.txt").exists():
                found.append((fault_folder, run_folder))
    return found


def _drop_timeouts(path: Path) -> int:
    """Remove timed-out records so those calls run again. Returns how many."""
    if not path.exists():
        return 0
    kept, dropped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if "timed out after" in (json.loads(line).get("error") or ""):
            dropped += 1
        else:
            kept.append(line)
    path.write_text("".join(item + "\n" for item in kept), encoding="utf-8")
    return dropped


def _already_done(path: Path) -> set[tuple[str, str, str, float]]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            done.add((item["case_folder"], item["run"], item["method"], float(item["delay_s"])))
    return done


def _write_config(args, folder_name, dataset_arg, metrics_file, n_cases) -> None:
    path = args.results / "config-rcaeval.json"
    config = {
        "script": Path(__file__).name,
        "dataset": args.dataset,
        "system": args.system,
        "folder": folder_name,
        "metrics_file": metrics_file,
        "dataset_arg_passed_to_rcaeval": dataset_arg,
        "methods": args.methods,
        "delay_s": args.delay_s,
        "timeout_s": args.timeout_s,
        "workers": args.workers,
        "cases": n_cases,
        "limit": args.limit,
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _write_env(path: Path) -> None:
    """Record what actually ran, which `docs/08` section 8 requires beside results."""
    lines = [
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"machine: {platform.machine()}",
    ]
    for package in ("RCAEval", "numpy", "pandas", "scikit-learn", "networkx",
                    "causal-learn", "sfr-pyrca"):
        lines.append(f"{package}: {_version(package)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _version(package: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(package)
    except PackageNotFoundError:
        return "not installed"


if __name__ == "__main__":
    raise SystemExit(main())
