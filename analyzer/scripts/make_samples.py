"""Write the sample request and responses the Java tests are built on.

`docs/03_JAVA_BACKEND_SPEC.md` section 4.4 requires the Java `FallbackRanker` to
produce the same ranking as Python `NSIGMA`. Something concrete has to sit
between the two languages for that test to mean anything, and these files are it:
one request, and the exact answers this engine gives for it.

Two details matter more than they look.

**The data is rounded before the responses are computed, not after.** Java reads
the rounded numbers out of the JSON, so if we scored the full-precision values
and then rounded them for the file, Java would be computing from slightly
different inputs than the stored answers came from, and the agreement test would
drift for no visible reason.

**Some values are deliberately missing.** The contract says a missing number is
`null`, never 0 and never the string "NaN". Java has to handle that on the way
in, so the sample contains some, and the test checks they are still there.

Run from the analyzer directory:

    python scripts/make_samples.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from pare.engine import AnalyzeRequest, Window, analyze
from pare.graph import CallGraph
from pare.synthetic import make_case

# Kept small enough that a person can open the file and see what is in it, while
# still having several services, a real graph and enough normal data to fit the
# dependency model.
N_SERVICES = 5
N_NORMAL = 150
N_ABNORMAL = 60
RECENT_FROM = 90  # the recent window starts here, so it straddles the fault
DECIMALS = 4
SEED = 42

# Which engines get a stored response. NSIGMA is the one Java must match; PARE is
# there so the Java side has a full-featured answer to deserialise, with roles,
# an explained-by and a change point.
ENGINES = ("PARE", "NSIGMA")


# Matches a JSON array that holds only numbers and nulls, spread over lines by
# the pretty printer.
_NUMBER = r"(?:-?[\d.eE+-]+|null)"
_NUMBER_ARRAY = re.compile(
    r"\[\s+" + _NUMBER + r"(?:,\s+" + _NUMBER + r")*\s+\]"
)


def dump(data: object) -> str:
    """Pretty JSON, but with each row of numbers kept on one line.

    With plain ``indent=2`` every single reading goes on its own line and the
    request becomes 130 KB of mostly whitespace. Keeping a row together makes the
    file a third of the size and far easier to read: one line is one moment in
    time. The result is ordinary JSON either way.
    """
    text = json.dumps(data, indent=2)

    def collapse(match: re.Match[str]) -> str:
        inner = match.group(0)[1:-1]
        return "[" + ", ".join(part.strip() for part in inner.split(",")) + "]"

    return _NUMBER_ARRAY.sub(collapse, text)


def build_request(engine: str, values: np.ndarray, case, alarm_time_sec: float):
    """One request over the already-rounded values."""
    times = case.to_frame().index.to_numpy(dtype=float)
    return AnalyzeRequest(
        engine=engine,
        alarm_time_sec=alarm_time_sec,
        columns=case.columns,
        normal=Window.of(times[:N_NORMAL], values[:N_NORMAL]),
        recent=Window.of(times[RECENT_FROM:], values[RECENT_FROM:]),
        graph=CallGraph.from_edges(case.edges, source="SYNTHETIC_TRUE"),
        request_id="sample-0001",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).resolve().parents[1] / "samples"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    case = make_case(
        n_services=N_SERVICES,
        n_normal=N_NORMAL,
        n_abnormal=N_ABNORMAL,
        fault="latency",
        propagation=0.9,
        amplification=0.25,
        seed=SEED,
    )

    # Round first: these are the numbers Java will read, so these are the numbers
    # the stored answers must have been computed from.
    values = np.round(case.to_frame().to_numpy(), DECIMALS)

    # A few holes, so the null handling is exercised on both sides. Chosen by
    # position rather than at random, so the file is the same every time.
    values[12, 1] = np.nan
    values[13, 1] = np.nan
    values[RECENT_FROM + 5, 3] = np.nan

    alarm_time_sec = float(case.inject_time_sec + 30)

    request = build_request(ENGINES[0], values, case, alarm_time_sec)
    request_json = request.to_api_dict()
    # The stored request names no engine in particular: Java sends it with
    # whichever engine it is testing.
    request_json["engine"] = ENGINES[0]
    (args.out / "analyze_request.json").write_text(
        dump(request_json), encoding="utf-8"
    )

    written = ["analyze_request.json"]
    for engine in ENGINES:
        result = analyze(build_request(engine, values, case, alarm_time_sec))
        payload = result.to_api_dict()
        # Timing is machine-dependent and would make the file churn on every run
        # while meaning nothing to a test.
        payload["tookMs"] = None
        name = f"analyze_response_{engine.lower()}.json"
        (args.out / name).write_text(dump(payload), encoding="utf-8")
        written.append(name)
        top = payload["services"][0]
        print(f"{engine:<8} top={top['service']:<9} role={top['role']:<14} "
              f"verdict={payload['verdict']}")

    (args.out / "README.md").write_text(
        f"""# samples

Fixtures shared with the Java backend. **Generated - do not edit by hand.**

    cd analyzer && python scripts/make_samples.py

| file | what it is |
|---|---|
| `analyze_request.json` | one `AnalyzeRequest`, shaped as `docs/06_DATA_CONTRACTS.md` section 3 |
| `analyze_response_pare.json` | what `PARE` answers for it |
| `analyze_response_nsigma.json` | what `NSIGMA` answers for it |

The case is generated by `pare.synthetic` with seed {SEED}: {N_SERVICES} services,
{N_NORMAL} normal rows, {N_ABNORMAL} abnormal rows, a latency fault, and the true
call graph. Ground truth is **not** in the request - an engine never receives it
(hard rule 4 in `PROJECT_RULES.md`) - and for the record the fault was injected into
`{case.gt_service}`, visible in `{case.gt_column}`.

Two things these files exist to protect:

1. **`docs/03_JAVA_BACKEND_SPEC.md` section 4.4**: the Java `FallbackRanker` must
   rank services exactly as Python `NSIGMA` does. `analyze_response_nsigma.json`
   is the expected answer.
2. **The wire format itself.** `analyzer/tests/test_samples.py` regenerates these
   from the current code and fails if anything drifts, so a change to the Python
   response shape cannot silently break the Java side.

Values are rounded to {DECIMALS} decimals *before* the answers are computed, so
Java scores exactly the numbers the stored answers came from. A few entries are
`null` on purpose: the contract says a missing number is `null`, never 0 and never
the string "NaN", and both sides have to cope with it.

`tookMs` is stored as `null`, since it is machine-dependent and would make the
files churn without telling a test anything.
""",
        encoding="utf-8",
    )
    written.append("README.md")

    print()
    print(f"wrote {len(written)} files to {args.out}")
    for name in written:
        size = (args.out / name).stat().st_size
        print(f"  {name:<32} {size / 1024:6.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
