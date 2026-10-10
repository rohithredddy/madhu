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

## Run the application (Windows)

Needs Python 3.10, Java 21 and Node 20+. First time only:

```powershell
cd analyzer;  python -m venv .venv;  .venv\Scripts\pip install -e ".[dev]";  cd ..
cd frontend;  npm install;  cd ..
.\analyzer\.venv\Scripts\python.exe scripts\make_synthetic_cases.py      # 12 demo cases
```

Then either run `scripts\start-all.bat`, or start the three parts in three PowerShell windows:

```powershell
cd analyzer;  .venv\Scripts\python.exe -m uvicorn service.app:app --port 8000   # engine
cd backend;   .\mvnw.cmd spring-boot:run                                       # backend :8080
cd frontend;  npm run dev -- --strictPort                                      # UI :5173
```

Open http://localhost:5173. (In PowerShell a program in the current folder needs `.\` in front.)
RCAEval cases appear in the app after `experiments/export_cases.py` has been run on downloaded data.

## Reproduce the paper

Download data with `experiments/download_rcaeval.py --dataset RE1-OB` (RCAEval venv, see
`docs/08_EXPERIMENTS_SPEC.md` section 2). Every experiment takes a YAML config and writes to
`experiments/results/<run_id>/`; seeds are fixed (42).

| Paper item | Command (from the repo root, `analyzer\.venv\Scripts\python.exe ...`) |
|---|---|
| E1 (Table E1) | `experiments/run_c1_grounding.py --config experiments/configs/c1_re1_{ob,ss,tt}.yaml`, then `c1_re1.yaml`; `c1_re2_ob.yaml` |
| E2/E3 (Table E2, Fig. 2) | `experiments/run_rca.py --config experiments/configs/e2_re1_{ob,ss}{,_lookback}.yaml`, then `e2_re1.yaml`, `e2_re1_lookback.yaml`; `e2_re2_ob.yaml` |
| RCAEval baselines | `experiments/run_rcaeval_baselines.py` (RCAEval venv), then `experiments/score_rcaeval.py` |
| Significance | `experiments/stats.py --runs e2_re1 --reference PARE --out e2_re1` |
| E4 (Table E4) | `experiments/run_rca.py --config experiments/configs/e4_re2_ob_{static,traces,correlation,none}.yaml` |
| E5 (Table E5) | `experiments/run_faithfulness.py --out e5_re1` |
| E6 (Fig. 6) | `experiments/run_synthetic_study.py --config experiments/configs/e6_synthetic.yaml` |
| All tables and figures | `experiments/make_tables.py`, `experiments/make_figures.py`, `experiments/make_paper_results.py` |

The paper is `paper/main.tex` (IEEE conference format); zip the `paper/` folder and upload it
to Overleaf to compile.

## Tests

```
cd analyzer && pytest -q            # PARE library
pytest experiments/tests -q         # experiment code, from the repo root
cd backend && ./mvnw -q clean verify
cd frontend && npm run build
```
