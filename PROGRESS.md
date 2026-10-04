# PROGRESS.md - Running log

Update this file at the end of every task. Newest entry at the top of "Log".
Human: read this before every session to know where things stand.

Order of this file: what is happening now, then the log of what was done (newest first), then
anything waiting on you, then the machine setup and the full list of decisions as reference.

## Current status
- Current milestone: M1 (Python PARE core)
- Next task: M1.11 (save `analyzer/samples/` request and responses for the Java tests), which
  finishes M1
- Blockers: none. Open question 3, which would have made the M1.10 synthetic check meaningless, was
  settled on 2026-10-03 (decision 38).

## Log
<!-- Template for each entry:
### YYYY-MM-DD - Task Mx.y - short title
- What was done:
- How it was tested (commands + result):
- Files changed:
- Left open / next:
-->

### 2026-10-03 - M1.2a - settling open question 3: the synthetic model could not produce the trap
- What was done: added a non-linear congestion term and an `amplification` parameter to
  `pare.synthetic`, resolving the finding raised during M1.2. Full reasoning, the measurements and
  the three regimes are in decision 38. The headline: with linear propagation a caller can never
  outscore the culprit, so our own generator could not produce the mistake the project exists to
  study; congestion fixes that with a mechanism that has a physical justification rather than being
  tuned to flatter the method.
- How it was tested (commands + result):
  - `pytest -q` -> **185 passed** (8 new) in 2.0 s. `ruff check .` -> clean.
  - The most important check is that nothing moved: all 56 pre-existing synthetic tests pass
    untouched, and a case built with `amplification=0.0` is byte-identical to one built without the
    argument. No new random draws were introduced, which is what makes that possible.
  - The two opposing properties are both asserted, because together they are the whole point:
    without amplification a caller **never** outscores the culprit across 20 seeds, and with
    amplification at 1.0 a caller outscores it in at least half of them.
  - Congestion is tested to be dormant in normal operation: the caller's normal spread changes by
    less than 10 percent between `amplification=0` and `amplification=2`. If that ever failed, the
    mechanism would be cancelling itself out and the trap would vanish again.
  - Behaviour across the amplification sweep was measured with a least-squares residual proxy, since
    `residual.py` is M1.6. Numbers in decision 38.
