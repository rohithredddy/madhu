# 08 - Experiments Spec (what produces the paper's results)

All experiments are offline Python scripts in `experiments/`. They use the `pare` library from `analyzer/`. CPU only.

## 1. Layout

```
experiments/
  adapters/
    rcaeval.py            load RCAEval cases
    synthetic.py          load synthetic cases from pare.synthetic (same interface)
    rsanomic.py           (optional) RS-Anomic dataset
  graphs/
    online-boutique.yaml  static call graph (from the app's public architecture)
    sock-shop.yaml
    train-ticket.yaml     (built from RE2 traces by build_graph_from_traces.py)
  configs/                YAML configs, one per run
  run_c1_grounding.py     RQ1, RQ2
  run_rca.py              RQ3, RQ4 (PARE variants + baselines, delay sweep)
  run_stability.py        stability part of C3 (writes stability.csv)
  run_faithfulness.py     faithfulness part of C3 (writes faithfulness.csv)
  run_synthetic_study.py  E6 controlled synthetic study
  export_cases.py    converts RCAEval cases into the case format read by the Java backend
  build_graph_from_traces.py
  stats.py                Wilcoxon, Cliff's delta, bootstrap CI
  make_tables.py          -> paper/tables/*.md and *.tex
  make_figures.py         -> paper/figures/*.pdf and *.png
  results/                (git-ignored except small summary CSVs)
```

## 2. Getting the data

- Install the RCAEval package in a separate Python 3.10 virtual env if its dependencies clash with ours (`experiments/.venv-rcaeval`). Read the RCAEval GitHub README for the exact download function and folder structure. Do not guess.
- Put data under `data/RCAEval/RE1`, `RE2`, `RE3`.
- Start with RE1 Online Boutique only. Add the other systems after the pipeline works end to end.

## 3. The RCAEval adapter (`adapters/rcaeval.py`)

Must provide:
```
list_cases(root, dataset, system) -> list[Case]
load_case(case, delay_s, normal_minutes=None) -> CaseData
```
- `Case`: id, dataset, system, fault_type, gt_service, gt_indicator, path, inject_time.
- `CaseData`: normal df, recent df, alarm_time (= inject_time + delay_s), columns (list of ColumnInfo), graph.
- First open a few case folders and print their structure, column names and inject time file. Write down what you find in `PROGRESS.md` before coding the parser.
- Column to (service, metric) mapping: build it explicitly from the real column names. Keep a mapping file `adapters/rcaeval_columns.yaml` if names are irregular.
- Ground-truth indicator: take it from RCAEval's own fine-grained evaluation code if it exists. Otherwise use this mapping and document it as an assumption: CPU -> cpu metric, MEM -> memory metric, DISK -> disk metric, DELAY -> latency metric, LOSS -> latency/loss metric, code-level faults -> the indicator given in the dataset (log/trace). Write the final mapping in `PROGRESS.md`.
- Counters: if some metrics are cumulative counters, convert to rates before scoring. Check by looking at whether values only increase.

## 4. Experiments

### E1 - Explanation grounding (C1, RQ1 and RQ2) - `run_c1_grounding.py`
- Methods: `ECDF`, `PCA_RECON`, `SHAP_IFOREST`, `PARE_NO_RESIDUAL` (marginal robust z), optional `KERNEL_SHAP_PCA`.
- Delays: 0 s only for E1 main table; delays are E3.
- For each case and method record `rank_gt_service`, `rank_gt_indicator`, `symptom_error`.
- Outputs: ExpAC@1, ExpAC@3, ExpAC@5 for indicators; AC@1/AC@3/Avg@5 for services; symptom rate = symptom errors / wrong top-1. Broken down by system and fault type.
- This experiment alone is a paper section. Do it first.

