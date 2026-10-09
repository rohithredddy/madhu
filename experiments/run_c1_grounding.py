"""E1: do standard anomaly explanations point at root causes, or at symptoms?

Task M3.1. This is contribution C1 and, as `docs/08` section 4 puts it, a paper
section on its own. It answers two of the project's research questions on real
failure data with real ground truth:

* **RQ1, grounding.** How often does a common detector-plus-explainer pair rank the
  true root-cause indicator in its top k? Reported as ExpAC@1, @3 and @5.
* **RQ2, symptom versus cause.** When an explanation is wrong, is it wrong in the
  particular way this project is about - blaming a service that *calls* the real
  culprit, and is therefore a victim of it? Reported as the symptom rate, over the
  wrong answers rather than over all of them.

The methods are the ones a practitioner would actually reach for, not ours. PARE is
deliberately absent: E1 measures common practice, and E2 (M4.1) is where the
proposed method is measured against it. Mixing them would turn a study of the
field into an advertisement.

    analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py \
        --config experiments/configs/c1_re1_ob.yaml

Everything about a run comes from the YAML and is saved beside the results, so a
number in the paper can be traced to the configuration and the environment that
produced it (hard rule 10, and `docs/08` section 8).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.experiment import run_from_command_line  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    return run_from_command_line(argv, title="E1 grounding", description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
