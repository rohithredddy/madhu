"""Score RCAEval's NSigma and BARO against ours, and account for the difference.

Task M2.4, second half. `run_rcaeval_baselines.py` has already run their code and
written the rankings it produced; this script scores those rankings, runs our
`NSIGMA`, and then works out where any gap comes from.

    analyzer/.venv/Scripts/python.exe experiments/run_m24_compare.py

Two numbers side by side would not settle anything. Their setup differs from ours
in three independent ways, and if all three move at once a difference in accuracy
cannot be attributed to any of them. So the comparison is a ladder that changes
one thing at a time:

===========  =======  =======  ==========  =========================================
cell         formula  window   candidates  what the step before it measures
===========  =======  =======  ==========  =========================================
A_theirs     theirs   theirs   theirs      (the reference; must reproduce their own
                                            output, which is checked, not assumed)
B_formula    ours     theirs   theirs      the formula: signed max of per-row z
                                            against the shift of the window mean
C_window     ours     ours     theirs      the windows: the 30 s gap before the
                                            injection, and an abnormal window that
                                            ends 120 s after the alarm instead of at
                                            the end of the file
D_ours       ours     ours     ours        the candidate set: our cleaning and the
                                            service allowlist against their
                                            `preprocess`
===========  =======  =======  ==========  =========================================

`A_theirs` is our re-implementation of their formula (`baseline_formulas.py`) run
over their windows, so it should return exactly the ranking their package
returned. The script measures that agreement and prints it first: if the
re-implementation does not reproduce their output, every attribution below it is
worthless, and saying so is more useful than a table that looks fine.

`D_ours` should in turn land where our `NSIGMA` engine lands. The engine is run
too, separately, because the engine is what the paper and the application
actually use; `D_ours` only exists to join it to the ladder.

On the two accuracy conventions. Their `Evaluator` reads service-level AC@k off
the top k **columns**, without removing repeats, so a run whose top three columns
all belong to one service gets one service to match on. Ranking distinct services
instead - our convention, and the one the rest of this project uses - is a
different question. At k=1 they are the same number; above it theirs is stricter.
Both are reported, labelled `_raw` for theirs and `_distinct` for ours, because
quietly picking one would make our method look better or worse for a reason that
has nothing to do with the method.

On indicator accuracy. Open question 6 in `PROGRESS.md` is not settled: DISK,
DELAY and LOSS faults have no matching metric column in RE1-OB. So two indicator
numbers are reported, and neither is called the answer: `strict` uses the 50 CPU
and MEM cases where the adapter has an unambiguous ground truth, and `loose` uses
all 125 by accepting any of the fault type's plausible metrics. The gap between
them is the size of the decision still to be made.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pare import eval_metrics  # noqa: E402
from pare.config import PareConfig  # noqa: E402
from pare.engine import AnalyzeRequest, Window, analyze  # noqa: E402
from pare.eval_metrics import Rank  # noqa: E402
from pare.graph import CallGraph  # noqa: E402

from experiments.adapters.rcaeval import (  # noqa: E402
    SYSTEM_SERVICES,
    Case,
    list_cases,
    load_case,
)
from experiments.baseline_formulas import (  # noqa: E402
    count_non_finite,
    our_nsigma_scores,
    rcaeval_scores,
    their_sort,
)

RUN_ID = "m2_4"

# The ladder, in order. Each entry is (cell name, formula, window, candidates).
LADDER = (
    ("A_theirs", "theirs", "theirs", "theirs"),
    ("B_formula", "ours", "theirs", "theirs"),
    ("C_window", "ours", "ours", "theirs"),
    ("D_ours", "ours", "ours", "ours"),
)

# Our window definitions, from the one window table in `docs/05` section 3 step 2.
NORMAL_GAP_S = 30.0
RECENT_AFTER_S = 120.0


@dataclass(frozen=True)
class Scored:
    """One method's answer on one case, already reduced to ranks."""

    method: str
    case: Case
    delay_s: float
    runtime_s: float
    ranked_columns: tuple[str, ...]
    service_order: tuple[str, ...]
    rank_service_distinct: Rank | None
    rank_service_raw: Rank | None
    rank_indicator_strict: Rank | None
    rank_indicator_loose: Rank | None
    n_candidates: int
    verdict: str = ""
    error: str | None = None
    n_non_finite: int = 0
    """Columns whose score was NaN. Non-zero means the ranking is partly
    arbitrary, because their sort cannot order a NaN (see `their_sort`)."""

    @property
    def top1_service(self) -> str:
        return self.service_order[0] if self.service_order else ""

    @property
    def top1_indicator(self) -> str:
        return self.ranked_columns[0] if self.ranked_columns else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--data-root", type=Path, default=repo_root / "data" / "RCAEval")
    parser.add_argument("--dataset", default="RE1")
    parser.add_argument("--system", default="online-boutique")
    parser.add_argument(
        "--results", type=Path, default=repo_root / "experiments" / "results" / RUN_ID
    )
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    rankings_path = args.results / "rcaeval_rankings.jsonl"
    if not rankings_path.exists():
        print(
            f"{rankings_path} is missing. Run their half first, in their "
            "environment:\n"
            "  experiments/.venv-rcaeval/Scripts/python.exe "
            "experiments/run_rcaeval_baselines.py",
            file=sys.stderr,
        )
        return 2

    cases = list_cases(args.data_root, args.dataset, args.system)
    if args.limit is not None:
        cases = cases[: args.limit]
    by_folder = {(case.path.parent.name, case.run): case for case in cases}

    theirs = _load_rankings(rankings_path, by_folder, args.delay_s)
    if not theirs:
        print("no rankings matched the cases found on disk", file=sys.stderr)
        return 2

    print(f"{len(cases)} cases, {len(theirs)} recorded rankings from their package\n")

    rows: list[Scored] = []

    # --- their package, scored by us ---------------------------------------
    for (case_key, method), record in sorted(theirs.items()):
        case = by_folder[case_key]
        rows.append(
            _score_ranking(
                method=f"RCAEVAL_{method}",
                case=case,
                delay_s=args.delay_s,
                runtime_s=record["runtime_s"],
                ranked_columns=tuple(record["ranked_columns"]),
                # Their functions return the order but not the scores, so ties
                # cannot be seen here. The ladder's A_theirs cell recomputes the
                # same formula with scores and is used for the tie check below.
                scores=None,
                n_candidates=record["n_candidates"],
                error=record["error"],
            )
        )

    # --- the ladder, and our engine ----------------------------------------
    ladder_rows, engine_rows, agreement = _run_ours(
        cases=cases, delay_s=args.delay_s, seed=args.seed
    )
    rows.extend(ladder_rows)
    rows.extend(engine_rows)

    # --- report -------------------------------------------------------------
    args.results.mkdir(parents=True, exist_ok=True)
    _report_agreement(theirs, agreement, args.results)
    summary = _summarise(rows)
    _write_outputs(rows, summary, args)

    report = "\n".join(
        [
            f"--- accuracy on {args.dataset} {args.system}, delay {args.delay_s} s ---",
            _format_summary(summary),
            "",
            "--- the ladder, one step at a time ---",
            _format_ladder(summary),
            "",
            "--- head to head, per case ---",
            _head_to_head(rows, "RCAEVAL_NSIGMA", "NSIGMA"),
        ]
    )
    # Saved as well as printed: hard rule 2 wants every number that reaches a
    # table or a note to come from a file under `experiments/results/`.
    (args.results / "comparison.txt").write_text(report + "\n", encoding="utf-8")

    print()
    print(report)
    print(f"\nwrote {args.results}")
    return 0


