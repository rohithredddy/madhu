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

### 1.1 PareConfig parameters (all of them, with defaults)

One dataclass in `config.py`. Every number used anywhere in this spec appears here, so there are
no hidden constants in the code.

| Parameter | Default | What it controls |
|---|---|---|
| `seed` | 42 | Random seed for every engine that uses randomness |
| `max_nan_fraction` | 0.5 | Drop a column with more than this fraction of NaN in `normal` |
| `fill_limit` | 3 | Forward/back-fill gaps of at most this many rows |
| `use_change_point` | true | Re-anchor the analysis window on the estimated change point |
| `cp_top_k` | 5 | How many of the most unusual columns are used to estimate the change point |
| `cp_lookback_s` | 300 | How far before the alarm the change-point search starts |
| `cp_lookahead_s` | 60 | How far after the alarm the change-point search may look (offline only; 0 in replay) |
| `window_len_s` | 120 | Length of the analysis (abnormal) window |
| `dependency_model` | `"ridge"` | `"ridge"` or `"lgbm"` |
| `ridge_alpha` | 1.0 | Ridge regularisation strength |
| `service_agg` | `"max"` | How a service score is built from its columns: `"max"` or `"top2mean"` |
| `traversal` | true | Use the call-graph traversal step when picking rank 1 |
| `symptom_min_marginal` | 3.0 | A service must look at least this abnormal to be called SYMPTOM or ALSO_ABNORMAL |
| `symptom_min_inherited` | 0.6 | Inherited fraction needed to be called SYMPTOM rather than ALSO_ABNORMAL |
| `min_cause_score` | 3.0 | If the top service score is below this, the verdict is `NO_CLEAR_CAUSE` and nobody is CAUSE |
| `top_k` | 10 | How many indicators are returned in the response (`params.topK` on the API) |

`top_k` and `cp_top_k` are two different things: `cp_top_k` is an internal detail of the
change-point step, `top_k` is only the length of the returned indicator list.

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
- For each, take the change-point search window from the table below, standardize it, and find the single best change point with `ruptures.Binseg(model="l2").fit(x).predict(n_bkps=1)`.
  - API checked against the installed `ruptures v1.1.10` on 2026-10-03, so this is not a guess:
    `predict(n_bkps=1)` returns a **list of breakpoint indices whose last element is always
    `len(x)`**. For a series with a step at index 100 it returns `[100, 200]`. So the change point
    is `bkps[0]`; the trailing sentinel must be dropped, never treated as a change point.
- Change point = median of these candidate times.
- If `use_change_point=False`, the analysis window starts at `alarm_time` instead.
- Return the change point in the result (the Java side shows it).

#### The windows, in one table

This is the single definition of every window. The Java side (`03_JAVA_BACKEND_SPEC.md`
section 4.2) and the experiments follow it; the numbers are not restated anywhere else.

| Window | Range | Who decides it |
|---|---|---|
| `normal` | rows before `inject_time - normal_gap` (gap 30 s) | caller (Java `WindowSplitter` or the experiment adapter) |
| `recent` sent to the engine, one-click analyze | `[alarm_time - 300 s, alarm_time + 120 s]` | caller |
| `recent` sent to the engine, replay | only rows already played, so `[alarm_time - 300 s, now]` | caller; never includes future rows |
| change-point search | `[alarm_time - cp_lookback_s, alarm_time + min(cp_lookahead_s, available data)]` | engine, step 2 |
| analysis (abnormal) window, `PARE`, `PARE_NO_RESIDUAL`, `PARE_LGBM` | `[change_point, change_point + window_len_s]`, cut to available data | engine, step 2 |
| analysis window, `PARE_NO_CP` | `[alarm_time, alarm_time + window_len_s]`, cut to available data | engine, step 2 |
| analysis window, `NSIGMA` and the explainer baselines | `[alarm_time, end of recent]`, change point never used | engine, section 4 |

In replay `cp_lookahead_s` is effectively 0, because no row after the alarm plus the short wait
has been played yet. The engine simply never sees rows it was not given.

