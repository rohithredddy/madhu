"""Run RCAEval's own NSigma and BARO on a dataset and record what they ranked.

Task M2.4, first half. This is the reproduction: it calls the functions from the
installed RCAEval package, with their arguments and their preprocessing, and
writes down the ranking each one produced. `run_m24_compare.py` then scores those
rankings and compares them with ours.

**Run it with the RCAEval environment, not the analyzer one.** The two cannot
share: RCAEval pins numpy 1.x and the analyzer uses 2.x.

    experiments/.venv-rcaeval/Scripts/python.exe experiments/run_rcaeval_baselines.py

Two things this script deliberately does not do.

* **It never reads the ground truth.** The folder name holds the broken service,
  and this script does not look at it. Scoring happens in the other script, which
  has the one ground-truth mapping the project uses. That keeps hard rule 4
  mechanical rather than a matter of care: a file that never reads the answer
  cannot leak it.
* **It does not import our code.** Not the `pare` library and not
  `adapters/rcaeval.py`, which imports `pare` and so would pull numpy 2.x into an
  environment that has numpy 1.x. The folder walk here is a small duplicate of
  the adapter's, and it is the price of the two environments. It stays as small as
  possible: find folders, read two files, call their function, write the result.

Output is one JSON object per line in `<results>/rcaeval_rankings.jsonl`, each
holding a full ranking with its scores. JSON rather than CSV because a ranking is
a variable-length list; the scored, contract-shaped `cases.csv` is written by the
comparison script.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

# The fault-type folder suffixes of RE1. Used only to recognise a case folder,
# never to decide anything about the answer.
FAULT_SUFFIXES = ("cpu", "mem", "disk", "delay", "loss")

# Which folder holds which system, and the `dataset` string to hand their
# functions. Their `preprocess` branches on `dataset` only to tell None (do
# nothing at all, not even drop the time column) from the one special case
# "causalrca-sock-shop"; every other string behaves identically. "ob" and
# "sock-shop" are the strings their own code uses, so those are the ones used
# here.
SYSTEMS = {
    ("RE1", "online-boutique"): ("RE1-OB", "ob"),
    ("RE1", "sock-shop"): ("RE1-SS", "sock-shop"),
    ("RE1", "train-ticket"): ("RE1-TT", "train-ticket"),
}

METHODS = ("NSIGMA", "BARO")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--data-root",
        type=Path,
        default=repo_root / "data" / "RCAEval",
        help="where the RCAEval datasets live",
    )
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--system", default="online-boutique")
    parser.add_argument(
        "--results",
        type=Path,
        default=repo_root / "experiments" / "results" / "m2_4",
        help="run folder; written into, not replaced",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=list(METHODS),
        choices=list(METHODS),
    )
    parser.add_argument(
        "--delay-s",
        type=float,
        nargs="+",
        default=[0.0],
        help=(
            "how late the alarm is assumed to be. Note this moves BOTH ends of "
            "their protocol at once - their normal window is everything before "
            "the time they are given - so a sweep here is not the same "
            "experiment as E3's. M2.4 uses 0 only."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="first N cases only, for a smoke run"
    )
    args = parser.parse_args()

    try:
        import pandas as pd
        from RCAEval.e2e import baro, nsigma
    except ImportError as error:
        print(
            f"cannot import RCAEval ({error}).\n"
            "This script needs the RCAEval environment:\n"
            "  cd experiments\n"
            "  uv venv .venv-rcaeval --python 3.10\n"
            "  uv pip install --python .venv-rcaeval/Scripts/python.exe "
            "-r requirements-rcaeval.txt",
            file=sys.stderr,
        )
        return 2

    functions = {"NSIGMA": nsigma, "BARO": baro}

    key = (args.dataset, args.system)
    if key not in SYSTEMS:
        print(f"no folder known for {key}; known: {sorted(SYSTEMS)}", file=sys.stderr)
        return 2
    folder_name, dataset_arg = SYSTEMS[key]

    base = args.data_root / args.dataset / folder_name
    if not base.exists():
        print(
            f"{base} does not exist. Download it first:\n"
            f"  experiments/.venv-rcaeval/Scripts/python.exe "
            f"experiments/download_rcaeval.py --dataset {folder_name}",
            file=sys.stderr,
        )
        return 2

    cases = _find_cases(base)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print(f"no case folders found under {base}", file=sys.stderr)
        return 2

    args.results.mkdir(parents=True, exist_ok=True)
    out_path = args.results / "rcaeval_rankings.jsonl"

    print(
        f"{len(cases)} cases x {len(args.methods)} methods x "
        f"{len(args.delay_s)} delay(s) -> {out_path}"
    )

    written = 0
    failures = 0
    with out_path.open("w", encoding="utf-8") as out:
        for position, (fault_folder, run_folder) in enumerate(cases, start=1):
            frame = pd.read_csv(run_folder / "data.csv")
            inject_time = int((run_folder / "inject_time.txt").read_text().strip())

            for delay_s in args.delay_s:
                for method in args.methods:
                    record = _run_one(
                        function=functions[method],
                        method=method,
                        # A fresh copy each time: their preprocessing drops
                        # columns, and `drop_time` mutates nothing but a reused
                        # frame is a risk not worth taking.
                        frame=frame.copy(),
                        dataset_arg=dataset_arg,
                        inject_time=inject_time,
                        delay_s=delay_s,
                    )
                    record.update(
                        dataset=args.dataset,
                        system=args.system,
                        case_folder=fault_folder.name,
                        run=run_folder.name,
                        inject_time_sec=inject_time,
                        n_rows=int(len(frame)),
                        n_columns_in_file=int(frame.shape[1]),
                    )
                    if record["error"] is not None:
                        failures += 1
                    out.write(json.dumps(record) + "\n")
                    written += 1

            if position % 25 == 0 or position == len(cases):
                print(f"  {position}/{len(cases)} cases")

    _write_env(args.results / "env-rcaeval.txt")
    (args.results / "config-rcaeval.json").write_text(
        json.dumps(
            {
                "script": Path(__file__).name,
                "dataset": args.dataset,
                "system": args.system,
                "folder": folder_name,
                "dataset_arg_passed_to_rcaeval": dataset_arg,
                "methods": args.methods,
                "delay_s": args.delay_s,
                "cases": len(cases),
                "limit": args.limit,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {written} rankings ({failures} failed) to {out_path}")
    print(
        "now score them in the analyzer environment:\n"
        "  analyzer/.venv/Scripts/python.exe experiments/run_m24_compare.py"
    )
    return 0


def _run_one(
    function,
    method: str,
    frame,
    dataset_arg: str,
    inject_time: int,
    delay_s: float,
) -> dict:
    """Call one of their functions and record the ranking, or the failure.

    A method that raises is recorded and the run continues, as `docs/08` section
    4 asks: a crash is a result about the method, not a reason to lose the other
    124 cases. Note their package also wraps some methods in a decorator that
    swallows exceptions and returns the unranked column order; `nsigma` and
    `baro` are not wrapped, so a failure here really does arrive as an exception.
    """
    started = time.perf_counter()
    try:
        output = function(
            frame,
            inject_time=inject_time + delay_s,
            dataset=dataset_arg,
        )
    except Exception as error:  # noqa: BLE001 - recorded, not hidden
        return {
            "method": method,
            "delay_s": delay_s,
            "runtime_s": round(time.perf_counter() - started, 4),
            "ranked_columns": [],
            "ranked_scores": [],
            "n_candidates": 0,
            "error": f"{type(error).__name__}: {error}",
        }

    runtime_s = time.perf_counter() - started
    ranked = list(output["ranks"])

    # Their functions return the order but not the scores, and the scores are
    # what tells a genuine first place from a tie. Recomputing them here would
    # mean re-implementing the method, which is the one thing this script must
    # not do. So the order is recorded as given, and the comparison script treats
    # a ranking without scores as having no detectable ties - stated plainly
    # there rather than assumed away here.
    return {
        "method": method,
        "delay_s": delay_s,
        "runtime_s": round(runtime_s, 4),
        "ranked_columns": ranked,
        "ranked_scores": None,
        "n_candidates": len(output.get("node_names", ranked)),
        "error": None,
    }


def _find_cases(base: Path) -> list[tuple[Path, Path]]:
    """Every `(fault_folder, run_folder)` pair under one system, sorted."""
    found: list[tuple[Path, Path]] = []
    for fault_folder in sorted(p for p in base.iterdir() if p.is_dir()):
        if fault_folder.name.rpartition("_")[2] not in FAULT_SUFFIXES:
            continue
        runs = [p for p in fault_folder.iterdir() if p.is_dir()]
        for run_folder in sorted(
            runs, key=lambda p: (int(p.name), "") if p.name.isdigit() else (1 << 30, p.name)
        ):
            if (run_folder / "data.csv").exists() and (
                run_folder / "inject_time.txt"
            ).exists():
                found.append((fault_folder, run_folder))
    return found


def _write_env(path: Path) -> None:
    """Record what actually ran, which `docs/08` section 8 requires beside results."""
    lines = [
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"machine: {platform.machine()}",
    ]
    for package in ("RCAEval", "numpy", "pandas", "scikit-learn", "networkx"):
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
