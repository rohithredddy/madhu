# 05 - Python Analyzer Spec (PARE engine)

The analyzer is one Python package (`pare`) used in two ways:
1. As a library by the offline experiments (`experiments/`).
2. As a FastAPI web service called by the Java Spring Boot backend over REST (the React frontend never calls Python directly).

CPU only. No deep learning.

## 1. Package layout

```
analyzer/
  pyproject.toml          (package name "pare", extras [dev] with pytest, ruff)
  pare/
    __init__.py
    config.py             PareConfig dataclass with all parameters and defaults
    columns.py            ColumnInfo(name, service, metric) and helpers
    preprocess.py         cleaning, NaN handling, counter-to-rate
    graph.py              CallGraph: children(s), parents(s), ancestors(s), from_edges(), infer_from_correlation()
    scores.py             robust_z, window_score, ecdf_tail_score
    changepoint.py        estimate_change_point()
    residual.py           DependencyModel: fit on normal, residual self-scores, inherited fraction, explained_by
    rank.py               rank_services(), traversal_rank(), rank_indicators(), assign_roles()
    explainers.py         shap_iforest(), pca_reconstruction(), ecdf_explainer(), kernel_shap_pca() (optional)
    engine.py             analyze(request) -> result; registry of engines
    synthetic.py          synthetic microservice data with known root cause (for tests and sanity checks)
    eval_metrics.py       ac_at_k, avg_at_5, exp_ac_at_k, symptom_error, deletion_faithfulness, topk_jaccard
  service/
    app.py                FastAPI app
    schemas.py            pydantic models matching docs/06_DATA_CONTRACTS.md
  tests/
```

## 2. Inputs (inside the library)

- `normal`: pandas DataFrame, index = time (ms or s), columns = metric columns. Data from before the problem.
- `recent`: DataFrame with the same columns, covering some time before the alarm and the time after it.
- `alarm_time`: time when the detector fired (or simulated detection time in experiments).
- `columns`: list of `ColumnInfo` mapping each column to `(service, metric)`. Never parse column names inside the algorithm; the adapter or the Java side gives this map.
- `graph`: `CallGraph` (edges from caller to callee). May be empty.
- `config`: `PareConfig`.

## 3. PARE algorithm, step by step

### Step 0. Preprocess
- Drop columns with more than 50% NaN in `normal`. Forward-fill then back-fill gaps of up to 3 rows.
- Drop columns that are constant in `normal` (MAD == 0 and std == 0). Record them in `warnings`.
- Do not standardize here; each step handles its own scaling.

### Step 1. Marginal scores (how unusual is each column, ignoring the graph)
- For each column c: `med_c = median(normal_c)`, `mad_c = 1.4826 * MAD(normal_c) + eps` (eps = 1e-6 x (|med_c| + 1)).
- Per-row robust z: `z_c(t) = (x_c(t) - med_c) / mad_c`.
- Window score: `marginal_c = |median(abnormal_c) - med_c| / mad_c`, where `abnormal` is the analysis window (Step 2 decides where it starts). Using the median of the window, not the max, makes it robust to single spikes.

### Step 2. Change-point re-anchoring
- Purpose: real detectors are late. Find where the change really started.
- Take the top `cp_top_k` (default 5) columns by `max |z_c(t)|` over `recent` up to the alarm.
- For each, take the series from `alarm_time - cp_lookback` (default 300 s) to `alarm_time + cp_lookahead` (default 0 live; up to 60 s offline if available), standardize it, and find the single best change point with `ruptures.Binseg(model="l2").fit(x).predict(n_bkps=1)`. (Check the ruptures API in the installed version.)
- Change point = median of these candidate times.
- Analysis window = `[change_point, change_point + window_len]` (default 120 s), cut to available data.
- If `use_change_point=False`, the window starts at `alarm_time`.
- Return the change point in the result (the Java side shows it).

### Step 3. Dependency model (the core idea)
For each service s and each of its columns c:
- Features = all columns of the services that s calls directly (`graph.children(s)`), at time t and t-1 (one lag). Do NOT use s's own past values: an autoregressive term would "learn" the anomaly after it starts and hide it.
- If s has no children, or no usable features: residual = `x_c - med_c` (self-score equals marginal score).
- Otherwise fit `Ridge(alpha=ridge_alpha)` (default 1.0) on standardized features using `normal` rows only. Optional: `LGBMRegressor(n_estimators=100, max_depth=3)` when `dependency_model="lgbm"`.
- Residuals on normal rows give `res_med_c`, `res_mad_c`.
- Self-score: `self_c = |median(residual over abnormal window) - res_med_c| / (1.4826 * res_mad_c + eps)`.
- Inherited fraction: `inherited_c = clip(1 - self_c / marginal_c, 0, 1)` when `marginal_c > 0`, else 0.
- Explained by: for the ridge model, contribution of child k = sum over k's features of `coef_j * (median(abnormal feature_j) - median(normal feature_j))` (in standardized units). `explained_by_c` = child with the largest positive contribution, or null.

