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

- Install the RCAEval package in a separate Python 3.10 virtual env (`experiments/.venv-rcaeval`).
  It is separate because RCAEval needs `numpy<2` while the analyzer uses numpy 2.x; they cannot
  share an environment. Read the RCAEval GitHub README for the exact download function and folder
  structure. Do not guess.

#### Install it without PyTorch

Do **not** use `pip install RCAEval[default]`. That extra pulls `torch`, which hard rule 1 in
`PROJECT_RULES.md` forbids. It is not needed: `RCAEval/e2e/__init__.py` imports each method inside a
`try/except` and skips any whose dependencies are absent, so a torch-free install simply leaves out
the torch methods. Verified on 2026-10-04, with no torch installed:

| method | available without torch |
|---|---|
| NSigma, BARO | yes |
| epsilon-Diagnosis (`e_diagnosis`) | yes |
| CIRCA, RCD, PC-PageRank, MicroCause | yes |
| CausalRCA, MSCRED | **no** - both import `torch` |

Every baseline named in `00_RESEARCH_PLAN.md` section 8.1 is in the first group, so nothing the plan
asks for is lost. CausalRCA and MSCRED are deep models and are **out of scope by rule, not by
accident**; the paper should say so plainly rather than let a reader wonder why they are absent.

The exact environment is pinned in `experiments/requirements-rcaeval.txt` (46 packages, about
420 MB, no torch and no tensorflow):

```
cd experiments
uv venv .venv-rcaeval --python 3.10
uv pip install --python .venv-rcaeval/Scripts/python.exe -r requirements-rcaeval.txt
```

Note that the `default` extra also pins `networkx==2.5`; that pin is not needed either, and the
methods above run on networkx 3.4.2.
- Put data under `data/RCAEval/RE1`, `RE2`, `RE3`. Use `experiments/download_rcaeval.py`, which
  wraps RCAEval's own download helpers so fetching the data is a recorded, repeatable step:

  ```
  experiments/.venv-rcaeval/Scripts/python.exe experiments/download_rcaeval.py --dataset RE1-OB
  ```

  It skips a dataset that is already present, so re-running is cheap. RE1-OB is about 31 MB
  compressed and 175 MB unpacked - far smaller than feared, because RE1 is metrics only. RE2 and RE3
  carry logs and traces and will be very much larger.
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
- Ground-truth indicator: RCAEval's own fine-grained evaluation code **does not contain it**. Checked
  on 2026-10-04 against the installed package: the shipped `Evaluator` compares `Node(entity, metric)`
  objects, but the code that builds the answer node for a case is not in the wheel. So the mapping is
  ours, and it is settled in section 4, "Which indicator counts as correct". The adapter implements it
  in `INDICATOR_METRICS` and records both a strict and a loose answer per case.
- Counters: if some metrics are cumulative counters, convert to rates before scoring. Check by looking at whether values only increase.

## 4. Experiments

### E1 - Explanation grounding (C1, RQ1 and RQ2) - `run_c1_grounding.py`
- Methods: `ECDF`, `PCA_RECON`, `SHAP_IFOREST`, `PARE_NO_RESIDUAL` (marginal robust z), optional `KERNEL_SHAP_PCA`.
- Delays: 0 s only for E1 main table; delays are E3.
- For each case and method record `rank_gt_service`, `rank_gt_indicator`, `symptom_error`.
- Outputs: ExpAC@1, ExpAC@3, ExpAC@5 for indicators; AC@1/AC@3/Avg@5 for services; symptom rate = symptom errors / wrong top-1. Broken down by system and fault type.
- **The symptom rate is always reported next to its chance floor** (`symptom_chance`): the rate a wrong
  answer picked at random among the ranked services would get on the same cases. Callers are common in
  these graphs (`frontend` calls almost everything), so the floor is not zero - about 0.13 to 0.16 on
  RE1 - and only the excess over it says a method is drawn to victims.
- **The service-versus-metric gap is measured on the same cases**: AC@1 restricted to the strict (CPU
  and MEM) cases, minus ExpAC@1. Comparing AC@1 over every case with ExpAC@1 over the strict ones mixes
  two populations, which is how M3.1 first reported it.
- Run one system at a time (`configs/c1_re1_ob.yaml`, `_ss`, `_tt`), then pool them with
  `configs/c1_re1.yaml`, which re-scores nothing and refuses runs whose settings differ.
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

#### Which indicator counts as correct

Two of RE1's five fault types have **no matching metric at all**: there is no `disk` column and no
`loss` column anywhere in the data. Measured over all 125 Online Boutique cases (M2.2), the broken
service's most-moved metric is `cpu` in 25 of 25 CPU cases and `mem` in 18 of 25 MEM cases, but DISK
splits roughly evenly between `cpu` and the two latency percentiles. So "the right indicator" is a
judgement call for DISK, DELAY and LOSS, and a single number cannot hide that.

The rule, which every table must state:

- **The headline ExpAC@k is strict**: it uses only the fault types whose indicator is unambiguous,
  which for RE1 means the CPU and MEM cases (50 of 125 for Online Boutique). The table says how many
  cases it covers.
- **A secondary table reports the loose definition** over all cases, counting a hit when the top
  indicator is any metric in that fault type's acceptable set. It is reported **per fault type, with
  the size of the acceptable set in the table**, and never pooled into one number. Pooling would
  average a 1-of-51 question (CPU) with a 4-of-51 question (DISK) and the result would mean nothing.
- For CPU and MEM the acceptable set holds exactly one metric, so **the loose and strict scores are
  identical on every case the strict number covers**. This is checked, not assumed, in
  `experiments/tests/test_m24_compare.py`. It matters because it means the difference between the two
  headline numbers is purely a difference in **which cases are included**, not in how any case is
  scored - so neither number is the other one with the scoring loosened.

Measured on RE1-OB at delay 0 (M2.4), for our `NSIGMA`: strict ExpAC@1 **0.92** over 50 cases, loose
ExpAC@1 **0.784** over 125. The strict number is higher, and the reason is visible in the per-fault
table rather than being a product of the definition: CPU and MEM are also the easiest fault types at
service level (AC@1 0.96 and 1.00, against 0.48 for LOSS).

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

**The same rule applies to the symptom rate** (added in M3.2). "Symptom errors / wrong top-1" is
computed with both counts as expected values under a shuffle of each case's rank-1 tie group: a
case contributes `symptom_share` (the fraction of its tied top group that calls the culprit) to the
numerator and `1 - its AC@1 contribution` to the denominator. With no tie at rank 1 this is exactly
the plain definition. Without it, a method that ties is judged on whichever tied service sorts first
by name: on RE1-SS `ECDF` listed `carts` first in 104 of 125 cases out of a tie of about ten
services, and its symptom rate read 0.0 for that reason alone.

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
- **`n_abnormal` is held fixed across every setting in the grid.** A MEM fault ramps to its peak at
  the last abnormal row, so its effective size in the analysis window depends on `n_abnormal`
  (`05_PYTHON_ANALYZER_SPEC.md` section 5, "What a memory fault is actually worth"). Varying it would
  change the fault while appearing to change only the run length. None of the factors above needs it
  varied, so this costs nothing.
- **Report the `NO_CLEAR_CAUSE` rate next to AC@k, never folded into it.** `AC@k` scores the ranking,
  which is returned even when the verdict is `NO_CLEAR_CAUSE`, so a case can count as a hit although
  the application would have shown the user no accusation. For MEM this is not a rare corner: it is
  about a quarter of cases at the M1.10 gate's settings.
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
