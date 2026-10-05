# PROGRESS.md - Running log

Update this file at the end of every task. Newest entry at the top of "Log".
Human: read this before every session to know where things stand.

Order of this file: what is happening now, then the log of what was done (newest first), then
anything waiting on you, then the machine setup and the full list of decisions as reference.

## Current status
- Current milestone: M3 (E1 explanation grounding). **M3.1 is done and contribution C1 has its
  headline result.** Next is M3.2.
- Next task: M3.2, running E1 on the rest of RE1, which needs RE1-SS and RE1-TT downloaded (one system
  at a time, decision 66). **Nothing is blocked and there are no open questions left.**
- **C1's finding, which is a paper section on its own.** On 125 RE1-OB cases, explanations name the
  right *service* far more often than the right *metric*. Isolation Forest with TreeSHAP - the popular
  approach, and what GAL-MAD does - gets the service right 65% of the time and the metric right 24%, a
  41-point gap. And **64% of its wrong answers blame a service that calls the real culprit** (0.82 on
  DELAY faults, 0.86 on MEM). That is hypothesis H1 confirmed and RQ2 answered, on real data with real
  ground truth. It also costs 3.5 s per case against ECDF's 58 ms.
- **Where PARE actually stands on real data, which is the thing to know.** On RE1-OB at delay 0, with
  the real call graph: AC@1 **0.384**, Avg@5 0.528, against NSIGMA's **0.848**. PARE is less than half
  as accurate as the simplest baseline at naming the right service. The scaling defect found in M2.5 is
  fixed (question 9, which lifted it from 0.240), so what remains is a research problem in the residual
  step, not a bug. **This is the M3.2 gate arriving two tasks early**, which is exactly what it was put
  there for.
- **But the paper's central claim does land.** `symptom_rate` - the share of wrong answers that blamed
  a service calling the real culprit - is **0.2208 without the call graph and 0.0779 with it**, same
  engine, same cases. Nearly threefold. AC@1 is identical either way, so the graph is not making PARE
  right more often; it is making its mistakes far less likely to accuse a victim. That is RQ2, and
  `00_RESEARCH_PLAN.md` section 15 predicted this exact shape - claims should rest on grounding and
  symptom rate, not on coarse ranking.
- **Where to start M3's investigation.** PARE's AC@1 by fault type is MEM 0.600, DELAY 0.520, DISK
  0.440, LOSS 0.240, **CPU 0.120** - and CPU is where NSIGMA is strongest (0.96). A CPU fault is the
  easiest case there is, so PARE being worst precisely there points at the residual step misbehaving
  when the culprit's signal sits in a metric its callees do not propagate.
- All nine open questions are settled (decisions 38, 47, 53, 62 to 66, 72). The two items under
  "Things the human must check by hand" are judgement calls for you, and the call-graph one is ready
  for review now.
- Indicator scoring, now fixed: the **headline ExpAC@k is strict** (CPU and MEM only, where the right
  metric is not a judgement call); the loose definition is a secondary table, per fault type, with the
  acceptable-set size beside it. Strict and loose score the CPU and MEM cases identically, so the two
  numbers differ only in which cases they cover. `docs/08` section 4 is the rule.

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

### 2026-10-05 - M3.1 - E1, explanation grounding. Contribution C1 has its result.
- What was done: `experiments/run_c1_grounding.py` with `experiments/configs/c1_re1_ob.yaml`, plus
  `experiments/runner.py`, the shared core that every experiment runner from here on uses to turn an
  engine's answer into a row of `cases.csv`. Putting that in one place matters: with a copy per script
  there would eventually be several implementations of AC@k and no way to say which number the paper
  should print.
- **The headline finding, and it is the one contribution C1 was designed to test.** Explanations find
  the right *service* far more often than the right *metric*:

  | method | ExpAC@1 (indicator) | AC@1 (service) | gap | symptom rate | ms |
  |---|---|---|---|---|---|
  | SHAP_IFOREST | 0.240 | **0.648** | **0.408** | **0.636** | 3534 |
  | PCA_RECON | 0.300 | 0.592 | 0.292 | 0.216 | 83 |
  | PARE_NO_RESIDUAL | 0.200 | 0.384 | 0.184 | 0.221 | 480 |
  | ECDF | 0.242 | 0.268 | 0.026 | 0.194 | 58 |

  ExpAC@1 is the strict definition over the 50 CPU and MEM cases; AC@1 and the symptom rate are over
  all 125. **This is hypothesis H1 from the research plan, confirmed**: the method that looks best at
  naming the right service - Isolation Forest with TreeSHAP, the GAL-MAD-style approach - names the
  right *metric* only 24% of the time, a 41-point gap. An engineer told "the problem is in
  cartservice" is helped; one told "the problem is cartservice's request rate" when it is really the
  memory is sent the wrong way.
- **RQ2 is answered sharply, and it indicts the most popular method.** Of SHAP_IFOREST's 44 wrong
  answers, **28 blamed a service that calls the real culprit** - 64%, nearly two in three. Per fault
  type it is worse where the story matters most: **0.82 on DELAY** faults (14 of 17 wrong answers) and
  **0.86 on MEM** (6 of 7). A memory leak's symptoms are downstream latency, and SHAP blames them
  almost every time it is wrong. That is this project's motivating example, measured on real data.
- Cost, which the paper should state next to the accuracy: SHAP_IFOREST takes **3.5 s per case**
  against 58 ms for ECDF, about 60 times slower, for the worst symptom rate of the four.
- **A bug found and fixed, which changes numbers already written down.**
  `pare.eval_metrics.symptom_rate` divided by the wrong denominator. `symptom_error` returns False for
  two different outcomes - the answer was right, and the answer was wrong but the service blamed does
  not call the culprit - and the function treated "not False" as wrong, which left only the True
  values and made it return **1.0 whenever any symptom error existed at all**. One boolean cannot carry
  three outcomes, so the function now takes the correctness of each answer as a second argument.
  - **The test had been written to match the code rather than the spec**, and its own comment admitted
    the ambiguity before asserting 1.0. `docs/08` section 4 and the function's own docstring both say
    "symptom errors / wrong top-1", so with three wrong answers and two symptom errors the answer is
    2/3, not 1. Both the code and the test were wrong; the spec was right. Four tests now pin it,
    including one stating the property directly: a method right on 100 cases and wrong on 4, one of
    them a symptom error, has a symptom rate of 0.25 and not 0.01.
  - **Numbers corrected.** M2.5's and question 9's `symptom_rate` figures were computed over all 125
    cases instead of the wrong ones: **0.088 -> 0.2208** without the graph and **0.040 -> 0.0779** with
    it (and the later pair 0.136/0.048 likewise). Both entries above now carry the correction. The
    ratio happened to survive because both sides shared the same wrong denominator, so every
    conclusion drawn from them stands - but the figures were understated by about 1.6x and the
    `symptom_rate` column of the M1.10 gate summary was simply 1.0 wherever anything was wrong.
  - The M1.10 gate was re-run in full (798 s, all 8 engines) to regenerate that column. **It still
    passes**, and the re-run is a reproducibility check worth recording: of the 64 summary rows,
    **every accuracy number - ac1, ac3, avg5, exp_ac1, exp_ac3, no_clear_cause - came back identical**,
    and only `symptom_rate` changed. That independently confirms decision 72's claim that the
    flat-column fix cannot touch synthetic data, since no synthetic column is ever flat. The corrected
    rates are real fractions rather than 1.0: ECDF on cpu 0.25, ECDF on mem 0.167, PARE on mem 0.400.
    My own mistake on the way: the first regeneration attempt omitted `--append`, which dropped the
    other seven engines from `cases.csv`, so the full run was needed rather than a re-summarise.
- How it was tested (commands + result):
  - `analyzer/.venv/Scripts/python.exe experiments/run_c1_grounding.py --config
    experiments/configs/c1_re1_ob.yaml` -> 500 runs (4 methods x 125 cases), **0 failures**, results in
    `results/e1_re1_ob/`.
  - `pytest -q` in `analyzer/` -> **379 passed**. `pytest experiments/tests -q` -> **86 passed**
    (22 new). `ruff check .` -> clean.
  - A test asserts `CASES_CSV_COLUMNS` matches the column list in `docs/06` section 5 **by parsing the
    doc**, so the contract and the writer cannot drift apart silently.
  - A test intercepts the request on its way into the engine and checks it carries no ground truth
    (hard rule 4), and another checks a baseline returns the same answer with and without a graph, so
    the runner cannot hand a baseline the one thing the proposed method is supposed to contribute.
  - An engine made to raise produces a row with the error rather than a missing case.
- Two things the report now says in words, because both were briefly misread while building it:
  `wrong_top1` is `symptom_rate`'s denominator and can exceed `(1 - AC@1) x cases` for a method that
  ties; and `no_clear_cause` is **not comparable between methods**, because the rule is a fixed
  threshold of 3.0 on the rank-1 score and these methods do not share a scale - SHAP_IFOREST reports
  mean absolute SHAP, which is almost never above 3, so it reads `NO_CLEAR_CAUSE` on all 125 cases
  while ranking services better than anything else.
- Files changed: new `experiments/run_c1_grounding.py`, `experiments/runner.py`,
  `experiments/configs/c1_re1_ob.yaml`, `experiments/tests/test_runner.py`,
  `experiments/results/e1_re1_ob/*`; `analyzer/pare/eval_metrics.py` (the `symptom_rate` fix),
  `analyzer/tests/test_eval_metrics.py`, `analyzer/scripts/synthetic_check.py`,
  `experiments/check_graph.py`, `experiments/results/synthetic_check/*`, `docs/07_TASKS.md`,
  `PROGRESS.md`.
- Left open / next: M3.2, running E1 on the rest of RE1, which needs RE1-SS and RE1-TT downloaded.
  Note the disk policy in decision 66: one system at a time.

### 2026-10-05 - settling open question 9. PARE 0.240 -> 0.384, and the symptom claim lands.
The last open question, raised by M2.5 the same day. There are now none.

- **The decision: when a column's MAD is 0 but the column is not constant, score it on its standard
  deviation.** One change, in `pare.scores.robust_baseline`, which is the only place the epsilon rule
  lives. Decision 72. The epsilon was written to stop a division by zero and had been quietly setting
  the scale instead; this is a repair of intent, not a special case.
