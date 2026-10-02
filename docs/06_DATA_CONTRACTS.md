# 06 - Data Contracts

Exact formats shared between React, Java and Python. If you change anything here, update all sides and their tests in the same commit.

General rules:
- Times in cases are epoch seconds (`...Sec`) unless a field says `Ms`.
- Missing numbers are JSON `null` (never 0, never the string "NaN").
- JSON field names are camelCase. Python pydantic models use aliases.

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
  "params": { "useChangePoint": true, "traversal": true, "topK": 5, "seed": 42 }
}
```
- `values` is row-major; each inner list has exactly `columns.length` entries in the same order.
- `params` optional; missing keys use `PareConfig` defaults.
- Ground truth is NEVER part of this request.

### POST /v1/analyze - response (AnalyzeResponse)
```json
{
  "requestId": "uuid",
  "engine": "PARE",
  "engineVersion": "0.1.0",
  "tookMs": 312,
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
`role`: `CAUSE`, `SYMPTOM`, `ALSO_ABNORMAL`, `NORMAL`.
For engines without residuals: `score == marginalScore`, `inheritedFraction = 0`, `explainedBy = null`.

### POST /v1/synthetic - request
```json
{ "nServices": 10, "faultType": "latency", "rootService": null, "propagation": 0.8,
  "noise": "medium", "nNormal": 600, "nAbnormal": 180, "seed": 7 }
```
Response: synthetic case JSON (section 2).

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
top1_service, top1_indicator, symptom_error, faithfulness_auc, runtime_s
```
- `rank_gt_*`: 1-based, empty if not ranked.
- `symptom_error`: true if top-1 is wrong AND top-1 calls the true root cause directly or indirectly; empty if no graph.

Each run folder also has `config.yaml`, `env.txt` (Python and package versions, CPU) and `log.txt`.
