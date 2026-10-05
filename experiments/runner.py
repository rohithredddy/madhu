"""The shared core of every experiment runner: run one engine on one case, score it.

From M3 onward the experiment scripts (`run_c1_grounding.py`, and `run_rca.py`
when it arrives) all need the same three things: load a case, run an engine on it,
and reduce the answer to the row `docs/06` section 5 specifies. Doing that in each
script would mean several implementations of AC@k, and the first time two of them
disagreed there would be no way to say which number the paper should print. So it
lives here once.

What this module is **not**: it is not where a particular experiment's choices go.
Which engines run, which delays, which cases, and how the results are summarised
belong to the script for that experiment. This module only knows how to produce
one honest row.

Three rules are enforced here rather than left to each caller, because each is a
rule the project cannot afford to break by accident:

* **Ground truth never reaches an engine** (hard rule 4). The request is built from
  the case's data and nothing else; the answer is used only after the engine has
  returned. A test checks the request carries no hint of it.
* **A failure is recorded, not hidden** (`docs/08` section 8). An engine that
  raises produces a row with the error in it, so a method that crashes on 20 cases
  cannot look like a method that scored badly on 105.
* **Ties are scored as ties** (`docs/08` section 4). The rank is the best position
  the tied group occupies plus its size, so a saturating method is not rewarded or
  punished by the alphabetical order of column names.
"""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pandas as pd
import yaml
from pare import eval_metrics
from pare.config import PareConfig
from pare.engine import AnalyzeRequest, Window, analyze
from pare.eval_metrics import Rank
from pare.graph import CallGraph

from experiments.adapters.rcaeval import Case, CaseData, load_case

# The columns of `cases.csv`, in the order `docs/06` section 5 lists them. Kept as
# a constant so a test can assert the written file matches the contract rather
# than trusting that it still does.
CASES_CSV_COLUMNS = (
    "run_id",
    "dataset",
    "system",
    "case_id",
    "fault_type",
    "gt_service",
    "gt_indicator",
    "method",
    "delay_s",
    "seed",
    "rank_gt_service",
    "rank_gt_indicator",
    "rank_gt_indicator_loose",
    "top1_service",
    "top1_indicator",
    "tied_gt_service",
    "tied_gt_indicator",
    "tied_gt_indicator_loose",
    "symptom_error",
    "tied_top1",
    "symptom_share",
    "symptom_chance",
    "verdict",
    "runtime_s",
)


@dataclass(frozen=True)
class CaseRow:
    """One (case, method, delay) result, in the shape the contract asks for.

    Every field is already a plain value, so a list of these goes straight into a
    DataFrame. A rank that does not exist is an empty string rather than 0 or NaN,
    because `docs/06` says a missing number is empty and because 0 would read as a
    real rank.
    """

    run_id: str
    dataset: str
    system: str
    case_id: str
    fault_type: str
    gt_service: str
    gt_indicator: str
    method: str
    delay_s: float
    seed: int
    rank_gt_service: object
    rank_gt_indicator: object
    rank_gt_indicator_loose: object
    top1_service: str
    top1_indicator: str
    tied_gt_service: object
    tied_gt_indicator: object
    tied_gt_indicator_loose: object
    symptom_error: object
    tied_top1: object
    """How many services share the rank-1 score (1 means no tie). When it is more
    than 1, ``top1_service`` and ``symptom_error`` describe whichever of them the
    engine happened to list first, which is an accident of naming."""

    symptom_share: object
    """The share of the rank-1 tie group that calls the culprit: the chance of a
    symptom error if the tie were broken at random. Equals ``symptom_error`` as
    1.0 / 0.0 when there is no tie. Empty when there is no graph."""

    symptom_chance: object
    """Of the services ranked other than the culprit, the share that call it: the
    symptom rate a wrong answer picked at random would have on this case. The
    floor a symptom rate has to be read against. Empty when there is no graph."""

    verdict: str
    runtime_s: float
    error: str = ""
    """Empty when the engine returned. Not part of the contract's column list, so
    it is written to its own file rather than into `cases.csv`."""

    def contract_row(self) -> dict[str, object]:
        """Just the contract's columns, in the contract's order."""
        data = asdict(self)
        return {name: data[name] for name in CASES_CSV_COLUMNS}