### E2 - RCA accuracy (RQ3) - `run_rca.py`
- Methods: `PARE`, `PARE_NO_RESIDUAL`, `PARE_NO_CP`, `PARE_LGBM`, `NSIGMA`, `SHAP_IFOREST`, plus RCAEval baselines that run on CPU in reasonable time: NSigma (theirs, as a cross-check of ours), BARO, epsilon-Diagnosis, CIRCA, RCD, PC-PageRank. Plus DoWhy `gcm` anomaly attribution on the call graph if it runs in under about 60 s per case.
- Call RCAEval baselines through their own functions with the same alarm time we use. Record any method that crashes or times out (limit 300 s per case) instead of hiding it.
- Metrics: AC@1, AC@3, Avg@5 (service and indicator level), runtime per case.

### E3 - Detection delay sweep (RQ4)
- Same as E2 with `delay_s` in {0, 30, 60, 120}. The methods only know the alarm time `inject_time + delay`, not the true injection time.
- Normal period for every method = data before `inject_time` minus a 30 s safety gap.

#### Stated assumption: the normal window uses the injection time

This is the standard RCAEval protocol and we keep it, but it must be stated openly in the paper,
because a real system would not know when the fault was injected:

- Every method gets exactly the same windows, so no method is favoured by it.
- It is optimistic. So E3 also runs a **second variant** in which the normal period ends at
  `alarm_time - cp_lookback_s` (no use of `inject_time` anywhere), and both sets of numbers are
  reported side by side. The gap between them is itself a result worth showing.
- It is a time boundary only. The root-cause service and indicator are never given to any method
  (hard rule 4 in `PROJECT_RULES.md`).
- The application's replay detector is stricter: it never uses `inject_time` at all
  (`03_JAVA_BACKEND_SPEC.md` section 4.7). Offline scoring follows the benchmark protocol; the live
  demo does not need to.
- Main figure: Avg@5 vs delay, one line per method. Expect simple methods to fall; PARE with change point should fall less.

### E4 - Call-graph ablation
- PARE with graph from (a) traces, (b) static architecture file, (c) correlation-inferred, (d) no graph. RE2 (has traces) is the right dataset.

#### How ties are scored

Several methods saturate. `ECDF`'s tail score cannot exceed `log(n+1)`, so with 400 normal rows
**every** column that moves beyond the normal range scores exactly 6.0 and a dozen columns can share
first place. Deciding those by the alphabetical order of column names would make the reported
accuracy an accident of naming.

So a tie is scored as what it is: **the expected hit rate if the tied group were shuffled**. If the
ground truth sits in a tie group of size `m` whose best rank is `r`, its contribution to AC@k is

```
clip(k - r + 1, 0, m) / m
```

With no ties this is exactly the textbook definition, so nothing changes for a method whose scores
are all distinct. It is neither optimistic nor pessimistic, and it must be stated in the paper
because it changes the numbers for any saturating method.

Measured on 15 synthetic cases, it changes nothing for `PARE`, `NSIGMA`, `SHAP_IFOREST` or
`PCA_RECON` (no ties at the top), and moves `ECDF`'s indicator accuracy from 0.13 to 0.46 - the
earlier figure was an artefact of column naming, not a property of the method.

### E5 - Explanation quality (C3) - `run_faithfulness.py`, `run_stability.py`
- Faithfulness (deletion test): system anomaly score = mean over the analysis window of the max robust z over columns. For k = 0..10, replace the top-k columns of a method's indicator ranking by their normal medians and recompute the score. Report the normalized area under this curve (lower = more faithful) and compare with a random ranking (average of 10 random orders).
  - Output goes to its own `faithfulness.csv` in the run folder, not into `cases.csv`: the shape is
    different (one row per case, method and k). Same for `stability.csv`. Columns are in
    `06_DATA_CONTRACTS.md` section 5.
- Stability: for each case run each method under 5 seeds x 3 normal-window subsamples (random contiguous 90%) x 3 window shifts (-10 s, 0, +10 s). Report mean Jaccard of the top-5 indicators and mean Kendall tau of the service ranking.
- Compactness: number of indicators needed to reach 80% of the total positive score mass.