- Files changed: `analyzer/pare/synthetic.py`, `analyzer/tests/test_synthetic.py`;
  `docs/05_PYTHON_ANALYZER_SPEC.md` (the congestion section, the derivation, the measured regimes),
  `docs/08_EXPERIMENTS_SPEC.md` (E6 gains amplification as a factor and its expected story is
  corrected), `docs/06_DATA_CONTRACTS.md` (`amplification` on the synthetic request),
  `docs/04_REACT_FRONTEND_SPEC.md` (the lab's slider and its now-corrected hint), `PROGRESS.md`.
- Left open / next: M1.6, `residual.py`. Worth carrying into it: the amplification sweep says a
  linear dependency model stops working above about 0.7, because the non-linearity is invisible in
  the normal data it is fitted on. That is a limitation to measure and report in E6, not a bug to
  tune away.

### 2026-10-04 - M1.10 - the M1 gate: failed, then two bugs found, then passed
- What was done: `analyzer/scripts/synthetic_check.py`, the gate M1 is allowed to finish on. 50
  seeds x 4 fault types x 2 amplifications x engines, run in parallel, writing `summary.csv`,
  `cases.csv` and `config.json` (settings, versions, platform, elapsed) under
  `experiments/results/synthetic_check/`. Ten tests cover the gate logic itself, most importantly
  that it **can fail** - a check that cannot fail is not a check.
  - It sweeps amplification, which the task line does not ask for. Without that the gate is empty:
    at amplification 0 there is no symptom trap, every engine finds the culprit, and PARE ties its
    own ablation at 1.00 while appearing to pass. The 0 run is kept as the control.
- **The first full run FAILED**, and that is worth recording rather than smoothing over:

      amp 0.0   cpu   PARE 0.76 vs 1.00  gap -0.24  FAILED
      amp 0.0   mem   PARE 0.78 vs 0.90  gap -0.12  FAILED
      amp 0.25  cpu   PARE 0.76 vs 1.00  gap -0.24  FAILED
      amp 0.25  mem   PARE 0.78 vs 0.90  gap -0.12  FAILED

  The task says stop and report, do not tune, so nothing was tuned. Investigating found **two bugs,
  both mine, neither in the method**.

  **Bug 1, in the measurement.** A diagnostic found 0 of 50 cpu cases where `PARE_NO_RESIDUAL`'s
  answer was right and `PARE`'s was wrong - by the engines' own answers PARE was never worse, so the
  0.76 had to be an artefact. It was: the script computed the rank by re-sorting the engine's scores,
  but `PARE` returns `[('svc-07', 4.00), ('frontend', 5.07), ...]` - the true culprit first with a
  **lower** score than the caller behind it. That is the graph traversal in `05` step 4 working
  exactly as specified, walking down past a loud symptom to the source, and "put the final node at
  rank 1". Re-deriving the rank from scores marked the engine wrong precisely when the traversal
  worked. Fixed by adding `rank_in_order()`, which ranks by the order the engine actually returned
  and counts a tie only across an unbroken run of equal scores. **No threshold, engine or config
  default was changed.**

  **Bug 2, in the engines, and more serious.** Every baseline was being given the call graph. The
  traversal step runs inside `rank_all`, which `analyze()` called with the request's graph for all
  engines, so `NSIGMA`, `SHAP_IFOREST`, `ECDF` and `PCA_RECON` were quietly handed the one piece of
  information the proposed method is supposed to contribute. The existing test gave false assurance
  because it only checked that the explainer **functions** take no graph argument, not how the engine
  wired them up. Fixed with `EngineSpec.use_graph`, and the new test is behavioural: a baseline must
  return an identical ranking with and without a graph. On this data it barely moved the numbers, but
  it would matter on RE1 where the graphs are real, and it was wrong regardless.
- **The gate then passed**, on 50 seeds:

  | amplification | fault | PARE | PARE_NO_RESIDUAL | gap |
  |---|---|---|---|---|
  | 0.00 | cpu | 1.00 | 1.00 | +0.00 |
  | 0.00 | error | 1.00 | 0.98 | +0.02 |
  | 0.00 | latency | 1.00 | 1.00 | +0.00 |
  | 0.00 | mem | 0.90 | 0.90 | +0.00 |
  | 0.25 | cpu | 1.00 | 1.00 | +0.00 |
  | 0.25 | error | 1.00 | 0.98 | +0.02 |
  | 0.25 | **latency** | **0.94** | **0.82** | **+0.12** |
  | 0.25 | mem | 0.90 | 0.90 | +0.00 |

  Condition 2 holds too: PARE on latency is 1.00 and 0.94, both above the 0.85 required.

  **Read honestly, this is a narrower claim than "PARE beats its ablation".** The residual step earns
  its keep in exactly one place - latency faults under congestion, +0.12 - and ties everywhere else.
  That is the claim the paper should make, and it is the one worth making: it says *when* the method
  helps rather than asserting it always does. PARE's latency accuracy over 50 seeds is 0.94, not the
  1.00 that a 10-seed preview suggested; more seeds, smaller number.
- How it was tested (commands + result):
  - `pytest -q` -> **352 passed** (21 new) in 3 minutes. `ruff check .` -> clean.
  - `python scripts/synthetic_check.py` prints the table and the gate verdict and writes the files.
- **The saved result file covers six engines, not eight.** The full 8-engine run takes about 13
  minutes because `SHAP_IFOREST` and `PARE_LGBM` cost 5 to 10 seconds per case, and the background
  run was stopped at a 10-minute limit. The gate only concerns `PARE` and `PARE_NO_RESIDUAL`, both
  of which are in the saved file. The two slow engines need a separate longer run before their
  numbers go anywhere near the paper; their figures in the M1.8 entry came from the first run, which
  used the buggy rank measurement, so **treat them as superseded**.
- Files changed: new `analyzer/scripts/synthetic_check.py`, `analyzer/tests/test_synthetic_check.py`;
  `analyzer/pare/eval_metrics.py` (`rank_in_order`), `analyzer/pare/engine.py`
  (`EngineSpec.use_graph`), `analyzer/tests/test_eval_metrics.py`, `analyzer/tests/test_engine.py`,
  `docs/05_PYTHON_ANALYZER_SPEC.md`, `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M1.11, the sample request and responses the Java tests will need, which closes
  M1. Also worth doing before the paper: a long run covering `SHAP_IFOREST` and `PARE_LGBM`.

### 2026-10-03 - M1.9 - eval_metrics.py, and settling how ties are scored
- What was done: `pare/eval_metrics.py`, the module that produces every number in the paper. It is
  kept apart from the engines deliberately, because it is the only place ground truth is allowed to
  appear - an engine never sees it, and a test asserts the words `gt_service`, `gt_column` and
  `ground_truth` do not occur anywhere in `engine.py`. Grounding: `ac_at_k`, `avg_at_5`,
  `exp_ac_at_k`, with `Rank` and `rank_of`. Cause versus symptom: `symptom_error`, `symptom_rate`.
  Explanation quality: `system_anomaly_score`, `deletion_faithfulness`, `random_deletion_baseline`,
  `topk_jaccard`, `kendall_tau`, `compactness`.
  - `kendall_tau` and `compactness` are not in the `05` section 1 list but are required by E5 in
    `08` section 4, so they are here rather than invented later in an experiment script.
- **Open question 4 is settled (decision 47).** Ties are scored as the expected hit rate if the tied
  group were shuffled: a ground truth in a group of size `m` starting at rank `r` contributes
  `clip(k - r + 1, 0, m) / m` to AC@k. With no ties that is exactly the textbook definition.
  Measured over 15 cases, it changes nothing for PARE, NSIGMA, SHAP_IFOREST or PCA_RECON, which have
  no ties at the top, and moves **ECDF's indicator accuracy from 0.13 to 0.46** - its mean tie group
  is 2.7 columns. The earlier 0.13 was an artefact of alphabetical ordering rather than a property
  of the method, and publishing it would have been wrong. The rule is now in `08` section 4 for the
  paper to quote, and `06` section 5 gains `tied_gt_service` and `tied_gt_indicator` so a result file
  carries what the metric needs.
- Two smaller judgement calls, both about not overstating a result:
  - `symptom_rate` returns **None**, not 0, when a method got everything right. Zero would read as
    "tested against the symptom problem and passed"; it was never tested at all.
  - `symptom_error` returns **None** when there is no graph, as `06` section 5 requires, rather than
    False. We cannot tell, and False would quietly understate the problem.
- How it was tested (commands + result):
  - `pytest -q` -> **331 passed** (38 new) in 45 s. `ruff check .` -> clean.
  - Expected values are worked out by hand: `ac_at_k([1,1,2,5,None], 1)` is 2/5; a group of five
    tied at the top gives AC@1 = 0.2, AC@3 = 0.6, AC@5 = 1.0; `avg_at_5([5])` is 0.2.
  - The deletion test is checked in both directions, which is the only way it means anything: naming
    the genuinely broken column first collapses the score to under 0.4 of its starting value, naming
    two innocent columns first leaves it essentially unchanged, and the faithful ordering has the
    smaller area. The random baseline sits between them and is reproducible under a seed.
  - `symptom_error` distinguishes the three outcomes that matter: blaming a caller of the culprit is
    a symptom error, blaming an unrelated service is wrong but **not** a symptom error and must not
    inflate the rate, and being right is neither.
- Files changed: new `analyzer/pare/eval_metrics.py`, `analyzer/tests/test_eval_metrics.py`;
  `analyzer/pare/__init__.py`, `docs/06_DATA_CONTRACTS.md`, `docs/08_EXPERIMENTS_SPEC.md`,
  `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M1.10, the synthetic check, which is the M1 gate proper.

### 2026-10-03 - M1.8 - the explainer baselines, and the first look at contribution C1
- What was done: `pare/explainers.py` with `shap_iforest()`, `ecdf_explainer()` and
  `pca_reconstruction()`, registered as the engines `SHAP_IFOREST`, `ECDF` and `PCA_RECON`. The
  registry now holds eight engines: the method, three ablations and four baselines.
  `kernel_shap_pca()` is left unimplemented - it is optional in `05` section 4, would cost minutes
  per case where the others cost milliseconds, and answers the same question as `PCA_RECON`; it
  raises with that reason rather than silently returning something that looks like an answer.
  - The baselines are deliberately **not** improved: none takes a call graph, none uses the change
    point, and their quirks are left in. A test asserts they have nowhere to put a graph. Improving
    them would make our own method look better and the comparison dishonest, since the claim is
    about what current practice does.
  - `EngineSpec.robust` (a flag) became `EngineSpec.scorer` (a name), because there are now five
    per-column scorers rather than two.
- A real bug was found by a test and fixed: **`marginal_score` for a service was always the maximum
  over its columns, while `score` honoured `service_agg`.** For `SHAP_IFOREST`, which the spec
  requires to sum a service's columns, that meant the two were a sum and a maximum of the same data.
  They sit side by side in the cause-versus-symptom chart, so that would have displayed as a gap
  that does not exist, and it also broke the contract line in `06` section 3 that says score equals
  marginalScore for engines without residuals. Both are now aggregated the same way. This mattered
  for `top2mean` too, so it was not only a SHAP problem.
- How it was tested (commands + result):
  - `pytest -q` -> **293 passed** (29 new) in 44 s. `ruff check .` -> clean.
  - Each baseline: one finite non-negative score per column, finds a planted anomaly, stays quiet on
    a window where nothing happened, survives missing values, and gives no opinion rather than
    crashing when there is too little history. `SHAP_IFOREST` is checked to be reproducible under a
    fixed seed, since it is the only explainer with randomness in it.
- **Two findings about PCA_RECON**, both now in its docstring and pinned by tests:
  1. It **smears blame across correlated columns**, so it often names a neighbour of the culprit
     rather than the culprit.
  2. It is **blind when columns are independent**. Keeping 95 percent of the variance of unrelated
     columns means keeping essentially all the components, and a full-rank model rebuilds everything
     perfectly - the anomaly included. Every score comes back around 1e-30. On realistic telemetry
     this does not bite (a generated case with 40 columns keeps 17 components), but it means a
     near-zero reconstruction error must never be read as "nothing is wrong".
- **First look at contribution C1.** 15 seeds, 8 services, latency fault, delay 30 s. ExpAC@1 is
  indicator-level accuracy; symptom rate counts how many wrong answers blamed a **caller** of the
  real cause:

  | amplification | engine | AC@1 | ExpAC@1 | wrong answers that blamed a caller |
  |---|---|---|---|---|
  | 0.00 | PARE | 1.00 | 1.00 | none wrong |
  | 0.00 | NSIGMA | 1.00 | 1.00 | none wrong |
  | 0.00 | SHAP_IFOREST | 0.73 | 0.73 | 3 of 4 |
  | 0.00 | ECDF | 1.00 | **0.33** | none wrong |
  | 0.00 | PCA_RECON | 0.07 | 0.07 | 1 of 14 |
  | 0.25 | PARE | 0.93 | 1.00 | 1 of 1 |
  | 0.25 | NSIGMA | 0.80 | 0.80 | 3 of 3 |
  | 0.25 | SHAP_IFOREST | 0.73 | 0.73 | 3 of 4 |
  | 0.25 | ECDF | 1.00 | **0.13** | none wrong |
  | 0.25 | PCA_RECON | 0.00 | 0.00 | 4 of 15 |

  Three things stand out, all of which are the kind of result C1 exists to produce.

  **SHAP on an Isolation Forest blames a caller three times out of four when it is wrong.** That is
  the paper's thesis appearing in the first measurement that could show it.

  **ECDF is perfect at service level and poor at indicator level** - 1.00 against 0.13. A method can
  look flawless in the coarse table everyone reports and be nearly useless at the question an
  engineer actually asks, which is "which metric". Part of this is the saturation effect now written
  up as open question 4, and M1.9 must settle how ties are scored before these numbers go in a paper.

  **PCA_RECON is close to useless here**, 0.00 to 0.07, and mostly not through the symptom trap - it
  simply blames whichever columns reconstruct worst, which in our data are the memory random walks.

  These are synthetic numbers on one fault type and are not paper results; RE1 in M3 is. But the
  pipeline that will produce the paper results now runs end to end.
- Files changed: new `analyzer/pare/explainers.py`, `analyzer/tests/test_explainers.py`;
  `analyzer/pare/{engine,rank,config,__init__}.py`, `analyzer/tests/test_engine.py`,
  `docs/05_PYTHON_ANALYZER_SPEC.md` (timings), `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M1.9, `eval_metrics.py`, which has to settle open question 4 on its way.

### 2026-10-03 - M1.7b - measuring the PARE_LGBM ablation
- What was done: the `PARE_LGBM` engine itself was registered during M1.7, and the "returns a valid
  result" half of the task was already covered by the test that runs every engine. What was missing
  was the half the task names specifically - that its **ranking is sane on one synthetic latency
  case** - and any measurement of how the ablation actually performs, which is the result the paper
  needs. Both are now done.
  - `test_pare_lgbm_ranks_sanely_on_a_synthetic_latency_case`: on a straightforward latency case the
    ablation finds the culprit, gives it the CAUSE role, keeps the change-point re-anchoring, names
    the right top indicator, and returns finite scores with inherited fractions inside [0, 1].
  - `test_pare_lgbm_differs_from_pare_only_in_its_dependency_model`: asserts the two engine
    specifications are identical apart from the model. An ablation that changes two things at once
    measures nothing, and that is easy to break later by editing the registry.
- How it was tested (commands + result):
  - `pytest -q` -> **264 passed** (2 new) in 25.9 s. `ruff check .` -> clean.
  - Measured as a whole engine, 20 seeds, 8 services, latency fault, delay 30 s:

    | amplification | PARE | PARE_LGBM | mean ms, ridge / lgbm |
    |---|---|---|---|
    | 0.00 | 1.00 | 1.00 | 233 / 1391 |
    | 0.25 | 0.95 | 0.90 | 369 / 2196 |
    | 0.50 | 0.70 | 0.55 | 401 / 2397 |

    **The ablation is a clean negative result.** With no congestion there is nothing to get wrong and
    both are perfect. As soon as there is a trap to fall into, LightGBM is worse - five points behind
    at amplification 0.25 and fifteen behind at 0.50 - and it is about six times slower throughout.

    The reason was already found in M1.6 and this confirms it at the engine level: a tree ensemble
    cannot extrapolate. A fault pushes a callee far outside anything in the normal period, where the
    model's prediction is flat, so the caller is predicted at its normal level and its entire
    inherited rise lands in its own residual. The method needs a model that extrapolates; tree
    ensembles do not, however well they interpolate.
  - Worth noting for `05` section 7: at 2.2 to 2.4 seconds `PARE_LGBM` is **over the 2 second
    response budget**. That is acceptable for an offline ablation and not for a default engine, which
    it is not. If it were ever exposed in the application, it would need a longer timeout.
- Files changed: `analyzer/tests/test_engine.py`, `docs/05_PYTHON_ANALYZER_SPEC.md` (engine table
  note), `PROGRESS.md`.
- Left open / next: M1.8, the explainer baselines.

### 2026-10-03 - M1.7 and M1.7b - preprocess, rank and the engine registry
- What was done: the method is now runnable end to end. `pare/preprocess.py` (step 0),
  `pare/rank.py` (steps 4 and 5) and `pare/engine.py` (the registry and `analyze()`), all exported
  from `pare`. Five engines are registered: `PARE`, `PARE_NO_RESIDUAL`, `PARE_NO_CP`, `PARE_LGBM`
  and `NSIGMA`. `AnalyzeResult` maps field for field onto `AnalyzeResponse` in `06` section 3.
  - `preprocess.py` was **not** in the task list although it is in the `05` section 1 layout, and
    the engine cannot run without it. Built here rather than inventing a task for it; `07` now says
    so. Decision 39.
  - `rank.py` holds the service score, the traversal, the verdict rule and the strict role
    precedence agreed in decision 9.
  - `engine.py` expresses the engines as a small table of three differences - change point, residuals,
    window - so the ablations cannot drift away from the method they are ablating.
- How it was tested (commands + result):
  - `pytest -q` -> **262 passed** (59 new) in 18.6 s. `ruff check .` -> clean.
  - Both guarantees `05` section 6 asks for by name are covered for **every** engine: a case with an
    entirely missing column, a long gap and a flat column still returns a valid result with no graph;
    and a window containing no fault comes back `NO_CLEAR_CAUSE` with nobody given the CAUSE role.
  - Roles are tested directly rather than through an engine, because a wrong role is a wrong answer
    shown confidently to a user: SYMPTOM needs both conditions, a barely-moved service with a high
    inherited fraction stays NORMAL, and when the verdict is NO_CLEAR_CAUSE the leader falls through
    to another role instead of being accused.
  - Preprocessing has a test for the property that matters most: **which columns are kept is decided
    by the normal window alone**. The abnormal window is the one containing the fault, and letting it
    choose which columns are worth looking at would be letting the answer pick the question.
  - Speed: a typical case is answered in about 120 ms warm, against the 2 s budget in `05` section 7.
- **Early look at the M1 gate**, which M1.10 will do properly. 25 seeds, 8 services, delay 30 s,
  top-1 accuracy:

  | amplification | fault | PARE | PARE_NO_RESIDUAL | PARE_NO_CP | NSIGMA |
  |---|---|---|---|---|---|
  | 0.00 | latency | 1.00 | 1.00 | 1.00 | 1.00 |
  | 0.00 | cpu | 1.00 | 1.00 | 1.00 | 1.00 |
  | 0.00 | mem | 0.92 | 0.92 | 0.92 | **1.00** |
  | 0.00 | error | 1.00 | 1.00 | 1.00 | 1.00 |
  | 0.25 | latency | **0.96** | 0.84 | 0.96 | 0.88 |
  | 0.25 | cpu | 1.00 | 1.00 | 1.00 | 1.00 |
  | 0.25 | mem | 0.92 | 0.92 | 0.92 | **1.00** |
  | 0.25 | error | 1.00 | 1.00 | 1.00 | 1.00 |

  Both halves of the gate hold: PARE on latency is 1.00 and 0.96, comfortably above the 0.85 the
  spec asks for, and PARE is never below `PARE_NO_RESIDUAL`. The 12-point gap at amplification 0.25
  on latency faults is the core claim appearing for the first time in a full run.

  Two honest readings to carry forward. Without amplification every engine ties, which is expected
  and is exactly why open question 3 had to be settled. And **NSIGMA beats PARE on memory faults**,
  0.92 against 1.00, in every setting. That is consistent with the M1.5 finding: a memory fault ramps
  rather than steps, so the change point lands mid-ramp, while NSIGMA scores from the alarm to the
  end of the data and so sees the whole ramp. It is a real result and belongs in the paper as one;
  it also suggests the analysis window length deserves an ablation for ramp-like faults.
- Files changed: new `analyzer/pare/{preprocess,rank,engine}.py` and
  `analyzer/tests/test_{preprocess,rank,engine}.py`; `analyzer/pare/scores.py` (`nsigma_score`),
  `analyzer/pare/residual.py` (carries `metric`, sklearn imported at module level),
  `analyzer/pare/__init__.py`, `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M1.8, the explainer baselines.

### 2026-10-03 - M1.6 - residual.py, the core idea, and two limits it revealed
- What was done: `pare/residual.py` with `DependencyModel` and `ColumnResidual`, exported from
  `pare`. For every column of every service it fits that column from the columns of the services it
  **calls**, at t and t-1, on normal rows only, and scores what is left over. A small leftover means
  the callees account for the movement and the service is a symptom; a large one means the trouble
  starts there. Implements `05` step 3 including the raw-units inherited fraction and `explained_by`.
  - `explained_by` is computed as a counterfactual - what the model would have predicted had this
    callee stayed normal - which for a linear model is exactly the coefficient formula the spec gives
    and also works for the LightGBM variant that has no coefficients to read.
  - Without a graph, or for a service with no callees, the self-score is simply the marginal score
    and nothing is inherited. That is the honest answer: we had nothing to explain it with.
- How it was tested (commands + result):
  - `pytest -q` -> **203 passed** (18 new) in 7.9 s. `ruff check .` -> clean.
  - The spec's own test first (`05` section 6): a parent whose latency is a linear function of its
    child's, with only the child faulty, gets a self-score of **0.77** against a marginal score of
    6.12, while the child scores 5.95. Movement alone would have blamed the parent; the residual does
    not. Its inherited fraction is 0.989.
  - The no-own-history rule has a test of its own: a strongly autocorrelated service that breaks must
    still get a large self-score. If its own past ever became a feature, the model would learn the
    anomaly a row after it starts and predict it away.
  - Properties: the inherited fraction stays inside [0, 1] for all four fault types; every column
    gets exactly one result; flat, missing and partially missing columns all produce finite scores.
  - End to end: on cases where movement alone points at a caller, the residual recovers the real
    culprit in every one of them at amplification 0.25.
- **Two limits were found, and both are properties of the approach rather than of the code.** Three
  tests failed on the first run; in all three the code was right and my expectations were wrong
  (hard rule 12), and the investigation is where the findings came from. Both are now written into
  `05` step 3 and pinned by tests.
  1. **A symptom's self-score is not zero and grows with the size of the fault.** The model is fitted
     on the normal range and the incident pushes its inputs outside it, so any slope error - and
     ridge shrinkage guarantees one - is multiplied by how far the fault reaches. Measured on the
     same parent-and-child setup: self-score 0.7, 2.3, 4.8, 9.6 for faults of 2, 6, 12 and 24 std,
     while the inherited fraction stayed at 0.996 throughout. So `inherited_fraction` is the stable,
     honest number to show a user, and the margin between cause and symptom narrows as faults grow.
     A smaller `ridge_alpha` cut the symptom's score from 2.3 to 0.5, so alpha is worth an ablation.
  2. **LightGBM is the wrong kind of model for this, and `PARE_LGBM` is a negative result.** Trees
     cannot extrapolate: beyond their training range the prediction is flat, so the caller is
     predicted at its normal level and its whole inherited rise lands in the residual. Ridge gave the
     parent 0.77 against the child's 5.95; LightGBM gave the parent **48.5**, ranking the symptom far
     above the cause. This is a clean finding for the ablation table - residual-based RCA needs a
     model that extrapolates - and the behaviour is pinned by a test so it is not later mistaken for
     a bug.
  - Decision 38's measured table has been **corrected** using the real implementation rather than the
    earlier least-squares proxy. The useful band is narrower and lower than the proxy suggested
    (around amplification 0.25, not 0.5), and limit 1 above is why.
- Files changed: new `analyzer/pare/residual.py`, `analyzer/tests/test_residual.py`;
  `analyzer/pare/__init__.py` (exports), `docs/05_PYTHON_ANALYZER_SPEC.md` (the counterfactual note
  and the two limits), `docs/07_TASKS.md` (M1.6 ticked), `PROGRESS.md`.
- Left open / next: M1.7, `rank.py` and `engine.py`. Everything the ranking needs now exists.

### 2026-10-03 - M1.5 - changepoint.py, re-anchoring the window when detection is late
- What was done: `pare/changepoint.py` with `estimate_change_point()` and the `ChangePoint` result,
  exported from `pare`. This is the step that answers RQ4: an alarm says "something is wrong now",
  but the fault may have started a minute earlier, and scoring from the alarm measures the aftermath
  - by which time the symptoms have caught up with the cause and the two look alike. So the window is
  re-anchored on where the data says the change began.
  - Follows `05` step 2: rank columns by `max |z|` in the run-up to the alarm, take the top
    `cp_top_k`, search each with `ruptures.Binseg(model="l2")` for one split, and take the **median**
    of the candidates so one column misled by a blip cannot drag the answer.
  - `ChangePoint` carries `estimated`, a plain-language `reason`, the candidate times and the columns
    they came from. When nothing usable is found it returns the alarm time with `estimated=False`,
    so a caller never receives a guess dressed up as a measurement.
- Three things about the ruptures API were checked against the installed v1.1.10 rather than assumed
  (hard rule 9), and two of them changed the code:
  - **`jump` defaults to 5**, which only proposes breakpoints at multiples of 5 and so rounds the
    answer to the nearest 5 rows. On a series whose change is at index 102 the default answers 100;
    with `jump=1` it answers 102. We care which second the change began, so this module sets
    `jump=1`. Decision 35.
  - **A flat column does not raise, it returns a confident split in the middle of nothing.** That
    would be pure invention, so flat columns are filtered out before searching. Decision 36.
  - A window shorter than `2 * min_size` raises `BadSegmentationParameters`, which is a normal
    outcome here rather than a failure, so it is caught and that column is skipped.
- How it was tested (commands + result):
  - `pytest -q` -> **177 passed** (19 new) in 2.2 s. `ruff check .` -> clean.
  - The spec's own bar first: "a step series with a known change at index 100 is found within +/- 3
    rows" (`05` section 6). Then the same at 40, 77, 100, 102 and 150, because positions that are not
    multiples of 5 are exactly what the `jump` default would have rounded.
  - The point of the module has its own test: with the alarm 60 rows late, the estimate still lands
    within 3 rows of the real start, and `seconds_before_alarm` reports about 60.
  - Failure behaviour: a flat column produces no estimate rather than an invented one; an all-missing
    column is skipped while its neighbour still works; scattered NaN is tolerated; too few rows falls
    back to the alarm time with a readable reason; a change outside the lookback is not pretended to
    be found.
  - Measured end to end against generated data where the true injection time is known exactly,
    20 seeds per setting, 8 services. Error of the re-anchored start against the real injection:

    | fault | delay 0 s | 30 s | 60 s | 120 s |
    |---|---|---|---|---|
    | latency | 0.0 | 0.0 | 0.0 | 0.0 |
    | cpu | 2.0 | 0.0 | 0.0 | 0.0 |
    | error | 0.5 | 0.0 | 0.0 | 0.0 |
    | mem | 78.5 | 37.5 | 40.0 | 61.0 |

    (median absolute error in seconds; without re-anchoring the error simply *is* the delay, so the
    comparison row is 0 / 30 / 60 / 120.) An estimate was produced in 20 of 20 cases everywhere.

    So for the three step-like faults, re-anchoring recovers the true start essentially exactly even
    when the detector is two minutes late. That is the RQ4 claim behaving as hoped, on synthetic data.
  - **`mem` is the exception and it is worth knowing why**: a memory fault ramps up gradually rather
    than stepping, and a ramp has no sharp split, so Binseg lands somewhere in the middle of it
    instead of at its onset. This is the same root cause as open question 4. It is not obviously
    harmful - a window starting mid-ramp contains a stronger signal than one starting at the barely
    perceptible beginning - but it does mean the delay-robustness claim will look weaker for MEM than
    for the others, and the paper should say so rather than report an average that hides it.
- Files changed: new `analyzer/pare/changepoint.py`, `analyzer/tests/test_changepoint.py`;
  `analyzer/pare/__init__.py` (exports), `docs/07_TASKS.md` (M1.5 ticked), `PROGRESS.md`.
- Left open / next: M1.6, `residual.py`, which is the core idea of the whole method. Open question 3
  still needs an answer before M1.7 and M1.10.

### 2026-10-03 - M1.4 - graph.py, the call graph and the questions asked of it
- What was done: `pare/graph.py` with `CallGraph` and `Edge`, exported from `pare`. An edge runs
  from caller to callee, and everything else follows from that: `children(s)` are the services s
  calls (the dependency model's features), `parents(s)` are its callers, and `ancestors(s)` is every
  caller directly or indirectly - which is exactly the set the symptom-rate metric is defined on.
  `descendants(s)` is the mirror image. Also `from_edges`, `from_dicts`/`to_dicts` for the JSON form
  in `06` section 2, `empty()`, `has_edge`, `services`, `is_empty`, and `infer_from_correlation`.
  - `from_edges` accepts all three shapes we actually receive: `(caller, callee)` tuples from
    `pare.synthetic`, `{"from", "to"}` mappings from the API, and `Edge` objects.
  - The graph carries `source` (one of the six values in `06` section 2), so a reader of a result
    knows whether the edges came from traces or from guesswork.
  - Messy graphs are normal input, not errors: duplicate edges are collapsed, unknown services give
    empty answers rather than raising, and cycles terminate. Self-loops are dropped - see decision 33.
- How it was tested (commands + result):
  - `pytest -q` -> **158 passed** (26 new) in 0.84 s. `ruff check .` -> clean.
  - The direction convention gets its own tests, because if `children` and `parents` were ever
    swapped the dependency model would use the wrong features and the symptom rate would measure the
    opposite of what it claims, with nothing else failing. On a five-service tree:
    `children("frontend") == ("checkout", "catalogue")`, `parents("cart") == ("checkout",)`,
    `ancestors("cart") == {"checkout", "frontend"}`, and `catalogue` is **not** among the services
    that can be affected by a fault in `cart`.
  - Messy input: a cycle `a->b->c->a` terminates and never reports a service as its own ancestor; a
    diamond reports each service once; duplicates collapse; an unknown service gives `()`; the empty
    graph answers every question without raising.
  - `infer_from_correlation` was measured against graphs we actually know, 20 seeds per setting,
    rather than only asserted loosely (see decision 34 for what it does):

    | services | propagation | undirected precision | undirected recall | directed precision |
    |---|---|---|---|---|
    | 6 | 0.5 | 1.00 | 0.30 | 0.88 |
    | 6 | 0.9 | 0.86 | 0.80 | 0.60 |
    | 10 | 0.5 | 1.00 | 0.17 | 0.78 |
    | 10 | 0.9 | 0.83 | 0.67 | 0.55 |

    Read: it rarely invents a call that does not exist, it misses many real ones when propagation is
    weak (a weak call leaves little correlation to find), and it gets the direction right more often
    than a coin toss but not much more. That is the right shape for its purpose - experiment E4 needs
    a plausible *wrong* graph to measure what a bad graph costs, not a good one.
  - Also tested: unrelated noise produces no edges at all, only the chosen metric is used,
    `max_children` caps the fan-out, a flat service is skipped, and the input shape is checked.
- Files changed: new `analyzer/pare/graph.py`, `analyzer/tests/test_graph.py`;
  `analyzer/pare/__init__.py` (exports), `docs/07_TASKS.md` (M1.4 ticked), `PROGRESS.md`.
- Left open / next: M1.5 (`changepoint.py`). The ruptures API was already checked against the
  installed version during M0 and written into `05` step 2, so that one starts from a known API.
  Open question 3 still needs an answer before M1.7 and M1.10.

### 2026-10-03 - M1.3 - scores.py, the shared scoring building blocks
- What was done: `pare/scores.py` with the three functions the spec names - `robust_z`,
  `window_score` and `ecdf_tail_score` - plus `robust_baseline()` and `mad()`, which they all share
  and which `residual.py` will reuse at M1.6. This is step 1 of the method: how strange a column
  looks on its own, before anything about the call graph is considered. Exported from `pare`.
  - `robust_baseline(normal)` measures the median and the scaled MAD per column, applying the
    epsilon rule from `05` step 1 (`1.4826 * MAD + 1e-6 * (|median| + 1)`) in one place, so a
    perfectly flat column can never divide by zero anywhere in the project.
  - `robust_z` keeps the sign, because the explanation text needs to say whether something went up
    or down.
  - `window_score` is the marginal score: `|median(abnormal) - median(normal)| / scale`. The median
    of the window rather than its maximum, so a single wild reading is not mistaken for an incident.
  - `ecdf_tail_score` is the ECOD-style baseline for the `ECDF` engine: `-log` of the two-sided
    empirical tail probability, floored at `1/(n+1)` so a value beyond anything ever seen gives a
    large but finite score rather than infinity. The ceiling is therefore `log(n+1)`.
  - Decisions 31 and 32 below cover the two judgement calls: what to do with an all-missing column,
    and accepting both one column and a whole window in the same function.
- How it was tested (commands + result):
  - `pytest -q` -> **132 passed** (30 new) in 0.8 s. `ruff check .` -> clean.
  - `05` section 6 asks for "robust z and window score on hand-made arrays", so the expected numbers
    are worked out by hand in the test and written there, not copied from what the code printed. For
    example the baseline of `[1,2,3,4,5]` is median 3 and MAD 1, so a value of 5 must score
    `2 / (1.4826 + 4e-6)`.
  - The two design claims are tested directly rather than assumed: an extreme value in the normal
    period moves the median by less than 0.1 while it moves the mean by more than 5x and the standard
    deviation by more than 100x; and a single spike of 10,000 inside an otherwise quiet window leaves
    the window score below 0.5, while a sustained shift pushes it above 3.
  - Also covered: a flat column gets a positive scale instead of zero, scores are never negative in
    either direction, several columns at once, scattered NaN, an entirely missing column scoring 0
    rather than NaN, empty inputs raising clearly, and integers not being truncated.
  - One test of mine failed first time and the test was at fault, not the code (hard rule 12). It
    built "clean" data as fifty 10s followed by fifty 12s, whose median sits in the gap at 11.0;
    appending one more value makes the count odd and the median jumps a whole level to 12.0. That is
    an artefact of bimodal toy data with an even count, not a weakness of the median. Replaced with a
    normal sample, where the claim holds properly.
- Files changed: new `analyzer/pare/scores.py`, `analyzer/tests/test_scores.py`;
  `analyzer/pare/__init__.py` (exports), `docs/07_TASKS.md` (M1.3 ticked), `PROGRESS.md`.
- Left open / next: M1.4 (`graph.py`), which is also unaffected by open question 3. That question
  still needs an answer before M1.7 and M1.10.

### 2026-10-03 - M1.2 - synthetic generator, and a problem with the model it implements
- What was done: `pare/synthetic.py` with `make_case()` and `SyntheticCase`,
  `analyzer/scripts/make_synthetic_example.py`, and the generated
  `paper/figures/synthetic_example.png`. Choices are decisions 26 to 30 below. The generator follows
  `05` section 5, including the agreed change that a memory fault also raises the culprit's own
  latency so it can reach callers.
- **What needs the human: the model cannot produce the cause-versus-symptom confusion the paper is
  about.** Written up as open question 3, with the measurements and the algebra. In short, a caller's
  robust-z can never exceed the culprit's under a linear propagation sum, so marginal scoring is
  already near-perfect (30/30 latency cases, 28/30 memory cases) and E6 as designed would show PARE
  adding nothing. Measured over 200 cases: the caller-to-culprit z ratio peaked at 0.973 and averaged
  0.591. The proposed fix is a non-linear congestion term with an `amplification` factor that
  defaults to today's behaviour; it is not applied, because it changes the research model.
  Open question 4 records a second, smaller issue: a memory fault's median deviation is about 1.9
  stds, below the 3.0 `min_cause_score`, because the ramp only reaches full size at the last row.
- How it was tested (commands + result):
  - `pytest -q` -> **102 passed** (56 new) in 0.63 s. `ruff check .` -> clean.
  - The new tests cover shape and naming, that a seed reproduces bit for bit and different seeds do
    not, that the graph really is a tree rooted at `frontend` with no cycles, that each of the four
    faults is visible in its ground-truth column, that the normal rows stay clean so splitting them
    for training is safe, and that ground truth never appears as a data column.
  - Propagation has its own tests because E6 depends on it: the fault reaches the callers and not
    unrelated services; every fault type including `mem` and `cpu` reaches a caller; stronger
    propagation moves the caller more; `propagation=0` keeps the fault put while the culprit stays
    clearly broken; `frontend` as culprit has nothing to propagate to.
  - All sixteen corners of the E6 grid (4 faults x n_services 5 and 40 x propagation 0.2 and 1.0)
    build finite, usable cases.
  - Beyond the tests, two diagnostics were run to check the generator behaves as intended rather
    than merely passing its own assertions. They are what turned up open questions 3 and 4.
- Files changed: new `analyzer/pare/synthetic.py`, `analyzer/scripts/make_synthetic_example.py`,
  `analyzer/tests/test_synthetic.py`, `paper/figures/synthetic_example.png`;
  `docs/05_PYTHON_ANALYZER_SPEC.md` (section 5: the memory latency term and why, the two-pass
  construction, what `make_case` returns), `docs/07_TASKS.md` (M1.2 ticked), `PROGRESS.md`.
- Left open / next: M1.3 (`scores.py`), which is unaffected by open question 3. That question should
  be settled before M1.7 builds the engines and M1.10 runs the synthetic check, because it decides
  what that check can possibly show.

### 2026-10-03 - M1.1 - pare package skeleton, PareConfig and ColumnInfo
- What was done: the first real code. `analyzer/pyproject.toml` (package `pare`, `[dev]` extra with
  pytest and ruff, ruff and pytest settings), `pare/__init__.py` holding `__version__` as the single
  source of truth, `pare/config.py` with `PareConfig`, and `pare/columns.py` with `ColumnInfo` and
  the lookup helpers the later steps need (`services`, `group_by_service`, `columns_of_service`,
  `name_to_index`, `validate_columns`, `columns_from_dicts`). Choices and reasons are decisions 21
  to 25 below. `pare/py.typed` marks the package as typed.
  - `config.py` carries all 16 parameters from `05` section 1.1 with a one-line docstring each, the
    validation rules, `with_changes()` for the ablations, and the camelCase conversion for the API.
  - `columns.py` deliberately has no name-guessing helper, and says in its module docstring why.
- How it was tested (commands + result):
  - `pip install -e ".[dev]"` in `analyzer/` -> installs clean; `import pare` reports version 0.1.0
    from the working tree, so the editable install works.
  - `pytest -q` -> **46 passed** in 0.07 s.
    - `test_config.py` copies the spec table from `05` section 1.1 and asserts every default against
      it, and separately asserts that the set of fields in the code equals the set in the table. So a
      default changed on one side without the other now fails the build instead of quietly changing
      every number in the paper.
    - Validation is checked with 14 parametrised bad values, plus the case that `cp_lookahead_s=0`
      must be *allowed*, because 0 is exactly the replay situation.
    - The API boundary is covered both ways, including that an unknown key raises and that
      `from_api_params(to_api_params())` round-trips.
    - `test_columns.py` covers duplicate rejection, that two services may share a metric name,
      ordering guarantees, the name->index map used by every engine, and the JSON round trip.
  - `ruff check .` -> clean. Two findings were fixed first: `Iterable`/`Mapping` now come from
    `collections.abc`, and one error message was wrapped to stay inside 100 columns.
- Files changed: new `analyzer/pyproject.toml`, `analyzer/pare/{__init__,config,columns}.py`,
  `analyzer/pare/py.typed`, `analyzer/tests/{test_config,test_columns}.py`;
  `docs/06_DATA_CONTRACTS.md` (section 3 now records how `params` keys are named, needed so the Java
  client builds the same keys), `docs/07_TASKS.md` (M1.1 ticked), `PROGRESS.md`.
- Left open / next: M1.2, the synthetic generator. Nothing from M1.2 onward was written. The
  PyTorch question is still open and still only matters at M2.

### 2026-10-03 - M0.1 / M0.2 / M0.3 - project skeleton and working Python environment
- What was done:
  - Installed Python 3.10.20 with `uv python install 3.10` and created `analyzer/.venv` on it, then
    installed the full analyzer stack into it (decisions 19 and 20).
  - M0.1: created `analyzer/`, `experiments/`, `backend/`, `frontend/`, `scripts/` and `paper/`
    (with `tables/`, `figures/`, `notes/`), each with a short README saying what it is and how to
    run it. `paper/*` and `experiments/results/` carry a `.gitkeep` so git tracks the empty folders.
    The git-ignored `data/cases`, `data/uploads`, `data/db` and `data/cache` were created with **no
    README**, per decision 16; the layout is in the root `README.md` instead.
  - M0.2: checked `.gitignore`. It already covered Java `target/`, Python `.venv/`/`__pycache__/`,
    Node `node_modules/`/`dist/`, `data/` and `experiments/results/*`. No change needed.
  - M0.3: filled in "Environment" below, and corrected the free-disk figure (24.4 GB, not the
    11.7 GB measured earlier the same day).
  - While the environment was fresh, checked the two library APIs that `docs/05` explicitly says not
    to guess, and wrote the findings into that spec so nobody has to re-derive them.
- How it was tested (commands + result):
  - `uv python install 3.10` -> installed 3.10.20; `uv venv analyzer/.venv --python 3.10` ->
    `analyzer/.venv/Scripts/python.exe --version` reports 3.10.20.
  - `uv pip install ...` into that venv -> every package resolved to the version the earlier dry run
    predicted, so the 3.10 decision is confirmed by a real install, not just by metadata.
  - Smoke test run with the venv interpreter, all assertions passed:
    - every one of the 17 required modules imports, versions printed above;
    - **ruptures**: `Binseg(model="l2").fit(x).predict(n_bkps=1)` on a series with a step at index
      100 returns `[100, 200]`. So the returned list ends with `len(x)` as a sentinel and the change
      point is `bkps[0]`. Written into `docs/05` step 2.
    - **shap**: `shap.TreeExplainer(IsolationForest).shap_values(X)` works in shap 0.49.1, returns
      shape `(n_rows, n_columns)`, needs **no** `check_additivity=False`, and ranks a planted
      single-column anomaly first. Written into `docs/05` section 4, replacing the "check whether it
      is supported" caveat.
    - `LGBMRegressor(n_estimators=100, max_depth=3)` fits and predicts (needed for M1.7b).
    - `Ridge(alpha=1.0)` recovers coefficients 2, -1, 0 from data built with those coefficients.
  - `git status` confirms `data/` and `analyzer/.venv` are ignored, and that
    `experiments/results/.gitkeep` is trackable despite `results/*` being ignored.
- Files changed: the new folders and their READMEs, `docs/07_TASKS.md` (M0.1 to M0.3 ticked),
  `docs/05_PYTHON_ANALYZER_SPEC.md` (the two verified APIs), `PROGRESS.md`.
- Left open / next: M1.1. Still waiting on the human for the PyTorch question, which first matters
  at M2.

### 2026-10-03 - Environment check and build tooling - no code yet
- What was done: checked every requirement in `PROJECT_RULES.md` section 4 against the actual machine and
  recorded the result in "Environment" below. Java 21, Node 24.15.0, npm 11.12.1, git and uv are all
  present and fine. Three gaps found: Maven missing, Python 3.10 missing (only 3.14, which this stack
  cannot use), and the Python libraries not installed. Decided on the Maven Wrapper instead of a
  system Maven (decision 18) and set `JAVA_HOME`, which was empty. Two findings need the human and
  are written up under "Open questions": RCAEval's `default` extra requires PyTorch, and the disk has
  only 11.7 GB free.
- How it was tested (commands + result):
  - `java -version` / `javac -version` -> 21.0.12.1 LTS; `node -v` -> v24.15.0; `npm -v` -> 11.12.1;
    `git --version` -> 2.54.0; `uv --version` -> 0.11.20.
  - `mvn -v` -> not found. Confirmed it is genuinely absent, not a stale PATH: no `mvn.cmd` anywhere
    under `C:\`, Program Files, the user profile, LocalAppData or ProgramData; no `MAVEN_HOME` or
    `M2_HOME`; the live registry PATH (machine and user) contains only the Oracle javapath entry.
    `winget search Apache.Maven` -> no package.
  - `py -0p` -> only 3.14 present; `py -3.10 --version` -> no suitable runtime.
  - Package presence checked with `importlib.util.find_spec` in the 3.14 environment: pandas,
    sklearn, shap, lightgbm, ruptures, networkx, statsmodels, matplotlib, pyarrow all missing.
  - 3.14 incompatibility verified from PyPI metadata and wheel filenames, not from memory: ruptures
    1.1.10 is capped `<3.14` with Windows wheels only up to cp313; shap 0.52.0 has no Windows cp314
    wheel; dowhy is capped `<3.14`.
  - `uv pip compile --python-version 3.10 --python-platform windows` on the full stack -> resolves
    cleanly; the chosen versions are listed in "Environment".
  - RCAEval metadata read from PyPI: 414 `requires_dist` entries, all behind the extras
    `default` / `rcd` / `eventadl`; `default` requires `torch>=1.12.1`, `numpy<2`, `networkx==2.5`.
  - `setx JAVA_HOME "C:\Program Files\Java\jdk-21.0.12.1"` -> verified by reading it back from
    `HKCU:\Environment` and confirming `bin\java.exe` exists at that path.
  - Nothing was installed. All of the above was read-only apart from setting `JAVA_HOME`.
- Files changed: `PROJECT_RULES.md` (section 6 and definition of done now use `./mvnw`),
  `docs/02_ARCHITECTURE.md` (run command), `docs/03_JAVA_BACKEND_SPEC.md` (section 1 explains the
  wrapper and the M8.1 ordering constraint), `PROGRESS.md`.
- Left open / next: the human's answer on the PyTorch question (not needed until M2) and on disk
  space. Then `uv python install 3.10`, the `analyzer/` virtual environment, and M0.1 + M0.3.

### 2026-10-03 - Spec fixes after first review - no code yet
- What was done: read `PROJECT_RULES.md`, `PROGRESS.md` and all nine files in `docs/`, reported 6
  contradictions, 7 ambiguities and 4 smaller problems, and applied the human's rulings to the
  specs. All 17 decisions are written up under "Decisions made" below. Changes by file:
  - `PROJECT_RULES.md`, `README.md`: dropped the `HOW_TO_USE_THIS_KIT.md` references; the root README now
    describes the `data/` layout and the `XAIRCA_DATA_DIR` variable.
  - `docs/00_RESEARCH_PLAN.md`: symptom rate reworded to "ancestor (caller)"; PELT replaced by
    Binseg as the implementation, PELT kept as an optional ablation.
  - `docs/02_ARCHITECTURE.md`: replay baseline no longer described as "before the fault"; data
    folder list extended.
  - `docs/03_JAVA_BACKEND_SPEC.md`: env-var data dir and derived H2 URL; `baseline-rows: 300`
    replacing `baseline-min-rows: 60`; detector no longer sees `injectTime`; `replayable` flag;
    stated assumption about the normal window; fallback window and verdict; `NO_CLEAR_CAUSE`
    headline; symptom template wording; `verdict` entity column; `NSIGMA_JAVA_FALLBACK` in
    `/api/engines`; in-memory H2 for tests.
  - `docs/04_REACT_FRONTEND_SPEC.md`: `NO_CLEAR_CAUSE` presentation (grey, no red, no cause
    sentences); UPPERCASE fault types and noise levels in the lab.
  - `docs/05_PYTHON_ANALYZER_SPEC.md`: new PareConfig parameter table (section 1.1); the one window
    table; raw-unit `inheritedFraction`; verdict and strict role precedence; NSIGMA window rule;
    noise and fault-name conversion at the service layer; two new tests.
  - `docs/06_DATA_CONTRACTS.md`: UPPERCASE enum rule; `verdict` in the response; `topK` 10 and its
    difference from `cpTopK`; uppercase synthetic request example; `faithfulness_auc` replaced by
    `verdict` in `cases.csv` plus the new `faithfulness.csv` / `stability.csv` schemas.
  - `docs/07_TASKS.md`: new M1.7b for `PARE_LGBM`; M1.7 now covers verdict and role precedence;
    M0.1 says no README in `data/`.
  - `docs/08_EXPERIMENTS_SPEC.md`: stated assumption about `inject_time` with the E3 no-`inject_time`
    variant; E5 writes its own files; noise levels uppercased.
- How it was tested: documentation only, so no build. Each edit was applied by a script that
  requires an exact unique match for every replacement and fails otherwise, so no edit landed in the
  wrong place. Afterwards `grep` confirmed zero remaining occurrences of `HOW_TO_USE`,
  `faithfulness_auc`, `baseline-min-rows`, bare `NSIGMA_JAVA`, `"noise": "medium"`,
  `"faultType": "latency"` and the old "downstream service" wording, and that `verdict` /
  `NO_CLEAR_CAUSE` now appear in all five docs that need them. Config key names (`cp_lookback_s`)
  were made consistent across `03`, `05` and `08`.
- Files changed: `PROJECT_RULES.md`, `README.md`, `PROGRESS.md`, `docs/00` through `docs/08` (all except
  `docs/01_PROJECT_OVERVIEW.md`, which needed nothing).
- Left open / next: M0.1 (create the folder skeleton with short READMEs, no README in `data/`) and
  M0.3 (fill in the Environment block) in one commit, then M1.1. No code written yet.
## Open questions (for the human)

1. **RCAEval pulls PyTorch. Does hard rule 1 allow it inside the isolated venv?**
   `pip install RCAEval` installs nothing by itself: all 414 dependencies sit behind extras
   (`default` 164, `rcd` 170, `eventadl` 80), so the real install is `RCAEval[default]`, and that
   extra requires `torch>=1.12.1`, plus `numpy<2` and `networkx==2.5` for Python < 3.13.
   - This confirms the separate-venv instruction in `PROJECT_RULES.md` section 4 and
     `08_EXPERIMENTS_SPEC.md` section 2 is mandatory, not optional: `numpy<2` and `networkx==2.5`
     cannot coexist with our resolved stack (numpy 2.2.6, networkx 3.4.2).
   - But hard rule 1 says "No PyTorch/TensorFlow". Reproducing their baselines (M2.4, M4.2) means
     torch lands in `experiments/.venv-rcaeval`, roughly 200-800 MB of wheels.
   - Proposed reading: the rule is about **our** method, which stays scikit-learn only; torch is
     allowed in the isolated baseline venv and nowhere else. Needs the human's yes before M2.
   - Not blocking anything before M2.

3. ~~**The synthetic model cannot produce the symptom trap.**~~ **SETTLED on 2026-10-03** - see
   decision 38 and the M1.2a log entry. In short: the cause was that linear propagation scales the
   inherited signal and the inherited noise by the same factor, so they cancel and a caller can never
   outscore the culprit for any propagation weight. Fixed by adding a non-linear congestion term with
   an `amplification` parameter, default 0, which reproduces the old linear model exactly. The trap
   now appears, PARE wins over a band of amplification, and beyond that band nothing metric-only
   works - which is reported rather than hidden.

4. ~~**Tie-breaking will affect ExpAC@k.**~~ **SETTLED on 2026-10-03** - decision 47. Scored as the
   expected hit rate if the tied group were shuffled. It changed `ECDF`'s indicator accuracy from
   0.13 to 0.46 and left every other engine untouched. Written into `08` section 4, which the paper
   must quote.

5. **A memory fault is weaker than the spec's `8 * std` suggests, and may fall under
   `min_cause_score`.** The ramp reaches `+8 * std` only at the last abnormal row, so the median over
   the analysis window is about half of that; measured, the culprit's memory column deviates about
   **1.9 stds**, not 8. `PareConfig.min_cause_score` is 3.0, so on current numbers a memory case could
   come back `NO_CLEAR_CAUSE`. Worth revisiting together with question 3, since both are about how
   strong an injected fault should be. Not blocking M1.3.

6. **Disk space** (less urgent than first reported). Now 24.4 GB free, not the 11.7 GB measured
   earlier that day. Still worth planning: `analyzer/.venv` already takes 644 MB, and the RCAEval
   RE2/RE3 downloads with their logs and traces plus torch are the big items still to come. Keeping
   only one RCAEval system on disk at a time (which `08_EXPERIMENTS_SPEC.md` section 2 already
   suggests for memory reasons) should be enough.

The 16 points raised in the first spec review were all answered on 2026-10-03 and are recorded
under "Decisions made" below.

## Things the human must check by hand
- Static call graphs in experiments/graphs/*.yaml (M2.5)
- Ground-truth indicator mapping for RCAEval (M2.2)
- Whether the M1.10 synthetic check supports the cause-versus-symptom story (gate before M2)
- Whether the first RE1 results in M3.2 support it on real data (gate before the application track)

## Environment (measured 2026-10-03)

Everything below was read off this machine, not assumed.

| Thing | Status |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26200 |
| CPU | 12th Gen Intel Core i5-1235U, 10 cores / 12 threads (no GPU used) |
| RAM | 15.7 GB total |
| Disk C: | 24.4 GB free of 237.7 GB (re-measured 2026-10-03 after the venv install; an earlier reading of 11.7 GB was taken before about 13 GB was freed on the machine) |
| Java | 21.0.12.1 LTS (Oracle), `C:\Program Files\Java\jdk-21.0.12.1`; `javac` 21.0.12.1 |
| JAVA_HOME | set to the path above on 2026-10-03 (it was empty) |
| Maven | **not installed, and deliberately not going to be** - we use the Maven Wrapper, see decision 18 |
| Python | **3.10.20** installed 2026-10-03 with `uv python install 3.10`, at `C:\Users\hp\AppData\Roaming\uv\python\cpython-3.10.20-windows-x86_64-none`. The pre-existing system 3.14.4 is untouched and is not used by this project |
| Project venv | `analyzer/.venv` on 3.10.20, 644 MB, git-ignored. Created with `uv venv analyzer/.venv --python 3.10` |
| uv | 0.11.20 |
| Node / npm | 24.15.0 / 11.12.1 |
| Git | 2.54.0.windows.1 |

Python packages in the global 3.14 environment: `numpy 2.4.4`, `scipy 1.17.1`, `pyyaml`, `joblib`,
`pytest`, `fastapi`, `uvicorn`, `pydantic` are present; **`pandas`, `scikit-learn`, `shap`,
`lightgbm`, `ruptures`, `networkx`, `statsmodels`, `matplotlib`, `pyarrow` are missing**. That
environment also holds ~190 unrelated packages (pipecat, google-genai, openai, playwright, boto3),
so the project will use its own virtual environment regardless.

Why Python 3.14 cannot be used for `analyzer/` (checked against PyPI, not guessed):
- `ruptures` 1.1.10 declares `requires_python = <3.14,>=3.9` and ships Windows wheels for cp39-cp313
  only. There is no cp314 wheel. Change-point detection is core to PARE.
- `shap` 0.52.0 needs >= 3.12, but its only 3.14 artifact is a `cp314t` (free-threaded) manylinux
  wheel. There is no Windows cp314 wheel.
- `dowhy` also caps at `<3.14`.

The whole stack does resolve cleanly for Python 3.10 on Windows (checked with
`uv pip compile --python-version 3.10 --python-platform windows`): numpy 2.2.6, pandas 2.3.3,
scikit-learn 1.7.2, scipy 1.15.3, shap 0.49.1, lightgbm 4.7.0, ruptures 1.1.10, networkx 3.4.2,
statsmodels 0.15.0, matplotlib 3.10.9, pyarrow 25.0.1, fastapi 0.142.2, uvicorn 0.54.0,
pydantic 2.13.5, pytest 9.1.1. So pip picks the last 3.10-compatible versions by itself and no
pinning work is needed.

## Decisions made

All of these came from the human's answers to the first spec review (2026-10-03) and are already
written into the spec files. One line of reason each.

### Contradictions between docs

1. **Symptom direction is "ancestor / caller of the true root cause".**
   Reason: edges run caller -> callee, so a fault travels from the called service up to its callers;
   the affected services are therefore ancestors, not descendants. `00_RESEARCH_PLAN.md` section 8.2
   said "downstream" and was wrong; the other four docs were already right.

2. **The Java fallback engine is called `NSIGMA_JAVA_FALLBACK` everywhere**, including the
   `/api/engines` list, which used to say `NSIGMA_JAVA`.
   Reason: the name is shown in the UI and stored in the database, so two spellings would mean two
   apparent engines.

3. **Change point = `ruptures.Binseg(model="l2")`, one change point.** PELT and Bayesian online CPD
   are optional ablations only.
   Reason: one implementation, named in one place (`05` section 3 step 2). `00` section 6 promised
   PELT and now points at the real choice. The PELT citation stays in the reference list.

4. **`noise` is the string `LOW` / `MEDIUM` / `HIGH` on the API and in the UI**; the FastAPI service
   layer maps it to the float the library wants (0.5 / 1.0 / 2.0) before calling
   `make_case(noise=float)`.
   Reason: the UI needs discrete labelled choices, the library needs a number, and exactly one place
   should know the mapping. Documented in `05` section 5 and `06` section 3.

5. **`faultType` is UPPERCASE in all JSON and in `meta.json`.** Synthetic: `LATENCY`, `CPU`, `MEM`,
   `ERROR`. RCAEval: the dataset's own names uppercased (`CPU`, `MEM`, `DISK`, `DELAY`, `LOSS`, plus
   the RE3 code-level names). The Python library may stay lowercase internally; the service layer
   converts.
   Reason: `meta.json` already used `MEM` while the synthetic request used `latency`, so the same
   field had two casings. Also made the library name consistent: `fault="mem"`, not `"memory"`.

6. **`HOW_TO_USE_THIS_KIT.md` will not exist.** The references in `PROJECT_RULES.md` and `README.md` are
   removed.
   Reason: two docs pointed at a file that was never written; deleting the pointer is simpler than
   inventing a fourth overview document.

### Ambiguities that needed a ruling

7. **`NSIGMA` (Python) and `NSIGMA_JAVA_FALLBACK` never use the change point.** Their abnormal
   window is `[alarmTime, end of recent]` on both sides.
   Reason: two reasons, both important. The shared-sample agreement test in `03` section 4.4 is only
   possible if both sides use the same window; and the delay-robustness claim (RQ4) is about what
   change-point re-anchoring adds, so the baselines must feel the full cost of a late alarm. The same
   rule applies to the explainer baselines (`SHAP_IFOREST`, `ECDF`, `PCA_RECON`).

8. **`inheritedFraction` is computed on one scale, in raw metric units:**
   `marginal_dev = |median(abnormal) - median(normal)|`,
   `self_dev = |median(abnormal residual) - median(normal residual)|`,
   `inheritedFraction = clip(1 - self_dev / marginal_dev, 0, 1)`, and 0 when `marginal_dev == 0`.
   `selfScore` stays normalised by the residual MAD, because that is the ranking score. The symptom
   template now reads "about X% of this change is explained by {explainedBy}".
   Reason: the old formula divided a residual-MAD score by a raw-MAD score. That is not a ratio of
   like quantities, so the "fraction" could leave [0, 1] - and the UI prints it as a percentage.

9. **There is now a "nothing clearly wrong" outcome.** New `PareConfig.min_cause_score = 3.0` and a
   new response field `verdict` (`ROOT_CAUSE_FOUND` | `NO_CLEAR_CAUSE`). If the top service score is
   below the threshold the verdict is `NO_CLEAR_CAUSE` and **no service gets the role `CAUSE`**.
   Roles are assigned in strict precedence order: CAUSE (rank 1, only when the verdict is
   `ROOT_CAUSE_FOUND`) > SYMPTOM > ALSO_ABNORMAL > NORMAL. Java headline for that case:
   "No clear root cause found. The strongest signal is {service} ({score})."
   Reason: the old spec made rank 1 `CAUSE` unconditionally, so analysing a quiet window produced a
   confident accusation. The precedence order also removes the old overlap where a service satisfied
   both the SYMPTOM and the ALSO_ABNORMAL condition. `verdict` is stored as its own database column
   so reports can count these without parsing JSON.

10. **`PARE_LGBM` has a task: new M1.7b** ("PARE_LGBM engine (LightGBM dependency model) + test").
    Reason: the engine was in the `05` engine table and in experiment E2 but no task built it, so it
    would have been missed.

11. **The replay detector must not use `injectTime`.** Baseline = the first
    `app.replay.baseline-rows` rows of the case (new config key, default 300, replacing
    `baseline-min-rows: 60`). `injectTime` is used in the catalog only, to mark a case
    `replayable` when the injection happens after those baseline rows.
    One-click analyze and the offline experiments still split the normal window at
    `injectTime - normalGapSeconds`. This is the standard RCAEval protocol, applied identically to
    every method, and it is now written down as an explicit stated assumption in `03` section 4.2
    and `08` section 4, together with the E3 variant that avoids `inject_time` entirely.
    Reason: the live demo should be honest about detection - a real detector does not know when the
    fault starts. Offline scoring follows the benchmark so our numbers stay comparable with
    published ones. A unit test asserts the detector takes no `injectTime` argument at all, so the
    rule cannot be broken by accident later.

12. **`app.data-dir` comes from the environment variable `XAIRCA_DATA_DIR`**, default
    `${user.dir}/../data`, resolved to an absolute path at startup and logged on one line. The H2
    URL is built from it. Tests use in-memory H2 (`jdbc:h2:mem:`) and a temporary data dir. The
    `start-all` scripts `cd` into `backend/` first.
    Reason: the old literal `jdbc:h2:file:../data/db/xairca` only resolved correctly when Java was
    launched from `backend/`, and a wrong working directory would silently create a second empty
    database somewhere else.

### Minor

13. **`faithfulness_auc` removed from `cases.csv`.** E5 writes its own `faithfulness.csv` and
    `stability.csv` in the same run folder, with columns defined in `06` section 5. `cases.csv`
    gains a `verdict` column instead.
    Reason: the faithfulness data has a different shape (one row per case, method and k), so it was
    always going to be an empty column for every other experiment.

14. **`params.topK` (default 10) = how many indicators the response returns.** It is separate from
    `cp_top_k` (default 5), which is how many columns the change-point step inspects. Both are in
    the new PareConfig table in `05` section 1.1.
    Reason: the two were easy to confuse, and the example request said `topK: 5` while the UI shows
    a top-10 table.

15. **All windows are defined once, in a table in `05` section 3 step 2.** One-click analyze sends
    `recent = [alarm - 300 s, alarm + 120 s]`; change-point search is
    `[alarm - 300 s, alarm + min(60 s, available data)]`; analysis window is
    `[changePoint, changePoint + 120 s]`, cut to available data; replay sends only played rows.
    `03` and `08` refer to that table instead of repeating the numbers.
    Reason: the numbers appeared in three docs with slightly different wording (notably
    `cp_lookahead` 0 versus `recent-after-seconds` 120), which is how the two sides drift apart.

16. **No README inside `data/`.** The `data/` layout is described in the root `README.md`.
    Reason: `data/` is git-ignored, so a README there would never be committed. M0.1 was changed to
    say so explicitly.

### Build tooling

18. **Java builds use the Maven Wrapper (`./mvnw`), not a system Maven.** Maven is not installed on
    this machine and will not be: it is also not available through winget (only unrelated packages
    match `Apache.Maven`). The Spring Initializr zip already contains `mvnw`, `mvnw.cmd` and
    `.mvn/wrapper/maven-wrapper.properties`, and all three get committed. `PROJECT_RULES.md` section 6,
    `docs/02` section 4 and the definition of done now say `./mvnw`.
    Reason: the wrapper pins the exact Maven version in a committed file, which is what hard rule 10
    (reproducible) asks for, and it needs nothing on the machine but the JDK. It also avoids editing
    the user PATH.
    Consequence to remember at M8.1: the wrapper cannot be created with `mvn wrapper:wrapper`,
    because that needs the Maven we do not have. M8.1 must start from the Spring Initializr zip.
    Also done at the same time: `JAVA_HOME` was empty and is now set to
    `C:\Program Files\Java\jdk-21.0.12.1` (user-level), because some IDE Java tooling expects it
    even though the wrapper copes without it.

### Python environment

19. **Python 3.10.20 via `uv`, with the project venv at `analyzer/.venv`.** The system Python 3.14.4
    stays untouched and unused by this project.
    Reason: 3.14 cannot run the stack (see "Environment" for the wheel evidence), and `uv` installs
    a private 3.10 without admin rights, without touching PATH, and without disturbing the existing
    interpreter. `analyzer/.venv` sits next to the package it serves and is already covered by
    `.gitignore`.

20. **The analyzer libraries were installed now, one milestone before M1.1 declares them.**
    Installed and verified: numpy 2.2.6, pandas 2.3.3, scikit-learn 1.7.2, scipy 1.15.3,
    shap 0.49.1, lightgbm 4.7.0, ruptures 1.1.10, networkx 3.4.2, statsmodels 0.15.0,
    matplotlib 3.10.9, pyarrow 25.0.1, fastapi 0.142.2, uvicorn 0.54.0, pydantic 2.13.5,
    pytest 9.1.1, pyyaml 6.0.3, joblib 1.6.0, ruff 0.16.10 - exactly the versions the dry-run
    resolution predicted.
    Reason: it turns "the stack should work on 3.10" into a checked fact before we write code
    against it. M1.1 will declare these same packages in `analyzer/pyproject.toml`, where
    `pip install -e ".[dev]"` then finds them already satisfied. If a version here disagrees with
    what M1.1 pins, M1.1's pyproject wins.

### M1.1 choices

21. **`PareConfig` is a frozen dataclass with validation in `__post_init__`.**
    Reason: the ablation engines are variants of one config (`PARE_NO_CP` is
    `use_change_point=False`), and `with_changes()` on a frozen object gives that without any risk
    of an analysis changing its own settings halfway through. Validation turns a typo into an
    immediate clear error instead of a quietly strange result later.

22. **The camelCase conversion for `params` lives in `config.py`** as
    `PareConfig.from_api_params()`, and it is **mechanical**, not a hand-written table:
    `use_change_point` -> `useChangePoint`, `top_k` -> `topK`. Unknown keys raise.
    Reason: one tested function beats duplicating all 16 defaults again in `service/schemas.py` at
    M7.1, and a mechanical rule cannot drift the way a second list of names would. `06` section 3
    now records the rule so the Java side builds the same keys. A silently ignored `topk` typo is
    the kind of thing that costs an afternoon.

23. **`pyproject.toml` uses version floors, not exact pins, but caps Python at `<3.14`.**
    Reason: the cap is the valuable part, because it encodes the ruptures/shap/dowhy problem and
    makes a wrong-interpreter install fail immediately with a clear message. Exact pins would fight
    pip on any other machine for no benefit; the exact verified versions are recorded in
    "Environment" below, which is what reproducibility actually needs.

24. **No `guess_from_name` helper in `pare.columns`.**
    Reason: `05` section 2 forbids the algorithm parsing column names. Guessing is still needed, but
    it belongs to the experiment adapter (M2.3) and the Java upload helper, where a human checks the
    result before it is used. A test in `test_columns.py` locks the rule in by giving a column a name
    that looks nothing like its service and metric.

25. **`pip` was added to `analyzer/.venv` with `ensurepip`, rather than changing the documented
    command.** `uv venv` creates an environment without pip, so `pip install -e ".[dev]"` from
    `PROJECT_RULES.md` section 6 would not have run.
    Reason: the documented command should be the one that works for someone on a fresh clone with a
    plain `python -m venv`, who will have pip and may not have uv. M12.2 is a fresh-clone test, so
    the docs stay standard and the local venv was brought up to match. pip 26.2.1 and
    setuptools 84.0.0 are now in the venv.

### M1.2 choices

26. **A memory fault also ramps the culprit's own latency by `+2 * std`**, mirroring what the spec
    already does for cpu, so that memory faults reach callers at all. `05` section 5 now says this
    and explains why.
    Reason: `mem` is a local random walk with no dependency on callees, so without a latency term a
    memory fault would produce no symptoms anywhere. That would make MEM useless for E6, contradict
    this project's own motivating example ("cartservice memory leak, so frontend gets slow"), and
    behave unlike real RCAEval memory faults. The human asked for whichever option was best.

27. **`make_case` returns a frozen `SyntheticCase` dataclass, not the 5-tuple the spec lists.**
    Same contents plus `inject_time_sec`, `fault` and the `params` the case was built from.
    Reason: every consumer needs the injection time (the case format, `alarm_time = inject + delay`,
    the E6 delay sweep), and a named object documents itself where a 5-tuple does not. `to_frame()`
    gives the single continuous series the case format and `/v1/synthetic` need.

28. **`edges` is a list of `(caller, callee)` tuples, not a `CallGraph`.**
    Reason: `graph.py` is M1.4, after this task. Rather than reorder milestones or write a throwaway
    graph class, M1.2 returns plain pairs and `CallGraph.from_edges(edges)` consumes them from M1.4
    onward. The E6 graph-quality variants (drop 20 percent of edges, add 20 percent wrong ones, no
    graph) work directly on an edge list anyway.

29. **Two-pass construction with the random draws made once.** Pass one builds the series with no
    fault, only to measure each column's normal standard deviation; pass two rebuilds with the fault
    using the identical noise arrays.
    Reason: fault sizes are multiples of a column's normal spread, but the fault also has to flow up
    the graph, so the spread has to be measured before it is applied. Reusing the draws is what makes
    a seed reproduce bit for bit.

30. **The example figure defaults to a latency fault, not the memory fault.**
    Reason: honesty. With `--fault mem` the callers barely move on the chart, for the reason in open
    question 4. The latency figure shows what the generator genuinely does - cause jumps, caller
    follows, unrelated service flat. The memory version is still one flag away.

### M1.3 choices

31. **A column with no readings at all scores 0, not NaN.** `window_score` and `ecdf_tail_score`
    both turn an all-missing column into a score of zero.
    Reason: missing data is not evidence of a fault. Returning NaN would spread through a ranking and
    could knock out an entire result, and `05` section 6 requires every engine to return a valid
    result for a case that has NaN columns. The deliberate "All-NaN slice" warnings numpy raises are
    silenced at the point where they are expected, rather than left to train the reader to ignore
    warnings.

32. **Every scoring function takes either one column or a whole window** - shape `(n_rows,)` or
    `(n_rows, n_columns)` - and reduces down the rows.
    Reason: the engines work on a whole window at once for speed, while the tests and the spec talk
    about a single column. numpy's `axis=0` gives both from the same code, so there is no second
    implementation to keep in step.

### M1.4 choices

33. **A self-loop is dropped when a graph is built**, quietly, rather than kept or rejected.
    Reason: an edge `a -> a` would make a service its own child, and the dependency model would then
    predict a service from its own values. That is precisely the autoregressive leak `05` step 3
    forbids ("Do NOT use s's own past values"), and it would hide the very anomaly we are looking
    for. Rejecting outright would be worse, because inferred and trace-derived graphs throw up
    self-loops routinely and a case should not fail to analyse over one.

34. **`infer_from_correlation` decides direction by lag first, then by variance.** Link a pair if
    the best correlation over lags 0 to `max_lag` reaches a threshold; orient it by whichever
    ordering correlates more strongly, and when the two are within 0.02 of each other, treat the
    wider-varying service as the caller.
    Reason: the lag rule alone cannot work when propagation is effectively instantaneous, which is
    the case in our own synthetic data and often in real sampled metrics. The variance tie-breaker
    has a reason behind it rather than being arbitrary: a caller's response time contains its
    callee's plus its own work, so it varies at least as much. Measured, this gets direction right
    55 to 88 percent of the time against a known tree - better than chance, and deliberately still
    imperfect, since E4's whole job is to measure what an imperfect graph costs.

### M1.5 choices

35. **`ruptures.Binseg` is used with `jump=1`, not its default of 5.**
    Reason: the default only ever proposes breakpoints at multiples of 5, so the estimated start is
    rounded to the nearest 5 rows. Checked on the installed v1.1.10: for a change at index 102 the
    default answers 100 and `jump=1` answers 102. The analysis window is anchored on this number, so
    the resolution matters. The extra cost is trivial on a window of a few hundred rows.

36. **Flat and all-missing columns are filtered out before searching, and a column that cannot be
    searched is skipped rather than failing the analysis.**
    Reason: ruptures does not object to a flat line, it returns a confident split in the middle of
    the noise. Trusting that would be inventing a result, which hard rule 2 forbids. For the same
    reason `BadSegmentationParameters` on a too-short window is caught and treated as "this column
    has nothing to say", which is what it means.

37. **When no change point can be found, the alarm time is returned with `estimated=False` and a
    reason in plain words**, rather than silently returning the alarm time as though it had been
    measured.
    Reason: the difference matters to whoever reads the result. "The change started 60 s before the
    alarm" and "we could not tell, so we used the alarm" are different claims, and the explanation
    text and the warnings list need to be able to say which one happened.

### Settling open question 3

38. **The synthetic generator gains a non-linear congestion term, controlled by a new
    `amplification` parameter that defaults to 0.**

    The problem: with linear propagation a caller can never look worse than the service that broke,
    so the symptom trap the whole project is about could not occur in our own data. Raising the
    propagation weight scales the inherited signal and the inherited noise by the same factor and
    they cancel. Derived, then measured over 200 cases: the caller-to-culprit score ratio peaked at
    0.973 and never once reached 1.

    The fix, with a physical reason rather than a fudge: a caller does not add a scaled copy of its
    callee's delay. Queueing, retries, timeouts and pool saturation make it degrade out of all
    proportion once a callee passes a threshold, while leaving it calm below it. That asymmetry -
    loud during the fault, silent in normal operation - lifts the caller's deviation without widening
    its normal spread, which is exactly what is needed. So

        latency_s += amplification * own_scale_s * sum over callees k of max(0, z_k - 3)^2

    Squared, so it is negligible just past the threshold and severe well beyond. Exactly zero below
    the threshold, which is the essential part and is tested: if congestion fired during normal
    operation it would widen the caller's normal spread and cancel itself out.

    `amplification=0` reproduces the old model **bit for bit** - no new random draws were added - so
    every earlier result stays reproducible and the linear case remains available as a comparison.

    Measured, 30 seeds, 8 services, latency fault, propagation 0.9, top-1 accuracy. **Updated on
    2026-10-03 with the real `residual.py` from M1.6**; the first version of this table used a
    least-squares proxy and was too optimistic:

    | amplification | marginal scoring | residual scoring | rescued of trapped |
    |---|---|---|---|
    | 0.00 | 1.00 | 1.00 | none trapped |
    | 0.25 | 0.80 | **1.00** | 6 of 6 |
    | 0.50 | 0.43 | 0.53 | 3 of 17 |
    | 0.75 | 0.20 | 0.23 | 3 of 24 |
    | 1.00 | 0.03 | 0.07 | 2 of 29 |
    | 2.00 | 0.00 | 0.00 | 0 of 30 |

    **Three regimes, and the paper must report all three.** Below about 0.15 there is no trap and
    nothing can beat marginal scoring. **Around 0.25 is the useful band**: movement alone starts
    blaming callers while subtracting what the callees explain still recovers the culprit every
    time. From about 0.5 upward the advantage shrinks to a few points, and by 1.0 both methods have
    collapsed, because the non-linearity is dormant in the normal data and no model fitted on normal
    data can extrapolate it. That last regime is a real limit of metric-only root-cause analysis and
    belongs in threats to validity, not in an average that hides it.

    The band is narrower and lower than the proxy suggested, for a reason M1.6 then identified: ridge
    shrinkage leaves a symptom with a residual proportional to the size of the fault, so symptoms
    accumulate self-score as amplification rises. See the M1.6 log entry.

    The band is predicted by algebra, not just observed: a trap needs the congestion contribution to
    exceed `(S/w - sd_child) * D` and a residual method keeps working while it stays below `D`.

    **This also corrected a claim in two specs.** `08` said E6's story was that *strong propagation*
    makes marginal methods blame symptoms. That is false, and E6 built on it would have measured
    nothing. The factor is amplification, so E6 now sweeps it and the headline figure is AC@1 and
    symptom rate against amplification. `04`'s synthetic-lab hint told the user to turn up
    propagation and watch ordinary methods fail, which would simply not have happened; it now points
    at amplification and warns the presenter that above 0.7 neither method works, so that is not
    shown as a PARE failure.

### M1.7 choices

39. **`preprocess.py` was built as part of M1.7, although no task owned it.** It is in the `05`
    section 1 layout and is step 0 of the algorithm, but `07` never listed it, and `engine.py` cannot
    run without it. `07` now records that M1.7 covers it.
    Reason: the alternative was an engine that skips cleaning, which does not merely add noise - a
    column that is constant through the normal period has no spread, so any movement divides by
    almost nothing and scores enormously. A dead metric would win rankings.

40. **`nsigma_score` lives in `scores.py` and deliberately uses mean and standard deviation**, not
    the robust median and MAD that everything else uses.
    Reason: NSigma is the baseline this work is measured against, so it has to be the method as
    everyone else implements it. An improved version would flatter our results. Its weakness to
    outliers is part of what the comparison is meant to show. The Java fallback ranker mirrors this
    function exactly, so the shared-sample test in `03` section 4.4 can pass.

41. **`ColumnResidual` carries `metric` through from the column map**, rather than recovering it from
    the column name when building the indicator table.
    Reason: `pare.columns` forbids parsing meaning out of a column name, and a display table is not
    an exception - `payment-service` with a metric called `memory_working_set_bytes` would be split
    wrongly and shown wrongly. A test pins it.

42. **scikit-learn is imported at the top of `residual.py`; LightGBM stays lazily imported.**
    Reason: with both lazy, the first `analyze()` call in a process took 2.0 s against a 2 s budget,
    almost all of it the sklearn import, while later calls took 114 ms. For a long-running service a
    slow start-up is much better than a slow first request. LightGBM stays lazy because only one
    ablation uses it and importing it always would cost every other run a second for nothing.

### M1.7b result

43. **`PARE_LGBM` is kept as a registered engine even though it is measurably worse**, because a
    negative ablation that is reported is worth more than one that is quietly dropped.
    Measured: equal to `PARE` when there is no symptom trap, 5 points worse at amplification 0.25,
    15 points worse at 0.50, and about six times slower. The cause is that tree ensembles cannot
    extrapolate beyond the range they were trained on, so a caller whose callee has gone far outside
    normal is predicted at its normal level and keeps the whole inherited rise as its own residual.
    The paper can state plainly that residual-based root-cause analysis needs an extrapolating model,
    with a measurement behind it.

### M1.8 choices

44. **`service_agg` gained a `"sum"` option, and `marginal_score` is now aggregated the same way as
    `score`.** `SHAP_IFOREST` is specified to sum a service's per-column SHAP values, which no
    existing option did.
    Reason for the second half, which was a real bug: the two numbers sit side by side in the
    cause-versus-symptom chart, so a sum against a maximum would have shown a gap that does not
    exist, and it broke the contract line saying score equals marginalScore for engines without
    residuals. Noted in `rank.py` that summing rewards whichever service has the most metrics - that
    bias belongs to the baseline being reproduced, not to us.

45. **`KERNEL_SHAP_PCA` is not implemented and raises with the reason.** It is marked optional in
    `05` section 4.
    Reason: KernelSHAP over 50 background rows times every column times every abnormal row costs
    minutes per case where the other explainers cost milliseconds, and it answers the same question
    as `PCA_RECON`. Raising with an explanation is better than quietly omitting it from the registry,
    where its absence would look like an oversight.

46. **The baselines are kept deliberately un-improved.** None takes a call graph, none uses change
    point re-anchoring, and known weaknesses are left in place.
    Reason: contribution C1 is a claim about what current practice does. A baseline we had quietly
    improved would make PARE look better and the comparison worthless. A test asserts the explainer
    functions have nowhere to put a graph, so this cannot be eroded by a later edit.

### M1.9 choices

47. **Ties are scored as the expected hit rate under a shuffle of the tied group**, settling open
    question 4. A ground truth in a tie group of size `m` starting at rank `r` contributes
    `clip(k - r + 1, 0, m) / m` to AC@k.
    Reason: saturating methods produce real ties - `ECDF` cannot score above `log(n+1)`, so every
    column past the normal range gets the identical ceiling - and breaking them alphabetically makes
    the published accuracy depend on what the columns happen to be called. The expectation is the
    only answer that is neither optimistic nor pessimistic, and it collapses to the ordinary
    definition when scores are distinct. Measured effect: ECDF's indicator accuracy 0.13 -> 0.46,
    everything else unchanged. Stated in `08` section 4 because the paper has to disclose it.

48. **`symptom_rate` and `symptom_error` return None rather than 0 or False when the question does
    not apply** - no wrong answers to judge, or no graph to judge with.
    Reason: both zeros would be read as evidence. "0 percent symptom errors" sounds like a method
    that was tested against the trap and passed, when it was never tested; and False for "no graph"
    would quietly understate the measured symptom rate across a dataset. `06` section 5 already says
    these fields are empty in that case.

### M1.10 findings

49. **Rank is measured from the order an engine returned, not by re-sorting its scores**
    (`rank_in_order`). PARE's traversal deliberately promotes the service the graph walk ends at even
    when a caller scores higher, so re-deriving the rank marks it wrong exactly when the traversal
    did its job. This cost PARE 0.24 of apparent accuracy on cpu faults and failed the gate
    spuriously. `rank_of` is kept for scoring plain score maps.

50. **Baselines are denied the call graph entirely** (`EngineSpec.use_graph`). The traversal step
    lives in the shared ranking code and was running for every engine, so `NSIGMA`, `SHAP_IFOREST`,
    `ECDF` and `PCA_RECON` were using the graph without taking one as an argument.
    Reason: the comparison in the paper is only meaningful if the baselines are the methods as
    published. The old test checked the explainer functions' signatures, which is not the same thing
    as checking the engine; the new one is behavioural and compares the ranking with and without a
    graph.

51. **`PARE_NO_RESIDUAL` keeps the traversal.** The ablation removes the dependency model and nothing
    else, so the measured gap is attributable to that one change.
    Reason: an ablation that alters two things at once measures neither. Worth stating in the paper,
    because it means the +0.12 is the residual model's contribution on top of a graph-aware ranking,
    not the value of using a graph at all.

### Order of work

17. **Normal order: research first.** M0 -> M1 -> M2 ... The "application early" shortcut in
    `07_TASKS.md` is not taken.
    Reason (the human's): if the synthetic check in M1.10 or the first RE1 results in M3 do not
    support the cause-versus-symptom story, we need to know that **before** building an application
    around it. So M1.10 and M3.2 are explicit stop-and-report gates.

