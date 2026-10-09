"""Score RCAEval's own baselines into the same `cases.csv` contract as our engines.

Task M4.2, second half. `run_rcaeval_baselines.py` runs their methods in their
environment and records only the ranking each produced; this script, in the
analyzer environment, joins those rankings to the project's one ground-truth
mapping (`adapters/rcaeval.py`) and writes one row per (case, method, delay)
exactly as `runner.run_case` does for our engines. So E2's table can set RCAEval's
CIRCA beside PARE without either side having been scored by different code.

    analyzer/.venv/Scripts/python.exe experiments/score_rcaeval.py \\
        --rankings experiments/results/e2_rcaeval_re1_ob --system online-boutique

What differs from our engines, and is stated rather than hidden:

* **Their names carry a prefix**: `RCAEVAL_NSIGMA`, `RCAEVAL_CIRCA` and so on, so
  their NSigma is never mistaken for ours.
* **They have no verdict.** Their rows carry `NO_VERDICT` (`docs/06` section 5),
  which keeps the column non-empty for a run that worked - an empty verdict is how
  the contract marks a failed run.
* **No ties can be seen.** Their functions return an order without scores, so
  every rank is a plain position. A real tie inside their scoring is broken by
  their sort and cannot be recovered.
* **Their normal window is everything before the alarm**, which is their protocol.
  Under a delay it contains fault data; ours does not (`inject_gap`). The column
  `normal_mode` in this run's config says `rcaeval_protocol`.
* **Services come from column names.** Their rankings are raw column names, so the
  service is recovered by splitting at the last underscore, as their own
  `Evaluator` does. It happens here, in scoring, and never reaches an engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare import eval_metrics  # noqa: E402

from experiments.adapters.graphs import load_graph  # noqa: E402
from experiments.adapters.rcaeval import Case, list_cases  # noqa: E402
from experiments.experiment import format_table, legend, summarise  # noqa: E402
from experiments.runner import CaseRow, _best_rank, write_run  # noqa: E402

NO_VERDICT = "NO_VERDICT"
GRAPHED_SYSTEMS = ("online-boutique", "sock-shop")


def score_record(record: dict, case: Case, run_id: str, graph) -> CaseRow:
    """One recorded ranking -> one contract row."""
    method = f"RCAEVAL_{record['method']}"
    delay_s = float(record["delay_s"])
    common = dict(
        run_id=run_id, dataset=case.dataset, system=case.system, case_id=case.case_id,
        fault_type=case.fault_type, gt_service=case.gt_service,
        gt_indicator=case.gt_indicator or "", method=method, delay_s=delay_s, seed=0,
        runtime_s=float(record.get("runtime_s") or 0.0),
    )
    columns = tuple(record.get("ranked_columns") or ())
    if record.get("error") or not columns:
        return CaseRow(
            **common, rank_gt_service="", rank_gt_indicator="", rank_gt_indicator_loose="",
            top1_service="", top1_indicator="", tied_gt_service="", tied_gt_indicator="",
            tied_gt_indicator_loose="", symptom_error="", tied_top1="", symptom_share="",
            symptom_chance="", verdict="",
            error=record.get("error") or "empty ranking",
        )

    services: dict[str, None] = {}
    for column in columns:
        services.setdefault(service_of(column), None)
    service_order = tuple(services)

    # No scores: every rank is a position, every tie group has one member.
    rank_service = eval_metrics.rank_in_order(service_order, {}, case.gt_service)
    rank_strict = (
        eval_metrics.rank_in_order(columns, {}, case.gt_indicator) if case.gt_indicator else None
    )
    rank_loose = _best_rank(columns, {}, case.acceptable_indicators)
    top1 = service_order[0]
    symptom = eval_metrics.symptom_error(top1, case.gt_service, graph)
    share = eval_metrics.symptom_share((top1,), case.gt_service, graph)
    chance = eval_metrics.symptom_chance(service_order, case.gt_service, graph)

    return CaseRow(
        **common,
        rank_gt_service=_best(rank_service),
        rank_gt_indicator=_best(rank_strict),
        rank_gt_indicator_loose=_best(rank_loose),
        top1_service=top1,
        top1_indicator=next(c for c in columns if service_of(c) == top1),
        tied_gt_service=_tied(rank_service),
        tied_gt_indicator=_tied(rank_strict),
        tied_gt_indicator_loose=_tied(rank_loose),
        symptom_error="" if symptom is None else symptom,
        tied_top1=1,
        symptom_share="" if share is None else share,
        symptom_chance="" if chance is None else round(chance, 6),
        verdict=NO_VERDICT,
    )


def service_of(column: str) -> str:
    """The service a raw column name belongs to (see the module docstring)."""
    return column.rpartition("_")[0] or column


def _best(rank) -> object:
    return "" if rank is None else rank.best


def _tied(rank) -> object:
    return "" if rank is None else rank.tied


def main(argv: Sequence[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rankings", type=Path, required=True,
                        help="the run folder run_rcaeval_baselines.py wrote")
    parser.add_argument("--system", required=True)
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--data-root", type=Path, default=repo / "data" / "RCAEval")
    args = parser.parse_args(argv)

    cases = {
        (case.path.parent.name, case.run): case
        for case in list_cases(args.data_root, args.dataset, args.system)
    }
    graph = load_graph(args.system) if args.system in GRAPHED_SYSTEMS else None
    run_id = args.rankings.name

    rows: list[CaseRow] = []
    unmatched = 0
    lines = (args.rankings / "rcaeval_rankings.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        case = cases.get((record["case_folder"], record["run"]))
        if case is None:
            unmatched += 1
            continue
        rows.append(score_record(record, case, run_id, graph))
    if unmatched:
        raise ValueError(f"{unmatched} rankings name a case the adapter does not know")

    frame = pd.DataFrame([row.contract_row() for row in rows])
    overall = summarise(frame, by=None)
    by_fault = summarise(frame, by="fault_type")
    failures = [row for row in rows if row.error]
    log = [
        f"scored {len(rows)} rankings from {args.rankings}",
        f"{len(failures)} failed or fell back; all in failures.csv",
    ]
    for method in sorted({row.method for row in rows}):
        failed = [row for row in failures if row.method == method]
        if failed:
            log.append(f"  {method}: {len(failed)} failed, e.g. {failed[0].error[:120]}")

    config = json.loads((args.rankings / "config-rcaeval.json").read_text(encoding="utf-8"))
    config.update(
        run_id=run_id, dataset=args.dataset, system=args.system,
        methods=sorted({row.method for row in rows}),
        delays_s=sorted({row.delay_s for row in rows}),
        normal_mode="rcaeval_protocol", graph=args.system if graph is not None else None,
        scored_by=Path(__file__).name,
    )
    write_run(rows, args.rankings, config, log)
    overall.to_csv(args.rankings / "summary.csv", index=False)
    by_fault.to_csv(args.rankings / "summary_by_fault.csv", index=False)
    report = "\n".join([
        f"--- RCAEval baselines: {args.dataset} {args.system} ---", "",
        format_table(overall, "method"), "", "--- by fault type ---",
        format_table(by_fault, "method", "fault_type"), "", *log, "", legend(),
    ])
    (args.rankings / "report.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
