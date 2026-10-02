# 03 - Java Backend Spec (Spring Boot)

This is the main application backend of the final project. It must be clean, tested, and easy to read and explain. It is a normal REST application: no messaging, no containers.

## 1. Project setup

- Folder: `backend/`. Maven, Java 21, latest stable Spring Boot 3.x.
- Dependencies: spring-boot-starter-web, spring-boot-starter-validation, spring-boot-starter-data-jpa, h2 (runtime), springdoc-openapi-starter-webmvc-ui, spring-boot-starter-test.
- Database: H2 in file mode (`jdbc:h2:file:../data/db/xairca`), `spring.jpa.hibernate.ddl-auto=update`. H2 console enabled only in the `dev` profile.
- CSV reading: plain Java (`BufferedReader`) or Apache Commons CSV. Keep it simple.
- No Lombok. Records for DTOs. Constructor injection.

## 2. Package layout

```
com.xairca.backend
  XaiRcaApplication
  config/      AppProperties (@ConfigurationProperties "app"), RestClientConfig, AsyncConfig, WebConfig
  cases/       CaseCatalogService, CaseLoader, CaseMeta (record), CaseData, CaseSummary (record), ColumnInfo (record), CallGraph (record), Edge (record)
  upload/      UploadService, UploadValidator
  analyze/     AnalysisService, AnalyzerClient, AnalyzeRequest / AnalyzeResponse (records), FallbackRanker, WindowSplitter
  explain/     ExplanationRenderer, Explanation (record), MetricLabels
  replay/      ReplayService, ReplaySession, OnlineDetector, RobustStats, ConformalThreshold, ReplayState (record)
  benchmark/   BenchmarkService, BenchmarkJob (entity), BenchmarkJobRepository, AccuracyCalculator, BenchmarkSummary (record)
  runs/        AnalysisRun (entity), AnalysisRunRepository
  report/      ReportService
  synthetic/   SyntheticService
  api/         CaseController, AnalysisController, ReplayController, BenchmarkController, SyntheticController, UploadController, ReportController, EngineController, HealthController, ApiExceptionHandler
```

## 3. Configuration (`application.yml`)

```
app:
  data-dir: ../data
  cases-dir: ../data/cases
  uploads-dir: ../data/uploads
  engine-url: http://localhost:8000
  engine-timeout-ms: 10000
  default-engine: PARE
  normal-gap-seconds: 30          # gap between normal data and injection time
  recent-before-seconds: 300      # data before the alarm sent as "recent"
  recent-after-seconds: 120       # data after the alarm sent as "recent" (only in one-click analyze)
  replay:
    max-sessions: 3
    baseline-min-rows: 60
    alarm-consecutive-rows: 3
    wait-after-alarm-rows: 20
    target-false-alarm-rate: 0.01
  benchmark:
    workers: 2
```

## 4. Components

### 4.1 CaseCatalogService + CaseLoader
- On startup, scan `cases-dir` and `uploads-dir`. Each subfolder with `meta.json` + `data.csv` is a case. Keep `CaseSummary` list in memory (id, source, system, faultType, gtService, nRows, nColumns).
- `CaseData load(caseId)`: reads the CSV once and caches up to 20 cases (simple LRU via `LinkedHashMap`).
- `CaseData` holds `long[] timeSec`, `double[][] values` (row-major, NaN for empty), `List<ColumnInfo> columns`, `CaseMeta meta`.
- Never guess column meaning from names; use `meta.columns`.

### 4.2 WindowSplitter
Given a case, an alarm time and options:
- `normal` = rows with `time < injectTime - normalGapSeconds`.
- `recent` = rows with `alarmTime - recentBefore <= time <= alarmTime + recentAfter`.
- In replay mode, `recentAfter` is limited to the rows already played (no future data).
- Rule: ground-truth fields are never put into the request. Unit test this.

### 4.3 AnalyzerClient
- Spring `RestClient`, `POST {engine-url}/v1/analyze`, `GET /v1/engines`, `POST /v1/synthetic`, `GET /health`.
- JSON exactly as `06_DATA_CONTRACTS.md` section 3. NaN -> `null`.
- Timeout from config. Log engine, rows, columns, time taken.

