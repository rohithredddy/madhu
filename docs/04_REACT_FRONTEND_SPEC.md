# 04 - React Frontend Spec (user interface)

A clean explainable-AI web app. Its job is to make one idea obvious: ordinary explanations often point at the victims; PARE points at the cause and says why.

## 1. Setup

- Folder: `frontend/`. Vite + React 18 + TypeScript.
- Libraries: `react-router-dom` (pages), `recharts` (line and bar charts), `@xyflow/react` (call-graph view; check the current package name and API in its docs), nothing else unless needed.
- Styling: plain CSS with CSS variables (light theme, one accent colour). No heavy UI framework.
- API calls: a small `src/api/client.ts` using `fetch`, with typed functions for every backend endpoint in `03_JAVA_BACKEND_SPEC.md` section 5. Types in `src/api/types.ts` match `06_DATA_CONTRACTS.md`.
- Dev proxy in `vite.config.ts`: `/api` -> `http://localhost:8080`.
- Build output can be copied to the backend's `static/` folder for single-server mode (one Java process serves the UI) (`npm run build:backend`).

## 2. Colours with meaning (use them everywhere)

| Meaning | Colour |
|---|---|
| CAUSE | red `#d64545` |
| SYMPTOM | orange `#e69a28` |
| ALSO_ABNORMAL | purple `#8a5cd1` |
| NORMAL | grey `#9aa3ad` |
| NO_CLEAR_CAUSE verdict | grey `#9aa3ad` (no red anywhere) |
| Ground truth marker | green outline `#2f9e44` |

## 3. Pages

### 3.1 Home `/`
- One-paragraph plain explanation of the problem and the idea.
- A small static picture: call graph where the cause is red and two callers are orange.
- Status chips: backend OK, Python engine OK (from `/api/health`).
- Buttons: "Try a real failure" (to Cases), "Watch a replay" (to Replay), "Synthetic lab", "Benchmark".

### 3.2 Cases `/cases`
- Table: case id, source, system, fault type, ground-truth service, rows. Filters (source, system, fault type) and search.
- Click a row -> Case detail.

### 3.3 Case detail `/cases/:id`
Layout top to bottom:
1. Header: case id, system, fault type, ground truth (can be hidden with a "hide answer" toggle, useful when presenting).
2. Controls: engine dropdown (default PARE), detection delay slider (0 to 120 s), "Analyze" button, "Compare engines" button (PARE vs SHAP_IFOREST vs NSIGMA).
3. **Explanation card**: headline, confidence badge, cause sentences, symptom sentences, evidence sentences, notes. Correct/incorrect badge versus ground truth.
   - When the response `verdict` is `NO_CLEAR_CAUSE`, the card shows the backend's "No clear root
     cause found" headline, no cause sentences, and a neutral grey badge instead of the red CAUSE
     styling. No node is coloured red in the call graph in that case. This must not look like a
     confident accusation.
4. **Call graph**: nodes coloured by role; ground truth node with green outline; edge direction caller -> callee; hover shows scores.
5. **Cause vs symptom chart** (the key chart): grouped bar per service, "marginal score" (how strange it looks) next to "self score" (how much is its own problem). Sorted by self score.
6. **Indicator table**: the returned indicators (up to `topK`, default 10) with self score, marginal score, inherited %.
7. **Time series**: the top 3 indicators plus the ground-truth indicator, with vertical lines for injection time (if shown), alarm time and estimated change point.
8. "Download report" (Markdown).

Compare mode: the explanation card, graph and bar chart appear side by side for each engine (2 or 3 columns, stacked on small screens).

### 3.4 Replay `/replay`
- Pick a case (dropdown with search) and speed (1x, 5x, 20x, 50x). Play / Stop.
- Live area (polls `/api/replay/{id}` every 1 s):
  - State badge: LEARNING -> WATCHING -> ALARM -> EXPLAINED.
  - Line chart of the detector score with the threshold line; alarm marker.
  - Small multiples (2 x 3) of the 6 most active metrics.
  - Progress bar of the case.
- When EXPLAINED: the explanation card and the cause vs symptom chart slide in, with a link "open full analysis".

### 3.5 Synthetic lab `/lab`
- Sliders and selects: number of services (5 to 40), fault type (`LATENCY`, `CPU`, `MEM`, `ERROR`), propagation strength (0.2 to 1.0), **amplification (0 to 2, default 0.5)**, noise (`LOW` / `MEDIUM` / `HIGH`), root service (random or chosen), seed.
- The API values are the UPPERCASE strings listed above, sent exactly as in `06_DATA_CONTRACTS.md`
  section 3. The UI may show them in a friendlier case, but it must not invent other values.
- "Generate and analyze": creates the case, then runs compare with PARE, PARE_NO_RESIDUAL and SHAP_IFOREST.
- Shows the three call graphs side by side with correct/incorrect badges.
- Text hint: "Try increasing **amplification** and watch the ordinary methods start blaming the
  callers." Amplification, not propagation strength, is the control that produces that effect:
  with purely linear propagation a caller can never look worse than the service that broke, however
  high the propagation. The reason is in `05_PYTHON_ANALYZER_SPEC.md` section 5.
- Worth knowing when demonstrating: around 0.5 the ordinary methods are fooled and PARE is not,
  which is the point of the page. Above about 0.7 neither works, so do not present that as a PARE
  failure - it is a limit of metric-only analysis and the page should say so.

### 3.6 Benchmark `/benchmark`
- Form: source/system/fault filters, engines (checkboxes), delays (checkboxes), max cases.
- Start -> progress bar.
- Results: table per engine (AC@1, AC@3, Avg@5, ExpAC@3, symptom rate, mean ms), bar chart of AC@1 per engine, line chart of Avg@5 vs delay.
- Download CSV.
- Small note: "Paper results are produced by the research scripts; this page reproduces them interactively."

### 3.7 Upload `/upload`
- Step 1: choose CSV. Step 2: review guessed column map (editable table: column, service, metric). Step 3: call graph as text lines `a -> b` with live preview of the graph. Step 4: injection time and optional ground truth. Submit -> go to case detail.

### 3.8 How it works `/method`
Plain-language explanation of PARE in 5 short steps with one diagram each (static SVG). Also explains the Java online detector and the conformal threshold.

## 4. Components

`ExplanationCard`, `RoleBadge`, `CallGraphView`, `CauseSymptomChart`, `IndicatorTable`, `SeriesChart`, `EngineSelect`, `DelaySlider`, `StatusChips`, `ProgressBar`, `CompareGrid`.

## 5. Quality

- Loading and error states on every API call (show the backend's `error` message).
- Works at 1366 x 768 (typical projector) and on a laptop screen.
- No console errors. `npm run build` passes with no TypeScript errors.
- A few tests with Vitest + React Testing Library for `ExplanationCard` and `CauseSymptomChart` data mapping (optional but nice).
