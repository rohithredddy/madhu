# 06 - Data Contracts

Exact formats shared between React, Java and Python. If you change anything here, update all sides and their tests in the same commit.

General rules:
- Times in cases are epoch seconds (`...Sec`) unless a field says `Ms`.
- Missing numbers are JSON `null` (never 0, never the string "NaN").
- JSON field names are camelCase. Python pydantic models use aliases.
- Enum-like string values are UPPERCASE in JSON: `faultType`, `source`, `graph.source`, `role`,
  `verdict`, `confidence`, `state`, `mode`, and the synthetic `noise` level. The Python library may
  use lowercase internally (for example `fault="latency"`); the FastAPI service layer converts at
  the boundary (`05_PYTHON_ANALYZER_SPEC.md` section 5).

## 1. Columns

A column is one metric of one service, e.g. `cartservice_mem`. The meaning always comes from an explicit column map, never from splitting the name inside the algorithm:
```json
{ "name": "cartservice_mem", "service": "cartservice", "metric": "mem" }
```
Common metric names: `cpu`, `mem`, `latency`, `error`, `rps`, `disk`, `net`. Other names are allowed.

## 2. Case format (folder on disk)

```
data/cases/<caseId>/
  data.csv     first column "time" (epoch seconds, increasing), then one column per metric
  meta.json
```

`meta.json`:
```json
{
  "caseId": "re1-ob-cartservice_mem-1",
  "source": "RCAEVAL_RE1",
  "system": "online-boutique",
  "faultType": "MEM",
  "injectTimeSec": 1705000000,
  "groundTruth": { "service": "cartservice", "indicator": "cartservice_mem" },
  "columns": [ { "name": "cartservice_mem", "service": "cartservice", "metric": "mem" } ],
  "graph": {
    "source": "STATIC_ARCHITECTURE",
    "edges": [ { "from": "frontend", "to": "cartservice" } ]
  },
  "notes": "exported from RCAEval RE1 by export_cases.py"
}
```
- `source`: `RCAEVAL_RE1`, `RCAEVAL_RE2`, `RCAEVAL_RE3`, `SYNTHETIC`, `UPLOAD`.
- `faultType` is always UPPERCASE. Synthetic cases use `LATENCY`, `CPU`, `MEM`, `ERROR`. RCAEval
  cases keep the dataset's own names, uppercased: `CPU`, `MEM`, `DISK`, `DELAY`, `LOSS`, plus the
  RE3 code-level fault names. `export_cases.py` and `SyntheticService` are the only places that
  write this field, so the uppercasing happens in exactly two places.
- `groundTruth` may be `null` for uploads.
- `graph.source`: `TRACES`, `STATIC_ARCHITECTURE`, `CORRELATION`, `SYNTHETIC_TRUE`, `USER`, `NONE`.
- Edge direction: caller -> callee.

Synthetic cases returned by Python `/v1/synthetic` use the same content as JSON: `{ "meta": {...}, "timeSec": [...], "values": [[...], ...] }`. Java writes them to disk in the folder format.

## 3. Python engine API

### POST /v1/analyze - request (AnalyzeRequest)
```json
{
  "requestId": "uuid",
  "engine": "PARE",
  "alarmTimeSec": 1705000030,
  "columns": [
    { "name": "cartservice_mem", "service": "cartservice", "metric": "mem" },
    { "name": "frontend_latency", "service": "frontend", "metric": "latency" }
  ],
  "normal": { "timeSec": [1704999000, 1704999001], "values": [[210.5, 31.2], [211.0, 30.8]] },
  "recent": { "timeSec": [1704999730, 1704999731], "values": [[212.0, 31.0], [390.2, 88.1]] },
  "graph": { "source": "STATIC_ARCHITECTURE", "edges": [ { "from": "frontend", "to": "cartservice" } ] },
  "params": { "useChangePoint": true, "traversal": true, "topK": 10, "seed": 42 }
}
```
- `values` is row-major; each inner list has exactly `columns.length` entries in the same order.
- `params` optional; missing keys use `PareConfig` defaults (listed in `05_PYTHON_ANALYZER_SPEC.md`
  section 1.1).
- `topK` (default 10) is only the number of indicators returned in `indicators`. It is a different
  thing from the internal `cpTopK` (default 5), which is how many columns the change-point step
  looks at. Both can be set here.
