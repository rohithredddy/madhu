"""Download an RCAEval dataset into `data/RCAEval/`.

A thin, reproducible wrapper over RCAEval's own download helpers, so that getting
the data is a recorded step rather than something someone did once at a shell
prompt and cannot repeat.

It must be run with the RCAEval virtual environment, not the analyzer one - the
two cannot share an environment because RCAEval needs numpy 1.x while the
analyzer uses 2.x:

    cd experiments
    .venv-rcaeval/Scripts/python.exe download_rcaeval.py --dataset RE1-OB

Downloads are skipped when the target folder already exists, so running it again
is cheap and safe.

Sizes, so nobody is surprised by what they started: RE1-OB is about 31 MB
compressed. The RE2 and RE3 sets carry logs and traces and are very much larger -
`08_EXPERIMENTS_SPEC.md` section 2 says to take one system at a time, and that
advice is about disk as much as memory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Which RCAEval helper fetches which dataset. Names match the folders the
# archives unpack into, so `--dataset RE1-OB` lands in `data/RCAEval/RE1/RE1-OB`.
DATASETS = {
    "RE1-OB": ("download_re1ob_dataset", "RE1"),
    "RE1-SS": ("download_re1ss_dataset", "RE1"),
    "RE1-TT": ("download_re1tt_dataset", "RE1"),
    "RE1": ("download_re1_dataset", "RE1"),
    "RE2-OB": ("download_re2ob_dataset", "RE2"),
    "RE2-SS": ("download_re2ss_dataset", "RE2"),
    "RE2-TT": ("download_re2tt_dataset", "RE2"),
    "RE3-OB": ("download_re3ob_dataset", "RE3"),
    "RE3-SS": ("download_re3ss_dataset", "RE3"),
    "RE3-TT": ("download_re3tt_dataset", "RE3"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="RE1-OB", choices=sorted(DATASETS))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "RCAEval",
        help="where RCAEval data lives; git-ignored",
    )
    args = parser.parse_args()

    try:
        import RCAEval.utility as utility
    except ImportError:
        print(
            "RCAEval is not importable. Run this with the RCAEval environment:\n"
            "  experiments/.venv-rcaeval/Scripts/python.exe experiments/download_rcaeval.py",
            file=sys.stderr,
        )
        return 1

    function_name, release = DATASETS[args.dataset]
    download = getattr(utility, function_name)
    target = args.data_dir / release
    target.mkdir(parents=True, exist_ok=True)

    if (target / args.dataset).exists():
        print(f"{args.dataset} is already in {target}; nothing to do")
        return 0

    free_gb = shutil.disk_usage(target).free / 1e9
    print(f"downloading {args.dataset} into {target} ({free_gb:.1f} GB free)")

    # RCAEval writes its temporary zip into the working directory and deletes it
    # afterwards, so run from the target to keep the project root clean and to
    # make sure the scratch space is on the same drive as the data.
    here = Path.cwd()
    try:
        os.chdir(target)
        download(local_path=str(target))
    finally:
        os.chdir(here)

    unpacked = target / args.dataset
    if not unpacked.exists():
        print(f"expected {unpacked} to exist after the download", file=sys.stderr)
        return 1

    files = sum(1 for _ in unpacked.rglob("*") if _.is_file())
    size_mb = sum(f.stat().st_size for f in unpacked.rglob("*") if f.is_file()) / 1e6
    print(f"done: {files} files, {size_mb:.0f} MB in {unpacked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