- **Chosen on principle, not on the score, because the scores did not separate the options.** All four
  were measured on all 125 cases across four engines:

  | option | PARE AC@1 | PARE Avg@5 | PARE_NO_RESIDUAL AC@1 |
  |---|---|---|---|
  | as the spec said | 0.240 | 0.410 | 0.224 |
  | **(a) standard deviation when MAD is 0** | **0.384** | **0.528** | 0.384 |
  | (b) drop the column | 0.400 | 0.544 | 0.400 |
  | (c) epsilon from the standard deviation | 0.280 | 0.427 | 0.264 |

  (c) is the weakest and was dropped. (a) and (b) differ by **two cases in 125**, which decides
  nothing, so the choice turned on what each does when it is wrong. (b) removes the column before
  ranking, so it can silently discard the right answer; (a) at worst scores it less robustly, which is
  visible and bounded. A metric flat while nothing is wrong and then climbing is exactly a memory
  leak - this project's own motivating example - and `mem` is the most common flat column in the data
  (195 occurrences). Measured for completeness: the ground-truth indicator is **never** a flat column
  anywhere in RE1-OB, so (b) would cost nothing *on this dataset*; that is luck, not a guarantee, and
  the application accepts user-uploaded CSVs.
  `ECDF` and `PCA_RECON` are unaffected by (a) and (c), since neither uses a robust scale. They gain
  about 1.5 points under (b) purely from having fewer columns to rank.
- **What it bought, and what it did not.** PARE's AC@1 on RE1-OB goes 0.240 -> **0.384**, Avg@5
  0.410 -> **0.528**, `NO_CLEAR_CAUSE` 41 -> 39. PARE is still well short of NSIGMA's 0.848, so the
  third item in the M2.5 diagnosis stands: something in the residual step is wrong, and that is M3's
  question. This fixed the part that was a scaling defect, not the part that is a research problem.
- **The symptom claim now lands clearly, which is the better news.** `symptom_rate`, the share of
  wrong top-1 answers that blamed a service calling the real culprit, on the same cases and the same
  engine, differing only in whether the call graph was supplied: ~~0.136 without the graph, 0.048 with
  it~~ **corrected on 2026-10-05 to 0.2208 without the graph and 0.0779 with it** - the denominator was
  wrong, see the M3.1 entry. A 2.8-fold reduction; the conclusion is unchanged and the figures are
  larger. This is RQ2, measured on real data, and it is the paper's
  central claim rather than a side effect. Note that AC@1 is *identical* (0.384) with and without the
  graph - the graph is not making PARE pick the right service more often, it is making its mistakes
  much less likely to be a victim. `00_RESEARCH_PLAN.md` section 15 anticipated exactly this shape of
  result and said the claims should rest on grounding and symptom rate rather than on coarse ranking.
- **A pointer for M3, from the per-fault breakdown.** PARE's AC@1 by fault type is now MEM 0.600,
  DELAY 0.520, DISK 0.440, LOSS 0.240, **CPU 0.120** - and CPU is the fault type NSIGMA handles best
  (0.96). A CPU fault is the easiest case there is: the broken service's `cpu` rises and its callers'
  latency follows. PARE being worst exactly there is a strong hint that the residual step is actively
  harmful when the culprit's own signal is in a metric its callees do not propagate. Worth starting
  M3's investigation from.
- How it was tested (commands + result):
  - `pytest -q` in `analyzer/` -> **377 passed** (6 new). `pytest experiments/tests -q` -> 62 passed.
    `ruff check .` -> clean.
  - **Nothing that should have moved, moved.** All 371 pre-existing analyzer tests pass untouched, and
    a test asserts that any column with a non-zero MAD keeps exactly the scale it had, so no result
    produced before today changes. The synthetic generator cannot produce a flat column - every
    synthetic metric carries continuous noise - which is both why M1 never saw the defect and why M1's
    numbers are unaffected.
  - `run_m24_compare.py` re-run: **every M2.4 number is byte-identical**, as it must be, since NSIGMA
    and both RCAEval baselines use mean and standard deviation and never touch a robust scale. A useful
    check that the fix did not quietly move the baseline the comparison rests on.
  - `check_graph.py` re-run; `results/m2_5/` now holds the post-fix numbers. The pre-fix ones are in
    the M2.5 log entry below and in the summary committed with that task.
- Files changed: `analyzer/pare/scores.py` (the rule, and `RobustBaseline.used_std`),
  `analyzer/pare/engine.py` (reports the affected columns in `warnings`),
  `analyzer/tests/test_scores.py`, `docs/05_PYTHON_ANALYZER_SPEC.md` (section 3 steps 1 and 3),
  `docs/03_JAVA_BACKEND_SPEC.md` (section 4.7, so the Java detector inherits the same rule),
  `experiments/results/m2_5/*`, `PROGRESS.md`.
- Left open / next: M3.1. No open questions remain.

### 2026-10-05 - M2.5 - the static call graphs. M2 is done. And a bad surprise about PARE.
- What was done: `experiments/graphs/online-boutique.yaml` and `sock-shop.yaml`, a loader and
  validator in `experiments/adapters/graphs.py`, and `experiments/check_graph.py` which checks a graph
  against the data and measures what it changes. 15 edges each.
- **No edge was taken from an architecture diagram.** Online Boutique declares its dependencies as
  `*_ADDR` environment variables in its Kubernetes manifest, so the graph is a parse of that file, not
  a reading of a picture. Pinned to **v0.7.0**, released 2023-05-19, because every RE1-OB case was
  injected in the week of 2023-05-28 - that is the version that was running. Checked rather than
  assumed: v0.8.0 extracts an identical edge list, and today's v0.10.7 differs only by adding
  `frontend -> shoppingassistantservice`, a service that appears in no column of the data. So the
  topology does not depend on the version choice.
  Sock Shop has no such declaration - services hard-code each other's DNS names - so each of its 15
  edges was read out of a specific source file, and the file records which. Two are easy to miss and
  are written up in full: `orders -> user` and `orders -> carts` happen because `OrdersController`
  fetches the customer, address, card and items **URLs it receives in the request body**, and
  `front-end/api/orders/index.js` fills those from its own `user` and `carts` endpoints. No hostname
  appears in the orders source, but the calls are real.
- **The rename that would have silently broken everything.** RE1-OB calls the `redis-cart` Deployment
  `redis`. A graph keeping the manifest's spelling loads without complaint, matches nothing, and
  leaves PARE running as a plain robust-z method while appearing to use a graph. That is why
  `validate_against_cases` exists and why `check_graph.py` refuses to measure a graph that does not
  match the data; a test pins it.
  The validator earned its keep immediately: its first run failed on `carts`, `catalogue`, `orders` and
  `front-end`, which are the Sock Shop columns M2.2 found contaminating one RE1-OB case. The adapter
  already drops them, so the check was asking the wrong question - it now filters by the same
  allowlist the adapter uses, so it compares the graph against what the engine really sees.
- How it was tested (commands + result):
  - `pytest experiments/tests -q` -> **62 passed** (15 new). `ruff check .` -> clean.
  - `analyzer/.venv/Scripts/python.exe experiments/check_graph.py` -> results in `results/m2_5/`.
  - **The graph is reaching the engine**, which is the question accuracy cannot answer: the service
    ranking differs from the no-graph run on **124 of 125** cases, some service has a non-zero
    inherited fraction on **112 of 125** with the graph and **0 of 125** without it (which is forced -
    without residuals the fraction is 0 by construction), and 20 cases produce at least one `SYMPTOM`
    role, a verdict unreachable without a graph.
  - The first `symptom_rate` the project has been able to compute at all, since the metric needs a
    graph to ask "is the service we blamed an ancestor of the real cause": ~~0.088 without the graph,
    0.040 with it~~ - **corrected on 2026-10-05 to 0.2208 and 0.0779**, because the denominator was
    wrong (see the M3.1 entry). The direction the paper predicts, on real data, and by a wider margin
    than first reported.
- **The bad surprise, and it is the important part of this entry. PARE on RE1-OB is far worse than
  NSIGMA.** AC@1 0.240 against NSIGMA's 0.848 from M2.4, on the same 125 cases at the same delay, with
  41 of 125 coming back `NO_CLEAR_CAUSE`. This is not the graph's fault - the graph is verified above -
  and it is not something to discover during M3.
  Diagnosed as far as M2.5 can without changing the method:
  1. **A preprocessing rule in `docs/05` step 0 is wrong for real data.** It drops a column when
     "MAD == 0 **and** std == 0", so a column that is flat for most of the normal period but not
     entirely flat survives with MAD == 0. Its robust scale is then the epsilon guard, about 1e-6, and
     a modest move scores in the millions: one case ranks `paymentservice_load` first with a score of
     4,000,000. Measured: **108 such columns across 40 cases** (~2.7 per case; mem 61, error 24,
     latency 15, load 8), and **the rank-1 column has MAD == 0 in 34 of 125 cases**. Dropping those
     columns before the engine lifts AC@1 from **0.240 to 0.400** and Avg@5 from 0.410 to 0.544. The
     synthetic data cannot produce this, which is why M1 never saw it: every synthetic column has
     continuous noise.
  2. **The traversal step is not the problem - it is helping.** Suspected because it promotes the
     service a graph walk ends at even when another scores higher, and one case does rank a service
     with a score of 1.3 above one at 1194. But measured both ways it is clearly positive: with the
     flat columns dropped, AC@1 is 0.400 with traversal and 0.248 without.
  3. **Something in the residual step itself is still wrong.** Even at 0.400 PARE is less than half as
     accurate as NSIGMA. Ridge fitted on normal data and asked to extrapolate through an incident is
     the obvious suspect, and `docs/05` section 3 already documents two measured limits of exactly
     that kind. This is the real question and it belongs to M3.
  Nothing in `pare` was changed for this task: the fix in (1) is a change to the method's specified
  behaviour, it affects every experiment, and it is the human's call. Recorded as open question 9.
- Worth saying plainly: **this is the M3.2 gate doing its job early.** `07` sets up M3.2 as a
  stop-and-report point precisely to catch "PARE does not work on real data" before an application is
  built on it, and the first real measurement has arrived two tasks ahead of schedule. The research
  plan's own safety net (section 9, the minimum viable paper) covers this case, and contribution C1 -
  measuring whether explanations point at causes - does not depend on PARE winning.
