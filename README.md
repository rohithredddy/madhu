# xai-rca: Explainable Anomaly Detection and Root-Cause Analysis for Microservices

MTech final project: research method + paper experiments + full application (React frontend, Java Spring Boot backend, Python engine).

- Research idea and novelty: `docs/00_RESEARCH_PLAN.md`
- Project rules: start with `PROJECT_RULES.md`
- Progress log: `PROGRESS.md`

Parts:
- `analyzer/` - Python PARE engine (library + FastAPI service)
- `experiments/` - Python experiments on the RCAEval benchmark (paper results)
- `backend/` - Java Spring Boot REST backend (application logic)
- `frontend/` - React user interface

Data folders (created at run time, git-ignored, never committed):

```
data/cases/<caseId>/data.csv + meta.json   failure cases the backend reads (exported RCAEval + synthetic)
data/uploads/<caseId>/...                  cases uploaded by a user, same format
data/db/                                   H2 database files
data/RCAEval/RE1, RE2, RE3                 downloaded benchmark data (research only)
data/cache/                                parquet cache of loaded cases
```

The case format is defined in `docs/06_DATA_CONTRACTS.md` section 2. The backend finds this
folder through the `XAIRCA_DATA_DIR` environment variable; the default is `../data` relative
to the backend working directory.

How to run: filled in during milestone M12.
