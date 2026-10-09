"""The engine service: PARE and the baselines behind four HTTP endpoints.

Run from `analyzer/`:

    uvicorn service.app:app --host 127.0.0.1 --port 8000

The Java backend is its only client (`docs/02`: React never calls Python, and
Python stores nothing). Endpoints, from `docs/05` section 7 and `docs/06` section 3:

* `GET  /health`       - `{"status": "ok", "version": ...}`
* `GET  /v1/engines`   - every engine with a one-line description
* `POST /v1/analyze`   - run one engine on one window of data
* `POST /v1/synthetic` - generate a synthetic case with a known root cause

This layer converts at the boundary and does nothing else: UPPERCASE enum values
on the wire, lowercase and floats inside the library (`docs/05` section 5).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pare import __version__
from pare.engine import AnalyzeRequest, analyze, available_engines
from pare.synthetic import make_case
from service.schemas import (
    NOISE_LEVELS,
    AnalyzeRequestModel,
    SyntheticRequestModel,
)

log = logging.getLogger("pare.service")

SAMPLE_REQUEST = Path(__file__).resolve().parents[1] / "samples" / "analyze_request.json"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm up once at start-up, so the first real request does not pay for it.

    The first analysis in a fresh process imports scikit-learn and fits its first
    models, about 2 s (decision 42). `docs/05` section 7 asks for the warm-up.
    """
    try:
        import json

        sample = json.loads(SAMPLE_REQUEST.read_text(encoding="utf-8"))
        analyze(AnalyzeRequest.from_api_dict(sample))
        log.info("warm-up analysis done")
    except Exception as error:  # noqa: BLE001 - a failed warm-up must not stop the service
        log.warning("warm-up skipped: %s", error)
    yield


app = FastAPI(
    title="PARE engine",
    version=__version__,
    description="Propagation-aware residual explanations and baseline engines.",
    lifespan=lifespan,
)


# --- errors: always the docs/06 section 4 body ------------------------------


@app.exception_handler(RequestValidationError)
async def _invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
    details = "; ".join(_describe(item) for item in error.errors())
    return JSONResponse(status_code=422, content={"error": "invalid request", "details": details})


@app.exception_handler(ValueError)
async def _bad_value(_: Request, error: ValueError) -> JSONResponse:
    # ValueError from the library is a problem with what was asked: an unknown
    # engine, an unknown params key, a bad column map. 422, with the reason.
    body = {"error": "invalid request", "details": str(error)}
    return JSONResponse(status_code=422, content=body)


def _describe(item: dict[str, Any]) -> str:
    where = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
    return f"{where}: {item.get('msg')}" if where else str(item.get("msg"))


# --- endpoints --------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/engines")
def engines() -> list[dict[str, str]]:
    return available_engines()


@app.post("/v1/analyze")
def analyze_endpoint(body: AnalyzeRequestModel) -> dict[str, Any]:
    """Run one engine. The request is validated, then read by the library itself."""
    request = AnalyzeRequest.from_api_dict(body.to_library_dict())
    started = time.perf_counter()
    result = analyze(request)
    took_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "analyze engine=%s rows=%d+%d columns=%d took_ms=%d",
        request.engine, request.normal.n_rows, request.recent.n_rows,
        len(request.columns), took_ms,
    )
    return result.to_api_dict()


@app.post("/v1/synthetic")
def synthetic_endpoint(body: SyntheticRequestModel) -> dict[str, Any]:
    """One generated case in the case format of `docs/06` section 2, as JSON."""
    case = make_case(
        n_services=body.nServices,
        n_normal=body.nNormal,
        n_abnormal=body.nAbnormal,
        fault=body.faultType.lower(),
        root=body.rootService,
        propagation=body.propagation,
        noise=NOISE_LEVELS[body.noise],
        amplification=body.amplification,
        seed=body.seed,
    )
    frame = case.to_frame()
    names = [column.name for column in case.columns]
    meta = {
        "caseId": synthetic_case_id(body),
        "source": "SYNTHETIC",
        "system": f"synthetic-{body.nServices}",
        "faultType": case.fault.upper(),
        "injectTimeSec": int(case.inject_time_sec),
        "groundTruth": {"service": case.gt_service, "indicator": case.gt_column},
        "columns": [column.to_dict() for column in case.columns],
        "graph": {
            "source": "SYNTHETIC_TRUE",
            "edges": [{"from": caller, "to": callee} for caller, callee in case.edges],
        },
        "notes": (
            f"generated by pare.synthetic: {body.nServices} services, fault "
            f"{case.fault.upper()} at {case.gt_service}, propagation {body.propagation}, "
            f"amplification {body.amplification}, noise {body.noise}, seed {body.seed}"
        ),
    }
    values = frame[names].to_numpy(dtype=float)
    return {
        "meta": meta,
        "timeSec": [int(t) for t in frame.index.to_numpy()],
        "values": [[None if not np.isfinite(v) else float(v) for v in row] for row in values],
    }


def synthetic_case_id(body: SyntheticRequestModel) -> str:
    """A readable id that is the same for the same settings, so regenerating a
    case replaces it instead of piling up copies."""
    root = body.rootService or "auto"
    return (
        f"synthetic-{body.faultType.lower()}-n{body.nServices}-root-{root}"
        f"-p{body.propagation:g}-a{body.amplification:g}-{body.noise.lower()}-s{body.seed}"
    )