def _format_ladder(summary: pd.DataFrame) -> str:
    """What each step of the ladder is worth, which is the point of M2.4.

    An aggregate difference between two methods says nothing about its cause. The
    deltas below each attribute their share of it to one change.
    """
    indexed = summary.set_index("method")
    labels = {
        "B_formula": "formula: their signed max of per-row z -> our mean shift",
        "C_window": "windows: 30 s gap, window ends 120 s after the alarm",
        "D_ours": "candidates: their preprocess -> our cleaning and allowlist",
    }
    width = 62
    lines = [f"{'step':<{width}} {'AC@1':>7} {'ExpAC@1':>8}"]
    previous = "A_theirs"
    lines.append(
        f"{'start: RCAEval NSigma, reproduced':<{width}} "
        f"{indexed.loc[previous, 'ac1']:>7.3f} "
        f"{indexed.loc[previous, 'exp_ac1_strict']:>8.3f}"
    )
    for cell, label in labels.items():
        delta_ac1 = indexed.loc[cell, "ac1"] - indexed.loc[previous, "ac1"]
        delta_exp = (
            indexed.loc[cell, "exp_ac1_strict"] - indexed.loc[previous, "exp_ac1_strict"]
        )
        lines.append(f"{'  + ' + label:<{width}} {delta_ac1:>+7.3f} {delta_exp:>+8.3f}")
        previous = cell
    lines.append(
        f"{'end: our NSIGMA':<{width}} "
        f"{indexed.loc['NSIGMA', 'ac1']:>7.3f} "
        f"{indexed.loc['NSIGMA', 'exp_ac1_strict']:>8.3f}"
    )
    return "\n".join(lines)


