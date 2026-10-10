"""Where does PARE's change point land on RCAEval, and does the window still see the fault?

A diagnostic for decision 84 (M4.1). E2 showed PARE at AC@1 0.400 at delay 0 but 0.888
with the change point switched off (PARE_NO_CP), and 0.852 at a 60 s delay. This
script measures, per case, where the estimated change point lands relative to the
injection and whether the analysis window [cp, cp + window_len] still reaches the
alarm. The injection time is used here only to describe the outcome; the engine is
never given it.

    analyzer/.venv/Scripts/python.exe experiments/diagnose_change_point.py \
        --out experiments/results/m4_cp
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare.changepoint import estimate_change_point  # noqa: E402
from pare.config import PareConfig  # noqa: E402
from pare.preprocess import preprocess  # noqa: E402
from pare.scores import robust_baseline  # noqa: E402

from experiments.adapters.graphs import load_graph  # noqa: E402
from experiments.adapters.rcaeval import list_cases, load_case  # noqa: E402


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--systems", nargs="+", default=["online-boutique", "sock-shop"])
    parser.add_argument("--delays", nargs="+", type=float, default=[0.0, 30.0, 60.0, 120.0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    settings = PareConfig()
    rows = []
    for system in args.systems:
        graph = load_graph(system)
        for case in list_cases(repo / "data" / "RCAEval", "RE1", system):
            for delay in args.delays:
                data = load_case(case, delay_s=delay, graph=graph)
                names = [c.name for c in data.columns]
                clean = preprocess(
                    data.normal[names].to_numpy(float),
                    data.recent[names].to_numpy(float),
                    data.columns,
                    settings,
                )
                cp = estimate_change_point(
                    data.recent["time"].to_numpy(float),
                    clean.recent,
                    clean.columns,
                    robust_baseline(clean.normal),
                    data.alarm_time_sec,
                    settings,
                )
                rows.append(
                    {
                        "system": system,
                        "case_id": case.case_id,
                        "fault_type": case.fault_type,
                        "delay_s": delay,
                        "estimated": cp.estimated,
                        "cp_minus_inject_s": cp.time_sec - case.inject_time_sec,
                        "window_reaches_alarm": cp.time_sec + settings.window_len_s
                        >= data.alarm_time_sec,
                        "window_contains_fault": cp.time_sec + settings.window_len_s
                        >= case.inject_time_sec,
                    }
                )
    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out / "change_points.csv", index=False)
    summary = frame.groupby("delay_s").agg(
        cases=("case_id", "size"),
        median_cp_minus_inject_s=("cp_minus_inject_s", "median"),
        cp_before_inject_by_60s_or_more=("cp_minus_inject_s", lambda s: int((s <= -60).sum())),
        window_misses_the_fault=("window_contains_fault", lambda s: int((~s).sum())),
    )
    text = (
        "Where PARE's change point lands (RE1 Online Boutique + Sock Shop)\n"
        + summary.to_string()
        + "\n"
    )
    (args.out / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
