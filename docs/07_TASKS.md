# 07 - Task List

Work top to bottom unless the human says otherwise. One task at a time. After each task: build, test, update `PROGRESS.md`, stop.

Tick boxes (`[x]`) when done.

Two tracks:
- **Track R (research, Python)**: M1 to M6, then M11. Produces the paper.
- **Track A (application: Python service + Java backend + React)**: M7 to M10. Produces the complete application (engine service, Java backend, React frontend).

If a working application is needed early: do M0, M1, M7, M8, M9, M10 (using synthetic cases only), then go back to M2. The application works with synthetic cases before any RCAEval data exists.

---

## M0 - Project skeleton
- [x] M0.1 Create folders: `analyzer/`, `experiments/`, `backend/`, `frontend/`, `scripts/`, `data/` (git-ignored), `paper/` (with `tables/`, `figures/`, `notes/`). Each gets a 2 to 5 line README, **except `data/`**: it is git-ignored, so a README inside it would never be committed. The `data/` layout is described in the root `README.md` instead.
- [x] M0.2 Check `.gitignore` covers Java, Python, Node (`node_modules/`, `dist/`), `data/`, results.
- [x] M0.3 Fill "Environment" in `PROGRESS.md` (Java, Maven, Python, Node, npm versions).
- Done when: first commit is clean.

## M1 - Python PARE core (library)
- [x] M1.1 `analyzer/pyproject.toml`, package `pare`, `config.py`, `columns.py`.
- [x] M1.2 `synthetic.py` (with `propagation` and `noise` parameters) + example plot in `paper/figures/synthetic_example.png`.
- [x] M1.3 `scores.py` + tests.
- [x] M1.4 `graph.py` + tests.
- [x] M1.5 `changepoint.py` + tests.
- [x] M1.6 `residual.py` + tests.
- [x] M1.7 `rank.py` + `engine.py` with `PARE`, `PARE_NO_RESIDUAL`, `PARE_NO_CP`, `NSIGMA`. Also `preprocess.py` (step 0), which the engine cannot run without and which no other task owned. Includes the `verdict` rule (`min_cause_score`) and the strict role precedence from `05_PYTHON_ANALYZER_SPEC.md` section 3, step 4, with tests for both.
- [x] M1.7b `PARE_LGBM` engine (LightGBM dependency model, `dependency_model="lgbm"`) + test that it returns a valid result and that its ranking is sane on one synthetic latency case.
- [ ] M1.8 `explainers.py`: `SHAP_IFOREST`, `ECDF`, `PCA_RECON`; register them.
- [ ] M1.9 `eval_metrics.py` + tests.
- [ ] M1.10 `analyzer/scripts/synthetic_check.py`: 50 seeds x 4 fault types -> CSV of top-1 accuracy per engine.
- [ ] M1.11 Save `analyzer/samples/analyze_request.json` and the matching responses for `PARE` and `NSIGMA` (used by Java tests).
- Done when: `pytest -q` passes and the synthetic check shows PARE top-1 >= PARE_NO_RESIDUAL. If not, stop and report.

## M2 - RCAEval data and baseline reproduction
- [ ] M2.1 Set up RCAEval (separate venv if needed); download RE1 Online Boutique.
- [ ] M2.2 Inspect folders; write structure, column names, inject time and ground-truth labelling in PROGRESS.md before writing code.
- [ ] M2.3 `experiments/adapters/rcaeval.py` + test loading 3 cases.
- [ ] M2.4 Reproduce RCAEval's NSigma and BARO on RE1-OB; compare with our NSIGMA.
- [ ] M2.5 `experiments/graphs/online-boutique.yaml`, `sock-shop.yaml` from the apps' public architecture. Add to "human must check".
- Done when: our NSIGMA matches theirs closely, or the difference is explained.

## M3 - E1 explanation grounding
- [ ] M3.1 `run_c1_grounding.py` (YAML config, joblib, results format from `06_DATA_CONTRACTS.md` section 5).
- [ ] M3.2 Run RE1-OB, then all of RE1.
- [ ] M3.3 `make_tables.py` (table 2), `make_figures.py` (figure 3).
- [ ] M3.4 `paper/notes/E1_findings.md`: 10 plain lines, only numbers from result files.

## M4 - E2 accuracy and E3 delay sweep on RE1
- [ ] M4.1 `run_rca.py` for our engines.
- [ ] M4.2 RCAEval baselines through their package (time limit, failures logged).
- [ ] M4.3 Delay sweep and figure 2.
- [ ] M4.4 `stats.py`; significance in table 3.
- [ ] M4.5 Motivating example figure 1 (one case where SHAP_IFOREST blames a symptom and PARE is right; also note one case where PARE is wrong).

