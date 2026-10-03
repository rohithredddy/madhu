# analyzer - Python PARE engine

The `pare` package: the propagation-aware residual explanation method and the baseline engines,
used two ways - as a library by `experiments/`, and as a small FastAPI service that the Java
backend calls over REST.

CPU only, no deep learning. Spec: `docs/05_PYTHON_ANALYZER_SPEC.md`.

    cd analyzer && pip install -e ".[dev]" && pytest -q
    cd analyzer && uvicorn service.app:app --port 8000