- **Which keys are allowed**: exactly the `PareConfig` fields from
  `05_PYTHON_ANALYZER_SPEC.md` section 1.1, with the snake_case field name converted to camelCase.
  The rule is mechanical, so there is no second list of names to keep in step:
  `use_change_point` -> `useChangePoint`, `top_k` -> `topK`, `cp_top_k` -> `cpTopK`,
  `cp_lookback_s` -> `cpLookbackS`, `seed` -> `seed`. `pare.config.api_param_names()` returns the
  full list, and `PareConfig.from_api_params()` is the only place that does the conversion.
- An **unknown key is rejected** with HTTP 422 rather than ignored. A request that says `topk`
  instead of `topK` is a mistake worth reporting, not something to silently analyse with defaults.
- Ground truth is NEVER part of this request.

### POST /v1/analyze - response (AnalyzeResponse)
```json
{
  "requestId": "uuid",
  "engine": "PARE",
  "engineVersion": "0.1.0",
  "tookMs": 312,
  "verdict": "ROOT_CAUSE_FOUND",
  "alarmTimeSec": 1705000030,
  "changePointSec": 1705000002,
  "windowStartSec": 1705000002,
  "windowEndSec": 1705000150,
  "services": [
    { "service": "cartservice", "rank": 1, "score": 11.2, "marginalScore": 11.9,
      "inheritedFraction": 0.06, "topIndicator": "cartservice_mem", "role": "CAUSE", "explainedBy": null },
    { "service": "frontend", "rank": 2, "score": 1.4, "marginalScore": 8.3,
      "inheritedFraction": 0.83, "topIndicator": "frontend_latency", "role": "SYMPTOM", "explainedBy": "cartservice" }
  ],
  "indicators": [
    { "column": "cartservice_mem", "service": "cartservice", "metric": "mem",
      "rank": 1, "selfScore": 11.2, "marginalScore": 11.9, "inheritedFraction": 0.06 }
  ],
  "warnings": [ "dropped constant column emailservice_disk" ]
}
```
`verdict`: `ROOT_CAUSE_FOUND` or `NO_CLEAR_CAUSE`. It is `NO_CLEAR_CAUSE` when the rank-1 service
score is below `minCauseScore` (default 3.0). In that case the ranked list is still returned as the
best guess available, but **no service has role `CAUSE`**, and the Java side words the headline
accordingly (`03_JAVA_BACKEND_SPEC.md` section 4.6).

`role`: `CAUSE`, `SYMPTOM`, `ALSO_ABNORMAL`, `NORMAL`. Assigned in strict precedence order, so a
service has exactly one role; see `05_PYTHON_ANALYZER_SPEC.md` section 3, step 4.

`inheritedFraction` is in [0, 1] and is computed in the metric's raw units
(`1 - self_dev / marginal_dev`), not from the normalised scores. `selfScore` stays normalised by
the residual MAD, because that is the ranking score.

`indicators` has at most `params.topK` entries (default 10).

For engines without residuals: `score == marginalScore`, `inheritedFraction = 0`, `explainedBy = null`.

### POST /v1/synthetic - request
```json
{ "nServices": 10, "faultType": "LATENCY", "rootService": null, "propagation": 0.8,
  "amplification": 0.5, "noise": "MEDIUM", "nNormal": 600, "nAbnormal": 180, "seed": 7 }
```
- `faultType`: `LATENCY` | `CPU` | `MEM` | `ERROR` (UPPERCASE).
- `amplification`: 0 or more, default 0. How non-linearly a caller degrades once a callee is slow.
  0 is purely linear propagation, where a caller can never look worse than the service that broke.
  Around 0.5 a caller can out-shout the culprit, which is the mistake this project is about; above
  about 0.7 nothing metric-only can tell them apart. See `05_PYTHON_ANALYZER_SPEC.md` section 5.
- `noise`: `LOW` | `MEDIUM` | `HIGH`. The service layer maps these to the float the library wants:
  LOW -> 0.5, MEDIUM -> 1.0, HIGH -> 2.0.
- Anything else in these two fields is HTTP 422 with a clear message.

Response: synthetic case JSON (section 2), with the UPPERCASE `faultType` in `meta`.

### GET /v1/engines - response
```json
[ { "name": "PARE", "description": "Propagation-aware residual explanations (proposed)" } ]
```

## 4. Java backend API objects (for React)

`CaseSummary`:
```json
{ "caseId": "...", "source": "RCAEVAL_RE1", "system": "online-boutique", "faultType": "MEM",
  "gtService": "cartservice", "nRows": 1200, "nColumns": 49 }
```