def run_case(
    case: Case,
    engine: str,
    run_id: str,
    delay_s: float = 0.0,
    graph: CallGraph | None = None,
    config: PareConfig | None = None,
    normal_mode: str = "inject_gap",
) -> CaseRow:
    """Run one engine on one case and score the answer.

    Args:
        case: From `adapters.rcaeval.list_cases`.
        engine: An engine name from the registry in `pare.engine`.
        run_id: The run folder's name, carried into every row.
        delay_s: How late the alarm is assumed to be. The engine is told only the
            alarm time, never the injection time.
        graph: The call graph. Passed to the engine, which ignores it for any
            method whose `EngineSpec.use_graph` is False - that switch lives in the
            engine so a caller cannot hand a baseline the one thing the proposed
            method is supposed to contribute. The graph is **always** used for
            scoring `symptom_error`, because "was the service we blamed a caller of
            the real culprit" is a question about the system, not about what the
            engine was told.
        config: Engine parameters. `top_k` is raised if it is at the default,
            because a rank beyond 10 cannot be measured from a list of 10 and the
            cap would silently flatter every method.
        normal_mode: Passed through to the adapter. ``"inject_gap"`` is the
            standard RCAEval protocol; ``"alarm_lookback"`` is the honest variant
            `docs/08` section 4 asks E3 to report alongside.
    """
    settings = config or PareConfig()
    if settings.top_k == PareConfig().top_k:
        settings = replace(settings, top_k=10_000)

    scoring_graph = graph if graph is not None else CallGraph.empty()
    started = time.perf_counter()
    try:
        data = load_case(
            case, delay_s=delay_s, graph=scoring_graph, normal_mode=normal_mode
        )
        result = analyze(_request_for(data, engine, settings))
    except Exception as error:  # noqa: BLE001 - recorded, never hidden
        return _failed_row(
            case, engine, run_id, delay_s, settings.seed,
            f"{type(error).__name__}: {error}",
            round(time.perf_counter() - started, 4),
        )

    runtime_s = round(time.perf_counter() - started, 4)

    service_order = tuple(item.service for item in result.services)
    service_scores = {item.service: item.score for item in result.services}
    columns = tuple(item.column for item in result.indicators)
    column_scores = {item.column: item.self_score for item in result.indicators}

    rank_service = eval_metrics.rank_in_order(
        service_order, service_scores, case.gt_service
    )
    rank_strict = (
        eval_metrics.rank_in_order(columns, column_scores, case.gt_indicator)
        if case.gt_indicator
        else None
    )
    rank_loose = _best_rank(columns, column_scores, case.acceptable_indicators)

    top1_service = service_order[0] if service_order else ""
    # The fine-grained answer is the loudest column **of the service ranked
    # first** (`docs/05` step 5), which is not always the globally loudest one:
    # the traversal step can put a service at rank 1 that another outscores.
    top1_indicator = next(
        (item.column for item in result.indicators if item.service == top1_service),
        columns[0] if columns else "",
    )
    symptom = eval_metrics.symptom_error(
        top1_service or None, case.gt_service, scoring_graph
    )
    # Ties at rank 1 are scored as ties here too (docs/08 section 4): which of
    # several equally scored services is listed first says nothing about the
    # method, so the symptom question is asked of the whole group.
    top_group = eval_metrics.top_tie_group(service_order, service_scores)
    share = eval_metrics.symptom_share(top_group, case.gt_service, scoring_graph)
    chance = eval_metrics.symptom_chance(service_order, case.gt_service, scoring_graph)

    return CaseRow(
        run_id=run_id,
        dataset=case.dataset,
        system=case.system,
        case_id=case.case_id,
        fault_type=case.fault_type,
        gt_service=case.gt_service,
        gt_indicator=case.gt_indicator or "",
        method=engine,
        delay_s=delay_s,
        seed=settings.seed,
        rank_gt_service=_best(rank_service),
        rank_gt_indicator=_best(rank_strict),
        rank_gt_indicator_loose=_best(rank_loose),
        top1_service=top1_service,
        top1_indicator=top1_indicator,
        tied_gt_service=_tied(rank_service),
        tied_gt_indicator=_tied(rank_strict),
        tied_gt_indicator_loose=_tied(rank_loose),
        symptom_error="" if symptom is None else symptom,
        tied_top1=len(top_group) if top_group else "",
        symptom_share="" if share is None else round(share, 6),
        symptom_chance="" if chance is None else round(chance, 6),
        verdict=result.verdict,
        runtime_s=runtime_s,
    )