- Files changed: new `experiments/graphs/online-boutique.yaml`, `experiments/graphs/sock-shop.yaml`,
  `experiments/adapters/graphs.py`, `experiments/check_graph.py`,
  `experiments/tests/test_graphs.py`, `experiments/results/m2_5/*`; `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: open question 9 needs an answer before M3.1, because every E1 and E2 number
  depends on it. M2 is complete.

### 2026-10-05 - settling open questions 5, 6, 7 and 8. None are left.
No new milestone: this closes the four questions that were waiting on a decision. Full reasoning in
decisions 62 to 66; the headlines and the measurements that drove them are here.

- **Question 6, the indicator ground truth for DISK, DELAY and LOSS.** Settled as the recommendation
  already proposed - strict headline, loose secondary - but with the piece that was missing from it.
  The worry was that the strict number (0.92) is higher than the loose one (0.784) and so looks
  cherry-picked. It is not, and this is checkable: CPU and MEM each accept exactly **one** metric, so
  strict and loose score those 50 cases identically. Verified on all 350 scored rows of the M2.4 run,
  and pinned by three tests. The gap is therefore purely which cases are included, not how any case is
  scored.
  The loose number is now reported **per fault type with the acceptable-set size beside it**, because
  pooling averages a 1-of-51 question with a 4-of-51 one: CPU 0.96 (1 acceptable metric), MEM 0.88 (1),
  DELAY 0.88 (3), DISK 0.80 (4), LOSS 0.40 (3). The pooled value stays in `summary.csv` and the printed
  table now says in words not to quote it.
  `docs/06` section 5 gained `rank_gt_indicator_loose` and `tied_gt_indicator_loose` - a deliberate
  contract change with the doc and the only writer updated together, as hard rule 6 requires. The
  loose columns were removed from `indicator_scoring.csv` so the number exists in one place.
- **Question 5, the strength of the synthetic memory fault.** The observation was right, the original
  figure was for half a window, and the cause is simpler than it looked: `8 * std` is the ramp's
  **peak at the final abnormal row**, while every score in the project is a **median** over a window,
  and the median of a linear ramp is half its peak. Measured: **4.0 stds** over a 120-row abnormal
  period, **2.4** at the M1.10 gate's 200 rows. So the discrepancy was in the spec's wording, not in
  the behaviour, and `docs/05` section 5 now carries both numbers and the table.
  Nothing changed in the generator and `min_cause_score` stays 3.0. With `PARE`, 30 seeds,
  `n_abnormal=120`, no delay: culprit score median 5.12, minimum 2.36, and 3 of 30 cases
  `NO_CLEAR_CAUSE`. For contrast, the step faults never refuse - median culprit score 15.4 cpu,
  7.6 latency, 7.5 error. Refusing to accuse a service on 2.4 MADs is exactly what the parameter is
  for; making MEM louder would flatter the method and invalidate every synthetic result so far.
  The measurement did turn up a second, real problem: because the ramp peaks at the last abnormal row,
  **the fault's effective size depends on `n_abnormal`**, so two runs differing only in run length do
  not inject the same fault. Handled as a stated constraint on E6 (`docs/08` section 4 holds
  `n_abnormal` fixed across compared settings) rather than a new parameter, since E6 varies six
  factors and `n_abnormal` is not one of them. Four tests pin it, including two showing cpu, latency
  and error do **not** share the dependence.
  Also written down, because it is easy to get backwards: `AC@k` scores the ranking, which is returned
  even under `NO_CLEAR_CAUSE`, so a case can count as a hit although the application would have shown
  the user no accusation. The refusal rate must be reported next to `AC@k`, never folded into it.
- **Question 8, the result files the repository tracks.** `.gitignore` now does what `docs/08` section
  1 always said: the small per-run files are tracked (`summary*.csv` 788 B, `comparison.txt` 2.4 KB,
  `agreement.txt`, `config*.json`, `env-*.txt`) and the per-case ones are not (`cases.csv` 137 KB,
  `indicator_scoring.csv`, `*.jsonl` 384 KB). The churn objection does not survive those sizes. One
  `.gitignore` subtlety was needed and is commented in the file: un-ignoring a run folder re-exposes
  all of its contents, so they are re-ignored by `experiments/results/*/*` before the small files are
  allowed back. Verified file by file with `git check-ignore`. This also brings M1.10's
  `synthetic_check/summary.csv` into the repository, which is the intended effect.
- **Question 7, disk space.** Closed by measuring rather than deciding. **23.4 GB free** of 237.7 GB;
  the project occupies about 1 GB in total (`analyzer/.venv` 663 MB, `.venv-rcaeval` 136 MB,
  `data/RCAEval` 168 MB). RE1 was never a risk. Standing policy: one RCAEval system on disk at a time,
  delete before downloading the next, and re-check free space before any RE2 or RE3 download, those
  being the only items that carry logs and traces.
- How it was tested (commands + result):
  - `pytest -q` in `analyzer/` -> **371 passed** (4 new, the memory-ramp tests).
  - `pytest experiments/tests -q` -> **47 passed** (3 new, the strict-versus-loose checks).
  - `analyzer/.venv/Scripts/python.exe experiments/run_m24_compare.py` re-run: every accuracy number
    unchanged, `cases.csv` now carrying the two loose columns, `summary_by_fault.csv` carrying the
    per-fault indicator table. `ruff check .` -> clean.
  - `git check-ignore` run over ten paths to confirm the tracked and untracked sets are exactly as
    intended.
- Files changed: `docs/05_PYTHON_ANALYZER_SPEC.md` (what a memory fault is actually worth),
  `docs/06_DATA_CONTRACTS.md` (section 5 gains the two loose columns),
  `docs/08_EXPERIMENTS_SPEC.md` (which indicator counts as correct; the E6 constraints; the
  ground-truth note in section 3), `.gitignore`, `analyzer/tests/test_synthetic.py`,
  `experiments/run_m24_compare.py`, `experiments/tests/test_m24_compare.py`, `PROGRESS.md`.
- Left open / next: M2.5, the static call graphs. Nothing is blocked.

### 2026-10-05 - M2.4 - reproducing their NSigma and BARO, and accounting for the difference
- What was done: two scripts, because the two environments cannot be joined.
  `experiments/run_rcaeval_baselines.py` runs in `.venv-rcaeval` and calls RCAEval's own `nsigma`
  and `baro` on all 125 RE1-OB cases, recording the ranking each produced to
  `results/m2_4/rcaeval_rankings.jsonl`. `experiments/run_m24_compare.py` runs in the analyzer
  environment, scores those rankings, runs our `NSIGMA`, and attributes the difference.
  `experiments/baseline_formulas.py` holds a re-implementation of their two formulas so that one
  thing at a time can be changed between their setup and ours.
- **The reproduction succeeded, and ours scores higher.** AC@1 over 125 cases: their NSigma 0.728,
  their BARO 0.720, our NSIGMA **0.848**. Avg@5 0.8816 / 0.8784 / 0.9344. Indicator accuracy on the
  50 CPU and MEM cases where the ground truth is unambiguous: 0.74 / 0.66 / **0.92**.
- The gap is not reported as a mystery. Changing one thing at a time from their setup to ours:

  | step | AC@1 | ExpAC@1 |
  |---|---|---|
  | start: RCAEval NSigma, reproduced | 0.728 | 0.740 |
  | + formula: their signed max of per-row z -> our shift of the window mean | +0.104 | +0.180 |
  | + windows: the 30 s gap, and an abnormal window ending 120 s after the alarm | +0.016 | +0.000 |
  | + candidates: their `preprocess` -> our cleaning and service allowlist | +0.000 | +0.000 |
  | end: our NSIGMA | 0.848 | 0.920 |

  So **almost all of it is the formula**, and the window and candidate-set differences are nearly
  free. Their score for a column is `max` over the abnormal rows of its z-score; ours is the shift
  of the window's median-free mean. One unusual row is enough to put a column first for them, which
  is what the extra 10 points of AC@1 and 18 points of indicator accuracy are made of. This is the
  answer to M2's "done when": the difference is explained, and it is explained by one line of their
  source.
- How it was tested (commands + result):
  - `experiments/.venv-rcaeval/Scripts/python.exe experiments/run_rcaeval_baselines.py` -> 250
    rankings, 0 failures, about 25 s.
  - `analyzer/.venv/Scripts/python.exe experiments/run_m24_compare.py` -> the tables above, saved to
    `results/m2_4/comparison.txt`, `summary.csv`, `summary_by_fault.csv`, `cases.csv`.
  - `pytest experiments/tests -q` -> **44 passed** (24 new). `pytest -q` in `analyzer/` ->
    **367 passed**. `ruff check .` -> clean.
  - **The re-implementation is checked, not trusted.** Cell `A_theirs` reproduces their package's
    own top-1 on **125 of 125** cases and the entire ranking on 124 of 125, and every accuracy number
    it produces is identical to theirs to four decimal places. Cell `D_ours` reproduces our engine's
    full ranking on 125 of 125. Without both of those the attribution above would be worthless, so
    the script prints them before anything else.
  - The 125-vs-124 case is explained below; it is not an error in the re-implementation.
- **Three findings about the baseline, all of which belong in the paper.**
  1. **Their sort is broken when any score is NaN, and on RE1-OB it happens on 4 of 125 cases.**
     A column with no valid rows in one window scores NaN. Their ranking is
     `sorted(pairs, key=score, reverse=True)`, and every comparison with NaN is False, so the sort
     has no valid ordering and returns a list in which even the real scores are misplaced
     (`their_sort(["a","b","c"], [1.0, nan, 5.0])` returns `["a","b","c"]`; `c` scores 5 and comes
     last). On two cases this puts `frontend_error` - which has **zero** readings in the whole
     normal window - in first place. Their `drop_constant` cannot remove it, because `NaN != NaN`
     means an all-NaN column never looks constant. Reproduced rather than repaired: it is how the
     published ranking is produced, and the four cases are counted in `summary.csv`
     (`cases_with_nan_score`).
  2. **Both methods are signed, not absolute.** `max(zscores)`, not `max(|zscores|)`, so a fault
     that *reduces* a metric is invisible to them. Ours takes the absolute shift. Not a factor on
     RE1-OB, but a limitation to state rather than discover later.
  3. **`convert_mem_mb` cannot change their answer.** Both their scalers are scale-invariant, so
     dividing a memory column by 1e6 leaves every z-score untouched. Kept in the faithful path
     anyway, and worth knowing before anyone reads significance into it.
- **Where ours is worse, which the honesty checklist requires.** Per fault type, AC@1, theirs then
  ours: CPU 0.68 -> 0.96, DISK 0.64 -> 0.92, MEM 0.96 -> 1.00, LOSS 0.40 -> 0.48, but
  **DELAY 0.96 -> 0.88**. Delay faults are the one place their `max` wins, and it is the mechanism
  you would expect: an injected network delay shows up as latency spikes, which a maximum catches
  and a window mean dilutes. Both steps of the ladder cost DELAY a little (0.96 -> 0.92 on the
  formula, 0.92 -> 0.88 on the window).
  LOSS is poor for everyone (0.40 to 0.48), which is hypothesis H4 in the research plan arriving on
  schedule: network faults stay hard for metric-only methods.
- **The improvement is not noise.** Paired over the 125 cases: 86 both right, 14 both wrong, 20 where
  only ours is right, 5 where only theirs is. McNemar exact test on the 25 disagreements,
  **p = 0.0041**. Four of the 5 cases theirs wins are DELAY or DISK. (The paper's full statistics
  are M4.4; this is one descriptive number about the pair M2.4 is about.)
- Also found and fixed: `pare.scores._quiet_all_nan` silenced two of the three warnings numpy
  raises for a column with no readings but not `np.nanstd`'s "Degrees of freedom <= 0". Nothing had
  fed `nsigma_score` such a column before, because our own preprocessing drops it; the ladder does,
  on purpose, by scoring our formula over their candidate set. No score changes - the result was
  already mapped to 0 - but a 125-case run printed hundreds of lines of warning noise. One filter
  added, with the reason.
- Note on what M2.4 does **not** claim: BARO here is RCAEval's `baro` function, which is the ranking
  half of the BARO paper. The other half, multivariate Bayesian online change-point detection, finds
  the incident time, and the benchmark hands every method the injection time instead, so that half
  never runs. The paper must say this rather than claim to have evaluated all of BARO.
- Files changed: new `experiments/run_rcaeval_baselines.py`, `experiments/run_m24_compare.py`,
  `experiments/baseline_formulas.py`, `experiments/tests/test_baseline_formulas.py`,
  `experiments/tests/test_m24_compare.py`, `experiments/results/m2_4/*`;
  `analyzer/pare/scores.py` (one warning filter), `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M2.5, the static call graphs. Open question 6 is now quantified (14 points
  between the strict and loose indicator definitions) and still needs the human's ruling.

### 2026-10-05 - M2.3 - the RCAEval adapter
- What was done: `experiments/adapters/rcaeval.py` with `list_cases()` and `load_case()`, returning
  the `Case` and `CaseData` shapes `08` section 3 specifies. It is the only place that knows what an
  RCAEval folder looks like; everything downstream sees a `Case` and never a CSV.
  - It **does not import RCAEval**. The data is plain CSV, so reading it needs only pandas, and
    keeping the dependency out means the experiments run in the analyzer environment next to `pare`
    rather than in the separate RCAEval one - which matters, because the two cannot share an
    environment (RCAEval pins numpy 1.x, the analyzer uses 2.x). Only the download script and the
    M2.4 baseline comparison need RCAEval itself. Decision 55.
  - The three M2.2 findings are handled: the duplicate `time` column is dropped, no schema is
    assumed, and columns whose service is not in an explicit allowlist for the system are removed and
    reported. No rate conversion, since M2.2 established there are no counters.
  - `normal_mode` supports both the standard protocol (`inject_gap`) and the honest variant
    (`alarm_lookback`) that `08` section 4 asks E3 to report alongside, so the comparison is a flag
    rather than a second code path written later.
- On ground truth, the adapter records rather than guesses: `gt_indicator` is set only for CPU and
  MEM, where M2.2 measured an unambiguous answer, and is **None** for DISK, DELAY and LOSS.
  `acceptable_indicators` always carries the full set. An experiment must therefore choose the strict
  or the loose definition explicitly, which is what open question 6 is about - the adapter cannot
  quietly pick one.
- How it was tested (commands + result):
  - `pytest experiments/tests -q` -> **20 passed**. They skip cleanly when the data is absent, so a
    fresh clone does not fail its test run for want of a 175 MB download.
  - `list_cases` finds **125 cases**, 25 per fault type, 25 per broken service, with 50 having an
    unambiguous indicator - exactly the M2.2 counts.
  - Three cases are loaded as the task asks, chosen at index 0, 60 and 124 so that both collection
    batches are covered.
  - The M2.2 findings are pinned as tests rather than left as prose: the duplicate `time` column is
    gone, every column maps to a known service, and the contaminated case comes back with its nine
    foreign columns removed and a warning saying so, while still keeping its own.
  - End to end: a loaded case drives `analyze()` and produces a finite ranking.
  - A test asserts the frames and column map an engine receives carry no hint of the answer
    (hard rule 4) - ground truth lives on the `Case`, which the engine never sees.
- A note on what the first end-to-end run showed, which is **not** a result: on one case PARE missed
  and NSIGMA hit. That is expected and uninteresting at this point - **no call graph exists yet**, so
  PARE has nothing to subtract and is just a robust-z method with a re-anchored window. The graph
  arrives in M2.5, and until then PARE should not be expected to beat a marginal method on real data.
- Also added: a `ruff.toml` at the repository root, with the same rules as `analyzer/pyproject.toml`.
  `experiments/` was outside the analyzer's config and so was being linted by a different standard,
  which is how two findings appeared only when it was checked by hand.
- Files changed: new `experiments/adapters/rcaeval.py`, `experiments/adapters/__init__.py`,
  `experiments/tests/test_rcaeval_adapter.py`, `experiments/conftest.py`, `ruff.toml`;
  `PROJECT_RULES.md` (section 6 now gives the command for the experiment tests), `docs/07_TASKS.md`,
  `PROGRESS.md`.
- Left open / next: M2.4, reproducing RCAEval's own NSigma and BARO and checking ours agrees.

### 2026-10-04 - M2.2 - what is actually inside RE1 Online Boutique
No code was written. This is the inspection `07` M2.2 asks for, recorded before the adapter is built.

**Folder layout.** `data/RCAEval/RE1/RE1-OB/{service}_{faulttype}/{run}/`, 25 fault folders x 5 runs
= **125 cases**. 5 services are broken (`adservice`, `cartservice`, `checkoutservice`,
`currencyservice`, `productcatalogservice`) x 5 fault types (`cpu`, `delay`, `disk`, `loss`, `mem`).
Each run folder holds `data.csv` and `inject_time.txt`.

**`inject_time.txt`** is a bare epoch-seconds integer, 10 digits, no trailing newline, for example
`1685202688`. Nothing else is in the file.

**`data.csv`** has a `time` column in epoch seconds at exactly 1-second steps, no gaps.

**The `time` column appears twice.** Columns 1 and 48 are both called `time`; pandas renames the
second to `time.1`. They are identical values. The adapter must drop the duplicate rather than treat
it as a metric - it is the single most likely cause of a confusing bug here.

**Column names** are `{service}_{metric}`, splitting at the **last** underscore. Service names
contain hyphens (`frontend-external`, `front-end`) but no underscores, so the split is safe. The
metric vocabulary across all cases is: `cpu`, `mem`, `load`, `latency`, `latency-50`, `latency-90`,
`workload`, `error`. **There is no `disk` metric and no `loss` metric anywhere**, which matters for
ground truth below.

**Two collection batches, and the split is perfectly systematic by fault type:**

| fault types | rows per case | columns | percentile latency columns |
|---|---|---|---|
| `cpu`, `mem` | 4201 | 51 | **no** (0 of 50 cases) |
| `delay`, `disk`, `loss` | 721 | 57 to 60 | **yes** (75 of 75 cases) |

So a method that relies on `latency-90` can only be compared across the three fault types that have
it. This was not obvious and would have produced a confusing partial-coverage result later.

**Column sets are not uniform.** There are **15 distinct column sets** across the 125 cases, and only
**25 columns appear in every case** - the `cpu` and `mem` columns of 12 services, plus `time`. The
adapter must not assume a fixed schema.

**One case is contaminated.** `productcatalogservice_cpu/3` carries the full Online Boutique column
set **plus five stray Sock Shop columns** (`carts`, `catalogue`, `orders`, `front-end`,
`InboundPassthroughClusterIpv4`) - a collection artefact, not mislabelled data. The case is still
usable because its ground-truth service and column are present, but the adapter should restrict
columns to the known services of the system and record what it dropped, or those five services would
be ranked as candidates and could produce a false positive. `cartservice_disk/3` similarly carries a
stray `frontend-check` column.

**No cumulative counters.** `08` section 3 says to convert counters to rates if any exist. A first
check appeared to find four, but that check was wrong - it counted **constant** columns as
non-decreasing. On re-examination those columns are all-zero (`frontend_error`,
`PassthroughCluster_error`, `PassthroughCluster_load` are flat zero in many cases). The only
genuinely rising column is `main_mem`, in 3 of 8 sampled cases, and that is a memory figure drifting
upward rather than an accumulating counter; converting it to a rate would be wrong. **Conclusion: no
rate conversion is needed for RE1-OB.**

**Inject time sits exactly at the midpoint** of every case - 2100 normal rows before it for the
4201-row cases, 360 for the 721-row ones. Every case has at least 360 rows before the injection and
361 after, so none is too short to learn a baseline from; **0 of 125 cases** have fewer than 60
normal rows.

**Ground truth.** The root-cause **service** is the folder-name prefix and is unambiguous. The
root-cause **indicator** is not, and `08` section 3's first instruction cannot be followed: RCAEval's
own fine-grained ground truth is **not in the installed package**. Its `Evaluator` compares
`Node(entity, metric)` objects and scores fine-grained accuracy as `answer in ranks[:k]`, but the
code that builds the answer node for a case is not shipped in the wheel. So the mapping is ours to
choose and to declare. What the data shows, and the three options, are written up as **open question
6**; CPU and MEM are settled by the evidence, DISK, DELAY and LOSS are not.

- Files changed: `docs/07_TASKS.md`, `PROGRESS.md`. No code, by design.
- Left open / next: M2.3, the adapter. It can be written now - only the indicator-level scoring waits
  on open question 6.

### 2026-10-04 - M2.1 - RE1 Online Boutique downloaded
- What was done: `experiments/download_rcaeval.py`, a thin wrapper over RCAEval's own download
  helpers, and RE1 Online Boutique fetched with it into `data/RCAEval/RE1/RE1-OB`. The RCAEval
  virtual environment was already built while settling open question 1, so that half of the task
  was done.
  - A script rather than a shell command, so getting the data is a recorded step someone can repeat
    rather than something done once at a prompt. It handles all ten RE1/RE2/RE3 datasets, skips one
    that is already present, and reports free disk before starting.
- The API was read, not guessed (hard rule 9): `RCAEval.utility` exposes
  `download_re1ob_dataset(local_path=None)`, which pulls
  `https://zenodo.org/records/14590730/files/RE1-OB.zip`, unpacks it and deletes the archive. Two
  behaviours worth knowing, both read from the source: it returns immediately if the target folder
  exists, and it writes its temporary zip into the **current working directory**, which is why the
  wrapper changes directory to the data folder first rather than leaving a 31 MB file in the project
  root.
- What arrived, confirmed rather than assumed:
  - 31 MB compressed, **175 MB unpacked, 250 files**. Much smaller than feared - RE1 is metrics only.
  - **125 cases**: 25 folders named `{service}_{faulttype}`, each holding 5 numbered runs.
  - 5 services: `adservice`, `cartservice`, `checkoutservice`, `currencyservice`,
    `productcatalogservice`.
  - 5 fault types: `cpu`, `delay`, `disk`, `loss`, `mem`.
  - Each run folder holds `data.csv` (about 2.7 MB) and `inject_time.txt` (10 bytes).
  - That is a quarter of RE1's 375 cases, which is right: the other two systems are Sock Shop and
    Train Ticket.
  - The temporary archive was cleaned up, and `data/` is git-ignored, so none of this is committed
    (hard rule 11). Disk went from 23.7 GB to 22 GB free.
- How it was tested (commands + result): the download reported 250 files and 175 MB; the folder tree
  was listed to confirm the shape above; `find data -name "*.zip"` found nothing left behind;
  `git check-ignore` confirmed the data cannot be committed.
- **Deliberately not done here**: reading the CSV columns, the inject-time format or how ground truth
  is labelled. `07` M2.2 says to inspect those and write the findings in this file **before** writing
  the adapter, and that is the next task rather than this one.
- Files changed: new `experiments/download_rcaeval.py`; `docs/08_EXPERIMENTS_SPEC.md` (section 2 now
  names the script), `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M2.2, the inspection.

### 2026-10-04 - Closing the M1.10 leftover: the two slow engines, re-measured
- What was done: `SHAP_IFOREST` and `PARE_LGBM` were re-run through the synthetic check with the
  corrected rank measurement and the graph-free baselines, so the result file now covers **all eight
  engines over 3,200 cases** rather than six. The gate was re-checked on the merged file and still
  passes, unchanged.
  - To make that possible the script gained `--append`: it keeps the per-case rows already in the
    output directory for engines it is not running, and re-summarises everything together. The full
    grid takes longer than a single background run is allowed, and the alternative was leaving the
    canonical result file permanently incomplete. Re-running an engine **replaces** its rows rather
    than adding to them, so a repeat run refreshes instead of double-counting. Decision 54.
- **`SHAP_IFOREST` was unaffected by the bug**, which is worth knowing rather than assuming: its
  numbers came back identical to the first run. The rank bug only ever touched engines that use the
  graph traversal, and `SHAP_IFOREST` does not. Its M1.8 figures stand.

  The headline C1 number survives at scale: its **symptom rate is 1.0** on latency, cpu and error -
  every single wrong answer blames a caller of the real culprit rather than an unrelated service,
  now over 400 cases rather than 15.
- **`PARE_LGBM` was affected, and my M1.7b report of it was wrong.** I reported it as five points
  behind ridge at amplification 0.25 and fifteen behind at 0.50 on service accuracy. That was the
  broken measurement penalising the traversal. Corrected over 400 cases:

  | fault | amp | AC@1 ridge / lgbm | ExpAC@1 ridge / lgbm |
  |---|---|---|---|
  | cpu | 0.0 / 0.25 | 1.00 / 1.00 | 0.76 / 0.64 |
  | error | 0.0 / 0.25 | 1.00 / 1.00 | 1.00 / 0.66 |
  | latency | 0.0 | 1.00 / 1.00 | 1.00 / 0.68 |
  | latency | 0.25 | 0.94 / 0.90 | **1.00 / 0.22** |
  | mem | 0.0 / 0.25 | 0.90 / 0.90 | 0.78 / 0.54 |

  Mean across all settings: service accuracy is effectively identical, indicator accuracy falls from
  **0.89 to 0.58**, and it is about **9 times slower**.

  This is a sharper finding than the one it replaces, and it fits the extrapolation limit found in
  M1.6 better. A tree ensemble cannot extrapolate, so its residuals are distorted in **magnitude**.
  Magnitude is what orders the columns inside a service, so the indicator ranking is scrambled -
  while the question of *which service* is carried largely by the graph traversal and survives. The
  ablation's real message is therefore: swapping the linear dependency model for a non-linear one
  costs you the answer to "which metric", which is the question an engineer actually asks, and buys
  nothing.
- How it was tested (commands + result):
  - `python scripts/synthetic_check.py --engines SHAP_IFOREST --append` (137 s) then
    `--engines PARE_LGBM --append` (361 s). `config.json` records which engines each run touched and
    how many rows were carried forward.
  - `pytest -q` -> all tests pass, including four new ones for `--append`: that per-case rows survive
    a CSV round trip with their types intact, that an absent value comes back as `None` rather than
    `0` (reading it as 0 would turn "the method never named it" into "it came first"), and that
    re-running an engine replaces its rows instead of duplicating them.
  - The gate on the merged file is identical to the six-engine run, as it must be: the two engines
    added are not part of it.
- A caveat on the timings in the result file: these runs used every core, so the per-case
  milliseconds are inflated by contention and are **not** comparable with the single-run figures in
  `05` section 7. Use them to compare engines with each other, not against the 2-second budget.
- Files changed: `analyzer/scripts/synthetic_check.py` (`--append`, `read_cases`),
  `analyzer/tests/test_synthetic_check.py`, `docs/05_PYTHON_ANALYZER_SPEC.md` (the corrected
  `PARE_LGBM` note), `PROGRESS.md`. The result files under `experiments/results/` are git-ignored by
  design.
- Left open / next: M2.1. Nothing from M1 is outstanding now.

### 2026-10-04 - Settling open question 1: RCAEval without PyTorch
- What was done: established, by building the environment rather than by reading dependency lists,
  that RCAEval can be installed **without PyTorch**, so hard rule 1 needs no exception. The
  environment is built and pinned at `experiments/requirements-rcaeval.txt`.
- How it was established:
  - `pip install RCAEval[default]` does require `torch>=1.12.1`, which is what raised the question.
    But the base package declares **no** dependencies at all - all 414 are behind extras - so the
    extra is a convenience, not a requirement.
  - Inspecting the wheel without installing it: only **four** modules in the whole package import
    torch (`e2e/causalrca.py`, `e2e/mscred.py`, `e2e/run.py`, `graph_construction/cmlp.py`).
  - `RCAEval/e2e/__init__.py` imports each method inside a `try/except: continue`, with a comment
    saying exactly this: "A method whose dependencies are not installed (e.g. torch ...) is skipped
    instead of breaking the whole package".
  - So the environment was built that way and checked. With **no torch installed**:

    | method | available |
    |---|---|
    | `nsigma`, `mmnsigma` | yes |
    | `baro` | yes |
    | `e_diagnosis` (epsilon-Diagnosis) | yes |
    | `circa` | yes |
    | `rcd` | yes |
    | `pc_pagerank` | yes |
    | `microcause` | yes |
    | `causalrca` | no - imports torch |
    | `mscred` | no - imports torch |

  - Every baseline named in `00_RESEARCH_PLAN.md` section 8.1 - NSigma, BARO, epsilon-Diagnosis,
    CIRCA, RCD, PC-PageRank, MicroCause - is in the available group. **Nothing the plan asks for is
    lost.**
- Two other things the investigation disposed of:
  - The `default` extra also pins `networkx==2.5`, a 2020 release. Not needed either: the methods
    above run on networkx 3.4.2.
  - The separate virtual environment is **still required**, for a different reason than torch:
    RCAEval needs `numpy<2` (it installed 1.26.4) while the analyzer uses numpy 2.2.6. Those cannot
    share an environment.
- What it costs: CausalRCA and MSCRED cannot be run. Both are deep models, and neither appears in the
  plan's baseline list - CausalRCA is mentioned only in section 2.2 as a method that *struggles* on
  larger systems. They are out of scope **by rule rather than by accident**, and the paper should say
  so plainly rather than leave a reader wondering.
- How it was tested (commands + result):
  - `experiments/.venv-rcaeval` built on Python 3.10, 46 packages, about 420 MB.
    `uv pip freeze` contains **zero** packages matching `torch` or `tensorflow`.
  - `import RCAEval.e2e` succeeds and exposes 44 callables; the availability table above was read off
    the live module, not inferred.
  - `.gitignore` gained `.venv-*/`, because `.venv/` does not match `.venv-rcaeval` and the
    environment would otherwise have been committed.
- Files changed: new `experiments/requirements-rcaeval.txt`; `.gitignore`,
  `docs/08_EXPERIMENTS_SPEC.md` (section 2 now carries the torch-free install recipe and the table),
  `PROGRESS.md`.
- Left open / next: M2.1 proper - downloading RE1 Online Boutique. The environment it needs now
  exists.

### 2026-10-04 - M1.11 - the samples the Java side will be built against. M1 is done.
- What was done: `analyzer/samples/` now holds `analyze_request.json` and the matching
  `analyze_response_pare.json` and `analyze_response_nsigma.json`, generated by
  `analyzer/scripts/make_samples.py`. These are the fixtures `03` section 4.4 needs: the Java
  `FallbackRanker` must rank services exactly as Python `NSIGMA` does, and that test means nothing
  without something concrete sitting between the two languages.
  - The case is 5 services, 25 columns, 150 normal rows and a 120-row recent window that straddles
    the fault, from `pare.synthetic` with seed 42. Ground truth is **not** in the request.
  - Serialisation was added to `engine.py` as `AnalyzeRequest.to_api_dict` / `from_api_dict` and
    `AnalyzeResult.to_api_dict`, rather than written inside the script. Decision 52.
- Three details that would each have caused a confusing Java-side failure later:
  - **The data is rounded before the answers are computed, not after.** Java reads the rounded
    numbers out of the JSON. Had we scored full-precision values and rounded them for the file, Java
    would be computing from slightly different inputs than the stored answers came from, and the
    agreement test would drift with nothing visibly wrong.
  - **Some readings are deliberately `null`.** The contract says a missing number is `null`, never 0
    and never the string "NaN". The fixture contains four, and a test asserts the strings `NaN` and
    `Infinity` never appear in the file.
  - **`tookMs` is stored as `null`.** It is machine-dependent and would make the files churn on every
    run while telling a test nothing. `03` section 4.4 now says not to assert on it.
- How it was tested (commands + result):
  - `pytest -q` -> **364 passed** (12 new) in 19 s. `ruff check .` -> clean.
  - The test that earns its keep is `test_rerunning_the_engine_reproduces_the_stored_response`: it
    reads the committed request, runs the engine now, and compares against the committed answer.
    These files are a contract between two languages and the Java side cannot notice when Python
    changes, so without this the agreement test would eventually be checking a stale fixture.
  - Also checked: both files match `06` section 3 field for field, every row has one entry per
    column, ranks run 1..n, the request carries no ground truth, the NSIGMA response has
    `score == marginalScore` with nothing inherited or explained, the PARE response contains the
    roles and change point the Java renderer needs, and regenerating produces byte-identical files.
  - The request is 69 KB rather than 132 KB because the generator keeps each row of readings on one
    line. One line is one moment in time, which is also far easier to read.
- **M1 is complete.** All eleven tasks are ticked, the gate passed on 50 seeds, and the engine runs
  end to end from a JSON request to a JSON answer.
- Files changed: new `analyzer/scripts/make_samples.py`, `analyzer/tests/test_samples.py`,
  `analyzer/samples/` (4 files); `analyzer/pare/engine.py` (serialisation),
  `docs/03_JAVA_BACKEND_SPEC.md`, `docs/07_TASKS.md`, `PROGRESS.md`.
- Left open / next: M2.1, setting up RCAEval and downloading RE1 Online Boutique. Two things are
  waiting there: the PyTorch question in open question 1, which finally matters, and a long run of
  `SHAP_IFOREST` and `PARE_LGBM` through the synthetic check, whose M1.8 figures are superseded.

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

    > **These service-level numbers are WRONG and are kept only for the record.** They were produced
    > with the rank measurement that M1.10 later found to be broken, which penalised any engine using
    > the graph traversal - and `PARE_LGBM` uses it. Corrected on 2026-10-04 over 400 cases:
    > `PARE_LGBM`'s service accuracy is **the same** as ridge's, not worse. What it really costs is
    > indicator accuracy and time. See the 2026-10-04 entry.

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

9. ~~**A column with no robust scale is scored by dividing by the epsilon guard, and it wrecks PARE on
   real data.**~~ **SETTLED on 2026-10-05** - decision 72, option (a). When the MAD is 0 but the column
   is not constant, the scale is now the standard deviation; the epsilon is back to doing only the job
   it was written for. PARE's AC@1 on RE1-OB rises **0.240 -> 0.384** and Avg@5 **0.410 -> 0.528**.
   Option (b), dropping the column, scored marginally higher (0.400) and was rejected on principle: a
   metric that is flat while nothing is wrong and then climbs is exactly what a memory leak looks
   like, and two cases in 125 is not a reason to make the method blind to its own motivating example.
   Written into `05` section 3 steps 1 and 3, and into `03` section 4.7 for the Java detector, which
   has the same formula and would have had the same defect.

   <details>
   <summary>the question as originally raised, and the measurements that settled it</summary>

   Raised by M2.5. `05` section 0 drops a column when "MAD == 0 **and** std == 0". A
   column that is flat over most of the normal period but not entirely flat therefore survives with
   MAD == 0, its scale becomes the epsilon (about 1e-6 x (|median| + 1)), and any move at all scores
   in the millions - one case ranks `paymentservice_load` first at 4,000,000.

   Measured on RE1-OB: **108 such columns across 40 cases** (mem 61, error 24, latency 15, load 8),
   and **the rank-1 column has MAD == 0 in 34 of 125 cases**. Removing them before the engine lifts
   PARE's AC@1 from **0.240 to 0.400** and Avg@5 from 0.410 to 0.544. Synthetic data cannot produce
   this, which is why M1 never saw it.

   This is not a bug against the spec - the code does exactly what `05` says - so it is a decision
   about the method, and it changes every number E1 to E4 will produce. Options:

   a. **Fall back to the standard deviation when MAD is 0.** Keeps the column and scores it on the
      only scale it has. Preserves information, and matters because a MEM fault's ground-truth
      indicator could itself be flat in normal - dropping it would make that case unsolvable by
      construction. Costs the method its purely-robust character for those columns, which has to be
      said in the paper.
   b. **Drop the column, widening the existing rule to "MAD == 0" alone.** Simplest, and it is what
      was measured above (0.240 -> 0.400). Risks discarding a column that is the real answer; worth
      measuring how often the ground-truth indicator is one of them before choosing this.
   c. **Scale the epsilon to the data** rather than to the median, for example a small fraction of the
      column's standard deviation. A smaller change than (a) with much the same effect, but it makes
      the epsilon meaningful rather than nominal, which is arguably what it should always have been.

   Recommendation: **(a)**, with the fallback recorded in `warnings` so a user of the application can
   see it happened, and with (b) reported as an ablation since it is one line and the comparison is
   cheap. Reason: (a) is the standard remedy, it cannot make a case unsolvable the way (b) can, and it
   leaves the epsilon doing the job it was written for - preventing division by zero - rather than
   silently setting the scale.

   **Blocking M3.1.** Every E1 and E2 number depends on it, so it should be settled before the first
   experiment runs rather than after.

   **How the options actually measured**, 125 cases, PARE and three other engines (the full table is
   in the 2026-10-05 question-9 log entry):

   | option | PARE AC@1 | PARE Avg@5 |
   |---|---|---|
   | as the spec said | 0.240 | 0.410 |
   | (a) standard deviation when MAD is 0 | **0.384** | **0.528** |
   | (b) drop the column | 0.400 | 0.544 |
   | (c) epsilon from the standard deviation | 0.280 | 0.427 |

   (c) is clearly the weakest and was dropped. (a) and (b) differ by two cases in 125, which is not a
   basis for a methodological choice, so the decision was made on what each one does when it is wrong:
   (b) discards a column before ranking, so it can silently throw away the right answer, while (a) at
   worst scores it less robustly. The ground-truth indicator is never a flat column anywhere in RE1-OB,
   so (b) happens to cost nothing *here* - but that is a property of this dataset, not a safety
   guarantee, and the application lets users upload their own data.
   </details>

1. ~~**RCAEval pulls PyTorch.**~~ **SETTLED on 2026-10-04** - decision 53. It does not have to.
   `RCAEval[default]` pulls torch, but the bare package plus the dependencies the wanted baselines
   actually import does not, and RCAEval skips any method whose dependencies are missing. Every
   baseline the research plan names works without torch. **Hard rule 1 stands unchanged, unamended
   and unbroken.** Full detail below; the original question is kept for the record.

   <details>
   <summary>the question as originally raised</summary>
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
   </details>

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

5. ~~**A memory fault is weaker than the spec's `8 * std` suggests.**~~ **SETTLED on 2026-10-05** -
   decisions 62 and 63. The observation was right and the first measurement was for a half-window;
   over the whole abnormal period the effective size is **4.0 stds**, and at the M1.10 gate's
   settings (`n_abnormal=200`, `delay_s=30`) it is **2.4**. Nothing is changed in the generator or in
   `min_cause_score`: a ramp caught early genuinely is thin evidence, and refusing to accuse on 2.4
   MADs is what `min_cause_score` is for. What was wrong was the **spec**, which quoted a peak as if
   it were what the scorer sees; it now states both, with the measured table. A second problem the
   measurement turned up - the effective size depends on `n_abnormal`, so two runs differing only in
   run length do not inject the same fault - is handled by a stated constraint on E6 rather than a
   new knob. Four tests pin all of it.

   <details>
   <summary>the question as originally raised</summary>
   The ramp reaches `+8 * std` only at the last abnormal row, so the median over the analysis window
   is about half of that; measured, the culprit's memory column deviates about **1.9 stds**, not 8.
   `PareConfig.min_cause_score` is 3.0, so on current numbers a memory case could come back
   `NO_CLEAR_CAUSE`. Worth revisiting together with question 3, since both are about how strong an
   injected fault should be. Not blocking M1.3.
   </details>

6. ~~**Which metric counts as the ground-truth indicator for DISK, DELAY and LOSS faults?**~~
   **SETTLED on 2026-10-05** - decision 64, written into `08` section 4 ("Which indicator counts as
   correct") and `06` section 5. Option (b) for the headline, (a) as a secondary table, **reported per
   fault type with the size of the acceptable set, never pooled.** The one thing that was missing when
   the recommendation was first written has now been checked: for CPU and MEM the acceptable set holds
   exactly one metric, so **the loose and strict scores are identical on every case the strict number
   covers** (verified on all 350 scored rows, and pinned by three tests). That removes the
   cherry-picking worry raised below - the 0.92 against 0.784 gap is entirely a difference in which
   cases are included, not in how any case is scored. Per fault type the secondary table reads: CPU
   0.96 (1 acceptable), MEM 0.88 (1), DELAY 0.88 (3), DISK 0.80 (4), LOSS 0.40 (3).

   <details>
   <summary>the question as originally raised, with the measurements that settled it</summary>

   Raised by M2.2. `08` section 3 says to take the fine-grained ground truth from RCAEval's own
   evaluation code if it exists, and otherwise to pick a mapping and document it as an assumption.
   **It does not exist in the installed package**: the shipped `Evaluator` compares `Node(entity,
   metric)` objects but the code that builds the ground-truth node for a case is not in the wheel.
   So the assumption is ours to make, and it is not obvious, because two of the five fault types have
   no corresponding metric at all - there is no `disk` column and no `loss` column anywhere in
   RE1-OB.

   What the data says. For each case, the robust z of the broken service's own metrics, abnormal
   window against normal, 125 cases:

   | fault | metric that moves most | reading |
   |---|---|---|
   | CPU | `cpu` 25/25 | unambiguous |
   | MEM | `mem` 18/25, `latency` 7/25 | clear enough; the runner-up is the service slowing down, which is the same effect we built into the synthetic generator |
   | DELAY | `latency-90` 14/25, `latency-50` 11/25 | a latency column, but **never plain `latency`** - it splits between the two percentiles |
   | LOSS | `latency-90` 14/25, `latency-50` 9/25, `mem` 2/25 | same shape as DELAY |
   | DISK | `cpu` 10/25, `latency-90` 10/25, `latency-50` 4/25, `mem` 1/25 | **no clear answer at all** |

   Options:
   a. **Accept a set of indicators per fault type.** CPU -> `{svc}_cpu`, MEM -> `{svc}_mem`,
      DELAY and LOSS -> any of the service's latency columns, DISK -> any of cpu or latency. ExpAC@k
      counts a hit if the top indicator is in the accepted set. Honest, uses all 125 cases, but
      makes ExpAC@k easier for the fault types with a larger accepted set, which must be said.
   b. **Report indicator-level accuracy only for CPU and MEM**, where the answer is unambiguous, and
      report service-level accuracy for all five. Cleanest claim, uses 50 of 125 cases for the
      indicator metric.
   c. Something else.

   Recommendation: **(b) for the headline ExpAC@k, with (a) reported alongside as a secondary
   table.** The paper's contribution C1 is about whether explanations point at the right *indicator*,
   so that number has to rest on cases where "right" is not a judgement call. Reporting (a) as well
   keeps all 125 cases visible and lets a reader see the effect of the looser definition. Either way
   the choice must be stated in the paper, because it moves the numbers.

   **How much it moves them, measured in M2.4.** ExpAC@1 for our `NSIGMA` on RE1-OB is **0.92**
   under the strict definition (b), over the 50 CPU and MEM cases, and **0.784** under the loose
   definition (a), over all 125. Their NSigma: 0.74 strict, 0.68 loose. So the two readings differ by
   about 14 points for us and 6 for them, and the strict definition is the more flattering one for
   both. That asymmetry is itself a reason to report both: picking (b) alone would look like
   cherry-picking the higher number, and the honest framing is that (b) measures a cleaner question
   on fewer cases.

   **Why that last worry turned out to be unfounded.** The acceptable set for CPU is `{cpu}` and for
   MEM is `{mem}` - one member each - so on those 50 cases the loose rule and the strict rule score
   every case identically. Checked on all 350 scored rows of the M2.4 run: the strict and loose ranks
   agree everywhere both are defined. So (b) is not (a) with the scoring tightened; the two differ
   only in which cases they cover. The remaining asymmetry is just that CPU and MEM are also the
   easiest fault types at service level (AC@1 0.96 and 1.00 against 0.48 for LOSS), which the
   per-fault table shows rather than hides.
   </details>

7. ~~**Disk space.**~~ **SETTLED on 2026-10-05** - decision 66, as a standing policy rather than a
   one-off answer. Re-measured today: **23.4 GB free** of 237.7 GB. What the project occupies now:
   `analyzer/.venv` 663 MB, `experiments/.venv-rcaeval` 136 MB, `data/RCAEval` 168 MB - about 1 GB in
   total, so RE1-OB was never the problem. The policy: **one RCAEval system on disk at a time**, which
   `08` section 2 already advises for memory, and delete a system's folder before downloading the
   next. `download_rcaeval.py` skips a dataset that is already present, so re-fetching after a delete
   is one command. Re-check free space before any RE2 or RE3 download, since those carry logs and
   traces and are the only items that could plausibly fill the disk. No longer tracked as a question.

8. ~~**`.gitignore` does not do what `docs/08` section 1 says about results.**~~ **SETTLED on
   2026-10-05** - decision 65, option (a). `.gitignore` now tracks the small per-run files
   (`summary*.csv`, `comparison.txt`, `agreement.txt`, `config*.json`, `env-*.txt`) and still excludes
   the per-case ones (`cases.csv`, `indicator_scoring.csv`, `*.jsonl`), which are hundreds of
   kilobytes and regenerate. Reason: PROGRESS.md and the paper quote the summaries, so a reader with a
   fresh clone should be able to check them without downloading the benchmark; the churn argument does
   not survive the file sizes, which are 1 to 3 KB. This retroactively brings M1.10's
   `synthetic_check/summary.csv` into the repository as well, which is the intended effect.

The 16 points raised in the first spec review were all answered on 2026-10-03 and are recorded
under "Decisions made" below. **Every open question is now settled**; the gates under "Things the
human must check by hand" are judgement calls for the human rather than questions for the project.

## Things the human must check by hand
- **Static call graphs in `experiments/graphs/*.yaml` (M2.5) - ready for you now.** Both files are
  written to be checked: each records the repository, version and date it came from, and for Sock Shop
  the specific source file behind every single edge. What to look at:
  - `online-boutique.yaml`: 15 edges, every one a `*_ADDR` environment variable in the app's own
    Kubernetes manifest at v0.7.0 (the version running when the data was collected). Two judgement
    calls to approve or reject: `redis-cart` is renamed to `redis` to match the data, and
    `loadgenerator` is excluded because it appears in no column. Automatically verified against all
    125 cases, so the names are known to match.
  - `sock-shop.yaml`: 15 edges over all 14 services. **Not yet verified against data**, because RE1-SS
    is not downloaded. Sock Shop declares no dependencies in its manifests, so every edge was read out
    of a service's source; the two worth a second look are `orders -> user` and `orders -> carts`,
    which happen through URLs that front-end passes in a request body rather than hostnames in the
    orders source.
  - Both files leave the Istio telemetry entries (`frontend-external`, `PassthroughCluster` and
    friends) and `main` with no edges, on the principle that an invented edge is worse than a missing
    one. `frontend-external -> frontend` is probably a real edge. Measured consequence: those services
    never actually won a ranking in the 125-case run, so the cost appears to be nil - but it is a
    judgement call you may want to overrule.
- Ground-truth indicator mapping for RCAEval - **investigated in M2.2, now open question 6**. CPU
  and MEM are settled by the data; DISK, DELAY and LOSS need a human decision
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

### M1.11 choices

52. **The contract serialisation lives in `engine.py`, not in the sample script or the service.**
    `AnalyzeRequest.to_api_dict` / `from_api_dict` and `AnalyzeResult.to_api_dict` produce the shapes
    in `06` section 3.
    Reason: the samples, the FastAPI service at M7.1 and anything else that speaks the wire format
    must agree exactly. Writing it in the script would have meant a second implementation at M7.1
    and the possibility of the committed fixtures no longer matching what the service sends - a
    difference the Java side could not detect. The pydantic models will validate this shape rather
    than define it again.

### Settling open question 1

53. **RCAEval is installed without PyTorch, and hard rule 1 is left exactly as written.**
    Not `RCAEval[default]`, which pulls torch, but the base package plus the dependencies its
    non-deep methods actually import. RCAEval skips any method whose dependencies are missing, by
    design and with a comment saying so.
    Reason: the question was framed as "may we break hard rule 1 inside an isolated environment",
    and the honest answer turned out to be that we do not need to. Every baseline the research plan
    names runs without torch; only CausalRCA and MSCRED are lost, both deep models that the plan
    never asked for. Weakening a stated rule when the rule costs nothing would have been the wrong
    trade - and the environment is pinned in `experiments/requirements-rcaeval.txt` so the claim
    stays checkable rather than becoming folklore.

### Closing M1.10

54. **The synthetic check can build its result file in pieces (`--append`).** Rows already present
    for engines not being run are kept and re-summarised with the new ones; re-running an engine
    replaces its rows.
    Reason: the full eight-engine grid takes longer than one background run is allowed, and the
    alternative was a canonical result file that permanently omitted the two slow engines. Replacing
    rather than appending per engine means a repeated run refreshes a result instead of silently
    weighting that engine twice in the summary.

### M2.3 choices

55. **The adapter does not import RCAEval.** It reads the CSV files directly with pandas.
    Reason: the data is plain CSV, and importing RCAEval would force every experiment into the
    separate `.venv-rcaeval` environment, which cannot also hold `pare` because RCAEval pins
    numpy 1.x against the analyzer's 2.x. Keeping the adapter dependency-free lets the loading, the
    engines and the metrics all live in one process. RCAEval is still needed for the download script
    and for running their baselines in M2.4, which is a separate step.

56. **`gt_indicator` is None for DISK, DELAY and LOSS rather than a guess.** The adapter also exposes
    `acceptable_indicators` with the full candidate set.
    Reason: RE1-OB has no `disk` and no `loss` metric, and M2.2 measured that DISK splits roughly
    evenly between `cpu` and the latency percentiles. Any single choice would be an invention
    presented as data. Leaving it None forces an experiment to state which definition it is using,
    which is exactly the decision open question 6 is waiting on.

### M2.4 choices

57. **Their half and our half are separate scripts, and their half never reads the ground truth.**
    `run_rcaeval_baselines.py` records only the ranking; all scoring happens in
    `run_m24_compare.py`.
    Reason: the two environments cannot be joined (numpy 1.x against 2.x), so a split was forced.
    Given that, putting every scoring decision on one side means there is one ground-truth mapping
    and one definition of each metric rather than two that could drift. It also makes hard rule 4
    mechanical instead of a matter of care: a file that never reads the answer cannot leak it, and
    a test asserts the recorded JSON carries no ground-truth key.

58. **Their formulas are re-implemented as well as called.** `baseline_formulas.py`.
    Reason: a reproduction only needs their code, but *explaining* a difference needs their formula
    and ours applied to the same window, which one process cannot do across two environments.
    The re-implementation is validated against their real output on all 125 cases - identical top-1
    on 125, identical accuracy to four decimals - and the script prints that check before the
    attribution, so a future RCAEval release that changes the method makes the check fail loudly
    instead of quietly invalidating the table.

59. **Their sort is reproduced, NaN bug included, and used for every ladder cell.**
    Reason: replacing it with a correct sort would hide a real property of the published baseline
    (finding 1 in the M2.4 log entry). Using it for our cells too costs nothing, because our formula
    never returns NaN, and it holds the sort fixed so that the formula step of the ladder measures
    the formula alone.

60. **Two service-level conventions are both reported, neither is called the answer.**
    Their `Evaluator` reads AC@k off the top k *columns* without removing repeats; the rest of this
    project ranks distinct services. Columns `ac3_raw` / `avg5_raw` are theirs, `ac3_distinct` /
    `avg5_distinct` are ours.
    Reason: at k=1 the two are identical, so the headline comparison is unaffected; above it theirs
    is stricter. Quietly picking one would move the numbers for a reason that has nothing to do with
    method quality. A test pins the case where they differ.

61. **`cases.csv` stays exactly as `docs/06` section 5 defines it; the loose indicator scoring goes
    in `indicator_scoring.csv`.**
    Reason: open question 6 is not settled, so neither definition should be written into the
    contract yet. When it is settled, `docs/06` and the writers change once, deliberately, rather
    than the contract having grown an extra column by accident (hard rule 6).

### Settling open questions 5, 6, 7 and 8

62. **The synthetic MEM fault keeps its current definition, and `min_cause_score` stays 3.0.**
    What changes is `05` section 5, which now states the effective size as well as the peak, with the
    measured table.
    Reason: the spec quoted `8 * std`, which is the ramp's peak at the final abnormal row, while every
    score in the project is a **median** over a window - and the median of a linear ramp is half its
    peak. Measured: 4.0 stds over a 120-row abnormal period, 2.4 at the gate's 200. So the
    discrepancy was in the description, not the behaviour. Making the fault bigger would make MEM
    artificially easy and would break the reproducibility of every synthetic result so far; lowering
    `min_cause_score` would make the method accuse services on thinner evidence, which is the
    opposite of what that parameter is for. `NO_CLEAR_CAUSE` on a ramp caught early is the correct
    answer, and it is reported as its own column rather than silently counted as a wrong one.

63. **`n_abnormal` is held fixed across any settings being compared.** Recorded as a constraint on E6
    in `08` section 4, not as a new parameter.
    Reason: because the ramp peaks at the last abnormal row, the fault's effective size in a fixed
    analysis window shrinks as `n_abnormal` grows - so two runs differing only in run length do not
    inject the same MEM fault. A `ramp_rows` parameter would decouple them, but E6 varies graph size,
    propagation, amplification, noise, graph quality and delay and **not** `n_abnormal`, so the knob
    would buy comparability nothing needs while adding a way to get results wrong. Two tests pin the
    dependence, and two more pin that step faults (cpu, latency, error) do not share it.

64. **Headline ExpAC@k is strict; the loose number is secondary, per fault type, never pooled.**
    `08` section 4 "Which indicator counts as correct"; `06` section 5 gains
    `rank_gt_indicator_loose` and `tied_gt_indicator_loose`.
    Reason: contribution C1 is about whether an explanation names the right *metric*, so the headline
    has to rest on cases where "right" is not a judgement call - CPU and MEM, 50 of 125 for RE1-OB.
    Pooling the loose score would average a 1-of-51 question (CPU accepts one metric) with a
    4-of-51 one (DISK accepts four) into a number with no meaning, which is why the secondary table
    carries the acceptable-set size in its own column. The decisive check, missing when this was first
    recommended: for CPU and MEM the acceptable set has one member, so strict and loose score those
    cases identically - verified on all 350 rows of the M2.4 run and pinned by three tests - which
    means the gap between the two headline numbers is purely case selection and the strict number is
    not the loose one with the rules bent.

65. **The small per-run result files are committed; the per-case ones are not.**
    Reason: `08` section 1 already said "git-ignored except small summary CSVs" and `.gitignore` did
    not implement it, so numbers quoted in PROGRESS.md and destined for the paper were unverifiable
    from a fresh clone. The churn objection does not survive the sizes: `summary.csv` is 788 bytes and
    `comparison.txt` 2.4 KB, against 137 KB for `cases.csv` and 384 KB for the rankings JSONL, which
    stay out and regenerate. Note the `.gitignore` subtlety this needed: un-ignoring a run folder
    re-exposes everything inside it, so the contents are re-ignored by `experiments/results/*/*`
    before the small files are allowed back.

66. **One RCAEval system on disk at a time, re-check free space before RE2 or RE3.**
    Reason: the measurement closed the question rather than a judgement did. The whole project
    occupies about 1 GB (`analyzer/.venv` 663 MB, `.venv-rcaeval` 136 MB, `data/RCAEval` 168 MB)
    against 23.4 GB free, so RE1 was never a risk. Only RE2 and RE3, which carry logs and traces, can
    plausibly fill the disk, and `08` section 2 already advises taking one system at a time for memory
    reasons - the same policy covers both. `download_rcaeval.py` skips what is already present, so
    deleting a system and re-fetching it later is one command.

### M2.5 choices

67. **Edges come from machine-readable declarations, never from an architecture diagram.**
    Online Boutique from the `*_ADDR` environment variables in its Kubernetes manifest; Sock Shop from
    the source file that holds each hard-coded hostname.
    Reason: a diagram is a PNG and reading one is guessing, which hard rule 9 forbids for library APIs
    and which is no more acceptable for the input the whole method depends on. The manifest is also
    version-pinnable, which a diagram is not.

68. **Online Boutique is pinned to v0.7.0, the version running when the data was collected.**
    Reason: every RE1-OB case was injected in the week of 2023-05-28, and v0.7.0 was released
    2023-05-19. The choice turns out not to matter, which was checked rather than assumed: v0.8.0
    yields an identical edge list, and v0.10.7 differs only by a service that appears in no column of
    the data. Recording the reasoning anyway, so nobody has to redo the check.

69. **Istio telemetry entries and `main` are left with no edges.**
    `frontend-external`, `PassthroughCluster`, `InboundPassthroughClusterIpv4`, `frontend-check`.
    Reason: no manifest declares them, so any edge would be invented, and `frontend-external ->
    frontend` - the tempting one - would be a guess however likely. The cost is real and is stated in
    the file: with no children a service's self-score equals its marginal score, so a symptom there can
    look self-originated. Measured over 125 cases, none of them ever won a ranking, so the cost appears
    to be nil in practice. Flagged for the human to overrule if they disagree.

70. **A graph is validated against the services the engine sees, not against the CSV headers.**
    Reason: the first version of the check failed on `carts`, `catalogue`, `orders` and `front-end` -
    the Sock Shop columns contaminating one RE1-OB case - which the adapter already drops. A graph that
    does not mention columns no engine receives is not incomplete, so the check filters by the same
    allowlist the adapter uses. Validating against raw headers would have meant either a permanently
    failing check or a graph padded with entries for data artefacts.

71. **`check_graph.py` refuses to measure a graph that does not match the data.**
    Reason: the failure this guards against is silent. A name mismatch makes `children()` return
    nothing for every service, so PARE degrades into a robust-z method and still produces plausible
    numbers. Refusing to proceed turns the worst kind of bug - one that only shows up as slightly
    disappointing accuracy months later - into an error message.

### Settling open question 9

72. **A column whose MAD is 0 but which is not constant is scored on its standard deviation.**
    In `pare.scores.robust_baseline`, the one place the epsilon rule lives. Written into `05` section 3
    steps 1 and 3, and into `03` section 4.7 so the Java detector inherits it.
    Reason, in order of weight:
    - The old behaviour was **meaningless, not merely suboptimal**. With MAD 0 the scale became the
      epsilon, about 1e-6, so the "robust z" was a raw deviation divided by a millionth. A score of
      4,000,000 is not a z-score. That alone justifies the change regardless of accuracy, and it is why
      this is a repair rather than tuning.
    - **The alternatives did not separate on accuracy**, so the choice had to rest on something else:
      (a) 0.384, (b) 0.400, (c) 0.280, against 0.240 as specified. Two cases in 125 between the two
      serious options.
    - **(b) can silently discard the right answer.** It drops the column before ranking. A metric that
      is flat while nothing is wrong and then climbs is exactly a memory leak, which is this project's
      own motivating example, and `mem` is the most common flat column in RE1-OB. (a)'s failure mode is
      a less-robust score on a minority of columns, which is visible, bounded and reported in
      `warnings`. Preferring the bounded failure over the silent one is the whole reason this project
      has a verdict rule and a leakage test.
    - **(a) leaves every other number exactly as it was.** Any column with a non-zero MAD keeps the
      scale it had, bit for bit, so no result produced before today moves. A test asserts it. (c) would
      have perturbed every score slightly for a smaller gain.
    - The cost, which the paper must state: those columns are no longer scored robustly. The standard
      deviation is the only spread estimate such a column has.
    No knob was added for (b). Decision 63 argued against knobs that no planned experiment needs, and
    nothing in `08` asks for this ablation; the measurement above is on record if it is ever wanted.

### M3.1 choices

73. **`symptom_rate` takes the correctness of each answer, not just the symptom flags.**
    `pare.eval_metrics.symptom_rate(errors, top1_correct)`.
    Reason: it was returning 1.0 whenever any symptom error existed, because `symptom_error` is False
    both for a right answer and for one wrong in an unrelated way, and the old code treated "not False"
    as wrong - which left only the True values. One boolean cannot carry three outcomes. The
    alternative was to make `symptom_error` return None for a correct answer, but None already means
    "no graph to judge by" in `docs/06` section 5, and overloading it would move the same ambiguity
    into the stored data. Passing the extra information explicitly keeps the CSV column's meaning
    intact and makes the denominator impossible to get wrong, with `strict=True` on the zip so a
    length mismatch is an error rather than a silent mispairing.
    The existing test asserted the buggy value and its own comment admitted why. Per hard rule 12 the
    question was which of the two was wrong: `docs/08` section 4 and the function's docstring both say
    "symptom errors / wrong top-1", so the code and the test were both wrong and the spec was right.

74. **One shared per-case runner, `experiments/runner.py`, from M3 onward.**
    Reason: every runner needs to load a case, run an engine and reduce the answer to a row of
    `cases.csv`. A copy per script means several implementations of AC@k, and the first time two
    disagreed there would be no way to say which number the paper should print - which is exactly the
    shape of the `symptom_rate` bug this task found. The experiment-specific choices (which engines,
    which delays, how to summarise) stay in each script; only the row-producing core is shared.
    `run_m24_compare.py` keeps its own path, because its ladder and its "their convention" service
    ranks do not generalise, and its numbers are already verified against RCAEval's own output.

75. **A test parses `docs/06` section 5 and asserts the column list matches the code.**
    Reason: hard rule 6 says a format change must update the doc and all sides together. A test that
    reads the doc makes that mechanical instead of a matter of discipline - change one and the other
    fails.

### Order of work

17. **Normal order: research first.** M0 -> M1 -> M2 ... The "application early" shortcut in
    `07_TASKS.md` is not taken.
    Reason (the human's): if the synthetic check in M1.10 or the first RE1 results in M3 do not
    support the cause-versus-symptom story, we need to know that **before** building an application
    around it. So M1.10 and M3.2 are explicit stop-and-report gates.

