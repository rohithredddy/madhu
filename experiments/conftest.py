"""Make the repository root importable, so `experiments.adapters...` resolves.

`experiments/` is a collection of scripts rather than an installed package, so
there is no entry in site-packages pointing at it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
