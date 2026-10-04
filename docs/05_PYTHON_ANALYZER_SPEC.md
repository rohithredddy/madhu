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
  - Implemented as a counterfactual - what would the fitted model have predicted if this child had
    stayed at its normal level, everything else as it actually was - which for a linear model is
    exactly the formula above, and also works for the LightGBM variant that has no coefficients.

#### Two measured limits of this step

Both were found while building it, both are properties of the approach rather than of the code, and
both belong in the paper's limitations rather than being discovered by a reviewer.

**1. A symptom's self-score is not zero, and grows with the size of the fault.** The model is fitted
on the normal range, and an incident pushes its inputs well outside that range. Any small error in
the fitted slope - and ridge regularisation guarantees one, since it shrinks coefficients on purpose
- is multiplied by how far the fault reaches. Measured on a parent that is exactly twice its child
plus a little noise, with only the child faulty:

| fault size | parent self-score | parent inherited fraction |
|---|---|---|
| 2 std | 0.7 | 0.997 |
| 6 std | 2.3 | 0.996 |
| 12 std | 4.8 | 0.996 |
| 24 std | 9.6 | 0.996 |

The share explained stays essentially constant, which is why `inherited_fraction` is the honest
number to report to a user, while the normalised self-score drifts upward. The consequence is that
the margin between cause and symptom narrows as faults get larger, rather than staying constant.
`ridge_alpha` is worth an ablation for this reason: a smaller alpha cut the parent's self-score from
2.3 to 0.5 in the same setup.

**2. LightGBM is the wrong kind of model for this job, and `PARE_LGBM` should be reported as a
negative result.** A tree ensemble cannot extrapolate: outside the range it was trained on its
prediction is flat. So when a callee goes far beyond anything in the normal period, the model
predicts the caller at its normal level and the caller's entire inherited rise lands in its residual.
On the same parent-and-child setup, ridge gives the parent a self-score of 0.77 against the child's
5.95 - correct - while LightGBM gives the parent **48.5**, ranking the symptom far above the cause.

This is a clean, explainable finding: root-cause analysis by residuals needs a model that
extrapolates, which rules out tree ensembles however well they interpolate. It is kept as a
registered engine so the ablation table can show it, with a test pinning the behaviour so nobody
later mistakes it for a bug.

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
| `PARE_LGBM` | LightGBM dependency model | Ablation (measured: no better, and much slower - see below) |
| `NSIGMA` | Mean of abnormal vs mean/std of normal, max per service. Abnormal window is `[alarm_time, end of recent]`; it **never** uses the change point | Baseline (must match Java FallbackRanker) |

**The baselines are never given the call graph, in any form.** That includes the traversal step in
ranking, which walks the graph to promote a service: it is switched off for `NSIGMA`,
`SHAP_IFOREST`, `ECDF` and `PCA_RECON` through `EngineSpec.use_graph`. Leaving it on would hand a
baseline the one piece of information the proposed method is supposed to contribute, and the
comparison would be meaningless. A behavioural test checks each baseline returns an identical
ranking with and without a graph.
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

`make_case(n_services=8, n_normal=600, n_abnormal=120, fault="latency"|"cpu"|"mem"|"error", root=None, propagation=0.8, noise=1.0, amplification=0.0, seed=0)`:

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
- Fault at the root-cause service r from the first abnormal row. `std` always means the standard
  deviation of that column over the **normal** rows of an unfaulted run, so the fault size is
  relative to how noisy the column normally is:
  - latency: `latency_r += 6 * std`
  - cpu: `cpu_r += 6 * std` **and** `latency_r += 2 * std`
  - mem: `mem_r` ramps up linearly to `+8 * std` **and** `latency_r` ramps up linearly to
    `+2 * std`
  - error: `error_r += 6 * std`
- The faulted service's own latency term is added **before** propagation, so callers inherit it
  through the latency equation.

#### Congestion: why `amplification` exists

With purely linear propagation a caller can **never** look worse than the service that broke, so
the symptom trap this project is about cannot occur in the data at all. The algebra, with `D` the
fault size and `w` the propagation weight:

```
parent = own_noise + w * child
child  z = D / sd_child
parent z = w*D / sqrt(sd_own^2 + w^2 * sd_child^2) = D / sqrt((sd_own/w)^2 + sd_child^2)
```

The parent's denominator is always the larger, so `parent z < child z` for **every** `w`. Raising
propagation scales the inherited signal and the inherited noise by the same factor and they cancel.
This was measured as well as derived: over 200 random cases at `propagation=1.0` the ratio of the
worst caller's score to the culprit's peaked at 0.973 and never reached 1.

Real systems behave differently because a caller does not simply add a scaled copy of its callee's
delay. Queueing, retries, timeouts and thread-pool saturation make a caller degrade out of all
proportion once a callee passes a threshold, while leaving it calm below that threshold. It is that
asymmetry - loud during the fault, silent during normal operation - that lifts the caller's
deviation without widening its normal spread.

So the caller's latency gains one more term:

```
latency_s += amplification * own_scale_s * sum over callees k of max(0, z_k - 3)^2
```

where `z_k` is how slow callee k is in units of its own normal spread, `own_scale_s` is the standard
deviation of the caller's own latency noise, and the onset of 3 is a constant
(`CONGESTION_ONSET_Z`). Squared rather than linear, so the effect is negligible just past the
threshold and severe well beyond it. Exactly zero below the threshold, which is the essential part:
if congestion fired during normal operation it would widen the caller's normal spread and cancel
itself out.

`amplification=0` reproduces the purely linear model exactly, bit for bit, so every result produced
before this was added remains reproducible and the linear case stays available as a comparison.