def _request_for(data: CaseData, engine: str, settings: PareConfig) -> AnalyzeRequest:
    """Build the engine's input. Ground truth is not among it - see hard rule 4.

    Everything here comes from `data.normal`, `data.recent`, `data.columns` and
    `data.graph`. `data.case`, which holds the answer, is deliberately not touched.
    """
    names = [column.name for column in data.columns]
    return AnalyzeRequest(
        engine=engine,
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
        config=settings,
    )


def _failed_row(
    case: Case,
    engine: str,
    run_id: str,
    delay_s: float,
    seed: int,
    error: str,
    runtime_s: float,
) -> CaseRow:
    return CaseRow(
        run_id=run_id,
        dataset=case.dataset,
        system=case.system,
        case_id=case.case_id,
        fault_type=case.fault_type,
        gt_service=case.gt_service,
        gt_indicator=case.gt_indicator or "",
        method=engine,
        delay_s=delay_s,
        seed=seed,
        rank_gt_service="",
        rank_gt_indicator="",
        rank_gt_indicator_loose="",
        top1_service="",
        top1_indicator="",
        tied_gt_service="",
        tied_gt_indicator="",
        tied_gt_indicator_loose="",
        symptom_error="",
        tied_top1="",
        symptom_share="",
        symptom_chance="",
        verdict="",
        runtime_s=runtime_s,
        error=error,
    )


def _best_rank(
    ordered: Sequence[str], scores: dict[str, float], acceptable: Sequence[str]
) -> Rank | None:
    """The best rank any acceptable indicator reached.

    The loose indicator score from `docs/08` section 4. For CPU and MEM the
    acceptable set has one member, so this equals the strict rank; for the other
    fault types it is the only score that can be computed at all.
    """
    ranks = [
        rank
        for rank in (
            eval_metrics.rank_in_order(ordered, scores, name) for name in acceptable
        )
        if rank is not None
    ]
    if not ranks:
        return None
    return min(ranks, key=lambda rank: (rank.best, -rank.tied))


def _best(rank: Rank | None) -> object:
    return "" if rank is None else rank.best


def _tied(rank: Rank | None) -> object:
    return "" if rank is None else rank.tied


# --- metrics ----------------------------------------------------------------


def ranks_from(frame: pd.DataFrame, best: str, tied: str) -> list[Rank | None]:
    """Rebuild the `Rank` objects a metric needs from two columns of `cases.csv`.

    A case whose truth was never ranked becomes None, which `ac_at_k` counts as a
    miss. That is the honest reading - the method did not name it - and it keeps
    the denominator at the number of cases rather than the number of successes.
    """
    out: list[Rank | None] = []
    for best_value, tied_value in zip(frame[best], frame[tied], strict=True):
        if str(best_value) in ("", "nan", "None"):
            out.append(None)
        else:
            out.append(Rank(best=int(float(best_value)), tied=int(float(tied_value))))
    return out