def _head_to_head(rows: Sequence[Scored], left: str, right: str) -> str:
    """How the two methods compare case by case, not only on average.

    A gap of twelve points in AC@1 could be a steady improvement or a pile of
    wins cancelling a pile of losses. Only the paired counts tell them apart, so
    they are reported next to the average. The exact binomial test over the
    discordant pairs is McNemar's test, which is the right one for paired
    yes/no outcomes; the paper's full statistics are a separate task (M4.4) and
    this is one descriptive number, not a substitute for them.
    """
    by_case = {
        (row.method, row.case.case_id): row for row in rows if row.method in (left, right)
    }
    shared = sorted(
        {case_id for method, case_id in by_case if method == left}
        & {case_id for method, case_id in by_case if method == right}
    )

    def correct(method: str, case_id: str) -> bool:
        rank = by_case[(method, case_id)].rank_service_distinct
        return rank is not None and rank.hit_fraction(1) == 1.0

    left_only = [c for c in shared if correct(left, c) and not correct(right, c)]
    right_only = [c for c in shared if correct(right, c) and not correct(left, c)]
    both = sum(1 for c in shared if correct(left, c) and correct(right, c))
    neither = len(shared) - both - len(left_only) - len(right_only)

    lines = [
        f"{len(shared)} cases compared on top-1 service:",
        f"  both right: {both}",
        f"  only {left}: {len(left_only)}",
        f"  only {right}: {len(right_only)}",
        f"  both wrong: {neither}",
    ]
    discordant = len(left_only) + len(right_only)
    if discordant:
        from scipy.stats import binomtest

        result = binomtest(len(right_only), discordant, 0.5)
        lines.append(
            f"  McNemar exact test on the {discordant} case(s) they disagree on: "
            f"p = {result.pvalue:.4f}"
        )
    for label, ids in ((f"only {left} right", left_only), (f"only {right} right", right_only)):
        if ids:
            lines.append(f"  {label}: {', '.join(ids[:6])}")
            if len(ids) > 6:
                lines.append(f"      ... and {len(ids) - 6} more")
    return "\n".join(lines)


# --- loading their side -----------------------------------------------------


def _load_rankings(
    path: Path, by_folder: dict, delay_s: float
) -> dict[tuple[tuple[str, str], str], dict]:
    """Read the JSONL and key it by (case, method), keeping only one delay."""
    found: dict[tuple[tuple[str, str], str], dict] = {}
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if float(record["delay_s"]) != float(delay_s):
                continue
            key = (record["case_folder"], record["run"])
            if key not in by_folder:
                skipped += 1
                continue
            found[(key, record["method"])] = record
    if skipped:
        print(f"note: {skipped} recorded rankings had no matching case on disk")
    return found


# --- running our side -------------------------------------------------------