`AnalysisRun` (returned by analyze/compare/runs):
```json
{
  "runId": "uuid", "caseId": "...", "engine": "PARE", "mode": "ONE_CLICK", "delaySeconds": 30,
  "createdAt": "2026-10-03T10:00:00Z", "tookMs": 340,
  "response": { "...": "AnalyzeResponse as above" },
  "explanation": {
    "headline": "Likely root cause: cartservice (memory use). Confidence: HIGH.",
    "confidence": "HIGH",
    "causeSentences": ["..."], "symptomSentences": ["..."], "evidenceSentences": ["..."], "notes": []
  },
  "groundTruth": { "service": "cartservice", "indicator": "cartservice_mem" },
  "evaluation": { "rankGtService": 1, "rankGtIndicator": 1, "correctTop1": true, "correctTop3": true, "symptomError": false }
}
```

`ReplayState`:
```json
{
  "sessionId": "uuid", "caseId": "...", "state": "WATCHING", "cursor": 640, "totalRows": 1200,
  "speed": 20, "threshold": 6.3,
  "timeSec": [ ... last N ... ], "detectorScore": [ ... ],
  "series": [ { "column": "cartservice_mem", "values": [ ... ] } ],
  "alarmTimeSec": null, "topColumnsAtAlarm": [], "run": null
}
```
`state`: `LEARNING`, `WATCHING`, `ALARM`, `EXPLAINED`, `FINISHED`, `STOPPED`.

`BenchmarkSummary` (inside a job):
```json
{ "rows": [ { "engine": "PARE", "delaySeconds": 0, "cases": 125, "ac1": 0.0, "ac3": 0.0, "avg5": 0.0,
              "expAc3": 0.0, "symptomRate": 0.0, "meanMs": 0 } ],
  "failed": [ { "caseId": "...", "engine": "...", "error": "..." } ] }
```
(The zeros are placeholders, not results.)

Error body for every 4xx/5xx: `{ "error": "short message", "details": "optional" }`.

## 5. Experiment result files (Python, for the paper)

Per-case results `experiments/results/<run_id>/cases.csv`, one row per (case, method, delay, seed):
```
run_id, dataset, system, case_id, fault_type, gt_service, gt_indicator,
method, delay_s, seed, rank_gt_service, rank_gt_indicator,
rank_gt_indicator_loose, top1_service, top1_indicator,
tied_gt_service, tied_gt_indicator, tied_gt_indicator_loose,
symptom_error, verdict, runtime_s
```
- `rank_gt_*`: 1-based, empty if not ranked. When several items share the ground truth's score, this
  records the **best** rank the tied group occupies, and `tied_gt_service` / `tied_gt_indicator`
  record how many items share it, so the metrics can score the tie properly rather than letting the
  order of column names decide. See `08_EXPERIMENTS_SPEC.md` section 4 for the rule.
- `rank_gt_indicator` is the **strict** indicator rank: the one metric that is unambiguously the
  right answer. It is empty whenever the fault type has no such metric, which for RCAEval RE1 means
  every DISK, DELAY and LOSS case.
- `rank_gt_indicator_loose` is the best rank reached by **any** metric that could reasonably be
  called correct for that fault type, so it is filled in for every case. For CPU and MEM the
  acceptable set holds exactly one metric, so the loose rank equals the strict one; the two columns
  differ only where the strict one is empty. Which of the two a table reports is a stated choice, not
  a detail: see `08_EXPERIMENTS_SPEC.md` section 4, "Which indicator counts as correct".
- `symptom_error`: true if top-1 is wrong AND top-1 calls the true root cause directly or indirectly; empty if no graph.

- `verdict`: `ROOT_CAUSE_FOUND` or `NO_CLEAR_CAUSE`, as returned by the engine.

E5 (faithfulness and stability) does not write into `cases.csv`. It writes its own files in the
same run folder, because it has a different shape (one row per case, method and k, or per
perturbation):

```
experiments/results/<run_id>/faithfulness.csv
  run_id, dataset, system, case_id, method, k, score_after_deletion, auc_normalized, random_auc_normalized
experiments/results/<run_id>/stability.csv
  run_id, dataset, system, case_id, method, seed, subsample, window_shift_s, top5_jaccard, kendall_tau
```

Each run folder also has `config.yaml`, `env.txt` (Python and package versions, CPU) and `log.txt`.
