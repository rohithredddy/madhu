# 02 - Architecture

## 1. The big picture

Three local programs. No Docker, no Kafka, no monitoring stack.

```
 +------------------------------+
 |  React frontend (Vite)  :5173 |   user interface
 +------------------------------+
              |  REST/JSON  (/api/...)
              v
 +------------------------------------------------+
 |  Spring Boot backend (Java 21)  :8080           |
 |                                                |
 |  CaseCatalog      - list/load cases             |
 |  UploadService    - user CSV + call graph       |
 |  ReplayService    - plays a case row by row     |
 |  OnlineDetector   - robust z + conformal (Java) |
 |  AnalysisService  - calls Python, saves runs    |
 |  FallbackRanker   - Java NSigma if Python down  |
 |  ExplanationRenderer - plain sentences (Java)   |
 |  BenchmarkService - batch runs, accuracy stats  |
 |  ReportService    - Markdown/JSON report export |
 |  H2 file database - runs, jobs, uploads         |
 +------------------------------------------------+
              |  REST/JSON
              v
 +------------------------------------------------+
 |  Python engine (FastAPI)  :8000                 |
 |  /v1/analyze  - PARE and baseline engines       |
 |  /v1/synthetic - generate a synthetic case      |
 +------------------------------------------------+

 Offline (research, no servers needed):
   experiments/ (Python) -> results, tables, figures for the paper
   experiments/export_cases.py -> data/cases/ (read by Java)
```

## 2. Who does what

| Part | Language | Job |
|---|---|---|
| frontend | React + TypeScript | Pages, charts, call-graph view, buttons. Talks only to the Java backend |
| backend | Java (Spring Boot) | All application logic: cases, replay, live detection, explanations, storage, benchmark, reports, API docs |
| engine | Python (FastAPI) | Pure computation: run PARE or a baseline on a window of data; make synthetic cases |
| experiments | Python | Offline research runs for the paper |

Rule: the frontend never calls Python. Python never stores anything. Java is the hub.

## 3. Main flows

### 3.1 Analyze a case (one click)
1. Frontend `POST /api/cases/{caseId}/analyze` with `{engine, delaySeconds}`.
2. Java loads the case, splits normal/recent data around `injectTime + delaySeconds`, builds an `AnalyzeRequest`, calls Python `/v1/analyze`.
3. If Python fails or times out (10 s), Java uses `FallbackRanker` and marks the run `engine=NSIGMA_JAVA_FALLBACK`.
4. Java renders the explanation text, compares with ground truth, saves an `AnalysisRun`, returns it.

### 3.2 Replay (looks live)
1. Frontend `POST /api/replay` with `{caseId, speed}` -> returns `sessionId`.
2. Java `ReplayService` advances one row per tick (tick = 1000 ms / speed). Each new row goes to the Java `OnlineDetector`.
3. The detector learns a baseline from the first `replay.baseline-rows` rows of the case (default 300). It is never told the injection time, so the alarm is produced the way a real detector would produce it. It raises an alarm when the score stays above the threshold for 3 rows.
4. After the alarm plus a short wait (default 20 rows), Java runs flow 3.1 using the data seen so far (no peeking at the future).
5. Frontend polls `GET /api/replay/{sessionId}` every second to draw the chart, the detector score, the alarm marker, and finally the explanation.

### 3.3 Synthetic lab
1. Frontend `POST /api/synthetic` with factor settings.
2. Java forwards to Python `/v1/synthetic`, saves the case into the catalog as source `SYNTHETIC`, returns its `caseId`.
3. Frontend then uses flow 3.1 (often several engines side by side).

### 3.4 Benchmark
1. Frontend `POST /api/benchmarks` with a case filter, engines and delays.
2. Java runs a background job (one thread pool, 2 workers) calling flow 3.1 for each combination; progress stored in DB.
3. Frontend polls the job and shows AC@1, AC@3, Avg@5, ExpAC@3 and symptom rate per engine.
Note: paper numbers come from the Python experiment scripts. The Java benchmark page is the interactive view of the same thing; a consistency task (M9.5) checks they agree.

### 3.5 Upload own data
Frontend uploads `data.csv`, a column map (auto-guessed, user can edit), a call graph (text lines like `frontend -> cartservice`), injection time and optional ground truth. Java validates and saves it as a case with source `UPLOAD`.

## 4. How to run (development)

Three terminals:
```
# 1 - Python engine
cd analyzer && uvicorn service.app:app --port 8000
# 2 - Java backend
cd backend && mvn spring-boot:run
# 3 - React frontend
cd frontend && npm run dev
```
Open http://localhost:5173. Vite proxies `/api` to `http://localhost:8080`, so no CORS setup is needed in development. A script `scripts/start-all.sh` (and `.bat` for Windows) starts all three.

For the final packaged version, the backend can also serve the built frontend: `npm run build` copies `frontend/dist` into `backend/src/main/resources/static`, then only Java and Python need to run.

## 5. Data folders

```
data/cases/<caseId>/data.csv
data/cases/<caseId>/meta.json
data/uploads/<caseId>/...           (same format)
data/db/                            (H2 database files)
data/RCAEval/RE1, RE2, RE3          (benchmark data, research side only)
data/cache/                         (parquet cache for the experiments)
```
The backend finds this folder through the `XAIRCA_DATA_DIR` environment variable; the default is
`../data` relative to the backend working directory, resolved to an absolute path and logged at
startup (`03_JAVA_BACKEND_SPEC.md` section 1).
Format in `06_DATA_CONTRACTS.md` section 2.