### 4.4 FallbackRanker (Java NSigma)
- For each column: `z = |mean(recent window after alarm) - mean(normal)| / (std(normal) + eps)`.
- Service score = max z over its columns. Indicators sorted by z.
- Returns an `AnalyzeResponse` with `engine = "NSIGMA_JAVA_FALLBACK"`, `inheritedFraction = 0`, roles: rank 1 CAUSE, others ALSO_ABNORMAL if score >= 3 else NORMAL.
- Must give the same ranking as Python `NSIGMA` on the shared sample file `analyzer/samples/analyze_request.json` (test).

### 4.5 AnalysisService
`AnalysisRun analyze(caseId, engine, delaySeconds, mode)`:
1. Load case, alarm time = `injectTime + delaySeconds`.
2. Split windows, build request (columns, normal, recent, graph, params).
3. Call engine; on error use fallback and add warning "engine not available, Java fallback used".
4. Render explanation.
5. Compute correctness against ground truth (if the case has it): `rankGtService`, `rankGtIndicator`, `correctTop1`, `correctTop3`, `symptomError` (top-1 wrong and top-1 is an ancestor of the true root cause in the call graph).
6. Save `AnalysisRun` (stores request summary, full response JSON, explanation JSON, correctness, took ms). Return a DTO.

### 4.6 ExplanationRenderer
Input: `AnalyzeResponse` (+ case start time for readable times). Output: `Explanation(headline, confidence, causeSentences, symptomSentences, evidenceSentences, notes)`.

Templates (numbers with 1 decimal):
- Headline: `"Likely root cause: {service} ({metricLabel}). Confidence: {confidence}."`
  - confidence: HIGH if top score >= 2 x second score, MEDIUM if >= 1.3 x, else LOW.
- Cause: `"{service}'s {metricLabel} moved {selfScore} times its normal spread away from normal, starting at {changePointTime}. The services it depends on do not explain this change."`
- Symptom (role SYMPTOM): `"{service} also looks abnormal ({marginalScore}), but about {inheritedPct}% of that is explained by {explainedBy}. It is probably affected, not the cause."`
- Also abnormal (role ALSO_ABNORMAL): `"{service} is also unusual ({marginalScore}) and this is not explained by its dependencies. It may be a second problem."`
- Evidence: `"Alarm at {alarmTime}; the change most likely started at {changePointTime} ({delay} s earlier)."`
- Notes: engine warnings in plain words; fallback note.

Metric labels: cpu -> "CPU usage", mem -> "memory use", latency -> "response time", error -> "error rate", rps -> "request rate", disk -> "disk activity", net -> "network traffic", anything else -> metric name.

Every template has a unit test with a fixed response.

### 4.7 OnlineDetector (pure Java, keep it simple and well commented)
State per replay session. For each new row:
1. Rows before `injectTime - normalGapSeconds` are baseline candidates. While baseline has fewer than `baseline-min-rows`: state `LEARNING`.
2. When baseline is ready: compute per-column median and MAD (`RobustStats`), and the threshold with `ConformalThreshold`: split baseline in two halves; first half -> median/MAD; second half -> row scores; threshold = the `ceil((n+1)(1 - alpha)) / n` empirical quantile of those scores (alpha = target false alarm rate). Then state `WATCHING`.
3. Row score = max over columns of `|x - median| / (1.4826 * MAD + eps)`, NaN skipped.
4. If score > threshold for `alarm-consecutive-rows` rows: state `ALARM`, record alarm time and top 5 columns.
5. After `wait-after-alarm-rows` more rows: run AnalysisService with `mode=REPLAY` (only played rows). State `EXPLAINED`.

Unit tests: hand-computed median/MAD; threshold on known data; alarm fires at the right row on synthetic rows; no alarm on pure normal data with fixed seed.