def wrong_probabilities(frame: pd.DataFrame) -> list[float]:
    """Per case, the chance the top-1 service is wrong, ties scored as ties.

    ``1 - AC@1`` contribution of each case, so these sum to ``(1 - AC@1) x cases``
    exactly. A case whose culprit was never ranked is wrong with certainty.
    """
    return [
        1.0 if rank is None else 1.0 - rank.hit_fraction(1)
        for rank in ranks_from(frame, "rank_gt_service", "tied_gt_service")
    ]


def symptom_rate(frame: pd.DataFrame) -> float | None:
    """The share of wrong top-1 answers that blamed a caller of the real culprit.

    A thin adapter over :func:`pare.eval_metrics.expected_symptom_rate`, which owns
    the definition, so there is one implementation of it in the project. Rank-1
    ties are scored as ties: each case contributes the share of its rank-1 tie
    group that calls the culprit, over its chance of being wrong. With no ties
    this is exactly "symptom errors / wrong top-1".

    Returns None when nothing was wrong or no graph was available: a rate over an
    empty denominator is not 0.
    """
    shares: list[float | None] = [
        None if str(value) in ("", "nan", "None") else float(value)
        for value in frame["symptom_share"]
    ]
    return eval_metrics.expected_symptom_rate(shares, wrong_probabilities(frame))


def symptom_rate_chance(frame: pd.DataFrame) -> float | None:
    """The symptom rate random wrong answers would score on the same cases.

    Each judged case's `symptom_chance`, weighted by its chance of being wrong -
    the same weights :func:`symptom_rate` divides by - so the two are computed over
    exactly the same mix of cases and can be set side by side.
    """
    pairs = [
        (float(chance), wrong)
        for chance, share, wrong in zip(
            frame["symptom_chance"],
            frame["symptom_share"],
            wrong_probabilities(frame),
            strict=True,
        )
        if str(share) not in ("", "nan", "None") and str(chance) not in ("", "nan", "None")
    ]
    total = sum(wrong for _, wrong in pairs)
    if total <= 0:
        return None
    return sum(chance * wrong for chance, wrong in pairs) / total


# --- writing a run ----------------------------------------------------------


def write_run(
    rows: Sequence[CaseRow],
    results_dir: Path,
    config: dict,
    log_lines: Sequence[str] = (),
) -> None:
    """Write `cases.csv` and the three files `docs/08` section 8 requires beside it.

    `config.yaml` is the configuration as it was actually used, not as it was
    written: a run that defaulted something records the default, so re-running from
    the saved file reproduces it.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    contract = pd.DataFrame([row.contract_row() for row in rows])
    # Column order is part of the contract, so it is set rather than hoped for.
    contract = contract.reindex(columns=list(CASES_CSV_COLUMNS))
    contract.to_csv(results_dir / "cases.csv", index=False)

    failures = [row for row in rows if row.error]
    pd.DataFrame(
        [
            {
                "run_id": row.run_id,
                "case_id": row.case_id,
                "method": row.method,
                "delay_s": row.delay_s,
                "error": row.error,
            }
            for row in failures
        ]
    ).to_csv(results_dir / "failures.csv", index=False)

    (results_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    (results_dir / "env.txt").write_text(environment_report(), encoding="utf-8")
    if log_lines:
        (results_dir / "log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8"
        )


def environment_report() -> str:
    """Python, platform and package versions, for the `env.txt` beside every run."""
    from importlib.metadata import PackageNotFoundError, version

    lines = [
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"machine: {platform.machine()}",
        f"cpu_count: {_cpu_count()}",
    ]
    for package in (
        "pare",
        "numpy",
        "pandas",
        "scikit-learn",
        "scipy",
        "shap",
        "lightgbm",
        "ruptures",
        "networkx",
        "joblib",
    ):
        try:
            lines.append(f"{package}: {version(package)}")
        except PackageNotFoundError:
            lines.append(f"{package}: not installed")
    return "\n".join(lines) + "\n"


def _cpu_count() -> int:
    import os

    return os.cpu_count() or 0