### Step 3. Dependency model (the core idea)
For each service s and each of its columns c:
- Features = all columns of the services that s calls directly (`graph.children(s)`), at time t and t-1 (one lag). Do NOT use s's own past values: an autoregressive term would "learn" the anomaly after it starts and hide it.
- If s has no children, or no usable features: residual = `x_c - med_c` (self-score equals marginal score).
- Otherwise fit `Ridge(alpha=ridge_alpha)` (default 1.0) on standardized features using `normal` rows only. Optional: `LGBMRegressor(n_estimators=100, max_depth=3)` when `dependency_model="lgbm"`.
- Residuals on normal rows give `res_med_c`, `res_mad_c`.
- Self-score: `self_c = |median(residual over abnormal window) - res_med_c| / (1.4826 * res_mad_c + eps)`.
- Inherited fraction. Compute it on one scale, in the metric's raw units, so the two parts are
  comparable and the number really is a fraction. (An earlier version of this spec divided a
  residual-MAD score by a raw-MAD score, which is not a ratio of like quantities and could leave
  the "fraction" outside a sensible range.)

  ```
  marginal_dev_c = |median(abnormal_c) - median(normal_c)|
  self_dev_c     = |median(abnormal residual_c) - median(normal residual_c)|
  inherited_c    = clip(1 - self_dev_c / marginal_dev_c, 0, 1)      # 0 if marginal_dev_c == 0
  ```

  `self_c` above (normalised by the residual MAD) does not change: it stays the ranking score.
  `inherited_c` is only for reporting and for the SYMPTOM role test.
- Explained by: for the ridge model, contribution of child k = sum over k's features of `coef_j * (median(abnormal feature_j) - median(normal feature_j))` (in standardized units). `explained_by_c` = child with the largest positive contribution, or null.

### Step 4. Rank services
- Service score `S_s = max_c self_c` (option `service_agg="top2mean"`).
- Default ranking: sort by `S_s` descending.
- Optional traversal (`traversal=True`), inspired by Orchard et al. 2025: start at the service with the highest marginal score; while some child has a higher `S` than the current node, move to the child with the highest `S`. Put the final node at rank 1; others follow by `S_s`.

#### Verdict: is anything clearly wrong at all?

A window can be quiet. The method must be able to say "I see nothing clear" instead of always
accusing whichever service happens to come first.

- If the rank-1 service score `S_1 >= min_cause_score` (default 3.0): `verdict = ROOT_CAUSE_FOUND`.
- Otherwise `verdict = NO_CLEAR_CAUSE`, and **no service is given the role `CAUSE`**. The ranking
  is still returned (it is the best guess available) and the Java side words the headline
  accordingly.

#### Roles, in strict precedence order

Each service gets the first role it qualifies for, top to bottom:

| Order | Role | Condition |
|---|---|---|
| 1 | `CAUSE` | rank 1, and only if `verdict == ROOT_CAUSE_FOUND` |
| 2 | `SYMPTOM` | max marginal >= `symptom_min_marginal` (3.0) **and** inherited fraction of its top column >= `symptom_min_inherited` (0.6) |
| 3 | `ALSO_ABNORMAL` | max marginal >= `symptom_min_marginal` (3.0) |
| 4 | `NORMAL` | anything else |

Because the order is strict, a service is never both SYMPTOM and ALSO_ABNORMAL, and when the
verdict is `NO_CLEAR_CAUSE` the rank-1 service falls through to whichever of SYMPTOM /
ALSO_ABNORMAL / NORMAL it qualifies for.

### Step 5. Rank indicators
- Global list of columns sorted by `self_c` descending, each with service, metric, self, marginal, inherited.
- Fine-grained answer = top column within the rank-1 service.

### Step 6. Return
A result object matching `AnalyzeResponse` in `06_DATA_CONTRACTS.md`, including `verdict`, the
estimated change point, the window bounds, at most `top_k` indicators, timing (`took_ms`) and
`warnings`.

## 4. Engines (registry in `engine.py`)

| Engine name | What it does | Role in the paper |
|---|---|---|
| `PARE` | Full method above | Proposed method |
| `PARE_NO_RESIDUAL` | Ranking by marginal scores only (+ change point) | Ablation |
| `PARE_NO_CP` | Full method, window starts at alarm time | Ablation |
| `PARE_LGBM` | LightGBM dependency model | Ablation |
| `NSIGMA` | Mean of abnormal vs mean/std of normal, max per service. Abnormal window is `[alarm_time, end of recent]`; it **never** uses the change point | Baseline (must match Java FallbackRanker) |
| `SHAP_IFOREST` | IsolationForest(n_estimators=200, random_state=seed) on normal rows; TreeSHAP on abnormal rows; mean absolute SHAP per column; service score = sum over its columns (GAL-MAD style) | Baseline / C1 explainer |
| `ECDF` | ECOD-style per-column tail score: `-log` of the empirical two-sided tail probability of the abnormal median under the normal ECDF; service score = max | C1 explainer |
| `PCA_RECON` | PCA (keep 95% variance) on standardized normal rows; per-column squared reconstruction error on abnormal rows | C1 explainer |
| `KERNEL_SHAP_PCA` (optional) | KernelSHAP on the PCA detector with 50 background rows | C1 explainer if time allows |