def _run_ours(
    cases: Sequence[Case], delay_s: float, seed: int
) -> tuple[list[Scored], list[Scored], dict]:
    """Run the four ladder cells and our NSIGMA engine over every case."""
    ladder_rows: list[Scored] = []
    engine_rows: list[Scored] = []
    # Per-case full ranking from A_theirs, so the re-implementation can be checked
    # against their real output, and from D_ours and the engine, so the ladder can
    # be checked against the thing it is meant to explain.
    agreement: dict[str, dict[tuple[str, str], tuple[str, ...]]] = {
        "A_theirs": {},
        "D_ours": {},
        "ENGINE": {},
    }

    for position, case in enumerate(cases, start=1):
        frame = pd.read_csv(case.path / "data.csv")
        key = (case.path.parent.name, case.run)

        for cell, formula, window, candidates in LADDER:
            started = time.perf_counter()
            try:
                columns, scores = _score_cell(
                    frame=frame,
                    case=case,
                    delay_s=delay_s,
                    formula=formula,
                    window=window,
                    candidates=candidates,
                )
            except Exception as error:  # noqa: BLE001 - recorded, not hidden
                ladder_rows.append(
                    _empty_scored(cell, case, delay_s, f"{type(error).__name__}: {error}")
                )
                continue
            runtime_s = time.perf_counter() - started

            # Their sort for every cell, not just theirs. Our formula never
            # returns NaN (`pare.scores.nsigma_score` maps it to 0), so for cells
            # B, C and D this is an ordinary stable sort on the score and the
            # choice costs nothing. Using it throughout means the A-to-B step
            # measures the formula alone, with the sort held fixed.
            order = their_sort(columns, scores)
            score_map = dict(zip(columns, scores.tolist(), strict=True))
            row = _score_ranking(
                method=cell,
                case=case,
                delay_s=delay_s,
                runtime_s=runtime_s,
                ranked_columns=tuple(order),
                scores=score_map,
                n_candidates=len(columns),
                error=None,
                n_non_finite=count_non_finite(scores),
            )
            ladder_rows.append(row)
            if cell in agreement:
                agreement[cell][key] = row.ranked_columns

        engine_row = _run_engine(case=case, delay_s=delay_s, seed=seed)
        engine_rows.append(engine_row)
        agreement["ENGINE"][key] = engine_row.ranked_columns

        if position % 25 == 0 or position == len(cases):
            print(f"  ours: {position}/{len(cases)} cases")

    return ladder_rows, engine_rows, agreement


def _score_cell(
    frame: pd.DataFrame,
    case: Case,
    delay_s: float,
    formula: str,
    window: str,
    candidates: str,
) -> tuple[list[str], np.ndarray]:
    """One cell of the ladder: pick the windows, pick the candidates, score."""
    normal_mask, abnormal_mask = _masks(frame["time"], case, delay_s, window)
    if candidates == "theirs":
        columns, normal, abnormal = _their_candidates(frame, normal_mask, abnormal_mask)
    else:
        columns, normal, abnormal = _our_candidates(frame, case, normal_mask, abnormal_mask)

    if formula == "theirs":
        # NSIGMA here, not BARO: the ladder explains the gap to *our* NSIGMA, and
        # BARO's own gap to it is one scaler further away. BARO is reported in the
        # accuracy table, which is what M2.4 asks of it.
        scores = rcaeval_scores(normal, abnormal, method="NSIGMA")
    else:
        scores = our_nsigma_scores(normal, abnormal)
    return columns, np.asarray(scores, dtype=np.float64)


def _masks(
    times: pd.Series, case: Case, delay_s: float, window: str
) -> tuple[pd.Series, pd.Series]:
    """Row masks for the normal and abnormal windows under one convention."""
    inject = float(case.inject_time_sec)
    alarm = inject + delay_s
    if window == "theirs":
        # Their functions split on the one time they are given: everything before
        # it is normal, everything from it to the end of the file is abnormal.
        return times < alarm, times >= alarm
    return (
        times < inject - NORMAL_GAP_S,
        (times >= alarm) & (times <= alarm + RECENT_AFTER_S),
    )