### Step 4. Rank services
- Service score `S_s = max_c self_c` (option `service_agg="top2mean"`).
- Default ranking: sort by `S_s` descending.
- Optional traversal (`traversal=True`), inspired by Orchard et al. 2025: start at the service with the highest marginal score; while some child has a higher `S` than the current node, move to the child with the highest `S`. Put the final node at rank 1; others follow by `S_s`.
- Roles: rank 1 = `CAUSE`; any other service with max marginal >= `symptom_min_marginal` (default 3.0) and inherited fraction of its top column >= 0.6 = `SYMPTOM`; others with marginal >= 3.0 = `ALSO_ABNORMAL`; rest = `NORMAL`.

### Step 5. Rank indicators
- Global list of columns sorted by `self_c` descending, each with service, metric, self, marginal, inherited.
- Fine-grained answer = top column within the rank-1 service.

### Step 6. Return
A result object matching `AnalyzeResponse` in `06_DATA_CONTRACTS.md`, plus timing (`took_ms`) and `warnings`.

## 4. Engines (registry in `engine.py`)

| Engine name | What it does | Role in the paper |
|---|---|---|
| `PARE` | Full method above | Proposed method |
| `PARE_NO_RESIDUAL` | Ranking by marginal scores only (+ change point) | Ablation |
| `PARE_NO_CP` | Full method, window starts at alarm time | Ablation |
| `PARE_LGBM` | LightGBM dependency model | Ablation |
| `NSIGMA` | Mean of abnormal vs mean/std of normal, max per service | Baseline (must match Java FallbackRanker) |
| `SHAP_IFOREST` | IsolationForest(n_estimators=200, random_state=seed) on normal rows; TreeSHAP on abnormal rows; mean absolute SHAP per column; service score = sum over its columns (GAL-MAD style) | Baseline / C1 explainer |
| `ECDF` | ECOD-style per-column tail score: `-log` of the empirical two-sided tail probability of the abnormal median under the normal ECDF; service score = max | C1 explainer |
| `PCA_RECON` | PCA (keep 95% variance) on standardized normal rows; per-column squared reconstruction error on abnormal rows | C1 explainer |
| `KERNEL_SHAP_PCA` (optional) | KernelSHAP on the PCA detector with 50 background rows | C1 explainer if time allows |

Before using `shap.TreeExplainer` on IsolationForest, check that the installed shap version supports it. If not, fall back to `shap.Explainer` with a small background set and note it.

All engines return the same result shape, so experiments and the Java side do not care which engine ran.

## 5. Synthetic data (`synthetic.py`) - used for tests

`make_case(n_services=8, n_normal=600, n_abnormal=120, fault="latency"|"cpu"|"memory"|"error", root=None, propagation=0.8, noise=1.0, seed=0)`:
- Random tree call graph (root node = "frontend").
- For each service s, columns: `latency`, `error`, `cpu`, `mem`, `rps`.
  - `rps` = shared load signal (slow sine + noise), same for all services, scaled.
  - `latency_s = base_s + sum_{k in children(s)} w_k * latency_k + noise`, with `w_k = propagation x U(0.8, 1.2)`.
  - `error_s = base_s + sum_{k in children(s)} v_k * error_k + noise`.
  - `cpu_s = a_s * rps + noise`, `mem_s` = random walk around a level.
- Fault at the root-cause service r from the first abnormal row:
  - latency: `latency_r += 6 * std`; cpu: `cpu_r += 6 * std` and `latency_r += 2 * std`; memory: `mem_r` ramps up linearly to +8 std; error: `error_r += 6 * std`.
- Propagation to callers happens automatically through the equations.
- Returns normal df, abnormal df, columns, graph, ground truth (service, column).

## 6. Tests (must pass before any experiment)

- `scores.py`: robust z and window score on hand-made arrays.
- `changepoint.py`: a step series with a known change at index 100 is found within +/- 3 rows.
- `residual.py`: if a parent's latency is exactly a linear function of a child's latency, the parent's self-score is near 0 when only the child is faulty.
- `engine.py` with synthetic data, fixed seeds 0..49:
  - PARE top-1 accuracy for `latency` faults >= 0.85.
  - PARE top-1 accuracy >= PARE_NO_RESIDUAL top-1 accuracy (this is the core claim; if it fails, stop and report, do not tune the test to pass).
- Every engine returns a valid result for a case with some NaN columns and an empty graph.

## 7. FastAPI service

- `GET /health` -> `{"status":"ok","version":"x.y.z"}`
- `GET /v1/engines` -> list of engine names with a one-line description each
- `POST /v1/synthetic` -> generates one synthetic case and returns it in the case format (`06_DATA_CONTRACTS.md` section 2, JSON form). Parameters: nServices, faultType, rootService (optional), propagation, noise, nNormal, nAbnormal, seed
- `POST /v1/analyze` -> request/response exactly as `AnalyzeRequest` / `AnalyzeResponse` in `06_DATA_CONTRACTS.md`
- Convert `null` values to NaN. Validate that each row length equals the number of columns; return HTTP 422 with a clear message otherwise.
- Log one line per request: engine, rows, columns, took_ms.
- Run with `uvicorn service.app:app --host 127.0.0.1 --port 8000` (local only; the Java backend is the only client).
- Typical request (5 services x 7 metrics, 240 normal rows, 60 recent rows) must answer in under 2 seconds on a laptop.