### E6 - Controlled synthetic study (when does PARE help?) - `run_synthetic_study.py`
- Uses `pare.synthetic`, so the true cause and the true propagation are known exactly.
- Vary one factor at a time, 50 seeds per setting, 4 fault types:
  - graph size: 5, 10, 20, 40 services
  - propagation strength (weight from callee to caller): 0.2, 0.5, 0.8, 1.0
  - amplification (how non-linearly a caller degrades once a callee is slow): 0, 0.25, 0.5, 1.0, 2.0
  - noise level: LOW, MEDIUM, HIGH (the float multipliers 0.5 / 1.0 / 2.0)
  - graph quality: true graph, 20% edges removed, 20% wrong edges added, no graph
  - detection delay: 0, 10, 30, 60 rows
- Methods: PARE, PARE_NO_RESIDUAL, PARE_NO_CP, NSIGMA, SHAP_IFOREST, ECDF.
- Expected story, corrected after building the generator: **propagation strength alone does not
  create the symptom trap** - under linear propagation a caller can never outscore the culprit, for
  the reason derived in `05_PYTHON_ANALYZER_SPEC.md` section 5. The factor that creates it is
  `amplification`. So the story to test is: as amplification rises, marginal methods and SHAP start
  blaming callers; PARE keeps finding the culprit over a band of amplification; and beyond that band
  nothing metric-only works, which is a limit worth reporting rather than hiding. PARE should also
  degrade gracefully when the graph is wrong.
- Because of that, the headline figure for this experiment is **AC@1 and symptom rate against
  amplification**, with propagation strength as a secondary factor rather than the main one.
- Figures: AC@1 vs amplification; symptom rate vs amplification; AC@1 vs propagation strength;
  AC@1 vs graph quality.
- This study is cheap (minutes on a laptop) and gives clear, explainable figures for the paper.

### E7 (optional) - RS-Anomic comparison with GAL-MAD's SHAP localization
- Only if time allows. Compare PARE localization with the GAL-MAD paper's reported localization table, on the same anomaly types.

## 5. Statistics (`stats.py`)
- Paired comparison PARE vs each other method on the same cases: Wilcoxon signed-rank on per-case reciprocal rank (1/rank), Cliff's delta as effect size.
- 95% bootstrap confidence intervals (1000 resamples, seed 42) for AC@k and ExpAC@k.
- Holm correction when comparing against several baselines.

## 6. Tables and figures (generated, never typed by hand)

Tables:
1. Datasets used (cases per system and fault type).
2. E1 grounding: ExpAC@1/3/5 and symptom rate per method.
3. E2 RCA accuracy: AC@1, AC@3, Avg@5 per method and system, with runtime.
4. E4 graph ablation.
5. E5 faithfulness, stability, compactness.
6. E6 synthetic study (factor tables).

Figures:
1. Motivating example: one case, bar chart of marginal vs self score per service (cause vs symptoms).
2. Avg@5 vs detection delay (E3).
3. Symptom rate by fault type (E1).
4. Deletion curves (E5).
5. Architecture of the system (draw once by hand or with a diagram tool; not generated).

## 7. Running time budget

- Use `joblib.Parallel(n_jobs=-2)` across cases.
- Target: full RE1 for all PARE variants and our baselines in under 2 hours on a 4-core laptop. RCAEval causal baselines may be slower; run them overnight and cache results.
- Cache loaded cases as parquet in `data/cache/` to avoid re-reading big CSVs.

## 8. Honesty checklist (before writing any result in the paper)

- [ ] The number comes from a file in `experiments/results/`.
- [ ] The config and environment for that run are saved next to it.
- [ ] Failed or skipped cases and methods are reported, not dropped silently.
- [ ] If PARE is worse somewhere, that is in the table too.

## 9. Case export (`export_cases.py`)

Converts selected RCAEval cases into the uniform case format described in `06_DATA_CONTRACTS.md` section 2, written to `data/cases/`. Default selection: all RE1 Online Boutique and Sock Shop cases plus 20 RE2 cases. This is the only bridge between the research data and the Java backend; the Java side never parses RCAEval folders directly.
