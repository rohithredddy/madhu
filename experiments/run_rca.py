"""E2 and E3: how accurate is root-cause ranking, and how does a late alarm hurt it?

Tasks M4.1 and M4.3. E2 (RQ3) compares PARE, its ablations and the baselines on
service and indicator accuracy; E3 (RQ4) repeats it with the alarm 0, 30, 60 and
120 s after the injection, so a method that only works with a perfectly timed
alarm shows it. Both are the same runner over different configurations:

    analyzer/.venv/Scripts/python.exe experiments/run_rca.py \
        --config experiments/configs/e2_re1_ob.yaml

The engines here are ours (`pare.engine`). RCAEval's own baselines run in their
environment through `run_rcaeval_baselines.py` and are scored into the same
contract by `score_rcaeval.py`, so the two meet in the tables, not in one process.

`docs/08` section 4 asks E3 to report two normal windows side by side: the
standard RCAEval protocol (`normal_mode: inject_gap`, which uses the injection
time to end the normal period) and an honest variant (`alarm_lookback`, which
never uses it). Each is its own configuration and run folder.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.experiment import run_from_command_line  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    return run_from_command_line(argv, title="E2/E3 RCA accuracy", description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
