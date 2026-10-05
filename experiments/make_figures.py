"""Generate the paper's figures from finished runs: `paper/figures/*.png` and `*.pdf`.

Like `make_tables.py`, this reads only the small summary files a run leaves behind
and draws them; it computes nothing new, so every bar comes from a number already
in a file under `experiments/results/` (hard rule 2).

Figures written so far (task M3.3):

* **Figure 3** - E1, the symptom rate by fault type: of each method's wrong
  answers, the share that blamed a service calling the real culprit, with the
  rate a randomly chosen wrong answer would get marked on every bar.

Figures 1, 2 and 4 belong to later experiments and are added with them.

    analyzer/.venv/Scripts/python.exe experiments/make_figures.py
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # files only; never open a window

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Categorical slots 1-4 of the validated default palette (light mode). Checked
# with the dataviz validator: every adjacent pair clears the colour-blind and
# normal-vision separation floors. Two slots sit below 3:1 contrast against the
# page, so identity never rests on colour alone - there is a legend, and every
# number is also in Table 2 and Table 2b.
COLOURS = {
    "SHAP_IFOREST": "#2a78d6",
    "PCA_RECON": "#eb6834",
    "ECDF": "#1baf7a",
    "PARE_NO_RESIDUAL": "#eda100",
}
LABELS = {
    "SHAP_IFOREST": "Isolation Forest + TreeSHAP",
    "PCA_RECON": "PCA reconstruction",
    "ECDF": "ECDF tail score",
    "PARE_NO_RESIDUAL": "Robust z (no residuals)",
}
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"

FAULTS = ("CPU", "MEM", "DISK", "DELAY", "LOSS")


def figure3_symptom_rate(e1: Path, out: Path) -> list[Path]:
    """Symptom rate by fault type, one bar per method, chance floor on each.

    Pooled over the systems that have a call graph (Online Boutique and Sock Shop);
    Train Ticket has none yet, and its cases carry no symptom judgement, which the
    summary already excludes. Each bar is labelled with how many wrong answers it
    is the share of, because some are small and a reader should see that.
    """
    overall = pd.read_csv(e1 / "summary.csv").assign(fault_type="All")
    by_fault = pd.read_csv(e1 / "summary_by_fault.csv")
    frame = pd.concat([by_fault, overall], ignore_index=True)
    groups = [*FAULTS, "All"]
    methods = [m for m in COLOURS if m in set(frame["method"])]

    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    width = 0.19
    gap = 0.01  # a sliver of page between neighbouring bars
    for i, method in enumerate(methods):
        rows = frame[frame["method"] == method].set_index("fault_type")
        for j, group in enumerate(groups):
            if group not in rows.index:
                continue
            row = rows.loc[group]
            rate, chance = row["symptom_rate"], row["symptom_chance"]
            if pd.isna(rate):
                continue
            x = j + (i - (len(methods) - 1) / 2) * width
            ax.bar(x, rate, width=width - gap, color=COLOURS[method], zorder=2)
            # The floor: what a wrong answer chosen at random would score.
            ax.hlines(chance, x - width / 2 + 0.02, x + width / 2 - 0.02,
                      colors=INK, linewidth=1.6, zorder=3)
            ax.text(x, rate + 0.015, f"{row['symptom_judged']:.0f}", ha="center",
                    va="bottom", fontsize=5.5, color=INK_SECONDARY)

    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups, color=INK, fontsize=8)
    ax.axvline(len(FAULTS) - 0.5, color=GRID, linewidth=1, zorder=1)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Symptom rate (share of wrong answers)", color=INK, fontsize=8)
    ax.tick_params(axis="y", colors=INK_SECONDARY, labelsize=7)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    handles = [Patch(color=COLOURS[m], label=LABELS[m]) for m in methods]
    handles.append(Line2D([], [], color=INK, linewidth=1.6,
                          label="Chance: a wrong answer picked at random"))
    ax.legend(handles=handles, loc="upper left", fontsize=6.5, frameon=False, ncol=3,
              bbox_to_anchor=(0, 1.16))
    fig.text(0.01, 0.005,
             "RE1 Online Boutique + Sock Shop, delay 0 s. Number above a bar: the "
             "wrong answers it is a share of (expected count, ties scored as ties).",
             fontsize=5.5, color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))

    written = []
    for suffix in ("png", "pdf"):
        path = out / f"fig3_e1_symptom_rate_by_fault.{suffix}"
        # Fixed metadata so a re-run produces an identical PDF.
        fig.savefig(path, facecolor=SURFACE,
                    metadata={"CreationDate": None} if suffix == "pdf" else None)
        written.append(path)
    plt.close(fig)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e1", type=Path, default=REPO / "experiments" / "results" / "e1_re1",
                        help="the pooled E1 run folder")
    parser.add_argument("--out", type=Path, default=REPO / "paper" / "figures")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    for path in figure3_symptom_rate(args.e1, args.out):
        print(f"wrote {path.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