def _their_candidates(
    frame: pd.DataFrame, normal_mask: pd.Series, abnormal_mask: pd.Series
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Their `preprocess`, faithful to `RCAEval/io/time_series.py`.

    Applied to each window separately and then intersected, which is what they do
    and is not the same as applying it once to the whole file: a column held
    constant only during the incident survives in normal and vanishes from
    abnormal, so it leaves the candidate set.

    `convert_mem_mb` is kept even though it cannot change their own ranking -
    both their scalers are scale-invariant, so dividing a column by 1e6 leaves
    every z-score untouched. It can move ours by a hair, because our epsilon is
    proportional to the metric's level, and that is exactly the sort of thing the
    candidate step of the ladder is there to absorb.
    """
    normal = _their_preprocess(frame[normal_mask])
    abnormal = _their_preprocess(frame[abnormal_mask])
    shared = [c for c in normal.columns if c in abnormal.columns]
    return (
        shared,
        normal[shared].to_numpy(dtype=float),
        abnormal[shared].to_numpy(dtype=float),
    )


def _their_preprocess(frame: pd.DataFrame) -> pd.DataFrame:
    """`drop_constant(drop_time(df))` then `convert_mem_mb`, as they have it."""
    frame = frame.drop(columns=[c for c in ("time.1", "time", "Time") if c in frame])
    if len(frame) == 0:
        return frame
    # drop_constant: keep a column only if some row differs from the first row.
    frame = frame.loc[:, (frame != frame.iloc[0]).any()]
    memory = [c for c in frame.columns if c.endswith("_mem")]
    if memory:
        frame = frame.copy()
        frame[memory] = frame[memory] / 1e6
    return frame


def _our_candidates(
    frame: pd.DataFrame, case: Case, normal_mask: pd.Series, abnormal_mask: pd.Series
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Our cleaning: the adapter's allowlist, then `pare.preprocess`."""
    from pare.columns import ColumnInfo
    from pare.preprocess import preprocess

    known = SYSTEM_SERVICES.get(case.system)
    keep: list[ColumnInfo] = []
    for name in frame.columns:
        if name == "time" or name.split(".")[0] == "time":
            continue
        service, _, metric = name.rpartition("_")
        if not service or not metric:
            continue
        if known is not None and service not in known:
            continue
        keep.append(ColumnInfo(name=name, service=service, metric=metric))

    names = [column.name for column in keep]
    clean = preprocess(
        normal=frame.loc[normal_mask, names].to_numpy(dtype=float),
        recent=frame.loc[abnormal_mask, names].to_numpy(dtype=float),
        columns=keep,
    )
    return (
        [column.name for column in clean.columns],
        clean.normal,
        clean.recent,
    )


def _run_engine(case: Case, delay_s: float, seed: int) -> Scored:
    """Our `NSIGMA` engine, through the adapter, exactly as an experiment runs it."""
    started = time.perf_counter()
    try:
        data = load_case(case, delay_s=delay_s, graph=CallGraph.empty())
        names = [column.name for column in data.columns]
        request = AnalyzeRequest(
            engine="NSIGMA",
            alarm_time_sec=data.alarm_time_sec,
            columns=data.columns,
            normal=Window.of(
                data.normal["time"].to_numpy(dtype=float),
                data.normal[names].to_numpy(dtype=float),
            ),
            recent=Window.of(
                data.recent["time"].to_numpy(dtype=float),
                data.recent[names].to_numpy(dtype=float),
            ),
            graph=data.graph,
            # `top_k` only sets how many indicators come back, never what the
            # engine computes (`docs/05` section 1.1), so raising it does not
            # change the method - it just makes the whole ranking visible, which
            # the indicator ranks here need. The default 10 would silently cap
            # every rank at 10 and flatter the method.
            config=PareConfig(seed=seed, top_k=10_000),
        )
        result = analyze(request)
    except Exception as error:  # noqa: BLE001 - recorded, not hidden
        return _empty_scored("NSIGMA", case, delay_s, f"{type(error).__name__}: {error}")

    runtime_s = time.perf_counter() - started
    columns = tuple(indicator.column for indicator in result.indicators)
    scores = {
        indicator.column: indicator.self_score for indicator in result.indicators
    }
    service_order = tuple(service.service for service in result.services)
    service_scores = {service.service: service.score for service in result.services}

    return Scored(
        method="NSIGMA",
        case=case,
        delay_s=delay_s,
        runtime_s=runtime_s,
        ranked_columns=columns,
        service_order=service_order,
        rank_service_distinct=eval_metrics.rank_in_order(
            service_order, service_scores, case.gt_service
        ),
        # Their convention needs the full column ranking, and the engine returns
        # only the top `top_k` indicators. Left as None rather than filled with a
        # guess; the `_raw` column for the engine is therefore blank, and the
        # ladder's D_ours cell is the row to read it from.
        rank_service_raw=None,
        rank_indicator_strict=(
            eval_metrics.rank_in_order(columns, scores, case.gt_indicator)
            if case.gt_indicator
            else None
        ),
        rank_indicator_loose=_best_rank(columns, scores, case.acceptable_indicators),
        n_candidates=len(result.indicators),
        verdict=result.verdict,
    )


# --- scoring ----------------------------------------------------------------


def _score_ranking(
    method: str,
    case: Case,
    delay_s: float,
    runtime_s: float,
    ranked_columns: tuple[str, ...],
    scores: dict[str, float] | None,
    n_candidates: int,
    error: str | None,
    n_non_finite: int = 0,
) -> Scored:
    """Turn a column ranking into the ranks every metric is computed from."""
    if error is not None or not ranked_columns:
        return _empty_scored(method, case, delay_s, error)

    score_map = scores or {}
    services_raw = [_service_of(column) for column in ranked_columns]
    # First appearance of each service, which is the same order as sorting
    # services by their best column's score, and is our service ranking.
    seen: dict[str, None] = {}
    for service in services_raw:
        seen.setdefault(service, None)
    service_order = tuple(seen)
    service_scores = {
        service: max(
            score_map.get(column, 0.0)
            for column, owner in zip(ranked_columns, services_raw, strict=True)
            if owner == service
        )
        for service in service_order
    }

    return Scored(
        method=method,
        case=case,
        delay_s=delay_s,
        runtime_s=runtime_s,
        ranked_columns=ranked_columns,
        service_order=service_order,
        rank_service_distinct=eval_metrics.rank_in_order(
            service_order, service_scores if scores else {}, case.gt_service
        ),
        rank_service_raw=_raw_service_rank(services_raw, case.gt_service),
        rank_indicator_strict=(
            eval_metrics.rank_in_order(ranked_columns, score_map, case.gt_indicator)
            if case.gt_indicator
            else None
        ),
        rank_indicator_loose=_best_rank(
            ranked_columns, score_map, case.acceptable_indicators
        ),
        n_candidates=n_candidates,
        error=None,
        n_non_finite=n_non_finite,
    )


def _raw_service_rank(services_in_column_order: list[str], gt_service: str) -> Rank | None:
    """Their `Evaluator`'s convention: the service of the k-th column, repeats kept.

    Scored as a plain position with no tie group, because the repetition is not a
    tie - their ranking really did put those columns in that order.
    """
    if gt_service not in services_in_column_order:
        return None
    return Rank(best=services_in_column_order.index(gt_service) + 1, tied=1)


def _best_rank(
    ordered: Sequence[str], scores: dict[str, float], acceptable: Sequence[str]
) -> Rank | None:
    """The best rank any acceptable answer reached.

    Used for the loose indicator number, where a fault type has several plausible
    indicators and getting any of them counts (open question 6).
    """
    ranks = [
        rank
        for rank in (eval_metrics.rank_in_order(ordered, scores, name) for name in acceptable)
        if rank is not None
    ]
    if not ranks:
        return None
    return min(ranks, key=lambda rank: (rank.best, -rank.tied))


def _empty_scored(method: str, case: Case, delay_s: float, error: str | None) -> Scored:
    return Scored(
        method=method,
        case=case,
        delay_s=delay_s,
        runtime_s=0.0,
        ranked_columns=(),
        service_order=(),
        rank_service_distinct=None,
        rank_service_raw=None,
        rank_indicator_strict=None,
        rank_indicator_loose=None,
        n_candidates=0,
        error=error,
    )


def _service_of(column: str) -> str:
    """The service a raw column name belongs to.

    Splitting a column name is exactly what the adapter forbids *inside* the
    algorithm, and for good reason. It is unavoidable here: their methods rank raw
    column names and return nothing else, so scoring their output at service level
    has to recover the service from the name. Their own `Evaluator` does the same
    thing through `Node(entity, metric)`. It stays in this one scoring helper and
    never reaches an engine.
    """
    return column.rpartition("_")[0] or column


# --- summarising ------------------------------------------------------------


def _summarise(rows: Sequence[Scored]) -> pd.DataFrame:
    """One row per method: the accuracy numbers under both conventions."""
    out: list[dict[str, object]] = []
    for method in dict.fromkeys(row.method for row in rows):
        group = [row for row in rows if row.method == method]
        distinct = [row.rank_service_distinct for row in group]
        raw = [row.rank_service_raw for row in group]
        strict = [
            row.rank_indicator_strict
            for row in group
            if row.case.indicator_is_unambiguous
        ]
        loose = [row.rank_indicator_loose for row in group]
        failed = sum(1 for row in group if row.error is not None)

        out.append(
            {
                "method": method,
                "cases": len(group),
                "failed": failed,
                "ac1": eval_metrics.ac_at_k(distinct, 1),
                "ac3_distinct": eval_metrics.ac_at_k(distinct, 3),
                "avg5_distinct": eval_metrics.avg_at_5(distinct),
                "ac3_raw": (
                    eval_metrics.ac_at_k(raw, 3) if any(r is not None for r in raw) else None
                ),
                "avg5_raw": (
                    eval_metrics.avg_at_5(raw) if any(r is not None for r in raw) else None
                ),
                "exp_ac1_strict": eval_metrics.exp_ac_at_k(strict, 1) if strict else None,
                "exp_ac3_strict": eval_metrics.exp_ac_at_k(strict, 3) if strict else None,
                "strict_cases": len(strict),
                "exp_ac1_loose": eval_metrics.exp_ac_at_k(loose, 1),
                "exp_ac3_loose": eval_metrics.exp_ac_at_k(loose, 3),
                "mean_candidates": float(np.mean([row.n_candidates for row in group])),
                "mean_ms": float(np.mean([row.runtime_s for row in group]) * 1000.0),
                # Cases where at least one column scored NaN, so the method's own
                # sort had no valid ordering to work with and part of the ranking
                # is arbitrary. Reported per method because it is a property of
                # the method, not of the data.
                "cases_with_nan_score": sum(1 for row in group if row.n_non_finite),
            }
        )
    return pd.DataFrame(out).round(4)


def _format_summary(summary: pd.DataFrame) -> str:
    shown = summary[
        [
            "method",
            "cases",
            "ac1",
            "ac3_distinct",
            "avg5_distinct",
            "ac3_raw",
            "exp_ac1_strict",
            "exp_ac1_loose",
            "mean_candidates",
            "cases_with_nan_score",
            "mean_ms",
        ]
    ]
    return shown.to_string(index=False)


def _report_agreement(
    theirs: dict, agreement: dict[str, dict[tuple[str, str], str]], results: Path
) -> None:
    """Print, and save, how well each of our stand-ins matches what it stands for.

    Two checks, and the first one gates the second. If `A_theirs` does not
    reproduce their package's own top-1, the ladder is not measuring what it
    claims to and the printed attribution should not be believed.
    """
    lines: list[str] = []

    their_rankings = {
        case_key: tuple(record["ranked_columns"])
        for (case_key, method), record in theirs.items()
        if method == "NSIGMA" and record["ranked_columns"]
    }
    checks = [
        (
            "A_theirs reproduces RCAEval's NSigma",
            their_rankings,
            agreement["A_theirs"],
        ),
        (
            "D_ours matches our NSIGMA engine",
            agreement["ENGINE"],
            agreement["D_ours"],
        ),
    ]
    for label, expected, actual in checks:
        shared = sorted(set(expected) & set(actual))
        total = len(shared)
        same_top1 = sum(1 for key in shared if expected[key][:1] == actual[key][:1])
        # The full ranking is the stronger check and the one to lead with: two
        # methods can agree on first place and disagree everywhere else.
        comparable = [
            key for key in shared if set(expected[key]) == set(actual[key])
        ]
        same_full = sum(1 for key in comparable if expected[key] == actual[key])
        share = same_top1 / total if total else 0.0
        lines.append(f"{label}: top-1 identical on {same_top1}/{total} ({share:.1%})")
        if comparable:
            lines.append(
                f"    full ranking identical on {same_full}/{len(comparable)} of the "
                f"cases whose candidate sets match"
            )
        if len(comparable) < total:
            lines.append(
                f"    {total - len(comparable)} case(s) ranked a different set of "
                f"columns, so only top-1 is comparable there"
            )
        differing = [key for key in shared if expected[key][:1] != actual[key][:1]]
        for key in differing[:5]:
            lines.append(
                f"    {key[0]}/{key[1]}: expected {expected[key][0]!r}, "
                f"got {actual[key][0]!r}"
            )
        if len(differing) > 5:
            lines.append(f"    ... and {len(differing) - 5} more")

    print("--- do our stand-ins stand in? ---")
    print("\n".join(lines))
    (results / "agreement.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- writing ----------------------------------------------------------------


def _write_outputs(rows: Sequence[Scored], summary: pd.DataFrame, args) -> None:
    """`cases.csv` to the contract, plus the files M2.4 owns."""
    contract: list[dict[str, object]] = []
    extra: list[dict[str, object]] = []
    for row in rows:
        contract.append(
            {
                "run_id": RUN_ID,
                "dataset": row.case.dataset,
                "system": row.case.system,
                "case_id": row.case.case_id,
                "fault_type": row.case.fault_type,
                "gt_service": row.case.gt_service,
                "gt_indicator": row.case.gt_indicator or "",
                "method": row.method,
                "delay_s": row.delay_s,
                "seed": args.seed,
                "rank_gt_service": _best(row.rank_service_distinct),
                "rank_gt_indicator": _best(row.rank_indicator_strict),
                "top1_service": row.top1_service,
                "top1_indicator": row.top1_indicator,
                "tied_gt_service": _tied(row.rank_service_distinct),
                "tied_gt_indicator": _tied(row.rank_indicator_strict),
                # No call graph exists for RE1 until M2.5, so there is nothing to
                # decide "is this an ancestor of the cause" with. Left empty, as
                # `docs/06` section 5 says to when there is no graph.
                "symptom_error": "",
                "verdict": row.verdict,
                "runtime_s": round(row.runtime_s, 4),
            }
        )
        extra.append(
            {
                "run_id": RUN_ID,
                "case_id": row.case.case_id,
                "fault_type": row.case.fault_type,
                "method": row.method,
                "indicator_unambiguous": row.case.indicator_is_unambiguous,
                "rank_gt_indicator_loose": _best(row.rank_indicator_loose),
                "tied_gt_indicator_loose": _tied(row.rank_indicator_loose),
                "acceptable_indicators": ";".join(row.case.acceptable_indicators),
                "rank_gt_service_raw": _best(row.rank_service_raw),
                "n_candidates": row.n_candidates,
                "error": row.error or "",
            }
        )

    args.results.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(contract).to_csv(args.results / "cases.csv", index=False)
    # The loose indicator scoring and their service convention live in their own
    # file: `cases.csv` follows `docs/06` section 5 exactly, and open question 6
    # is not settled, so neither belongs in the contract yet.
    pd.DataFrame(extra).to_csv(args.results / "indicator_scoring.csv", index=False)
    summary.to_csv(args.results / "summary.csv", index=False)

    by_fault = _by_fault(rows)
    by_fault.to_csv(args.results / "summary_by_fault.csv", index=False)

    (args.results / "config.json").write_text(
        json.dumps(
            {
                "script": Path(__file__).name,
                "run_id": RUN_ID,
                "dataset": args.dataset,
                "system": args.system,
                "delay_s": args.delay_s,
                "seed": args.seed,
                "limit": args.limit,
                "normal_gap_s": NORMAL_GAP_S,
                "recent_after_s": RECENT_AFTER_S,
                "ladder": [list(cell) for cell in LADDER],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_env(args.results / "env-analyzer.txt")


def _by_fault(rows: Sequence[Scored]) -> pd.DataFrame:
    """AC@1 per method and fault type, which is where the methods differ most."""
    out: list[dict[str, object]] = []
    for method in dict.fromkeys(row.method for row in rows):
        for fault in sorted({row.case.fault_type for row in rows}):
            group = [
                row for row in rows if row.method == method and row.case.fault_type == fault
            ]
            if not group:
                continue
            out.append(
                {
                    "method": method,
                    "fault_type": fault,
                    "cases": len(group),
                    "ac1": round(
                        eval_metrics.ac_at_k([r.rank_service_distinct for r in group], 1), 4
                    ),
                    "avg5": round(
                        eval_metrics.avg_at_5([r.rank_service_distinct for r in group]), 4
                    ),
                }
            )
    return pd.DataFrame(out)


def _best(rank: Rank | None) -> object:
    return "" if rank is None else rank.best


def _tied(rank: Rank | None) -> object:
    return "" if rank is None else rank.tied


def _write_env(path: Path) -> None:
    lines = [
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"machine: {platform.machine()}",
    ]
    from importlib.metadata import PackageNotFoundError, version

    for package in ("pare", "numpy", "pandas", "scikit-learn", "scipy", "ruptures"):
        try:
            lines.append(f"{package}: {version(package)}")
        except PackageNotFoundError:
            lines.append(f"{package}: not installed")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
