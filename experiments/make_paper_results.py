"""The paper's remaining tables and figures, from finished runs only (M4.3-M4.5, M5.4, M6.2).

Like make_tables.py and make_figures.py this reads result files and never runs an
engine on benchmark data - except Figure 1, which re-runs PARE on the single case
it shows, to get the per-service scores that cases.csv does not keep. Every part
skips with a message when its results are missing, so it can run at any time.

    analyzer/.venv/Scripts/python.exe experiments/make_paper_results.py

Writes:
  paper/tables/table3_e2_accuracy.{md,tex}   E2: accuracy per method, delay 0
  paper/tables/table4_e4_graph.{md,tex}      E4: PARE with four graphs
  paper/tables/table6_e6_synthetic.{md,tex}  E6: AC@1 per factor level
  paper/figures/fig1_motivating_example.{png,pdf}
  paper/figures/fig2_avg5_vs_delay.{png,pdf}
  paper/figures/fig6_e6_synthetic.{png,pdf}
  paper/notes/fig1_case.txt                  which case Figure 1 shows, and one PARE miss
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.make_figures import GRID, INK, INK_SECONDARY, SURFACE  # noqa: E402
from experiments.make_tables import Table, _num  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "experiments" / "results"
TABLES = REPO / "paper" / "tables"
FIGURES = REPO / "paper" / "figures"
NOTES = REPO / "paper" / "notes"

# Display names. Engine names stay in brackets in tables so a row traces to code.
NAMES = {
    "PARE": "PARE (proposed)",
    "PARE_LGBM": "PARE, LightGBM dependency model",
    "PARE_NO_RESIDUAL": "PARE without residuals",
    "PARE_NO_CP": "PARE without change point",
    "NSIGMA": "N-sigma (ours, robust)",
    "SHAP_IFOREST": "Isolation Forest + TreeSHAP",
    "ECDF": "ECDF tail score",
    "PCA_RECON": "PCA reconstruction",
    "RCAEVAL_NSIGMA": "RCAEval NSigma",
    "RCAEVAL_BARO": "RCAEval BARO",
    "RCAEVAL_CIRCA": "RCAEval CIRCA",
    "RCAEVAL_E_DIAGNOSIS": "RCAEval epsilon-Diagnosis",
    "RCAEVAL_PC_PAGERANK": "RCAEval PC-PageRank",
    "RCAEVAL_RCD": "RCAEval RCD",
}
# Line colours for the figures: PARE stands out, ablations muted, baselines distinct.
LINE = {
    "PARE": "#c4302b",
    "PARE_NO_CP": "#eda100",
    "PARE_NO_RESIDUAL": "#9a9890",
    "NSIGMA": "#2a78d6",
    "SHAP_IFOREST": "#1baf7a",
    "ECDF": "#7d5ba6",
    "PCA_RECON": "#eb6834",
    "RCAEVAL_NSIGMA": "#6aa7ee",
    "RCAEVAL_BARO": "#eb6834",
    "RCAEVAL_CIRCA": "#52514e",
}


def _read(run: str, name: str = "summary.csv") -> pd.DataFrame | None:
    path = RESULTS / run / name
    if not path.exists():
        print(f"  skipped: {path.relative_to(REPO)} is missing")
        return None
    return pd.read_csv(path)


def _write_table(name: str, table: Table) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{name}.md").write_text(table.markdown(), encoding="utf-8", newline="\n")
    (TABLES / f"{name}.tex").write_text(table.latex(), encoding="utf-8", newline="\n")
    print(f"  wrote {name}.md/.tex")


def _save(fig, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(FIGURES / f"{name}.{suffix}", facecolor=SURFACE,
                    metadata={"CreationDate": None} if suffix == "pdf" else None)
    plt.close(fig)
    print(f"  wrote {name}.png/.pdf")


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=7)


# --- Table 3: E2 accuracy ---------------------------------------------------------


def _accuracy_rows(frame: pd.DataFrame, order: list[str]) -> list[tuple[str, ...]]:
    """One row per method at delay 0, in the given order."""
    at0 = frame[frame["delay_s"].astype(float) == 0.0] if "delay_s" in frame else frame
    rows = []
    for method in [m for m in order if m in set(at0["method"])]:
        r = at0[at0["method"] == method].iloc[0]
        failed = int(r["failed"]) if "failed" in r and str(r["failed"]) != "nan" else 0
        symptom = _num(r["symptom_rate"])
        if symptom:
            symptom += f" ({_num(r['symptom_chance'])})"
        rows.append((
            f"{NAMES.get(method, method)} [{method}]",
            _num(r["ac1"]), _num(r["ac3"]), _num(r["avg5"]), _num(r["exp_ac1"]),
            symptom, f"{float(r['mean_ms']):.0f}",
            str(failed) if failed else "",
        ))
    return rows


def table3() -> None:
    print("Table 3 (E2 accuracy)")
    ours = ["PARE", "PARE_LGBM", "PARE_NO_RESIDUAL", "PARE_NO_CP", "NSIGMA", "SHAP_IFOREST"]
    theirs = [m for m in NAMES if m.startswith("RCAEVAL_")]
    ob, rcaeval, pooled, re2 = (_read("e2_re1_ob"), _read("e2_rcaeval_re1_ob"),
                                _read("e2_re1"), _read("e2_re2_ob"))
    if ob is None or pooled is None:
        return
    blank = ("",) * 7
    rows: list[tuple[str, ...]] = [("RE1 Online Boutique (125 cases)", *blank)]
    rows += _accuracy_rows(ob, ours)
    if rcaeval is not None:
        rows += _accuracy_rows(rcaeval, theirs)
    rows += [("RE1 Online Boutique + Sock Shop (250 cases)", *blank)]
    rows += _accuracy_rows(pooled, ours)
    if re2 is not None:
        rows += [(f"RE2 Online Boutique ({int(re2['cases'].iloc[0])} cases)", *blank)]
        rows += _accuracy_rows(re2, ours)
    _write_table("table3_e2_accuracy", Table(
        name="table3_e2_accuracy",
        title="E2: root-cause accuracy at detection delay 0",
        header=("Method", "AC@1", "AC@3", "Avg@5", "ExpAC@1", "Symptom rate (chance)",
                "ms/case", "Failed"),
        rows=rows,
        notes=(
            "AC@k: the true service is in the top k (ties scored as the expected value "
            "under a random order). ExpAC@1: the true metric is ranked first, on CPU and "
            "MEM cases (and SOCKET on RE2) only.",
            "Symptom rate: share of wrong answers that blame a caller of the real "
            "culprit; chance in brackets. Lower is better.",
            "RCAEval baselines were run through RCAEval's own package (Online Boutique "
            "only). Failed counts time-outs (300 s) and crashes, scored as misses; RCD "
            "could not run with the installed causal-learn.",
        ),
        source="experiments/results/e2_re1_ob, e2_rcaeval_re1_ob, e2_re1, e2_re2_ob",
    ))


# --- Table 4: E4 graph ablation ---------------------------------------------------


def table4() -> None:
    print("Table 4 (E4 graph ablation)")
    arms = {
        "static": "Static architecture file (15 edges)",
        "traces": "Read from RE2 traces (9 edges)",
        "correlation": "Inferred from correlation, per case",
        "none": "No graph",
    }
    rows = []
    for arm, label in arms.items():
        frame = _read(f"e4_re2_ob_{arm}")
        if frame is None:
            continue
        r = frame[frame["method"] == "PARE"].iloc[0]
        rows.append((label, _num(r["ac1"]), _num(r["ac3"]), _num(r["avg5"]),
                     _num(r["symptom_rate"]), _num(r["symptom_chance"]),
                     str(int(r["no_clear_cause"]))))
    if not rows:
        return
    _write_table("table4_e4_graph", Table(
        name="table4_e4_graph",
        title="E4: PARE with different call graphs (RE2 Online Boutique, delay 0)",
        header=("Graph given to PARE", "AC@1", "AC@3", "Avg@5", "Symptom rate",
                "Chance", "No clear cause"),
        rows=rows,
        notes=("Every arm is scored against the static graph: whether a blamed service "
               "calls the culprit is a fact about the system, not about what PARE was told.",),
        source="experiments/results/e4_re2_ob_*",
    ))


# --- Table 6 and Figure 6: E6 synthetic study --------------------------------------

E6_METHODS = ["PARE", "PARE_NO_RESIDUAL", "PARE_NO_CP", "NSIGMA", "SHAP_IFOREST", "ECDF"]
FACTOR_NAMES = {
    "n_services": "Services", "propagation": "Propagation", "amplification": "Amplification",
    "noise": "Noise", "graph": "Graph quality", "delay_rows": "Delay (s)",
}


def _e6() -> pd.DataFrame | None:
    frame = _read("e6_synthetic")
    if frame is None:
        return None
    return frame[frame["fault_type"] == "ALL"]


def table6() -> None:
    print("Table 6 (E6 synthetic study)")
    frame = _e6()
    if frame is None:
        return
    methods = [m for m in E6_METHODS if m in set(frame["method"])]
    rows = []
    for factor, label in FACTOR_NAMES.items():
        part = frame[frame["factor"] == factor]
        for level in dict.fromkeys(part["level"].astype(str)):
            at = part[part["level"].astype(str) == level].set_index("method")
            rows.append((label, level, *(_num(at.loc[m, "ac1"]) if m in at.index else ""
                                         for m in methods)))
    _write_table("table6_e6_synthetic", Table(
        name="table6_e6_synthetic",
        title="E6: AC@1 on synthetic data, one factor varied at a time",
        header=("Factor", "Level", *methods),
        rows=rows,
        notes=("Base: 10 services, propagation 0.8, amplification 0.25, noise 1.0, true "
               "graph, delay 0. 30 seeds x 4 fault types per setting.",
               "Graph quality is what PARE is told; answers are scored on the true graph."),
        source="experiments/results/e6_synthetic/summary.csv",
    ))


def figure6() -> None:
    print("Figure 6 (E6)")
    frame = _e6()
    if frame is None:
        return
    panels = [("amplification", "ac1", "AC@1"), ("amplification", "symptom_rate",
              "Symptom rate"), ("propagation", "ac1", "AC@1"), ("graph", "ac1", "AC@1")]
    methods = ["PARE", "PARE_NO_RESIDUAL", "NSIGMA", "SHAP_IFOREST"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    for ax, (factor, metric, ylabel) in zip(axes.flat, panels, strict=True):
        part = frame[frame["factor"] == factor]
        levels = list(dict.fromkeys(part["level"].astype(str)))
        for method in methods:
            rows = part[part["method"] == method].set_index(part["level"].astype(str))
            values = [pd.to_numeric(rows.loc[lv, metric], errors="coerce")
                      if lv in rows.index else float("nan") for lv in levels]
            ax.plot(range(len(levels)), values, marker="o", markersize=3,
                    linewidth=2.2 if method == "PARE" else 1.4,
                    color=LINE[method], label=NAMES[method], zorder=3)
        ax.set_xticks(range(len(levels)))
        ax.set_xticklabels(levels, fontsize=7, color=INK)
        ax.set_xlabel(FACTOR_NAMES[factor], fontsize=8, color=INK)
        ax.set_ylabel(ylabel, fontsize=8, color=INK)
        ax.set_ylim(0, 1.05)
        _style(ax)
    axes[0, 0].legend(fontsize=6.5, frameon=False, loc="lower left")
    fig.text(0.01, 0.005, "Synthetic cases, 30 seeds x 4 fault types per point. "
             "Base: 10 services, propagation 0.8, amplification 0.25, true graph.",
             fontsize=5.5, color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    _save(fig, "fig6_e6_synthetic")


# --- Figure 2: Avg@5 against detection delay ---------------------------------------


def figure2() -> None:
    print("Figure 2 (E3 delay sweep)")
    gap, lookback, rcaeval = (_read("e2_re1_ob"), _read("e2_re1_ob_lookback"),
                              _read("e2_rcaeval_re1_ob"))
    if gap is None:
        return
    # RCAEval's methods are given only the alarm time and treat everything before it
    # as normal. The fair comparison is therefore our alarm-only protocol (normal
    # window ends 300 s before the alarm, injection time never used), so they share
    # the left panel. The right panel is the benchmark protocol, ours only, because
    # there our normal window is cut using the injection time.
    panels = []
    if lookback is not None:
        panels.append(("Alarm time only: no method is told the injection time",
                       pd.concat([lookback, rcaeval]) if rcaeval is not None else lookback))
    panels.append(("Benchmark protocol: normal window ends 30 s before the injection", gap))
    methods = ["PARE", "PARE_NO_CP", "NSIGMA", "SHAP_IFOREST",
               "RCAEVAL_NSIGMA", "RCAEVAL_BARO", "RCAEVAL_CIRCA"]
    fig, axes = plt.subplots(1, len(panels), figsize=(7.2, 3.8), dpi=200, sharey=True,
                             squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, (title, frame) in zip(axes[0], panels, strict=True):
        for method in [m for m in methods if m in set(frame["method"])]:
            rows = frame[frame["method"] == method].sort_values("delay_s")
            ax.plot(rows["delay_s"], rows["avg5"], marker="o", markersize=3,
                    linewidth=2.2 if method == "PARE" else 1.3,
                    linestyle="--" if method.startswith("RCAEVAL") else "-",
                    color=LINE[method], label=NAMES[method], zorder=3)
        ax.set_title(title, fontsize=7, color=INK)
        ax.set_xlabel("Detection delay (s)", fontsize=8, color=INK)
        ax.set_xticks([0, 30, 60, 120])
        ax.set_ylim(0, 1.0)
        _style(ax)
    axes[0][0].set_ylabel("Avg@5", fontsize=8, color=INK)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=6.5, frameon=False, loc="lower center", ncol=4)
    fig.text(0.01, 0.005, "RE1 Online Boutique, 125 cases per point. Dashed: RCAEval's "
             "own implementations.", fontsize=5.5, color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    _save(fig, "fig2_avg5_vs_delay")


# --- Figure 1: the motivating example ----------------------------------------------


def figure1() -> None:
    """One real case where TreeSHAP blames a symptom and PARE names the culprit.

    Chosen by rule, not by eye: the first RE1 Online Boutique case (in case-id order)
    at delay 0 where SHAP_IFOREST's top service is a caller of the culprit, PARE ranks
    the culprit first, and - so the bars say what the text says - the culprit also
    has PARE's highest self score. TreeSHAP is re-run on that case for its own
    per-service attribution. Each method's bars are scaled to its own maximum,
    because the scores are on different scales. Also records the first case PARE
    gets wrong.
    """
    print("Figure 1 (motivating example)")
    cases = _read("e2_re1_ob", "cases.csv")
    if cases is None:
        return
    at0 = cases[cases["delay_s"].astype(float) == 0.0]
    shap = at0[at0["method"] == "SHAP_IFOREST"].set_index("case_id")
    pare = at0[at0["method"] == "PARE"].set_index("case_id")
    candidates = [cid for cid in sorted(shap.index)
                  if str(shap.loc[cid, "symptom_error"]) == "True"
                  and cid in pare.index and str(pare.loc[cid, "rank_gt_service"]) == "1"
                  and str(pare.loc[cid, "tied_gt_service"]) == "1"]
    missed = next((cid for cid in sorted(pare.index)
                   if str(pare.loc[cid, "rank_gt_service"]) != "1"), None)

    from pare.config import PareConfig
    from pare.engine import analyze

    from experiments.adapters.graphs import load_graph
    from experiments.adapters.rcaeval import list_cases, load_case
    from experiments.runner import _request_for

    by_id = {c.case_id: c for c in list_cases(REPO / "data" / "RCAEval", "RE1",
                                             "online-boutique")}
    graph = load_graph("online-boutique")
    chosen = case = result = None
    for cid in candidates:
        data = load_case(by_id[cid], graph=graph)
        run = analyze(_request_for(data, "PARE", PareConfig(top_k=10_000)))
        scores = {s.service: s for s in run.services}
        culprit, blamed = by_id[cid].gt_service, shap.loc[cid, "top1_service"]
        if max(scores.values(), key=lambda s: s.score).service == culprit and blamed in scores:
            chosen, case, result = cid, by_id[cid], run
            shap_run = analyze(_request_for(data, "SHAP_IFOREST", PareConfig(top_k=10_000)))
            break
    if chosen is None:
        print("  skipped: no case met the rule")
        return
    shap_scores = {s.service: s.score for s in shap_run.services}
    # Show the services either method rates highly: PARE's top ones and TreeSHAP's.
    shap_top = max(shap_scores.values()) or 1.0
    pare_top = max(x.score for x in result.services) or 1.0

    def prominence(item) -> float:
        return max(item.score / pare_top, shap_scores.get(item.service, 0.0) / shap_top)

    services = sorted(result.services, key=prominence, reverse=True)[:7]

    def scaled(values: list[float]) -> list[float]:
        top = max(values) or 1.0
        return [v / top for v in values]

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    x = range(len(services))
    all_shap = scaled([shap_scores.get(s.service, 0.0) for s in result.services])
    shap_of = dict(zip([s.service for s in result.services], all_shap, strict=True))
    all_marg = scaled([s.marginal_score for s in result.services])
    marg_of = dict(zip([s.service for s in result.services], all_marg, strict=True))
    all_self = scaled([s.score for s in result.services])
    self_of = dict(zip([s.service for s in result.services], all_self, strict=True))
    ax.bar([i - 0.27 for i in x], [shap_of[s.service] for s in services], width=0.26,
           color="#2a78d6", label="TreeSHAP attribution", zorder=2)
    ax.bar([i for i in x], [marg_of[s.service] for s in services], width=0.26,
           color="#b9b7b0", label="PARE marginal score: how unusual it looks", zorder=2)
    ax.bar([i + 0.27 for i in x], [self_of[s.service] for s in services], width=0.26,
           color="#c4302b", label="PARE self score: how much is its own problem", zorder=2)
    ax.set_xticks(list(x))
    labels = []
    for s in services:
        tag = " (culprit)" if s.service == case.gt_service else ""
        tag += " <- TreeSHAP" if s.service == shap.loc[chosen, "top1_service"] else ""
        labels.append(s.service + tag)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=6.5, color=INK)
    ax.set_ylabel("Score / method's maximum", fontsize=8, color=INK)
    ax.set_ylim(0, 1.15)
    _style(ax)
    ax.legend(fontsize=6.5, frameon=False)
    fig.text(0.01, 0.005, f"{chosen}, delay 0 s. TreeSHAP's top service is a caller of the "
             f"culprit; PARE ranks {case.gt_service} first.", fontsize=5.5,
             color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, "fig1_motivating_example")

    NOTES.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Figure 1 case: {chosen} (fault {case.fault_type}, culprit {case.gt_service}).",
        f"  TreeSHAP top service: {shap.loc[chosen, 'top1_service']} (a caller of the culprit).",
        f"  PARE top service: {pare.loc[chosen, 'top1_service']}.",
        "  Chosen by rule: first case id where SHAP_IFOREST commits a symptom error, PARE "
        "ranks the culprit alone at 1, and the culprit has PARE's top self score.",
        "  Observed while choosing (all 20 cases where SHAP blames a symptom and PARE is "
        "right): PARE's residual usually RAISES the blamed caller's score above its "
        "marginal score; PARE is right through its graph walk, not through the residual.",
    ]
    if missed is not None:
        lines += [
            f"One case PARE gets wrong: {missed} (culprit {pare.loc[missed, 'gt_service']}, "
            f"PARE blamed {pare.loc[missed, 'top1_service']}, verdict "
            f"{pare.loc[missed, 'verdict']}).",
        ]
    (NOTES / "fig1_case.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  wrote paper/notes/fig1_case.txt")


# --- Table 5 and Figure 4: E5 explanation quality -----------------------------------

E5_METHODS = ["PARE", "PARE_NO_RESIDUAL", "NSIGMA", "SHAP_IFOREST", "PCA_RECON", "ECDF"]


def table5() -> None:
    print("Table 5 (E5 explanation quality)")
    frame = _read("e5_re1")
    if frame is None:
        return
    rows = []
    for method in [m for m in E5_METHODS if m in set(frame["method"])]:
        r = frame[frame["method"] == method].iloc[0]
        rows.append((f"{NAMES.get(method, method)} [{method}]", _num(r["deletion_auc"]),
                     _num(r["random_auc"]), _num(r["beats_random"]),
                     f"{float(r['compactness_median']):.0f}", _num(r["jaccard_top5"]),
                     _num(r["kendall_tau"])))
    _write_table("table5_e5_quality", Table(
        name="table5_e5_quality",
        title="E5: faithfulness, compactness and stability (RE1 Online Boutique + Sock Shop)",
        header=("Method", "Deletion AUC", "Random AUC", "Beats random", "Compactness",
                "Top-5 Jaccard", "Kendall tau"),
        rows=rows,
        notes=(
            "Deletion AUC: normalised system anomaly score as the top 0-10 indicators are "
            "reset to normal; lower = the explanation removes the anomaly faster. Random: "
            "10 random orders. Beats random: share of cases below their random area.",
            "The deletion test rewards removing the loudest columns. A method that ranks a "
            "quieter root-cause column above a louder inherited one is penalised by it by "
            "design, so read it alongside accuracy, not instead of it.",
            "Compactness: median number of indicators holding 80% of the positive score. "
            "Stability: alarm moved -10 s and +10 s; overlap with the unshifted answer.",
        ),
        source="experiments/results/e5_re1/summary.csv",
    ))


def figure4() -> None:
    print("Figure 4 (E5 deletion curves)")
    curves = _read("e5_re1", "faithfulness.csv")
    summary = _read("e5_re1")
    if curves is None or summary is None:
        return
    fig, ax = plt.subplots(figsize=(5.2, 3.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    for method in [m for m in E5_METHODS if m in set(curves["method"])]:
        mean = curves[curves["method"] == method].groupby("k")["normalised_score"].mean()
        ax.plot(mean.index, mean.values, marker="o", markersize=2.5,
                linewidth=2.2 if method == "PARE" else 1.3,
                color=LINE.get(method, "#eb6834"), label=NAMES.get(method, method), zorder=3)
    random_auc = float(summary["random_auc"].mean())
    ax.axhline(random_auc, color=INK, linestyle=":", linewidth=1,
               label=f"Random order (mean area {random_auc:.2f})")
    ax.set_xlabel("Top-k indicators reset to normal", fontsize=8, color=INK)
    ax.set_ylabel("System anomaly score (share of k=0)", fontsize=8, color=INK)
    ax.set_ylim(0, 1.05)
    _style(ax)
    ax.legend(fontsize=6, frameon=False)
    fig.tight_layout()
    _save(fig, "fig4_e5_deletion")


# --- Compact tables for the 6-page IEEE paper ----------------------------------------
#
# The tables above carry every column for the record; these carry only what the
# paper discusses, with short method names, so they fit IEEE's narrow columns.
# Same numbers, read from the same files.

SHORT = {
    "PARE": "PARE", "PARE_LGBM": "PARE-LGBM", "PARE_NO_RESIDUAL": "PARE w/o residual",
    "PARE_NO_CP": "PARE w/o change point", "NSIGMA": "Robust $n$-sigma",
    "SHAP_IFOREST": "IForest+TreeSHAP", "PCA_RECON": "PCA reconstruction", "ECDF": "ECDF tail",
    "RCAEVAL_NSIGMA": r"NSigma~\cite{pham2025rcaeval}",
    "RCAEVAL_BARO": r"BARO~\cite{pham2024baro}",
    "RCAEVAL_CIRCA": r"CIRCA~\cite{li2022circa}",
    "RCAEVAL_E_DIAGNOSIS": r"$\varepsilon$-Diagnosis~\cite{shan2019ediagnosis}",
    "RCAEVAL_PC_PAGERANK": r"PC-PageRank~\cite{pham2025rcaeval}",
}


def _f(value: object) -> str:
    text = _num(value)
    return text if text else "--"


def _ieee(name: str, caption: str, label: str, spec: str, header: str,
          body: list[str], wide: bool = False) -> None:
    env = "table*" if wide else "table"
    lines = ["% Generated by experiments/make_paper_results.py. Do not edit by hand.",
             rf"\begin{{{env}}}[t]", r"\centering", rf"\caption{{{caption}}}",
             rf"\label{{{label}}}", r"\footnotesize", r"\setlength{\tabcolsep}{3pt}",
             rf"\begin{{tabular}}{{{spec}}}", r"\toprule", header + r" \\", r"\midrule",
             *body, r"\bottomrule", r"\end{tabular}", rf"\end{{{env}}}"]
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {name}.tex")


def ieee_tables() -> None:
    print("IEEE compact tables")
    # E1: grounding on RE1 (pooled) and RE2-OB.
    re1, re2 = _read("e1_re1"), _read("e1_re2_ob")
    if re1 is not None and re2 is not None:
        body = []
        for method in ["SHAP_IFOREST", "PCA_RECON", "ECDF"]:
            a = re1[re1["method"] == method].iloc[0]
            b = re2[re2["method"] == method].iloc[0]
            body.append(f"{SHORT[method]} & {_f(a['ac1'])} & {_f(a['exp_ac1'])} & "
                        f"{_f(a['symptom_rate'])} ({_f(a['symptom_chance'])}) & "
                        f"{_f(b['ac1'])} & {_f(b['exp_ac1'])} & "
                        f"{_f(b['symptom_rate'])} ({_f(b['symptom_chance'])}) \\\\")
        _ieee("ieee_e1", "E1: service accuracy (AC@1), metric accuracy (ExpAC@1) and "
              "symptom rate of common anomaly explainers (chance level in brackets).",
              "tab:e1", "lrrrrrr",
              r"& \multicolumn{3}{c}{RE1 (375 cases)} & \multicolumn{3}{c}{RE2-OB (90 cases)}"
              r" \\ \cmidrule(lr){2-4}\cmidrule(lr){5-7}" "\n"
              "Explainer & AC@1 & ExpAC@1 & Symptom & AC@1 & ExpAC@1 & Symptom",
              body, wide=True)

    # E2/E3: accuracy at delay 0 and 120 s.
    pooled, ob, rca, re2 = (_read("e2_re1"), _read("e2_re1_ob"), _read("e2_rcaeval_re1_ob"),
                            _read("e2_re2_ob"))
    if pooled is not None and ob is not None:
        def at(frame, method, delay, column):
            rows = frame[(frame["method"] == method) & (frame["delay_s"].astype(float) == delay)]
            return _f(rows.iloc[0][column]) if len(rows) else "--"
        ours = ["PARE", "PARE_NO_RESIDUAL", "PARE_NO_CP", "PARE_LGBM", "NSIGMA", "SHAP_IFOREST"]
        body = [r"\multicolumn{7}{l}{\textit{RE1 Online Boutique + Sock Shop (250 cases)}} \\"]
        for m in ours:
            r2 = (at(re2.assign(delay_s=0.0), m, 0.0, "ac1") if re2 is not None else "--")
            body.append(f"{SHORT[m]} & {at(pooled, m, 0.0, 'ac1')} & {at(pooled, m, 0.0, 'avg5')}"
                        f" & {at(pooled, m, 0.0, 'symptom_rate')} & {at(pooled, m, 120.0, 'ac1')}"
                        f" & {at(pooled, m, 120.0, 'avg5')} & {r2} \\\\")
        if rca is not None:
            # Alarm-time-only protocol on both sides: RCAEval's methods see only the
            # alarm, so ours are shown from the run that never uses the injection time.
            obl = _read("e2_re1_ob_lookback")
            body.append(r"\midrule" "\n" r"\multicolumn{7}{l}{\textit{RE1 Online Boutique "
                        r"(125 cases), alarm time only}} \\")
            for m in ["PARE", "NSIGMA"]:
                body.append(f"{SHORT[m]} & {at(obl, m, 0.0, 'ac1')} & {at(obl, m, 0.0, 'avg5')}"
                            f" & {at(obl, m, 0.0, 'symptom_rate')} & {at(obl, m, 120.0, 'ac1')}"
                            f" & {at(obl, m, 120.0, 'avg5')} & -- \\\\")
            for m in ["RCAEVAL_NSIGMA", "RCAEVAL_BARO", "RCAEVAL_CIRCA", "RCAEVAL_E_DIAGNOSIS",
                      "RCAEVAL_PC_PAGERANK"]:
                body.append(f"{SHORT[m]} & {at(rca, m, 0.0, 'ac1')} & {at(rca, m, 0.0, 'avg5')}"
                            f" & {at(rca, m, 0.0, 'symptom_rate')} & {at(rca, m, 120.0, 'ac1')}"
                            f" & {at(rca, m, 120.0, 'avg5')} & -- \\\\")
        _ieee("ieee_e2", r"E2/E3: root-cause accuracy with an on-time alarm (0\,s) and a late "
              r"one (120\,s). Symptom: share of wrong answers that blame a caller of the "
              "culprit (lower is better).", "tab:e2", "lrrrrrr",
              r"& \multicolumn{3}{c}{Delay 0\,s} & \multicolumn{2}{c}{Delay 120\,s} & RE2 "
              r"\\ \cmidrule(lr){2-4}\cmidrule(lr){5-6}" "\n"
              "Method & AC@1 & Avg@5 & Symptom & AC@1 & Avg@5 & AC@1", body, wide=True)

    # E4: graph ablation.
    arms = [("static", "Architecture file"), ("traces", "From traces"),
            ("correlation", "Correlation-inferred"), ("none", "No graph")]
    body = []
    for arm, label in arms:
        frame = _read(f"e4_re2_ob_{arm}")
        if frame is not None:
            r = frame[frame["method"] == "PARE"].iloc[0]
            body.append(f"{label} & {_f(r['ac1'])} & {_f(r['avg5'])} & {_f(r['symptom_rate'])}"
                        " \\\\")
    if body:
        _ieee("ieee_e4", "E4: PARE on RE2-OB given different call graphs (scored against the "
              "true graph).", "tab:e4", "lrrr", "Graph given to PARE & AC@1 & Avg@5 & Symptom",
              body)

    # E5: explanation quality.
    e5 = _read("e5_re1")
    if e5 is not None:
        body = []
        for m in [x for x in E5_METHODS if x in set(e5["method"])]:
            r = e5[e5["method"] == m].iloc[0]
            body.append(f"{SHORT[m]} & {_f(r['deletion_auc'])} & "
                        f"{float(r['compactness_median']):.0f} & {_f(r['jaccard_top5'])} & "
                        f"{_f(r['kendall_tau'])} \\\\")
        _ieee("ieee_e5", f"E5: deletion area (lower is more faithful; random order "
              f"{float(e5['random_auc'].mean()):.3f}), compactness (indicators holding "
              r"80\% of the score) and stability under $\pm$10\,s alarm shifts.", "tab:e5",
              "lrrrr", r"Method & Deletion & Compact. & Jaccard@5 & Kendall $\tau$", body)


def main() -> int:
    for part in (table3, table4, table5, table6, ieee_tables, figure1, figure2, figure4,
                 figure6):
        part()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
