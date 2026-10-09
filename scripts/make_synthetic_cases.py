"""Write 12 synthetic cases (3 per fault type) into data/cases/ (task M7.5).

So the application has something to show from the first start, before any
RCAEval data is exported. Each case is built by the very function behind
`POST /v1/synthetic` and written by `experiments/case_format.py`, so a case made
here is byte-for-byte what the Java backend would save from the lab page.

    analyzer/.venv/Scripts/python.exe scripts/make_synthetic_cases.py

The three cases per fault type differ in `amplification`, the factor that decides
whether ordinary explanations get fooled (`docs/05` section 5): 0 (no symptom
trap - every method should be right), 0.25 (the band where PARE should help) and
0.5 (callers loud enough that marginal methods blame them). The seed is fixed per
case, so running this again rewrites the same twelve cases.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "analyzer"))

from service.app import synthetic_endpoint  # noqa: E402
from service.schemas import SyntheticRequestModel  # noqa: E402

from experiments.case_format import write_case  # noqa: E402

FAULTS = ("LATENCY", "CPU", "MEM", "ERROR")
AMPLIFICATIONS = (0.0, 0.25, 0.5)


def settings() -> list[SyntheticRequestModel]:
    """The twelve requests. n_abnormal is the same for all (docs/08 section 4)."""
    out = []
    for fault_index, fault in enumerate(FAULTS):
        for amp_index, amplification in enumerate(AMPLIFICATIONS):
            out.append(
                SyntheticRequestModel(
                    nServices=8, faultType=fault, propagation=0.8,
                    amplification=amplification, noise="MEDIUM",
                    nNormal=600, nAbnormal=180, seed=100 + 10 * fault_index + amp_index,
                )
            )
    return out


def write_one(request: SyntheticRequestModel, out: Path) -> Path:
    case = synthetic_endpoint(request)
    meta = case["meta"]
    names = [column["name"] for column in meta["columns"]]
    frame = pd.DataFrame(case["values"], columns=names)
    frame.insert(0, "time", case["timeSec"])
    return write_case(
        out, meta["caseId"], frame,
        source=meta["source"], system=meta["system"], fault_type=meta["faultType"],
        inject_time_sec=meta["injectTimeSec"], ground_truth=meta["groundTruth"],
        columns=meta["columns"], graph_source=meta["graph"]["source"],
        edges=[(edge["from"], edge["to"]) for edge in meta["graph"]["edges"]],
        notes=meta["notes"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "data" / "cases")
    args = parser.parse_args(argv)
    for request in settings():
        folder = write_one(request, args.out)
        print(f"wrote {folder.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
