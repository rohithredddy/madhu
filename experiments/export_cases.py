"""Export RCAEval cases into the case folders the Java backend reads (M7.4).

`docs/08` section 9: this is the only bridge between the research data and the
application; Java never parses an RCAEval folder. Each case is read through the
same adapter the experiments use (`adapters/rcaeval.py`), so the application sees
exactly the columns an experiment sees - foreign columns dropped, rows without a
timestamp removed - and written with `case_format.write_case`.

    analyzer/.venv/Scripts/python.exe experiments/export_cases.py \\
        --systems online-boutique sock-shop train-ticket

The ground-truth indicator is written only where it is a single unambiguous metric
(CPU and MEM, `docs/08` section 4). For DISK, DELAY and LOSS it is `null`, and the
notes say which metrics count as acceptable, rather than pretending one is right.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.adapters.graphs import GRAPHS_DIR, KNOWN_SYSTEMS, read_graph_file  # noqa: E402
from experiments.adapters.rcaeval import Case, list_cases, read_case_frame  # noqa: E402
from experiments.case_format import write_case  # noqa: E402

SOURCE = {"RE1": "RCAEVAL_RE1", "RE2": "RCAEVAL_RE2", "RE3": "RCAEVAL_RE3"}


def export_case(case: Case, out: Path) -> Path:
    """Write one RCAEval case as a case folder."""
    frame, columns, warnings = read_case_frame(case)

    if case.system in KNOWN_SYSTEMS and (GRAPHS_DIR / KNOWN_SYSTEMS[case.system]).exists():
        graph_file = read_graph_file(case.system)
        graph_source, edges = graph_file.source, list(graph_file.edges)
    else:
        graph_source, edges = "NONE", []

    notes = [f"exported from RCAEval {case.dataset} by export_cases.py ({case.path.as_posix()})"]
    if case.gt_indicator is None:
        notes.append(
            f"{case.fault_type} has no single ground-truth metric; acceptable: "
            f"{', '.join(case.acceptable_indicators)}"
        )
    notes += warnings
    return write_case(
        out,
        case.case_id,
        frame,
        source=SOURCE[case.dataset],
        system=case.system,
        fault_type=case.fault_type,
        inject_time_sec=case.inject_time_sec,
        ground_truth={"service": case.gt_service, "indicator": case.gt_indicator},
        columns=[column.to_dict() for column in columns],
        graph_source=graph_source,
        edges=edges,
        notes="; ".join(notes),
    )


def main(argv: Sequence[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--systems", nargs="+", default=["online-boutique", "sock-shop"])
    parser.add_argument("--data-root", type=Path, default=repo / "data" / "RCAEval")
    parser.add_argument("--out", type=Path, default=repo / "data" / "cases")
    parser.add_argument("--limit", type=int, default=None, help="per system, for a quick try")
    args = parser.parse_args(argv)

    total = 0
    for system in args.systems:
        try:
            cases = list_cases(args.data_root, args.dataset, system)
        except FileNotFoundError as error:
            print(f"skipping {system}: {error}", file=sys.stderr)
            continue
        for case in cases[: args.limit]:
            export_case(case, args.out)
            total += 1
        print(f"{system}: {min(len(cases), args.limit or len(cases))} cases")
    print(f"wrote {total} case folders to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
