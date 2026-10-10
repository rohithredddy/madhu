"""How well does the live Java detector time its alarm? (M10 check, recorded in m10_replay/.)

Replays cases through the running backend (POST /api/replay) at top speed and
records, for each, when the detector raised its alarm relative to the injection:
early (a false alarm, before the fault), late (after it), or never. The detector is
never told the injection time; this script reads it from the case afterwards, only
to score the alarm.

    analyzer/.venv/Scripts/python.exe experiments/check_replay_alarms.py \\
        --cases synthetic- re1-ss- --limit 12 --out experiments/results/m10_replay

Needs the backend on :8080 (and the engine, for the explanation after the alarm).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

API = "http://localhost:8080/api"


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode()
        return json.loads(text) if text else {}


def replay(case_id: str, engine: str) -> dict:
    session = call("POST", "/replay", {"caseId": case_id, "speed": 50, "engine": engine})[
        "sessionId"
    ]
    while True:
        state = call("GET", f"/replay/{session}")
        if state["state"] in ("EXPLAINED", "FINISHED", "STOPPED"):
            return state
        time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", default=["synthetic-"], help="case id prefixes")
    parser.add_argument("--limit", type=int, default=12, help="per prefix")
    parser.add_argument("--engine", default="PARE")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    listed = call("GET", "/cases?size=1000")["items"]
    rows = []
    for prefix in args.cases:
        chosen = [c for c in listed if c["caseId"].startswith(prefix) and c["replayable"]][
            : args.limit
        ]
        for summary in chosen:
            detail = call("GET", f"/cases/{summary['caseId']}")
            inject = detail["meta"]["injectTimeSec"]
            state = replay(summary["caseId"], args.engine)
            alarm = state["alarmTimeSec"]
            run = state.get("run") or {}
            evaluation = run.get("evaluation") or {}
            rows.append(
                {
                    "case_id": summary["caseId"],
                    "alarm_minus_inject_s": None if alarm is None else alarm - inject,
                    "outcome": "never"
                    if alarm is None
                    else ("early" if alarm < inject else "after"),
                    "threshold": state["threshold"],
                    "top_columns_at_alarm": " ".join(state.get("topColumnsAtAlarm") or []),
                    "verdict": (run.get("response") or {}).get("verdict"),
                    "correct_top1": evaluation.get("correctTop1"),
                }
            )
            print(rows[-1], flush=True)

    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out / "alarms.csv", index=False)
    summary = (
        frame.groupby(frame["case_id"].str.split("-").str[0])["outcome"]
        .value_counts()
        .unstack(fill_value=0)
    )
    text = (
        "Replay alarm timing (detector never told the injection time)\n"
        + summary.to_string()
        + "\n"
    )
    after = frame[frame.outcome == "after"]["alarm_minus_inject_s"]
    if len(after):
        text += (
            f"\nalarms after the injection: median {after.median():.0f} s late, "
            f"max {after.max():.0f} s\n"
        )
    (args.out / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
