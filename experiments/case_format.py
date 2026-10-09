"""Write and check the case folders the Java backend reads (`docs/06` section 2).

    data/cases/<caseId>/data.csv    "time" first, then one column per metric
    data/cases/<caseId>/meta.json   source, system, fault, injection, truth, columns, graph

This is the only bridge from the research data to the application (`docs/08`
section 9): `export_cases.py` writes RCAEval cases through it and
`scripts/make_synthetic_cases.py` writes synthetic ones, so both produce exactly
one format, and `validate_case_folder` is what M7's "case folders validate
against section 2" means in code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

SOURCES = {"RCAEVAL_RE1", "RCAEVAL_RE2", "RCAEVAL_RE3", "SYNTHETIC", "UPLOAD"}
GRAPH_SOURCES = {"TRACES", "STATIC_ARCHITECTURE", "CORRELATION", "SYNTHETIC_TRUE", "USER", "NONE"}
CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def write_case(
    root: Path,
    case_id: str,
    frame: pd.DataFrame,
    *,
    source: str,
    system: str,
    fault_type: str,
    inject_time_sec: int,
    ground_truth: Mapping[str, Any] | None,
    columns: Sequence[Mapping[str, str]],
    graph_source: str,
    edges: Iterable[tuple[str, str]],
    notes: str,
) -> Path:
    """Write one case folder and check it. Returns the folder.

    `frame` must hold a `time` column (epoch seconds) and every column named in
    `columns`, in that order; anything else is dropped. Missing readings are
    written as empty cells, which the Java CSV reader turns into null.
    """
    folder = Path(root) / case_id
    folder.mkdir(parents=True, exist_ok=True)

    names = [column["name"] for column in columns]
    table = frame[["time", *names]].copy()
    table["time"] = table["time"].astype("int64")
    table.to_csv(folder / "data.csv", index=False, na_rep="", lineterminator="\n")

    meta = {
        "caseId": case_id,
        "source": source,
        "system": system,
        "faultType": fault_type.upper(),
        "injectTimeSec": int(inject_time_sec),
        "groundTruth": dict(ground_truth) if ground_truth is not None else None,
        "columns": [dict(column) for column in columns],
        "graph": {
            "source": graph_source,
            "edges": [{"from": caller, "to": callee} for caller, callee in edges],
        },
        "notes": notes,
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    problems = validate_case_folder(folder)
    if problems:
        raise ValueError(f"{folder} does not match docs/06 section 2: {problems}")
    return folder


def validate_case_folder(folder: Path) -> list[str]:
    """Every way a case folder breaks the contract, as plain sentences. [] = valid."""
    problems: list[str] = []
    folder = Path(folder)
    meta_path, data_path = folder / "meta.json", folder / "data.csv"
    if not meta_path.exists() or not data_path.exists():
        return ["needs both data.csv and meta.json"]

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    required = ("caseId", "source", "system", "faultType", "injectTimeSec",
                "groundTruth", "columns", "graph")
    problems += [f"meta.json has no {key}" for key in required if key not in meta]
    if problems:
        return problems

    if meta["caseId"] != folder.name:
        problems.append(f"caseId {meta['caseId']!r} differs from the folder name")
    if not CASE_ID.match(str(meta["caseId"])):
        problems.append("caseId may only hold letters, digits, '.', '_' and '-'")
    if meta["source"] not in SOURCES:
        problems.append(f"source {meta['source']!r} is not one of {sorted(SOURCES)}")
    if meta["faultType"] != str(meta["faultType"]).upper():
        problems.append("faultType must be UPPERCASE")
    if meta["graph"].get("source") not in GRAPH_SOURCES:
        problems.append(f"graph.source {meta['graph'].get('source')!r} is not allowed")

    columns = meta["columns"]
    names = [column.get("name") for column in columns]
    if len(set(names)) != len(names):
        problems.append("column names repeat")
    for column in columns:
        if not all(column.get(key) for key in ("name", "service", "metric")):
            problems.append(f"column {column} needs name, service and metric")
    services = {column.get("service") for column in columns}
    for edge in meta["graph"].get("edges", []):
        if edge.get("from") == edge.get("to"):
            problems.append(f"self-loop on {edge.get('from')}")

    truth = meta["groundTruth"]
    if truth is not None:
        if truth.get("service") not in services:
            problems.append(f"ground-truth service {truth.get('service')!r} has no column")
        if truth.get("indicator") is not None and truth["indicator"] not in names:
            problems.append(f"ground-truth indicator {truth['indicator']!r} is not a column")

    header = pd.read_csv(data_path, nrows=0).columns.tolist()
    if not header or header[0] != "time":
        problems.append('data.csv must start with a "time" column')
    elif header[1:] != names:
        problems.append("data.csv columns differ from meta.json columns, or their order does")
    else:
        times = pd.read_csv(data_path, usecols=["time"])["time"]
        if times.isna().any():
            problems.append("data.csv has rows with no time")
        elif not times.is_monotonic_increasing or times.duplicated().any():
            problems.append("time must be strictly increasing")
        elif not (times.iloc[0] < meta["injectTimeSec"] <= times.iloc[-1]):
            problems.append("injectTimeSec is outside the data")
    if isinstance(meta["injectTimeSec"], bool) or not isinstance(meta["injectTimeSec"], int):
        problems.append("injectTimeSec must be an integer of epoch seconds")
    return problems