## M5 - RE2/RE3 and E4 graph ablation
- [ ] M5.1 RE2 download one system at a time; chunked loading; parquet cache.
- [ ] M5.2 `build_graph_from_traces.py`.
- [ ] M5.3 E1, E2 on RE2 and RE3 (metrics part); limitations noted.
- [ ] M5.4 E4 graph ablation, table 4.

## M6 - E6 controlled synthetic study
- [ ] M6.1 `run_synthetic_study.py` with the factor grid from `08_EXPERIMENTS_SPEC.md`.
- [ ] M6.2 Figures: AC@1 and symptom rate vs propagation; AC@1 vs graph quality.
- [ ] M6.3 `paper/notes/E6_findings.md`.

## M7 - Python engine service + case export
- [ ] M7.1 `service/schemas.py` matching `06_DATA_CONTRACTS.md` section 3.
- [ ] M7.2 `service/app.py`: `/health`, `/v1/engines`, `/v1/analyze`, `/v1/synthetic`.
- [ ] M7.3 Tests with FastAPI TestClient.
- [ ] M7.4 `experiments/export_cases.py` -> `data/cases/` (skip if RCAEval not downloaded yet; synthetic cases still work).
- [ ] M7.5 `scripts/make_synthetic_cases.py`: writes 12 synthetic cases (3 per fault type) so the app has data from day one.
- Done when: sample request answers in under 2 s and case folders validate against section 2.

## M8 - Java backend core
- [ ] M8.1 Spring Boot project in `backend/`, config, H2, health endpoint, Swagger.
- [ ] M8.2 CaseCatalogService + CaseLoader + case endpoints (+ tiny test case).
- [ ] M8.3 AnalyzerClient + WindowSplitter (+ leakage tests).
- [ ] M8.4 FallbackRanker (+ test against Python NSIGMA sample).
- [ ] M8.5 ExplanationRenderer (+ template tests).
- [ ] M8.6 AnalysisService, AnalysisRun entity, analyze/compare/runs endpoints, report export.
- Done when: with the Python service running, `POST /api/cases/{id}/analyze` returns a full AnalysisRun for a synthetic case; with Python stopped, the fallback is used and says so.

## M9 - Java replay, synthetic, upload, benchmark
- [ ] M9.1 RobustStats, ConformalThreshold, OnlineDetector (+ tests).
- [ ] M9.2 ReplayService + endpoints (+ fast integration test reaching EXPLAINED).
- [ ] M9.3 SyntheticService + endpoint.
- [ ] M9.4 UploadService + validator + guess-columns endpoint.
- [ ] M9.5 BenchmarkService + AccuracyCalculator + endpoints. Consistency check: on 20 cases, Java benchmark AC@1 for PARE equals the Python `run_rca.py` value on the same cases and delay.

## M10 - React frontend
- [ ] M10.1 Vite + React + TS project, router, API client and types, proxy, layout, Home page, status chips.
- [ ] M10.2 Cases list + Case detail (explanation card, call graph, cause vs symptom chart, indicator table, series chart).
- [ ] M10.3 Compare mode.
- [ ] M10.4 Replay page.
- [ ] M10.5 Synthetic lab page.
- [ ] M10.6 Benchmark page.
- [ ] M10.7 Upload page.
- [ ] M10.8 How-it-works page.
- [ ] M10.9 `scripts/start-all.sh` and `start-all.bat`; `npm run build:backend` for single-server mode.
- Done when: every page in `04_REACT_FRONTEND_SPEC.md` works end to end (analyze, compare, replay, synthetic lab, benchmark, upload) with no console errors, using both synthetic and RCAEval cases.

## M11 - Explanation quality and final results
- [ ] M11.1 E5 faithfulness and stability on RE1 (and RE2 if time).
- [ ] M11.2 Regenerate all tables and figures; `paper/notes/RESULTS_SUMMARY.md` (numbers only from results files).
- Done when: every table/figure in `08_EXPERIMENTS_SPEC.md` section 6 exists.

## M12 - Polish
- [ ] M12.1 Root README: what it is, how to run the application, how to reproduce each table.
- [ ] M12.2 Fresh-clone test: follow README on a clean folder; fix anything missing.
- [ ] M12.3 Tag `v1.0`.