`shap.TreeExplainer` on IsolationForest was checked against the installed `shap 0.49.1` on
2026-10-03 and works: `shap.TreeExplainer(iso).shap_values(X)` returns an array of shape
`(n_rows, n_columns)`, the additivity check passes (no `check_additivity=False` needed), and on a
planted single-column anomaly the mean absolute SHAP correctly puts that column first. If a future
shap version drops this, fall back to `shap.Explainer` with a small background set and record it in
`warnings`.

`NSIGMA` and the explainer baselines (`SHAP_IFOREST`, `ECDF`, `PCA_RECON`, `KERNEL_SHAP_PCA`)
never use change-point re-anchoring: their abnormal window is always
`[alarm_time, end of recent]`. This matters for two reasons. First, it is what makes them honest
baselines: the delay-robustness claim (RQ4) is about what the change point adds, so the baselines
must feel the full effect of a late alarm. Second, `NSIGMA` and the Java `NSIGMA_JAVA_FALLBACK`
then share one window definition, so the shared-sample agreement test in
`03_JAVA_BACKEND_SPEC.md` section 4.4 can actually pass.

All engines return the same result shape, so experiments and the Java side do not care which engine ran.
Engines without residuals return `score == marginalScore`, `inheritedFraction = 0` and
`explainedBy = null`, and they set `verdict` by the same `min_cause_score` rule.

## 5. Synthetic data (`synthetic.py`) - used for tests

`make_case(n_services=8, n_normal=600, n_abnormal=120, fault="latency"|"cpu"|"mem"|"error", root=None, propagation=0.8, noise=1.0, seed=0)`:

Naming and types at the boundary:
- Inside the library, `fault` is lowercase (`"latency"`, `"cpu"`, `"mem"`, `"error"`) and `noise`
  is a float multiplier on the noise standard deviation.
- On the API and in `meta.json`, `faultType` is UPPERCASE (`LATENCY`, `CPU`, `MEM`, `ERROR`) and
  `noise` is one of the strings `LOW`, `MEDIUM`, `HIGH`.
- The **service layer** (`service/app.py`) does the conversion, not the library:

  | API `noise` | `make_case(noise=...)` |
  |---|---|
  | `LOW` | 0.5 |
  | `MEDIUM` | 1.0 (the default) |
  | `HIGH` | 2.0 |

  and `faultType` is lowercased on the way in, uppercased on the way out. An unknown value gives
  HTTP 422 with a clear message.
- Random tree call graph (root node = "frontend").
- For each service s, columns: `latency`, `error`, `cpu`, `mem`, `rps`.
  - `rps` = shared load signal (slow sine + noise), same for all services, scaled.
  - `latency_s = base_s + sum_{k in children(s)} w_k * latency_k + noise`, with `w_k = propagation x U(0.8, 1.2)`.
  - `error_s = base_s + sum_{k in children(s)} v_k * error_k + noise`.
  - `cpu_s = a_s * rps + noise`, `mem_s` = random walk around a level.
- Fault at the root-cause service r from the first abnormal row:
  - latency: `latency_r += 6 * std`; cpu: `cpu_r += 6 * std` and `latency_r += 2 * std`; mem: `mem_r` ramps up linearly to +8 std; error: `error_r += 6 * std`.
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
- `verdict`: a window with no injected fault gives `NO_CLEAR_CAUSE` and no service with role
  `CAUSE`; a clear latency fault gives `ROOT_CAUSE_FOUND`.
- `inherited_c` is inside [0, 1] for every column of every synthetic case.

## 7. FastAPI service

- `GET /health` -> `{"status":"ok","version":"x.y.z"}`
- `GET /v1/engines` -> list of engine names with a one-line description each
- `POST /v1/synthetic` -> generates one synthetic case and returns it in the case format (`06_DATA_CONTRACTS.md` section 2, JSON form). Parameters: nServices, faultType (`LATENCY` | `CPU` | `MEM` | `ERROR`), rootService (optional), propagation, noise (`LOW` | `MEDIUM` | `HIGH`), nNormal, nAbnormal, seed. The returned `meta.json` carries the UPPERCASE `faultType`.
- `POST /v1/analyze` -> request/response exactly as `AnalyzeRequest` / `AnalyzeResponse` in `06_DATA_CONTRACTS.md`
- Convert `null` values to NaN. Validate that each row length equals the number of columns; return HTTP 422 with a clear message otherwise.
- Log one line per request: engine, rows, columns, took_ms.
- Run with `uvicorn service.app:app --host 127.0.0.1 --port 8000` (local only; the Java backend is the only client).
- Typical request (5 services x 7 metrics, 240 normal rows, 60 recent rows) must answer in under 2 seconds on a laptop.