### 4.8 ReplayService
- Creates `ReplaySession` (id, caseId, speed 1/5/20/50 rows per second, cursor, detector, state, run id when done).
- Uses a `ScheduledExecutorService`; one task per session; stops at end of data or on `DELETE`.
- At most `max-sessions` sessions; old finished sessions removed after 30 minutes.
- `ReplayState` returned to the frontend: cursor, total rows, state, threshold, last N (default 300) rows of the top 6 columns (chosen by the detector, or the ground-truth service's columns when "show ground truth" is on), detector scores, alarm time, run (when explained).

### 4.9 BenchmarkService
- Job = case filter (source, system, fault type, max cases) x engines x delays.
- Runs in a thread pool (`benchmark.workers`), saves each `AnalysisRun` with the job id, updates progress.
- `AccuracyCalculator`: AC@1, AC@3, Avg@5 (service), ExpAC@1/3 (indicator), symptom rate, mean runtime, per engine and per delay. Same definitions as `pare/eval_metrics.py`; test with a small hand-made list of ranks.

### 4.10 SyntheticService
Forwards settings to Python `/v1/synthetic`, writes the returned case to `data/cases/syn-<timestamp>/`, registers it in the catalog.

### 4.11 UploadService
- Accepts multipart: `data.csv`, `meta` JSON (columns, graph edges, injectTime, optional ground truth).
- Validation: `time` column exists and increases; every column in meta exists in CSV; graph services exist in columns; at least 60 rows before injectTime.
- Helper endpoint to guess the column map: split each header at the last `_` into service and metric; user can fix it in the UI.

### 4.12 ReportService
`GET /api/runs/{id}/report?format=md|json`: headline, explanation sentences, ranking table, ground truth, engine, timings. `GET /api/benchmarks/{id}/report?format=md|csv`.

## 5. REST API (for the React frontend)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend status + engine reachable yes/no |
| GET | `/api/engines` | Engine list (from Python, plus `NSIGMA_JAVA`) |
| GET | `/api/cases?source=&system=&faultType=&page=&size=` | Case list |
| GET | `/api/cases/{id}` | Meta + call graph + summary |
| GET | `/api/cases/{id}/series?columns=a,b&from=&to=&maxPoints=1000` | Time series for charts (downsample if needed) |
| POST | `/api/cases/{id}/analyze` | Body `{engine, delaySeconds}` -> AnalysisRun |
| POST | `/api/cases/{id}/compare` | Body `{engines:[...], delaySeconds}` -> list of AnalysisRun |
| GET | `/api/runs?caseId=` | Past runs |
| GET | `/api/runs/{id}` | One run |
| GET | `/api/runs/{id}/report?format=md` | Report |
| POST | `/api/replay` | Body `{caseId, speed}` -> `{sessionId}` |
| GET | `/api/replay/{sessionId}` | ReplayState |
| DELETE | `/api/replay/{sessionId}` | Stop |
| POST | `/api/synthetic` | Factor settings -> CaseSummary |
| POST | `/api/uploads` | Multipart upload -> CaseSummary |
| POST | `/api/uploads/guess-columns` | CSV header -> guessed column map |
| POST | `/api/benchmarks` | Start job |
| GET | `/api/benchmarks/{id}` | Progress + summary |
| GET | `/api/benchmarks/{id}/report?format=csv` | Results |

Errors: `ApiExceptionHandler` returns `{ "error": "short message", "details": "..." }` with proper HTTP codes (400 validation, 404 not found, 502 engine error).

Swagger UI at `/swagger-ui.html`.

## 6. Database entities

`AnalysisRun`: id (uuid), createdAt, caseId, engine, mode (ONE_CLICK, REPLAY, BENCHMARK), delaySeconds, alarmTimeSec, changePointSec, top1Service, top1Indicator, confidence, rankGtService, rankGtIndicator, correctTop1, correctTop3, symptomError, tookMs, benchmarkJobId (nullable), responseJson (clob), explanationJson (clob), warnings (clob).

`BenchmarkJob`: id, createdAt, status (QUEUED, RUNNING, DONE, FAILED), filterJson, engines, delays, total, done, failed, summaryJson.

## 7. Tests

- Unit: RobustStats, ConformalThreshold, OnlineDetector, WindowSplitter (no ground-truth leakage, no future rows in replay), FallbackRanker, ExplanationRenderer, AccuracyCalculator, UploadValidator.
- Integration: `@SpringBootTest` with a mocked engine (WireMock or MockRestServiceServer) using files in `analyzer/samples/`: analyze a small test case end to end; replay a short case at high speed and reach EXPLAINED.
- Test resources: a tiny case folder (`src/test/resources/cases/tiny/`) with 200 rows, 3 services.
