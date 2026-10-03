"""Draw the example figure for the synthetic generator.

Writes ``paper/figures/synthetic_example.png``: one generated fault, shown the way
the paper describes the problem - the broken service moves, the services that call
it follow, and an unrelated service does not.

Defaults to a latency fault because that is where propagation is clearest. The
memory fault is the paper's motivating example, but it reaches callers only
through a small latency term and is hard to see on a chart; ``--fault mem`` draws
it anyway. See the M1.2 entry in PROGRESS.md.

Matplotlib lives in this script rather than in the ``pare`` package, so the
library itself never pulls in a plotting backend.

Run from the analyzer directory:

    python scripts/make_synthetic_example.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

# Pick a non-interactive backend before pyplot is imported, so this runs the same
# way from a terminal, a script or CI.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

from pare.synthetic import make_case  # noqa: E402

# Colours match the roles in docs/04_REACT_FRONTEND_SPEC.md section 2, so the
# figure and the user interface tell the same story with the same colours.
COLOUR_CAUSE = "#d64545"
COLOUR_SYMPTOM = "#e69a28"
COLOUR_NORMAL = "#9aa3ad"
COLOUR_INJECT = "#2f9e44"


def callers_of(case, service: str) -> list[str]:
    """The chain of services that call ``service``, directly or indirectly."""
    caller_of = {callee: caller for caller, callee in case.edges}
    chain = []
    current = service
    while current in caller_of:
        current = caller_of[current]
        chain.append(current)
    return chain


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-services", type=int, default=10)
    parser.add_argument("--propagation", type=float, default=0.8)
    parser.add_argument(
        "--fault",
        default="latency",
        choices=["latency", "cpu", "mem", "error"],
        help="latency shows propagation most clearly; mem is the paper's motivating example "
        "but reaches callers only weakly (see PROGRESS.md)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "paper" / "figures" / "synthetic_example.png",
    )
    args = parser.parse_args()

    case = make_case(
        n_services=args.n_services,
        n_normal=400,
        n_abnormal=200,
        fault=args.fault,
        propagation=args.propagation,
        seed=args.seed,
    )

    culprit = case.gt_service
    chain = callers_of(case, culprit)
    called_by_culprit = {callee for caller, callee in case.edges if caller == culprit}
    unrelated = [
        s for s in case.services if s not in {culprit, *chain} | called_by_culprit
    ]

    frame = case.to_frame()
    # Seconds since the start, which reads better on an axis than epoch seconds.
    seconds = frame.index - frame.index[0]
    inject_at = case.inject_time_sec - frame.index[0]

    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [1, 1.3]}
    )

    # --- top: the cause itself ---
    top.plot(seconds, frame[case.gt_column], color=COLOUR_CAUSE, linewidth=1.2,
             label=f"{culprit} {case.fault} (the cause)")
    top.axvline(inject_at, color=COLOUR_INJECT, linestyle="--", linewidth=1.2,
                label="fault injected")
    top.set_ylabel(case.fault)
    top.set_title(
        f"A {case.fault} fault in one service, and what its callers look like",
        fontsize=12,
    )
    top.legend(loc="upper left", fontsize=9)
    top.grid(alpha=0.25)

    # --- bottom: the cause and the symptoms, in response time ---
    bottom.plot(seconds, frame[f"{culprit}_latency"], color=COLOUR_CAUSE, linewidth=1.2,
                label=f"{culprit} response time (the cause)")
    for position, caller in enumerate(chain[:3]):
        bottom.plot(
            seconds,
            frame[f"{caller}_latency"],
            color=COLOUR_SYMPTOM,
            linewidth=1.1,
            alpha=1.0 - 0.25 * position,
            label=f"{caller} response time (only affected)",
        )
    if unrelated:
        bottom.plot(seconds, frame[f"{unrelated[0]}_latency"], color=COLOUR_NORMAL,
                    linewidth=1.0, label=f"{unrelated[0]} response time (unrelated)")
    bottom.axvline(inject_at, color=COLOUR_INJECT, linestyle="--", linewidth=1.2)
    bottom.set_ylabel("response time")
    bottom.set_xlabel("seconds")
    bottom.legend(loc="upper left", fontsize=9)
    bottom.grid(alpha=0.25)

    figure.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")
    print(f"  fault={case.fault} culprit={culprit} callers={chain}")
    print(f"  propagation={args.propagation} seed={args.seed}")


if __name__ == "__main__":
    main()
