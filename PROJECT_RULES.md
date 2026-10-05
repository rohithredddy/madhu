# PROJECT_RULES.md - Read this first

This file says what this project is and how to work on it.
At the start of every session read this file, then `PROGRESS.md`, then the task in `docs/07_TASKS.md` you are asked to do and the spec files it points to.

---

## 1. What this project is

A complete MTech final project: a research method, experiments for a research paper, and a full application. The React frontend is the user interface used to present the whole project.

The code will be read and explained by other people after it is built, so clear, readable, well-commented code is part of the deliverable.

Topic: Explainable AI for anomaly detection and root-cause analysis (RCA) in microservice systems.

The idea in one sentence: ordinary anomaly explanations (like SHAP) often point at services that are only affected (symptoms), so we build a CPU-only method called **PARE** (Propagation-Aware Residual Explanations) that uses the service call graph to separate "this service caused it" from "this service only felt the effect", and we measure explanation quality against real ground truth.

Background and novelty: `docs/00_RESEARCH_PLAN.md`.

Three parts:
1. **Python** (`analyzer/`, `experiments/`): the PARE engine (library + small FastAPI service) and the offline experiments that produce the paper's numbers.
2. **Java Spring Boot backend** (`backend/`): the application logic. Java is a requirement for the backend. It owns cases, replay, the live Java detector, calls to Python over REST, the Java fallback ranker, explanation text, storage (H2), benchmarks and reports.
3. **React frontend** (`frontend/`): the user interface used to present the project. Talks only to the Java backend.

Not used (do not add): Kafka, Docker, Kubernetes, Prometheus, Grafana, Jaeger, OpenTelemetry, any cloud service, any message broker.

---

## 2. Hard rules

1. **No GPU.** Laptop CPU, 8 to 16 GB RAM. No PyTorch/TensorFlow. Use scikit-learn, shap, lightgbm, ruptures, numpy, pandas, scipy, networkx.
2. **Never invent results.** Every number in a table, figure, README, UI text or paper note must come from code that actually ran, with output saved under `experiments/results/`. If something did not run, say so plainly.
3. **Java is the hub.** React -> Java -> Python. React never calls Python. Python stores nothing.
4. **No ground-truth leakage.** Ground truth is only used for scoring. It must never be sent to an engine or used to pick input windows. There are tests for this; keep them.
5. **No peeking at the future in replay.** Replay analysis only uses rows already played.
6. **Follow the specs** in `docs/`. If a spec is unclear or wrong, write it under "Open questions" in `PROGRESS.md` and pick the simplest reasonable option. Do not silently change formats in `docs/06_DATA_CONTRACTS.md`; if a change is needed, update the doc and all sides in the same commit.
7. **Small steps.** One task from `docs/07_TASKS.md` at a time. Then build, test, update `PROGRESS.md`, and stop for review.
8. **Plain language** in comments, docs, logs, UI text.
9. **Do not guess library APIs** (RCAEval, shap, ruptures, @xyflow/react, springdoc). Read the installed source or official README first.
10. **Reproducible.** Seeds fixed (default 42). Every experiment takes `--config` YAML and saves the config with its results.
11. **Do not commit data** (`data/` is git-ignored).
12. **Never change a test just to make it pass.** If a test fails, explain whether the test or the code is wrong first.
13. **Readable code.** Prefer simple, readable code over clever code. Every important class/function gets a short comment saying what it does and why. After each milestone, add a short paragraph to PROGRESS.md saying what was built and why.

---

## 3. Folder layout

```
xai-rca/
  PROJECT_RULES.md  PROGRESS.md  README.md
  docs/              specs (read before coding)
  analyzer/          Python: package "pare" + service/ (FastAPI) + tests/ + samples/
  experiments/       Python: adapters, configs, run_*.py, make_tables.py, make_figures.py
  backend/           Java: Spring Boot (Maven)
  frontend/          React + Vite + TypeScript
  scripts/           start-all.sh / .bat, helper scripts
  data/              cases/, uploads/, db/, RCAEval/, cache/  (git-ignored)
  paper/             tables/, figures/, notes/
```

## 4. Tech stack

- Python 3.10 (RCAEval needs 3.10), FastAPI, uvicorn, pydantic, numpy, pandas, scikit-learn, shap, lightgbm, ruptures, networkx, scipy, statsmodels, matplotlib, pyyaml, joblib, pytest.
- Java 21, Spring Boot 3.x (latest stable), Maven, spring-boot-starter-web, validation, data-jpa, H2 (file mode), springdoc-openapi, JUnit 5, Mockito, WireMock or MockRestServiceServer.
- React 18, Vite, TypeScript, react-router-dom, recharts, @xyflow/react, Vitest (optional).

## 5. Ports

| Part | Port |
|---|---|
| React dev server | 5173 |
| Java backend | 8080 |
| Python engine | 8000 |

## 6. Commands

```
# Python
cd analyzer && pip install -e ".[dev]" && pytest -q      # the pare library
pytest experiments/tests -q                             # the experiment adapters, from the repo root
cd analyzer && uvicorn service.app:app --port 8000
cd experiments && python run_c1_grounding.py --config configs/c1_re1_ob.yaml

# Java  (mvnw = the Maven Wrapper that ships inside backend/; no system Maven needed)
cd backend && ./mvnw -q clean verify
cd backend && ./mvnw spring-boot:run

# React
cd frontend && npm install && npm run dev
cd frontend && npm run build

# All three
scripts/start-all.sh
```

## 7. Spec files

| File | Covers |
|---|---|
| `docs/00_RESEARCH_PLAN.md` | Research background, novelty, research questions |
| `docs/01_PROJECT_OVERVIEW.md` | Plain overview and glossary |
| `docs/02_ARCHITECTURE.md` | Parts, flows, how to run |
| `docs/03_JAVA_BACKEND_SPEC.md` | Spring Boot backend: packages, components, REST API, entities, tests |
| `docs/04_REACT_FRONTEND_SPEC.md` | Pages, components, charts, colours |
| `docs/05_PYTHON_ANALYZER_SPEC.md` | PARE algorithm, engines, synthetic data, FastAPI |
| `docs/06_DATA_CONTRACTS.md` | Case format, JSON between React/Java/Python, result CSVs |
| `docs/07_TASKS.md` | Ordered tasks with "done when" checks |
| `docs/08_EXPERIMENTS_SPEC.md` | Experiments that produce the paper's results |

## 8. Coding style

Java: package root `com.xairca.backend`; constructor injection; records for DTOs; no Lombok; SLF4J logging; one responsibility per class; clear comments on the detector and explanation logic.

Python: package `pare`; type hints; small pure functions; pytest; no notebooks as source of truth.

React: function components + hooks; typed API client; components small; no inline magic numbers for colours (use CSS variables from `04_REACT_FRONTEND_SPEC.md`).

Git: one commit per finished task, message like `M8.5: explanation renderer with template tests`.

## 9. Definition of done

- Builds with no errors (`pytest`, `./mvnw clean verify`, `npm run build` as relevant).
- New code has tests that pass.
- The task's "done when" check is met.
- `PROGRESS.md` updated (what, how tested, files, open points).
- Stop and tell the human what to review.
