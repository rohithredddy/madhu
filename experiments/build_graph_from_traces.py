"""Build a call graph from a benchmark's own traces (M5.2).

An edge ``A -> B`` is written when a span of service A is the parent of a span of
service B, i.e. A called B. Calls are counted, so the file shows how much evidence
each edge has, and edges with fewer than ``--min-calls`` calls are left out as
noise.

Only spans from the **normal period** of each case are used: those that start
more than ``--gap-s`` seconds before the injection. The graph should describe how
the system talks when it is healthy; spans recorded during the fault could carry
retries or errors that point at the answer, and a graph used to explain a case
must not be built from that case's incident (hard rule 4).

Service names in traces are not always the names in the metrics. Each rename is
passed explicitly (``--rename frontendservice=frontend``) and written into the
file, never guessed.

    analyzer/.venv/Scripts/python.exe experiments/build_graph_from_traces.py \\
        --dataset RE2 --system online-boutique --name online-boutique-traces \\
        --rename frontendservice=frontend
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.adapters.rcaeval import list_cases, read_case_frame  # noqa: E402

TRACE_COLUMNS = ["spanID", "parentSpanID", "serviceName", "startTime"]
# Spans are read in pieces so a large traces.csv never has to fit in memory at once.
CHUNK_ROWS = 500_000


def calls_in_case(traces: Path, normal_ends_sec: float) -> Counter[tuple[str, str]]:
    """Count caller -> callee calls among the spans of one case's normal period.

    A span's parent can sit in an earlier chunk, so the span -> service map is
    built over the whole normal period first and the edges are counted after.
    """
    parts = []
    for chunk in pd.read_csv(traces, usecols=TRACE_COLUMNS, chunksize=CHUNK_ROWS):
        # startTime is in microseconds (checked on RE2-OB: 1705349445111283).
        parts.append(chunk[chunk["startTime"] / 1e6 < normal_ends_sec])
    spans = pd.concat(parts, ignore_index=True)
    service_of = spans.drop_duplicates("spanID").set_index("spanID")["serviceName"]
    callers = spans["parentSpanID"].map(service_of)
    pairs = pd.DataFrame({"caller": callers, "callee": spans["serviceName"]}).dropna()
    pairs = pairs[pairs["caller"] != pairs["callee"]]
    return Counter(map(tuple, pairs[["caller", "callee"]].to_numpy()))


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--name", required=True, help="graph name; the file is <name>.yaml")
    parser.add_argument("--rename", nargs="*", default=[], help="trace=metrics name pairs")
    parser.add_argument("--min-calls", type=int, default=10)
    parser.add_argument("--gap-s", type=float, default=30.0)
    parser.add_argument("--data-root", type=Path, default=repo / "data" / "RCAEval")
    parser.add_argument("--out-dir", type=Path, default=repo / "experiments" / "graphs")
    args = parser.parse_args()

    renames = dict(pair.split("=", 1) for pair in args.rename)
    cases = list_cases(args.data_root, args.dataset, args.system)
    with_traces = [case for case in cases if (case.path / "traces.csv").exists()]
    print(f"{len(with_traces)} of {len(cases)} cases have traces.csv")

    total: Counter[tuple[str, str]] = Counter()
    for number, case in enumerate(with_traces, start=1):
        found = calls_in_case(case.path / "traces.csv", case.inject_time_sec - args.gap_s)
        total.update(found)
        print(f"  {number}/{len(with_traces)} {case.case_id}: {sum(found.values())} calls")

    renamed = Counter()
    for (caller, callee), count in total.items():
        renamed[(renames.get(caller, caller), renames.get(callee, callee))] += count

    kept = sorted(
        ((pair, count) for pair, count in renamed.items() if count >= args.min_calls),
        key=lambda item: (item[0][0], item[0][1]),
    )
    dropped = sorted(pair for pair, count in renamed.items() if count < args.min_calls)

    # Services the metrics carry but the traces never mention: no edge can be read
    # for them, and saying so is the point of the comparison with the static graph.
    _, columns, _ = read_case_frame(with_traces[0])
    in_metrics = {column.service for column in columns}
    in_graph = {name for pair, _ in kept for name in pair}
    untraced = sorted(in_metrics - in_graph)

    document = {
        "system": args.system,
        "source": "TRACES",
        "origin": {
            "dataset": f"RCAEval {args.dataset}",
            "built_by": "experiments/build_graph_from_traces.py",
            "built": date.today().isoformat(),
            "how": (
                "A -> B when a span of A is the parent of a span of B, counted over the "
                f"normal period (spans starting more than {args.gap_s:g} s before the "
                f"injection) of all {len(with_traces)} cases with traces. Edges with "
                f"fewer than {args.min_calls} calls are left out."
            ),
            "edges_below_min_calls": [f"{a} -> {b}" for a, b in dropped],
        },
        "renamed": renames,
        "no_edges": {
            service: "In the metrics but in no span of the traces, so no edge can be read."
            for service in untraced
        },
        "edges": [
            {"from": caller, "to": callee, "calls": int(count)}
            for (caller, callee), count in kept
        ],
    }
    out = args.out_dir / f"{args.name}.yaml"
    header = (
        f"# Call graph of {args.system} read from RCAEval {args.dataset} traces.\n"
        "# Generated by experiments/build_graph_from_traces.py - edit by re-running it.\n"
        "# Edge direction is caller -> callee (docs/06 section 2).\n"
    )
    out.write_text(header + yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    print(f"\n{len(kept)} edges written to {out}")
    for (caller, callee), count in kept:
        print(f"  {caller} -> {callee}: {count}")
    print(f"untraced services: {untraced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