**Measured behaviour** (40 seeds, 10 services, latency fault, propagation 0.9; top-1 accuracy of
scoring by marginal deviation versus by residual after a least-squares fit on the callees):

| amplification | marginal | residual | of the wrong answers, how many were callers |
|---|---|---|---|
| 0.0 | 1.00 | 1.00 | none wrong |
| 0.5 | 0.50 | 0.70 | 20 of 20 |
| 1.0 | 0.17 | 0.12 | 33 of 33 |
| 2.0 | 0.00 | 0.00 | 40 of 40 |
| 4.0 | 0.00 | 0.03 | 40 of 40 |

Read honestly, there are three regimes, and the paper must report all three:

- **Below about 0.3**: no trap. Marginal scoring is already right, and nothing can improve on it.
- **About 0.3 to 0.7**: the useful band. Callers are loud enough to fool a method that only looks at
  how far each service moved, while subtracting what the callees explain still recovers the culprit.
- **Above about 0.7**: the fault is so amplified downstream that a model fitted on normal data
  cannot explain the caller's response either, because the non-linearity is dormant in the training
  data and no amount of fitting can extrapolate it. Neither method works. This is a real limit of
  metric-only root-cause analysis, and belongs in the threats-to-validity section rather than being
  averaged away.

The band is predicted by the algebra, not just observed: a trap needs the congestion contribution
`A` to exceed `(sqrt(sd_own^2 + w^2 sd_child^2)/w - sd_child) * D`, and a residual method keeps
working while `A < D`.

#### Why a memory fault must also raise the service's own latency

Only `latency` and `error` propagate in the equations above: `mem_s` is a local random walk with no
dependency on the services s calls. So without the `+2 * std` latency term, a memory fault would
produce **no symptoms anywhere**, and that would break three things:

- E6's whole point is that a fault which spreads can make marginal methods blame the services it
  spread to, while PARE does not. With a non-propagating fault the symptom rate would be 0 by
  construction and `PARE_NO_RESIDUAL` would score exactly like `PARE`, so MEM could say nothing
  about the claim. (Spreading is necessary but not sufficient: see "Congestion" above for why
  propagation strength alone never produces the trap.)
- It would contradict this project's own motivating example. `00_RESEARCH_PLAN.md` section 1 and
  `01_PROJECT_OVERVIEW.md` both use "cartservice has a memory leak, so frontend and checkoutservice
  get slow", and figure 1 is meant to be exactly that case. The generator has to be able to make it.
- Real RCAEval MEM faults do propagate, so synthetic MEM would behave unlike the data it is meant
  to explain.

`cpu` already works this way (`+2 * std` on latency), so this is the same mechanism, not a new one.
A service whose memory is exhausted getting slower is also simply what happens.

#### Two-pass construction

`std` has to come from an unfaulted run, but the fault then has to flow up the graph. So the
generator draws every noise array once, builds the series with no fault to measure each column's
normal standard deviation, and then rebuilds with the fault injected **reusing the same noise
arrays**. Reusing the draws is what makes a given seed reproduce bit for bit.

#### What it returns

A `SyntheticCase` with: `normal` and `abnormal` DataFrames (time-indexed, epoch seconds),
`columns` (the explicit `ColumnInfo` list), `edges` (caller -> callee pairs), `gt_service`,
`gt_column` and `inject_time_sec`, plus `to_frame()` for the one continuous series that the case
format and `/v1/synthetic` need.

`edges` is a plain list of `(caller, callee)` tuples rather than a `CallGraph`, because
`graph.py` is built later (M1.4); `CallGraph.from_edges(edges)` consumes it from then on. The E6
graph-quality variants (drop 20% of edges, add 20% wrong ones, no graph) also work directly on an
edge list.

The ground truth is only ever on the returned object, never a column in the data.

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
- `POST /v1/synthetic` -> generates one synthetic case and returns it in the case format (`06_DATA_CONTRACTS.md` section 2, JSON form). Parameters: nServices, faultType (`LATENCY` | `CPU` | `MEM` | `ERROR`), rootService (optional), propagation, amplification, noise (`LOW` | `MEDIUM` | `HIGH`), nNormal, nAbnormal, seed. The returned `meta.json` carries the UPPERCASE `faultType`.
- `POST /v1/analyze` -> request/response exactly as `AnalyzeRequest` / `AnalyzeResponse` in `06_DATA_CONTRACTS.md`
- Convert `null` values to NaN. Validate that each row length equals the number of columns; return HTTP 422 with a clear message otherwise.
- Log one line per request: engine, rows, columns, took_ms.
- Run with `uvicorn service.app:app --host 127.0.0.1 --port 8000` (local only; the Java backend is the only client).
- Typical request (5 services x 7 metrics, 240 normal rows, 60 recent rows) must answer in under 2 seconds on a laptop.
  - Measured on a larger case (8 services x 5 metrics, 400 normal rows): `PARE` about 100 ms,
    `NSIGMA` 4 ms, `ECDF` 13 ms, `PCA_RECON` 17 ms - all comfortably inside the budget.
  - Two engines do not meet it and are **offline baselines rather than interactive ones**:
    `SHAP_IFOREST` at about 2.2 s, which is the cost of fitting 200 trees and running TreeSHAP as
    the published method specifies, and `PARE_LGBM` at about 2.2 s. Neither is the default engine.
    If either is ever offered in the application, the Java timeout (10 s) covers it, but the page
    should warn the user it is slow.
  - The first call in a fresh process additionally pays for importing scikit-learn, shap or
    lightgbm. The service should make one warm-up call at start-up rather than let the first real
    request pay for it.
